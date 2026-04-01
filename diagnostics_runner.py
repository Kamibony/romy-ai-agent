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
from datetime import datetime

# Configure logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCAL_API_URL = "http://127.0.0.1:8764/api"

def check_local_api_running():
    try:
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

def get_chaos_scenarios():
    return [
        {
            "name": "Chaos: Dynamic Web Resilience (Aggressive Overlays & JS)",
            "command_text": "Navigate to www.alza.cz. Reject or accept all pop-ups (cookies, discounts, notifications). Find the cheapest notebook and add it to the cart. Then go to the cart and tell me the total price.",
            "client_context": {
                "client_id": "chaos_web_resilience",
                "rules": [
                    "Dismiss any GDPR or discount modals immediately before proceeding.",
                    "Search for 'notebook'.",
                    "Sort by cheapest if possible.",
                    "Add the first item to the cart.",
                    "Navigate to the cart.",
                    "Read the total price."
                ]
            }
        },
        {
            "name": "Chaos: Spatial OS Interaction (Continuous Drag/Draw)",
            "command_text": "Open the Paint application (MS Paint) in Windows. Draw a square or circle in the middle of the canvas using the mouse. Then open the Notepad application and write 'Drawing completed' into it.",
            "client_context": {
                "client_id": "chaos_os_spatial",
                "rules": [
                    "Open MS Paint.",
                    "Click and drag on the canvas to draw something.",
                    "Open Notepad.",
                    "Type 'Drawing completed'."
                ]
            }
        },
        {
            "name": "Chaos: Rapid Context Ping-Pong (Web -> OS -> Web)",
            "command_text": "Navigate to google.com/finance and find the current price of Apple stock (AAPL). Copy this value. Open the Calculator application in Windows and multiply this value by 10. Copy the result. Go back to the browser to google.com, paste the result into the search bar, and hit search.",
            "client_context": {
                "client_id": "chaos_ping_pong",
                "rules": [
                    "Extract AAPL stock price from Google Finance.",
                    "Open Windows Calculator.",
                    "Multiply the price by 10.",
                    "Copy the calculated result.",
                    "Navigate to Google.com in the browser.",
                    "Paste the result and search."
                ]
            }
        }
    ]

