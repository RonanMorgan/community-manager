# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
import re  # For slugify
from typing import TYPE_CHECKING, Optional

from app import config  # Import config to access EXCLUDED_USERS

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


# Copied from mattermost_client.py to avoid import issues and keep it self-contained here for now.
# TODO: Consider moving to a shared utils module if used in more places.
def slugify(text: str) -> str:
    """
    Simple slugify function:
    - Convert to lowercase
    - Replace spaces and underscores with hyphens
    - Remove characters that are not alphanumeric or hyphens
    - Ensure it doesn't start or end with a hyphen
    - Truncate to 64 characters (Mattermost limit for channel name)
    - Return a default name if the slug becomes empty
    """
    text = str(text).lower()
    # Replace spaces and underscores with hyphens first
    text = re.sub(r"[\s_]+", "-", text)
    # Replace any sequence of non-alphanumeric characters (excluding existing hyphens) with a single hyphen
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    # Remove leading or trailing hyphens that might have been created
    text = text.strip("-")
    # Consolidate multiple hyphens (e.g., "foo---bar" to "foo-bar").
    text = re.sub(r"-+", "-", text)

    if len(text) > 64:
        text = text[:64].strip("-")  # Re-strip if truncation creates leading/trailing hyphen

    if not text or text == "-":  # Handle if slug becomes empty or just a hyphen
        return "default-slug-name"  # Changed default from 'default-channel-name' to be more generic
    return text


# Helper function to determine Outline permission (REMOVED as logic is now in _sync_single_outline_collection)
# def _determine_outline_permission(auth_group_name: str, mm_channel_type: str) -> str:
#     ...


def get_all_authentik_groups_and_user_map(authentik_client: "AuthentikClient"):
    """
    Fetches all Authentik groups and constructs a user email-to-PK map.
    Uses the get_groups_with_users method from AuthentikClient.
    """
    logging.info("Fetching all Authentik groups and constructing user email-to-PK map...")
    if not authentik_client:
        logging.error("Authentik client not provided to get_all_authentik_groups_and_user_map.")
        return [], {}

    groups, email_map = authentik_client.get_groups_with_users()

    if not groups:
        logging.warning("No Authentik groups found or an error occurred during fetching.")
    if not email_map:
        logging.warning("Authentik user email-to-PK map is empty or could not be constructed.")

    return groups, email_map


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


def _get_mm_users_for_entity(
    mattermost_client: "MattermostClient",
    mm_team_id: str,
    base_name: str,
    entity_config: dict,
) -> tuple[dict, list, list]:  # Returns mm_users_for_services, std_mm_users, adm_mm_users
    """
    Fetches Mattermost users for a given entity, from both standard and admin channels.
    Returns a consolidated dictionary of users with their admin status, and separate lists for std/admin channel users.
    """
    std_config = entity_config.get("standard", {})
    admin_config = entity_config.get("admin")

    std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(base_name=base_name)
    std_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(std_mm_channel_name))
    std_mm_users_in_channel = []
    if std_mm_channel:
        std_mm_users_in_channel = mattermost_client.get_users_in_channel(std_mm_channel["id"])
    else:
        logging.warning(f"Mattermost channel '{std_mm_channel_name}' for entity '{base_name}' not found.")

    adm_mm_users_in_channel = []
    if admin_config:
        adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(
            base_name=base_name
        )
        adm_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(adm_mm_channel_name))
        if adm_mm_channel:
            adm_mm_users_in_channel = mattermost_client.get_users_in_channel(adm_mm_channel["id"])
        else:
            logging.warning(f"Mattermost admin channel '{adm_mm_channel_name}' for entity '{base_name}' not found.")

    mm_users_for_services = {}
    for mm_user in std_mm_users_in_channel:
        email = mm_user.get("email", "").lower()
        if email:
            mm_users_for_services[email] = {
                "username": mm_user.get("username"),
                "mm_user_id": mm_user.get("id"),
                "is_admin_channel_member": False,
            }

    if admin_config:
        for mm_user in adm_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                existing_data = mm_users_for_services.get(email, {})
                mm_users_for_services[email] = {
                    "username": mm_user.get("username", existing_data.get("username")),
                    "mm_user_id": mm_user.get("id", existing_data.get("mm_user_id")),
                    "is_admin_channel_member": True,
                }

    return mm_users_for_services, std_mm_users_in_channel, adm_mm_users_in_channel


