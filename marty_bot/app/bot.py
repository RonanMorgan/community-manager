import websockets
import json
import re  # Import re for regular expressions

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
# authentik_client = None # Will be instance variable
# outline_client = None # Will be instance variable
# mattermost_api_client = None  # Will be instance variable

# try:
#     if config.AUTHENTIK_URL and config.AUTHENTIK_TOKEN:
#         authentik_client = AuthentikClient(config.AUTHENTIK_URL, config.AUTHENTIK_TOKEN)
#         logging.info("AuthentikClient initialized successfully.")
#     else:
#         logging.warning("Authentik URL or Token not configured. Authentik features will be disabled.")

#     if config.OUTLINE_URL and config.OUTLINE_TOKEN:
#         outline_client = OutlineClient(config.OUTLINE_URL, config.OUTLINE_TOKEN)
#         logging.info("OutlineClient initialized successfully.")
#     else:
#         logging.warning("Outline URL or Token not configured. Outline features will be disabled.")

#     if config.MATTERMOST_URL and config.BOT_TOKEN and config.MATTERMOST_TEAM_ID:  # Check for BOT_TOKEN now
#         # This client now uses BOT_TOKEN for its API operations
#         mattermost_api_client = MattermostClient(
#             config.MATTERMOST_URL, config.BOT_TOKEN, config.MATTERMOST_TEAM_ID  # Pass BOT_TOKEN
#         )
#         logging.info("MattermostClient (for API operations using BOT_TOKEN) initialized successfully.")
#     else:
#         logging.warning(
#             "Mattermost URL, Bot Token, or Team ID not fully configured for MattermostClient. Mattermost API operations may fail or be disabled."  # noqa: E501
#         )

# except ValueError as e:
#     logging.error(f"Error initializing API clients: {e}. Bot may not function correctly.")
# Depending on desired behavior, could raise an exception here to stop the bot entirely
# For now, it will continue, but client instances might be None


