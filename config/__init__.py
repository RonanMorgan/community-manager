import logging  # Added for logging matrix loading status
import os

import yaml  # Added for permissions matrix
from dotenv import load_dotenv

load_dotenv()

# Initialize basic logging for config loading phase
# This allows seeing messages about config files being loaded/not found
# It might be overridden by the bot's main logging setup later.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - CONFIG - %(message)s")


MATTERMOST_URL = os.getenv("MATTERMOST_URL")
# MATTERMOST_TOKEN = os.getenv("MATTERMOST_TOKEN") # Admin/API token for operations like channel creation - REMOVED
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Bot's own token for WebSocket/posting messages as bot
BOT_NAME = os.getenv("BOT_NAME")
MATTERMOST_TEAM_ID = os.getenv("MATTERMOST_TEAM_ID")  # Team ID for channel creation
MATTERMOST_LOGIN_ID = os.getenv("MATTERMOST_LOGIN_ID")
MATTERMOST_PASSWORD = os.getenv("MATTERMOST_PASSWORD")
PROJECT_BOARD_TEMPLATE_ID = os.getenv("PROJECT_BOARD_TEMPLATE_ID")

AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")

OUTLINE_URL = os.getenv("OUTLINE_URL")
OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN")

# Brevo settings
BREVO_API_URL = os.getenv("BREVO_API_URL", "https://api.brevo.com/v3")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_DEFAULT_SENDER_EMAIL = os.getenv("BREVO_DEFAULT_SENDER_EMAIL")
BREVO_DEFAULT_SENDER_NAME = os.getenv("BREVO_DEFAULT_SENDER_NAME", "Marty Bot")

# NoCoDB settings
NOCODB_URL = os.getenv("NOCODB_URL")
NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")

# Vaultwarden settings
VAULTWARDEN_ORGANIZATION_ID = os.getenv("VAULTWARDEN_ORGANIZATION_ID")
VAULTWARDEN_SERVER_URL = os.getenv("VAULTWARDEN_SERVER_URL")
# VAULTWARDEN_CLIENT_ID and VAULTWARDEN_CLIENT_SECRET are no longer used by VaultwardenClient.
# The client now relies on a one-time manual 'bw login' and uses BW_PASSWORD for 'bw unlock'.
# BW_PASSWORD is intentionally not loaded into the config object directly for security.
# The VaultwardenClient will attempt to read it from the environment itself using os.getenv("BW_PASSWORD").
# This avoids storing it in a config object that might be logged or exposed.
VAULTWARDEN_API_USERNAME = os.getenv("VAULTWARDEN_API_USERNAME")
VAULTWARDEN_API_PASSWORD = os.getenv("VAULTWARDEN_API_PASSWORD")

# General Configuration
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# User Exclusion Configuration
config_dir = os.path.dirname(__file__)
EXCLUDED_USERS_FILE_PATH = os.getenv("EXCLUDED_USERS_FILE_PATH", os.path.join(config_dir, "excluded_users.txt"))
EXCLUDED_USERS: set[str] = set()

if EXCLUDED_USERS_FILE_PATH:  # Only try to load if path is provided
    if os.path.exists(EXCLUDED_USERS_FILE_PATH):
        try:
            with open(EXCLUDED_USERS_FILE_PATH, "r") as f:
                EXCLUDED_USERS = {line.strip() for line in f if line.strip()}
            if EXCLUDED_USERS:
                logging.info(
                    f"Successfully loaded {len(EXCLUDED_USERS)} excluded users from {EXCLUDED_USERS_FILE_PATH}."
                )
            else:
                logging.info(f"Excluded users file found at {EXCLUDED_USERS_FILE_PATH}, but it is empty.")
        except IOError as e:
            logging.warning(f"Error reading excluded users file at {EXCLUDED_USERS_FILE_PATH}: {e}.")
    else:
        logging.warning(f"Excluded users file not found at {EXCLUDED_USERS_FILE_PATH}.")
else:
    logging.info("EXCLUDED_USERS_FILE_PATH not set. No users will be explicitly excluded.")


# Permissions Matrix Configuration
PERMISSIONS_MATRIX_FILE_PATH = os.getenv(
    "PERMISSIONS_MATRIX_FILE_PATH", os.path.join(config_dir, "permissions_matrix.yml")
)
PERMISSIONS_MATRIX: dict = {}

if PERMISSIONS_MATRIX_FILE_PATH:
    if os.path.exists(PERMISSIONS_MATRIX_FILE_PATH):
        try:
            with open(PERMISSIONS_MATRIX_FILE_PATH, "r") as f:
                loaded_matrix = yaml.safe_load(f)
                if loaded_matrix and isinstance(loaded_matrix.get("permissions"), dict):
                    PERMISSIONS_MATRIX = loaded_matrix["permissions"]
                    if PERMISSIONS_MATRIX:
                        logging.info(
                            f"Successfully loaded {len(PERMISSIONS_MATRIX)} permission categories from {PERMISSIONS_MATRIX_FILE_PATH}."  # noqa: E501
                        )
                    else:
                        logging.warning(
                            f"Permissions matrix file {PERMISSIONS_MATRIX_FILE_PATH} loaded, but the 'permissions' dictionary is empty."  # noqa: E501
                        )
                else:
                    logging.warning(
                        f"Permissions matrix file {PERMISSIONS_MATRIX_FILE_PATH} is empty or not structured correctly (missing 'permissions' key or not a dictionary)."  # noqa: E501
                    )
        except yaml.YAMLError as e:
            logging.error(f"Error parsing YAML from permissions matrix file at {PERMISSIONS_MATRIX_FILE_PATH}: {e}.")
        except IOError as e:
            logging.error(f"Error reading permissions matrix file at {PERMISSIONS_MATRIX_FILE_PATH}: {e}.")
    else:
        logging.warning(f"Permissions matrix file not found at {PERMISSIONS_MATRIX_FILE_PATH}.")
else:
    logging.info("PERMISSIONS_MATRIX_FILE_PATH not set. Permissions matrix features will be disabled.")

# Example of how to access a specific permission setting:
# projet_mattermost_type = PERMISSIONS_MATRIX.get("PROJET", {}).get("mattermost", {}).get("channel_type")
# if projet_mattermost_type:
#     logging.info(f"PROJET Mattermost channel type: {projet_mattermost_type}")
# else:
#     logging.info("PROJET settings or Mattermost channel type not found in matrix.")
