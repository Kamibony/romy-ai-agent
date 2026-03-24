import sys
import os
import time
import logging
import uuid
import json
import urllib.request
import urllib.error

# Configure logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCAL_API_URL = "http://127.0.0.1:8764/api"

def check_local_api_running():
    try:
        # Just checking if the port is open and responding with 404 to a random GET
        req = urllib.request.Request(f"{LOCAL_API_URL}/ping")
        try:
            urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return True
            return False
        return True
    except urllib.error.URLError:
        return False

def test_harness():
    """
    E2E Test Harness:
    Automatically feeds commands targeting generic websites to the agent queue via local API.
    Logs success/failure and execution time of each.
    """
    commands = [
        {
            "command_text": "Navigate to sreality.cz, select 'Pronájem', select 'Byty', set disposition to '2+kk', enter location 'Praha', and sort by price.",
            "client_context": {
                "client_id": "sreality",
                "rules": [
                    "Always click 'Souhlasím' on cookie consent banners.",
                    "When searching for rentals, always select 'Pronájem' button.",
                    "Ensure Prague ('Praha') is correctly selected in the locality autocomplete dropdown."
                ]
            }
        },
        {
            "command_text": "On sreality.cz, apply filters for 'Balkón' and 'Terasa' for apartments.",
            "client_context": {
                "client_id": "sreality",
                "rules": [
                    "Always click 'Souhlasím' on cookie consent banners.",
                    "When searching for rentals, always select 'Pronájem' button.",
                    "Ensure Prague ('Praha') is correctly selected in the locality autocomplete dropdown."
                ]
            }
        },
        {
            "command_text": "Open the first apartment listing on sreality.cz and check if the description contains 'suterén'. If so, report it as rejected.",
            "client_context": {
                "client_id": "sreality",
                "rules": [
                    "Always click 'Souhlasím' on cookie consent banners.",
                    "When searching for rentals, always select 'Pronájem' button.",
                    "Ensure Prague ('Praha') is correctly selected in the locality autocomplete dropdown."
                ]
            }
        }
    ]

    print("=" * 60)
    print("STARTING E2E SREALITY MASTER SUITE")
    print("=" * 60)

    if not check_local_api_running():
        print("ERROR: Local API server is not running on port 8764.")
        print("Please ensure that main.py is running and logged in before executing test_e2e.py")
        return

    results = []

    for i, cmd_obj in enumerate(commands, 1):
        cmd = cmd_obj["command_text"]
        client_context = cmd_obj.get("client_context")
        doc_id = f"e2e_test_run_{uuid.uuid4().hex[:8]}"
        print(f"\n[{i}/{len(commands)}] Queueing command: {cmd}")
        print(f"Tracking session ID: {doc_id}")

        start_time = time.time()

        # Enqueue the command via local API
        payload_dict = {
            "doc_id": doc_id,
            "command_text": cmd
        }
        if client_context:
            payload_dict["client_context"] = client_context

        payload = json.dumps(payload_dict).encode('utf-8')

        req = urllib.request.Request(f"{LOCAL_API_URL}/run_command", data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            response = urllib.request.urlopen(req)
            resp_data = json.loads(response.read().decode())
            if resp_data.get("status") != "queued":
                print(f"Failed to queue command. API returned: {resp_data}")
                continue
        except Exception as e:
            print(f"Failed to queue command. Error: {e}")
            continue

        # Wait for the task to finish by polling status
        status = "pending"
        while status not in ["completed", "failed"]:
            time.sleep(2)
            try:
                status_req = urllib.request.Request(f"{LOCAL_API_URL}/status/{doc_id}")
                status_response = urllib.request.urlopen(status_req)
                status_data = json.loads(status_response.read().decode())
                status = status_data.get("status", "unknown")
                if status == "AWAITING_HUMAN_INPUT":
                    print("Waiting for human Ghost Click...")
            except Exception as e:
                print(f"Failed to get status. Error: {e}")
                break

        end_time = time.time()
        elapsed = end_time - start_time

        print(f"-> Command finished in {elapsed:.2f} seconds. Final Status: {status}")

        results.append({
            "command": cmd,
            "elapsed": elapsed,
            "status": status
        })

        # Give the system a brief moment before the next test
        time.sleep(2)

    print("\n" + "=" * 60)
    print("E2E TEST HARNESS SUMMARY")
    print("=" * 60)
    for res in results:
        print(f"- {res['command']}: {res['status']} ({res['elapsed']:.2f}s)")

    print("=" * 60)

if __name__ == "__main__":
    print("Note: Make sure your desktop client (main.py) is actively running and logged in.")
    test_harness()
