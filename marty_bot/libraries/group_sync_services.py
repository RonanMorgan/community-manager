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
    from clients.nocodb_client import NocoDBClient  # Added NocoDBClient


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
    nocodb_client: Optional["NocoDBClient"],  # Added NocoDBClient
    mm_team_id: str,
    base_name: str,
    entity_key: str,
    entity_config: dict,
    all_authentik_groups_by_name: dict,
    email_to_authentik_user_pk_map: dict,
    perform_deletions: bool,
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
    nocodb_cfg = entity_config.get("nocodb", {})  # Added NocoDB config

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
    if nocodb_client and nocodb_cfg and entity_key in ["ANTENNE", "POLES"]:
        nocodb_base_title_pattern = nocodb_cfg.get("base_title_pattern", "nocodb_{base_name}")
        # base_name is the entity's base name (e.g., "MyAntenne")
        # mm_users_for_services contains the necessary user details including 'is_admin_channel_member'
        default_nocodb_permission = nocodb_cfg.get("default_access", "viewer")
        admin_nocodb_permission = nocodb_cfg.get("admin_access", "owner")
        results.extend(
            _sync_single_nocodb_base(
                nocodb_client,
                nocodb_base_title_pattern,
                base_name,  # This is the base_name of the entity (e.g. "MonAntenne")
                mm_users_for_services,  # Combined user list with admin flag
                default_nocodb_permission,
                admin_nocodb_permission,
                std_mm_channel_name_for_log,  # Context for logging
                perform_deletions,
            )
        )

    logging.info(f"Finished sync for entity '{base_name}'. Total results: {len(results)}")
    return results


