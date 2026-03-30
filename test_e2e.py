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
            "name": "Data Extraction (Czech National Bank)",
            "command_text": "Přejdi na www.cnb.cz. Najdi aktuální kurz Eura (EUR) vůči české koruně a hodnotu mi napiš.",
            "client_context": {
                "client_id": "cnb_data_extraction",
                "rules": [
                    "Always click 'Souhlasím' on cookie consent banners if present.",
                    "Wait for the exchange rate table to load.",
                    "Extract the EUR/CZK exchange rate."
                ]
            }
        },
        {
            "name": "Local Search Navigation (Seznam.cz)",
            "command_text": "Přejdi na seznam.cz, vyhledej téma 'AI v byznysu' a klikni na první zajímavý článek.",
            "client_context": {
                "client_id": "seznam_search",
                "rules": [
                    "Accept any Seznam consent dialogs.",
                    "Use the main search bar to search for 'AI v byznysu'.",
                    "Click on one of the top organic results."
                ]
            }
        },
        {
            "name": "Complex Menu Navigation (Alza.cz)",
            "command_text": "Přejdi na alza.cz. Bez použití vyhledávacího pole klikni v hlavním menu na kategorii 'Počítače a notebooky' a následně vyhledej sekci pro Notebooky.",
            "client_context": {
                "client_id": "alza_menu",
                "rules": [
                    "Accept any Alza cookie/consent dialogs.",
                    "Do NOT use the search bar. You must use the navigation menu.",
                    "Navigate through the category tree: Počítače a notebooky -> Notebooky."
                ]
            }
        },
        {
            "name": "Multi-Field Form Entry (Firmy.cz)",
            "command_text": "Přejdi na firmy.cz. Do pole 'Co hledáte' napiš 'IT služby' a do pole 'Kde' napiš 'Praha'. Pak stiskni tlačítko Hledat.",
            "client_context": {
                "client_id": "firmy_form",
                "rules": [
                    "Accept cookie banners.",
                    "Fill 'Co hledáte' with 'IT služby'.",
                    "Fill 'Kde' with 'Praha'.",
                    "Submit the form."
                ]
            }
        },
        {
            "name": "The Architect's Choice: Aggressive Modals & Legacy B2B (Justice.cz)",
            "command_text": "Přejdi na justice.cz (Veřejný rejstřík). Zkus vyhledat IČO '00006947' (Ministerstvo financí). Zkopíruj mi přesný název subjektu z výsledků hledání.",
            "client_context": {
                "client_id": "justice_cz_legacy",
                "rules": [
                    "Handle any potential captchas or legacy UI elements carefully.",
                    "Navigate to the 'Veřejný rejstřík' (Public Register) section if not already there.",
                    "Enter IČO '00006947' into the search field and submit.",
                    "Extract the exact registered name from the complex HTML table result."
                ]
            }
        }
    ]

    print("=" * 80)
    print("STARTING AUTOMATED E2E TEST SUITE (CZECH B2B MARKET DEMO)")
    print("=" * 80)

    if not check_local_api_running():
        print("ERROR: Local API server is not running on port 8764.")
        print("Please ensure that main.py is running and logged in before executing test_e2e.py")
        return

    results = []

    for i, cmd_obj in enumerate(commands, 1):
        name = cmd_obj["name"]
        cmd = cmd_obj["command_text"]
        client_context = cmd_obj.get("client_context")
        doc_id = f"e2e_test_run_{uuid.uuid4().hex[:8]}"

        print(f"\n[{i}/{len(commands)}] Running Scenario: {name}")
        print(f"Command: {cmd}")
        print(f"Tracking session ID: {doc_id}")

        start_time = time.time()
        status = "failed (initialization)"
        elapsed = 0

        try:
            # Enqueue the command via local API
            payload_dict = {
                "doc_id": doc_id,
                "command_text": cmd
            }
            if client_context:
                payload_dict["client_context"] = client_context

            payload = json.dumps(payload_dict).encode('utf-8')

            req = urllib.request.Request(f"{LOCAL_API_URL}/run_command", data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            response = urllib.request.urlopen(req)
            resp_data = json.loads(response.read().decode())

            if resp_data.get("status") != "queued":
                print(f"Failed to queue command. API returned: {resp_data}")
                status = "failed (queue error)"
            else:
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
                        status = "failed (status poll error)"
                        break
        except Exception as e:
            print(f"Exception during scenario execution: {e}")
            status = f"failed (exception: {e})"

        end_time = time.time()
        elapsed = end_time - start_time

        print(f"-> Scenario finished in {elapsed:.2f} seconds. Final Status: {status}")

        results.append({
            "name": name,
            "command": cmd,
            "elapsed": elapsed,
            "status": status
        })

        # Give the system a brief moment before the next test
        time.sleep(2)

    print("\n" + "=" * 80)
    print("E2E TEST SUITE SUMMARY MATRIX")
    print("=" * 80)
    print(f"{'SCENARIO':<60} | {'STATUS':<15} | {'TIME'}")
    print("-" * 80)
    for res in results:
        name_trunc = res['name'][:57] + "..." if len(res['name']) > 60 else res['name']
        print(f"{name_trunc:<60} | {res['status']:<15} | {res['elapsed']:.2f}s")
    print("=" * 80)

    success_count = sum(1 for r in results if r['status'] == 'completed')
    total_count = len(results)
    print(f"Total Passed: {success_count} / {total_count}")
    print("=" * 80)

if __name__ == "__main__":
    print("Note: Make sure your desktop client (main.py) is actively running and logged in.")
    test_harness()
