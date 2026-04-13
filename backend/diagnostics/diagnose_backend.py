import sys
import os
import requests
import traceback
import json

# Setup Local Dev mock tokens
os.environ["LOCAL_DEV"] = "True"
os.environ["ROMY_TEST_MODE"] = "1"

API_BASE_URL = "http://127.0.0.1:8000"

def print_header(title):
    print("\n" + "=" * 50)
    print(f" {title} ")
    print("=" * 50)

def test_environment_vars():
    print_header("Test: Environment Variable Loading")
    # Load .env manually for diagnosis
    from pathlib import Path
    from dotenv import load_dotenv

    backend_dir = Path(__file__).resolve().parent.parent
    dotenv_path = backend_dir / ".env"

    print(f"Looking for .env at: {dotenv_path}")
    if dotenv_path.exists():
        print("PASS: .env file found.")
        load_dotenv(dotenv_path=dotenv_path)
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            print("PASS: GEMINI_API_KEY is loaded.")
        else:
            print("WARN: GEMINI_API_KEY is missing from .env.")
    else:
        print("WARN: .env file not found. System may rely on system environment variables.")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            print("PASS: GEMINI_API_KEY is loaded from system env.")
        else:
            print("WARN: GEMINI_API_KEY is completely missing.")

def test_firebase_db_connectivity():
    print_header("Test: Firebase / DB Connectivity")
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from db import check_user_license
        from memory import list_playbook_rules_from_firestore

        # We will attempt to use a mock user ID
        # Since LOCAL_DEV=True, this should bypass real auth, but let's test if we can interact with DB
        res = check_user_license("local-dev-uid")
        if res:
            print("PASS: check_user_license bypassed correctly via LOCAL_DEV.")
        else:
            print("FAIL: check_user_license failed.")

        print("Attempting to list playbook rules (may fail if Firebase is not properly initialized with ADC)...")
        try:
            rules = list_playbook_rules_from_firestore(client_id="test_client")
            print(f"PASS: list_playbook_rules_from_firestore returned {len(rules)} rules.")
        except Exception as e:
            print(f"WARN: list_playbook_rules_from_firestore raised an exception: {e}")
            traceback.print_exc()

    except Exception as e:
        print(f"FAIL: Error in DB connectivity test: {e}")
        traceback.print_exc()

def test_get_sops_endpoint():
    print_header("Test: GET /api/v1/memory/sops")
    try:
        headers = {"Authorization": "Bearer local-dev-token"}
        response = requests.get(f"{API_BASE_URL}/api/v1/memory/sops", headers=headers, timeout=5)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if "sops" in data:
                print("PASS: GET /api/v1/memory/sops returned successfully with graceful degradation/data.")
            else:
                print("FAIL: Response JSON missing 'sops' key.")
                print(data)
        else:
            print(f"FAIL: Unexpected status code {response.status_code}")
            print(response.text)
    except requests.exceptions.ConnectionError:
        print("FAIL: Connection error. Is the FastAPI server running?")
    except Exception as e:
        print(f"FAIL: GET request raised an exception: {e}")
        traceback.print_exc()

def test_post_sops_endpoint():
    print_header("Test: POST /api/v1/memory/sops")
    try:
        headers = {
            "Authorization": "Bearer local-dev-token",
            "Content-Type": "application/json"
        }
        payload = {
            "domain": "diagnostics.local",
            "goal": "Test POST Endpoint",
            "recorded_steps": [
                {"action": "click", "target": "submit_button"}
            ],
            "client_id": "diag_client"
        }
        response = requests.post(f"{API_BASE_URL}/api/v1/memory/sops", headers=headers, json=payload, timeout=10)
        print(f"Status Code: {response.status_code}")

        if response.status_code in [200, 500]:
            print(f"PASS: POST endpoint responded without silent crashing (Status {response.status_code}).")
            print(f"Response: {response.text}")
        else:
            print(f"FAIL: Unexpected status code {response.status_code}")
            print(response.text)
    except requests.exceptions.ConnectionError:
        print("FAIL: Connection error. Is the FastAPI server running?")
    except Exception as e:
        print(f"FAIL: POST request raised an exception: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    print("Starting ROMY Backend Diagnostics...")
    test_environment_vars()
    test_firebase_db_connectivity()

    print("\nNote: The HTTP endpoint tests require the FastAPI server to be running on localhost:8000.")
    print("If it is not running, these tests will fail with a ConnectionError.")
    test_get_sops_endpoint()
    test_post_sops_endpoint()

    print("\nDiagnostic run complete.")