def _sync_single_nocodb_base(
    nocodb_client: "NocoDBClient",
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
    target_nocodb_user_emails = set()  # Set of emails that should be in the base

    for email_lower, mm_user_data in mm_users_for_permission.items():
        mm_username = mm_user_data["username"]

        if mm_username in config.EXCLUDED_USERS:
            logging.debug(
                f"User '{mm_username}' is excluded. Skipping NoCoDB sync for base '{nocodb_base_title}'."
            )  # DEBUG
            if (
                email_lower in current_nocodb_users_map
            ):  # If excluded user is already there, ensure they are not removed
                target_nocodb_user_emails.add(email_lower)
            continue

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": nocodb_base_title,
            "service": "NOCODB",
        }
        nocodb_result = {**base_user_info, "status": "FAILURE", "action": "NOCODB_USER_UNCHANGED"}

        target_role = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
        target_nocodb_user_emails.add(email_lower)  # Mark this email as "should be in base"

        existing_nocodb_user = current_nocodb_users_map.get(email_lower)

        if existing_nocodb_user:
            # User exists in NoCoDB base, check if role needs update
            nocodb_user_id = existing_nocodb_user["id"]
            current_role = existing_nocodb_user.get("roles")  # API returns "roles" as a string like "owner"
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
            # User not in NoCoDB base, invite them
            if nocodb_client.invite_user_to_base(base_id, email_lower, target_role):
                nocodb_result.update({"status": "SUCCESS", "action": f"NOCODB_USER_INVITED_AS_{target_role.upper()}"})
            else:
                # Check if the user exists in NocoDB but couldn't be invited (e.g. already invited but not accepted, or other issue)
                # This part might need more specific error handling based on NocoDBClient's invite_user_to_base behavior
                nocodb_result.update(
                    {"action": "FAILED_TO_INVITE_NOCODB_USER", "error_message": "API call to invite user failed."}
                )
        results.append(nocodb_result)

    if perform_deletions:
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
    current_auth_user_pks_in_group = set(auth_group_obj.get("users", []))
    auth_pk_to_auth_user_obj_map = {user.get("pk"): user for user in auth_group_obj.get("users_obj", [])}
    target_auth_pks_for_this_group = set()

    for mm_user in mm_users_in_corresponding_channel:
        mm_username = mm_user.get("username", "UnknownUser")
        mm_user_email_lower = mm_user.get("email", "").lower()
        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user.get("email") or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name_for_log,
            "target_resource_name": auth_group_name,
        }

        if mm_username in config.EXCLUDED_USERS:
            if mm_user_email_lower and mm_user_email_lower in email_to_authentik_user_pk_map:
                auth_pk = email_to_authentik_user_pk_map[mm_user_email_lower]
                if auth_pk in current_auth_user_pks_in_group:
                    target_auth_pks_for_this_group.add(auth_pk)
            continue

        if not mm_user_email_lower:
            # If no email, cannot map to Authentik user. Skip.
            # Log or add to results if needed, but for now, just continue.
            continue

        auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)
        auth_user_result = {
            **base_user_info,
            "service": "AUTHENTIK",
            "status": "FAILURE",
            "action": "AUTHENTIK_GROUP_UNCHANGED",  # Default action if nothing happens
        }

        if auth_pk_for_mm_user is None:
            auth_user_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_AUTHENTIK",
                    "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                }
            )
        else:
            target_auth_pks_for_this_group.add(auth_pk_for_mm_user)  # Mark this Authentik user as "should be in group"
            if auth_pk_for_mm_user not in current_auth_user_pks_in_group:
                if authentik_client.add_user_to_group(auth_group_pk, auth_pk_for_mm_user):
                    auth_user_result.update({"status": "SUCCESS", "action": "USER_ADDED_TO_AUTHENTIK_GROUP"})
                else:
                    auth_user_result.update(
                        {  # Status remains FAILURE
                            "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                            "error_message": "API call to add user to Authentik group failed.",
                        }
                    )
            else:
                auth_user_result.update({"status": "SUCCESS", "action": "USER_ALREADY_IN_AUTHENTIK_GROUP"})
        results.append(auth_user_result)

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
    outline_id_to_mm_user_map = {}

    for email_lower, mm_user_data in mm_users_for_permission.items():
        mm_username = mm_user_data["username"]

        if mm_username in config.EXCLUDED_USERS:
            logging.info(
                f"User '{mm_username}' is in EXCLUDED_USERS list, skipping Outline collection add/permission update for '{collection_name}'."
            )
            # If an excluded user is already in the collection, ensure they are not removed by adding their Outline ID
            # to the target set if they are a current member.
            temp_outline_user = outline_client.get_user_by_email(email_lower)
            if temp_outline_user and temp_outline_user.get("id") in current_outline_member_ids:
                target_outline_ids_for_collection.add(temp_outline_user.get("id"))
                # Populate map for removal loop's exclusion check (though primarily for logging if not excluded)
                outline_id_to_mm_user_map[temp_outline_user.get("id")] = {
                    "username": mm_username,
                    "mm_user_id": mm_user_data.get("mm_user_id"),  # For DM context if needed
                    "email": email_lower,  # For logging
                }
            continue

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,  # Already lowercased
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": collection_name,
        }
        outline_user_api = outline_client.get_user_by_email(email_lower)  # API should handle case if necessary
        outline_result = {
            **base_user_info,
            "service": "OUTLINE",
            "status": "FAILURE",  # Default
            "action": "OUTLINE_COLLECTION_UNCHANGED",  # Default
        }

        if not outline_user_api:
            outline_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_OUTLINE",
                    "error_message": f"User email '{email_lower}' not found in Outline.",
                }
            )
        else:
            outline_user_id = outline_user_api.get("id")
            target_outline_ids_for_collection.add(outline_user_id)
            # Store MM details mapped to Outline ID for potential use in removal logging
            outline_id_to_mm_user_map[outline_user_id] = {
                "username": mm_username,
                "mm_user_id": mm_user_data["mm_user_id"],
                "email": email_lower,
            }

            permission_to_set = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
            is_already_member = outline_user_id in current_outline_member_ids
            action_verb = (
                "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"
                if is_already_member
                else f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{permission_to_set.upper()}_ACCESS"
            )

            if outline_client.add_user_to_collection(
                outline_collection_id, outline_user_id, permission=permission_to_set
            ):
                outline_result.update({"status": "SUCCESS", "action": action_verb})
                if not is_already_member:  # Send DM only on first add
                    coll_details = outline_client.get_collection_details(outline_collection_id)
                    if coll_details and coll_details.get("name") and mm_user_data["mm_user_id"]:
                        coll_name_for_dm = coll_details.get("name")
                        # Construct URL (assuming slugify logic or direct link if available)
                        # For simplicity, using a placeholder or assuming direct ID linking if Outline supports it
                        # A more robust URL might involve slugifying the collection name + ID.
                        slug_part = slugify(coll_name_for_dm)  # Ensure slugify is available or imported
                        outline_base_url = config.OUTLINE_URL or "http://default-outline.com"  # From config
                        coll_url = f"{outline_base_url.rstrip('/')}/collection/{slug_part}-{outline_collection_id}"
                        dm_text = (
                            f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline "
                            f"**{coll_name_for_dm}**.\nVous pouvez y accéder ici : {coll_url}"
                        )
                        if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                            outline_result["action"] = f"{action_verb}_AND_DM_SENT"
                        else:
                            outline_result["action"] = f"{action_verb}_DM_FAILED"
            else:
                verb_failed = (
                    "FAILED_TO_UPDATE_OUTLINE_PERMISSION"
                    if is_already_member
                    else "FAILED_TO_ADD_TO_OUTLINE_COLLECTION"
                )
                outline_result.update({"action": verb_failed, "error_message": "API call to Outline failed."})
        results.append(outline_result)

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
    brevo_list_obj = brevo_client.get_list_by_name(brevo_list_name)
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
    target_emails_in_list = set()  # Emails that should be in the Brevo list

    for mm_user in mm_users_in_channel:
        mm_username = mm_user.get("username", "UnknownUser")
        mm_user_email = mm_user.get("email")

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user_email or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name_for_log,
            "target_resource_name": brevo_list_name,
            "service": "BREVO",
        }

        if mm_username in config.EXCLUDED_USERS:
            logging.info(f"User '{mm_username}' is excluded. Skipping Brevo list add for '{brevo_list_name}'.")
            continue

        if not mm_user_email:
            results.append(
                {
                    **base_user_info,
                    "status": "SKIPPED",
                    "action": "SKIPPED_NO_MM_EMAIL",
                    "error_message": "User has no email in Mattermost.",
                }
            )
            continue

        target_emails_in_list.add(mm_user_email.lower())

        if brevo_client.add_contact_to_list(email=mm_user_email, list_id=brevo_list_id):
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
                    "action": "FAILED_TO_ADD_TO_BREVO_LIST",
                    "error_message": f"API call to add contact '{mm_user_email}' to Brevo list '{brevo_list_name}' failed.",
                }
            )

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


