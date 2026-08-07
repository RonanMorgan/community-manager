"""
Central place where environment variables are loaded and exposed as module-level
constants. `clients/client_factory.py` reads from here to build the API clients.

NOTE for whoever builds the new web app: this module currently just loads env
vars into plain constants. It has NOT been adapted to a web app config pattern
yet (e.g. pydantic-settings, per-environment config classes, secrets manager).
Do that adaptation once the backend framework is chosen. See CLAUDE.md.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - CONFIG - %(message)s")

# --- Mattermost ---
# Still a source of truth (see CLAUDE.md). Needed both to call the Mattermost API
# (create channels, list channel members, etc.) and, eventually, to run the
# Mattermost -> DB synchronization job.
MATTERMOST_URL = os.getenv("MATTERMOST_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")  # API token for a Mattermost service/bot account
MATTERMOST_TEAM_ID = os.getenv("MATTERMOST_TEAM_ID")
MATTERMOST_LOGIN_ID = os.getenv("MATTERMOST_LOGIN_ID")  # only needed for the Focalboard endpoints
MATTERMOST_PASSWORD = os.getenv("MATTERMOST_PASSWORD")

# --- Authentik ---
# The other source of truth (see CLAUDE.md): identity, users, and (today) groups.
AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")

# --- Outline ---
OUTLINE_URL = os.getenv("OUTLINE_URL")
OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN")

# --- Brevo ---
BREVO_API_URL = os.getenv("BREVO_API_URL", "https://api.brevo.com/v3")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_DEFAULT_SENDER_EMAIL = os.getenv("BREVO_DEFAULT_SENDER_EMAIL")
BREVO_DEFAULT_SENDER_NAME = os.getenv("BREVO_DEFAULT_SENDER_NAME", "Community Manager")

# --- NocoDB ---
NOCODB_URL = os.getenv("NOCODB_URL")
NOCODB_TOKEN = os.getenv("NOCODB_TOKEN")

# --- Vaultwarden ---
VAULTWARDEN_ORGANIZATION_ID = os.getenv("VAULTWARDEN_ORGANIZATION_ID")
VAULTWARDEN_SERVER_URL = os.getenv("VAULTWARDEN_SERVER_URL")
# BW_PASSWORD is intentionally NOT loaded here (kept out of any object that could be
# logged/serialized). VaultwardenClient reads it directly via os.getenv("BW_PASSWORD").
VAULTWARDEN_API_USERNAME = os.getenv("VAULTWARDEN_API_USERNAME")
VAULTWARDEN_API_PASSWORD = os.getenv("VAULTWARDEN_API_PASSWORD")

# --- General ---
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
