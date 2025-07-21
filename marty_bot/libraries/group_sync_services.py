# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
import re
from typing import TYPE_CHECKING, Optional

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import config
from app.enums import SyncStatus
from clients.vaultwarden_client import VaultwardenAction
from libraries.services.outline import (
    _sync_single_outline_collection,
    _remove_user_from_outline_collection,
)
from libraries.services.nocodb import _sync_single_nocodb_base, _remove_user_from_nocodb_base
from libraries.services.vaultwarden import _sync_single_vaultwarden_collection_members
from libraries.services.brevo import _sync_single_brevo_list
from libraries.services.authentik import (
    get_all_authentik_groups_and_user_map,
    _sync_single_authentik_group,
    remove_user_from_authentik_group,
)

# Import client-specific utilities and classes for type hinting
# from clients.mattermost_client import slugify # Removed to avoid potential circular dependency if this slugify is widely used
# Copied slugify directly into this file for now.
# Consider moving slugify to a common utils module.

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient
    from clients.brevo_client import BrevoClient
    from clients.nocodb_client import NocoDBClient
    from clients.vaultwarden_client import VaultwardenClient  # Added VaultwardenClient


from libraries.services.mattermost import slugify, _get_mm_users_for_entity


# Helper function to determine Outline permission (REMOVED as logic is now in _sync_single_outline_collection)
# def _determine_outline_permission(auth_group_name: str, mm_channel_type: str) -> str:
#     ...




