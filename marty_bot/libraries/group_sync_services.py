# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
from typing import TYPE_CHECKING

# Import client-specific utilities and classes for type hinting
from clients.mattermost_client import slugify

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient


def get_all_authentik_groups_and_user_map(authentik_client: "AuthentikClient"):
    """
    Fetches all Authentik groups and constructs a user email-to-PK map.
    Uses the get_groups_with_users method from AuthentikClient.
    """
    logging.info("Fetching all Authentik groups and constructing user email-to-PK map...")
    if not authentik_client:
        logging.error("Authentik client not provided to get_all_authentik_groups_and_user_map.")
        return [], {}

    groups, email_map = authentik_client.get_groups_with_users()  # This method handles pagination

    if not groups:
        logging.warning("No Authentik groups found or an error occurred during fetching.")
    if not email_map:
        logging.warning("Authentik user email-to-PK map is empty or could not be constructed.")

    return groups, email_map


def sync_single_authentik_group_with_mattermost(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    mm_team_id: str,
    authentik_group: dict,
    email_to_authentik_user_pk_map: dict,
) -> list[dict]:
    """
    Synchronizes members from a Mattermost channel (matched by name to the Authentik group)
    into the corresponding Authentik group.
    Returns a list of dictionaries, each detailing an attempted sync operation for a user.
    Returns an empty list if a critical setup error occurred or no operations were performed.
    """
    results = []
    if not authentik_client or not mattermost_client or not mm_team_id:
        logging.error("Client or team_id missing for sync_single_authentik_group_with_mattermost.")
        # In case of critical setup error, we might still want to return an error entry,
        # but the plan asks to change return type to list[dict], so an empty list is more consistent.
        # The higher level function `orchestrate_authentik_mattermost_sync` handles the boolean False for critical errors.
        return []

    auth_group_name = authentik_group.get("name")
    auth_group_pk = authentik_group.get("pk")
    current_auth_user_pks_in_group = set(authentik_group.get("users", []))

    if not auth_group_name or not auth_group_pk:
        logging.warning(f"Skipping Authentik group due to missing name or PK: {authentik_group}")
        return []

    logging.info(f"Processing sync for Authentik group: '{auth_group_name}' (PK: {auth_group_pk})")
    mm_channel_slug = slugify(auth_group_name)
    mm_channel = mattermost_client.get_channel_by_name(mm_team_id, mm_channel_slug)

    mm_channel_display_name = f"'{mm_channel_slug}' (derived from Authentik group)"
    if mm_channel:
        mm_channel_display_name = mm_channel.get("display_name", mm_channel_slug)

    if not mm_channel:
        logging.warning(
            f"No Mattermost channel found with slug '{mm_channel_slug}' "
            f"(derived from Authentik group '{auth_group_name}'). Skipping."
        )
        # results.append({ # Potentially add a record for this skip
        # "status": "SKIPPED_NO_MM_CHANNEL" ... })
        return []  # No user operations if no channel

    mm_channel_id = mm_channel.get("id")
    logging.info(f"Found corresponding Mattermost channel '{mm_channel_display_name}' " f"(ID: {mm_channel_id})")

    mm_users_in_channel = mattermost_client.get_users_in_channel(mm_channel_id)
    if not mm_users_in_channel:
        logging.info(
            f"No users in Mattermost channel '{mm_channel_display_name}'. "
            f"Nothing to sync to Authentik group '{auth_group_name}'."
        )
        return []

    logging.info(f"Found {len(mm_users_in_channel)} users in Mattermost channel " f"'{mm_channel_display_name}'.")

    for mm_user in mm_users_in_channel:
        mm_user_email = mm_user.get("email")
        mm_username = mm_user.get("username", "UnknownUsername")  # Default if username is missing

        user_result = {
            "mm_username": mm_username,
            "mm_user_email": mm_user_email or "NoEmailProvided",
            "auth_group_name": auth_group_name,
            "mm_channel_display_name": mm_channel_display_name,
            "status": "FAILURE",  # Default to failure, change on success
            "action": "SKIPPED_AUTHENTIK_GROUP_UNCHANGED",  # Default action
            "error_message": None,
        }

        if not mm_user_email:
            log_msg = (
                f"Mattermost user ID {mm_user.get('id')} (username: {mm_username}) "
                f"has no email. Skipping for Authentik sync."
            )
            logging.debug(log_msg)
            user_result["action"] = "SKIPPED_NO_MM_EMAIL"
            user_result["error_message"] = "Mattermost user has no email address."
            results.append(user_result)
            continue

        auth_pk_to_add = email_to_authentik_user_pk_map.get(mm_user_email.lower())
        if auth_pk_to_add is None:
            log_msg = (
                f"MM user email '{mm_user_email}' (username: {mm_username}) "
                f"not found in Authentik. Skipping for group '{auth_group_name}'."
            )
            logging.debug(log_msg)
            user_result["action"] = "SKIPPED_MM_USER_NOT_IN_AUTHENTIK"
            err_msg = f"User email '{mm_user_email}' not found in Authentik."
            user_result["error_message"] = err_msg
            results.append(user_result)
            continue

        if auth_pk_to_add not in current_auth_user_pks_in_group:
            log_add_attempt = (
                f"User '{mm_user_email}' (Auth PK: {auth_pk_to_add}, "
                f"MM username: {mm_username}) from MM channel "
                f"'{mm_channel_display_name}' is NOT in Auth group "
                f"'{auth_group_name}'. Attempting to add."
            )
            logging.info(log_add_attempt)
            if authentik_client.add_user_to_group(auth_group_pk, auth_pk_to_add):
                current_auth_user_pks_in_group.add(auth_pk_to_add)
                user_result["status"] = "SUCCESS"
                user_result["action"] = "ADDED_TO_AUTHENTIK_GROUP"
                logging.info(
                    f"Successfully added user '{mm_user_email}' "
                    f"(MM username: {mm_username}) to Auth group '{auth_group_name}'."
                )
            else:
                user_result["status"] = "FAILURE"
                user_result["action"] = "FAILED_TO_ADD_TO_AUTHENTIK_GROUP"
                err_msg = f"API call to add user to Auth group '{auth_group_name}' failed."
                user_result["error_message"] = err_msg
                logging.warning(
                    f"Failed to add user '{mm_user_email}' (Auth PK: {auth_pk_to_add}, "
                    f"MM username: {mm_username}) to Auth group '{auth_group_name}'."
                )
        else:
            user_result["status"] = "SUCCESS"
            user_result["action"] = "ALREADY_IN_AUTHENTIK_GROUP"
            logging.debug(
                f"User '{mm_user_email}' (Auth PK: {auth_pk_to_add}, "
                f"MM username: {mm_username}) is already in Auth group "
                f"'{auth_group_name}'. No action needed."
            )
        results.append(user_result)

    logging.info(
        f"Finished sync for Auth group '{auth_group_name}' with MM channel "
        f"'{mm_channel_display_name}'. Processed {len(mm_users_in_channel)} MM users."
    )
    return results


