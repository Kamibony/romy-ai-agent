import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.auth'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['chromadb'] = MagicMock()

os.environ["LOCAL_DEV"] = "True"

from main import app, verify_firebase_token, get_memory_repository
from repositories import InMemoryMemoryRepository

def override_verify_firebase_token():
    return "fake_uid"

shared_mock_repo = InMemoryMemoryRepository()

app.dependency_overrides[verify_firebase_token] = override_verify_firebase_token
app.dependency_overrides[get_memory_repository] = lambda: shared_mock_repo

client = TestClient(app)

@patch('main.check_user_license')
@patch('main.compile_sop_with_gemini')
def test_save_sop(mock_compile, mock_check_license):
    mock_check_license.return_value = True
    mock_compile.return_value = "Compiled SOP Rule"

    shared_mock_repo.rules.clear()

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

    assert len(shared_mock_repo.rules) == 1
    saved_rule = list(shared_mock_repo.rules.values())[0]
    assert saved_rule["rule"] == "Compiled SOP Rule"

@patch('main.check_user_license')
def test_get_sops(mock_check_license):
    mock_check_license.return_value = True

    shared_mock_repo.rules.clear()
    shared_mock_repo.rules["doc1"] = {"id": "doc1", "rule": "Rule 1", "client_id": "test_client"}

    response = client.get("/api/v1/memory/sops?client_id=test_client")
    assert response.status_code == 200

    sops = response.json().get("sops", [])
    assert len(sops) == 1
    assert sops[0]["id"] == "doc1"
    assert sops[0]["rule"] == "Rule 1"

@patch('main.check_user_license')
def test_delete_sop(mock_check_license):
    mock_check_license.return_value = True

    shared_mock_repo.rules.clear()
    shared_mock_repo.rules["doc1"] = {"id": "doc1", "rule": "Rule 1", "client_id": "test_client"}

    response = client.delete("/api/v1/memory/sops/doc1?client_id=test_client")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(shared_mock_repo.rules) == 0