def _sync_single_nocodb_base(
    nocodb_client: "NocoDBClient",
    mattermost_client: "MattermostClient",  # Added MattermostClient for DMs
    base_title_pattern: str,
    entity_base_name: str,  # e.g., "AntenneParis"
    mm_users_for_permission: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    default_permission: str,
    admin_permission: str,
    mm_channel_context_name: str,  # For logging/reporting context
    perform_deletions: bool,
) -> list[dict]:
    results = []
    nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
    # Main entry log changed to DEBUG, INFO will be for specific actions taken.
    logging.debug(f"Starting NoCoDB base sync for '{nocodb_base_title}'. Deletions: {perform_deletions}")

    nocodb_base_obj = nocodb_client.get_base_by_title(nocodb_base_title)
    if not nocodb_base_obj or not nocodb_base_obj.get("id"):
        logging.warning(  # This is an important warning, so kept as WARNING.
            f"NoCoDB base '{nocodb_base_title}' not found. Skipping sync. It should be created by 'create_antenne/pole' command."
        )
        return [
            {
                "service": "NOCODB",
                "target_resource_name": nocodb_base_title,
                "status": "SKIPPED",
                "action": "SKIPPED_NOCODB_BASE_NOT_FOUND",
                "error_message": f"Base '{nocodb_base_title}' not found in NoCoDB.",
            }
        ]

    base_id = nocodb_base_obj["id"]
    current_nocodb_users_list = nocodb_client.list_base_users(base_id)
    # Create a map of email_lower -> user_obj for current NoCoDB users for quick lookup
    current_nocodb_users_map = {
        user.get("email", "").lower(): user for user in current_nocodb_users_list if user.get("email")
    }
    target_nocodb_user_emails = set()

    # Preserve excluded users if they are already in the base
    for email_l, mm_user_d in mm_users_for_permission.items():
        if mm_user_d.get("username") in config.EXCLUDED_USERS:
            if email_l in current_nocodb_users_map:
                target_nocodb_user_emails.add(email_l)
                logging.debug(
                    f"User '{mm_user_d.get('username')}' ({email_l}) is excluded and already in NoCoDB base '{nocodb_base_title}'. Will be preserved."
                )

    # Ensure users from Mattermost are in the NoCoDB base with correct roles
    add_update_results, mm_targeted_emails = _ensure_users_in_nocodb_base(
        nocodb_client=nocodb_client,
        mattermost_client=mattermost_client,
        base_id=base_id,
        base_title=nocodb_base_title,
        mm_users_for_permission=mm_users_for_permission,
        default_permission=default_permission,
        admin_permission=admin_permission,
        current_nocodb_users_map=current_nocodb_users_map,
        mm_channel_context_name=mm_channel_context_name,
    )
    results.extend(add_update_results)
    target_nocodb_user_emails.update(mm_targeted_emails)

    if perform_deletions:
        # The existing_email_lower here is from current_nocodb_users_map.keys()
        # This is correct.
        for existing_email_lower, nocodb_user_obj in current_nocodb_users_map.items():
            nocodb_user_id_to_remove = nocodb_user_obj["id"]
            # Try to find original Mattermost username for logging if possible, otherwise use email.
            # This requires mm_users_for_permission to be comprehensive or another source for username if not in current MM channels.
            # For simplicity, we'll use the email as the primary identifier from NoCoDB's user list.
            username_for_log = nocodb_user_obj.get("firstname", "") + " " + nocodb_user_obj.get("lastname", "")
            if not username_for_log.strip():  # Fallback if no name
                username_for_log = existing_email_lower

            # Check if this NoCoDB user (by email) is in the EXCLUDED_USERS list via their MM username
            # This requires a reverse lookup: find if any mm_user_data maps to this email_lower and has an excluded username
            is_excluded = False
            for mm_email, mm_data in mm_users_for_permission.items():
                if mm_email == existing_email_lower and mm_data.get("username") in config.EXCLUDED_USERS:
                    is_excluded = True
                    break
            # Also, if the user was directly added to target_nocodb_user_emails due to exclusion earlier, respect that.
            if existing_email_lower in target_nocodb_user_emails and any(
                mm_data.get("username") in config.EXCLUDED_USERS
                for mm_data in mm_users_for_permission.values()
                if mm_data.get("email") == existing_email_lower
            ):
                is_excluded = True

            if not is_excluded and existing_email_lower not in target_nocodb_user_emails:
                removal_base_info = {
                    "mm_username": username_for_log,  # Best effort username from NoCoDB
                    "mm_user_email": existing_email_lower,
                    "mm_channel_display_name": mm_channel_context_name,
                    "target_resource_name": nocodb_base_title,
                    "service": "NOCODB",
                }
                removal_result = {**removal_base_info, "status": "FAILURE", "action": "FAILED_TO_REMOVE_NOCODB_USER"}
                if nocodb_client.delete_base_user(base_id, nocodb_user_id_to_remove):  # This sets role to "no-access"
                    removal_result.update({"status": "SUCCESS", "action": "NOCODB_USER_REMOVED_FROM_BASE"})
                else:
                    removal_result["error_message"] = (
                        "API call to remove user (set no-access) from NoCoDB base failed."
                    )
                results.append(removal_result)
            elif is_excluded:
                logging.debug(  # DEBUG for excluded user preservation details
                    f"User '{username_for_log}' ({existing_email_lower}) is in NoCoDB base "
                    f"'{nocodb_base_title}' and is excluded from sync-based removal."
                )

    # Summary log changed to DEBUG. INFO logs will be for specific successful/failed actions.
    logging.debug(f"Finished NoCoDB base sync for '{nocodb_base_title}'. Total results: {len(results)}")
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
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_AUTHENTIK_FOR_ENSURE",
                    "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                }
            )
        else:
            targeted_auth_pks.add(auth_pk_for_mm_user)
            # Check if user is already in the group is done by the caller _sync_single_authentik_group
            # This function's job is to attempt the add if the caller decided it's necessary.
            # For this refactoring, _ensure_users_in_authentik_group IS the one deciding.
            # It needs current_auth_user_pks_in_group, which I'll add to its signature.

            # This function is called by _sync_single_authentik_group.
            # _sync_single_authentik_group has current_auth_user_pks_in_group.
            # It should pass it to this function.
            # Let's assume current_auth_user_pks_in_group is now an argument to _ensure_users_in_authentik_group

            # The placeholder `pass` is being replaced here.
            # The argument `current_auth_user_pks_in_group` will be added to the signature by editing the file directly for the next step if necessary,
            # as the diff tool might not easily allow changing signature and body in one go if it was complex.
            # For now, let's assume it's available (e.g. added manually to the signature before this diff is applied).
            # I will proceed as if `current_auth_user_pks_in_group` is part of the arguments.
            # To make the diff work, I'll copy the argument name from the original function.
            # This means the signature used for the diff `_ensure_users_in_authentik_group` must be updated first.

            # Correcting: The diff tool replaces the `pass` placeholder. The signature of the new function was just created.
            # I need to ensure the signature of `_ensure_users_in_authentik_group` includes `current_auth_user_pks_in_group: set`.

            # For now, I will write the logic assuming current_auth_user_pks_in_group is NOT available
            # to keep this diff focused on the loop and basic add.
            # The next diff will refine this by passing current_auth_user_pks_in_group.

            # If not checking current membership here, then the action is just an attempt.
            # This is less ideal than the plan.
            # Let's assume the proper signature is:
            # _ensure_users_in_authentik_group(..., current_auth_user_pks_in_group: set)
            # And this function will use it.
            # The diff for the signature change will be done separately if needed.

            # For this specific diff, I will write the code as if current_auth_user_pks_in_group is present.
            # The diff tool will only care about replacing the `pass` line.

            # This function will now contain the logic from the loop in _sync_single_authentik_group
            # related to adding users.
            # It does NOT get `current_auth_user_pks_in_group`.
            # It determines who *should* be in the group from MM users, and attempts to add them.
            # The `targeted_auth_pks` it returns is the set of users it tried to process.

            # The original function `_sync_single_authentik_group` will then use this `targeted_auth_pks`
            # in conjunction with its `current_auth_user_pks_in_group` to decide on actual adds and report status.
            # This means `_ensure_users_in_authentik_group` does not call `add_user_to_group`.
            # It only identifies candidates. This makes it a "get_target_pks_from_mm_users" function.
            # This is not what was intended by "extract add logic".

            # Re-strategy for _ensure_users_in_authentik_group:
            # It WILL perform the add. It needs current_auth_user_pks_in_group.
            # I will modify its signature in the actual code block.

            # The placeholder `pass` should be replaced by the loop that processes mm_users_to_ensure.
            # Inside the loop, if a user needs to be added (they are in Authentik, not excluded,
            # and NOT in current_auth_user_pks_in_group), then call client.add_user_to_group.

            # The signature of _ensure_users_in_authentik_group will be updated in the next tool call
            # to include `current_auth_user_pks_in_group: set`.
            # This current diff will fill in the loop assuming that argument is present.

            # To make this diff work standalone, I'll put the logic here.
            # The signature update will follow.
            # This is slightly out of order but makes each step testable.

            # The `pass` is removed. The following is the new content for the function body.
            # This content assumes `current_auth_user_pks_in_group` will be added to the signature.
            # For this diff, I will hardcode it as an empty set to make the code runnable,
            # and then update the signature and usage in the next step. This is a temporary workaround.
            # current_auth_user_pks_in_group_temp_placeholder = set() # Placeholder # Removed

            if auth_pk_for_mm_user not in current_auth_user_pks_in_group:  # Using the actual argument
                if authentik_client.add_user_to_group(auth_group_pk, auth_pk_for_mm_user):
                    auth_user_result.update({"status": "SUCCESS", "action": "USER_ADDED_TO_AUTHENTIK_GROUP"})
                else:
                    auth_user_result.update(
                        {
                            "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                            "error_message": "API call to add user to Authentik group failed.",
                        }
                    )
            else:
                auth_user_result.update({"status": "SUCCESS", "action": "USER_ALREADY_IN_AUTHENTIK_GROUP"})
        results.append(auth_user_result)

    return results, targeted_auth_pks


