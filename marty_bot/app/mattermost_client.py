import requests
import json
import re
from app.config import MATTERMOST_URL, MATTERMOST_TOKEN, BOT_TOKEN

# Attempt to import MATTERMOST_TEAM_ID, but allow it to be None if not set
try:
    from app.config import MATTERMOST_TEAM_ID
except ImportError:
    MATTERMOST_TEAM_ID = None

def slugify(text: str) -> str:
    """
    Simple slugify function:
    - Convert to lowercase
    - Replace spaces and underscores with hyphens
    - Remove characters that are not alphanumeric or hyphens
    - Ensure it doesn't start or end with a hyphen
    """
    text = text.lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = text.strip("-")
    if not text: # Handle case where project_name is e.g. "!!!"
        return "default-channel-name"
    return text

def create_channel(project_name: str, team_id: str = None) -> bool:
    """
    Creates a new public channel in Mattermost.
    `project_name` will be used as the display name and slugified for the channel name.
    `team_id` is required. It can be passed directly or fetched from config.
    """
    actual_team_id = team_id or MATTERMOST_TEAM_ID

    if not MATTERMOST_URL or not MATTERMOST_TOKEN: # Using MATTERMOST_TOKEN for channel creation
        print("Mattermost URL or Admin/Bot Token (MATTERMOST_TOKEN) not configured for channel creation.")
        return False

    if not actual_team_id:
        print("Mattermost Team ID not provided or configured (MATTERMOST_TEAM_ID). Cannot create channel.")
        # Instructions for user if team_id is missing
        print("Please ensure MATTERMOST_TEAM_ID is set in your .env file and app/config.py, or pass team_id to create_channel.")
        return False

    api_url = f"{MATTERMOST_URL}/api/v4/channels"

    # Use MATTERMOST_TOKEN for channel creation (assumed to have higher privileges)
    # BOT_TOKEN is typically for the WebSocket bot user itself.
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {MATTERMOST_TOKEN}",
    }

    channel_name_slug = slugify(project_name)
    if len(channel_name_slug) > 64: # Mattermost channel name length limit
        channel_name_slug = channel_name_slug[:64].strip('-')

    payload = {
        "team_id": actual_team_id,
        "name": channel_name_slug, # URL-friendly name
        "display_name": project_name, # Display name in UI
        "type": "O",  # "O" for public, "P" for private
        "purpose": f"Channel for project {project_name}", # Optional
        "header": f"Project {project_name}", # Optional
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code == 201:
            created_channel = response.json()
            print(f"Mattermost channel '{created_channel.get('display_name')}' (name: {created_channel.get('name')}) created successfully. Channel ID: {created_channel.get('id')}")
            return True
        else:
            print(f"Error creating Mattermost channel '{project_name}': {response.status_code} - {response.text}")
            try:
                error_details = response.json()
                if error_details.get("id") == "store.sql_channel.save_channel.exists.app_error":
                    print(f"Hint: A channel with the name '{channel_name_slug}' or display name '{project_name}' might already exist on this team.")
                elif error_details.get("id") == "api.channel.create_channel.invalid_name.app_error":
                     print(f"Hint: The generated channel name '{channel_name_slug}' is invalid. Check for length or character restrictions not covered by slugify.")
            except json.JSONDecodeError:
                pass
            return False
    except requests.exceptions.RequestException as e:
        print(f"Request failed for Mattermost channel creation '{project_name}': {e}")
        return False

if __name__ == '__main__':
    from app.config import load_dotenv
    load_dotenv()

    if not MATTERMOST_URL or not MATTERMOST_TOKEN or not MATTERMOST_TEAM_ID:
        print("Please set MATTERMOST_URL, MATTERMOST_TOKEN, and MATTERMOST_TEAM_ID in your .env for testing.")
    else:
        print(f"Testing Mattermost client with URL: {MATTERMOST_URL}, Team ID: {MATTERMOST_TEAM_ID}")

        # Test 1: Create a new channel
        project_name_test = "Project Alpha Team"
        print(f"\nAttempting to create channel for: '{project_name_test}'")
        success_new = create_channel(project_name_test)
        print(f"Mattermost channel creation test successful: {success_new}")

        # Test 2: Attempt to create the same channel again (should fail or be handled)
        if success_new: # Only try re-creating if first one seemed to work
            print(f"\nAttempting to create channel AGAIN for: '{project_name_test}' (should fail)")
            success_existing = create_channel(project_name_test)
            print(f"Mattermost existing channel creation test successful: {success_existing}")

        # Test 3: Channel with a very long name
        long_project_name = "This is a very very long project name that will exceed sixty four characters limit for sure and needs to be truncated"
        print(f"\nAttempting to create channel for long name: '{long_project_name}'")
        success_long = create_channel(long_project_name)
        print(f"Mattermost long channel name creation test successful: {success_long}")

        # Test 4: Channel with special characters
        special_char_name = "Project X!@#$%^&*()_+"
        print(f"\nAttempting to create channel for special chars: '{special_char_name}'")
        success_special = create_channel(special_char_name)
        print(f"Mattermost special chars channel name creation test successful: {success_special}")

        # Test 5: Channel with only special characters (slug should become 'default-channel-name')
        only_special_name = "!@#$%^&*()_+"
        print(f"\nAttempting to create channel for only special chars: '{only_special_name}'")
        success_only_special = create_channel(only_special_name)
        print(f"Mattermost only special chars channel name creation test successful: {success_only_special}")
