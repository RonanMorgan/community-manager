import websockets
import json
import re  # Import re for regular expressions

# import threading # No longer used
import requests

# import os # No longer used
import asyncio
import logging
import signal # For graceful shutdown
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

# Configure basic logging based on DEBUG status
# This was moved down to be after 'from app import config'
# if config.DEBUG:
#     logging.basicConfig(
#         level=logging.DEBUG, format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
#     )
#     logging.debug("DEBUG mode is enabled. Verbose logging active.")
# else:
#     logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class MartyBot:
    def __init__(self, config_obj):  # Renamed config to config_obj to avoid conflict with imported config module
        self.config = config_obj

        # Ensure logging is configured based on the instance's config
        if self.config.DEBUG:
            logging.getLogger().setLevel(logging.DEBUG)
            # Update formatter for all handlers if basicConfig was already called
            for handler in logging.getLogger().handlers:
                handler.setFormatter(
                    logging.Formatter("%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s")
                )
            logging.debug("DEBUG mode is enabled for MartyBot instance. Verbose logging active.")
        else:
            logging.getLogger().setLevel(logging.INFO)
            for handler in logging.getLogger().handlers:
                handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

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
        self.websocket = None # Represents the active WebSocket connection object
        self.ws_app = None # Compatibility with prompt, can be alias for self.websocket or removed if not used like websocket-client's WebSocketApp

        # For graceful shutdown
        self.shutdown_event = asyncio.Event()

        # Reconnection parameters
        self.MAX_RECONNECT_ATTEMPTS = 5  # Example value
        self.INITIAL_RECONNECT_DELAY = 5  # seconds
        self.MAX_RECONNECT_DELAY = 60 # seconds

        # Commands are defined here, mapping command string to handler method
        self.commands = {
            "create_group": self._handle_create_group_command,
            "help": self._send_help_message,
            # Future commands can be added here
        }

    def _request_shutdown(self):
        logging.info("Shutdown requested. Setting shutdown event.")
        self.shutdown_event.set()
        # Attempt to close the websocket connection if it's active
        # This needs to be done carefully if called from a signal handler in a different thread context
        # For asyncio, it's better to let the main loop handle the closure once shutdown_event is set.
        # If self.websocket is an instance of websockets.WebSocketClientProtocol,
        # scheduling its close() coroutine is the way.
        if self.websocket and self.websocket.open:
            logging.info("Requesting WebSocket close from _request_shutdown.")
            # Ensure close is scheduled as a task if called from a signal handler
            # that might not be in the same thread as the asyncio loop.
            # However, loop.add_signal_handler runs the callback in the loop's thread.
            asyncio.create_task(self.websocket.close())


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

    # Regex version of _parse_command_from_mention (old one should be fully deleted)
    def _parse_command_from_mention(self, message_text_after_mention):
        """
        Parses the command and arguments from the text following a bot mention.
        Returns: (command_verb, arg_string) or (None, None)
        """
        stripped_text = message_text_after_mention.strip()
        if not stripped_text: # Handles empty string or string with only spaces
            return None, None

        parts = stripped_text.split(maxsplit=1)
        command_verb = parts[0].lower()
        arg_string = parts[1] if len(parts) > 1 else None # arg_string will not have leading/trailing spaces from itself
        return command_verb, arg_string

    async def _send_help_message(self, channel_id, arg_string=None):
        """Displays this help message listing all available commands."""
        help_lines = ["### MartyBot Available Commands", "---"]
        if not self.commands:
            help_lines.append("No commands are currently available.")
        else:
            for cmd, handler_method in self.commands.items():
                docstring = handler_method.__doc__
                description = ""
                if docstring:
                    first_line = docstring.strip().split('\n')[0]
                    description = f" - _{first_line}_" # Italic for description
                help_lines.append(f"* **`{cmd}`**{description}")

        help_lines.append("\n---")
        help_lines.append(f"**Example:** `{self.bot_name_mention} create_group MyNewProject` - Creates resources for 'MyNewProject'.")
        help_lines.append(f"Mention me with a command, like `{self.bot_name_mention} help`.")

        help_text = "\n".join(help_lines)
        await asyncio.to_thread(self.envoyer_message, channel_id, help_text)

    async def _handle_create_group_command(self, channel_id, project_name_str):
        """Creates all necessary group resources for a new project."""
        if not project_name_str:
            message = f":warning: **Error:** Project name is required. Usage: `{self.bot_name_mention} create_group <projectName>`"
            await asyncio.to_thread(self.envoyer_message, channel_id, message)
            return

        project_name = project_name_str
        # Initial processing message
        processing_message = f":hourglass_flowing_sand: Processing 'create_group' for project: **`{project_name}`**..."
        await asyncio.to_thread(self.envoyer_message, channel_id, processing_message)

        results_summary = []
        attempted_ops = 0
        succeeded_ops = 0

        # Authentik
        auth_configured = bool(self.authentik_client)
        auth_success = False
        if auth_configured:
            attempted_ops += 1
            auth_success = self.authentik_client.create_group(project_name)
            if auth_success:
                succeeded_ops += 1
        results_summary.append(f"{':white_check_mark:' if auth_success else ':x:'} Authentik group creation {'succeeded' if auth_success else 'failed'}. (Client configured: {auth_configured})")

        # Outline
        outline_configured = bool(self.outline_client)
        outline_success = False
        if outline_configured:
            attempted_ops += 1
            outline_success = self.outline_client.create_group(project_name)
            if outline_success:
                succeeded_ops += 1
        results_summary.append(f"{':white_check_mark:' if outline_success else ':x:'} Outline collection creation {'succeeded' if outline_success else 'failed'}. (Client configured: {outline_configured})")

        # Mattermost
        mm_configured = bool(self.mattermost_api_client)
        mm_success = False
        if mm_configured:
            attempted_ops += 1
            mm_success = self.mattermost_api_client.create_channel(project_name)
            if mm_success:
                succeeded_ops += 1
        results_summary.append(f"{':white_check_mark:' if mm_success else ':x:'} Mattermost channel creation {'succeeded' if mm_success else 'failed'}. (Client configured: {mm_configured})")

        if attempted_ops == 0:
            final_header = f":information_source: No services configured for 'create_group' for project **`{project_name}`**. Please check bot configuration."
        elif succeeded_ops == attempted_ops:
            final_header = f":rocket: Successfully created all requested resources for project **`{project_name}`**!"
        elif succeeded_ops > 0:
            final_header = f":warning: Partially completed group creation for project **`{project_name}`**:"
        else: # succeeded_ops == 0 and attempted_ops > 0
            final_header = f":boom: Failed to create any requested resources for project **`{project_name}`**."

        final_response_message = f"{final_header}\n---\n" + "\n".join(results_summary)
        await asyncio.to_thread(self.envoyer_message, channel_id, final_response_message)

    async def _handle_message_event(self, message_data):
        post_info = message_data.get("data", {}).get("post")
        if not post_info:
            logging.warning("No post data in 'posted' event.")
            return

        post_data = json.loads(post_info)  # post is a JSON string
        message_text = post_data.get("message", "")
        channel_id = post_data.get("channel_id")
        # user_id = post_data.get("user_id") # TODO: Use to avoid self-reply if bot's own user_id is known

        # Use regex to check for mention and extract text after mention
        # The regex now expects the bot mention to be followed by a space or end of line.
        escaped_mention = re.escape(self.bot_name_mention)
        # (?i) for case-insensitive matching of the mention part in the message_text
        # (?:^|\s) ensures mention is at start or preceded by space (whole word)
        # \s+ ensures a space after mention if there's more text
        # (.*) captures the rest
        # |$ allows for just the mention with nothing after it
        mention_match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text)

        if not mention_match:
            return # Bot not mentioned correctly or at all

        # Text after the mention (could be empty string or None)
        text_after_mention = mention_match.group(1)

        command_verb, arg_string = self._parse_command_from_mention(text_after_mention if text_after_mention else "")

        if command_verb:
            handler_method = self.commands.get(command_verb)
            if handler_method:
                # Assuming handlers are async, if not, remove await
                await handler_method(channel_id, arg_string)
            else:
                message = f":question: Unknown command: **`{command_verb}`**. Try `{self.bot_name_mention} help` for a list of available commands."
                await asyncio.to_thread(self.envoyer_message, channel_id, message)
        elif text_after_mention is None or text_after_mention.strip() == "":
             message = f"Hi there! You mentioned me. Try `{self.bot_name_mention} help` for a list of commands."
             await asyncio.to_thread(self.envoyer_message, channel_id, message)
        # else: # This case should ideally not be reached if parsing is exhaustive
            # logging.debug(f"Text after mention '{text_after_mention}' resulted in no command_verb but was not empty.")
            # message = f"I'm not sure what you mean by '{text_after_mention}'. Try `{self.bot_name_mention} help`."
            # await asyncio.to_thread(self.envoyer_message, channel_id, message)
            # The generic "Hi! You mentioned me" is likely the best fallback if a command isn't parsed.
            # This complex conditional might need further simplification based on _parse_command_from_mention's exact return for "mention only"
            # Based on current _parse_command_from_mention, (None, None) is for no command text.
            # The original "Bonjour toi" for other commands is now an "Unknown command" or part of help.
            # Let's ensure the "Hi! You mentioned me." is the main fallback if no valid command is found after mention.
            # The current logic:
            # 1. If valid command_verb and handler -> call handler
            # 2. If valid command_verb but no handler -> unknown command
            # 3. If no command_verb (e.g. only mention, or unparseable as command) -> Hi! You mentioned me.
            # This seems reasonable.
            # The "Bonjour toi" for any other text after mention is removed in favor of specific commands or "Unknown command".
            # If we want a generic response to *any* text after mention that isn't a command:
            # elif text_after_mention is not None: # Bot was mentioned, and there was *some* text, but not a known command
            #    await asyncio.to_thread(self.envoyer_message, channel_id, "Bonjour toi ! How can I help you today?")

    async def on_message(self, ws, message_str):  # ws might not be needed if not directly used
        logging.debug(f"WebSocket << Raw incoming message: {message_str}")
        try:
            data = json.loads(message_str)  # Renamed for clarity from prompt
            logging.debug(
                f"WebSocket << Event received: Type='{data.get('event')}', Seq='{data.get('seq')}', DataKeys='{list(data.get('data', {}).keys()) if data.get('data') else None}'"
            )

            event_type = data.get("event")

            if event_type == "posted":
                # Specific log for "posted" event data
                logging.debug(f"WebSocket << 'posted' event 'data' field raw content: {data.get('data')}")
                await self._handle_message_event(data)  # Pass the parsed 'data'
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
            await asyncio.sleep(current_delay) # Use current_delay for backoff
            # else: # Shutdown event was set
            #      logging.info("WebSocket connection loop terminating due to shutdown request.")
            # Handled by the outer while not self.shutdown_event.is_set()

        logging.info("MartyBot WebSocket listener stopped.")
        if self.websocket and self.websocket.open:
            logging.info("Closing WebSocket connection finally...")
            try:
                await self.websocket.close()
                # Call on_close manually because the loop is exiting due to shutdown_event,
                # not necessarily a clean close from the server that would trigger the callback via the library.
                # However, if self.websocket.close() triggers the callback, this might be redundant.
                # For clarity, we can assume on_close is called by the library upon successful close.
                # await self.on_close(self.websocket, 1000, "Shutdown initiated")
            except Exception as e:
                logging.error(f"Error during final WebSocket close: {e}")


    def start(self):
        logging.info("Initializing Marty Bot instance...")

        # Check if critical clients were initialized in __init__
        # This is an additional check or can replace the one in _run_websocket_loop
        if not self.mattermost_api_client:  # Example critical client
            logging.error("Mattermost API client not initialized. MartyBot instance cannot fully operate.")
            # Depending on desired behavior, could prevent startup:
            # return

        logging.info("Starting WebSocket listener for MartyBot instance...")
        loop = asyncio.get_event_loop() # Get current event loop or create one if none
        if loop.is_closed(): # Handle case where a previous loop was closed (e.g. in tests or re-runs)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Add signal handlers for graceful shutdown
        # These will call _request_shutdown, which sets self.shutdown_event
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._request_shutdown)
        except NotImplementedError:
            # For Windows, signal handlers for SIGINT/SIGTERM might not work the same way.
            logging.warning("Signal handlers for graceful shutdown may not be fully supported on this OS (e.g., Windows).")

        try:
            loop.run_until_complete(self._run_websocket_loop())
        except KeyboardInterrupt: # Should be caught by signal handler now, but good fallback
            logging.info("KeyboardInterrupt received. Requesting shutdown...")
            self._request_shutdown()
            # Allow the loop to complete ongoing tasks if _run_websocket_loop respects shutdown_event
            loop.run_until_complete(self._run_websocket_loop()) # Will exit quickly if shutdown_event is set
        except Exception as e:
            logging.critical(f"WebSocket listener for MartyBot instance failed critically: {e}", exc_info=True)
        finally:
            logging.info("Cleaning up asyncio tasks and closing loop...")
            # Gather all remaining tasks and cancel them (except the current one)
            # This is more relevant if _run_websocket_loop created detached tasks.
            # tasks = [t for t in asyncio.all_tasks(loop=loop) if t is not asyncio.current_task(loop=loop)]
            # if tasks:
            #     logging.info(f"Cancelling {len(tasks)} outstanding tasks.")
            #     for task in tasks:
            #         task.cancel()
            #     loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

            if not loop.is_closed():
                 # Run pending tasks to completion (e.g. cleanup from cancelled tasks)
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            logging.info("Asyncio loop closed.")


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
