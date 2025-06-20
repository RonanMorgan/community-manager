import websockets
import json

# import threading # No longer used
import requests

# import os # No longer used
import asyncio
import logging

# Load configuration first
from app import config

# Configure basic logging based on DEBUG status
if config.DEBUG:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )
    logging.debug("DEBUG mode is enabled. Verbose logging active.")
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Import client classes
from app.authentik_client import AuthentikClient
from app.outline_client import OutlineClient
from app.mattermost_client import MattermostClient

# Global client instances - initialized after config is loaded
authentik_client = None
outline_client = None
mattermost_api_client = None  # Renamed to avoid confusion with a potential websocket client variable

try:
    if config.AUTHENTIK_URL and config.AUTHENTIK_TOKEN:
        authentik_client = AuthentikClient(config.AUTHENTIK_URL, config.AUTHENTIK_TOKEN)
        logging.info("AuthentikClient initialized successfully.")
    else:
        logging.warning("Authentik URL or Token not configured. Authentik features will be disabled.")

    if config.OUTLINE_URL and config.OUTLINE_TOKEN:
        outline_client = OutlineClient(config.OUTLINE_URL, config.OUTLINE_TOKEN)
        logging.info("OutlineClient initialized successfully.")
    else:
        logging.warning("Outline URL or Token not configured. Outline features will be disabled.")

    if config.MATTERMOST_URL and config.BOT_TOKEN and config.MATTERMOST_TEAM_ID:  # Check for BOT_TOKEN now
        # This client now uses BOT_TOKEN for its API operations
        mattermost_api_client = MattermostClient(
            config.MATTERMOST_URL, config.BOT_TOKEN, config.MATTERMOST_TEAM_ID  # Pass BOT_TOKEN
        )
        logging.info("MattermostClient (for API operations using BOT_TOKEN) initialized successfully.")
    else:
        logging.warning(
            "Mattermost URL, Bot Token, or Team ID not fully configured for MattermostClient. Mattermost API operations may fail or be disabled."  # noqa: E501
        )

except ValueError as e:
    logging.error(f"Error initializing API clients: {e}. Bot may not function correctly.")
    # Depending on desired behavior, could raise an exception here to stop the bot entirely
    # For now, it will continue, but client instances might be None


# envoyer_message uses BOT_TOKEN (for posting messages as the bot)
def envoyer_message(channel_id, message):
    if not config.BOT_TOKEN or not config.MATTERMOST_URL:
        logging.error("BOT_TOKEN or MATTERMOST_URL not configured. Cannot send message.")
        return

    headers = {
        "Authorization": f"Bearer {config.BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "channel_id": channel_id,
        "message": message,
    }
    post_url = f"{config.MATTERMOST_URL.rstrip('/')}/api/v4/posts"

    # Debug log for outgoing message payload
    logging.debug(
        f"Mattermost API >> Sending message to channel {channel_id}. Payload: {json.dumps(payload)}"
    )  # Not logging thread_id as it's not a current param

    log_message = f"Sending message to {post_url} in channel {channel_id}: {message[:100]}..."
    logging.info(log_message)
    try:
        response = requests.post(post_url, headers=headers, json=payload)
        if response.status_code == 201:
            logging.info(f"Message sent successfully to channel {channel_id}")
        else:
            logging.error(f"Error sending message: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error sending message (network request failed): {e}")


async def on_message(ws, message_str):
    logging.debug(f"WebSocket << Raw incoming message: {message_str}")
    try:
        message_data = json.loads(message_str)
        event = message_data.get("event")

        if event == "posted":
            post_info = message_data.get("data", {}).get("post")
            if not post_info:
                logging.warning("No post data in 'posted' event.")
                return

            post_data = json.loads(post_info)
            message_text = post_data.get("message", "")
            channel_id = post_data.get("channel_id")
            # sender_id = post_data.get("user_id") # Potentially useful for ignoring self

            # Basic check to prevent bot reacting to its own messages if they don't contain @BOT_NAME
            # A more robust check would involve getting the bot's actual user_id.
            if f"@{config.BOT_NAME}" not in message_text:
                # If bot name is not mentioned, simply ignore. This also helps avoid self-replies to simple status messages.
                return

            command_parts = message_text.split(f"@{config.BOT_NAME}", 1)
            actual_command = ""
            if len(command_parts) > 1:
                actual_command = command_parts[1].strip()

            if actual_command.startswith("create_group"):
                project_name_parts = actual_command.split("create_group", 1)
                if len(project_name_parts) > 1:
                    project_name = project_name_parts[1].strip()
                else:
                    project_name = ""  # Will trigger error below

                if project_name:
                    response_parts = [f"Processing 'create_group' for project: **{project_name}**"]

                    # Authentik
                    if authentik_client:
                        auth_success = authentik_client.create_group(project_name)
                        response_parts.append(f"- Authentik group creation: {'Success' if auth_success else 'Failed'}")
                    else:
                        response_parts.append("- Authentik client not initialized. Skipping.")

                    # Outline
                    if outline_client:
                        outline_success = outline_client.create_group(project_name)
                        response_parts.append(
                            f"- Outline collection creation: {'Success' if outline_success else 'Failed'}"
                        )
                    else:
                        response_parts.append("- Outline client not initialized. Skipping.")

                    # Mattermost
                    if mattermost_api_client:
                        # The default team_id is handled by the client instance now
                        mm_success = mattermost_api_client.create_channel(project_name)
                        response_parts.append(
                            f"- Mattermost channel creation: {'Success' if mm_success else 'Failed'}"
                        )
                    else:
                        response_parts.append("- Mattermost API client not initialized. Skipping.")

                    final_response = "\n".join(response_parts)
                else:
                    final_response = f"Please specify a project name for create_group. Usage: @{config.BOT_NAME} create_group <project_name>"  # noqa: E501

                envoyer_message(channel_id, final_response)

            elif actual_command:  # Any other command directed at the bot
                envoyer_message(channel_id, "Bonjour toi ! How can I help you today?")
            else:  # Bot was mentioned but no command followed
                envoyer_message(
                    channel_id,
                    f"Hi! You mentioned me @{config.BOT_NAME}. Try `create_group <project_name>` or ask for `help`.",
                )

    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON message: {message_str}")
    except Exception as e:
        logging.error(f"Error in on_message: {e}. Original message: {message_str}", exc_info=True)


