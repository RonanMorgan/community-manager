import logging
import json # For potential pretty printing of results or payloads
import sys
import os

# Adjust path to import from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import config
from app.authentik_client import AuthentikClient
from app.mattermost_client import MattermostClient, slugify # Import slugify if needed for channel name matching

# Configure logging
log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
if config.DEBUG:
    logging.basicConfig(level=logging.DEBUG, format=log_format)
    logging.debug("DEBUG mode is enabled for sync script.")
else:
    logging.basicConfig(level=logging.INFO, format=log_format)

def initialize_clients():
    """Initializes and returns Authentik and Mattermost clients."""
    auth_client = None
    if config.AUTHENTIK_URL and config.AUTHENTIK_TOKEN:
        try:
            auth_client = AuthentikClient(config.AUTHENTIK_URL, config.AUTHENTIK_TOKEN)
            logging.info("AuthentikClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize AuthentikClient: {e}") # Changed to error
    else:
        logging.warning("Authentik URL or Token not configured. Authentik client not created.")

    mm_client = None
    if config.MATTERMOST_URL and config.BOT_TOKEN and config.MATTERMOST_TEAM_ID:
        try:
            mm_client = MattermostClient(
                config.MATTERMOST_URL, config.BOT_TOKEN, config.MATTERMOST_TEAM_ID
            )
            logging.info("MattermostClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize MattermostClient: {e}") # Changed to error
    else:
        logging.warning("Mattermost URL, Bot Token, or Team ID not configured. Mattermost client not created.")

    return auth_client, mm_client

def get_all_authentik_groups_and_user_map(authentik_client: AuthentikClient):
    """
    Fetches all Authentik groups and constructs a user email-to-PK map.
    Uses the get_groups_with_users method from AuthentikClient.
    """
    logging.info("Fetching all Authentik groups and constructing user email-to-PK map...")
    if not authentik_client:
        logging.error("Authentik client not provided to get_all_authentik_groups_and_user_map.")
        return [], {}

    groups, email_map = authentik_client.get_groups_with_users() # This method handles pagination

    if not groups:
        logging.warning("No Authentik groups found or an error occurred during fetching.")
    if not email_map:
        logging.warning("Authentik user email-to-PK map is empty or could not be constructed.")

    return groups, email_map

def sync_single_authentik_group_with_mattermost(
    authentik_client: AuthentikClient,
    mattermost_client: MattermostClient,
    mm_team_id: str,
    authentik_group: dict,
    email_to_authentik_user_pk_map: dict
):
    """
    Synchronizes members from a Mattermost channel (matched by name to the Authentik group)
    into the corresponding Authentik group.
    """
    auth_group_name = authentik_group.get("name")
    auth_group_pk = authentik_group.get("pk")
    # 'users' in authentik_group object from API lists user PKs directly in that group.
    current_auth_user_pks_in_group = set(authentik_group.get("users", []))

    if not auth_group_name or not auth_group_pk:
        logging.warning(f"Skipping Authentik group due to missing name or PK: {authentik_group}")
        return

    logging.info(f"Processing sync for Authentik group: '{auth_group_name}' (PK: {auth_group_pk})")

    # Assume Authentik group name should directly match Mattermost channel *name* (slug)
    # If DisplayName is used for matching, slugify it first.
    # For this example, we'll use the MattermostClient's slugify to be safe,
    # assuming the Authentik group name might be more like a display name.
    mm_channel_slug = slugify(auth_group_name)

    mm_channel = mattermost_client.get_channel_by_name(mm_team_id, mm_channel_slug)
    if not mm_channel:
        logging.warning(f"No Mattermost channel found with slug '{mm_channel_slug}' (derived from Authentik group '{auth_group_name}'). Skipping.")
        return

    mm_channel_id = mm_channel.get("id")
    mm_channel_display_name = mm_channel.get("display_name")
    logging.info(f"Found corresponding Mattermost channel '{mm_channel_display_name}' (ID: {mm_channel_id})")

    mm_users_in_channel = mattermost_client.get_users_in_channel(mm_channel_id)
    if not mm_users_in_channel: # Empty list is a valid response if channel has no members
        logging.info(f"No users found in Mattermost channel '{mm_channel_display_name}'. Nothing to sync to Authentik group.")
        return

    logging.info(f"Found {len(mm_users_in_channel)} users in Mattermost channel '{mm_channel_display_name}'.")

    users_added_to_auth_group_count = 0
    for mm_user in mm_users_in_channel:
        mm_user_email = mm_user.get("email")
        if not mm_user_email:
            logging.debug(f"Mattermost user ID {mm_user.get('id')} (username: {mm_user.get('username')}) has no email. Skipping.")
            continue

        # Match emails case-insensitively
        authentik_user_pk_to_add = email_to_authentik_user_pk_map.get(mm_user_email.lower())

        if authentik_user_pk_to_add is None:
            logging.debug(f"Mattermost user email '{mm_user_email}' not found in Authentik user map. Skipping.")
            continue

        if authentik_user_pk_to_add not in current_auth_user_pks_in_group:
            logging.info(
                f"User '{mm_user_email}' (Authentik PK: {authentik_user_pk_to_add}) from Mattermost channel "
                f"is NOT in Authentik group '{auth_group_name}'. Attempting to add."
            )
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

    logging.info(f"Finished processing Authentik group '{auth_group_name}'. Added {users_added_to_auth_group_count} new user(s).")

def main_sync_logic():
    logging.info("Starting Mattermost to Authentik group synchronization script...")

    authentik_client, mattermost_client = initialize_clients()

    if not authentik_client:
        logging.error("Authentik client not initialized. Cannot proceed. Please check AUTHENTIK_URL and AUTHENTIK_TOKEN.")
        return
    if not mattermost_client:
        logging.error("Mattermost client not initialized. Cannot proceed. Please check MATTERMOST_URL, BOT_TOKEN, and MATTERMOST_TEAM_ID.")
        return
    if not config.MATTERMOST_TEAM_ID: # This is also checked by mm_client init, but good for clarity.
        logging.error("MATTERMOST_TEAM_ID not configured. Cannot proceed with Mattermost operations.")
        return

    all_auth_groups, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)

    if not all_auth_groups:
        logging.info("No Authentik groups found or an error occurred fetching them. Exiting sync.")
        return

    if not email_to_auth_pk_map:
        logging.warning("Authentik email-to-user-PK map is empty. Sync operations might not find users to add.")

    processed_groups_count = 0
    for auth_group in all_auth_groups:
        sync_single_authentik_group_with_mattermost(
            authentik_client,
            mattermost_client,
            config.MATTERMOST_TEAM_ID, # Using the configured team_id for MM channel lookups
            auth_group,
            email_to_auth_pk_map
        )
        processed_groups_count += 1

    logging.info(f"Synchronization task completed. Processed {processed_groups_count} Authentik groups.")

if __name__ == "__main__":
    main_sync_logic()