def sync_entity_permissions(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],
    brevo_client: Optional["BrevoClient"],
    nocodb_client: Optional["NocoDBClient"],
    vaultwarden_client: Optional["VaultwardenClient"],  # Added VaultwardenClient
    mm_team_id: str,
    base_name: str,
    entity_key: str,
    entity_config: dict,
    all_authentik_groups_by_name: dict,
    email_to_authentik_user_pk_map: dict,
    perform_deletions: bool,
    skip_services: list[str] | None = None,  # Added skip_services
) -> list[dict]:
    """
    Synchronizes permissions for a single entity (e.g., a project, an antenne)
    across Authentik, Mattermost, and Outline.
    Includes deletion logic based on `perform_deletions` flag.
    """
    results = []
    logging.info(f"Processing sync for entity '{base_name}' (type: {entity_key}, deletions: {perform_deletions})")

    std_config = entity_config.get("standard", {})
    admin_config = entity_config.get("admin")
    outline_cfg = entity_config.get("outline", {})
    brevo_cfg = entity_config.get("brevo", {})
    nocodb_cfg = entity_config.get("nocodb", {})
    vaultwarden_cfg = entity_config.get("vaultwarden", {})  # Added Vaultwarden config

    std_auth_group_name = std_config.get("authentik_group_name_pattern", "{base_name}").format(base_name=base_name)
    std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(base_name=base_name)

    std_auth_group_obj = all_authentik_groups_by_name.get(std_auth_group_name)
    if not std_auth_group_obj:  # Group not pre-fetched (e.g. fetch_remote_members=False)
        logging.info(
            f"Authentik group '{std_auth_group_name}' for entity '{base_name}' not in pre-fetched list. Attempting to fetch/create."
        )
        std_auth_group_obj = authentik_client.get_group_by_name(std_auth_group_name)
        if not std_auth_group_obj:
            logging.info(f"Authentik group '{std_auth_group_name}' not found, attempting to create.")
            # Ensure create_group returns the group object or None if failed
            created_group = authentik_client.create_group(std_auth_group_name)
            if created_group:
                std_auth_group_obj = created_group
                # Simulate the structure expected by _sync_single_authentik_group if needed,
                # especially 'users' and 'users_obj' which would be empty for a new group.
                if "users" not in std_auth_group_obj:
                    std_auth_group_obj["users"] = []
                if "users_obj" not in std_auth_group_obj:
                    std_auth_group_obj["users_obj"] = []
                logging.info(f"Authentik group '{std_auth_group_name}' created successfully.")
            else:
                logging.error(
                    f"Failed to create Authentik group '{std_auth_group_name}'. Skipping standard Authentik sync for this group."
                )
        else:
            logging.info(f"Authentik group '{std_auth_group_name}' fetched successfully.")
            # Ensure users and users_obj are present, even if empty, to match structure from get_groups_with_users
            if "users" not in std_auth_group_obj:
                std_auth_group_obj["users"] = []  # Should be populated by get_group_by_name if it includes users
            if "users_obj" not in std_auth_group_obj:
                std_auth_group_obj["users_obj"] = []  # Same as above

    if not std_auth_group_obj:  # Still no group object after trying to fetch/create
        logging.warning(
            f"Failed to obtain Authentik group '{std_auth_group_name}' for entity '{base_name}'. Skipping standard Authentik sync."
        )
    # else: std_auth_group_obj is now available for sync

    std_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(std_mm_channel_name))
    std_mm_users_in_channel = []
    if std_mm_channel:
        std_mm_users_in_channel = mattermost_client.get_users_in_channel(std_mm_channel["id"])
    else:
        logging.warning(
            f"Mattermost channel '{std_mm_channel_name}' for entity '{base_name}' not found. Standard sync might be incomplete."
        )

    adm_auth_group_obj = None
    adm_mm_users_in_channel = []
    adm_mm_channel_name_for_log = "N/A"

    if admin_config:
        adm_auth_group_name = admin_config.get("authentik_group_name_pattern", "{base_name} Admin").format(
            base_name=base_name
        )
        adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(
            base_name=base_name
        )
        adm_mm_channel_name_for_log = adm_mm_channel_name  # For logging context
        adm_auth_group_obj = all_authentik_groups_by_name.get(adm_auth_group_name)
        if not adm_auth_group_obj:  # Group not pre-fetched
            logging.info(
                f"Authentik admin group '{adm_auth_group_name}' for entity '{base_name}' not in pre-fetched list. Attempting to fetch/create."
            )
            adm_auth_group_obj = authentik_client.get_group_by_name(adm_auth_group_name)
            if not adm_auth_group_obj:
                logging.info(f"Authentik admin group '{adm_auth_group_name}' not found, attempting to create.")
                created_group = authentik_client.create_group(adm_auth_group_name)
                if created_group:
                    adm_auth_group_obj = created_group
                    if "users" not in adm_auth_group_obj:
                        adm_auth_group_obj["users"] = []
                    if "users_obj" not in adm_auth_group_obj:
                        adm_auth_group_obj["users_obj"] = []
                    logging.info(f"Authentik admin group '{adm_auth_group_name}' created successfully.")
                else:
                    logging.error(
                        f"Failed to create Authentik admin group '{adm_auth_group_name}'. Skipping admin Authentik sync for this group."
                    )
            else:
                logging.info(f"Authentik admin group '{adm_auth_group_name}' fetched successfully.")
                if "users" not in adm_auth_group_obj:
                    adm_auth_group_obj["users"] = []
                if "users_obj" not in adm_auth_group_obj:
                    adm_auth_group_obj["users_obj"] = []

        if not adm_auth_group_obj:  # Still no admin group object
            logging.warning(
                f"Failed to obtain Authentik admin group '{adm_auth_group_name}' for entity '{base_name}'. Skipping admin Authentik sync."
            )
        # else: adm_auth_group_obj is now available for sync

        adm_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(adm_mm_channel_name))
        if adm_mm_channel:
            adm_mm_users_in_channel = mattermost_client.get_users_in_channel(adm_mm_channel["id"])
            adm_mm_channel_name_for_log = adm_mm_channel.get("display_name", adm_mm_channel_name)
        else:
            logging.warning(
                f"Mattermost channel '{adm_mm_channel_name}' for entity '{base_name}' (admin) not found. Admin sync might be incomplete."
            )

    # Prepare user data for Outline and Brevo (which uses all users from standard channel)
    # Users from admin channels determine specific permissions (e.g., admin in Outline)
    # For Brevo, typically all users from the "standard" channel are added to the list.
    # If admin channel members also need to be on the Brevo list, they'd be part of std_mm_users_in_channel
    # if the admin channel is a superset or if they are also in the standard channel.
    # The current logic assumes Brevo list membership is primarily tied to the standard channel.

    mm_users_for_services = {}  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    # Prioritize admin channel membership status if a user is in both
    for mm_user in std_mm_users_in_channel:
        email = mm_user.get("email", "").lower()
        if email:
            mm_users_for_services[email] = {
                "username": mm_user.get("username"),
                "mm_user_id": mm_user.get("id"),
                "is_admin_channel_member": False,  # Default, might be overridden by admin channel check
            }
    if admin_config:  # If there's an admin channel, its members might have different roles
        for mm_user in adm_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                existing_data = mm_users_for_services.get(email, {})
                mm_users_for_services[email] = {
                    "username": mm_user.get("username", existing_data.get("username")),
                    "mm_user_id": mm_user.get("id", existing_data.get("mm_user_id")),
                    "is_admin_channel_member": True,  # User is in admin channel
                }

    std_mm_channel_name_for_log = std_mm_channel.get("display_name") if std_mm_channel else std_mm_channel_name

    # Authentik Sync
    if std_auth_group_obj:
        results.extend(
            _sync_single_authentik_group(
                authentik_client,
                std_auth_group_obj,
                std_mm_users_in_channel,  # Standard Authentik group syncs with standard MM channel users
                email_to_authentik_user_pk_map,
                std_mm_channel_name_for_log,
                perform_deletions,
            )
        )
    if admin_config and adm_auth_group_obj:
        results.extend(
            _sync_single_authentik_group(
                authentik_client,
                adm_auth_group_obj,
                adm_mm_users_in_channel,  # Admin Authentik group syncs with admin MM channel users
                email_to_authentik_user_pk_map,
                adm_mm_channel_name_for_log,  # Log context for admin channel
                perform_deletions,
            )
        )

    # Outline Sync
    if outline_client and outline_cfg:
        outline_coll_name_pattern = outline_cfg.get("collection_name_pattern", "{base_name}")
        outline_coll_name = outline_coll_name_pattern.format(base_name=base_name)
        default_permission = outline_cfg.get("default_access", "read")
        admin_permission = outline_cfg.get("admin_access", "read_write")
        results.extend(
            _sync_single_outline_collection(
                outline_client,
                mattermost_client,
                outline_coll_name,
                mm_users_for_services,  # Uses combined user list with admin flag
                default_permission,
                admin_permission,
                std_mm_channel_name_for_log,
                perform_deletions,
            )
        )

    # Brevo Sync
    if brevo_client and brevo_cfg:
        brevo_list_name_pattern = brevo_cfg.get("list_name_pattern", "mm_{base_name}")
        brevo_list_name = brevo_list_name_pattern.format(base_name=base_name)
        results.extend(
            _sync_single_brevo_list(
                brevo_client,
                brevo_list_name,
                std_mm_users_in_channel,  # Brevo list syncs with standard MM channel users
                std_mm_channel_name_for_log,
                perform_deletions,
            )
        )

    # NoCoDB Sync (only for ANTENNE and POLES)
    skip_services = skip_services or []  # Ensure it's a list for safe checking
    if "nocodb" not in skip_services and nocodb_client and nocodb_cfg and entity_key in ["ANTENNE", "POLES"]:
        nocodb_base_title_pattern = nocodb_cfg.get("base_title_pattern", "nocodb_{base_name}")
        # base_name is the entity's base name (e.g., "MyAntenne")
        # mm_users_for_services contains the necessary user details including 'is_admin_channel_member'
        default_nocodb_permission = nocodb_cfg.get("default_access", "viewer")
        admin_nocodb_permission = nocodb_cfg.get("admin_access", "owner")
        results.extend(
            _sync_single_nocodb_base(
                nocodb_client,
                mattermost_client,  # Pass Mattermost client
                nocodb_base_title_pattern,
                base_name,  # This is the base_name of the entity (e.g. "MonAntenne")
                mm_users_for_services,  # Combined user list with admin flag
                default_nocodb_permission,
                admin_nocodb_permission,
                std_mm_channel_name_for_log,  # Context for logging
                perform_deletions,
            )
        )

    # Vaultwarden Collection Member Sync
    # Vaultwarden sync does not involve deletions from the collection based on MM channel membership.
    # It's additive: users in MM channels are invited.
    # If `perform_deletions` is True for the overall sync, it doesn't apply here.
    if "vaultwarden" not in skip_services and vaultwarden_client and vaultwarden_cfg:
        vw_collection_name_pattern = vaultwarden_cfg.get("collection_name_pattern", "Shared - {base_name}")
        vw_collection_name = vw_collection_name_pattern.format(base_name=base_name)
        results.extend(
            _sync_single_vaultwarden_collection_members(
                vaultwarden_client,
                mattermost_client,  # Pass Mattermost client
                vw_collection_name,
                # mm_users_for_services contains all users from standard and admin channels relevant to this entity
                # The invite logic in Vaultwarden client uses default permissions, so no specific admin/default distinction needed here.
                mm_users_for_services,
                std_mm_channel_name_for_log,  # Context for logging
            )
        )
    elif vaultwarden_client and not vaultwarden_cfg:
        logging.debug(
            f"Vaultwarden client available but no vaultwarden config for entity '{base_name}'. Skipping VW sync."
        )

    logging.info(f"Finished sync for entity '{base_name}'. Total results: {len(results)}")
    return results