def _ensure_users_in_nocodb_base(
    nocodb_client: "NocoDBClient",
    mattermost_client: "MattermostClient",
    base_id: str,
    base_title: str,
    mm_users_for_permission: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    default_permission: str,
    admin_permission: str,
    current_nocodb_users_map: dict,  # email_lower -> NoCoDB user object
    mm_channel_context_name: str,
) -> tuple[list[dict], set]:  # Returns results and set of targeted NocoDB user emails
    """
    Ensures that the given Mattermost users are members of the specified NoCoDB base
    with the correct permissions. Invites, adds, or updates users in the base.
    Sends DMs for new invites.
    Returns a list of action results and a set of emails that were targeted.
    """
    results = []
    targeted_emails_in_base = set()

    if not base_id:
        logging.error(f"No NoCoDB base ID provided to _ensure_users_in_nocodb_base for base title {base_title}.")
        return results, targeted_emails_in_base

    for email_lower, mm_user_data in mm_users_for_permission.items():
        mm_username = mm_user_data["username"]

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": base_title,
            "service": "NOCODB",
        }
        nocodb_result = {**base_user_info, "status": "FAILURE", "action": "NOCODB_USER_UNCHANGED"}

        if mm_username in config.EXCLUDED_USERS:
            logging.debug(f"User '{mm_username}' is excluded. Skipping NoCoDB ensure for base '{base_title}'.")
            # If excluded user is already in the base, their email should be added to
            # targeted_emails_in_base by the caller to prevent removal.
            continue

        targeted_emails_in_base.add(email_lower)
        target_role = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
        existing_nocodb_user = current_nocodb_users_map.get(email_lower)

        if existing_nocodb_user:
            nocodb_user_id = existing_nocodb_user["id"]
            current_role = existing_nocodb_user.get("roles")
            if current_role != target_role:
                if nocodb_client.update_base_user(base_id, nocodb_user_id, target_role):
                    nocodb_result.update(
                        {"status": "SUCCESS", "action": f"NOCODB_USER_ROLE_UPDATED_TO_{target_role.upper()}"}
                    )
                else:
                    nocodb_result.update(
                        {
                            "action": "FAILED_TO_UPDATE_NOCODB_USER_ROLE",
                            "error_message": "API call to update user role failed.",
                        }
                    )
            else:
                nocodb_result.update({"status": "SUCCESS", "action": "NOCODB_USER_ALREADY_IN_BASE_WITH_CORRECT_ROLE"})
        else:
            action_verb = f"NOCODB_USER_INVITED_AS_{target_role.upper()}"
            if nocodb_client.invite_user_to_base(base_id, email_lower, target_role):
                nocodb_result.update({"status": "SUCCESS", "action": action_verb})
                if mm_user_data.get("mm_user_id") and config.NOCODB_URL:
                    nocodb_base_link = f"{config.NOCODB_URL.rstrip('/')}/#/nc/{base_id}/dashboard"
                    dm_text = (
                        f"Bonjour @{mm_username}, vous avez été invité(e) à la base NoCoDb "
                        f"**{base_title}** (rôle: {target_role}).\n"
                        f"Vous pouvez y accéder ici : {nocodb_base_link}"
                    )
                    if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                        nocodb_result["action"] = f"{action_verb}_AND_DM_SENT"
                    else:
                        nocodb_result["action"] = f"{action_verb}_DM_FAILED"
                elif not config.NOCODB_URL:
                    logging.warning(
                        f"NOCODB_URL not configured. Cannot send DM for NoCoDB invite to {mm_username} for base {base_title}."
                    )
                    nocodb_result["action"] = f"{action_verb}_DM_SKIPPED_NO_URL"
            else:
                nocodb_result.update(
                    {"action": "FAILED_TO_INVITE_NOCODB_USER", "error_message": "API call to invite user failed."}
                )

        results.append(nocodb_result)

    return results, targeted_emails_in_base


