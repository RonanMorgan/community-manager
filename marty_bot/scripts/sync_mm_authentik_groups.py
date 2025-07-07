import logging
import sys
import os

# Adjust path to import from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import config
from clients.authentik_client import AuthentikClient
from clients.mattermost_client import MattermostClient
from clients.outline_client import OutlineClient
from clients.brevo_client import BrevoClient
from clients.vaultwarden_client import VaultwardenClient  # Import VaultwardenClient

# Import the orchestrator function
from libraries.group_sync_services import orchestrate_group_synchronization

# Configure logging
log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
if config.DEBUG:
    logging.basicConfig(level=logging.DEBUG, format=log_format)
    logging.debug("DEBUG mode is enabled for sync script.")
else:
    logging.basicConfig(level=logging.INFO, format=log_format)


def initialize_clients():
    """Initializes and returns Authentik, Mattermost, Outline, Brevo, and Vaultwarden clients."""
    auth_client = None
    if config.AUTHENTIK_URL and config.AUTHENTIK_TOKEN:
        try:
            auth_client = AuthentikClient(config.AUTHENTIK_URL, config.AUTHENTIK_TOKEN)
            logging.info("AuthentikClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize AuthentikClient: {e}")
    else:
        logging.warning("Authentik URL or Token not configured. Authentik client not created.")

    mm_client = None
    if config.MATTERMOST_URL and config.BOT_TOKEN and config.MATTERMOST_TEAM_ID:
        try:
            mm_client = MattermostClient(config.MATTERMOST_URL, config.BOT_TOKEN, config.MATTERMOST_TEAM_ID)
            logging.info("MattermostClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize MattermostClient: {e}")
    else:
        logging.warning("Mattermost URL, Bot Token, or Team ID not configured. Mattermost client not created.")

    outline_client = None
    if config.OUTLINE_URL and config.OUTLINE_TOKEN:
        try:
            outline_client = OutlineClient(config.OUTLINE_URL, config.OUTLINE_TOKEN)
            logging.info("OutlineClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize OutlineClient for script: {e}. Outline sync will be skipped.")
    else:
        logging.info("Outline URL or Token not configured for script. Outline sync will be skipped.")

    brevo_client = None
    if config.BREVO_API_URL and config.BREVO_API_KEY:
        try:
            brevo_client = BrevoClient(config.BREVO_API_URL, config.BREVO_API_KEY)
            logging.info("BrevoClient initialized for script.")
        except ValueError as e:
            logging.error(f"Failed to initialize BrevoClient for script: {e}")
    else:
        logging.info("Brevo API URL or Key not configured for script. Brevo sync will be skipped.")

    vaultwarden_client = None
    if config.VAULTWARDEN_ORGANIZATION_ID:
        try:
            vaultwarden_client = VaultwardenClient(
                organization_id=config.VAULTWARDEN_ORGANIZATION_ID,
                server_url=config.VAULTWARDEN_SERVER_URL,  # Client handles default if None
            )
            logging.info("VaultwardenClient initialized for script.")
        except ValueError as e:
            logging.error(f"Failed to initialize VaultwardenClient for script: {e}")
        except Exception as e:
            logging.error(f"Unexpected error initializing VaultwardenClient for script: {e}", exc_info=True)
    else:
        logging.info("VAULTWARDEN_ORGANIZATION_ID not configured for script. Vaultwarden features will be disabled.")

    return auth_client, mm_client, outline_client, brevo_client, vaultwarden_client


def main_sync_logic():
    logging.info(
        "Attempting to run Mattermost to Authentik, Outline, Brevo, & Vaultwarden group synchronization via script..."
    )

    authentik_client, mattermost_client, outline_client, brevo_client, vaultwarden_client = initialize_clients()

    if not authentik_client:
        logging.critical("Authentik client not initialized in script. Aborting sync.")
        return
    if not mattermost_client:
        logging.critical("Mattermost client not initialized in script. Aborting sync.")
        return
    if not config.MATTERMOST_TEAM_ID:
        logging.critical("MATTERMOST_TEAM_ID not configured in script. Aborting sync.")
        return

    # Optional clients logging already handled in initialize_clients

    logging.info("Clients initialized by script. Calling group synchronization function from library...")

    success, detailed_results = orchestrate_group_synchronization(
        authentik_client,
        mattermost_client,
        outline_client,
        brevo_client,
        vaultwarden_client,  # Pass the Vaultwarden client
        config.MATTERMOST_TEAM_ID,
        # Defaults for perform_deletions=True and fetch_remote_members=True are used from orchestrator
    )

    if success:
        logging.info(
            f"Group synchronization process orchestrated by script completed. Success: {success}. Results count: {len(detailed_results)}"
        )
        actions_summary = {}
        for res in detailed_results:
            action = res.get("action", "UNKNOWN_ACTION")
            actions_summary[action] = actions_summary.get(action, 0) + 1
        if detailed_results:  # Only log summary if there were results
            logging.info(f"Script run actions summary: {actions_summary}")
        else:
            logging.info("Script run completed with no specific actions performed or results reported.")
    else:
        logging.error("Synchronization process orchestrated by script encountered errors or failed.")


if __name__ == "__main__":
    main_sync_logic()
