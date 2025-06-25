import os
from dotenv import load_dotenv

load_dotenv()

MATTERMOST_URL = os.getenv("MATTERMOST_URL")
# MATTERMOST_TOKEN = os.getenv("MATTERMOST_TOKEN") # Admin/API token for operations like channel creation - REMOVED
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Bot's own token for WebSocket/posting messages as bot
BOT_NAME = os.getenv("BOT_NAME")
MATTERMOST_TEAM_ID = os.getenv("MATTERMOST_TEAM_ID")  # Team ID for channel creation

AUTHENTIK_URL = os.getenv("AUTHENTIK_URL")
AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_TOKEN")

OUTLINE_URL = os.getenv("OUTLINE_URL")
OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN")

# General Configuration
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# User Exclusion Configuration
# Defines the path to the file containing a list of usernames to exclude from sync operations.
# Each username should be on a new line.
EXCLUDED_USERS_FILE_PATH = os.getenv("EXCLUDED_USERS_FILE_PATH", "config/excluded_users.txt")
EXCLUDED_USERS: set[str] = set()

# Attempt to load the excluded users list
if EXCLUDED_USERS_FILE_PATH and os.path.exists(EXCLUDED_USERS_FILE_PATH):
    try:
        with open(EXCLUDED_USERS_FILE_PATH, "r") as f:
            # Read lines, strip whitespace, and add non-empty lines to the set
            EXCLUDED_USERS = {line.strip() for line in f if line.strip()}
        if EXCLUDED_USERS:
            print(f"Successfully loaded {len(EXCLUDED_USERS)} excluded users from {EXCLUDED_USERS_FILE_PATH}.") # noqa: T201
        else:
            print(f"Excluded users file found at {EXCLUDED_USERS_FILE_PATH}, but it is empty. No users will be excluded based on this file.") # noqa: T201
    except IOError as e:
        # Using print for simple config-time feedback. A logger might not be configured yet.
        print(f"Warning: Error reading excluded users file at {EXCLUDED_USERS_FILE_PATH}: {e}. No users will be excluded based on this file.") # noqa: T201
elif EXCLUDED_USERS_FILE_PATH:
    print(f"Warning: Excluded users file not found at {EXCLUDED_USERS_FILE_PATH} (as specified by EXCLUDED_USERS_FILE_PATH). No users will be excluded.") # noqa: T201
else:
    # This case means EXCLUDED_USERS_FILE_PATH was not set and the default path also wasn't used/found.
    # This is less of a "warning" and more of an informational note if the feature is optional.
    print(f"Info: EXCLUDED_USERS_FILE_PATH not set. No users will be explicitly excluded.") # noqa: T201
