import sys
import unittest
import os
import asyncio
import time
from unittest.mock import patch, MagicMock

# Add project root and backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
import firebase_admin
import chromadb
sys.modules['chromadb'] = MagicMock()

import google.generativeai
sys.modules['google.generativeai'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.service_account'] = MagicMock()

sys.modules['uiautomation'] = MagicMock()
sys.modules['comtypes'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()
sys.modules['pyautogui'] = MagicMock()
sys.modules['win32clipboard'] = MagicMock()

import ctypes
# We shouldn't globally mock ctypes entirely since other modules like scipy use it heavily
if not hasattr(ctypes, 'windll'):
    ctypes.windll = MagicMock()
    ctypes.windll.user32 = MagicMock()
    ctypes.windll.shcore = MagicMock()

# Do not mock entire ctypes
# sys.modules['ctypes'] = MagicMock()

from client.agent import AgentStateMachine, AgentState
from client.tests.integration.test_sop_loop import MockExtensionBridge

# We mock out backend calls entirely for this test, we just want to test agent's resilience
class ChaosRunner:
    def __init__(self):
        self.iterations = 50
        self.successes = 0
        self.failures = 0
        self.diagnostics = []

    async def run(self):
        print(f"Starting Nightly Chaos Healing Fuzzer ({self.iterations} iterations)...")

        for i in range(self.iterations):
            # We want to mutate the mock bridge or the agent's expected state
            mock_dom = "<html><body><button id='submit-btn'>Submit</button></body></html>"

            # Every 3rd iteration, make the DOM invalid
            if i % 3 == 0:
                mock_dom = "<html><body><h1>Missing button!</h1></body></html>"

            bridge = MockExtensionBridge(mock_dom)
            agent = AgentStateMachine()

            agent.client_context = {"domain": "mock.com", "id": f"client_{i}"}
            agent.sub_tasks = ["submit_form"]
            agent.state = AgentState.THINKING
            agent.current_sub_task_index = 0
            agent.history = []
            agent.command_text = "Submit form"
            agent.current_ui_elements = [{"id": "submit-btn", "tag": "button", "text": "Submit", "center_x": 100, "center_y": 100}]
            agent.current_url = "https://mock.com"
            agent.current_clean_screenshot = b""
            agent.doc_id = f"chaos_run_{i}"
            agent.intent = "WEB"

            # Setup agent context
            agent.max_sub_task_iterations = 3

            # Try running the state machine loop explicitly for a few steps
            try:
                with patch('client.agent.save_flight_record'), \
                     patch('client.agent.firestore_get_document', return_value={"domain": "mock.com", "goal": "submit_form", "rule": "WAIT_FOR target_id=submit-btn; CLICK target_id=submit-btn"}), \
                     patch('client.agent.CURRENT_TOKEN', "mock_token"), \
                     patch('client.agent.firestore_update_document'), \
                     patch('client.agent.requests.Session.request') as mock_auth_req:

                    mock_response = MagicMock()
                    mock_response.status_code = 200

                    if i % 3 == 0:
                        mock_response.json.return_value = {
                            "actions": [{"action": "ERROR", "error": "Target not found in DOM"}],
                            "rules": []
                        }
                    else:
                        mock_response.json.return_value = {
                            "actions": [{"action": "CLICK", "target_id": "submit-btn"}],
                            "rules": ["WAIT_FOR target_id=submit-btn; CLICK target_id=submit-btn"]
                        }
                    mock_auth_req.return_value = mock_response

                    await agent.state_thinking(bridge)
                    await agent.state_acting(bridge)

                    # For evaluating, we need to deal with failures
                    if i % 3 == 0:
                        agent.previous_action = {"action": "ERROR", "error": "Target not found"}
                        agent.sub_task_iteration = 3 # Circuit breaker
                        await agent.state_evaluating(bridge)
                        if agent.state in [AgentState.TRAINING_NEEDED, AgentState.SUSPENDED_HITL]:
                            self.successes += 1
                        else:
                            self.failures += 1
                    else:
                        await agent.state_evaluating(bridge)
                        # Expecting to transition cleanly or finish
                        self.successes += 1

            except Exception as e:
                self.failures += 1
                self.diagnostics.append(f"Run {i} failed: {e}")

        # Generate markdown report
        report = f"""# Nightly Chaos Healing Report

## Execution Summary
* **Total Iterations:** {self.iterations}
* **Successes:** {self.successes}
* **Failures:** {self.failures}

## Diagnostics
"""
        for d in self.diagnostics:
            report += f"* {d}\n"

        with open("nightly_healing_report.md", "w", encoding="utf-8") as f:
            f.write(report)

        print("Report generated at nightly_healing_report.md")

if __name__ == "__main__":
    runner = ChaosRunner()
    asyncio.run(runner.run())