def orchestrate_authentik_mattermost_sync(
    authentik_client: "AuthentikClient", mattermost_client: "MattermostClient", mm_team_id: str
) -> tuple[bool, list[dict]]:
    """
    Orchestrates the full synchronization of Mattermost channel users to Authentik groups.
    Requires initialized Authentik and Mattermost clients and the Mattermost Team ID.
    Returns a tuple:
        - bool: True if synchronization process initiated successfully (even if no users were changed),
                False if a critical setup error occurred preventing any sync attempt.
        - list[dict]: A list of detailed results from sync_single_authentik_group_with_mattermost.
                      This list will be empty if a critical setup error occurs or no groups are processed.
    """
    logging.info("Starting Mattermost to Authentik group synchronization task...")
    detailed_results = []

    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Cannot proceed.")
        return False, detailed_results
    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed.")
        return False, detailed_results
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    all_auth_groups, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)

    if not all_auth_groups:
        logging.info("No Authentik groups to process. Synchronization finished.")
        return True, detailed_results  # Success, but no operations to report

    if not email_to_auth_pk_map:
        logging.warning(
            "Authentik email-to-user-PK map is empty. Sync operations might not find users to add effectively."
        )

    processed_groups_count = 0
    # total_users_added_across_all_groups = 0 # This metric is now implicitly in detailed_results

    for auth_group in all_auth_groups:
        group_sync_results = sync_single_authentik_group_with_mattermost(
            authentik_client,
            mattermost_client,
            mm_team_id,
            auth_group,
            email_to_auth_pk_map,
        )
        detailed_results.extend(group_sync_results)
        processed_groups_count += 1

    total_added_count = sum(1 for r in detailed_results if r["action"] == "ADDED_TO_AUTHENTIK_GROUP")
    log_msg = (
        f"Synchronization task completed. Processed {processed_groups_count} Auth groups. "
        f"Total new users added: {total_added_count}. "
        f"Total operations/skips: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results
