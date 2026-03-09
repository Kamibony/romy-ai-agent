import asyncio
import websockets
import json
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class ExtensionServer:
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.active_connection: Optional[websockets.WebSocketServerProtocol] = None
        self.loop = asyncio.new_event_loop()
        self.server_task = None
        self._pending_scan_result = None
        self._scan_event = None
        self._action_result = None
        self._action_event = None

    async def _handler(self, websocket: websockets.WebSocketServerProtocol, path: str):
        logger.info(f"Chrome Extension connected from {websocket.remote_address}")
        # Only allow one active connection for simplicity (the active tab)
        if self.active_connection:
            try:
                await self.active_connection.close()
            except Exception:
                pass

        self.active_connection = websocket

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "SCAN_RESULT":
                        self._pending_scan_result = data.get("ui_elements", [])
                        self._scan_event.set()
                    elif msg_type == "ACTION_RESULT":
                        self._action_result = data
                        self._action_event.set()
                    else:
                        logger.warning(f"Unknown message type from extension: {msg_type}")
                except json.JSONDecodeError:
                    logger.error("Failed to decode message from extension")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Chrome Extension disconnected")
        finally:
            if self.active_connection == websocket:
                self.active_connection = None

    async def _start_server(self):
        self._scan_event = asyncio.Event()
        self._action_event = asyncio.Event()
        async with websockets.serve(self._handler, self.host, self.port):
            logger.info(f"Extension WebSocket server listening on ws://{self.host}:{self.port}")
            await asyncio.Future()  # run forever

    def run_server(self):
        """Runs the WebSocket server in its own asyncio loop. To be called in a daemon thread."""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._start_server())
        except Exception as e:
            logger.error(f"Error running extension server: {e}")

    def is_connected(self) -> bool:
        """Returns True if a client is connected and open."""
        return self.active_connection is not None and self.active_connection.open

    async def _send_and_wait(self, payload: dict, event: asyncio.Event, timeout: float = 3.0) -> Any:
        if not self.is_connected():
            return None

        event.clear()
        try:
            await self.active_connection.send(json.dumps(payload))
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response to {payload.get('action')}")
            return None
        except Exception as e:
            logger.error(f"Error sending message to extension: {e}")
            return None

    def scan_dom(self, timeout: float = 3.0) -> Optional[list[Dict[str, Any]]]:
        """Requests a DOM scan from the extension and waits for the result."""
        if not self.is_connected():
            return None

        async def do_scan():
            result = await self._send_and_wait({"action": "SCAN"}, self._scan_event, timeout)
            if result:
                return self._pending_scan_result
            return None

        # Run the coroutine in the server's thread loop and wait for it
        future = asyncio.run_coroutine_threadsafe(do_scan(), self.loop)
        try:
            return future.result(timeout=timeout + 1.0)
        except Exception as e:
            logger.error(f"Failed to scan DOM via extension: {e}")
            return None

    def execute_click(self, target_id: str, timeout: float = 3.0) -> bool:
        if not self.is_connected():
            return False

        async def do_click():
            result = await self._send_and_wait({"action": "CLICK", "target_id": target_id}, self._action_event, timeout)
            if result and self._action_result:
                return self._action_result.get("status") == "success"
            return False

        future = asyncio.run_coroutine_threadsafe(do_click(), self.loop)
        try:
            return future.result(timeout=timeout + 1.0)
        except Exception:
            return False

    def execute_type(self, target_id: str, text: str, timeout: float = 3.0) -> bool:
        if not self.is_connected():
            return False

        async def do_type():
            result = await self._send_and_wait({"action": "TYPE", "target_id": target_id, "text": text}, self._action_event, timeout)
            if result and self._action_result:
                return self._action_result.get("status") == "success"
            return False

        future = asyncio.run_coroutine_threadsafe(do_type(), self.loop)
        try:
            return future.result(timeout=timeout + 1.0)
        except Exception:
            return False

    def execute_scroll(self, direction: str, timeout: float = 3.0) -> bool:
        if not self.is_connected():
            return False

        async def do_scroll():
            result = await self._send_and_wait({"action": "SCROLL", "direction": direction}, self._action_event, timeout)
            if result and self._action_result:
                return self._action_result.get("status") == "success"
            return False

        future = asyncio.run_coroutine_threadsafe(do_scroll(), self.loop)
        try:
            return future.result(timeout=timeout + 1.0)
        except Exception:
            return False

# Global instance
extension_server = ExtensionServer()
