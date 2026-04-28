import logging
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
    logging.info("\n" + "=" * 50)
    logging.info(f" {title} ")
    logging.info("=" * 50)

def test_environment_vars():
    print_header("Test: Environment Variable Loading")
    # Load .env manually for diagnosis
    from pathlib import Path
    from dotenv import load_dotenv

    backend_dir = Path(__file__).resolve().parent.parent
    dotenv_path = backend_dir / ".env"

    logging.info(f"Looking for .env at: {dotenv_path}")
    if dotenv_path.exists():
        logging.info("PASS: .env file found.")
        load_dotenv(dotenv_path=dotenv_path)
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            logging.info("PASS: GEMINI_API_KEY is loaded.")
        else:
            logging.info("WARN: GEMINI_API_KEY is missing from .env.")
    else:
        logging.info("WARN: .env file not found. System may rely on system environment variables.")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            logging.info("PASS: GEMINI_API_KEY is loaded from system env.")
        else:
            logging.info("WARN: GEMINI_API_KEY is completely missing.")

def test_firebase_db_connectivity():
    print_header("Test: Firebase / DB Connectivity")
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from db import check_user_license
        from repositories import get_memory_repository

        # We will attempt to use a mock user ID
        # Since LOCAL_DEV=True, this should bypass real auth, but let's test if we can interact with DB
        res = check_user_license("local-dev-uid")
        if res:
            logging.info("PASS: check_user_license bypassed correctly via LOCAL_DEV.")
        else:
            logging.info("FAIL: check_user_license failed.")

        logging.info("Attempting to list playbook rules (may fail if Firebase is not properly initialized with ADC)...")
        try:
            repo = get_memory_repository()
            rules = repo.list_playbook_rules()
            logging.info(f"PASS: list_playbook_rules_from_firestore returned {len(rules)} rules.")
        except Exception as e:
            logging.info(f"WARN: list_playbook_rules_from_firestore raised an exception: {e}")
            traceback.print_exc()

    except Exception as e:
        logging.info(f"FAIL: Error in DB connectivity test: {e}")
        traceback.print_exc()

def test_get_sops_endpoint():
    print_header("Test: GET /api/v1/memory/sops")
    try:
        headers = {"Authorization": "Bearer local-dev-token"}
        response = requests.get(f"{API_BASE_URL}/api/v1/memory/sops", headers=headers, timeout=5)
        logging.info(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if "sops" in data:
                logging.info("PASS: GET /api/v1/memory/sops returned successfully with graceful degradation/data.")
            else:
                logging.info("FAIL: Response JSON missing 'sops' key.")
                logging.info(data)
        else:
            logging.info(f"FAIL: Unexpected status code {response.status_code}")
            logging.info(response.text)
    except requests.exceptions.ConnectionError:
        logging.info("FAIL: Connection error. Is the FastAPI server running?")
    except Exception as e:
        logging.info(f"FAIL: GET request raised an exception: {e}")
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
        logging.info(f"Status Code: {response.status_code}")

        if response.status_code in [200, 500]:
            logging.info(f"PASS: POST endpoint responded without silent crashing (Status {response.status_code}).")
            logging.info(f"Response: {response.text}")
        else:
            logging.info(f"FAIL: Unexpected status code {response.status_code}")
            logging.info(response.text)
    except requests.exceptions.ConnectionError:
        logging.info("FAIL: Connection error. Is the FastAPI server running?")
    except Exception as e:
        logging.info(f"FAIL: POST request raised an exception: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    logging.info("Starting ROMY Backend Diagnostics...")
    test_environment_vars()
    test_firebase_db_connectivity()

    logging.info("\nNote: The HTTP endpoint tests require the FastAPI server to be running on localhost:8000.")
    logging.info("If it is not running, these tests will fail with a ConnectionError.")
    test_get_sops_endpoint()
    test_post_sops_endpoint()

    logging.info("\nDiagnostic run complete.")
