import sys
import os
import time
import logging
import uuid
import json
import urllib.request
import urllib.error
import glob
import re
import argparse

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

def validate_outcome(doc_id, expected_outcome):
    """
    Validates the actual outcome by reading the last flight record JSON file.
    """
    if not expected_outcome:
        return True, "No validation criteria specified."

    user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RomyAgentBrowserData", "flight_records", doc_id)
    if not os.path.exists(user_data_dir):
        return False, "Flight records directory not found."

    record_files = glob.glob(os.path.join(user_data_dir, "record_*.json"))
    if not record_files:
        return False, "No flight records found."

    # Sort files by iteration to get the latest one
    # Assuming filenames are formatted as record_0_timestamp.json, etc.
    def get_iteration(filename):
        try:
            return int(os.path.basename(filename).split('_')[1])
        except (IndexError, ValueError):
            return -1

    record_files.sort(key=get_iteration)
    last_record_file = record_files[-1]

    try:
        with open(last_record_file, "r", encoding="utf-8") as f:
            last_record = json.load(f)
    except Exception as e:
        return False, f"Failed to read last flight record: {e}"

    actual_url = last_record.get("prompt_payload", {}).get("current_url", "")
    actions_executed = last_record.get("action_executed", [])

    # Extract replies from all records just in case it replied earlier
    replies = []
    urls_visited = []
    for file in record_files:
        try:
            with open(file, "r", encoding="utf-8") as f:
                rec = json.load(f)
                url = rec.get("prompt_payload", {}).get("current_url", "")
                if url:
                    urls_visited.append(url)
                for act in rec.get("action_executed", []):
                    if isinstance(act, dict) and str(act.get("action", "")).upper() == "REPLY":
                        replies.append(str(act.get("text", "")))
        except:
            pass

    rule_type = expected_outcome.get("type")

    if rule_type == "final_url_match":
        match_str = expected_outcome.get("value", "")
        if match_str in actual_url:
            return True, f"Final URL matches '{match_str}'"
        return False, f"Final URL '{actual_url}' does not contain '{match_str}'"

    elif rule_type == "url_visited":
        match_str = expected_outcome.get("value", "")
        for url in urls_visited:
            if match_str in url:
                return True, f"Visited URL matching '{match_str}'"
        return False, f"Never visited a URL containing '{match_str}'"

    elif rule_type == "reply_match":
        match_str = expected_outcome.get("value", "")
        for reply in replies:
            if match_str.lower() in reply.lower():
                return True, f"Reply matched '{match_str}'"
        return False, f"No reply contained '{match_str}'. Replies: {replies}"

    elif rule_type == "regex_reply":
        pattern = expected_outcome.get("value", "")
        for reply in replies:
            if re.search(pattern, reply):
                return True, f"Reply matched regex '{pattern}'"
        return False, f"No reply matched regex '{pattern}'. Replies: {replies}"

    return False, f"Unknown validation rule type: {rule_type}"

def test_harness(run_target=None):
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
            },
            "expected_outcome": {
                "type": "regex_reply",
                "value": r"\d+,\d{3}" # Regex to match format like 25,123
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
            },
            "expected_outcome": {
                "type": "url_visited",
                "value": "seznam.cz"
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
            },
            "expected_outcome": {
                "type": "url_visited",
                "value": "notebooky"
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
            },
            "expected_outcome": {
                "type": "url_visited",
                "value": "firmy.cz"
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
            },
            "expected_outcome": {
                "type": "reply_match",
                "value": "Ministerstvo financí"
            }
        },
        {
            "name": "Stress Test (Sreality.cz)",
            "command_text": "Přejdi na sreality.cz. Nastav vyhledávání na 'Prodej', 'Byty' a lokalitu 'Brno' a dej vyhledat. Poté ve filtrech nastav dispozici na 3+kk a maximální cenu 8 000 000 Kč. Z výsledků klikni na inzerát, který nabízí balkón. Z jeho detailu mi extrahuj užitnou plochu a energetickou náročnost. Nakonec otevři kontaktní formulář, vyplň jméno 'Test Romy' a e-mail 'test@romy.ai'. Formulář NEODESÍLEJ, ale najdi křížek a modální okno zavři.",
            "client_context": {
                "client_id": "sreality_stress_test",
                "rules": [
                    "Accept any cookie/consent dialogs.",
                    "Do NOT submit the contact form.",
                    "Ensure you extract and reply with the area and energy efficiency."
                ]
            },
            "expected_outcome": {
                "type": "regex_reply",
                "value": r"\d+\s*m2" # Looking for area in square meters
            }
        }
    ]

    if run_target is not None:
        try:
            # If target is integer index
            idx = int(run_target) - 1
            if 0 <= idx < len(commands):
                commands = [commands[idx]]
            else:
                print(f"Error: Target index {run_target} out of range.")
                return
        except ValueError:
            # If target is string match
            filtered_commands = [c for c in commands if run_target.lower() in c["name"].lower()]
            if filtered_commands:
                commands = filtered_commands
            else:
                print(f"Error: No scenarios match '{run_target}'.")
                return

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
        expected_outcome = cmd_obj.get("expected_outcome")
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

        # Validation step
        validation_passed = False
        validation_reason = ""
        if status == "completed":
            validation_passed, validation_reason = validate_outcome(doc_id, expected_outcome)
            if not validation_passed:
                status = f"failed (validation: {validation_reason})"

        print(f"-> Scenario finished in {elapsed:.2f} seconds. Final Status: {status}")
        if validation_reason:
            print(f"Validation: {validation_reason}")

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
    parser = argparse.ArgumentParser(description="Run E2E tests via Local API.")
    parser.add_argument("--run", type=str, help="Index or partial name of the scenario to run.")
    args = parser.parse_args()

    print("Note: Make sure your desktop client (main.py) is actively running and logged in.")
    test_harness(run_target=args.run)