def _ensure_users_invited_to_vaultwarden_collection(
    vaultwarden_client: "VaultwardenClient",
    mattermost_client: "MattermostClient",
    collection_id: str,
    collection_name: str,
    mm_users_for_services: dict,  # email_lower -> {username, mm_user_id, ...}
    mm_channel_context_name: str,
    access_token: str,  # Vaultwarden API access token
) -> list[dict]:  # Returns results
    """
    Ensures that the given Mattermost users are invited to the specified Vaultwarden collection.
    Sends DMs for new invites. This function is additive.
    Returns a list of action results.
    """
    results = []

    if not collection_id:
        logging.error(
            f"No Vaultwarden collection ID provided to _ensure_users_invited_to_vaultwarden_collection for collection name {collection_name}."
        )
        # Could append a result indicating this failure
        return results

    if not access_token:
        logging.error(f"No Vaultwarden access token provided for collection '{collection_name}'. Cannot invite users.")
        results.append(
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "FAILURE",
                "action": "VW_ENSURE_FAILED_NO_TOKEN",
                "error_message": "Missing Vaultwarden access token.",
            }
        )
        return results

    for email_lower, mm_user_data in mm_users_for_services.items():
        mm_username = mm_user_data.get("username", "UnknownUser")

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": collection_name,
            "service": "VAULTWARDEN",
        }
        invite_result = {**base_user_info, "status": "FAILURE", "action": "VAULTWARDEN_USER_INVITE_UNCHANGED"}

        if mm_username in config.EXCLUDED_USERS:
            logging.debug(
                f"User '{mm_username}' is excluded. Skipping Vaultwarden invite for collection '{collection_name}'."
            )
            continue

        if not email_lower:
            logging.warning(
                f"Skipping user with no email for Vaultwarden invite: {mm_username} to collection {collection_name}"
            )
            invite_result.update({"status": "SKIPPED", "action": "SKIPPED_NO_EMAIL_FOR_VW_INVITE"})
            results.append(invite_result)
            continue

        logging.debug(
            f"Attempting to invite {email_lower} to Vaultwarden collection '{collection_name}' (ID: {collection_id}) via ensure function."
        )
        success = vaultwarden_client.invite_user_to_collection(
            user_email=email_lower,
            collection_id=collection_id,
            organization_id=vaultwarden_client.organization_id,
            access_token=access_token,
        )

        action_verb = "USER_INVITED_TO_VW_COLLECTION"
        if success:
            invite_result.update({"status": "SUCCESS", "action": action_verb})
            if mm_user_data.get("mm_user_id"):
                if config.VAULTWARDEN_SERVER_URL:
                    dm_text = (
                        f"Bonjour @{mm_username}, vous avez été invité(e) à la collection Vaultwarden "
                        f"**{collection_name}**.\n"
                        f"Vous pouvez accéder à Vaultwarden ici : {config.VAULTWARDEN_SERVER_URL.rstrip('/')}"
                    )
                    if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                        invite_result["action"] = f"{action_verb}_AND_DM_SENT"
                    else:
                        invite_result["action"] = f"{action_verb}_DM_FAILED"
                else:
                    logging.warning(
                        f"VAULTWARDEN_SERVER_URL not configured. Cannot send DM for Vaultwarden invite to {mm_username} for collection {collection_name}."
                    )
                    invite_result["action"] = f"{action_verb}_DM_SKIPPED_NO_URL"
            else:
                invite_result["action"] = f"{action_verb}_DM_SKIPPED_NO_MM_USER_ID"
        else:
            invite_result.update(
                {
                    "action": "FAILED_TO_INVITE_TO_VW_COLLECTION",
                    "error_message": f"API call to invite {email_lower} to VW collection {collection_name} failed or user already member/invited. See client logs.",
                }
            )
        results.append(invite_result)

    return results


def _sync_single_authentik_group(
    authentik_client: "AuthentikClient",
    auth_group_obj: dict,
    mm_users_in_corresponding_channel: list[dict],
    email_to_authentik_user_pk_map: dict,
    mm_channel_display_name_for_log: str,
    perform_deletions: bool,
) -> list[dict]:
    results = []
    auth_group_name = auth_group_obj.get("name")
    auth_group_pk = auth_group_obj.get("pk")

    if not auth_group_pk or not auth_group_name:
        logging.error(
            f"Authentik group PK or name missing in auth_group_obj: {auth_group_obj}. Skipping sync for this group."
        )
        return [
            {
                "service": "AUTHENTIK",
                "target_resource_name": str(auth_group_obj.get("name", "UnknownGroup")),
                "status": "FAILURE",
                "action": "MISSING_GROUP_PK_OR_NAME",
                "error_message": "Group PK or name missing.",
            }
        ]

    current_auth_user_pks_in_group = set(auth_group_obj.get("users", []))
    auth_pk_to_auth_user_obj_map = {user.get("pk"): user for user in auth_group_obj.get("users_obj", [])}

    # Initialize target_auth_pks_for_this_group with PKs of excluded users already in the group
    target_auth_pks_for_this_group = set()
    for mm_user_email_lower, auth_pk_val in email_to_authentik_user_pk_map.items():
        # Need to find the username associated with this email to check against EXCLUDED_USERS
        # This requires iterating mm_users_in_corresponding_channel or having a direct email->username map for excluded check
        # For simplicity, if an Authentik user (via their PK) is in EXCLUDED_USERS (via their username), preserve them.
        # This check is more robust if we can map auth_pk_val back to a username found in EXCLUDED_USERS.
        auth_user_obj = auth_pk_to_auth_user_obj_map.get(auth_pk_val)
        if auth_user_obj and auth_user_obj.get("username") in config.EXCLUDED_USERS:
            if auth_pk_val in current_auth_user_pks_in_group:
                target_auth_pks_for_this_group.add(auth_pk_val)

    # Ensure users from Mattermost channel are in the Authentik group
    # This function handles additions and returns results for those actions,
    # and the set of Authentik PKs that were targeted based on MM channel members.
    add_results, mm_targeted_pks = _ensure_users_in_authentik_group(
        authentik_client,
        auth_group_pk,
        auth_group_name,
        mm_users_in_corresponding_channel,
        email_to_authentik_user_pk_map,
        mm_channel_display_name_for_log,
        current_auth_user_pks_in_group,  # Pass current members for accurate reporting in _ensure_users
    )
    results.extend(add_results)
    target_auth_pks_for_this_group.update(mm_targeted_pks)  # Add all users who should be in the group based on MM

    # Removal logic: Only if perform_deletions is True
    if perform_deletions:
        for auth_pk_in_group_obj in list(current_auth_user_pks_in_group):  # Iterate over a copy for safe removal
            auth_user_details = auth_pk_to_auth_user_obj_map.get(auth_pk_in_group_obj)
            auth_username_for_check = auth_user_details.get("username") if auth_user_details else None

            # Skip removal for excluded users, they are managed manually or by other means
            if auth_username_for_check and auth_username_for_check in config.EXCLUDED_USERS:
                continue

            if auth_pk_in_group_obj not in target_auth_pks_for_this_group:
                # This Authentik user was in the group but is no longer in the target set from Mattermost
                removal_base_info = {
                    "mm_username": auth_username_for_check or f"AuthUserPK_{auth_pk_in_group_obj}",
                    "mm_user_email": auth_user_details.get("email", "N/A") if auth_user_details else "N/A",
                    "mm_channel_display_name": mm_channel_display_name_for_log,
                    "target_resource_name": auth_group_name,
                }
                removal_result = {
                    **removal_base_info,
                    "service": "AUTHENTIK",
                    "status": "FAILURE",  # Default to failure
                    "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
                }
                if authentik_client.remove_user_from_group(auth_group_pk, auth_pk_in_group_obj):
                    removal_result.update({"status": "SUCCESS", "action": "USER_REMOVED_FROM_AUTHENTIK_GROUP"})
                else:
                    removal_result["error_message"] = "API call to remove user from Authentik group failed."
                results.append(removal_result)
    return results


