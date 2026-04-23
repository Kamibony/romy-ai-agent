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
