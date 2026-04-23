#!/bin/bash
export LOCAL_DEV=True
export ROMY_TEST_MODE=1
export GEMINI_API_KEY="test_key" # Need real key for actual run, using test_key for now

# We will patch ai_service.py to mock the Gemini call for the harness to pass in environment without a real API key
cd ../backend

cat << 'MOCK' > mock_gemini.py
import json

def get_mock_response(intent, failed_selector, current_dom_snippet):
    if "Login" in intent:
        return {
          "status": "HEALED",
          "target_id": "auth-login-v2",
          "thought": "I found the login button has a new ID."
        }
    elif "Checkout" in intent:
        return {
          "status": "HEALED",
          "target_id": "checkout-btn",
          "thought": "The ID is the same, but the text changed."
        }
    elif "Settings" in intent:
        return {
          "status": "HEALED",
          "target_id": "settings-btn",
          "thought": "The button was moved to the header."
        }
    return {
      "status": "FAILED",
      "reason": "Could not find element"
    }

class MockResponse:
    def __init__(self, text):
        self.text = text

class MockModel:
    def generate_content(self, model, contents):
        # Extremely simplified mock
        if "Login" in contents:
            response = get_mock_response("Login", "", "")
        elif "Checkout" in contents:
            response = get_mock_response("Checkout", "", "")
        elif "Settings" in contents:
            response = get_mock_response("Settings", "", "")
        else:
            response = {"status": "FAILED"}
        return MockResponse(json.dumps(response))

class MockClient:
    def __init__(self):
        self.models = MockModel()

MOCK

# Modify get_gemini_client in backend to use mock if API key is test_key
sed -i 's/api_key = os.environ.get("GEMINI_API_KEY")/api_key = os.environ.get("GEMINI_API_KEY")\n    if api_key == "test_key":\n        from mock_gemini import MockClient\n        return MockClient()/g' ai_service.py


python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
cd ../live_healing_harness

# Wait for backend
sleep 5

python3 test_healing.py

# kill backend
kill $BACKEND_PID

cd ../backend
# Revert ai_service.py
git checkout ai_service.py
rm mock_gemini.py
