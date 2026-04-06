import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock firebase and chromadb before importing main
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.auth'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['chromadb'] = MagicMock()

# Instead of patching backend.main decorators directly which gets hairy, let's just
# override the dependency for authentication
from backend.main import app, verify_firebase_token

def override_verify_firebase_token():
    return "fake_uid"

app.dependency_overrides[verify_firebase_token] = override_verify_firebase_token

client = TestClient(app)

@patch('backend.main.check_user_license')
@patch('backend.main.compile_sop_with_gemini')
@patch('backend.main.save_playbook_rule')
def test_save_sop(mock_save, mock_compile, mock_check_license):
    mock_check_license.return_value = True
    mock_compile.return_value = "Compiled SOP Rule"

    response = client.post(
        "/api/v1/memory/sops",
        json={
            "domain": "example.com",
            "goal": "Test Goal",
            "recorded_steps": [{"action": "click", "target": "button"}],
            "client_id": "test_client"
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "rule": "Compiled SOP Rule"}
    mock_save.assert_called_once()

@patch('backend.main.check_user_license')
@patch('backend.main.list_playbook_rules_from_firestore')
def test_get_sops(mock_list, mock_check_license):
    mock_check_license.return_value = True
    mock_list.return_value = [{"id": "doc1", "rule": "Rule 1"}]

    response = client.get("/api/v1/memory/sops?client_id=test_client")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "sops": [{"id": "doc1", "rule": "Rule 1"}]}


@patch('backend.main.check_user_license')
@patch('backend.main.delete_playbook_rule')
def test_delete_sop(mock_delete, mock_check_license):
    mock_check_license.return_value = True
    mock_delete.return_value = True

    response = client.delete("/api/v1/memory/sops/doc1?client_id=test_client")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
