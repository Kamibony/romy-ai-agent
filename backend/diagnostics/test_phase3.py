import sys
import os
import json
from unittest.mock import MagicMock

# Mock chromadb to bypass dependency
sys.modules['chromadb'] = MagicMock()

# Mock firebase_admin and firestore.client() to bypass database dependency errors
# using dummy credentials and MagicMock as required by isolated testing.
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()

import firebase_admin
from firebase_admin import credentials, firestore

dummy_cred = MagicMock()
credentials.Certificate = MagicMock(return_value=dummy_cred)
firebase_admin.initialize_app = MagicMock()
firestore.client = MagicMock(return_value=MagicMock())

# Ensure we can import backend modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock Gemini API Key
os.environ['GEMINI_API_KEY'] = 'dummy_key'

# Mock google.genai
mock_genai = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = mock_genai
sys.modules['google.genai.types'] = MagicMock()

import ai_service

def setup_gemini_mock(response_text):
    mock_response = MagicMock()
    mock_response.text = response_text

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    ai_service.gemini_client = mock_client
    return mock_client

def run_diagnostics():
    print("--- Phase 3 Multi-Agent Diagnostics ---")

    cmd = "Book a flight to Tokyo for next Friday."

    # [1] Pre-Flight Agent
    print(f"\n[1] Testing Pre-Flight Agent with command: '{cmd}'")
    setup_gemini_mock(json.dumps({"status": "ok"}))
    pre_flight_res = ai_service.pre_flight_check_with_gemini(cmd)
    print(f"Result: {pre_flight_res}")

    # [2] Supervisor Agent
    print(f"\n[2] Testing Supervisor Agent with command: '{cmd}'")
    setup_gemini_mock(json.dumps(["Navigate to pelikan.cz", "Type Origin", "Type Destination", "Select Dates", "Click Search"]))
    plan_res = ai_service.supervisor_plan_with_gemini(cmd)
    print(f"Result: {plan_res}")

    # [3] Navigator Agent
    print("\n[3] Testing Navigator Agent (process_with_gemini)")
    ui_elements = [{"id": "1", "xpath": "//input", "description": "Destination input"}]
    setup_gemini_mock(json.dumps([{"action": "TYPE", "target_id": "1", "text": "Tokyo", "thought": "Entering destination"}]))
    nav_res = ai_service.process_with_gemini(
        ui_elements=ui_elements,
        command_text=cmd,
        current_sub_task="Enter destination city"
    )
    print(f"Result: {nav_res}")

    # [4] Critic Agent
    print("\n[4] Testing Critic Agent (critic_verify_with_gemini)")
    setup_gemini_mock(json.dumps({"success": True, "reason": "The text Tokyo appears in the destination input"}))
    critic_res = ai_service.critic_verify_with_gemini(
        sub_task="Enter destination city",
        before_state={"ui_elements": ui_elements},
        action_taken={"action": "TYPE", "target_id": "1", "text": "Tokyo"},
        after_state={"ui_elements": [{"id": "1", "xpath": "//input", "description": "Destination input with text Tokyo"}]}
    )
    print(f"Result: {critic_res}")

    print("\n--- Diagnostics Complete ---")

if __name__ == "__main__":
    run_diagnostics()