def analyze_flight_records(doc_id):
    """
    Parses the local flight records for a given session and returns a summary dict
    containing telemetry, errors, steps taken, and screenshots paths.
    """
    user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RomyAgentBrowserData", "flight_records", doc_id)
    if not os.path.exists(user_data_dir):
        return {"error": "Flight records directory not found.", "steps": 0, "telemetry": [], "errors": [], "circuit_breakers": 0}

    record_files = glob.glob(os.path.join(user_data_dir, "record_*.json"))
    if not record_files:
        return {"error": "No flight records found.", "steps": 0, "telemetry": [], "errors": [], "circuit_breakers": 0}

    def get_iteration(filename):
        try:
            return int(os.path.basename(filename).split('_')[1].split('.')[0])
        except (IndexError, ValueError):
            return -1

    record_files.sort(key=get_iteration)

    analysis = {
        "steps": len(record_files),
        "telemetry": [],
        "errors": [],
        "circuit_breakers": 0,
        "final_url": "Unknown",
        "last_screenshot": None
    }

    for idx, file in enumerate(record_files):
        try:
            with open(file, "r", encoding="utf-8") as f:
                rec = json.load(f)

                sys_state = rec.get("system_state", {})
                prompt_payload = rec.get("prompt_payload", {})
                actions = rec.get("action_executed", [])

                # Capture URL
                if "current_url" in prompt_payload:
                    analysis["final_url"] = prompt_payload["current_url"]

                # Check for errors in actions
                if isinstance(actions, list):
                    for act in actions:
                        if isinstance(act, dict) and "ERROR" in str(act.get("action", "")).upper():
                            analysis["errors"].append(f"Step {idx}: {act.get('error', 'Unknown Error')}")

                # Check for circuit breaker triggers (if sub_task_iteration resets without SUB_TASK_COMPLETE or is very high)
                iteration = sys_state.get("sub_task_iteration", 0)
                if iteration >= 3:
                    analysis["circuit_breakers"] += 1

                telemetry_entry = {
                    "iteration": idx,
                    "intent": sys_state.get("intent", "UNKNOWN"),
                    "sub_task": prompt_payload.get("sub_task", "Unknown"),
                    "actions": [a.get("action") for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []
                }
                analysis["telemetry"].append(telemetry_entry)

        except Exception as e:
            analysis["errors"].append(f"Failed to read record {file}: {e}")

    # Look for screenshots
    screenshot_files = glob.glob(os.path.join(user_data_dir, "screenshot_*.png"))
    if screenshot_files:
        screenshot_files.sort(key=get_iteration)
        analysis["last_screenshot"] = screenshot_files[-1]

    return analysis

def generate_markdown_report(results, run_name):
    """Generates a Markdown report from the test results."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"diagnostic_run_{timestamp}.md"

    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(f"# Unattended Chaos Diagnostics Report\n")
        f.write(f"**Run Name:** {run_name}\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## Summary Matrix\n")
        f.write("| Scenario | Status | Time (s) | Steps | Final URL |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- |\n")

        for res in results:
            analysis = res.get("analysis", {})
            steps = analysis.get("steps", 0)
            final_url = analysis.get("final_url", "Unknown")
            f.write(f"| {res['name']} | **{res['status']}** | {res['elapsed']:.2f} | {steps} | {final_url} |\n")

        f.write("\n---\n\n")
        f.write("## Detailed Autopsies\n\n")

        for res in results:
            analysis = res.get("analysis", {})
            f.write(f"### {res['name']}\n")
            f.write(f"- **Command:** `{res['command']}`\n")
            f.write(f"- **Status:** {res['status']}\n")
            f.write(f"- **Execution Time:** {res['elapsed']:.2f} seconds\n")
            f.write(f"- **Total Steps:** {analysis.get('steps', 0)}\n")
            f.write(f"- **Circuit Breaker Triggers:** {analysis.get('circuit_breakers', 0)}\n")

            if analysis.get("errors"):
                f.write("- **Errors Encountered:**\n")
                for err in analysis["errors"]:
                    f.write(f"  - {err}\n")
            else:
                f.write("- **Errors Encountered:** None\n")

            f.write("\n#### Execution Telemetry:\n")
            f.write("```json\n")
            f.write(json.dumps(analysis.get("telemetry", []), indent=2))
            f.write("\n```\n")

            last_ss = analysis.get("last_screenshot")
            if last_ss:
                f.write(f"\n- **Final State Screenshot Saved At:** `{last_ss}`\n")

            f.write("\n---\n")

    return report_filename

def run_diagnostics(strict_autonomous=True):
    print("=" * 80)
    print("STARTING UNATTENDED CHAOS DIAGNOSTICS")
    print("=" * 80)

    if not check_local_api_running():
        print("ERROR: Local API server is not running on port 8764.")
        print("Please ensure main.py is running.")
        return

    commands = get_chaos_scenarios()
    results = []

    for i, cmd_obj in enumerate(commands, 1):
        name = cmd_obj["name"]
        cmd = cmd_obj["command_text"]
        client_context = cmd_obj.get("client_context")

        if strict_autonomous:
            if not client_context:
                client_context = {"rules": []}
            # Add a system-level rule to never ask for human help
            client_context["rules"].append("STRICT_AUTONOMOUS_MODE: Never output the ASK_HUMAN action. If you are stuck, fail gracefully with an ERROR action instead.")

        doc_id = f"chaos_test_{uuid.uuid4().hex[:8]}"

        print(f"\n[{i}/{len(commands)}] Running Scenario: {name}")
        print(f"Tracking session ID: {doc_id}")

        start_time = time.time()
        status = "failed (initialization)"
        timeout_seconds = 300 # 5 minutes hard stop

        try:
            payload_dict = {
                "doc_id": doc_id,
                "command_text": cmd,
                "client_context": client_context
            }
            payload = json.dumps(payload_dict).encode('utf-8')

            req = urllib.request.Request(f"{LOCAL_API_URL}/run_command", data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            response = urllib.request.urlopen(req)
            resp_data = json.loads(response.read().decode())

            if resp_data.get("status") != "queued":
                print(f"Failed to queue command. API returned: {resp_data}")
                status = "failed (queue error)"
            else:
                status = "pending"
                last_iteration = -1
                last_agent_state = "unknown"
                stagnation_timer = time.time()
                stagnation_timeout = 60 # 60 seconds without an iteration increment = stagnation

                while status not in ["completed", "failed"]:
                    time.sleep(2)

                    elapsed_total = time.time() - start_time
                    if elapsed_total > timeout_seconds:
                        print(f"WATCHDOG TRIGGERED: Global scenario timeout ({timeout_seconds}s) reached. Aborting scenario.")
                        status = "failed (TIMEOUT)"
                        try:
                            urllib.request.urlopen(urllib.request.Request(f"{LOCAL_API_URL}/reset", method='POST'), timeout=2)
                        except Exception as e:
                            print(f"Failed to send reset command to agent: {e}")
                        break

                    try:
                        status_req = urllib.request.Request(f"{LOCAL_API_URL}/status/{doc_id}")
                        status_response = urllib.request.urlopen(status_req)
                        status_data = json.loads(status_response.read().decode())
                        status = status_data.get("status", "unknown")

                        iteration = status_data.get("iteration", 0)
                        agent_state = status_data.get("agent_state", "unknown")

                        # Stagnation check
                        if iteration > last_iteration or agent_state != last_agent_state:
                            last_iteration = iteration
                            last_agent_state = agent_state
                            stagnation_timer = time.time()
                        elif time.time() - stagnation_timer > stagnation_timeout:
                            print(f"WATCHDOG TRIGGERED: Stagnation detected ({stagnation_timeout}s without state or iteration progress). Agent stuck in state: {agent_state}, iteration: {iteration}. Aborting scenario.")
                            status = "failed (STAGNATION/DEADLOCK)"
                            try:
                                urllib.request.urlopen(urllib.request.Request(f"{LOCAL_API_URL}/reset", method='POST'), timeout=2)
                            except Exception as e:
                                print(f"Failed to send reset command to agent: {e}")
                            break

                        # Strict Autonomous Bypass Check
                        if status == "AWAITING_HUMAN_INPUT":
                            if strict_autonomous:
                                print("HITL Suspension detected. Strict Autonomous Mode active -> Failing scenario immediately.")
                                status = "failed (HITL bypassed)"
                                try:
                                    urllib.request.urlopen(urllib.request.Request(f"{LOCAL_API_URL}/reset", method='POST'), timeout=2)
                                except Exception as e:
                                    print(f"Failed to send reset command to agent: {e}")
                                break
                            else:
                                print("Waiting for human input...")
                                continue
                    except Exception as e:
                        print(f"Failed to poll status: {e}")
                        status = "failed (poll error)"
                        try:
                            urllib.request.urlopen(urllib.request.Request(f"{LOCAL_API_URL}/reset", method='POST'), timeout=2)
                        except Exception as inner_e:
                            pass
                        break
        except Exception as e:
            print(f"Exception during scenario: {e}")
            status = f"failed (exception: {e})"
            try:
                urllib.request.urlopen(urllib.request.Request(f"{LOCAL_API_URL}/reset", method='POST'), timeout=2)
            except Exception as inner_e:
                pass

        elapsed = time.time() - start_time

        # Analyze flight records
        analysis = analyze_flight_records(doc_id)

        # Refactor Semantic Diagnostic Truthfulness
        if status == "completed":
            if analysis.get("circuit_breakers", 0) > 0:
                status = "failed (circuit breaker triggered)"
            elif analysis.get("errors"):
                status = "failed (execution errors)"

        print(f"-> Finished in {elapsed:.2f}s. Final Status: {status}")

        results.append({
            "name": name,
            "command": cmd,
            "elapsed": elapsed,
            "status": status,
            "analysis": analysis
        })

        # Cooldown between scenarios
        time.sleep(3)

    print("\nGenerating Unified Diagnostic Dump...")
    report_file = generate_markdown_report(results, run_name="Phase 5 Chaos Diagnostics")
    print(f"Diagnostics complete. Report generated at: {report_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Unattended Chaos Diagnostics.")
    parser.add_argument("--no-strict", action="store_true", help="Disable strict autonomous mode (allow HITL).")
    args = parser.parse_args()

    run_diagnostics(strict_autonomous=not args.no_strict)
