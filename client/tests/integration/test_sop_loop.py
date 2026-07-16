import sys
import unittest
import os
import asyncio
from unittest.mock import patch, MagicMock

# Add project root and backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from agent import AgentStateMachine, AgentState
from fastapi.testclient import TestClient

# We must import backend.main after patching
import firebase_admin
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
import chromadb
sys.modules['chromadb'] = MagicMock()

import google.generativeai
sys.modules['google.generativeai'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.service_account'] = MagicMock()

from backend.main import app

class MockExtensionBridge:
    def __init__(self, mock_dom):
        self.mock_dom = mock_dom
        self.dispatched_actions = []

    def delegate_command(self, payload: dict, timeout=300):
        self.dispatched_actions.append(payload)

        action = payload.get("action")
        action_type = payload.get("action_type")

        if action == "GET_STATE" or action_type == "GET_STATE":
            return {
                "success": True,
                "data": {
                    "dom": self.mock_dom,
                    "screenshot": "base64_dummy",
                    "url": "https://mock.com",
                    "focused_element": None,
                    "elements": [
                        {"id": "submit-btn", "tag": "button", "text": "Submit", "center_x": 100, "center_y": 100}
                    ]
                }
            }
        elif action in ["CLICK", "TYPE", "NAVIGATE"] or action_type == "EXECUTE_ACTION":
            return {"success": True, "data": {}}

        return {"success": False, "error": "Unknown action"}

class TestSOPLoopIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch('backend.main.verify_firebase_token')
    @patch('backend.main.compile_sop_with_gemini')
    @patch('backend.main.check_user_license')
    def test_pillar_1_sop_ingestion(self, mock_check_license, mock_compile_sop, mock_verify_token):
        """Pillar 1: SOP Ingestion & Memory (The 'Inbound' Flow)"""
        mock_verify_token.return_value = "mock_uid"
        mock_check_license.return_value = True

        mocked_rule = "WAIT_FOR target_id=submit-btn; CLICK target_id=submit-btn"
        mock_compile_sop.return_value = mocked_rule

        payload = {
            "domain": "mock.com",
            "raw_sop": "Click the submit button",
            "client_id": "client_123",
            "target_sub_task": "submit_form"
        }

        response = self.client.post("/api/v1/memory/inject_sop", json=payload, headers={"Authorization": "Bearer mock_token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "rule": mocked_rule})

        mock_compile_sop.assert_called_once_with(
            "mock.com",
            "Click the submit button",
            client_id="client_123",
            target_sub_task="submit_form"
        )

    def test_mock_bridge(self):
        bridge = MockExtensionBridge("<html><body><button id='submit-btn'>Submit</button></body></html>")
        res = bridge.delegate_command({"action": "GET_STATE"})
        self.assertTrue(res["success"])

    import unittest

    @unittest.skip(reason="Phase 4: Requires async/MCP mock refactoring")
    @patch('client.agent.requests.Session.request')
    async def test_pillar_2_deterministic_execution(self, mock_auth_req):
        """Pillar 2: Deterministic Execution (The 'Happy Path')"""
        # Patch requests.Session.request directly since authenticated_request uses it
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "actions": [{"action": "CLICK", "target_id": "submit-btn"}],
            "rules": ["WAIT_FOR target_id=submit-btn; CLICK target_id=submit-btn"]
        }
        mock_auth_req.return_value = mock_response

        mock_dom = "<html><body><button id='submit-btn' data-romy-id='submit-btn'>Submit</button></body></html>"
        mock_bridge = MockExtensionBridge(mock_dom)

        agent = AgentStateMachine()
        agent.client_context = {"domain": "mock.com", "id": "client_123"}
        agent.sub_tasks = ["submit_form"]
        agent.state = AgentState.THINKING
        agent.current_sub_task_index = 0
        agent.history = []
        agent.command_text = "Submit form"
        agent.current_ui_elements = [{"id": "submit-btn", "tag": "button", "text": "Submit", "center_x": 100, "center_y": 100}]
        agent.current_url = "https://mock.com"
        agent.current_clean_screenshot = b""
        agent.doc_id = "mock_doc"
        agent.intent = "WEB"

        # Disable logging to avoid flight_record errors
        with patch('client.agent.save_flight_record'), \
             patch('client.agent.firestore_get_document', return_value={"domain": "mock.com", "goal": "submit_form", "rule": "WAIT_FOR target_id=submit-btn; CLICK target_id=submit-btn"}), \
             patch('client.agent.CURRENT_TOKEN', "mock_token"): # bypass auth error
            # Thinking will fetch rule, evaluate DOM, create actions_to_execute, change state to ACTING
            await agent.state_thinking(mock_bridge)
            self.assertEqual(agent.state, AgentState.ACTING)

            # Acting will dispatch the actions to the mock_bridge
            await agent.state_acting(mock_bridge)

        # Check if bridge dispatched EXECUTE_ACTION with action CLICK
        click_actions = [a for a in mock_bridge.dispatched_actions if a.get("action_type") == "EXECUTE_ACTION" and a.get("action", {}).get("action") == "CLICK"]
        self.assertTrue(len(click_actions) > 0, f"Dispatched actions: {mock_bridge.dispatched_actions}")
        self.assertEqual(agent.state, AgentState.EVALUATING)



    @unittest.skip(reason="Phase 4: Requires async/MCP mock refactoring")
    @patch('client.agent.requests.Session.request')
    async def test_pillar_3_graceful_failure_and_hitl(self, mock_auth_req):
        """Pillar 3: Graceful Failure & HITL Trigger (The 'Recovery Path')"""
        # When element is missing, agent uses LLM to find it,
        # mock returns ERROR since target is missing
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "actions": [{"action": "ERROR", "error": "Target not found in DOM"}],
            "rules": []
        }
        mock_auth_req.return_value = mock_response

        # DOM missing the submit button
        mock_dom = "<html><body><h1>Missing button!</h1></body></html>"
        mock_bridge = MockExtensionBridge(mock_dom)
        # Mock bridge GET_STATE returns no elements

        agent = AgentStateMachine()
        agent.client_context = {"domain": "mock.com", "id": "client_123"}
        agent.sub_tasks = ["submit_form"]
        agent.state = AgentState.THINKING
        agent.current_sub_task_index = 0
        agent.history = []
        agent.command_text = "Submit form"
        agent.current_ui_elements = [] # Empty!
        agent.current_url = "https://mock.com"
        agent.current_clean_screenshot = b""
        agent.doc_id = "mock_doc"
        agent.intent = "WEB"

        with patch('client.agent.save_flight_record'), \
             patch('client.agent.firestore_get_document', return_value={"domain": "mock.com", "goal": "submit_form", "rule": "WAIT_FOR target_id=submit-btn; CLICK target_id=submit-btn"}), \
             patch('client.agent.CURRENT_TOKEN', "mock_token"):

            # Subtask loop limit is usually 3
            agent.max_sub_task_iterations = 3
            agent.sub_task_iteration = 3 # Simulate circuit breaker tripped

            # Evaluation will see error and trigger circuit breaker
            await agent.state_thinking(mock_bridge)
            self.assertEqual(agent.state, AgentState.ACTING)

            await agent.state_acting(mock_bridge)
            self.assertEqual(agent.state, AgentState.EVALUATING)

            agent.previous_action = {"action": "ERROR", "error": "Target not found"}

            with patch('client.agent.firestore_update_document'):
                await agent.state_evaluating(mock_bridge)

            # Agent should notice `sub_task_iteration >= max_iterations` or explicit ERROR action
            # and transition to TRAINING_NEEDED or SUSPENDED_HITL
            self.assertIn(agent.state, [AgentState.TRAINING_NEEDED, AgentState.SUSPENDED_HITL])


if __name__ == "__main__":
    unittest.main()