def orchestrate_group_synchronization(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],
    brevo_client: Optional["BrevoClient"],
    nocodb_client: Optional["NocoDBClient"],  # Added NocoDB client
    mm_team_id: str,
    perform_deletions: bool = True,
    fetch_remote_members: bool = True,
) -> tuple[bool, list[dict]]:
    logging.info(
        f"Starting group synchronization task... "
        f"(Perform Deletions: {perform_deletions}, Fetch Remote Members: {fetch_remote_members})"
    )
    detailed_results = []

    # Client checks
    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Authentik sync will be skipped.")
        # Not returning False, as other services might still sync.
    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed with core logic.")
        return False, detailed_results  # Mattermost is essential for user/group discovery
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    if not outline_client:
        logging.info("Outline client not provided. Outline synchronization will be skipped.")
    if not brevo_client:
        logging.info("Brevo client not provided. Brevo synchronization will be skipped.")
    if not nocodb_client:
        logging.info("NocoDB client not provided. NocoDB synchronization will be skipped.")

    # Fetch all Authentik users for email-to-PK mapping if Authentik client is available
    # This map is crucial for Authentik operations.
    # However, fetching all groups is conditional.
    _, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)  # We always need the email map
    if not email_to_auth_pk_map:
        logging.warning(
            "Authentik email-to-user-PK map is empty. Authentik sync operations might not find users effectively."
        )

    all_auth_groups_by_name = {}
    entities_to_process = {}  # Stores { (entity_key, base_name): entity_config }

    if fetch_remote_members:
        logging.info("Fetching all Authentik groups to discover entities...")
        all_auth_groups_list = []  # Initialize to empty list
        if authentik_client:  # Check if client exists before using
            all_auth_groups_list, _ = authentik_client.get_groups_with_users()  # email_map already fetched
            if not all_auth_groups_list:
                logging.info("No Authentik groups found or an error occurred during fetching for discovery.")
            all_auth_groups_by_name = {g["name"]: g for g in all_auth_groups_list}
        else:
            logging.warning("Authentik client not available for fetching remote groups by Authentik discovery.")
            # all_auth_groups_list is already empty, all_auth_groups_by_name will be empty too.

        if not all_auth_groups_list:  # This check remains, covers both missing client and no groups found
            logging.info(
                "No Authentik groups found to process based on remote member fetching. Synchronization might be limited."
            )
            # Depending on strictness, could return early, or proceed if MM discovery is also planned
        # all_auth_groups_by_name is defined inside the if authentik_client block, ensure it's initialized if client is None
        if not authentik_client:
            all_auth_groups_by_name = {}

        for auth_group_name_iter in all_auth_groups_by_name.keys():
            found_entity_key_auth, current_base_name_auth = _map_auth_group_to_entity_and_base_name(
                auth_group_name_iter, config.PERMISSIONS_MATRIX
            )
            if found_entity_key_auth and current_base_name_auth:
                entity_tuple = (found_entity_key_auth, current_base_name_auth)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_auth]
            else:
                logging.debug(f"Authentik group '{auth_group_name_iter}' did not map to a known entity pattern.")
    else:
        logging.info("Discovering entities to process based on Mattermost channels...")
        mm_channels = mattermost_client.get_channels_for_team(mm_team_id)
        if not mm_channels:
            logging.warning("No Mattermost channels found for the team. Cannot discover entities via Mattermost.")
            return True, detailed_results  # Nothing to process

        for channel in mm_channels:
            channel_name = channel.get("name")  # This is the slugified name
            channel_display_name = channel.get("display_name")

            found_entity_key_mm, current_base_name_mm = _map_mm_channel_to_entity_and_base_name(
                channel_name, channel_display_name, config.PERMISSIONS_MATRIX  # Pass both for flexibility
            )
            if found_entity_key_mm and current_base_name_mm:
                entity_tuple = (found_entity_key_mm, current_base_name_mm)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_mm]
                    logging.info(
                        f"Discovered entity '{current_base_name_mm}' (type: {found_entity_key_mm}) from MM channel '{channel_display_name}'."
                    )
            else:
                logging.debug(
                    f"MM channel '{channel_display_name}' (slug: {channel_name}) did not map to a known entity pattern."
                )

    if not entities_to_process:
        logging.info("No entities found to process after discovery phase. Synchronization finished.")
        return True, detailed_results

    for (entity_key, base_name), entity_config_to_use in entities_to_process.items():
        logging.info(
            f"Orchestrating sync for entity: {entity_key}, base_name: {base_name}, "
            f"perform_deletions: {perform_deletions}, fetch_remote_members mode was: {fetch_remote_members}"
        )
        # When fetch_remote_members is False, all_auth_groups_by_name is initially empty.
        # sync_entity_permissions will need to handle this by potentially fetching/creating groups on demand.
        entity_sync_results = sync_entity_permissions(
            authentik_client,
            mattermost_client,
            outline_client,
            brevo_client,
            nocodb_client,  # Pass NocoDB client
            mm_team_id,
            base_name,
            entity_key,
            entity_config_to_use,
            all_auth_groups_by_name,  # This will be populated if fetch_remote_members=True, empty otherwise
            email_to_auth_pk_map,
            perform_deletions,
        )
        detailed_results.extend(entity_sync_results)

    log_msg = (
        f"Synchronization task completed. Mode (fetch_remote: {fetch_remote_members}, deletions: {perform_deletions}). "
        f"Processed {len(entities_to_process)} unique entities. "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results


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
