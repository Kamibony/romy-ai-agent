import sys
import os
import time
import logging
import threading
import uuid
import datetime

# Configure logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_harness():
    """
    E2E Test Harness:
    Automatically feeds 5 distinct commands targeting generic websites to the agent queue.
    Logs success/failure and execution time of each.
    """
    commands = [
        "Navigate to wikipedia.org and search for 'Artificial Intelligence'",
        "Navigate to github.com and search for 'tensorflow'",
        "Navigate to amazon.com and search for 'laptop'",
        "Navigate to news.ycombinator.com and click the first article",
        "Navigate to duckduckgo.com and search for 'OpenAI'"
    ]

    print("=" * 60)
    print("STARTING E2E TEST HARNESS FOR UNIVERSAL CAPABILITY")
    print("=" * 60)

    # We import inside the function to avoid ModuleNotFoundError when running via `python test_e2e.py` without requirements
    try:
        from client.agent import COMMAND_QUEUE, agent_worker_loop, run_remote_agent_loop, set_firebase_token, firestore_get_document
        from client.local_bridge import bridge
    except ImportError as e:
        print(f"Skipping actual test execution due to missing dependencies: {e}")
        print("To run this test, activate the environment and install requirements.txt")
        return

    # Start the local bridge
    bridge.start()

    worker_thread = threading.Thread(target=agent_worker_loop, daemon=True)
    worker_thread.start()

    results = []

    for i, cmd in enumerate(commands, 1):
        doc_id = f"e2e_test_run_{uuid.uuid4().hex[:8]}"
        print(f"\n[{i}/{len(commands)}] Queueing command: {cmd}")
        print(f"Tracking session ID: {doc_id}")

        start_time = time.time()

        # Enqueue the command
        COMMAND_QUEUE.put({
            "type": "remote",
            "doc_id": doc_id,
            "command_text": cmd,
            "audio_b64": ""
        })

        # Wait for the task to finish.
        COMMAND_QUEUE.join()

        end_time = time.time()
        elapsed = end_time - start_time

        status = "unknown"
        try:
            doc = firestore_get_document("remote_commands", doc_id)
            if doc:
                status = doc.get("status", "unknown")
        except Exception:
            pass

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
    print("Note: Make sure your desktop client is logged in or you set a valid CURRENT_TOKEN")
    test_harness()
