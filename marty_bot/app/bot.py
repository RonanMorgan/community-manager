import websockets
import json
import re  # Import re for regular expressions

# import threading # No longer used
import requests

# import os # No longer used
import asyncio
import logging

# import signal  # No longer used directly in MartyBot class after removing signal handlers
import threading  # For logging current thread name in start()

from app import config

# Configure basic logging based on DEBUG status
# This initial basicConfig is for any logging before MartyBot instance is created
# or if MartyBot's specific config isn't applied globally.
# MartyBot's __init__ will refine this for its instance.
if config.DEBUG:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )
    logging.debug("Initial DEBUG mode is enabled. Global verbose logging active.")
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# Import client classes
from clients.authentik_client import AuthentikClient
from clients.outline_client import OutlineClient
from clients.mattermost_client import MattermostClient

# Import orchestration function for sync command
from libraries.group_sync_services import orchestrate_authentik_mattermost_sync


class MartyBot:
    def __init__(self, config_obj):
        self.config = config_obj

        # Ensure logging is configured based on the instance's config for future logs from this instance
        # This will apply to loggers obtained after this point if they inherit from root.
        log_format = "%(asctime)s - %(levelname)s - %(message)s"
        log_level = logging.INFO
        if self.config.DEBUG:
            log_level = logging.DEBUG
            log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

        # Get root logger and set its level. Remove existing handlers before adding new one.
        # This is to avoid duplicate log messages if basicConfig was called before.
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:  # Iterate over a copy
            root_logger.removeHandler(handler)
        logging.basicConfig(level=log_level, format=log_format)  # Re-apply basicConfig with new settings

        if self.config.DEBUG:
            logging.debug("DEBUG mode is enabled for MartyBot instance. Verbose logging active.")

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

        self.websocket = None  # Represents the active WebSocket connection object

        # For graceful shutdown
        self.shutdown_event = asyncio.Event()

        # Reconnection parameters
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.INITIAL_RECONNECT_DELAY = 5  # seconds
        self.MAX_RECONNECT_DELAY = 60  # seconds

        self.commands = {
            "create_group": self._handle_create_group_command,
            "help": self._send_help_message,
            "sync_user_channels": self._handle_sync_user_channels_command,  # New command
        }

    async def _handle_sync_user_channels_command(self, channel_id, arg_string=None):  # arg_string is unused for now
        """Triggers the synchronization of Mattermost channel users to Authentik groups."""
        logging.info(f"'{self.bot_name_mention} sync_user_channels' command received in channel {channel_id}.")

        # Send initial acknowledgement message and get its ID for threading
        initial_message_text = ":hourglass_flowing_sand: Starting synchronization of Mattermost channel users to Authentik groups... This may take a while."
        # Using asyncio.to_thread for the synchronous envoyer_message
        initial_post_id = await asyncio.to_thread(self.envoyer_message, channel_id, initial_message_text)

        # Check if necessary clients and config are available on the bot instance
        if not self.authentik_client or not self.mattermost_api_client or not self.config.MATTERMOST_TEAM_ID:
            error_msg = ":warning: **Error:** Bot is not properly configured to perform synchronization. Missing Authentik client, Mattermost API client, or Mattermost Team ID. Please check server logs."
            logging.error(
                "Bot is not properly configured for sync: Missing Authentik client, Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(
                self.envoyer_message, channel_id, error_msg, thread_id=initial_post_id  # Reply in thread if possible
            )
            return

        try:
            # Run the synchronous orchestration function in a separate thread
            logging.info("Dispatching synchronization task to a thread...")
            orchestration_success, detailed_results = await asyncio.to_thread(
                orchestrate_authentik_mattermost_sync,
                self.authentik_client,
                self.mattermost_api_client,
                self.config.MATTERMOST_TEAM_ID,
            )

            final_summary_message = ""

            if not orchestration_success:
                logging.warning("Synchronization task reported critical failure during orchestration.")
                final_summary_message = ":x: Synchronization of Mattermost channel users to Authentik groups failed critically during orchestration. Please check server logs for details."
            else:
                logging.info(
                    f"Synchronization task orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                if not detailed_results:
                    final_summary_message = ":information_source: Synchronization process completed, but no specific user operations were performed or reported. This could mean no groups were found, no channels matched, or no users were in the relevant channels."
                else:
                    # Process detailed_results and send messages
                    success_count = 0
                    failure_count = 0
                    for result in detailed_results:
                        user_mm_name = result.get("mm_username", "Unknown User")
                        auth_group = result.get("auth_group_name", "Unknown Group")
                        mm_channel_name = result.get("mm_channel_display_name", "Unknown Channel")  # noqa E501
                        action = result.get("action", "NO_ACTION")
                        status = result.get("status", "FAILURE")
                        error_msg = result.get("error_message")

                        icon = ":white_check_mark:" if status == "SUCCESS" else ":x:"
                        user_message = f"{icon} **User:** `{user_mm_name}`"
                        if result.get("mm_user_email"):
                            user_message += f" ({result.get('mm_user_email')})"  # noqa E501

                        if action == "ADDED_TO_AUTHENTIK_GROUP":
                            message_detail = f" successfully added to Authentik group `{auth_group}` (from MM channel `{mm_channel_name}`)."
                            success_count += 1
                        elif action == "ALREADY_IN_AUTHENTIK_GROUP":
                            message_detail = f" already in Authentik group `{auth_group}`."
                            success_count += 1  # Still a success in terms of state
                        elif action == "FAILED_TO_ADD_TO_AUTHENTIK_GROUP":
                            message_detail = (
                                f" FAILED to be added to Authentik group `{auth_group}`. Reason: {error_msg}"
                            )
                            failure_count += 1
                        elif action == "SKIPPED_NO_MM_EMAIL":
                            message_detail = f" skipped for Authentik group `{auth_group}` (MM channel `{mm_channel_name}`) - User has no email in Mattermost."
                            # This is not a failure of the sync process itself, but a data issue.
                        elif action == "SKIPPED_MM_USER_NOT_IN_AUTHENTIK":
                            message_detail = f" skipped for Authentik group `{auth_group}` (MM channel `{mm_channel_name}`) - User email not found in Authentik."
                            # Also a data issue.
                        else:  # SKIPPED_AUTHENTIK_GROUP_UNCHANGED or other new/default cases
                            message_detail = f" processed for Authentik group `{auth_group}`. Action: `{action}`. Status: `{status}`."
                            if status != "SUCCESS":
                                failure_count += 1
                            else:
                                success_count += 1

                        full_user_report_message = f"{user_message}{message_detail}"
                        await asyncio.to_thread(
                            self.envoyer_message, channel_id, full_user_report_message, thread_id=initial_post_id
                        )

                    if failure_count > 0 and success_count > 0:
                        final_summary_message = f":warning: Synchronization partially completed. {success_count} successful operations, {failure_count} failures/issues. See details above."
                    elif failure_count > 0:
                        final_summary_message = (
                            f":x: Synchronization completed with {failure_count} failures/issues. See details above."
                        )
                    elif success_count > 0:
                        final_summary_message = f":rocket: Synchronization completed successfully with {success_count} operations. See details above."
                    else:  # Should be covered by the "no specific user operations" if detailed_results was not empty but all were skips
                        final_summary_message = ":white_check_mark: Synchronization process completed. No direct user additions or failures to report, check details for skips or existing memberships."

            # Send the final summary message
            if final_summary_message:
                await asyncio.to_thread(
                    self.envoyer_message, channel_id, final_summary_message, thread_id=initial_post_id
                )

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the sync task: {e}", exc_info=True
            )
            error_response_msg = ":boom: An unexpected server error occurred while trying to run the synchronization. Please check server logs."
            await asyncio.to_thread(self.envoyer_message, channel_id, error_response_msg, thread_id=initial_post_id)

    def _request_shutdown(self):
        logging.info("Shutdown requested. Setting shutdown event.")
        self.shutdown_event.set()
        if self.websocket and self.websocket.open:
            logging.info("Requesting WebSocket close from _request_shutdown (scheduling task).")
            # loop.call_soon_threadsafe might be needed if signal handler is not in loop's thread
            # but loop.add_signal_handler usually runs callback in loop's thread.
            asyncio.create_task(self.websocket.close(code=1000, reason="Bot shutdown"))

    def envoyer_message(self, channel_id, message_text, thread_id=None) -> str | None:
        """
        Sends a message to the specified Mattermost channel.
        Returns the post ID of the sent message if successful, None otherwise.
        """
        if not self.config.BOT_TOKEN or not self.config.MATTERMOST_URL:
            logging.error("BOT_TOKEN or MATTERMOST_URL not configured for bot instance. Cannot send message.")
            return None

        headers = {
            "Authorization": f"Bearer {self.config.BOT_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "channel_id": channel_id,
            "message": message_text,
        }
        if thread_id:
            payload["root_id"] = thread_id

        post_url = f"{self.config.MATTERMOST_URL.rstrip('/')}/api/v4/posts"
        logging.debug(
            f"Mattermost API >> Sending message to channel {channel_id} (thread: {thread_id}). Payload: {json.dumps(payload)}"
        )
        log_message = f"Sending message to {post_url} in channel {channel_id}: {message_text[:100]}..."
        logging.info(log_message)
        try:
            response = requests.post(post_url, headers=headers, json=payload)
            response.raise_for_status()
            post_data = response.json()
            post_id = post_data.get("id")
            if post_id:
                logging.info(f"Message sent successfully to channel {channel_id}. Post ID: {post_id}")
                return post_id
            else:
                logging.error(
                    f"Message sent to channel {channel_id} but no post ID was returned in response: {post_data}"
                )
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending message to Mattermost: {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response from Mattermost after sending message: {e}")
            return None

    def _parse_command_from_mention(self, message_text_after_mention):
        stripped_text = message_text_after_mention.strip()
        if not stripped_text:
            return None, None

        parts = stripped_text.split(maxsplit=1)
        command_verb = parts[0].lower()
        arg_string = parts[1] if len(parts) > 1 else None
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
                    first_line = docstring.strip().split("\n")[0]
                    description = f" - _{first_line}_"
                help_lines.append(f"* **`{cmd}`**{description}")
        help_lines.append("\n---")
        help_lines.append(
            f"**Example:** `{self.bot_name_mention} create_group MyNewProject` - Creates resources for 'MyNewProject'."
        )
        help_lines.append(
            f"\n**Note:** The `{self.bot_name_mention} sync_user_channels` command may take some time to complete."
        )
        help_lines.append(f"\nMention me with a command, like `{self.bot_name_mention} help`.")
        help_text = "\n".join(help_lines)
        await asyncio.to_thread(self.envoyer_message, channel_id, help_text)

    async def _handle_create_group_command(self, channel_id, project_name_str):
        """Creates all necessary group resources for a new project."""
        if not project_name_str:
            message = f":warning: **Error:** Project name is required. Usage: `{self.bot_name_mention} create_group <projectName>`"
            await asyncio.to_thread(self.envoyer_message, channel_id, message)
            return

        project_name = project_name_str
        processing_message = f":hourglass_flowing_sand: Processing 'create_group' for project: **`{project_name}`**..."
        await asyncio.to_thread(self.envoyer_message, channel_id, processing_message)

        results_summary = []
        attempted_ops = 0
        succeeded_ops = 0

        auth_configured = bool(self.authentik_client)
        auth_success = False
        if auth_configured:
            attempted_ops += 1
            auth_success = self.authentik_client.create_group(project_name)
            if auth_success:
                succeeded_ops += 1
        results_summary.append(
            f"{':white_check_mark:' if auth_success else ':x:'} Authentik group creation {'succeeded' if auth_success else 'failed'}. (Client configured: {auth_configured})"
        )

        outline_configured = bool(self.outline_client)
        outline_success = False
        if outline_configured:
            attempted_ops += 1
            outline_success = self.outline_client.create_group(project_name)
            if outline_success:
                succeeded_ops += 1
        results_summary.append(
            f"{':white_check_mark:' if outline_success else ':x:'} Outline collection creation {'succeeded' if outline_success else 'failed'}. (Client configured: {outline_configured})"
        )

        mm_configured = bool(self.mattermost_api_client)
        mm_success = False
        if mm_configured:
            attempted_ops += 1
            mm_success = self.mattermost_api_client.create_channel(project_name)
            if mm_success:
                succeeded_ops += 1
        results_summary.append(
            f"{':white_check_mark:' if mm_success else ':x:'} Mattermost channel creation {'succeeded' if mm_success else 'failed'}. (Client configured: {mm_configured})"
        )

        if attempted_ops == 0:
            final_header = f":information_source: No services configured for 'create_group' for project **`{project_name}`**. Please check bot configuration."
        elif succeeded_ops == attempted_ops:
            final_header = f":rocket: Successfully created all requested resources for project **`{project_name}`**!"
        elif succeeded_ops > 0:
            final_header = f":warning: Partially completed group creation for project **`{project_name}`**:"
        else:
            final_header = f":boom: Failed to create any requested resources for project **`{project_name}`**."

        final_response_message = f"{final_header}\n---\n" + "\n".join(results_summary)
        await asyncio.to_thread(self.envoyer_message, channel_id, final_response_message)

    async def _handle_message_event(self, message_data):
        post_info = message_data.get("data", {}).get("post")
        if not post_info:
            logging.warning("No post data in 'posted' event.")
            return
        post_data = json.loads(post_info)
        message_text = post_data.get("message", "")
        channel_id = post_data.get("channel_id")

        escaped_mention = re.escape(self.bot_name_mention)
        mention_match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text)

        if not mention_match:
            return
        text_after_mention = mention_match.group(1)
        command_verb, arg_string = self._parse_command_from_mention(text_after_mention if text_after_mention else "")

        if command_verb:
            handler_method = self.commands.get(command_verb)
            if handler_method:
                await handler_method(channel_id, arg_string)
            else:
                message = f":question: Unknown command: **`{command_verb}`**. Try `{self.bot_name_mention} help` for a list of available commands."
                await asyncio.to_thread(self.envoyer_message, channel_id, message)
        elif text_after_mention is None or text_after_mention.strip() == "":
            message = f"Hi there! You mentioned me. Try `{self.bot_name_mention} help` for a list of commands."
            await asyncio.to_thread(self.envoyer_message, channel_id, message)

    async def on_message(self, ws, message_str):
        logging.debug(f"WebSocket << Raw incoming message: {message_str}")
        try:
            data = json.loads(message_str)
            logging.debug(
                f"WebSocket << Event received: Type='{data.get('event')}', Seq='{data.get('seq')}', DataKeys='{list(data.get('data', {}).keys()) if data.get('data') else None}'"
            )
            event_type = data.get("event")

            if event_type == "posted":
                logging.debug(f"WebSocket << 'posted' event 'data' field raw content: {data.get('data')}")
                await self._handle_message_event(data)
            elif event_type == "hello":
                logging.info(f"WebSocket << Received 'hello' event: {data}")
            elif event_type:
                logging.debug(f"WebSocket << Received unhandled event type '{event_type}': {data}")
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON message: {message_str}")
        except Exception as e:
            logging.error(f"Error in on_message: {e}. Original message: {message_str}", exc_info=True)

    async def on_error(self, ws, error):
        logging.error(f"WebSocket Error: {error}")

    async def on_close(self, ws, close_status_code, close_msg):
        logging.info(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")

    async def on_open(self, ws):
        logging.info("WebSocket connection opened.")
        if not self.config.BOT_TOKEN:
            logging.error("BOT_TOKEN not configured for bot instance. Cannot send authentication challenge.")
            await ws.close()
            return
        auth_data = {"seq": 1, "action": "authentication_challenge", "data": {"token": self.config.BOT_TOKEN}}
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
            logging.warning(
                "One or more API clients are not initialized. Bot may have limited functionality."
            )  # Changed to warning

        websocket_url = f"{self.config.MATTERMOST_URL.replace('http', 'ws', 1).rstrip('/')}/api/v4/websocket"
        reconnect_attempts = 0
        current_delay = self.INITIAL_RECONNECT_DELAY

        while not self.shutdown_event.is_set():
            try:
                logging.info(
                    f"Attempting to connect to WebSocket: {websocket_url} (Attempt: {reconnect_attempts + 1})"
                )
                async with websockets.connect(
                    websocket_url,
                    ping_interval=60,  # From user's working example
                    ping_timeout=30,  # From user's working example
                    # extra_headers argument removed
                ) as self.websocket:
                    logging.info(f"Successfully connected to WebSocket: {websocket_url}")
                    await self.on_open(self.websocket)
                    reconnect_attempts = 0
                    current_delay = self.INITIAL_RECONNECT_DELAY
                    while not self.shutdown_event.is_set():
                        try:
                            message_str = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                            if message_str:
                                await self.on_message(self.websocket, message_str)
                        except asyncio.TimeoutError:
                            if self.shutdown_event.is_set():
                                logging.debug("Shutdown event set during recv timeout, breaking inner loop.")
                                break
                            continue
                        except websockets.exceptions.ConnectionClosedOK as e:
                            logging.info(f"WebSocket connection closed normally by server (ClosedOK): {e}")
                            await self.on_close(self.websocket, e.code, e.reason)
                            break
                        except websockets.exceptions.ConnectionClosedError as e:
                            logging.warning(
                                f"WebSocket connection closed with error: {e}. Code: {e.code}, Reason: {e.reason}"
                            )
                            await self.on_close(self.websocket, e.code, e.reason)
                            break
                        except Exception as e:
                            logging.error(f"Error during WebSocket recv: {e}", exc_info=True)
                            await self.on_error(self.websocket, e)
                            break
                if self.shutdown_event.is_set():
                    logging.info("Shutdown event set, breaking outer connection loop.")
                    break
            except (
                websockets.exceptions.InvalidURI,
                websockets.exceptions.InvalidHandshake,
                ConnectionRefusedError,
                OSError,
            ) as e:
                logging.error(f"Failed to connect to WebSocket: {e}")
            except Exception as e:
                logging.error(f"Unexpected error during WebSocket connection attempt: {e}", exc_info=True)

            if not self.shutdown_event.is_set():
                reconnect_attempts += 1
                if reconnect_attempts >= self.MAX_RECONNECT_ATTEMPTS:
                    logging.error(f"Exceeded max reconnect attempts ({self.MAX_RECONNECT_ATTEMPTS}). Stopping bot.")
                    self.shutdown_event.set()
                    break
                logging.info(f"Reconnecting in {current_delay} seconds...")
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=current_delay)
                    if self.shutdown_event.is_set():
                        logging.info("Shutdown initiated during reconnect delay.")
                        break
                except asyncio.TimeoutError:
                    pass
                current_delay = min(current_delay * 2, self.MAX_RECONNECT_DELAY)

        logging.info("MartyBot WebSocket listener stopped.")
        if self.websocket and self.websocket.open:
            logging.info("Closing WebSocket connection finally (if still open)...")
            try:
                await self.websocket.close(code=1000, reason="Bot shutting down")
            except Exception as e:
                logging.error(f"Error during final WebSocket close: {e}")

    def start(self):
        logging.info(f"Initializing Marty Bot instance for dedicated thread: {threading.current_thread().name}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logging.info(f"New asyncio event loop created and set for thread {threading.current_thread().name}")

        try:
            # Signal handlers removed as per subtask requirement
            # for sig in (signal.SIGINT, signal.SIGTERM):
            #     try:
            #         loop.add_signal_handler(sig, self._request_shutdown)
            #         logging.info(f"Signal handler for {sig.name} set.")
            #     except NotImplementedError:
            #         logging.warning(f"Signal handler for {sig.name} could not be set on this OS/loop policy (NotImplementedError).")
            #     except Exception as e:
            #         logging.error(f"Error setting signal handler for {sig.name}: {e}")

            logging.info(
                f"Starting WebSocket listener for MartyBot instance in thread {threading.current_thread().name}..."
            )
            loop.run_until_complete(self._run_websocket_loop())
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt caught in start(), requesting shutdown.")
            if not self.shutdown_event.is_set():
                self._request_shutdown()
        finally:
            logging.info(f"Cleaning up asyncio event loop in thread {threading.current_thread().name}.")
            try:
                all_tasks = asyncio.all_tasks(loop=loop)
                current_task = None
                if loop.is_running():
                    current_task = asyncio.current_task(loop=loop)
                tasks_to_cancel = [t for t in all_tasks if t is not current_task]
                if tasks_to_cancel:
                    logging.debug(f"Cancelling {len(tasks_to_cancel)} outstanding tasks.")
                    for task in tasks_to_cancel:
                        task.cancel()
                    loop.run_until_complete(asyncio.gather(*tasks_to_cancel, return_exceptions=True))
                    logging.debug("Outstanding tasks gathered after cancellation.")
                if hasattr(loop, "shutdown_asyncgens"):
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    logging.debug("Async generators shut down.")
            except RuntimeError as e:
                logging.warning(f"RuntimeError during task cleanup (likely loop already stopped): {e}")
            except Exception as e:
                logging.error(f"Error during task cleanup: {e}", exc_info=True)
            finally:
                if hasattr(loop, "shutdown_default_executor"):
                    try:
                        loop.run_until_complete(loop.shutdown_default_executor())
                        logging.debug("Default executor shut down.")
                    except Exception as e:
                        logging.error(f"Error shutting down default executor: {e}", exc_info=True)
                if not loop.is_closed():
                    loop.close()
                    logging.info(f"Asyncio event loop closed for thread {threading.current_thread().name}.")
                else:
                    logging.info(
                        f"Asyncio event loop was already closed for thread {threading.current_thread().name}."
                    )


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
        marty_bot_instance = MartyBot(config)
        marty_bot_instance.start()
