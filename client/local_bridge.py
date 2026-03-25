import asyncio
import json
import logging
import threading
import time
import websockets
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

def _kill_process_using_port(port: int):
    """Kills any process currently listening on the specified port to prevent 'Address already in use' errors."""
    try:
        current_pid = os.getpid()
        if os.name == 'nt':
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            pid = int(pid_str)
                            if pid != current_pid and pid > 0:
                                logging.warning(f"Port {port} is in use by PID {pid}. Attempting to kill it...")
                                subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
        else:
            result = subprocess.run(['lsof', '-t', f'-i:{port}'], capture_output=True, text=True)
            pids = result.stdout.strip().split('\n')
            for pid_str in pids:
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid != current_pid and pid > 0:
                        logging.warning(f"Port {port} is in use by PID {pid}. Attempting to kill it...")
                        subprocess.run(['kill', '-9', str(pid)], capture_output=True)
    except Exception as e:
        logging.warning(f"Failed to check/kill process on port {port}: {e}")


class StateAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/state':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))

                # Send the result to the global bridge instance
                bridge.receive_result(data)

                self.send_response(200)
                self.send_header('Content-type', 'application/json')

                # Enable CORS for the extension
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')

                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())

            except json.JSONDecodeError:
                logging.error("Failed to decode JSON from HTTP POST payload")
                self.send_response(400)
                self.send_header('Content-type', 'application/json')

                # Enable CORS
                self.send_header('Access-Control-Allow-Origin', '*')

                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            except Exception as e:
                logging.error(f"Error handling HTTP POST payload: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')

                # Enable CORS
                self.send_header('Access-Control-Allow-Origin', '*')

                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging of requests
        pass

class LocalBridgeManager:
    def __init__(self, port=8765, http_port=8766):
        self.port = port
        self.http_port = http_port
        self.active_websocket = None
        self.pending_command = None
        self.result = None
        self.server_thread = None
        self.http_thread = None
        self.http_server = None
        self.loop = None
        self.server = None

        # Synchronization
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.result_event = threading.Event()

        # Chunk reassembly buffer
        self.chunk_buffers = {}

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
                    if 'type' in data and data['type'] == 'chunk':
                        msg_id = data.get('message_id')
                        chunk_idx = data.get('chunk_index')
                        total_chunks = data.get('total_chunks')
                        chunk_data = data.get('data')

                        if msg_id not in self.chunk_buffers:
                            self.chunk_buffers[msg_id] = [None] * total_chunks

                        self.chunk_buffers[msg_id][chunk_idx] = chunk_data

                        if all(c is not None for c in self.chunk_buffers[msg_id]):
                            full_msg = "".join(self.chunk_buffers[msg_id])
                            del self.chunk_buffers[msg_id]

                            try:
                                reconstructed_data = json.loads(full_msg)
                                if 'type' in reconstructed_data and reconstructed_data['type'] == 'result':
                                    self.receive_result(reconstructed_data.get('payload', {}))
                                elif 'type' in reconstructed_data and reconstructed_data['type'] == 'telemetry':
                                    logging.info(f"Extension Telemetry: {reconstructed_data.get('payload')}")
                                else:
                                    logging.warning(f"Unknown reconstructed WebSocket message received: {reconstructed_data}")
                            except json.JSONDecodeError:
                                logging.error("Failed to decode reconstructed WebSocket message.")
                    elif 'type' in data and data['type'] == 'ping':
                        await websocket.send(json.dumps({"type": "pong"}))
                    elif 'type' in data and data['type'] == 'result':
                        self.receive_result(data.get('payload', {}))
                    elif 'type' in data and data['type'] == 'telemetry':
                        # Log extension telemetry, don't spam if it's just a keep-alive
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

        # Ensure the port is free before binding
        _kill_process_using_port(self.port)

        # Small delay to ensure OS has fully released the port
        await asyncio.sleep(0.5)

        self.server = await websockets.serve(
            self._handle_client,
            '127.0.0.1',
            self.port,
            max_size=None, # Explicitly remove max_size to accommodate massive base64 uncompressed payloads
            ping_interval=None,        # Disable default pings to avoid timeout during long vision captures
            ping_timeout=None
        )
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
        if self.server_thread is None or not self.server_thread.is_alive():
            self.server_thread = threading.Thread(target=self._start_loop, daemon=True)
            self.server_thread.start()

        if self.http_thread is None or not self.http_thread.is_alive():
            self.http_thread = threading.Thread(target=self._start_http_server, daemon=True)
            self.http_thread.start()

    def _start_http_server(self):
        try:
            # Ensure the port is free before binding
            _kill_process_using_port(self.http_port)
            time.sleep(0.5)

            self.http_server = HTTPServer(('127.0.0.1', self.http_port), StateAPIHandler)

            # Allow address reuse
            self.http_server.allow_reuse_address = True

            logging.info(f"HTTP local bridge server started on http://127.0.0.1:{self.http_port}")
            self.http_server.serve_forever()
        except Exception as e:
            logging.error(f"HTTP server thread exception: {e}")

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.stop_event.set)

        if self.server_thread:
            self.server_thread.join(timeout=2)

        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()

        if self.http_thread:
            self.http_thread.join(timeout=2)

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
