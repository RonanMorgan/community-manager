import websockets

print("<<<<<<<<<< SCRIPT EXECUTED >>>>>>>>>>")
import json
import re  # Import re for regular expressions
import os  # IMPORT MANQUANT !

# import threading # No longer used
import requests

# import os # No longer used
import asyncio
import logging
import markdown2  # For send_email Markdown to HTML conversion

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
from clients.nocodb_client import NocoDBClient
from clients.vaultwarden_client import VaultwardenClient
from clients.client_factory import create_clients
# Import orchestration function for sync command
from libraries.group_sync_services import orchestrate_group_synchronization
from app.commands.command_factory import CommandFactory
from app.result_manager import ResultManager


class MartyBot:
    def __init__(self, config_obj):
        self.config = config_obj

        # Ensure logging is configured based on the instance's config for future logs from this instance
        log_format = "%(asctime)s - %(levelname)s - %(message)s"
        log_level = logging.INFO
        if self.config.DEBUG:
            log_level = logging.DEBUG
            log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

        # Get root logger and set its level. Remove existing handlers before adding new one.
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        logging.basicConfig(level=log_level, format=log_format)

        if self.config.DEBUG:
            logging.debug("DEBUG mode is enabled for MartyBot instance. Verbose logging active.")

        self.bot_name_mention = f"@{self.config.BOT_NAME.lower()}" if self.config.BOT_NAME else ""

        clients = create_clients()
        self.authentik_client = clients.get("authentik")
        self.outline_client = clients.get("outline")
        self.mattermost_api_client = clients.get("mattermost")
        self.brevo_client = clients.get("brevo")
        self.nocodb_client = clients.get("nocodb")
        self.vaultwarden_client = clients.get("vaultwarden")

        self.websocket = None

        # For graceful shutdown
        self.shutdown_event = asyncio.Event()

        # Reconnection parameters
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.INITIAL_RECONNECT_DELAY = 5
        self.MAX_RECONNECT_DELAY = 60

        self.command_factory = CommandFactory(self)
        self.result_manager = ResultManager(self)
        self.orchestrate_group_synchronization = orchestrate_group_synchronization


    # _handle_create_projet_command, _handle_create_antenne_command, _handle_create_pole_command
    # are now simplified by the lambdas in self.commands, directly calling _execute_batch_create_command.
    # They can be removed if no other specific logic is needed for them.
    # For now, I will keep them commented out in case they are needed for more specific logic later.
    # async def _handle_create_projet_command(self, channel_id, arg_string, user_id_who_posted=None):
    #     """Crée les ressources pour un ou plusieurs projets. Usage: create_projet <NomProjet1> [NomProjet2 ...]"""
    #     await self._execute_batch_create_command(
    #         channel_id, arg_string, "projet", "PROJET", user_id_who_posted
    #     )
    # async def _handle_create_antenne_command(self, channel_id, arg_string, user_id_who_posted=None):
    #     """Crée les ressources pour une ou plusieurs antennes. Usage: create_antenne <NomAntenne1> [NomAntenne2 ...]"""
    #     await self._execute_batch_create_command(
    #         channel_id, arg_string, "antenne", "ANTENNE", user_id_who_posted
    #     )
    # async def _handle_create_pole_command(self, channel_id, arg_string, user_id_who_posted=None):
    #     """Crée les ressources pour un ou plusieurs pôles. Usage: create_pole <NomPole1> [NomPole2 ...]"""
    #     await self._execute_batch_create_command(
    #         channel_id, arg_string, "pôle", "POLES", user_id_who_posted
    #     )

    def _request_shutdown(self):
        logging.info("Shutdown requested. Setting shutdown event.")
        self.shutdown_event.set()
        if self.websocket and self.websocket.open:
            logging.info("Requesting WebSocket close from _request_shutdown (scheduling task).")
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

    async def _handle_message_event(self, message_data):
        post_info = message_data.get("data", {}).get("post")
        if not post_info:
            logging.warning("No post data in 'posted' event.")
            return
        post_data = json.loads(post_info)
        message_text = post_data.get("message", "")
        channel_id = post_data.get("channel_id")
        user_id_who_posted = post_data.get("user_id")  # Get user_id here

        escaped_mention = re.escape(self.bot_name_mention)
        # Add re.DOTALL to make . match newline characters
        mention_match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text, re.DOTALL)

        if not mention_match:
            return
        text_after_mention = mention_match.group(1)
        command_verb, arg_string = self._parse_command_from_mention(text_after_mention if text_after_mention else "")

        if command_verb:
            command = self.command_factory.get_command(command_verb)
            if command:
                await command.execute(channel_id, arg_string, user_id_who_posted)
            else:
                message = f":question: Commande inconnue : **`{command_verb}`**. Essayez `{self.bot_name_mention} help` pour une liste des commandes disponibles."
                await asyncio.to_thread(self.envoyer_message, channel_id, message)
        elif text_after_mention is None or text_after_mention.strip() == "":
            message = f"Bonjour ! Vous m'avez mentionné. Essayez `{self.bot_name_mention} help` pour une liste des commandes."
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
            logging.warning("One or more API clients are not initialized. Bot may have limited functionality.")

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
                    ping_interval=60,
                    ping_timeout=30,
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