def _ensure_users_in_outline_collection(
    outline_client: "OutlineClient",
    mattermost_client: "MattermostClient",  # For DMs
    collection_id: str,
    collection_name: str,
    mm_users_for_permission: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    default_permission: str,
    admin_permission: str,
    current_outline_member_ids: set,  # Set of Outline user IDs currently in the collection
    mm_channel_context_name: str,
) -> tuple[list[dict], set]:  # Returns results and set of targeted Outline user IDs
    """
    Ensures that the given Mattermost users are members of the specified Outline collection
    with the correct permissions. Adds or updates users in the collection.
    Sends DMs for new additions.
    Returns a list of action results and a set of Outline user IDs that were targeted.
    """
    results = []
    targeted_outline_user_ids = set()

    if not collection_id:
        logging.error(
            f"No Outline collection ID provided to _ensure_users_in_outline_collection for collection name {collection_name}."
        )
        return results, targeted_outline_user_ids

    for email_lower, mm_user_data in mm_users_for_permission.items():
        mm_username = mm_user_data["username"]
        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": collection_name,
            "service": "OUTLINE",
        }
        outline_result = {**base_user_info, "status": "FAILURE", "action": "OUTLINE_COLLECTION_UNCHANGED"}

        if mm_username in config.EXCLUDED_USERS:
            logging.debug(
                f"User '{mm_username}' is excluded. Skipping Outline ensure for collection '{collection_name}'."
            )
            # If an excluded user is already in the collection, their ID should be added to
            # targeted_outline_user_ids by the caller (_sync_single_outline_collection)
            # to prevent removal. This function focuses on adding non-excluded users.
            continue

        outline_user_api = outline_client.get_user_by_email(email_lower)
        if not outline_user_api:
            outline_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_OUTLINE_FOR_ENSURE",
                    "error_message": f"User email '{email_lower}' not found in Outline.",
                }
            )
            results.append(outline_result)
            continue

        outline_user_id = outline_user_api.get("id")
        targeted_outline_user_ids.add(outline_user_id)

        permission_to_set = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
        is_already_member = outline_user_id in current_outline_member_ids

        action_verb_prefix = (
            "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"
            if is_already_member
            else f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{permission_to_set.upper()}_ACCESS"
        )

        if outline_client.add_user_to_collection(collection_id, outline_user_id, permission=permission_to_set):
            current_action = action_verb_prefix
            outline_result.update({"status": "SUCCESS"})

            if not is_already_member:  # Send DM only on first add
                coll_details = outline_client.get_collection_details(collection_id)
                if (
                    coll_details
                    and coll_details.get("name")
                    and coll_details.get("urlId")
                    and mm_user_data.get("mm_user_id")
                ):
                    coll_name_for_dm = coll_details.get("name")
                    collection_url_id = coll_details.get("urlId")
                    outline_base_url = config.OUTLINE_URL

                    if outline_base_url:
                        coll_url = f"{outline_base_url.rstrip('/')}/collection/{collection_url_id}"
                        dm_text = (
                            f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline "
                            f"**{coll_name_for_dm}**.\nVous pouvez y accéder ici : {coll_url}"
                        )
                        if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                            current_action = f"{action_verb_prefix}_AND_DM_SENT"
                        else:
                            current_action = f"{action_verb_prefix}_DM_FAILED"
                    else:
                        logging.warning(
                            f"OUTLINE_URL not configured. Cannot send DM for Outline collection '{coll_name_for_dm}' to user '{mm_username}'."
                        )
                        current_action = f"{action_verb_prefix}_DM_SKIPPED_NO_URL"
                elif mm_user_data.get("mm_user_id"):
                    logging.warning(
                        f"Could not send DM for Outline collection (ID: {collection_id}) to user '{mm_username}' due to missing details."
                    )
                    if not config.OUTLINE_URL:
                        current_action = f"{action_verb_prefix}_DM_SKIPPED_NO_URL"
                    elif not (coll_details and coll_details.get("name") and coll_details.get("urlId")):
                        current_action = f"{action_verb_prefix}_DM_SKIPPED_INCOMPLETE_COLL_DETAILS"
                    else:
                        current_action = f"{action_verb_prefix}_DM_SKIPPED_UNKNOWN_REASON"
            outline_result["action"] = current_action
        else:
            verb_failed = (
                "FAILED_TO_UPDATE_OUTLINE_PERMISSION" if is_already_member else "FAILED_TO_ADD_TO_OUTLINE_COLLECTION"
            )
            outline_result.update({"action": verb_failed, "error_message": "API call to Outline failed."})

        results.append(outline_result)

    return results, targeted_outline_user_ids


