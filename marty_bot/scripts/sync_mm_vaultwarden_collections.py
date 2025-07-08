import logging
import sys
import os

# Adjust path to import from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import config
from clients.mattermost_client import MattermostClient
from clients.vaultwarden_client import VaultwardenClient
# We might need other utility functions or specific error types
# from libraries.group_sync_services import ... (if we move logic there)

# Configure logging
log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
if config.DEBUG:
    logging.basicConfig(level=logging.DEBUG, format=log_format)
    logging.debug("DEBUG mode is enabled for Vaultwarden sync script.")
else:
    logging.basicConfig(level=logging.INFO, format=log_format)

def initialize_clients():
    """Initializes and returns Mattermost and Vaultwarden clients."""
    mm_client = None
    if config.MATTERMOST_URL and config.BOT_TOKEN and config.MATTERMOST_TEAM_ID:
        try:
            mm_client = MattermostClient(config.MATTERMOST_URL, config.BOT_TOKEN, config.MATTERMOST_TEAM_ID)
            logging.info("MattermostClient initialized successfully for Vaultwarden sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize MattermostClient: {e}")
    else:
        logging.warning("Mattermost URL, Bot Token, or Team ID not configured. Mattermost client not created.")

    vw_client = None
    # VaultwardenClient needs organization_id. Server URL and API creds are read from config/env by default.
    if config.VAULTWARDEN_ORGANIZATION_ID and config.VAULTWARDEN_SERVER_URL and \
       config.VAULTWARDEN_API_USERNAME and config.VAULTWARDEN_API_PASSWORD:
        try:
            vw_client = VaultwardenClient(
                organization_id=config.VAULTWARDEN_ORGANIZATION_ID,
                server_url=config.VAULTWARDEN_SERVER_URL
                # API creds will be picked up from config by the client's __init__
            )
            logging.info("VaultwardenClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize VaultwardenClient: {e}")
        except Exception as e: # Catch any other unexpected errors during init
            logging.error(f"An unexpected error occurred during VaultwardenClient initialization: {e}")
    else:
        logging.warning(
            "Vaultwarden Organization ID, Server URL, API Username or API Password not configured. "
            "Vaultwarden client not created."
        )

    return mm_client, vw_client

def sync_channel_users_to_vaultwarden_collection(
    mm_client: MattermostClient,
    vw_client: VaultwardenClient,
    channel_id: str,
    channel_name: str,
    api_access_token: str
):
    """
    Synchronizes users from a Mattermost channel to a Vaultwarden collection.
    Assumes channel_name directly maps to collection_name.
    """
    logging.info(f"Processing Mattermost channel '{channel_name}' (ID: {channel_id}) for Vaultwarden sync.")

    # For Vaultwarden, collection name is assumed to be the same as Mattermost channel name
    collection_name = channel_name
    collection_id = vw_client.get_collection_id_by_name_via_api_or_cli(collection_name)

    if not collection_id:
        logging.warning(
            f"Vaultwarden collection named '{collection_name}' (derived from channel '{channel_name}') not found or accessible. "
            f"Skipping user invitations for this channel."
        )
        return False

    logging.info(f"Found Vaultwarden collection '{collection_name}' with ID '{collection_id}'.")

    try:
        # Mattermost API returns a list of UserChannelMember objects or similar
        # We need to ensure we get actual user objects to fetch emails.
        # The `get_users_in_channel` method from MattermostClient should give us user IDs.
        channel_members = mm_client.get_users_in_channel(channel_id) # This should return list of user dicts or user IDs
        if channel_members is None: # Check if the call failed
            logging.error(f"Could not retrieve members for Mattermost channel '{channel_name}' (ID: {channel_id}).")
            return False

        if not channel_members:
            logging.info(f"No members found in Mattermost channel '{channel_name}'. No users to invite.")
            return True # No failure, just no work to do

        successful_invites = 0
        failed_invites = 0

        for member in channel_members:
            user_id = member.get("user_id") if isinstance(member, dict) else member # Adapt based on actual return type
            if not user_id:
                logging.warning(f"Could not get user_id for a member in channel {channel_name}. Member data: {member}")
                continue

            user_info = mm_client.get_user(user_id) # Fetches full user profile
            if not user_info:
                logging.warning(f"Could not retrieve info for user ID '{user_id}' in channel '{channel_name}'.")
                continue

            user_email = user_info.get("email")
            if not user_email:
                logging.warning(f"No email found for user '{user_info.get('username', user_id)}' (ID: {user_id}). Skipping Vaultwarden invite.")
                continue

            # Exclude the bot itself from being invited
            if user_email == config.VAULTWARDEN_API_USERNAME: # Assuming bot uses the API user
                 logging.debug(f"Skipping invite for API user '{user_email}' to collection '{collection_name}'.")
                 continue

            # Exclude users defined in the EXCLUDED_USERS set (by email or username)
            # Assuming EXCLUDED_USERS contains usernames. If it contains emails, adjust accordingly.
            if user_info.get('username') in config.EXCLUDED_USERS or user_email in config.EXCLUDED_USERS:
                logging.info(f"User '{user_info.get('username', user_email)}' is in the exclusion list. Skipping Vaultwarden invite for collection '{collection_name}'.")
                continue

            logging.debug(f"Attempting to invite user '{user_email}' (from channel '{channel_name}') to Vaultwarden collection '{collection_name}'.")

            # Using default permissions: read_only=True, hide_passwords=False, manage_collection=False
            # These can be made configurable if needed.
            if vw_client.invite_user_to_collection_api(api_access_token, user_email, collection_id):
                successful_invites += 1
            else:
                failed_invites += 1
                logging.error(f"Failed to invite user '{user_email}' to Vaultwarden collection '{collection_name}' (ID: {collection_id}).")

        logging.info(
            f"Finished processing channel '{channel_name}'. Successful Vaultwarden invites: {successful_invites}, Failed invites: {failed_invites}."
        )
        return failed_invites == 0

    except Exception as e:
        logging.error(f"An unexpected error occurred while processing channel '{channel_name}' for Vaultwarden sync: {e}", exc_info=True)
        return False

