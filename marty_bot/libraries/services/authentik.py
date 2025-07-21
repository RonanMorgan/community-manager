import logging
from typing import TYPE_CHECKING, Optional

import config
from app.enums import SyncStatus
from clients.authentik_client import AuthentikAction

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient


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

            # Let's stick to the plan: `_ensure_users_in_authentik_group` will do the loop and add logic.
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
                    auth_user_result.update(
                        {"status": SyncStatus.SUCCESS.value, "action": AuthentikAction.USER_ADDED_TO_GROUP.value}
                    )
                else:
                    auth_user_result.update(
                        {
                            "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                            "error_message": "API call to add user to Authentik group failed.",
                        }
                    )
            else:
                auth_user_result.update(
                    {"status": SyncStatus.SUCCESS.value, "action": AuthentikAction.USER_ALREADY_IN_GROUP.value}
                )
        results.append(auth_user_result)

    return results, targeted_auth_pks


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
                "status": SyncStatus.FAILURE.value,
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
                    "status": SyncStatus.FAILURE.value,
                    "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
                }
                if authentik_client.remove_user_from_group(auth_group_pk, auth_pk_in_group_obj):
                    removal_result.update(
                        {"status": SyncStatus.SUCCESS.value, "action": AuthentikAction.USER_REMOVED_FROM_GROUP.value}
                    )
                else:
                    removal_result["error_message"] = "API call to remove user from Authentik group failed."
                results.append(removal_result)
    return results


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
        "status": SyncStatus.FAILURE.value,
        "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
    }
    if authentik_client.remove_user_from_group(group_pk, user_pk):
        result["status"] = SyncStatus.SUCCESS.value
        result["action"] = AuthentikAction.USER_REMOVED_FROM_GROUP.value
    else:
        result["error_message"] = "API call to remove user from Authentik group failed."
    return result


from .mattermost import _extract_base_name


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


def _sync_authentik_for_entity(
    authentik_client,
    mattermost_client,
    base_name,
    config,
    all_authentik_groups_by_name,
    email_to_authentik_user_pk_map,
    std_mm_users,
    admin_mm_users,
    mm_users_for_services,
    log_channel_name,
    perform_deletions,
    entity_key,
):
    results = []
    std_auth_group_name = (
        config["standard"].get("authentik_group_name_pattern", "{base_name}").format(base_name=base_name)
    )
    std_auth_group_obj = all_authentik_groups_by_name.get(std_auth_group_name)
    if not std_auth_group_obj:
        std_auth_group_obj = authentik_client.get_group_by_name(std_auth_group_name) or authentik_client.create_group(
            std_auth_group_name
        )
    if std_auth_group_obj:
        results.extend(
            _sync_single_authentik_group(
                authentik_client,
                std_auth_group_obj,
                std_mm_users,
                email_to_authentik_user_pk_map,
                log_channel_name,
                perform_deletions,
            )
        )

    if config.get("admin"):
        adm_auth_group_name = (
            config["admin"].get("authentik_group_name_pattern", "{base_name} Admin").format(base_name=base_name)
        )
        adm_auth_group_obj = all_authentik_groups_by_name.get(adm_auth_group_name)
        if not adm_auth_group_obj:
            adm_auth_group_obj = authentik_client.get_group_by_name(
                adm_auth_group_name
            ) or authentik_client.create_group(adm_auth_group_name)
        if adm_auth_group_obj:
            results.extend(
                _sync_single_authentik_group(
                    authentik_client,
                    adm_auth_group_obj,
                    admin_mm_users,
                    email_to_authentik_user_pk_map,
                    log_channel_name,
                    perform_deletions,
                )
            )
    return results