def _sync_single_outline_collection(
    outline_client: "OutlineClient",
    mattermost_client: "MattermostClient",
    collection_name: str,
    mm_users_for_permission: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    default_permission: str,
    admin_permission: str,
    mm_channel_context_name: str,  # For logging/reporting context
    perform_deletions: bool,
) -> list[dict]:
    results = []
    # Attempt to get or create the Outline collection.
    # Assuming outline_client.create_group ensures the collection exists and returns its object, or None on failure.
    # The name `create_group` is a bit generic if it's also used for getting; `ensure_collection_exists` might be clearer.
    # For now, using `create_group` as per existing code in `_create_resources_for_entity`.
    outline_collection_obj = outline_client.create_group(collection_name)  # Renamed from get_collection_by_name

    if not outline_collection_obj or not outline_collection_obj.get("id"):
        logging.error(f"Failed to get or create Outline collection '{collection_name}'. Cannot sync this collection.")
        return [
            {
                "service": "OUTLINE",
                "target_resource_name": collection_name,
                "status": "FAILURE",  # Changed from SKIPPED to FAILURE as creation was attempted
                "action": "FAILED_TO_ENSURE_OUTLINE_COLLECTION",
                "error_message": "Failed to get or create collection in Outline.",
            }
        ]

    outline_collection_id = outline_collection_obj.get("id")
    # get_collection_members should be called after we know the collection exists.
    current_outline_member_ids = set(outline_client.get_collection_members(outline_collection_id) or [])
    target_outline_ids_for_collection = set()
    # Map Outline user ID to their MM details (username, mm_user_id, email) for logging during removal
    outline_id_to_mm_user_map = (
        {}
    )  # This map will be populated by _ensure_users_in_outline_collection indirectly if needed, or built here for removals.
    # For excluded users, we still need to know their Outline ID if they are already members.

    # Populate outline_id_to_mm_user_map for all users in mm_users_for_permission
    # This is useful for the removal step to log details of users being removed.
    for email_lower, mm_user_data_val in mm_users_for_permission.items():
        temp_outline_user_obj = outline_client.get_user_by_email(email_lower)
        if temp_outline_user_obj and temp_outline_user_obj.get("id"):
            outline_id_to_mm_user_map[temp_outline_user_obj.get("id")] = {
                "username": mm_user_data_val.get("username"),
                "mm_user_id": mm_user_data_val.get("mm_user_id"),
                "email": email_lower,
            }

    # Preserve excluded users if they are already in the collection
    for email_l, mm_user_d in mm_users_for_permission.items():
        if mm_user_d.get("username") in config.EXCLUDED_USERS:
            excluded_outline_user = outline_client.get_user_by_email(email_l)
            if excluded_outline_user and excluded_outline_user.get("id") in current_outline_member_ids:
                target_outline_ids_for_collection.add(excluded_outline_user.get("id"))
                logging.info(
                    f"User '{mm_user_d.get('username')}' is excluded and already in Outline collection '{collection_name}'. Will be preserved."
                )

    # Ensure users from Mattermost channels are in the Outline collection
    add_update_results, mm_targeted_outline_ids = _ensure_users_in_outline_collection(
        outline_client=outline_client,
        mattermost_client=mattermost_client,
        collection_id=outline_collection_id,
        collection_name=collection_name,
        mm_users_for_permission=mm_users_for_permission,
        default_permission=default_permission,
        admin_permission=admin_permission,
        current_outline_member_ids=current_outline_member_ids,
        mm_channel_context_name=mm_channel_context_name,
    )
    results.extend(add_update_results)
    target_outline_ids_for_collection.update(mm_targeted_outline_ids)

    # Removal logic: Only if perform_deletions is True
    if perform_deletions:
        for outline_member_id in list(current_outline_member_ids):  # Iterate over a copy
            mm_user_details_for_this_outline_member = outline_id_to_mm_user_map.get(outline_member_id)

            is_excluded_member = False
            if (
                mm_user_details_for_this_outline_member  # Check if we have MM details for this Outline ID
                and mm_user_details_for_this_outline_member.get("username") in config.EXCLUDED_USERS
            ):
                is_excluded_member = True
            # If mm_user_details_for_this_outline_member is None, it means this Outline user
            # was not found in any of the source Mattermost channels for this entity.
            # If they are not excluded, they are a candidate for removal.

            if is_excluded_member:
                logging.info(
                    f"Outline user '{mm_user_details_for_this_outline_member.get('username')}' (ID: {outline_member_id}) "
                    f"is excluded and already in collection '{collection_name}'. Will not be removed by sync."
                )
                # Ensure they are not accidentally removed if they weren't processed in the add loop
                # (e.g. not in any MM channel but should remain in Outline due to exclusion)
                target_outline_ids_for_collection.add(outline_member_id)
                continue  # Skip to next member

            if outline_member_id not in target_outline_ids_for_collection:
                # This Outline user was a member but is no longer in the target set from Mattermost users
                # AND is not an excluded user who should remain.
                username_for_log = f"OutlineUser_{outline_member_id}"  # Default if no MM mapping
                user_email_for_log = "N/A"  # Default
                if mm_user_details_for_this_outline_member:  # We have MM details for this user
                    username_for_log = mm_user_details_for_this_outline_member.get("username", username_for_log)
                    user_email_for_log = mm_user_details_for_this_outline_member.get("email", "N/A")
                else:  # No MM details, try to get email from Outline directly for logging
                    outline_user_obj = outline_client.get_user_by_id(
                        outline_member_id
                    )  # Assumes get_user_by_id exists
                    if outline_user_obj:
                        user_email_for_log = outline_user_obj.get("email", "N/A")
                        username_for_log = outline_user_obj.get(
                            "name", username_for_log
                        )  # Outline 'name' might be display name

                removal_base_info = {
                    "mm_username": username_for_log,  # Best effort username
                    "mm_user_email": user_email_for_log,  # Best effort email
                    "mm_channel_display_name": mm_channel_context_name,  # Context of the sync operation
                    "target_resource_name": collection_name,
                }
                removal_result = {
                    **removal_base_info,
                    "service": "OUTLINE",
                    "status": "FAILURE",  # Default
                    "action": "FAILED_TO_REMOVE_FROM_OUTLINE_COLLECTION",
                }
                if outline_client.remove_user_from_collection(outline_collection_id, outline_member_id):
                    removal_result.update({"status": "SUCCESS", "action": "USER_REMOVED_FROM_OUTLINE_COLLECTION"})
                else:
                    removal_result["error_message"] = "API call to remove user from Outline collection failed."
                results.append(removal_result)
    return results


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# Brevo Synchronization Logic (merged from brevo_sync_utils.py)
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
def _ensure_contacts_in_brevo_list(
    brevo_client: "BrevoClient",
    list_id: int,
    list_name: str,
    mm_users_to_ensure: list[dict],  # Users from Mattermost channel
    mm_channel_display_name_for_log: str,
) -> tuple[list[dict], set]:  # Returns results and set of targeted emails
    """
    Ensures that the given Mattermost users are contacts in the specified Brevo list.
    Adds contacts to the list. The Brevo client handles idempotency.
    Returns a list of action results and a set of emails that were targeted.
    """
    results = []
    targeted_emails = set()

    if not list_id:
        logging.error(f"No Brevo list ID provided to _ensure_contacts_in_brevo_list for list name {list_name}.")
        return results, targeted_emails

    for mm_user in mm_users_to_ensure:
        mm_username = mm_user.get("username", "UnknownUser")
        mm_user_email = mm_user.get("email")

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user_email or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name_for_log,
            "target_resource_name": list_name,
            "service": "BREVO",
        }

        if mm_username in config.EXCLUDED_USERS:
            logging.debug(f"User '{mm_username}' is excluded. Skipping Brevo ensure for list '{list_name}'.")
            continue

        if not mm_user_email:
            results.append(
                {
                    **base_user_info,
                    "status": "SKIPPED",
                    "action": "SKIPPED_NO_MM_EMAIL_FOR_BREVO_ENSURE",
                    "error_message": "User has no email in Mattermost for Brevo.",
                }
            )
            continue

        targeted_emails.add(mm_user_email.lower())

        # The add_contact_to_list method in BrevoClient is idempotent.
        # It returns True if the contact is successfully added or already exists in the list.
        # It returns False if the API call fails for other reasons.
        if brevo_client.add_contact_to_list(email=mm_user_email, list_id=list_id):
            results.append(
                {
                    **base_user_info,
                    "status": "SUCCESS",
                    "action": "USER_ENSURED_IN_BREVO_LIST",
                }
            )
        else:
            results.append(
                {
                    **base_user_info,
                    "status": "FAILURE",
                    "action": "FAILED_TO_ENSURE_IN_BREVO_LIST",
                    "error_message": f"API call to add/ensure contact '{mm_user_email}' in Brevo list '{list_name}' failed.",
                }
            )

    return results, targeted_emails


