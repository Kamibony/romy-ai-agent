import asyncio
import json
import logging
import threading
import time
import websockets

class LocalBridgeManager:
    def __init__(self, port=8765):
        self.port = port
        self.active_websocket = None
        self.pending_command = None
        self.result = None
        self.server_thread = None
        self.loop = None
        self.server = None

        # Synchronization
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.result_event = threading.Event()

    async def _handle_client(self, websocket):
        logging.info(f"WebSocket client connected from {websocket.remote_address}")

        old_websocket = None
        with self.lock:
            # We only support one active Chrome Extension connection at a time
            # If a new one connects, cleanly terminate the old one without blocking
            if self.active_websocket and self.active_websocket != websocket:
                logging.warning("New WebSocket connection replacing existing active connection.")
                old_websocket = self.active_websocket
            self.active_websocket = websocket

        if old_websocket:
            try:
                await old_websocket.close()
            except Exception as e:
                logging.warning(f"Error closing stale WebSocket connection: {e}")

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if 'type' in data and data['type'] == 'result':
                        self.receive_result(data.get('payload', {}))
                    elif 'type' in data and data['type'] == 'telemetry':
                        logging.info(f"Extension Telemetry: {data.get('payload')}")
                    else:
                        logging.warning(f"Unknown WebSocket message received: {data}")
                except json.JSONDecodeError:
                    logging.error(f"Failed to decode WebSocket message: {message}")
        except websockets.exceptions.ConnectionClosed:
            logging.info(f"WebSocket client disconnected: {websocket.remote_address}")
        except Exception as e:
            logging.error(f"WebSocket handling error: {e}")
        finally:
            with self.lock:
                if self.active_websocket == websocket:
                    self.active_websocket = None

    async def _run_server(self):
        self.loop = asyncio.get_running_loop()
        self.server = await websockets.serve(self._handle_client, '127.0.0.1', self.port)
        self.stop_event = asyncio.Event()
        logging.info(f"WebSocket local bridge server started on ws://127.0.0.1:{self.port}")

        try:
            await self.stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            self.server.close()
            await self.server.wait_closed()
            logging.info("WebSocket local bridge server stopped.")

    def _start_loop(self):
        try:
            asyncio.run(self._run_server())
        except Exception as e:
            logging.error(f"WebSocket server thread exception: {e}")

    def start(self):
        if self.server_thread is not None and self.server_thread.is_alive():
            return

        self.server_thread = threading.Thread(target=self._start_loop, daemon=True)
        self.server_thread.start()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.stop_event.set)

        if self.server_thread:
            self.server_thread.join(timeout=2)

    def delegate_command(self, payload: dict, timeout=300):
        # Import inside the method to avoid circular imports if any
        import agent

        with self.lock:
            if not self.active_websocket:
                logging.error("No active WebSocket connection from Chrome Extension.")
                return {"success": False, "error": "Chrome Extension is not connected to the local bridge."}

        # Clear previous result
        self.result_event.clear()
        self.result = None

        logging.info(f"Delegating command to Chrome Extension: {payload.get('commandText', '')[:50]}")

        # We need to send the message from the asyncio loop thread
        async def send_cmd():
            with self.lock:
                ws = self.active_websocket
            if ws:
                msg = json.dumps({"type": "command", "payload": payload})
                await ws.send(msg)

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(send_cmd(), self.loop)
        else:
            return {"success": False, "error": "WebSocket loop is not running."}

        # Wait for result
        start_time = time.time()
        while not self.result_event.is_set():
            # Check for emergency abort
            if agent.ABORT_AGENT:
                logging.warning("Emergency abort triggered while waiting for Chrome Extension result.")
                return {"success": False, "error": "User aborted execution"}

            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                return {"success": False, "error": "Timeout waiting for extension result"}

            # Wait for a short duration to allow checking the abort flag frequently
            self.result_event.wait(timeout=min(1.0, remaining))

        res = self.result
        self.result = None
        self.result_event.clear()
        return res

    def receive_result(self, result: dict):
        self.result = result
        self.result_event.set()

# Global instance for use in agent.py
bridge = LocalBridgeManager()