def main_sync_logic():
    logging.info("Starting Mattermost to Vaultwarden collection synchronization script...")
    mm_client, vw_client = initialize_clients()

    if not mm_client:
        logging.critical("Mattermost client not initialized. Aborting Vaultwarden sync script.")
        return
    if not vw_client:
        logging.critical("Vaultwarden client not initialized. Aborting Vaultwarden sync script.")
        return

    # Get Vaultwarden API access token once for the script run
    api_access_token = vw_client.get_api_access_token()
    if not api_access_token:
        logging.critical("Failed to obtain Vaultwarden API access token. Aborting sync script.")
        return

    logging.info("Successfully obtained Vaultwarden API access token.")

    # Determine which channels to process.
    # For now, let's assume we process all public channels in the configured team.
    # This could be refined based on channel naming conventions or specific configurations.
    try:
        team_channels = mm_client.get_public_channels_for_team(config.MATTERMOST_TEAM_ID)
        if team_channels is None: # API call failed
            logging.error(f"Could not retrieve public channels for team ID '{config.MATTERMOST_TEAM_ID}'.")
            return

        if not team_channels:
            logging.info(f"No public channels found for team ID '{config.MATTERMOST_TEAM_ID}'. Nothing to sync.")
            return

        logging.info(f"Found {len(team_channels)} public channels to potentially sync to Vaultwarden.")

        overall_success = True
        for channel in team_channels:
            channel_id = channel.get("id")
            channel_name = channel.get("name") # This is the channel handle/slug
            channel_display_name = channel.get("display_name") # This is the human-readable name

            if not channel_id or not channel_name:
                logging.warning(f"Channel data incomplete, skipping: {channel}")
                continue

            # We need to decide if collection name maps to `channel_name` (slug) or `channel_display_name`.
            # The Vaultwarden `create_collection` uses `collection_name`.
            # Let's assume the `channel_display_name` is more suitable for a collection name.
            # If `channel_display_name` can be empty, fallback to `channel_name`.
            effective_collection_name_base = channel_display_name if channel_display_name else channel_name

            # TODO: Add specific logic here if channels need to be filtered (e.g. by prefix)
            # For example:
            # if not effective_collection_name_base.startswith("vw-"):
            #     logging.debug(f"Channel '{effective_collection_name_base}' does not match sync criteria. Skipping.")
            #     continue

            if not sync_channel_users_to_vaultwarden_collection(
                mm_client, vw_client, channel_id, effective_collection_name_base, api_access_token
            ):
                overall_success = False # Mark failure if any channel sync fails
                logging.error(f"Error processing channel '{effective_collection_name_base}' for Vaultwarden sync.")

        if overall_success:
            logging.info("Mattermost to Vaultwarden collection synchronization script completed successfully for all processed channels.")
        else:
            logging.warning("Mattermost to Vaultwarden collection synchronization script completed with some errors for one or more channels.")

    except Exception as e:
        logging.critical(f"An unexpected critical error occurred in the main sync logic: {e}", exc_info=True)

if __name__ == "__main__":
    main_sync_logic()
