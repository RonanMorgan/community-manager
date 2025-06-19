import websockets
import json
import threading
import requests
import os
import asyncio # Required for run_websocket_app

from app.config import MATTERMOST_URL, MATTERMOST_TOKEN, BOT_TOKEN, BOT_NAME, MATTERMOST_TEAM_ID

# Import actual client functions
from app.authentik_client import create_group as authentik_create_group
from app.outline_client import create_group as outline_create_group
from app.mattermost_client import create_channel as mattermost_create_channel

# This function is provided in the issue, assuming it's for sending messages back to Mattermost
def envoyer_message(channel_id, message):
    headers = {
        "Authorization": f"Bearer {BOT_TOKEN}", # Use BOT_TOKEN for posting messages as the bot
        "Content-Type": "application/json",
    }
    payload = {
        "channel_id": channel_id,
        "message": message,
    }
    # Construct the correct API endpoint for posting messages
    # MATTERMOST_URL should be the base URL, e.g., http://localhost:8065
    post_url = f"{MATTERMOST_URL}/api/v4/posts"

    print(f"Sending message to {post_url} in channel {channel_id}: {message}")
    try:
        response = requests.post(post_url, headers=headers, json=payload)
        if response.status_code == 201:
            print(f"Message sent successfully to channel {channel_id}")
        else:
            print(f"Error sending message: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message (network request failed): {e}")


async def on_message(ws, message_str):
    try:
        message_data = json.loads(message_str)
        event = message_data.get("event")

        if event == "posted":
            post_info = message_data.get("data", {}).get("post")
            if not post_info:
                print("No post data in message")
                return

            post_data = json.loads(post_info) # post is a JSON string
            message_text = post_data.get("message", "")
            channel_id = post_data.get("channel_id")
            sender_id = post_data.get("user_id")

            # Get bot's user ID to prevent self-reply more reliably
            # This might require an initial API call or be stored in config if known
            # For now, we assume BOT_NAME is unique enough or sender_is_bot check works.
            # A common check is if 'props' exists and 'from_webhook' is 'true' or if user_id is the bot's user_id.
            # Or, if the post is from a bot, the `post_data.get("props", {}).get("from_bot") == "true"`
            # However, simpler check for now:
            # A more robust way to get bot's own user ID would be to fetch it on startup.
            # For now, we'll rely on BOT_NAME or assume the bot doesn't trigger itself.
            # A common pattern for bots is that their own messages might not trigger the 'posted' event
            # in the same way, or they lack a 'user_id' that's a typical user.
            # Let's assume mattermost server is configured so bot does not see its own messages,
            # or we need a better way to identify bot's own messages.
            # The previous `user_id == BOT_TOKEN` was incorrect as BOT_TOKEN is an access token.
            # We need the actual user ID of the bot. If not available, we might reply to self.
            # For now, let's just log and proceed.
            # print(f"Message from user_id: {sender_id}")


            if f"@{BOT_NAME}" in message_text:
                command_parts = message_text.split(f"@{BOT_NAME}", 1) # Split only on the first mention
                actual_command = ""
                if len(command_parts) > 1:
                    actual_command = command_parts[1].strip()

                if actual_command.startswith("create_group"):
                    try:
                        project_name = actual_command.split("create_group", 1)[1].strip()
                        if project_name:
                            response_parts = [f"Processing 'create_group' for project: **{project_name}**"]

                            # Authentik
                            auth_success = authentik_create_group(project_name)
                            response_parts.append(f"- Authentik group creation: {'Success' if auth_success else 'Failed'}")

                            # Outline
                            outline_success = outline_create_group(project_name)
                            response_parts.append(f"- Outline collection creation: {'Success' if outline_success else 'Failed'}")

                            # Mattermost
                            # For mattermost_create_channel, team_id is needed. Using from config.
                            if not MATTERMOST_TEAM_ID:
                                mm_success_msg = "Failed (MATTERMOST_TEAM_ID not configured)"
                                print("MATTERMOST_TEAM_ID is not configured in .env or config.py")
                            else:
                                mm_success = mattermost_create_channel(project_name, team_id=MATTERMOST_TEAM_ID)
                                mm_success_msg = 'Success' if mm_success else 'Failed'
                            response_parts.append(f"- Mattermost channel creation: {mm_success_msg}")

                            final_response = "\n".join(response_parts)
                        else:
                            final_response = "Please specify a project name for create_group. Usage: @BOT_NAME create_group <project_name>"
                    except IndexError:
                        final_response = "Command 'create_group' needs a project name. Usage: @BOT_NAME create_group <project_name>"
                    except Exception as e:
                        print(f"Error processing create_group command: {e}")
                        final_response = f"An unexpected error occurred while processing your request for '{project_name}'."

                    envoyer_message(channel_id, final_response)

                elif actual_command: # Any other command directed at the bot
                    envoyer_message(channel_id, "Bonjour toi ! How can I help you today?")
                else: # Bot was mentioned but no command followed
                    envoyer_message(channel_id, f"Hi! You mentioned me @{BOT_NAME}. Try `create_group <project_name>` or ask for `help`.")

    except json.JSONDecodeError:
        print(f"Error decoding JSON message: {message_str}")
    except Exception as e:
        print(f"Error in on_message: {e}. Original message: {message_str}")


