import logging
import sys
import os

# Adjust path to import from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import config
from clients.authentik_client import AuthentikClient
from clients.mattermost_client import MattermostClient

# Import the orchestrator function
from libraries.group_sync_services import orchestrate_group_synchronization  # Renamed
from clients.outline_client import OutlineClient  # For potential initialization

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

    return auth_client, mm_client


def main_sync_logic():
    logging.info("Attempting to run Mattermost to Authentik & Outline group synchronization via script...")

    authentik_client, mattermost_client = initialize_clients()

    # Initialize Outline client - for now, it's optional for the script's core logic
    # This script primarily focuses on the Authentik-Mattermost part from its name,
    # but the orchestrator now supports Outline. We'll pass None if not configured.
    outline_client = None
    if config.OUTLINE_URL and config.OUTLINE_TOKEN:
        try:
            outline_client = OutlineClient(config.OUTLINE_URL, config.OUTLINE_TOKEN)
            logging.info("OutlineClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize OutlineClient for script: {e}. Outline sync will be skipped.")
    else:
        logging.info("Outline URL or Token not configured for script. Outline sync will be skipped.")

    if not authentik_client:
        logging.critical("Authentik client not initialized in script. Aborting sync.")
        return
    if not mattermost_client:
        logging.critical("Mattermost client not initialized in script. Aborting sync.")
        return
    if not config.MATTERMOST_TEAM_ID:  # This is also checked by mm_client init, but good for script-level clarity
        logging.critical("MATTERMOST_TEAM_ID not configured in script. Aborting sync.")
        return

    logging.info("Clients initialized by script. Calling group synchronization function from library...")

    # Call the main logic from the library
    # The orchestrator now returns (bool_success, list_detailed_results)
    success, detailed_results = orchestrate_group_synchronization(  # Renamed function
        authentik_client,
        mattermost_client,
        outline_client,  # Pass the (potentially None) Outline client
        config.MATTERMOST_TEAM_ID,
    )

    # The script's success logging can be based on the boolean or the content of detailed_results
    if success:
        logging.info(
            f"Group synchronization process orchestrated by script completed. Success: {success}. Results count: {len(detailed_results)}"
        )
    else:
        logging.error("Synchronization process orchestrated by script encountered errors or failed.")


if __name__ == "__main__":
    main_sync_logic()
