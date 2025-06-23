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
) -> int | None:
    """
    Synchronizes members from a Mattermost channel (matched by name to the Authentik group)
    into the corresponding Authentik group.
    Returns the count of users added, or 0 if no users were added or group skipped.
    Returns None if a critical setup error occurred (e.g. missing client).
    """
    if not authentik_client or not mattermost_client or not mm_team_id:
        logging.error("Client or team_id missing for sync_single_authentik_group_with_mattermost.")
        return None

    auth_group_name = authentik_group.get("name")
    auth_group_pk = authentik_group.get("pk")
    current_auth_user_pks_in_group = set(authentik_group.get("users", []))

    if not auth_group_name or not auth_group_pk:
        logging.warning(f"Skipping Authentik group due to missing name or PK: {authentik_group}")
        return 0

    logging.info(f"Processing sync for Authentik group: '{auth_group_name}' (PK: {auth_group_pk})")
    mm_channel_slug = slugify(auth_group_name)
    mm_channel = mattermost_client.get_channel_by_name(mm_team_id, mm_channel_slug)

    if not mm_channel:
        logging.warning(
            f"No Mattermost channel found with slug '{mm_channel_slug}' "
            f"(derived from Authentik group '{auth_group_name}'). Skipping."
        )
        return 0

    mm_channel_id = mm_channel.get("id")
    mm_channel_display_name = mm_channel.get("display_name")
    logging.info(f"Found corresponding Mattermost channel '{mm_channel_display_name}' (ID: {mm_channel_id})")

    mm_users_in_channel = mattermost_client.get_users_in_channel(mm_channel_id)
    if not mm_users_in_channel:
        logging.info(
            f"No users found in Mattermost channel '{mm_channel_display_name}'. Nothing to sync to Authentik group."
        )
        return 0

    logging.info(f"Found {len(mm_users_in_channel)} users in Mattermost channel '{mm_channel_display_name}'.")
    users_added_to_auth_group_count = 0
    for mm_user in mm_users_in_channel:
        mm_user_email = mm_user.get("email")
        if not mm_user_email:
            logging.debug(
                f"Mattermost user ID {mm_user.get('id')} (username: {mm_user.get('username')}) has no email. Skipping."
            )
            continue

        authentik_user_pk_to_add = email_to_authentik_user_pk_map.get(mm_user_email.lower())
        if authentik_user_pk_to_add is None:
            logging.debug(f"Mattermost user email '{mm_user_email}' not found in Authentik user map. Skipping.")
            continue

        if authentik_user_pk_to_add not in current_auth_user_pks_in_group:
            log_message_part1 = f"User '{mm_user_email}' (Authentik PK: {authentik_user_pk_to_add}) "
            log_message_part2 = (  # noqa: E501
                f"from Mattermost channel is NOT in Authentik group '{auth_group_name}'. " "Attempting to add."
            )
            logging.info(log_message_part1 + log_message_part2)
            if authentik_client.add_user_to_group(auth_group_pk, authentik_user_pk_to_add):
                users_added_to_auth_group_count += 1
                current_auth_user_pks_in_group.add(authentik_user_pk_to_add)
            else:
                logging.warning(
                    f"Failed to add user '{mm_user_email}' (Authentik PK: {authentik_user_pk_to_add}) "
                    f"to Authentik group '{auth_group_name}'."
                )
        else:
            logging.debug(
                f"User '{mm_user_email}' (Authentik PK: {authentik_user_pk_to_add}) "
                f"is already in Authentik group '{auth_group_name}'. No action needed."
            )

    logging.info(
        f"Finished processing Authentik group '{auth_group_name}'. Added {users_added_to_auth_group_count} new user(s)."
    )
    return users_added_to_auth_group_count


def orchestrate_authentik_mattermost_sync(
    authentik_client: "AuthentikClient", mattermost_client: "MattermostClient", mm_team_id: str
) -> bool:
    """
    Orchestrates the full synchronization of Mattermost channel users to Authentik groups.
    Requires initialized Authentik and Mattermost clients and the Mattermost Team ID.
    Returns True if synchronization process completed (even if no users were added),
    False if a critical setup error occurred.
    """
    logging.info("Starting Mattermost to Authentik group synchronization task...")

    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Cannot proceed.")
        return False
    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed.")
        return False
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False

    all_auth_groups, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)

    if not all_auth_groups:
        logging.info("No Authentik groups to process. Synchronization finished.")
        return True

    if not email_to_auth_pk_map:
        logging.warning("Authentik email-to-user-PK map is empty. Sync operations might not find users to add effectively.")

    processed_groups_count = 0
    total_users_added_across_all_groups = 0

    for auth_group in all_auth_groups:
        users_added = sync_single_authentik_group_with_mattermost(
            authentik_client,
            mattermost_client,
            mm_team_id,
            auth_group,
            email_to_auth_pk_map,
        )
        if users_added is not None:  # Count users if sync_single didn't have a critical error
            total_users_added_across_all_groups += users_added
        processed_groups_count += 1

    logging.info(
        f"Synchronization task completed. Processed {processed_groups_count} Authentik groups. "
        f"Total new users added to groups: {total_users_added_across_all_groups}."
    )
    return True
