import http.server
import json
import logging
import threading
from urllib.parse import urlparse, parse_qs
import queue
import time

class LocalBridgeHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/command':
            self.handle_get_command()
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        if self.path == '/result':
            self.handle_post_result()
        else:
            self.send_error(404, 'Not Found')

    def handle_get_command(self):
        try:
            cmd = getattr(self.server, 'bridge_manager').get_pending_command()
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(cmd if cmd else {})
            self.wfile.write(response.encode('utf-8'))
        except Exception as e:
            logging.error(f"Error handling GET /command: {e}")
            self.send_error(500, 'Internal Server Error')

    def handle_post_result(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            result = json.loads(post_data.decode('utf-8'))
            getattr(self.server, 'bridge_manager').receive_result(result)
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        except Exception as e:
            logging.error(f"Error handling POST /result: {e}")
            self.send_error(500, 'Internal Server Error')

    def log_message(self, format, *args):
        pass

class LocalBridgeManager:
    def __init__(self, port=8765):
        self.port = port
        self.pending_command = None
        self.result = None
        self.server = None
        self.server_thread = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

    def start(self):
        if self.server is not None:
            return

        self.server = http.server.HTTPServer(('127.0.0.1', self.port), LocalBridgeHandler)
        self.server.bridge_manager = self
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        logging.info(f"Local bridge server started on port {self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def delegate_command(self, payload: dict, timeout=300):
        with self.condition:
            self.pending_command = payload
            self.result = None
            logging.info(f"Delegating command to Chrome Extension: {payload.get('commandText', '')[:50]}")

            # Wait for result
            start_time = time.time()
            while self.result is None:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    self.pending_command = None
                    return {"success": False, "error": "Timeout waiting for extension result"}
                self.condition.wait(timeout=remaining)

            res = self.result
            self.result = None
            return res

    def get_pending_command(self):
        with self.lock:
            cmd = self.pending_command
            self.pending_command = None # Clear after fetching to prevent double execution
            return cmd

    def receive_result(self, result: dict):
        with self.condition:
            self.result = result
            self.condition.notify_all()

# Global instance for use in agent.py
bridge = LocalBridgeManager()
