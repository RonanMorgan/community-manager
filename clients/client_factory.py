import logging

import config
from clients.authentik_client import AuthentikClient
from clients.brevo_client import BrevoClient
from clients.mattermost_client import MattermostClient
from clients.nocodb_client import NocoDBClient
from clients.outline_client import OutlineClient
from clients.vaultwarden_client import VaultwardenClient


def create_clients() -> dict:
    """
    Initializes and returns a dictionary of API clients.

    This factory function reads the configuration from the `config` module
    and initializes the API clients for the different services used by the bot.
    If a service is not configured, its client will not be initialized.

    :return: A dictionary where keys are service names (e.g., "authentik")
             and values are the initialized client objects.
    """
    clients = {}

    if config.AUTHENTIK_URL and config.AUTHENTIK_TOKEN:
        try:
            clients["authentik"] = AuthentikClient(config.AUTHENTIK_URL, config.AUTHENTIK_TOKEN)
            logging.info("AuthentikClient initialized successfully.")
        except ValueError as e:
            logging.warning(f"Failed to initialize AuthentikClient: {e}")
    else:
        logging.warning("Authentik URL or Token not configured. Authentik features will be disabled.")

    if config.OUTLINE_URL and config.OUTLINE_TOKEN:
        try:
            clients["outline"] = OutlineClient(config.OUTLINE_URL, config.OUTLINE_TOKEN)
            logging.info("OutlineClient initialized successfully.")
        except ValueError as e:
            logging.warning(f"Failed to initialize OutlineClient: {e}")
    else:
        logging.warning("Outline URL or Token not configured. Outline features will be disabled.")

    if config.MATTERMOST_URL and config.BOT_TOKEN and config.MATTERMOST_TEAM_ID:
        try:
            clients["mattermost"] = MattermostClient(
                base_url=config.MATTERMOST_URL,
                token=config.BOT_TOKEN,
                team_id=config.MATTERMOST_TEAM_ID,
                login_id=config.MATTERMOST_LOGIN_ID,
                password=config.MATTERMOST_PASSWORD,
                debug=config.DEBUG,
            )
            logging.info("MattermostClient initialized successfully.")
        except ValueError as e:
            logging.warning(f"Failed to initialize MattermostClient: {e}")
    else:
        logging.warning(
            "Mattermost URL, Bot Token, or Team ID not fully configured. Mattermost API operations may fail or be disabled."
        )

    if config.BREVO_API_URL and config.BREVO_API_KEY:
        try:
            clients["brevo"] = BrevoClient(config.BREVO_API_URL, config.BREVO_API_KEY)
            logging.info("BrevoClient initialized successfully.")
        except ValueError as e:
            logging.warning(f"Failed to initialize BrevoClient: {e}")
    else:
        logging.warning("Brevo API URL or Key not configured. Brevo features will be disabled.")

    if config.NOCODB_URL and config.NOCODB_TOKEN:
        try:
            clients["nocodb"] = NocoDBClient(config.NOCODB_URL, config.NOCODB_TOKEN)
            logging.info("NocoDBClient initialized successfully.")
        except ValueError as e:
            logging.warning(f"Failed to initialize NocoDBClient: {e}")
    else:
        logging.warning("NocoDB URL or Token not configured. NocoDB features will be disabled.")

    if (
        config.VAULTWARDEN_ORGANIZATION_ID
        and config.VAULTWARDEN_SERVER_URL
        and config.VAULTWARDEN_API_USERNAME
        and config.VAULTWARDEN_API_PASSWORD
    ):
        try:
            clients["vaultwarden"] = VaultwardenClient(
                organization_id=config.VAULTWARDEN_ORGANIZATION_ID,
                server_url=config.VAULTWARDEN_SERVER_URL,
                api_username=config.VAULTWARDEN_API_USERNAME,
                api_password=config.VAULTWARDEN_API_PASSWORD,
            )
            logging.info("VaultwardenClient initialized successfully.")
        except ValueError as e:
            logging.warning(f"Failed to initialize VaultwardenClient: {e}")
        except Exception as e:
            logging.error(
                f"An unexpected error occurred during VaultwardenClient initialization: {e}",
                exc_info=True,
            )
    else:
        logging.warning("Vaultwarden Organization ID not configured. Vaultwarden features will be disabled.")

    return clients