async def on_error(ws, error):
    print(f"WebSocket Error: {error}")

async def on_close(ws, close_status_code, close_msg):
    print(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")

async def on_open(ws):
    print("WebSocket connection opened.")
    auth_data = {
        "seq": 1, # Sequence number, should be incremented for each message sent by the client
        "action": "authentication_challenge",
        "data": {"token": BOT_TOKEN} # Using BOT_TOKEN for WebSocket auth
    }
    try:
        await ws.send(json.dumps(auth_data))
        print(f"Sent authentication challenge for bot token starting with: {str(BOT_TOKEN)[:4]}...")
    except Exception as e:
        print(f"Error sending authentication challenge: {e}")


async def run_websocket_app():
    if not MATTERMOST_URL or not BOT_TOKEN:
        print("MATTERMOST_URL or BOT_TOKEN not configured. Cannot start WebSocket.")
        return

    protocol_stripped_url = MATTERMOST_URL.replace("https://", "").replace("http://", "")
    # Ensure ws or wss prefix based on original URL or a config setting
    # For simplicity, defaulting to ws. Production might need wss.
    ws_scheme = "ws"
    if MATTERMOST_URL.startswith("https://"):
        ws_scheme = "wss"

    ws_url = f"{ws_scheme}://{protocol_stripped_url}/api/v4/websocket"

    print(f"Attempting to connect to WebSocket: {ws_url}")

    retry_delay = 5 # seconds
    while True: # Keep trying to connect
        try:
            async with websockets.connect(ws_url, ping_interval=60, ping_timeout=30) as websocket:
                await on_open(websocket)
                async for message in websocket:
                    await on_message(websocket, message)
        except websockets.exceptions.ConnectionClosed as e:
            print(f"WebSocket connection closed: {e}. Retrying in {retry_delay}s...")
        except ConnectionRefusedError:
            print(f"Connection refused for WebSocket at {ws_url}. Is Mattermost running? Retrying in {retry_delay}s...")
        except Exception as e: # Catch other exceptions like gaierror
            print(f"WebSocket connection error: {e}. Retrying in {retry_delay}s...")

        await asyncio.sleep(retry_delay)


def run():
    print("Starting WebSocket listener...")
    # asyncio.run(run_websocket_app()) # This will block if called directly in a sync function.
    # The FastAPI startup event will run this in a thread, which is fine.
    # If running bot.py directly, ensure it handles the event loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_websocket_app())
    except KeyboardInterrupt:
        print("WebSocket listener stopped by user.")
    finally:
        loop.close()


if __name__ == "__main__":
    # This part is for direct execution of bot.py for testing
    print("Starting Marty Bot directly (for testing WebSocket connection)...")
    # Need to load .env for direct execution if config relies on it
    from dotenv import load_dotenv
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dotenv_path = os.path.join(project_root, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        print(f".env loaded from {dotenv_path}")
    else:
        print(f".env file not found at {dotenv_path}, ensure it's created with necessary tokens.")

    # Re-check config variables after attempting to load .env
    from app.config import MATTERMOST_URL as MM_URL_CHECK, BOT_TOKEN as BT_CHECK, MATTERMOST_TEAM_ID as MTI_CHECK
    if not MM_URL_CHECK or not BT_CHECK:
         print("Cannot start: MATTERMOST_URL or BOT_TOKEN is missing after .env load attempt.")
    elif not MTI_CHECK:
        print("Warning: MATTERMOST_TEAM_ID is not set. `create_group` command will fail for Mattermost channel creation.")
    else:
        print(f"Config check: MATTERMOST_URL={MM_URL_CHECK}, BOT_TOKEN starts with {str(BT_CHECK)[:4]}, TEAM_ID={MTI_CHECK}")
        run()