class MartyBot:
    def __init__(self, config_obj):  # Renamed config to config_obj to avoid conflict with imported config module
        self.config = config_obj
        self.bot_name_mention = f"@{self.config.BOT_NAME.lower()}" if self.config.BOT_NAME else ""

        # Initialize API Clients
        self.authentik_client = None
        if self.config.AUTHENTIK_URL and self.config.AUTHENTIK_TOKEN:
            try:
                self.authentik_client = AuthentikClient(self.config.AUTHENTIK_URL, self.config.AUTHENTIK_TOKEN)
                logging.info("AuthentikClient initialized successfully for MartyBot instance.")
            except ValueError as e:
                logging.warning(f"Failed to initialize AuthentikClient for MartyBot instance: {e}")
        else:
            logging.warning(
                "Authentik URL or Token not configured for MartyBot instance. Authentik features will be disabled."
            )

        self.outline_client = None
        if self.config.OUTLINE_URL and self.config.OUTLINE_TOKEN:
            try:
                self.outline_client = OutlineClient(self.config.OUTLINE_URL, self.config.OUTLINE_TOKEN)
                logging.info("OutlineClient initialized successfully for MartyBot instance.")
            except ValueError as e:
                logging.warning(f"Failed to initialize OutlineClient for MartyBot instance: {e}")
        else:
            logging.warning(
                "Outline URL or Token not configured for MartyBot instance. Outline features will be disabled."
            )

        self.mattermost_api_client = None
        if self.config.MATTERMOST_URL and self.config.BOT_TOKEN and self.config.MATTERMOST_TEAM_ID:
            try:
                self.mattermost_api_client = MattermostClient(
                    self.config.MATTERMOST_URL, self.config.BOT_TOKEN, self.config.MATTERMOST_TEAM_ID
                )
                logging.info(
                    "MattermostClient (for API operations using BOT_TOKEN) initialized successfully for MartyBot instance."
                )
            except ValueError as e:
                logging.warning(f"Failed to initialize MattermostClient (API) for MartyBot instance: {e}")
        else:
            logging.warning(
                "Mattermost URL, Bot Token, or Team ID not fully configured for MattermostClient instance. Mattermost API operations may fail or be disabled."
            )

        # Placeholder for WebSocket connection, will be initialized in 'run_bot' method
        self.websocket = None

    def envoyer_message(self, channel_id, message_text, thread_id=None):  # Added thread_id as optional
        if not self.config.BOT_TOKEN or not self.config.MATTERMOST_URL:
            logging.error("BOT_TOKEN or MATTERMOST_URL not configured for bot instance. Cannot send message.")
            return

        headers = {
            "Authorization": f"Bearer {self.config.BOT_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "channel_id": channel_id,
            "message": message_text,
        }
        if thread_id:  # Add root_id to payload if thread_id is provided
            payload["root_id"] = thread_id

        post_url = f"{self.config.MATTERMOST_URL.rstrip('/')}/api/v4/posts"

        logging.debug(
            f"Mattermost API >> Sending message to channel {channel_id} (thread: {thread_id}). Payload: {json.dumps(payload)}"
        )

        log_message = f"Sending message to {post_url} in channel {channel_id}: {message_text[:100]}..."
        logging.info(log_message)
        try:
            response = requests.post(post_url, headers=headers, json=payload)
            response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
            logging.info(f"Message sent successfully to channel {channel_id}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending message to Mattermost: {e}")

    # THIS IS THE OLDER VERSION TO BE DELETED
    # def _parse_command_from_mention(self, message_text):
    #     if self.bot_name_mention and self.bot_name_mention in message_text.lower():
    #         parts = message_text.lower().split(self.bot_name_mention, 1)
    #         if len(parts) > 1:
    #             command_str = parts[1].strip()
    #             return command_str
    #     return None

    def _parse_command_from_mention(self, message_text):  # This is the new regex version
        # Ensure self.bot_name_mention is not empty and is actually present in the message
        if not self.bot_name_mention or self.bot_name_mention not in message_text.lower():
            return None

        # Use regex to ensure the mention is a whole word and capture the command part
        # The mention should be at the beginning of the message or preceded by a space.
        # It should be followed by a space, or end of the message.
        # Example: "@botname command" or "hello @botname command"
        # We made self.bot_name_mention lowercase in __init__

        # Escape special characters in bot name for regex
        escaped_mention = re.escape(self.bot_name_mention)

        # Regex to find "@botname" followed by a command, or just "@botname"
        # It looks for the mention, then captures anything after it.
        # The (?i) makes the match case-insensitive for the message_text part.
        # The \s+ makes sure there's a space after mention if there's a command.
        # If no command, command_part will be None or empty after strip.
        match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text)

        if match:
            command_part = match.group(1)
            if command_part is not None:
                return command_part.strip()
            return ""  # Bot was mentioned, but no command followed (e.g. "@botname" or "hello @botname")
        return None

    def _handle_create_group(self, project_name, channel_id):
        response_parts = [f"Processing 'create_group' for project: **{project_name}**"]

        # Authentik
        if self.authentik_client:
            auth_success = self.authentik_client.create_group(project_name)
            response_parts.append(f"- Authentik group creation: {'Success' if auth_success else 'Failed'}")
        else:
            response_parts.append("- Authentik client not initialized. Skipping.")

        # Outline
        if self.outline_client:
            outline_success = self.outline_client.create_group(project_name)
            response_parts.append(f"- Outline collection creation: {'Success' if outline_success else 'Failed'}")
        else:
            response_parts.append("- Outline client not initialized. Skipping.")

        # Mattermost
        if self.mattermost_api_client:
            mm_success = self.mattermost_api_client.create_channel(project_name)  # team_id handled by client
            response_parts.append(f"- Mattermost channel creation: {'Success' if mm_success else 'Failed'}")
        else:
            response_parts.append("- Mattermost API client not initialized. Skipping.")

        final_response = "\n".join(response_parts)
        self.envoyer_message(channel_id, final_response)

    async def _handle_message_event(self, message_data):
        post_info = message_data.get("data", {}).get("post")
        if not post_info:
            logging.warning("No post data in 'posted' event.")
            return

        post_data = json.loads(post_info)  # post is a JSON string
        message_text = post_data.get("message", "")
        channel_id = post_data.get("channel_id")
        # user_id = post_data.get("user_id") # TODO: Use to avoid self-reply if bot's own user_id is known

        command_str = self._parse_command_from_mention(message_text)

        if command_str is None:
            # Bot was not mentioned in a way that `_parse_command_from_mention` recognizes
            return

        if command_str == "":  # Bot was mentioned, but no command followed
            self.envoyer_message(
                channel_id,
                "Hi! You mentioned me. Try `create_group <project_name>` or ask for `help`.",  # Removed f-prefix
            )
            return

        if command_str.startswith("create_group"):
            project_name_parts = command_str.split("create_group", 1)
            project_name = ""
            if len(project_name_parts) > 1:
                project_name = project_name_parts[1].strip()

            if project_name:
                self._handle_create_group(project_name, channel_id)
            else:
                self.envoyer_message(
                    channel_id,
                    f"Please specify a project name for create_group. Usage: {self.bot_name_mention} create_group <project_name>",
                )  # noqa: E501

        elif command_str:  # Any other command recognized after mention
            self.envoyer_message(channel_id, "Bonjour toi ! How can I help you today?")
        # If command_str is empty (bot mentioned but no command), it's handled by the check in _parse_command_from_mention's caller

    async def on_message(self, ws, message_str):  # ws might not be needed if not directly used
        logging.debug(f"WebSocket << Raw incoming message: {message_str}")
        try:
            message_data = json.loads(message_str)
            event_type = message_data.get("event")

            if event_type == "posted":
                await self._handle_message_event(message_data)
            # TODO: Handle other event types like 'hello' for connection confirmation if needed

        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON message: {message_str}")
        except Exception as e:
            logging.error(f"Error in on_message: {e}. Original message: {message_str}", exc_info=True)

    async def on_error(self, ws, error):  # ws might not be needed
        logging.error(f"WebSocket Error: {error}")

    async def on_close(self, ws, close_status_code, close_msg):  # ws might not be needed
        logging.info(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")

    async def on_open(self, ws):  # Changed from global config to self.config
        logging.info("WebSocket connection opened.")
        if not self.config.BOT_TOKEN:
            logging.error(
                "BOT_TOKEN not configured for bot instance. Cannot send authentication challenge."
            )  # noqa: E501
            await ws.close()
            return

        auth_data = {
            "seq": 1,
            "action": "authentication_challenge",
            "data": {"token": self.config.BOT_TOKEN},
        }  # noqa: E501
        try:
            await ws.send(json.dumps(auth_data))
            logging.info(
                f"Sent authentication challenge for bot token starting with: {str(self.config.BOT_TOKEN)[:4]}..."
            )
        except Exception as e:
            logging.error(f"Error sending authentication challenge: {e}")

    async def _run_websocket_loop(self):
        if not self.config.MATTERMOST_URL or not self.config.BOT_TOKEN:
            logging.error("Mattermost URL or Bot Token not configured for bot instance. Cannot start WebSocket.")
            return

        if not self.authentik_client and not self.outline_client and not self.mattermost_api_client:
            logging.error(
                "No API clients were initialized successfully for bot instance. Bot might be non-functional. Aborting run."
            )
            return

        ws_scheme = "ws"
        if self.config.MATTERMOST_URL.startswith("https://"):
            ws_scheme = "wss"

        protocol_stripped_url = self.config.MATTERMOST_URL.replace("https://", "").replace("http://", "")
        ws_url = f"{ws_scheme}://{protocol_stripped_url}/api/v4/websocket"

        logging.info(f"Attempting to connect to WebSocket: {ws_url} for bot instance")

        retry_delay = 5
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=60, ping_timeout=30) as self.websocket:
                    await self.on_open(self.websocket)
                    async for message in self.websocket:
                        await self.on_message(self.websocket, message)
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

    def start(self):  # Renamed run to start to avoid conflict if run is used for direct script exec
        logging.info("Initializing Marty Bot instance...")

        # Check if critical clients were initialized in __init__
        # This is an additional check or can replace the one in _run_websocket_loop
        if not self.mattermost_api_client:  # Example critical client
            logging.error("Mattermost API client not initialized. MartyBot instance cannot fully operate.")
            # Depending on desired behavior, could prevent startup:
            # return

        logging.info("Starting WebSocket listener for MartyBot instance...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_websocket_loop())
        except KeyboardInterrupt:
            logging.info("WebSocket listener stopped by user for MartyBot instance.")
        except Exception as e:
            logging.critical(f"WebSocket listener for MartyBot instance failed critically: {e}", exc_info=True)
        finally:
            loop.close()


# (Old global functions below are to be removed or commented out)
# def envoyer_message(channel_id, message): ...
# async def on_message(ws, message_str): ...
# async def on_error(ws, error): ...
# async def on_close(ws, close_status_code, close_msg): ...
# async def on_open(ws): ...
# async def run_websocket_app(): ...
# def run(): ...


if __name__ == "__main__":
    logging.info("Starting Marty Bot directly (for testing WebSocket connection)...")

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

        # Instantiate and run the bot
        marty_bot_instance = MartyBot(config)  # Pass the imported config module
        marty_bot_instance.start()
