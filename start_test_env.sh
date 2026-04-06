#!/bin/bash
export DISPLAY=:99
kill $(pgrep -af python | grep main.py | awk '{print $1}') 2>/dev/null

cd client
source venv/bin/activate

# Mock token validation and backend requests for offline testing
cat << 'MOCK' > mock_backend.py
import sys
import unittest.mock as mock
import requests

def start_mock():
    # Mock requests to avoid 401 errors
    def mock_request(method, url, *args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code, text=""):
                self.json_data = json_data
                self.status_code = status_code
                self.text = text

            def json(self):
                return self.json_data

            def raise_for_status(self):
                if self.status_code != 200:
                    raise Exception(f"HTTPError: {self.status_code}")

        if "classify_intent" in url:
            return MockResponse({"intent": "WEB", "command_text": "mock command"}, 200)
        elif "get_command" in url:
            return MockResponse({"actions": [{"action": "DONE"}]}, 200)
        elif "pre_flight" in url:
            return MockResponse({"status": "ok"}, 200)
        elif "supervisor_plan" in url:
            return MockResponse({"sub_tasks": ["mock sub task"]}, 200)
        elif "evaluate_plan_progress" in url:
            return MockResponse({"is_accomplished": True, "reason": "mock reason"}, 200)
        elif "firestore" in url:
            if method == "GET":
                 if "client_profiles" in url or "tenants" in url:
                     return MockResponse({"fields": {}}, 200)
                 return MockResponse({}, 200)
            elif method == "POST" and "runQuery" in url:
                 return MockResponse([], 200)
            return MockResponse({}, 200)

        return MockResponse({}, 200)

    requests_mock = mock.patch('agent.requests.Session.request', side_effect=mock_request)
    requests_mock.start()

start_mock()

import agent
agent.CURRENT_TOKEN = 'dummy_token'

# Mock local_bridge so it doesn't wait for Chrome Extension
import local_bridge
class MockBridge:
    def start(self): pass
    def request_fresh_token(self, timeout=None): return 'dummy_token'
    def delegate_command(self, *args, **kwargs): return {"success": True, "url": "mock", "ui_elements": []}
local_bridge.bridge = MockBridge()

import main
main.main()
MOCK

python -c "
import sys
with open('agent.py', 'r') as f:
    code = f.read()
code = code.replace('if not CURRENT_TOKEN:', 'if False:')
with open('agent_mock.py', 'w') as f:
    f.write(code)
"
mv agent_mock.py agent.py
python mock_backend.py &> client_main.log &
CLIENT_PID=$!

echo "Waiting for services to start..."
sleep 5
cd ..
python diagnostics_runner.py

kill $CLIENT_PID
git restore client/agent.py
rm client/mock_backend.py
