import logging
from typing import TYPE_CHECKING, Optional

from app import config
from app.enums import SyncStatus
from clients.nocodb_client import NocoDBAction

if TYPE_CHECKING:
    from clients.mattermost_client import MattermostClient
    from clients.nocodb_client import NocoDBClient


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
                    "status": SyncStatus.SKIPPED.value,
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
                removal_result = {**removal_base_info, "status": SyncStatus.FAILURE.value, "action": "FAILED_TO_REMOVE_NOCODB_USER"}
                if nocodb_client.delete_base_user(base_id, nocodb_user_id_to_remove):
                    removal_result.update({"status": SyncStatus.SUCCESS.value, "action": NocoDBAction.USER_REMOVED_FROM_BASE.value})
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
                        {"status": SyncStatus.SUCCESS.value, "action": f"NOCODB_USER_ROLE_UPDATED_TO_{target_role.upper()}"}
                    )
                else:
                    nocodb_result.update(
                        {
                            "action": "FAILED_TO_UPDATE_NOCODB_USER_ROLE",
                            "error_message": "API call to update user role failed.",
                        }
                    )
            else:
                nocodb_result.update({"status": SyncStatus.SUCCESS.value, "action": "NOCODB_USER_ALREADY_IN_BASE_WITH_CORRECT_ROLE"})
        else:
            action_verb = f"NOCODB_USER_INVITED_AS_{target_role.upper()}"
            if nocodb_client.invite_user_to_base(base_id, email_lower, target_role):
                nocodb_result.update({"status": SyncStatus.SUCCESS.value, "action": action_verb})
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
        "status": SyncStatus.FAILURE.value,
        "action": "FAILED_TO_REMOVE_NOCODB_USER",
    }
    if nocodb_client.delete_base_user(base_id, user_id):
        result["status"] = SyncStatus.SUCCESS.value
        result["action"] = NocoDBAction.USER_REMOVED_FROM_BASE.value
    else:
        result["error_message"] = "API call to remove user from NoCoDB base failed."
    return result


from .mattermost import _extract_base_name


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


def _sync_nocodb_for_entity(nocodb_client, mattermost_client, base_name, config, all_authentik_groups_by_name, email_to_authentik_user_pk_map, std_mm_users, admin_mm_users, mm_users_for_services, log_channel_name, perform_deletions, entity_key):
    if entity_key not in ["ANTENNE", "POLES"]:
        return []
    nocodb_base_title_pattern = config.get("base_title_pattern", "nocodb_{base_name}")
    default_permission = config.get("default_access", "viewer")
    admin_permission = config.get("admin_access", "owner")
    return _sync_single_nocodb_base(nocodb_client, mattermost_client, nocodb_base_title_pattern, base_name, mm_users_for_services, default_permission, admin_permission, log_channel_name, perform_deletions)
