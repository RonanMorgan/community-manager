import asyncio
import json
import logging

import websockets


class WebsocketHandler:
    def __init__(self, bot):
        self.bot = bot
        self.websocket = None
        self.shutdown_event = asyncio.Event()
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.INITIAL_RECONNECT_DELAY = 5
        self.MAX_RECONNECT_DELAY = 60

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
                await self.bot._handle_message_event(data)
            elif event_type == "hello":
                logging.info(f"WebSocket << Received 'hello' event: {data}")
            elif event_type:
                logging.debug(f"WebSocket << Received unhandled event type '{event_type}': {data}")
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON message: {message_str}")
        except Exception as e:
            logging.error(
                f"Error in on_message: {e}. Original message: {message_str}",
                exc_info=True,
            )

    async def on_error(self, ws, error):
        logging.error(f"WebSocket Error: {error}")

    async def on_close(self, ws, close_status_code, close_msg):
        logging.info(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")

    async def on_open(self, ws):
        logging.info("WebSocket connection opened.")
        if not self.bot.config.BOT_TOKEN:
            logging.error("BOT_TOKEN not configured for bot instance. Cannot send authentication challenge.")
            await ws.close()
            return
        auth_data = {
            "seq": 1,
            "action": "authentication_challenge",
            "data": {"token": self.bot.config.BOT_TOKEN},
        }
        try:
            await ws.send(json.dumps(auth_data))
            logging.info(
                f"Sent authentication challenge for bot token starting with: {str(self.bot.config.BOT_TOKEN)[:4]}..."
            )
        except Exception as e:
            logging.error(f"Error sending authentication challenge: {e}")

    async def run(self):
        if not self.bot.config.MATTERMOST_URL or not self.bot.config.BOT_TOKEN:
            logging.error("Mattermost URL or Bot Token not configured for bot instance. Cannot start WebSocket.")
            return

        websocket_url = f"{self.bot.config.MATTERMOST_URL.replace('http', 'ws', 1).rstrip('/')}/api/v4/websocket"
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
                logging.error(
                    f"Unexpected error during WebSocket connection attempt: {e}",
                    exc_info=True,
                )

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

    def stop(self):
        logging.info("Shutdown requested. Setting shutdown event.")
        self.shutdown_event.set()
        if self.websocket and self.websocket.open:
            logging.info("Requesting WebSocket close from _request_shutdown (scheduling task).")
            asyncio.create_task(self.websocket.close(code=1000, reason="Bot shutdown"))
