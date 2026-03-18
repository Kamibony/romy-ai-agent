import sys
import os
import json
import time
from unittest.mock import MagicMock
from dotenv import load_dotenv

# Construct absolute path to backend/.env and load it
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
dotenv_path = os.path.join(backend_dir, '.env')
load_dotenv(dotenv_path)

# Ensure we can import backend modules
sys.path.insert(0, backend_dir)

# Mock google.genai so we don't need a real API key and can isolate ChromaDB latency
mock_genai = MagicMock()
sys.modules['google.genai'] = mock_genai
sys.modules['google.genai.types'] = MagicMock()

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

import ai_service

# Inject our mocked gemini client directly into ai_service
mock_client = MagicMock()
ai_service.gemini_client = mock_client

def run_diagnostics():
    print("--- Phase 3 Multi-Agent Diagnostics (LIVE) ---")

    print("MOCKING GEMINI API CALLS")
    cmd = "Book a flight to Tokyo for next Friday."

    # Setup dummy mock responses
    # 1. Pre-Flight
    mock_preflight_response = MagicMock()
    mock_preflight_response.text = '{"status": "ok"}'

    # 2. Supervisor
    mock_supervisor_response = MagicMock()
    mock_supervisor_response.text = '["Navigate to pelikan.cz", "Search flights to Tokyo"]'

    # 3. Navigator
    mock_navigator_response = MagicMock()
    mock_navigator_response.text = '[{"action": "CLICK", "target_id": "100", "thought": "Clicking destination."}]'

    # 4. Critic
    mock_critic_response = MagicMock()
    mock_critic_response.text = '{"success": true, "reason": "Destination input has correct text."}'

    # We use side_effect to return different responses on subsequent calls
    mock_client.models.generate_content.side_effect = [
        mock_preflight_response,
        mock_supervisor_response,
        mock_navigator_response,
        mock_critic_response
    ]

    # [1] Pre-Flight Agent
    print(f"\n[1] Testing Pre-Flight Agent with command: '{cmd}'")
    pre_flight_res = ai_service.pre_flight_check_with_gemini(cmd)
    print(f"Result: {pre_flight_res}")

    # [2] Supervisor Agent
    print(f"\n[2] Testing Supervisor Agent with command: '{cmd}'")
    plan_res = ai_service.supervisor_plan_with_gemini(cmd)
    print(f"Result: {plan_res}")

    # [3] Navigator Agent
    print("\n[3] Testing Navigator Agent (process_with_gemini) with heavy payload")

    # Generate a large mock ui_elements array
    ui_elements = []
    for i in range(100):
        ui_elements.append({
            "id": str(i),
            "xpath": f"//div[{i}]/input",
            "description": f"Input field {i} for general data entry"
        })
    # Add a specific target element to see if it can find it
    ui_elements.append({
        "id": "100",
        "xpath": "//input[@name='destination']",
        "description": "Destination input"
    })

    print(f"Generated {len(ui_elements)} UI elements. Sending to Navigator...")

    start_time = time.time()
    nav_res = ai_service.process_with_gemini(
        ui_elements=ui_elements,
        command_text=cmd,
        current_sub_task="Enter destination city",
        current_url="https://www.pelikan.cz"
    )
    end_time = time.time()

    print(f"Navigator Time: {end_time - start_time:.2f} seconds")
    print(f"Result: {nav_res}")

    # [4] Critic Agent
    print("\n[4] Testing Critic Agent (critic_verify_with_gemini)")
    critic_res = ai_service.critic_verify_with_gemini(
        sub_task="Enter destination city",
        before_state={"ui_elements": ui_elements},
        action_taken={"action": "TYPE", "target_id": "100", "text": "Tokyo"},
        after_state={"ui_elements": [{"id": "100", "xpath": "//input[@name='destination']", "description": "Destination input with text Tokyo"}]}
    )
    print(f"Result: {critic_res}")

    print("\n--- Diagnostics Complete ---")

if __name__ == "__main__":
    run_diagnostics()
