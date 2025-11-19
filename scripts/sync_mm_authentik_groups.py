import logging
import os
import sys

import config
from clients.authentik_client import AuthentikClient
from clients.brevo_client import BrevoClient
from clients.mattermost_client import MattermostClient
from clients.nocodb_client import NocoDBClient
from clients.outline_client import OutlineClient
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

# Adjust path to import from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def initialize_clients():
    """Initializes and returns Authentik, Mattermost, Outline, and Brevo clients."""
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

    nocodb_client = None
    if config.NOCODB_URL and config.NOCODB_TOKEN:
        try:
            nocodb_client = NocoDBClient(config.NOCODB_URL, config.NOCODB_TOKEN)
            logging.info("NocoDBClient initialized successfully for sync script.")
        except ValueError as e:
            logging.error(f"Failed to initialize NocoDBClient for script: {e}. NocoDB sync will be skipped.")
    else:
        logging.info("NocoDB URL or Token not configured for script. NocoDB sync will be skipped.")

    vaultwarden_client = None
    if (
        config.VAULTWARDEN_ORGANIZATION_ID
        and config.VAULTWARDEN_SERVER_URL
        and config.VAULTWARDEN_API_USERNAME
        and config.VAULTWARDEN_API_PASSWORD
    ):
        try:
            vaultwarden_client = VaultwardenClient(
                organization_id=config.VAULTWARDEN_ORGANIZATION_ID,
                server_url=config.VAULTWARDEN_SERVER_URL,
                api_username=config.VAULTWARDEN_API_USERNAME,
                api_password=config.VAULTWARDEN_API_PASSWORD,
            )
            logging.info("VaultwardenClient initialized successfully for sync script.")
        except Exception as e:
            logging.error(f"Failed to initialize VaultwardenClient for script: {e}. Vaultwarden sync will be skipped.")
    else:
        logging.info(
            "Vaultwarden config (Org ID, Server URL, API User/Pass) not fully set for script. Vaultwarden sync will be skipped."
        )

    return (
        auth_client,
        mm_client,
        outline_client,
        brevo_client,
        nocodb_client,
        vaultwarden_client,
    )


async def main_sync_logic():  # Changed to async
    logging.info(
        "Attempting to run Mattermost to Authentik, Outline, Brevo, NocoDB, & Vaultwarden group synchronization via script..."
    )

    (
        authentik_client,
        mattermost_client,
        outline_client,
        brevo_client,
        nocodb_client,
        vaultwarden_client,
    ) = initialize_clients()

    if not authentik_client:  # Keeping Authentik mandatory for WITH_AUTHENTIK mode often initiated by script
        logging.critical("Authentik client not initialized in script. Aborting WITH_AUTHENTIK.")
        return
    if not mattermost_client:
        logging.critical("Mattermost client not initialized in script. Aborting sync.")
        return
    if not config.MATTERMOST_TEAM_ID:
        logging.critical("MATTERMOST_TEAM_ID not configured in script. Aborting sync.")
        return

    logging.info(
        "Clients initialized by script. Calling group synchronization function from library (WITH_AUTHENTIK mode)..."
    )

    clients = {
        "authentik": authentik_client,
        "mattermost": mattermost_client,
        "outline": outline_client,
        "brevo": brevo_client,
        "nocodb": nocodb_client,
        "vaultwarden": vaultwarden_client,
    }
    success, detailed_results = await orchestrate_group_synchronization(
        clients=clients,
        mm_team_id=config.MATTERMOST_TEAM_ID,
        sync_mode="WITH_AUTHENTIK",
        skip_services=None,
    )

    if success:
        logging.info(
            f"Group synchronization process (WITH_AUTHENTIK) orchestrated by script completed. Success: {success}. Results count: {len(detailed_results)}"
        )
        actions_summary = {}
        for res in detailed_results:
            action = res.get("action", "UNKNOWN_ACTION")
            actions_summary[action] = actions_summary.get(action, 0) + 1
        if detailed_results:
            logging.info(f"Script run (WITH_AUTHENTIK) actions summary: {actions_summary}")
        else:
            logging.info(
                "Script run (WITH_AUTHENTIK) completed with no specific actions performed or results reported."
            )
    else:
        logging.error("Synchronization process (WITH_AUTHENTIK) orchestrated by script encountered errors or failed.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main_sync_logic())