def _sync_single_brevo_list(
    brevo_client: "BrevoClient",
    brevo_list_name: str,
    mm_users_in_channel: list[dict],  # Users from the Mattermost channel
    mm_channel_display_name_for_log: str,
    perform_deletions: bool,
) -> list[dict]:
    """
    Synchronizes a single Brevo contact list with members of a Mattermost channel.
    - Creates the list in Brevo if it doesn't exist.
    - Adds Mattermost channel members to the list.
    - Removes users from the list if they are no longer in the Mattermost channel (if perform_deletions is True).
    - Excludes users defined in EXCLUDED_USERS.
    """
    results = []
    logging.info(
        f"Starting Brevo list sync for '{brevo_list_name}' based on MM channel '{mm_channel_display_name_for_log}'. "
        f"Deletions: {perform_deletions}"
    )

    if not brevo_client:
        logging.error("Brevo client not provided to _sync_single_brevo_list.")
        return results

    # 1. Get or Create the Brevo list
    brevo_lists = brevo_client.get_lists(name=brevo_list_name)
    brevo_list_obj = brevo_lists[0] if brevo_lists else None
    if not brevo_list_obj:
        brevo_list_obj = brevo_client.create_list(brevo_list_name)
        if not brevo_list_obj:
            logging.error(f"Failed to create or retrieve Brevo list '{brevo_list_name}'. Skipping sync for this list.")
            results.append(
                {
                    "service": "BREVO",
                    "target_resource_name": brevo_list_name,
                    "status": "FAILURE",
                    "action": "FAILED_TO_ENSURE_BREVO_LIST",
                    "error_message": f"Could not create or find Brevo list '{brevo_list_name}'.",
                }
            )
            return results

    brevo_list_id = brevo_list_obj["id"]
    logging.info(f"Ensured Brevo list '{brevo_list_name}' (ID: {brevo_list_id}) exists.")

    # 2. Process Mattermost users for adding to the list
    # target_emails_in_list will be populated by _ensure_contacts_in_brevo_list
    # and also needs to account for excluded users if they were already in the list (though Brevo sync typically doesn't preserve them if not in MM)

    # For Brevo, excluded users are typically NOT added. If they are in a list and removed from MM channel,
    # they would be removed by the deletion logic if perform_deletions is true.
    # So, we don't need special handling for target_emails_in_list for excluded users here.

    add_results, mm_targeted_emails = _ensure_contacts_in_brevo_list(
        brevo_client,
        brevo_list_id,
        brevo_list_name,
        mm_users_in_channel,
        mm_channel_display_name_for_log,
    )
    results.extend(add_results)
    target_emails_in_list = mm_targeted_emails  # These are the emails that should be in the list based on MM users

    # 3. Handle removals if perform_deletions is True
    if perform_deletions:
        logging.info(f"Performing deletions for Brevo list '{brevo_list_name}' (ID: {brevo_list_id}).")
        current_contacts_in_brevo_list = []
        offset = 0
        limit = 50
        while True:
            page_contacts = brevo_client.get_contacts_from_list(brevo_list_id, limit=limit, offset=offset)
            if page_contacts:
                current_contacts_in_brevo_list.extend(page_contacts)
                if len(page_contacts) < limit:
                    break
                offset += limit
            else:
                logging.warning(
                    f"Could not fetch contacts from Brevo list '{brevo_list_name}' (ID: {brevo_list_id}) for deletion check, or list is empty."
                )
                break

        current_emails_in_brevo_list = {
            contact.get("email", "").lower() for contact in current_contacts_in_brevo_list if contact.get("email")
        }
        emails_to_remove = current_emails_in_brevo_list - target_emails_in_list

        for email_to_remove in emails_to_remove:
            mm_username_for_log = "UnknownUser (removed)"
            base_removal_info = {
                "mm_username": mm_username_for_log,
                "mm_user_email": email_to_remove,
                "mm_channel_display_name": mm_channel_display_name_for_log,
                "target_resource_name": brevo_list_name,
                "service": "BREVO",
            }
            if brevo_client.remove_contact_from_list(email=email_to_remove, list_id=brevo_list_id):
                results.append(
                    {
                        **base_removal_info,
                        "status": "SUCCESS",
                        "action": "USER_REMOVED_FROM_BREVO_LIST",
                    }
                )
            else:
                results.append(
                    {
                        **base_removal_info,
                        "status": "FAILURE",
                        "action": "FAILED_TO_REMOVE_FROM_BREVO_LIST",
                        "error_message": f"API call to remove contact '{email_to_remove}' from Brevo list '{brevo_list_name}' failed.",
                    }
                )

    logging.info(f"Finished Brevo list sync for '{brevo_list_name}'. Total results: {len(results)}")
    return results


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# End of Brevo Synchronization Logic
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


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
                "status": "FAILURE",
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
        logging.info("TOOLS_TO_MM: Vaultwarden sync is additive only. Skipping.")
        pass

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


