import os
import time
import logging
import uuid
import json
import urllib.request
import urllib.error
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LOCAL_API_URL = "http://127.0.0.1:8764/api"

class StressTestRunner:
    def __init__(self):
        self.diagnostics = {
            "ask_human_triggers": 0,
            "ws_errors": 0,
            "no_active_session_errors": 0,
            "timing_data": [],
            "ask_human_timestamps": []
        }

    def trigger_ghost_click(self):
        try:
            logging.info("Injecting human guidance string to bypass ask_human (after 3s timeout)...")
            time.sleep(3)
            # Use xpath to inject a string response instead of coordinates
            payload = json.dumps({"xpath": "Continue with the next logical step"}).encode('utf-8')
            req = urllib.request.Request(f"{LOCAL_API_URL}/human_guidance", data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            start_t = time.time()
            response = urllib.request.urlopen(req, timeout=5)
            end_t = time.time()
            logging.info(f"Ghost click injected. HTTP {response.getcode()}. Extension Response Time: {end_t - start_t:.4f}s")
        except urllib.error.HTTPError as e:
            logging.error(f"Failed to inject ghost click (HTTP Error): {e}")
        except Exception as e:
            logging.error(f"Failed to inject ghost click: {e}")
            self.diagnostics["ws_errors"] += 1

    def poll_status(self, doc_id, timeout_secs=120):
        status = "pending"
        start_time = time.time()
        last_status_change_time = time.time()

        while status not in ["completed", "failed"] and (time.time() - start_time) < timeout_secs:
            time.sleep(2)
            try:
                status_req = urllib.request.Request(f"{LOCAL_API_URL}/status/{doc_id}")
                req_start = time.time()
                status_response = urllib.request.urlopen(status_req, timeout=5)
                req_end = time.time()

                status_data = json.loads(status_response.read().decode())
                new_status = status_data.get("status", "unknown")

                # Check for "No active session tab" or other errors embedded in status if possible
                # (Assuming agent or bridge logs it to the API response, though usually it just says failed)
                # But we at least track WS connection status via successful polling vs timeouts
                if new_status != status:
                    duration = time.time() - last_status_change_time
                    logging.info(f"[{doc_id}] Status changed to '{new_status}' after {duration:.2f}s. Ext. Response Time: {req_end - req_start:.4f}s")

                    # If duration is approximately >= 1.5s, it roughly validates the native stabilization wait in extension
                    if duration >= 1.5:
                        logging.info(f"[{doc_id}] -> Validation: 1.5s native wait likely respected (Duration: {duration:.2f}s)")
                    else:
                        logging.warning(f"[{doc_id}] -> Validation Warning: Status changed in {duration:.2f}s (< 1.5s). Wait may have been skipped.")

                    last_status_change_time = time.time()
                    status = new_status

                if status == "AWAITING_HUMAN_INPUT":
                    logging.warning(f"ask_human triggered for {doc_id}!")
                    self.diagnostics["ask_human_triggers"] += 1
                    self.diagnostics["ask_human_timestamps"].append(time.time())

                    # Launch background thread to send ghost click without blocking the polling loop immediately
                    threading.Thread(target=self.trigger_ghost_click, daemon=True).start()

                    # Sleep to avoid multiple threads being spawned for the same AWAITING_HUMAN_INPUT
                    time.sleep(4)

            except urllib.error.URLError as e:
                logging.error(f"WS/Connection Error to API while polling {doc_id}: {e}")
                self.diagnostics["ws_errors"] += 1
            except Exception as e:
                logging.error(f"Failed to poll status for {doc_id}. Error: {e}")
                self.diagnostics["ws_errors"] += 1

        if status == "failed":
            logging.error(f"[{doc_id}] Task Failed. Checking for 'No active session tab' errors...")
            # We assume failure could be due to missing tab; increment diagnostic counter
            self.diagnostics["no_active_session_errors"] += 1

        return status

    def enqueue_command(self, cmd_text, client_context=None):
        doc_id = f"stress_test_{uuid.uuid4().hex[:8]}"
        payload_dict = {
            "doc_id": doc_id,
            "command_text": cmd_text
        }
        if client_context:
            payload_dict["client_context"] = client_context

        payload = json.dumps(payload_dict).encode('utf-8')

        try:
            req = urllib.request.Request(f"{LOCAL_API_URL}/run_command", data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            start_t = time.time()
            response = urllib.request.urlopen(req, timeout=10)
            end_t = time.time()
            resp_data = json.loads(response.read().decode())

            enqueue_time = end_t - start_t

            if resp_data.get("status") != "queued":
                logging.error(f"Failed to queue {cmd_text}: {resp_data}")
                return None, enqueue_time

            return doc_id, enqueue_time
        except Exception as e:
            logging.error(f"Error queueing command {cmd_text}: {e}")
            self.diagnostics["ws_errors"] += 1
            return None, 0

    def run_scenario_a(self):
        logging.info("=== Starting Scenario A: 'The Rapid Fire' ===")
        # We will rapidly queue several commands to see if the WS bridge buffers them and stays alive.
        commands = [
            "Navigate to https://example.com and check the title.",
            "Scroll down slightly.",
            "Click anywhere on the page.",
            "Scroll up slightly.",
            "Type 'Hello world' in any input field if it exists."
        ]

        doc_ids = []
        for i, cmd in enumerate(commands):
            logging.info(f"Rapid queueing command {i+1}/{len(commands)}: {cmd}")
            doc_id, enqueue_t = self.enqueue_command(cmd)
            if doc_id:
                doc_ids.append(doc_id)
                self.diagnostics["timing_data"].append({"cmd": cmd, "enqueue_time": enqueue_t})
            # Sleep very briefly to simulate rapid requests, but not instantly 0
            time.sleep(0.1)

        logging.info(f"Queued {len(doc_ids)} commands. Now tracking them...")

        for doc_id in doc_ids:
            logging.info(f"Tracking doc {doc_id}...")
            # We track them sequentially, but the agent processes them from queue.
            # Timeout is longer since they are queued up.
            status = self.poll_status(doc_id, timeout_secs=180)
            logging.info(f"Command {doc_id} finished with status: {status}")

        logging.info("=== Scenario A Completed ===")

    def run_scenario_b(self):
        logging.info("=== Starting Scenario B: 'The Navigation Stress' ===")
        # Navigate to a heavy site, and immediately follow up with another task that forces a GET_STATE.
        # We queue them very close together to see if the second one fails or throws WS errors.

        cmd_nav = "Navigate to https://news.ycombinator.com/ and wait for it to load."
        cmd_state = "Check the first story title on https://news.ycombinator.com/."

        logging.info(f"Queueing heavy navigation: {cmd_nav}")
        doc_id_nav, _ = self.enqueue_command(cmd_nav)

        # Enqueue state check command immediately
        logging.info(f"Immediately queueing state check: {cmd_state}")
        doc_id_state, _ = self.enqueue_command(cmd_state)

        if doc_id_nav:
            logging.info(f"Tracking heavy navigation {doc_id_nav}...")
            status_nav = self.poll_status(doc_id_nav, timeout_secs=120)
            logging.info(f"Heavy navigation finished with status: {status_nav}")

        if doc_id_state:
            logging.info(f"Tracking immediate state check {doc_id_state}...")
            status_state = self.poll_status(doc_id_state, timeout_secs=120)
            logging.info(f"State check finished with status: {status_state}")

        logging.info("=== Scenario B Completed ===")

    def print_diagnostics(self):
        logging.info("=" * 60)
        logging.info("STRESS TEST DIAGNOSTIC REPORT")
        logging.info("=" * 60)
        logging.info(f"Total ask_human triggers bypassed: {self.diagnostics['ask_human_triggers']}")
        logging.info(f"Total WS/Network queueing errors encountered: {self.diagnostics['ws_errors']}")
        logging.info(f"Total 'No active session tab' errors suspected/logged: {self.diagnostics['no_active_session_errors']}")

        logging.info("--- Command Queueing Performance ---")
        for data in self.diagnostics["timing_data"]:
            logging.info(f"Command: {data['cmd'][:30]}... | Queue Time: {data['enqueue_time']:.4f}s")

        logging.info("=" * 60)

    def run(self):
        try:
            self.run_scenario_a()
            time.sleep(2)
            self.run_scenario_b()
        except KeyboardInterrupt:
            logging.warning("Stress test interrupted by user.")
        finally:
            self.print_diagnostics()

if __name__ == "__main__":
    runner = StressTestRunner()
    runner.run()
