import os
from dotenv import load_dotenv

load_dotenv()

MATTERMOST_URL = os.getenv("MATTERMOST_URL")
MATTERMOST_TOKEN = os.getenv("MATTERMOST_TOKEN")  # Admin/API token for operations like channel creation
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Bot's own token for WebSocket/posting messages as bot
BOT_NAME = os.getenv("BOT_NAME")
MATTERMOST_TEAM_ID = os.getenv("MATTERMOST_TEAM_ID")  # Team ID for channel creation

AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")

OUTLINE_URL = os.getenv("OUTLINE_URL")
OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN")
