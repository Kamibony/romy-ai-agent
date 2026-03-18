import sys
import os
import json
import time
from unittest.mock import MagicMock

# Ensure we can import backend modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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

def run_diagnostics():
    print("--- Phase 3 Multi-Agent Diagnostics (LIVE) ---")

    if not os.environ.get("GEMINI_API_KEY"):
        print("Warning: GEMINI_API_KEY environment variable is not set!")

    cmd = "Book a flight to Tokyo for next Friday."

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