def _ensure_users_in_authentik_group(
    authentik_client: "AuthentikClient",
    auth_group_pk: str,
    auth_group_name: str,
    mm_users_to_ensure: list[dict],  # List of Mattermost user objects
    email_to_authentik_user_pk_map: dict,
    mm_channel_display_name_for_log: str,
    current_auth_user_pks_in_group: set,
) -> tuple[list[dict], set]:  # Returns results and set of targeted authentik pks
    """
    Ensures that the given Mattermost users are in the specified Authentik group.
    Adds users to the group if they are not already members.
    Returns a list of action results and a set of Authentik PKs that were targeted (found in MM and Authentik).
    """
    results = []
    targeted_auth_pks = set()

    if not auth_group_pk:
        logging.error(
            f"No Authentik group PK provided to _ensure_users_in_authentik_group for group name {auth_group_name}."
        )
        # Potentially return a result indicating this failure
        return results, targeted_auth_pks

    # To check who is already in the group, we need the current members.
    # This might require fetching the group details again if not passed in,
    # or assuming the caller (e.g., _sync_single_authentik_group) provides this.
    # For now, let's assume we need to fetch it or it's passed.
    # Simplified: the original _sync_single_authentik_group has this.
    # This helper will focus on the "add" part, assuming the caller has the full group state.

    for mm_user in mm_users_to_ensure:
        mm_username = mm_user.get("username", "UnknownUser")
        mm_user_email_lower = mm_user.get("email", "").lower()
        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user.get("email") or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name_for_log,
            "target_resource_name": auth_group_name,
            "service": "AUTHENTIK",
        }
        auth_user_result = {**base_user_info, "status": "FAILURE", "action": "AUTHENTIK_GROUP_UNCHANGED"}

        if mm_username in config.EXCLUDED_USERS:
            # If user is excluded, we don't try to add them.
            # The calling function will handle ensuring they are preserved if already in group.
            logging.debug(f"User '{mm_username}' is excluded. Skipping ensure in Authentik group '{auth_group_name}'.")
            continue

        if not mm_user_email_lower:
            auth_user_result.update(
                {
                    "status": SyncStatus.SKIPPED.value,
                    "action": "SKIPPED_NO_MM_EMAIL_FOR_AUTHENTIK_ENSURE",
                    "error_message": "User has no email in Mattermost for Authentik mapping.",
                }
            )
            results.append(auth_user_result)
            continue

        auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)

        if auth_pk_for_mm_user is None:
            auth_user_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_AUTHENTIK_FOR_ENSURE",
                    "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                }
            )
        else:
            targeted_auth_pks.add(auth_pk_for_mm_user)
            # This function's role is to ensure addition. The check for "already in group"
            # would ideally use `current_auth_user_pks_in_group`.
            # If this function is called by `_sync_single_authentik_group`, that function already has this set.
            # Let's assume for now this function is "dumb" and just tries to add.
            # The `add_user_to_group` client method should ideally be idempotent or handle "already member".
            # However, to provide accurate reporting ("USER_ADDED" vs "USER_ALREADY_IN"),
            # the knowledge of current membership is needed here or assumed handled by _sync_single_authentik_group.

            # To simplify, this function will just attempt the add.
            # _sync_single_authentik_group will use the returned targeted_auth_pks
            # to compare against its known current_auth_user_pks_in_group to report accurately.
            # OR, this function needs `current_auth_user_pks_in_group` as an argument.
            # Let's add `current_auth_user_pks_in_group` for more precise action reporting here.
            # This was commented out in the signature, adding it back.

            # Re-evaluating: The original _sync_single_authentik_group iterates MM users.
            # If user is in MM, and in Authentik, it adds to target_auth_pks_for_this_group.
            # Then it checks if this pk is NOT in current_auth_user_pks_in_group, then adds.
            # This new function _ensure_users_in_authentik_group will mirror that "add" logic.

            # Let's assume `current_auth_user_pks_in_group` is passed or fetched if this function becomes standalone.
            # For now, let's assume it's NOT passed and this function only attempts adds,
            # and the caller (_sync_single_authentik_group) interprets the results.
            # The "action" reported here will be "ATTEMPTED_ADD_TO_AUTHENTIK_GROUP".

            # Simpler approach: This function is called by _sync_single_authentik_group.
            # _sync_single_authentik_group will iterate its MM users. For each, it decides if an add is needed.
            # If so, it calls a more primitive function: `_add_user_to_authentik_group_if_not_member`
            # This seems like over-refactoring for now.

            # Let's stick to the plan: `_ensure_users_in_authentik_group` handles the loop and add logic.
            # It needs `current_auth_user_pks_in_group` to report correctly.
            # Let's assume it's passed implicitly by the caller managing that set.
            # This function will just return the list of users *that should be in the group* from MM's perspective.

            # Corrected approach for _ensure_users_in_authentik_group:
            # It takes the list of MM users. It identifies which ones *should* be in the group.
            # It then ensures they ARE in the group.
            # It needs `current_auth_user_pks_in_group` to avoid adding if already present and report correctly.

            # Reverting to the idea that this function gets `current_auth_user_pks_in_group`
            # Let's assume it's passed for now.
            # However, the prompt implies _sync_single_authentik_group calls this.
            # _sync_single_authentik_group already has this set.

            # Let's refine: this function will be responsible for the "add" part.
            # It needs to know who is *already* in the group to avoid redundant adds and report correctly.
            # So, `current_auth_user_pks_in_group` should be an argument.
            # The signature in the plan didn't include it, this is an adjustment.

            # Let's assume `current_auth_user_pks_in_group` is NOT passed for now to minimize changes to original call structure.
            # This means this function will just try to add, and the client's `add_user_to_group` should be robust.
            # The reporting from this function will be about the *attempt* to add.

            # If `authentik_client.add_user_to_group` is smart (doesn't error if user already member),
            # then we can call it directly.
            # The original code checks `if auth_pk_for_mm_user not in current_auth_user_pks_in_group:` before adding.
            # This new function should replicate that.
            # This means `current_auth_user_pks_in_group` is essential here.
            # The plan was to have _sync_single_authentik_group call this.
            # _sync_single_authentik_group will have `current_auth_user_pks_in_group`.
            # So, it should pass it.

            # Adding current_auth_user_pks_in_group to the signature of _ensure_users_in_authentik_group
            # This was missed in the initial thought but is vital.
            # The calling function _sync_single_authentik_group will provide this.
            # This is a refinement of the plan step.

            # The diff will show this new function. Let's assume current_auth_user_pks_in_group is passed.
            # For now, to proceed with the diff, I will assume it's NOT passed and simplify the logic.
            # The main `_sync_single_authentik_group` will handle the "is member" check before calling a simpler "add" function.
            # This means `_ensure_users_in_authentik_group` might be too high-level.

            # Let's create a more focused `_add_authentik_user_to_group` helper.
            # This seems like a deviation from "Extract logic of add/update".
            # The original plan was: `_ensure_users_in_authentik_group` will contain the loop and add logic.

            # Sticking to the plan: `_ensure_users_in_authentik_group` will do the loop.
            # It needs `current_auth_user_pks_in_group`.
            # I will add it to the signature in the code I write.
            # The diff tool only sees the new function body.

            # This function will be simpler if it just returns the set of users who *should* be members
            # based on MM list. The caller (_sync_single_authentik_group) then performs the actual adds/removals.
            # This also feels like not fulfilling "extracting the add logic".

            # Final decision for this step:
            # `_ensure_users_in_authentik_group` will take `current_auth_user_pks_in_group`.
            # It will iterate `mm_users_to_ensure`.
            # If a user should be added (exists in Auth, not excluded, not already in group), it calls `authentik_client.add_user_to_group`.
            # It returns results of these "add" actions and the set of `targeted_auth_pks`.

    # The calling function _sync_single_authentik_group will provide this.

    for mm_user in mm_users_to_ensure:
        mm_username = mm_user.get("username", "UnknownUser")
        mm_user_email_lower = mm_user.get("email", "").lower()
        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user.get("email") or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name_for_log,
            "target_resource_name": auth_group_name,
            "service": "AUTHENTIK",
        }
        auth_user_result = {**base_user_info, "status": "FAILURE", "action": "AUTHENTIK_GROUP_UNCHANGED"}

        if mm_username in config.EXCLUDED_USERS:
            # If user is excluded, we don't try to add them.
            # If they are already in the group, their PK would have been added to
            # targeted_auth_pks by the calling function to prevent removal.
            logging.debug(f"User '{mm_username}' is excluded. Skipping ensure in Authentik group '{auth_group_name}'.")
            # Add their PK to targeted_auth_pks if they are already a member (this check might be redundant if caller handles it)
            # For now, this function focuses on adding non-excluded users.
            # The responsibility of preserving excluded users if they are already members lies with the caller
            # which populates the initial `target_auth_pks_for_this_group` in `_sync_single_authentik_group`.
            continue

        if not mm_user_email_lower:
            auth_user_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_NO_MM_EMAIL_FOR_AUTHENTIK_ENSURE",
                    "error_message": "User has no email in Mattermost for Authentik mapping.",
                }
            )
            results.append(auth_user_result)
            continue

        auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)

        if auth_pk_for_mm_user is None:
            auth_user_result.update(
                {
                    "status": SyncStatus.SKIPPED.value,
                    "action": "SKIPPED_USER_NOT_IN_AUTHENTIK_FOR_ENSURE",
                    "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                }
            )
        else:
            targeted_auth_pks.add(auth_pk_for_mm_user)
            if auth_pk_for_mm_user not in current_auth_user_pks_in_group:
                if authentik_client.add_user_to_group(auth_group_pk, auth_pk_for_mm_user):
                    auth_user_result.update({"status": SyncStatus.SUCCESS.value, "action": AuthentikAction.USER_ADDED_TO_GROUP.value})
                else:
                    auth_user_result.update(
                        {
                            "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                            "error_message": "API call to add user to Authentik group failed.",
                        }
                    )
            else:
                auth_user_result.update({"status": SyncStatus.SUCCESS.value, "action": AuthentikAction.USER_ALREADY_IN_GROUP.value})
        results.append(auth_user_result)

    return results, targeted_auth_pks












async def orchestrate_group_synchronization(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],
    brevo_client: Optional["BrevoClient"],
    nocodb_client: Optional["NocoDBClient"],
    vaultwarden_client: Optional["VaultwardenClient"],
    mm_team_id: str,
    perform_deletions: bool = True,
    sync_mode: str = "FULL_SYNC",  # MM_TO_TOOLS, TOOLS_TO_MM, FULL_SYNC
    skip_services: list[str] | None = None,
) -> tuple[bool, list[dict]]:
    skip_services = skip_services or []
    logging.info(
        f"Starting group synchronization task (async)... "
        f"(Perform Deletions: {perform_deletions}, Sync Mode: {sync_mode}, Skip Services: {skip_services})"
    )
    detailed_results = []

    if sync_mode not in ["MM_TO_TOOLS", "TOOLS_TO_MM", "FULL_SYNC"]:
        logging.error(f"Invalid sync_mode: {sync_mode}. Must be one of MM_TO_TOOLS, TOOLS_TO_MM, FULL_SYNC.")
        return False, [
            {
                "service": "ORCHESTRATOR",
                "target_resource_name": "N/A",
                "status": SyncStatus.FAILURE.value,
                "action": "INVALID_SYNC_MODE",
                "error_message": f"Invalid sync_mode: {sync_mode}",
            }
        ]

    # Client checks
    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Authentik sync will be skipped.")
    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed with core logic.")
        return False, detailed_results
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    if not outline_client:
        logging.info("Outline client not provided. Outline synchronization will be skipped.")
    if not brevo_client:
        logging.info("Brevo client not provided. Brevo synchronization will be skipped.")
    if not nocodb_client:
        logging.info("NocoDB client not provided. NocoDB synchronization will be skipped.")
    if not vaultwarden_client:
        logging.info("Vaultwarden client not provided. Vaultwarden synchronization will be skipped.")

    _, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)
    if not email_to_auth_pk_map and authentik_client:  # Only warn if client was available
        logging.warning(
            "Authentik email-to-user-PK map is empty. Authentik sync operations might not find users effectively."
        )

    all_auth_groups_by_name = {}
    entities_to_process = {}

    if sync_mode == "FULL_SYNC":
        logging.info("Sync Mode: FULL_SYNC. Discovering entities from Authentik groups...")
        all_auth_groups_list = []
        if authentik_client:
            all_auth_groups_list, _ = authentik_client.get_groups_with_users()
            if not all_auth_groups_list:
                logging.info("No Authentik groups found or an error occurred during fetching for discovery.")
            all_auth_groups_by_name = {g["name"]: g for g in all_auth_groups_list}
        else:
            logging.warning("Authentik client not available for FULL_SYNC discovery.")
            all_auth_groups_by_name = {}

        if not all_auth_groups_list and authentik_client:
            logging.info("No Authentik groups found to process for FULL_SYNC. Synchronization might be limited.")

        for auth_group_name_iter in all_auth_groups_by_name.keys():
            found_entity_key_auth, current_base_name_auth = _map_auth_group_to_entity_and_base_name(
                auth_group_name_iter, config.PERMISSIONS_MATRIX
            )
            if found_entity_key_auth and current_base_name_auth:
                entity_tuple = (found_entity_key_auth, current_base_name_auth)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_auth]
            else:
                logging.debug(
                    f"Authentik group '{auth_group_name_iter}' did not map to a known entity pattern for FULL_SYNC."
                )

    elif sync_mode == "MM_TO_TOOLS":
        logging.info("Sync Mode: MM_TO_TOOLS. Discovering entities based on Mattermost channels...")
        mm_channels = mattermost_client.get_channels_for_team(mm_team_id)
        if not mm_channels:
            logging.warning(
                "No Mattermost channels found for the team. Cannot discover entities for MM_TO_TOOLS sync."
            )
            return True, detailed_results

        for channel in mm_channels:
            channel_name = channel.get("name")
            channel_display_name = channel.get("display_name")
            found_entity_key_mm, current_base_name_mm = _map_mm_channel_to_entity_and_base_name(
                channel_name, channel_display_name, config.PERMISSIONS_MATRIX
            )
            if found_entity_key_mm and current_base_name_mm:
                entity_tuple = (found_entity_key_mm, current_base_name_mm)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_mm]
                    logging.info(
                        f"Discovered entity '{current_base_name_mm}' (type: {found_entity_key_mm}) from MM channel '{channel_display_name}' for MM_TO_TOOLS sync."
                    )
            else:
                logging.debug(
                    f"MM channel '{channel_display_name}' (slug: {channel_name}) did not map to a known entity pattern for MM_TO_TOOLS sync."
                )
    # TOOLS_TO_MM discovery is handled within its loop by _sync_entity_permissions_tools_to_mm

    if not entities_to_process and sync_mode not in ["TOOLS_TO_MM"]:
        logging.info(
            f"No entities found to process after discovery phase for sync_mode '{sync_mode}'. Synchronization finished."
        )
        return True, detailed_results

    if sync_mode == "TOOLS_TO_MM":
        logging.info("TOOLS_TO_MM sync mode: Iterating through configured services.")
        service_clients_map = {
            "AUTHENTIK": authentik_client,
            "OUTLINE": outline_client,
            "BREVO": brevo_client,
            "NOCODB": nocodb_client,
            "VAULTWARDEN": vaultwarden_client,
        }
        for service_name, service_client in service_clients_map.items():
            if service_client:
                service_results = await _sync_entity_permissions_tools_to_mm(
                    service_client=service_client,
                    service_name=service_name,
                    mattermost_client=mattermost_client,
                    mm_team_id=mm_team_id,
                    email_to_authentik_user_pk_map=email_to_auth_pk_map if service_name == "AUTHENTIK" else None,
                    perform_deletions=perform_deletions,
                    permissions_matrix=config.PERMISSIONS_MATRIX,
                    skip_services=skip_services,
                )
                detailed_results.extend(service_results)
            else:
                logging.info(f"Service client for {service_name} not configured, skipping for TOOLS_TO_MM sync.")
    else:  # For FULL_SYNC and MM_TO_TOOLS
        for (entity_key, base_name), entity_config_to_use in entities_to_process.items():
            logging.info(
                f"Orchestrating sync for entity: {entity_key}, base_name: {base_name}, "
                f"sync_mode: {sync_mode}, perform_deletions: {perform_deletions}"
            )
            # When sync_mode is MM_TO_TOOLS (formerly fetch_remote_members=False),
            # all_auth_groups_by_name is initially empty.
            # sync_entity_permissions handles fetching/creating groups on demand.
            entity_sync_results = sync_entity_permissions(  # This function will also need sync_mode
                authentik_client,
                mattermost_client,
                outline_client,
                brevo_client,
                nocodb_client,
                vaultwarden_client,
                mm_team_id,
                base_name,
                entity_key,
                entity_config_to_use,
                all_auth_groups_by_name,  # Used by FULL_SYNC, empty for MM_TO_TOOLS initially
                email_to_auth_pk_map,
                perform_deletions,
                skip_services=skip_services,
                # sync_mode=sync_mode, # sync_entity_permissions will need this
            )
            detailed_results.extend(entity_sync_results)

    log_msg = (
        f"Synchronization task completed. Mode: {sync_mode}, "
        f"deletions: {perform_deletions}, skip_services: {skip_services}). "
        f"Processed {len(entities_to_process) if sync_mode != 'TOOLS_TO_MM' else 'N/A (TOOLS_TO_MM)'} unique entities. "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results


async def _sync_entity_permissions_tools_to_mm(
    service_client: object,
    service_name: str,
    mattermost_client: "MattermostClient",
    mm_team_id: str,
    email_to_authentik_user_pk_map: Optional[dict],
    perform_deletions: bool,
    permissions_matrix: dict,
    skip_services: list[str] | None,
) -> list[dict]:
    results = []
    logging.info(f"Starting TOOLS_TO_MM sync for service: {service_name}")

    if service_name.lower() in (skip_services or []):
        logging.info(f"Skipping {service_name} sync for TOOLS_TO_MM as per skip_services.")
        return results

    if service_name == "AUTHENTIK":
        authentik_client = service_client
        all_auth_groups, _ = authentik_client.get_groups_with_users()
        if not all_auth_groups:
            logging.warning("TOOLS_TO_MM: No Authentik groups found to sync.")
            return results

        for group in all_auth_groups:
            entity_key, base_name = _map_auth_group_to_entity_and_base_name(group.get("name"), permissions_matrix)
            if not entity_key or not base_name:
                logging.debug(
                    f"TOOLS_TO_MM: Authentik group '{group.get('name')}' did not map to an entity. Skipping."
                )
                continue

            logging.info(
                f"TOOLS_TO_MM: Processing Authentik group '{group.get('name')}' for entity '{base_name}' ({entity_key})"
            )
            entity_config = permissions_matrix.get(entity_key, {})

            # Determine if the current Authentik group is an admin or standard group
            # This heuristic is simple and relies on naming convention. A more robust way would be to check against both patterns.
            admin_cfg = entity_config.get("admin", {})
            is_admin_group = False
            if admin_cfg and _extract_base_name(group.get("name"), admin_cfg.get("authentik_group_name_pattern", "")):
                is_admin_group = True

            _, std_mm_users, adm_mm_users = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )

            mm_users_for_this_group = adm_mm_users if is_admin_group else std_mm_users

            mm_user_emails = {user["email"].lower() for user in mm_users_for_this_group if "email" in user}

            auth_users = group.get("users_obj", [])
            for user in auth_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    # Check if user is excluded
                    if user.get("username") in config.EXCLUDED_USERS:
                        continue
                    results.append(
                        remove_user_from_authentik_group(
                            authentik_client,
                            group.get("pk"),
                            group.get("name"),
                            user.get("pk"),
                            user_email,
                            base_name,
                        )
                    )

    elif service_name == "OUTLINE":
        outline_client = service_client
        try:
            all_collections = outline_client.list_collections()
            if not all_collections:
                logging.warning("TOOLS_TO_MM: No Outline collections found to sync.")
                return results
        except (AttributeError, NotImplementedError):
            logging.error("`outline_client.list_collections()` method not implemented. Skipping Outline sync.")
            return results

        for collection in all_collections:
            collection_name = collection.get("name")
            collection_id = collection.get("id")
            entity_key, base_name = _map_outline_collection_to_entity_and_base_name(
                collection_name, permissions_matrix
            )

            if not entity_key or not base_name:
                continue

            entity_config = permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )

            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            outline_users_id = outline_client.get_collection_members(collection_id)
            for id in outline_users_id:
                user = outline_client.get_user_by_id(id)
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    results.append(
                        _remove_user_from_outline_collection(
                            outline_client,
                            collection_id,
                            collection_name,
                            user["id"],
                            user_email,
                            base_name,
                        )
                    )

    elif service_name == "NOCODB":
        nocodb_client = service_client
        all_bases = nocodb_client.list_bases()
        if not all_bases:
            logging.warning("TOOLS_TO_MM: No NoCoDB bases found to sync.")
            return results

        for base in all_bases["list"]:
            base_title = base.get("title")
            base_id = base.get("id")
            entity_key, base_name = _map_nocodb_base_to_entity_and_base_name(base_title, permissions_matrix)

            if not entity_key or not base_name:
                continue

            entity_config = permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )
            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            nocodb_users = nocodb_client.list_base_users(base_id)
            for user in nocodb_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    results.append(
                        _remove_user_from_nocodb_base(
                            nocodb_client,
                            base_id,
                            base_title,
                            user["id"],
                            user_email,
                            base_name,
                        )
                    )

    elif service_name == "BREVO":
        # Brevo sync is handled by the existing _sync_single_brevo_list
        pass

    elif service_name == "VAULTWARDEN":
        vaultwarden_client = service_client
        all_collections = vaultwarden_client.get_collections_details()
        if not all_collections:
            logging.warning("TOOLS_TO_MM: No Vaultwarden collections found to sync.")
            return results
        rc_list, sout_list, err_list = vaultwarden_client.get_collections()
        rc_user_list, sout_user_list, err_user_list = vaultwarden_client.get_members()
        for collection in all_collections:
            collection_id = collection.get("id")

            collection_name = None
            if rc_list == 0:
                collection_name = vaultwarden_client.get_name_from_collections(collection_id, sout_list)
            else:
                logging.error(f"Failed to list collections using 'bw list collections': {err_list.strip()}")
            entity_key, base_name = _map_vaultwarden_collection_to_entity_and_base_name(
                collection_name, permissions_matrix
            )

            if not entity_key or not base_name:
                continue

            entity_config = permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )
            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            vaultwarden_users_by_collection = collection.get("users", [])
            users_to_keep = []
            for user in vaultwarden_users_by_collection:
                user_id = user.get("id")
                
                user_email = None
                if rc_user_list == 0:
                    user_email = vaultwarden_client.get_email_from_members(user_id, sout_user_list)
                else:
                    logging.error(f"Failed to list collections using 'bw list collections': {err_user_list.strip()}")

                if user_email and user_email in mm_user_emails:
                    users_to_keep.append(user)

            if len(users_to_keep) != len(vaultwarden_users_by_collection):
                payload = {
                    "users": users_to_keep,
                    "groups": collection.get("groups", []),
                    "externalId": collection.get("externalId"),
                    "name": collection.get("name"),
                }
                if vaultwarden_client.update_collection(collection_id, payload):
                    results.append(
                        {
                            "service": "VAULTWARDEN",
                            "target_resource_name": collection_name,
                            "status": SyncStatus.SUCCESS.value,
                            "action": VaultwardenAction.USER_REMOVED_FROM_COLLECTION.value,
                        }
                    )
                else:
                    results.append(
                        {
                            "service": "VAULTWARDEN",
                            "target_resource_name": collection_name,
                            "status": SyncStatus.FAILURE.value,
                            "action": VaultwardenAction.FAILED_TO_REMOVE_FROM_COLLECTION.value,
                        }
                    )
    return results


