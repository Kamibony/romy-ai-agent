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

    def poll_all_statuses(self, doc_ids, timeout_secs=300):
        start_time = time.time()
        statuses = {doc_id: "pending" for doc_id in doc_ids}
        last_status_change_times = {doc_id: time.time() for doc_id in doc_ids}
        active_docs = set(doc_ids)

        while active_docs and (time.time() - start_time) < timeout_secs:
            time.sleep(2)

            # Use a list to iterate over safely while modifying the set
            for doc_id in list(active_docs):
                try:
                    status_req = urllib.request.Request(f"{LOCAL_API_URL}/status/{doc_id}")
                    req_start = time.time()
                    status_response = urllib.request.urlopen(status_req, timeout=5)
                    req_end = time.time()

                    status_data = json.loads(status_response.read().decode())
                    new_status = status_data.get("status", "unknown")

                    current_status = statuses[doc_id]

                    if new_status != current_status:
                        duration = time.time() - last_status_change_times[doc_id]
                        logging.info(f"[{doc_id}] Status changed to '{new_status}' after {duration:.2f}s. Ext. Response Time: {req_end - req_start:.4f}s")

                        if duration >= 1.5:
                            logging.info(f"[{doc_id}] -> Validation: 1.5s native wait likely respected (Duration: {duration:.2f}s)")
                        else:
                            logging.warning(f"[{doc_id}] -> Validation Warning: Status changed in {duration:.2f}s (< 1.5s). Wait may have been skipped.")

                        last_status_change_times[doc_id] = time.time()
                        statuses[doc_id] = new_status

                    if new_status == "AWAITING_HUMAN_INPUT":
                        logging.warning(f"ask_human triggered for {doc_id}!")
                        self.diagnostics["ask_human_triggers"] += 1
                        self.diagnostics["ask_human_timestamps"].append(time.time())

                        threading.Thread(target=self.trigger_ghost_click, daemon=True).start()
                        time.sleep(4)

                    if new_status in ["completed", "failed"]:
                        active_docs.remove(doc_id)
                        if new_status == "failed":
                            logging.error(f"[{doc_id}] Task Failed. Checking for 'No active session tab' errors...")
                            self.diagnostics["no_active_session_errors"] += 1

                except urllib.error.URLError as e:
                    logging.error(f"WS/Connection Error to API while polling {doc_id}: {e}")
                    self.diagnostics["ws_errors"] += 1
                except Exception as e:
                    logging.error(f"Failed to poll status for {doc_id}. Error: {e}")
                    self.diagnostics["ws_errors"] += 1

        if active_docs:
            logging.error(f"Timeout reached. Active docs remaining: {active_docs}")

        return statuses

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
            "Navigate to example.com and use JavaScript to read the exact text of the main h1 heading.",
            "Navigate to google.com, type 'AI Chrome Agents' into the search box, and press Enter.",
            "Navigate to wikipedia.org and scroll down the page."
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

        if doc_ids:
            statuses = self.poll_all_statuses(doc_ids, timeout_secs=300)
            for doc_id, status in statuses.items():
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

        docs_to_track = []
        if doc_id_nav:
            docs_to_track.append(doc_id_nav)
        if doc_id_state:
            docs_to_track.append(doc_id_state)

        if docs_to_track:
            logging.info(f"Tracking {len(docs_to_track)} commands for Scenario B...")
            statuses = self.poll_all_statuses(docs_to_track, timeout_secs=300)
            for doc_id, status in statuses.items():
                logging.info(f"Command {doc_id} finished with status: {status}")

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