async def on_error(ws, error):
    logging.error(f"WebSocket Error: {error}")


async def on_close(ws, close_status_code, close_msg):
    logging.info(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")


async def on_open(ws):
    logging.info("WebSocket connection opened.")
    if not config.BOT_TOKEN:
        logging.error("BOT_TOKEN not configured. Cannot send authentication challenge.")  # noqa: E501
        await ws.close()  # Close connection if auth token is missing
        return

    auth_data = {"seq": 1, "action": "authentication_challenge", "data": {"token": config.BOT_TOKEN}}  # noqa: E501
    try:
        await ws.send(json.dumps(auth_data))
        logging.info(f"Sent authentication challenge for bot token starting with: {str(config.BOT_TOKEN)[:4]}...")
    except Exception as e:
        logging.error(f"Error sending authentication challenge: {e}")


async def run_websocket_app():
    if not config.MATTERMOST_URL or not config.BOT_TOKEN:
        logging.error("MATTERMOST_URL or BOT_TOKEN not configured. Cannot start WebSocket.")
        return

    # Check if critical clients failed to initialize
    if not authentik_client and not outline_client and not mattermost_api_client:
        # This check can be more nuanced based on which clients are critical
        logging.error("No API clients were initialized successfully. " "Bot might be non-functional. Aborting run.")
        # return # Or raise an exception to be caught by main.py

    ws_scheme = "ws"
    if config.MATTERMOST_URL.startswith("https://"):
        ws_scheme = "wss"

    protocol_stripped_url = config.MATTERMOST_URL.replace("https://", "").replace("http://", "")
    ws_url = f"{ws_scheme}://{protocol_stripped_url}/api/v4/websocket"

    logging.info(f"Attempting to connect to WebSocket: {ws_url}")

    retry_delay = 5
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=60, ping_timeout=30) as websocket:
                await on_open(websocket)
                async for message in websocket:
                    await on_message(websocket, message)
        except websockets.exceptions.ConnectionClosed as e:
            logging.warning(f"WebSocket connection closed: {e}. Retrying in {retry_delay}s...")
        except ConnectionRefusedError:
            logging.error(
                f"Connection refused for WebSocket at {ws_url}. "
                f"Is Mattermost running? Retrying in {retry_delay}s..."
            )
        except Exception as e:
            logging.error(
                f"WebSocket connection error: {e}. Retrying in {retry_delay}s...", exc_info=True  # noqa: E501
            )

        await asyncio.sleep(retry_delay)


def run():
    logging.info("Initializing Marty Bot...")

    # Initial check if any client failed to initialize due to config errors passed from global scope
    if authentik_client is None and outline_client is None and mattermost_api_client is None:
        # This condition means all clients failed to initialize due to missing configs handled by the global try-except.
        # The ValueError from client constructors would have been caught at module load time.
        # This is more about the config not being present leading to None clients.
        all_configs_missing = True
        if config.AUTHENTIK_URL and config.AUTHENTIK_TOKEN:
            all_configs_missing = False
        if config.OUTLINE_URL and config.OUTLINE_TOKEN:
            all_configs_missing = False
        if config.MATTERMOST_URL and config.MATTERMOST_TOKEN and config.MATTERMOST_TEAM_ID:
            all_configs_missing = False

        if all_configs_missing:
            logging.error(
                "CRITICAL: All API client configurations are missing. Bot cannot operate effectively and will not start."
            )
            return  # Prevent bot from running if all primary clients are unconfigured.

    logging.info("Starting WebSocket listener...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_websocket_app())
    except KeyboardInterrupt:
        logging.info("WebSocket listener stopped by user.")
    except Exception as e:
        logging.critical(f"WebSocket listener failed critically: {e}", exc_info=True)
    finally:
        loop.close()


if __name__ == "__main__":
    logging.info("Starting Marty Bot directly (for testing WebSocket connection)...")
    # .env should be loaded by app.config at the very beginning.
    # If running this directly, ensure .env is in the marty_bot parent directory or project root.

    # Check essential config for direct run
    if not config.MATTERMOST_URL or not config.BOT_TOKEN or not config.BOT_NAME:
        logging.critical(
            "Cannot start directly: MATTERMOST_URL, BOT_TOKEN, or BOT_NAME is missing. "
            "Check .env file and config.py."
        )
    elif not config.MATTERMOST_TEAM_ID:
        logging.warning(
            "MATTERMOST_TEAM_ID is not set. `create_group` for Mattermost channels will fail."  # noqa: E501
        )
    else:
        log_msg = (
            f"Direct run config check: URL={config.MATTERMOST_URL}, BotName={config.BOT_NAME}, "
            f"Token starts with {str(config.BOT_TOKEN)[:4]}, TeamID={config.MATTERMOST_TEAM_ID}"
        )
        logging.info(log_msg)
        run()