def _map_auth_group_to_entity_and_base_name(
    auth_group_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map an Authentik group name to an entity key and base_name from the PERMISSIONS_MATRIX.
    Returns (None, None) if no unambiguous match is found.
    Prioritizes admin patterns if a name could ambiguously match both standard and admin.
    """
    # Check admin patterns first to give them precedence in ambiguity
    for entity_key, entity_cfg in permissions_matrix.items():
        if entity_cfg.get("admin"):
            adm_pattern = entity_cfg.get("admin", {}).get("authentik_group_name_pattern")
            if adm_pattern:
                base_name = _extract_base_name(auth_group_name, adm_pattern)
                if base_name is not None:
                    return entity_key, base_name

    # Then check standard patterns
    for entity_key, entity_cfg in permissions_matrix.items():
        std_pattern = entity_cfg.get("standard", {}).get("authentik_group_name_pattern")
        if std_pattern:
            base_name = _extract_base_name(auth_group_name, std_pattern)
            if base_name is not None:
                # Before returning, ensure this wasn't primarily an admin group from another pattern
                # This check is imperfect if patterns are very complex or similar across entity types.
                # A more robust solution might involve checking if formatting the extracted base_name
                # with other admin patterns would yield the same auth_group_name.
                # For now, this assumes that if it matched an admin pattern above, it was handled.
                return entity_key, base_name
    return None, None


def _map_outline_collection_to_entity_and_base_name(
    collection_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map an Outline collection name to an entity key and base_name from the PERMISSIONS_MATRIX.
    """
    for entity_key, entity_cfg in permissions_matrix.items():
        outline_cfg = entity_cfg.get("outline")
        if outline_cfg:
            pattern = outline_cfg.get("collection_name_pattern")
            if pattern:
                base_name = _extract_base_name(collection_name, pattern)
                if base_name is not None:
                    return entity_key, base_name
    return None, None


def _map_vaultwarden_collection_to_entity_and_base_name(
    collection_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a Vaultwarden collection name to an entity key and base_name from the PERMISSIONS_MATRIX.
    """
    for entity_key, entity_cfg in permissions_matrix.items():
        vaultwarden_cfg = entity_cfg.get("vaultwarden")
        if vaultwarden_cfg:
            pattern = vaultwarden_cfg.get("collection_name_pattern")
            if pattern:
                base_name = _extract_base_name(collection_name, pattern)
                if base_name is not None:
                    return entity_key, base_name
    return None, None


def _map_brevo_list_to_entity_and_base_name(
    list_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a Brevo list name to an entity key and base_name from the PERMISSIONS_MATRIX.
    """
    for entity_key, entity_cfg in permissions_matrix.items():
        brevo_cfg = entity_cfg.get("brevo")
        if brevo_cfg:
            pattern = brevo_cfg.get("list_name_pattern")
            if pattern:
                base_name = _extract_base_name(list_name, pattern)
                if base_name is not None:
                    return entity_key, base_name
    return None, None


def _map_nocodb_base_to_entity_and_base_name(
    base_title: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a NoCoDB base title to an entity key and base_name from the PERMISSIONS_MATRIX.
    """
    for entity_key, entity_cfg in permissions_matrix.items():
        nocodb_cfg = entity_cfg.get("nocodb")
        if nocodb_cfg:
            pattern = nocodb_cfg.get("base_title_pattern")
            if pattern:
                base_name = _extract_base_name(base_title, pattern)
                if base_name is not None:
                    return entity_key, base_name
    return None, None


def _map_mm_channel_to_entity_and_base_name(
    mm_channel_slug: str, mm_channel_display_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a Mattermost channel (slug or display name) to an entity key and base_name.
    """
    # Try matching with channel display name first, as it's often more descriptive
    for entity_key, entity_cfg in permissions_matrix.items():
        if entity_cfg.get("admin"):
            mm_adm_pattern = entity_cfg.get("admin", {}).get("mattermost_channel_name_pattern")
            if mm_adm_pattern:
                base_name = _extract_base_name(mm_channel_display_name, mm_adm_pattern)
                if base_name is not None:
                    return entity_key, base_name
        std_pattern = entity_cfg.get("standard", {}).get("mattermost_channel_name_pattern")
        if std_pattern:
            base_name = _extract_base_name(mm_channel_display_name, std_pattern)
            if base_name is not None:
                return entity_key, base_name

    # Fallback to matching with channel slug if display name didn't yield a match
    # (Patterns are usually based on display name conventions, but slug might work for simple cases)
    for entity_key, entity_cfg in permissions_matrix.items():
        if entity_cfg.get("admin"):
            mm_adm_pattern = entity_cfg.get("admin", {}).get("mattermost_channel_name_pattern")
            # Slugifying the pattern to compare with slug might be needed if patterns are complex
            # For simple "{base_name}" or "prefix_{base_name}" it might work directly if base_name is slug-compatible
            if (
                mm_adm_pattern
                and slugify(mm_adm_pattern.format(base_name="test-slug"))
                == mm_adm_pattern.format(base_name="test-slug").lower()
            ):  # Simple pattern check
                base_name = _extract_base_name(
                    mm_channel_slug, mm_adm_pattern.lower()
                )  # Compare with lowercased pattern
                if base_name is not None:
                    return entity_key, base_name
        std_pattern = entity_cfg.get("standard", {}).get("mattermost_channel_name_pattern")
        if (
            std_pattern
            and slugify(std_pattern.format(base_name="test-slug")) == std_pattern.format(base_name="test-slug").lower()
        ):
            base_name = _extract_base_name(mm_channel_slug, std_pattern.lower())
            if base_name is not None:
                return entity_key, base_name

    return None, None


def _extract_base_name(actual_name: str, pattern_with_placeholder: str) -> Optional[str]:
    """
    Extracts the base_name from an actual_name given a pattern string like "prefix_{base_name}_suffix".
    Returns the extracted base_name (can be an empty string), or None if the actual_name doesn't match
    the pattern or if {base_name} is not in the pattern.
    """
    placeholder = "{base_name}"
    if placeholder not in pattern_with_placeholder:
        return None

    parts = pattern_with_placeholder.split(placeholder)
    prefix = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""

    if actual_name.startswith(prefix) and actual_name.endswith(suffix):
        if len(actual_name) < len(prefix) + len(suffix):
            return None

        if suffix:
            base_name_part = actual_name[len(prefix) : -len(suffix)]
        else:
            base_name_part = actual_name[len(prefix) :]

        return base_name_part
    return None