def _sync_single_vaultwarden_collection_members(
    vaultwarden_client: "VaultwardenClient",
    mattermost_client: "MattermostClient",  # Added MattermostClient for DMs
    collection_name: str,
    mm_users_for_services: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    mm_channel_context_name: str,  # For logging/reporting context
) -> list[dict]:
    """
    Ensures all users from mm_users_for_services are invited to the specified Vaultwarden collection and sends a DM.
    This function is additive; it only invites users and does not remove them based on MM channel membership.
    """
    results = []
    logging.info(
        f"Starting Vaultwarden collection member sync for '{collection_name}' based on MM channel '{mm_channel_context_name}'."
    )

    if not vaultwarden_client.api_username or not vaultwarden_client.api_password:
        logging.warning(f"Vaultwarden API credentials not configured. Skipping member sync for '{collection_name}'.")
        return [
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "SKIPPED",
                "action": "SKIPPED_MISSING_API_CREDENTIALS",
                "error_message": "Vaultwarden API username or password not set.",
            }
        ]

    collection_id = vaultwarden_client.get_collection_by_name(collection_name)
    if not collection_id:
        logging.warning(
            f"Vaultwarden collection '{collection_name}' not found. It should be created by entity creation command."
        )
        return [
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "SKIPPED",
                "action": "SKIPPED_VW_COLLECTION_NOT_FOUND",
                "error_message": f"Collection '{collection_name}' not found.",
            }
        ]

    access_token = vaultwarden_client._get_api_token()
    if not access_token:
        logging.error(f"Failed to obtain Vaultwarden API token for collection '{collection_name}'.")
        return [
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "FAILURE",
                "action": "FAILED_TO_GET_VW_API_TOKEN",
                "error_message": "Could not obtain API token.",
            }
        ]

    # Ensure users are invited
    invite_results = _ensure_users_invited_to_vaultwarden_collection(
        vaultwarden_client=vaultwarden_client,
        mattermost_client=mattermost_client,
        collection_id=collection_id,
        collection_name=collection_name,
        mm_users_for_services=mm_users_for_services,
        mm_channel_context_name=mm_channel_context_name,
        access_token=access_token,
    )
    results.extend(invite_results)

    # Vaultwarden sync is additive only, no removal logic based on MM channel membership.
    logging.info(f"Finished Vaultwarden collection member sync for '{collection_name}'. Total results: {len(results)}")
    return results


def _remove_user_from_outline_collection(
    outline_client: "OutlineClient",
    collection_id: str,
    collection_name: str,
    user_id: str,
    user_email: str,
    mm_channel_context_name: str,
) -> dict:
    """Removes a user from an Outline collection and returns a result dictionary."""
    result = {
        "service": "OUTLINE",
        "target_resource_name": collection_name,
        "mm_user_email": user_email,
        "mm_channel_display_name": mm_channel_context_name,
        "status": "FAILURE",
        "action": "FAILED_TO_REMOVE_FROM_OUTLINE_COLLECTION",
    }
    if outline_client.remove_user_from_collection(collection_id, user_id):
        result["status"] = "SUCCESS"
        result["action"] = "USER_REMOVED_FROM_OUTLINE_COLLECTION"
    else:
        result["error_message"] = "API call to remove user from Outline collection failed."
    return result


def _remove_user_from_nocodb_base(
    nocodb_client: "NocoDBClient",
    base_id: str,
    base_title: str,
    user_id: str,
    user_email: str,
    mm_channel_context_name: str,
) -> dict:
    """Removes a user from a NocoDB base and returns a result dictionary."""
    result = {
        "service": "NOCODB",
        "target_resource_name": base_title,
        "mm_user_email": user_email,
        "mm_channel_display_name": mm_channel_context_name,
        "status": "FAILURE",
        "action": "FAILED_TO_REMOVE_NOCODB_USER",
    }
    if nocodb_client.delete_base_user(base_id, user_id):
        result["status"] = "SUCCESS"
        result["action"] = "NOCODB_USER_REMOVED_FROM_BASE"
    else:
        result["error_message"] = "API call to remove user from NoCoDB base failed."
    return result


def remove_user_from_authentik_group(
    authentik_client: "AuthentikClient",
    group_pk: str,
    group_name: str,
    user_pk: int,
    user_email: str,
    mm_channel_context_name: str,
) -> dict:
    """Removes a user from an Authentik group and returns a result dictionary."""
    result = {
        "service": "AUTHENTIK",
        "target_resource_name": group_name,
        "mm_user_email": user_email,
        "mm_channel_display_name": mm_channel_context_name,
        "status": "FAILURE",
        "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
    }
    if authentik_client.remove_user_from_group(group_pk, user_pk):
        result["status"] = "SUCCESS"
        result["action"] = "USER_REMOVED_FROM_AUTHENTIK_GROUP"
    else:
        result["error_message"] = "API call to remove user from Authentik group failed."
    return result
