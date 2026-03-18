import sys
import os
import time
import json
import base64

# Add backend directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock environment if necessary, though we need GEMINI_API_KEY
# os.environ["GEMINI_API_KEY"] = "your_key"

# Initialize a mock Firebase app to prevent db errors
import firebase_admin
from firebase_admin import credentials
# Mock credentials are fine for pure db client initialization locally
try:
    cred = credentials.Certificate({"type": "service_account", "project_id": "dummy"})
    firebase_admin.initialize_app(cred)
except ValueError:
    pass # App already initialized

# Also mock firestore client specifically
from unittest.mock import MagicMock
import sys
import os

mock_db = MagicMock()
mock_db.collection.return_value.document.return_value.get.return_value.exists = False

class MockFirestore:
    def client(self):
        return mock_db

sys.modules['firebase_admin.firestore'] = MockFirestore()

import ai_service
import memory

def run_pre_flight_tests():
    print("\n--- Testing Pre-Flight Agent ---")

    # Missing data
    start_time = time.time()
    cmd_missing = "Book me a flight to Paris"
    res_missing = ai_service.pre_flight_check_with_gemini(cmd_missing)
    elapsed = time.time() - start_time
    print(f"Pre-Flight (Missing Data) - Result: {res_missing}, Time: {elapsed:.3f}s")

    # Complete data
    start_time = time.time()
    cmd_complete = "Book me a flight to Paris from New York on October 15th"
    res_complete = ai_service.pre_flight_check_with_gemini(cmd_complete)
    elapsed = time.time() - start_time
    print(f"Pre-Flight (Complete Data) - Result: {res_complete}, Time: {elapsed:.3f}s")

def run_supervisor_tests():
    print("\n--- Testing Supervisor Agent ---")
    start_time = time.time()
    cmd = "Go to pelikan.cz, search for a round trip flight from Prague to Rome departing next Monday and returning next Friday, and select the cheapest option."
    res = ai_service.supervisor_plan_with_gemini(cmd)
    elapsed = time.time() - start_time
    print(f"Supervisor - Result: {res}, Time: {elapsed:.3f}s")

def run_navigator_tests():
    print("\n--- Testing Navigator Agent (The Suspect) ---")

    # Mock data
    ui_elements = [
        {"id": "1", "xpath": "//input[@id='from']", "description": "Origin city input"},
        {"id": "2", "xpath": "//input[@id='to']", "description": "Destination city input"},
        {"id": "3", "xpath": "//button[@id='search']", "description": "Search button"}
    ]
    current_sub_task = "Enter destination city Rome"
    current_url = "https://www.pelikan.cz/en/"

    # Monkey patch to measure inner components
    # 1. ChromaDB RAG retrieval
    original_get_playbook_rules = memory.get_playbook_rules
    rag_time = [0]
    def mocked_get_playbook_rules(domain):
        st = time.time()
        res = original_get_playbook_rules(domain)
        rag_time[0] = time.time() - st
        return res
    ai_service.get_playbook_rules = mocked_get_playbook_rules

    # 2. Gemini API
    original_generate_content = ai_service.gemini_client.models.generate_content
    gemini_time = [0]
    def mocked_generate_content(*args, **kwargs):
        st = time.time()
        res = original_generate_content(*args, **kwargs)
        gemini_time[0] = time.time() - st
        return res
    ai_service.gemini_client.models.generate_content = mocked_generate_content

    # Measure overall
    start_time = time.time()
    # Using process_with_gemini
    res = ai_service.process_with_gemini(
        ui_elements=ui_elements,
        current_sub_task=current_sub_task,
        current_url=current_url,
        command_text="mock command"
    )
    total_time = time.time() - start_time

    # We will do one more RAG call isolated to see if it's the 90s issue
    # since sometimes Chroma block is lazy loading

    start_rag = time.time()
    memory.get_playbook_rules("anotherdomain.com")
    second_rag_time = time.time() - start_rag
    print(f"  -> Second isolated RAG retrieval time: {second_rag_time:.3f}s")

    # Calculate prompt assembly roughly
    prompt_assembly_time = total_time - rag_time[0] - gemini_time[0]

    print(f"Navigator - Overall Time: {total_time:.3f}s")
    print(f"  -> ChromaDB RAG retrieval time: {rag_time[0]:.3f}s")
    print(f"  -> Gemini API latency: {gemini_time[0]:.3f}s")
    print(f"  -> Estimated Prompt Assembly & parsing time: {prompt_assembly_time:.3f}s")
    print(f"Result: {res}")

    # Restore monkey patches
    ai_service.get_playbook_rules = original_get_playbook_rules
    ai_service.gemini_client.models.generate_content = original_generate_content

def run_critic_tests():
    print("\n--- Testing Critic Agent ---")
    sub_task = "Enter destination city Rome"
    action_taken = {"action": "TYPE", "target_id": "2", "text": "Rome"}
    before_state = {"ui_elements": [{"id": "2", "value": ""}]}
    after_state = {"ui_elements": [{"id": "2", "value": "Rome"}]}

    start_time = time.time()
    res = ai_service.critic_verify_with_gemini(sub_task, before_state, action_taken, after_state)
    elapsed = time.time() - start_time
    print(f"Critic - Result: {res}, Time: {elapsed:.3f}s")

def run_synthesizer_tests():
    print("\n--- Testing Synthesizer / Memory ---")
    domain = "testdomain.com"
    telemetry = "Tried to type Rome, but a dropdown appeared. Next time, must click the dropdown."

    start_time = time.time()
    res = ai_service.synthesize_playbook_rule_with_gemini(domain, telemetry)
    elapsed = time.time() - start_time
    print(f"Synthesizer - Result: {res}, Time: {elapsed:.3f}s")

if __name__ == "__main__":
    if ai_service.gemini_client is None:
        print("Error: Gemini client is not initialized. Make sure GEMINI_API_KEY is set.")
        sys.exit(1)

    print("Starting Phase 3 Comprehensive Diagnostics...")
    run_pre_flight_tests()
    run_supervisor_tests()
    run_navigator_tests()
    run_critic_tests()
    run_synthesizer_tests()
    print("\nDiagnostics complete.")
