import re

with open('client/local_bridge.py', 'r') as f:
    content = f.read()

# Add imports for HTTP server
import_repl = "import asyncio\nimport json\nimport logging\nimport threading\nimport time\nimport websockets\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\nimport urllib.parse\n"

content = content.replace("import asyncio\nimport json\nimport logging\nimport threading\nimport time\nimport websockets\n", import_repl)

# Add the HTTP Handler Class before LocalBridgeManager
http_handler = """
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
"""
content = content.replace("class LocalBridgeManager:", http_handler + "\nclass LocalBridgeManager:")

# Add initialization code for the HTTP Server thread
init_repl = """    def __init__(self, port=8765, http_port=8766):
        self.port = port
        self.http_port = http_port
        self.active_websocket = None
        self.pending_command = None
        self.result = None
        self.server_thread = None
        self.http_thread = None
        self.http_server = None
        self.loop = None
        self.server = None"""
content = re.sub(r'    def __init__\(self, port=8765\):.*?self\.server = None', init_repl, content, flags=re.DOTALL)

# Add start logic for the HTTP Server
start_repl = """    def start(self):
        if self.server_thread is None or not self.server_thread.is_alive():
            self.server_thread = threading.Thread(target=self._start_loop, daemon=True)
            self.server_thread.start()

        if self.http_thread is None or not self.http_thread.is_alive():
            self.http_thread = threading.Thread(target=self._start_http_server, daemon=True)
            self.http_thread.start()

    def _start_http_server(self):
        try:
            self.http_server = HTTPServer(('127.0.0.1', self.http_port), StateAPIHandler)
            logging.info(f"HTTP local bridge server started on http://127.0.0.1:{self.http_port}")
            self.http_server.serve_forever()
        except Exception as e:
            logging.error(f"HTTP server thread exception: {e}")"""
content = re.sub(r'    def start\(self\):.*?self\.server_thread\.start\(\)', start_repl, content, flags=re.DOTALL)

# Add stop logic for HTTP Server
stop_repl = """    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.stop_event.set)

        if self.server_thread:
            self.server_thread.join(timeout=2)

        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()

        if self.http_thread:
            self.http_thread.join(timeout=2)"""
content = re.sub(r'    def stop\(self\):.*?self\.server_thread\.join\(timeout=2\)', stop_repl, content, flags=re.DOTALL)


with open('client/local_bridge.py', 'w') as f:
    f.write(content)
