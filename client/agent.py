import logging
import base64
import io
import time
import os
import re
import requests
import queue

import uiautomation as auto
import sounddevice as sd
from scipy.io.wavfile import write as wav_write
import pyautogui
from plyer import notification
try:
    import winsound
except ImportError:
    winsound = None
from typing import Dict, Any, Tuple

pyautogui.FAILSAFE = False

BACKEND_URL = os.environ.get("BACKEND_URL", "https://romy-backend-1049976869239.europe-west1.run.app/api/v1/agent/command")

CURRENT_TOKEN = None

COMMAND_QUEUE = queue.Queue()
ABORT_AGENT = False
PAUSE_AGENT = False

def toggle_pause() -> bool:
    """Toggles the pause state of the agent loops. Returns the new state."""
    global PAUSE_AGENT
    PAUSE_AGENT = not PAUSE_AGENT
    if PAUSE_AGENT:
        logging.info("Agent execution paused by user.")
    else:
        logging.info("Agent execution resumed by user.")
    return PAUSE_AGENT

def trigger_abort() -> None:
    """Sets the global abort flag to instantly stop the agent execution loop."""
    global ABORT_AGENT
    logging.critical("User requested emergency abort. Stopping agent loops...")
    ABORT_AGENT = True

def agent_worker_loop() -> None:
    """
    Main Loop running on the primary thread to process commands from the COMMAND_QUEUE.
    """
    global ABORT_AGENT
    logging.info("Starting Agent Worker Loop on primary thread...")
    while True:
        try:
            task = COMMAND_QUEUE.get(timeout=1.0)
            ABORT_AGENT = False # Reset abort flag on new task
            task_type = task.get("type")

            if task_type == "remote":
                doc_id = task.get("doc_id")
                command_text = task.get("command_text", "")
                audio_b64 = task.get("audio_b64", "")
                run_remote_agent_loop(doc_id, command_text, audio_b64)
            elif task_type == "voice":
                execute_voice_agent_loop()

            COMMAND_QUEUE.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logging.error(f"Error processing command from queue: {e}")

def set_firebase_token(token: str) -> None:
    """Sets the global Firebase token."""
    global CURRENT_TOKEN
    CURRENT_TOKEN = token

def firestore_update_document(collection: str, doc_id: str, updates: Dict[str, Any], delete_fields: list = None) -> None:
    """Updates a Firestore document using the REST API with retries for network resilience."""
    if not CURRENT_TOKEN:
        logging.error("Missing token, cannot update Firestore.")
        return

    url = f"https://firestore.googleapis.com/v1/projects/romy-ai-agent/databases/(default)/documents/{collection}/{doc_id}"

    fields = {}
    update_mask = []

    for key, val in updates.items():
        update_mask.append(key)
        if isinstance(val, str):
            fields[key] = {"stringValue": val}
        elif isinstance(val, bool):
            fields[key] = {"booleanValue": val}
        elif isinstance(val, int):
            fields[key] = {"integerValue": str(val)}
        elif isinstance(val, float):
            fields[key] = {"doubleValue": val}
        elif isinstance(val, dict):
            pass

    if delete_fields:
        for key in delete_fields:
            update_mask.append(key)

    params = []
    for mask in update_mask:
        params.append(f"updateMask.fieldPaths={mask}")

    query_string = "&".join(params)
    if query_string:
        url += "?" + query_string

    payload = {"name": f"projects/romy-ai-agent/databases/(default)/documents/{collection}/{doc_id}"}
    if fields:
        payload["fields"] = fields

    headers = {
        "Authorization": f"Bearer {CURRENT_TOKEN}",
        "Content-Type": "application/json"
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Using Session object specifically inside the loop can help reset the connection pool
            # to mitigate stubborn [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol
            with requests.Session() as session:
                response = session.patch(url, json=payload, headers=headers, timeout=10)
                logging.info(f"Status update response for {doc_id}: {response.status_code} - {response.text}")
                response.raise_for_status()
                return  # Success, exit the function
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTPError updating Firestore doc {doc_id} on attempt {attempt+1}: {e} - Response: {e.response.text}")
            if e.response.status_code in [400, 401, 403, 404]:
                break # Non-retriable HTTP errors
        except requests.exceptions.RequestException as e:
            logging.warning(f"Network/SSL error updating Firestore doc {doc_id} on attempt {attempt+1}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error updating Firestore doc {doc_id} on attempt {attempt+1}: {e}")
            break

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    logging.error(f"Failed to update Firestore doc {doc_id} after {max_retries} attempts.")

def firestore_get_document(collection: str, doc_id: str) -> Dict[str, Any]:
    """Gets a Firestore document using the REST API."""
    if not CURRENT_TOKEN:
        return {}

    url = f"https://firestore.googleapis.com/v1/projects/romy-ai-agent/databases/(default)/documents/{collection}/{doc_id}"
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        data = response.json()

        # Convert from Firestore REST format to simple dict
        result = {}
        fields = data.get("fields", {})
        for key, val_dict in fields.items():
            if "stringValue" in val_dict:
                result[key] = val_dict["stringValue"]
            elif "booleanValue" in val_dict:
                result[key] = val_dict["booleanValue"]
            elif "integerValue" in val_dict:
                result[key] = int(val_dict["integerValue"])
            elif "doubleValue" in val_dict:
                result[key] = float(val_dict["doubleValue"])

        return result
    except Exception as e:
        logging.error(f"Error getting Firestore doc {doc_id}: {e}")
        return {}

def _get_uid_from_token() -> str | None:
    """Extracts the UID (user_id) from the current JWT token."""
    if not CURRENT_TOKEN:
        return None
    try:
        import json
        parts = CURRENT_TOKEN.split('.')
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        # Pad with = to make it a multiple of 4
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        return payload.get('user_id')
    except Exception as e:
        logging.error(f"Error extracting UID from token: {e}")
        return None

def set_agent_online() -> None:
    """Sets the agent status to online in Firestore."""
    # Note: Using REST API doesn't support serverTimestamp() directly, we'll just write online.
    try:
        uid = _get_uid_from_token()
        if uid:
            firestore_update_document("users", uid, {"status": "online"})
        else:
            logging.warning("Could not set agent online: No UID found in token.")
    except Exception as e:
        logging.error(f"Failed to set agent online status: {e}")

def set_agent_offline() -> None:
    """Sets the agent status to offline in Firestore."""
    try:
        uid = _get_uid_from_token()
        if uid:
            firestore_update_document("users", uid, {"status": "offline"})
    except Exception as e:
        logging.error(f"Failed to set agent offline status: {e}")

def start_remote_listener() -> None:
    """Starts a polling loop for pending remote commands using REST API in a background thread."""
    import threading

    def _poll_loop():
        logging.info("Started listening for remote commands on Firestore via REST polling.")
        url = "https://firestore.googleapis.com/v1/projects/romy-ai-agent/databases/(default)/documents:runQuery"

        # Keep track of loops to periodically update online status
        loop_counter = 0
        error_count = 0
        session = requests.Session()

        while True:
            if not CURRENT_TOKEN:
                time.sleep(3)
                continue

            if PAUSE_AGENT:
                time.sleep(3)
                continue

            loop_counter += 1
            if loop_counter >= 20: # roughly every minute
                # Only set agent online if we are not in a sustained error state
                if error_count < 3:
                    set_agent_online()
                loop_counter = 0

            payload = {
                "structuredQuery": {
                    "from": [{"collectionId": "remote_commands"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": "status"},
                            "op": "EQUAL",
                            "value": {"stringValue": "pending"}
                        }
                    }
                }
            }

            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            try:
                response = session.post(url, json=payload, headers=headers, timeout=10)

                if response.status_code == 401:
                    logging.error("Unauthorized in start_remote_listener. Handling token expiry.")
                    handle_token_expiry()
                    time.sleep(3)
                    continue

                response.raise_for_status()
                results = response.json()
                error_count = 0 # Reset error count on successful fetch

                for res in results:
                    if "document" in res:
                        doc = res["document"]
                        doc_name = doc.get("name", "")
                        doc_id = doc_name.split("/")[-1]

                        fields = doc.get("fields", {})
                        command_text = fields.get("command", {}).get("stringValue", "")
                        audio_b64 = fields.get("audio_b64", {}).get("stringValue", "")

                        logging.info(f"Detected new remote command. Text: '{command_text}', Audio present: {bool(audio_b64)}")

                        # Update status to in_progress
                        firestore_update_document("remote_commands", doc_id, {"status": "in_progress"})

                        # Add to command queue instead of executing directly
                        COMMAND_QUEUE.put({
                            "type": "remote",
                            "doc_id": doc_id,
                            "command_text": command_text,
                            "audio_b64": audio_b64
                        })
            except requests.exceptions.RequestException as e:
                error_count += 1
                logging.error(f"Network error in remote listener poll (attempt {error_count}): {e}")
                # Re-initialize session on network errors to clear potentially bad sockets
                if error_count >= 3:
                    session.close()
                    session = requests.Session()
                    logging.warning("Re-initializing requests session due to repeated errors.")

            except Exception as e:
                logging.error(f"Error in remote listener poll: {e}")

            # Dynamic backoff based on error count (max 15s)
            sleep_time = min(3 * (2 ** max(0, error_count - 1)), 15) if error_count > 0 else 3
            time.sleep(sleep_time)

    # Start the polling loop in a background thread
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()

def handle_token_expiry():
    """Handles 401 Unauthorized by deleting the token and prompting for re-login."""
    global CURRENT_TOKEN
    logging.critical("Handling Token Expiry (401 Unauthorized).")

    # Clear global token to stop polling loop
    CURRENT_TOKEN = None

    # 1. Delete token.json from local AppData
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        for folder in ["RomyAgent", "RomyAgentBrowserData", ""]:
            if folder:
                token_path = os.path.join(local_app_data, folder, "token.json")
            else:
                token_path = os.path.join(local_app_data, "token.json")
            if os.path.exists(token_path):
                try:
                    os.remove(token_path)
                    logging.info(f"Deleted expired token file: {token_path}")
                except Exception as e:
                    logging.error(f"Failed to delete token file {token_path}: {e}")

    try:
        from plyer import notification
        notification.notify(title="ROMY AI Error", message="Session expired. Please log in from the tray menu.", app_name="ROMY", timeout=5)
    except Exception:
        pass


def scan_ui_elements() -> Tuple[list[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """
    Scans the active window's accessibility tree for clickable elements.
    Returns a list of UI element dictionaries and a memory map of ID to coordinates.
    """
    ui_elements = []
    memory_map = {}

    try:
        # We can either scan the entire desktop or the active window.
        # Active window is usually better for RPA context to avoid sending too much data.
        active_window = auto.GetForegroundControl()
        if not active_window:
            active_window = auto.GetRootControl()

        logging.info(f"Scanning UI tree for window: {active_window.Name}")

        # Traverse the tree
        element_id = 1
        for walk_result in auto.WalkTree(active_window, getChildren=lambda c: c.GetChildren(), includeTop=True):
            if isinstance(walk_result, (tuple, list)):
                control = walk_result[0] if len(walk_result) > 0 else None
                depth = walk_result[1] if len(walk_result) > 1 else 0
            else:
                control = walk_result
                depth = 0

            if not control:
                continue

            # Filter for elements that are likely interactive or provide context
            try:
                control_type = control.ControlTypeName
                name = control.Name
            except AttributeError:
                continue

            if control_type in ['ButtonControl', 'HyperlinkControl', 'TextControl', 'EditControl', 'MenuItemControl', 'ListItemControl', 'TabItemControl']:
                rect = control.BoundingRectangle
                if rect.width() > 0 and rect.height() > 0:
                    center_x = rect.left + rect.width() // 2
                    center_y = rect.top + rect.height() // 2

                    element_str_id = str(element_id)
                    ui_elements.append({
                        "id": element_str_id,
                        "type": control_type,
                        "name": name
                    })

                    memory_map[element_str_id] = {
                        "x": center_x,
                        "y": center_y
                    }
                    element_id += 1

        logging.info(f"Found {len(ui_elements)} UI elements.")
    except Exception as e:
        logging.error(f"Error scanning UI tree: {e}")

    return ui_elements, memory_map

def is_web_command(command_text: str) -> bool:
    """Simple heuristic to determine if a command is web-related."""
    if not command_text or not command_text.strip():
        return False

    text = command_text.lower()

    # Extended keywords and regex for domain extensions
    keywords = ["browser", "web", "chrome", "website", "http", "www", "url", "tab", "page",
                "youtube", "google", "wikipedia", "facebook", "twitter", "linkedin", "search for",
                "open site"]

    if any(kw in text for kw in keywords):
        return True

    # Check for domain-like strings (e.g., pelikan.cz, google.com)
    domain_pattern = r'\b[a-zA-Z0-9-]+\.(com|cz|org|net|io|co|edu|gov|info|biz)\b'
    if re.search(domain_pattern, text):
        return True

    # Generic "open <word>" could mean open an app or a site, but we can safely route "open <domain>"
    # "open pelikan" or similar
    if "open " in text and ("pelikan" in text or "site" in text):
        return True

    # Also check if the active window is Chrome
    try:
        active_window = auto.GetForegroundControl()
        if active_window and ("chrome" in active_window.Name.lower() or "browser" in active_window.Name.lower()):
            return True
    except Exception:
        pass

    return False

def run_remote_agent_loop(doc_id: str, command_text: str, audio_b64: str = "") -> None:
    """Runs the agent loop triggered by a remote text command."""
    if not CURRENT_TOKEN:
        logging.error("Error: Missing Firebase Token. Cannot execute remote command.")
        return

    try:
        logging.info(f"=== Remote Agent Activated for Document: {doc_id} ===")
        try:
            msg_text = f"Remote command received: {command_text}" if command_text else "Remote audio command received."
            notification.notify(title="ROMY AI", message=msg_text, app_name="ROMY", timeout=2)
            if winsound: winsound.Beep(800, 200)
        except Exception:
            if winsound: winsound.Beep(800, 200)

        # Command Routing
        # If command is web-related, delegate the whole loop to the Chrome extension
        if is_web_command(command_text):
            logging.info("Command routed to Web (Chrome Extension).")
            from local_bridge import bridge
            payload = {
                "commandText": command_text,
                "audioBase64": audio_b64
            }
            # Wait for Chrome to execute and return the result
            result = bridge.delegate_command(payload)
            if result.get("success"):
                final_status = "completed"
            elif result.get("helpNeeded"):
                final_status = "help_needed"
                try:
                    firestore_update_document("remote_commands", doc_id, {
                        "status": "help_needed",
                        "help_reason": result.get("reason", "Human help needed.")
                    })
                except Exception as e:
                    logging.error(f"Error updating help status: {e}")
                return # We don't mark as final_status here because we already updated with help_reason
            else:
                final_status = "failed"
                try:
                    firestore_update_document("remote_commands", doc_id, {
                        "status": "failed",
                        "error": result.get("error", "Unknown web execution error.")
                    })
                except Exception as e:
                    logging.error(f"Error updating failed status: {e}")
                return

            # Update final document status
            try:
                firestore_update_document("remote_commands", doc_id, {"status": final_status})
                logging.info(f"Remote command {doc_id} marked as {final_status} from Web execution.")
            except Exception as e:
                pass
            return

        logging.info("Command routed to OS (Native).")
        iteration = 0
        final_status = "completed"

        while True:
            if ABORT_AGENT:
                logging.info("Emergency abort triggered. Stopping remote agent loop.")
                final_status = "failed"
                break

            if PAUSE_AGENT:
                time.sleep(1)
                continue

            # Check for human response
            data = firestore_get_document("remote_commands", doc_id)
            if data:
                if data.get("status") == "help_needed":
                    logging.info("Agent paused, waiting for human input...")
                    time.sleep(2)
                    continue

                if data.get("human_response"):
                    command_text += "\nHuman instruction: " + data.get("human_response")
                    firestore_update_document("remote_commands", doc_id, {}, delete_fields=["human_response"])

            ui_elements, memory_map = scan_ui_elements()

            payload = {
                "ui_elements": ui_elements,
                "session_id": doc_id
            }
            if iteration == 0 and audio_b64:
                payload["audio_base64"] = audio_b64
            else:
                payload["audio_base64"] = ""

            payload["command_text"] = command_text

            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            logging.info(f"Sending remote payload to backend (iteration {iteration})...")
            try:
                response = requests.post(BACKEND_URL, json=payload, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list):
                    actions = data
                elif isinstance(data, dict):
                    actions = data.get("actions", [])
                    # If backend returned older single-action format, wrap it
                    if not actions and "action" in data:
                        actions = [data]
                else:
                    logging.warning(f"Unexpected response type from backend: {type(data)}")
                    actions = []

                break_outer = False
                had_terminal_action = False
                for act in actions:
                    if not isinstance(act, dict):
                        logging.warning(f"Skipping invalid action type: {type(act)}")
                        continue

                    if ABORT_AGENT:
                        logging.info("Emergency abort triggered during action sequence.")
                        final_status = "failed"
                        break_outer = True
                        break

                    action_type = act.get("action", "")
                    action_upper = str(action_type).upper()

                    if action_upper == "DONE":
                        logging.info("Remote task finished successfully.")
                        break_outer = True
                        break
                    elif "ERROR" in action_upper:
                        raw_response = act.get("raw_response", "No raw response provided")
                        error_msg = act.get("error", "No error message provided")
                        logging.error(f"Remote agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                        final_status = "failed"
                        break_outer = True
                        break
                    elif action_upper == "CLICK" and "target_id" in act:
                        target_id = str(act["target_id"])
                        if target_id in memory_map:
                            logging.info(f"Clicking element with ID {target_id} using PyAutoGUI...")
                            try:
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                                pyautogui.moveTo(x, y, duration=0.5)
                                pyautogui.click()
                            except Exception as click_e:
                                logging.error(f"Error executing click via PyAutoGUI: {click_e}.")
                        else:
                            logging.error(f"Error: target_id {target_id} not found in memory map.")

                    elif action_upper == "TYPE" and "target_id" in act and "text" in act:
                        target_id = str(act["target_id"])
                        text_to_type = act["text"]
                        if target_id in memory_map:
                            logging.info(f"Typing '{text_to_type}' at element {target_id} using PyAutoGUI...")
                            try:
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                                pyautogui.moveTo(x, y, duration=0.5)
                                pyautogui.click()
                                pyautogui.hotkey('ctrl', 'a')
                                pyautogui.press('backspace')
                                time.sleep(0.2)
                                pyautogui.write(text_to_type)
                            except Exception as type_e:
                                logging.error(f"Error executing type via PyAutoGUI: {type_e}.")
                        else:
                            logging.error(f"Error: target_id {target_id} not found in memory map.")

                    elif action_upper == "SCROLL" and "direction" in act:
                        direction = act["direction"].lower()
                        logging.info(f"Scrolling {direction}...")
                        try:
                            amount = -500 if direction == "down" else 500
                            pyautogui.scroll(amount)
                        except Exception as scroll_e:
                            logging.error(f"Error executing scroll via PyAutoGUI: {scroll_e}.")
                        time.sleep(1) # Let the DOM settle

                    elif action_upper == "REPLY" and "text" in act:
                        reply_text = act["text"]
                        logging.info(f"Agent replied: {reply_text}")
                        try:
                            notification.notify(title="ROMY AI Reply", message=reply_text, app_name="ROMY", timeout=5)
                            if winsound: winsound.Beep(800, 200)
                        except Exception as notif_e:
                            logging.error(f"Error showing reply notification: {notif_e}")
                            if winsound: winsound.Beep(800, 200)

                    elif action_upper == "ASK_HUMAN":
                        reason = act.get("reason", "No reason provided")
                        logging.info(f"Agent asking human for help: {reason}")
                        try:
                            screenshot = pyautogui.screenshot()
                            buffered = io.BytesIO()
                            screenshot.save(buffered, format="PNG")
                            img_str = base64.b64encode(buffered.getvalue()).decode()
                            firestore_update_document("remote_commands", doc_id, {
                                "status": "help_needed",
                                "help_reason": reason,
                                "screenshot_b64": img_str
                            })
                        except Exception as img_e:
                            logging.error(f"Error capturing screenshot: {img_e}")
                            firestore_update_document("remote_commands", doc_id, {
                                "status": "help_needed",
                                "help_reason": reason
                            })
                        had_terminal_action = True
                        break_outer = True
                        break
                    else:
                        logging.info(f"Received action: {action_type}. Continuing loop...")

                    # Micro-sleep between sequential actions within the array
                    time.sleep(0.5)

                if break_outer:
                    break

                if iteration > 0 and not had_terminal_action:
                    logging.error("Agentic Loop terminated to prevent infinite empty audio loop. No terminal action provided by backend.")
                    break

            except requests.exceptions.RequestException as req_e:
                if isinstance(req_e, requests.exceptions.HTTPError) and req_e.response.status_code == 401:
                    handle_token_expiry()
                    final_status = "failed"
                    error_msg = "Token expired"
                    break
                logging.info(f"Request failed: {req_e}")
                final_status = "failed"
                error_msg = f"Network request failed: {req_e}"
                break

            time.sleep(2)
            iteration += 1

        # Update final document status
        try:
            update_payload = {"status": final_status}
            if final_status == "failed":
                update_payload["error"] = error_msg if "error_msg" in locals() else "Unknown agent loop termination"
            firestore_update_document("remote_commands", doc_id, update_payload)
            logging.info(f"Remote command {doc_id} marked as {final_status}.")
        except Exception:
            pass

    except Exception as e:
        logging.error(f"Error executing remote command: {e}")
        try:
            firestore_update_document("remote_commands", doc_id, {"status": "failed", "error": str(e)})
        except Exception:
            pass


import numpy as np

def record_audio() -> str:
    """
    Records microphone input dynamically, stopping after ~1.5 to 2.0 seconds of silence.
    Saves as WAV in memory, and returns the Base64 encoded string.
    """
    try:
        sample_rate = 44100
        channels = 1
        block_duration = 0.1  # seconds
        block_size = int(sample_rate * block_duration)
        silence_threshold = 0.01  # RMS threshold for silence
        silence_duration_limit = 2.0  # seconds of silence to stop recording
        max_duration = 30.0  # maximum recording duration to prevent infinite loops

        logging.info("Recording audio dynamically... Speak now.")

        recorded_frames = []
        silent_frames = 0
        total_frames = 0

        stream = sd.InputStream(samplerate=sample_rate, channels=channels, dtype='float32')
        with stream:
            while True:
                data, overflowed = stream.read(block_size)
                recorded_frames.append(data)
                total_frames += 1

                # Calculate RMS
                rms = np.sqrt(np.mean(np.square(data)))

                if rms < silence_threshold:
                    silent_frames += 1
                else:
                    silent_frames = 0

                if silent_frames * block_duration >= silence_duration_limit:
                    logging.info("Silence detected. Stopping recording.")
                    break

                if total_frames * block_duration >= max_duration:
                    logging.warning("Maximum recording duration reached.")
                    break

        logging.info("Recording finished.")

        if not recorded_frames:
            return ""

        # Concatenate all frames and convert back to int16 for WAV writing
        recording = np.concatenate(recorded_frames, axis=0)
        recording_int16 = np.int16(recording * 32767)

        # Save to an in-memory byte buffer
        wav_io = io.BytesIO()
        wav_write(wav_io, sample_rate, recording_int16)
        wav_bytes = wav_io.getvalue()

        # Encode to base64
        b64_str = base64.b64encode(wav_bytes).decode('utf-8')
        return b64_str
    except Exception as e:
        logging.error(f"Error recording audio: {e}")
        return ""


def activate_agent() -> None:
    """
    Adds a voice agent task to the command queue.
    """
    logging.info("Voice activation triggered. Adding to command queue...")
    COMMAND_QUEUE.put({"type": "voice"})

def execute_voice_agent_loop() -> None:
    """
    Activates the agent. Captures initial audio command, then enters the
    Agentic Loop, sending screen and audio data to the backend until DONE.
    """
    if not CURRENT_TOKEN:
        logging.error("Error: Missing Firebase Token. Please log in first.")
        return

    try:
        logging.info("=== Agent Activated: Ready for commands ===")

        # 1. Capture initial audio command
        try:
            notification.notify(title="ROMY AI", message="🎙️ Recording started... Speak your command now.", app_name="ROMY", timeout=2)
            if winsound: winsound.Beep(1000, 200)
        except Exception:
            if winsound: winsound.Beep(1000, 200)

        audio_b64 = record_audio()

        try:
            notification.notify(title="ROMY AI", message="🧠 Processing command...", app_name="ROMY", timeout=2)
            if winsound: winsound.Beep(800, 200)
        except Exception:
            if winsound: winsound.Beep(800, 200)

        # 2. Start Agentic Loop
        iteration = 0
        doc_id = "voice_session_1"
        command_text = ""

        # Create or ensure the document exists
        try:
            # For set with merge = true using REST we can just patch
            firestore_update_document("remote_commands", doc_id, {
                "status": "in_progress",
                "command": "voice command"
            })
        except Exception as e:
            logging.error(f"Error setting up voice session document: {e}")

        while True:
            if ABORT_AGENT:
                logging.info("Emergency abort triggered. Stopping voice agent loop.")
                break

            if PAUSE_AGENT:
                time.sleep(1)
                continue

            # Check for human response
            try:
                data = firestore_get_document("remote_commands", doc_id)
                if data:
                    if data.get("status") == "help_needed":
                        logging.info("Agent paused, waiting for human input...")
                        time.sleep(2)
                        continue

                    if data.get("human_response"):
                        command_text += "\nHuman instruction: " + data.get("human_response")
                        firestore_update_document("remote_commands", doc_id, {}, delete_fields=["human_response"])
            except Exception as e:
                logging.error(f"Error checking human response: {e}")

            # 3. Scan UI Elements
            ui_elements, memory_map = scan_ui_elements()

            # 4. Construct JSON payload
            payload = {
                "ui_elements": ui_elements
            }
            if iteration == 0:
                payload["audio_base64"] = audio_b64
            else:
                payload["audio_base64"] = ""

            payload["command_text"] = command_text
            payload["session_id"] = doc_id

            # 5. Send POST to backend
            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            logging.info(f"Sending payload to backend (iteration {iteration})...")
            try:
                response = requests.post(BACKEND_URL, json=payload, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                # 6. Check response
                if isinstance(data, list):
                    actions = data
                elif isinstance(data, dict):
                    actions = data.get("actions", [])
                    if not actions and "action" in data:
                        actions = [data]
                else:
                    logging.warning(f"Unexpected response type from backend: {type(data)}")
                    actions = []

                break_outer = False
                had_terminal_action = False
                for act in actions:
                    if not isinstance(act, dict):
                        logging.warning(f"Skipping invalid action type: {type(act)}")
                        continue

                    if ABORT_AGENT:
                        logging.info("Emergency abort triggered during action sequence.")
                        break_outer = True
                        break

                    action_type = act.get("action", "")
                    action_upper = str(action_type).upper()

                    if action_upper == "DONE":
                        logging.info("Task finished.")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif "ERROR" in action_upper:
                        raw_response = act.get("raw_response", "No raw response provided")
                        error_msg = act.get("error", "No error message provided")
                        logging.error(f"Agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif action_upper == "CLICK" and "target_id" in act:
                        target_id = str(act["target_id"])
                        if target_id in memory_map:
                            logging.info(f"Clicking element with ID {target_id} using PyAutoGUI...")
                            try:
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                                pyautogui.moveTo(x, y, duration=0.5)
                                pyautogui.click()
                            except Exception as click_e:
                                logging.error(f"Error executing click via PyAutoGUI: {click_e}.")
                        else:
                            logging.error(f"Error: target_id {target_id} not found in memory map.")

                    elif action_upper == "TYPE" and "target_id" in act and "text" in act:
                        target_id = str(act["target_id"])
                        text_to_type = act["text"]
                        if target_id in memory_map:
                            logging.info(f"Typing '{text_to_type}' at element {target_id} using PyAutoGUI...")
                            try:
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                                pyautogui.moveTo(x, y, duration=0.5)
                                pyautogui.click()
                                pyautogui.hotkey('ctrl', 'a')
                                pyautogui.press('backspace')
                                time.sleep(0.2)
                                pyautogui.write(text_to_type)
                            except Exception as type_e:
                                logging.error(f"Error executing type via PyAutoGUI: {type_e}.")
                        else:
                            logging.error(f"Error: target_id {target_id} not found in memory map.")

                    elif action_upper == "SCROLL" and "direction" in act:
                        direction = act["direction"].lower()
                        logging.info(f"Scrolling {direction}...")
                        try:
                            amount = -500 if direction == "down" else 500
                            pyautogui.scroll(amount)
                        except Exception as scroll_e:
                            logging.error(f"Error executing scroll via PyAutoGUI: {scroll_e}.")
                        time.sleep(1) # Let the DOM settle

                    elif action_upper == "REPLY" and "text" in act:
                        reply_text = act["text"]
                        logging.info(f"Agent replied: {reply_text}")
                        try:
                            notification.notify(title="ROMY AI Reply", message=reply_text, app_name="ROMY", timeout=5)
                            if winsound: winsound.Beep(800, 200)
                        except Exception as notif_e:
                            logging.error(f"Error showing reply notification: {notif_e}")
                            if winsound: winsound.Beep(800, 200)

                    elif action_upper == "ASK_HUMAN":
                        reason = act.get("reason", "No reason provided")
                        logging.info(f"Agent asking human for help: {reason}")
                        try:
                            screenshot = pyautogui.screenshot()
                            buffered = io.BytesIO()
                            screenshot.save(buffered, format="PNG")
                            img_str = base64.b64encode(buffered.getvalue()).decode()
                            firestore_update_document("remote_commands", doc_id, {
                                "status": "help_needed",
                                "help_reason": reason,
                                "screenshot_b64": img_str
                            })
                        except Exception as img_e:
                            logging.error(f"Error capturing screenshot: {img_e}")
                            firestore_update_document("remote_commands", doc_id, {
                                "status": "help_needed",
                                "help_reason": reason
                            })
                        had_terminal_action = True
                        break_outer = True
                        break
                    else:
                        logging.info(f"Received action: {action_type}. Continuing loop...")

                    # Micro-sleep between sequential actions within the array
                    time.sleep(0.5)

                if break_outer:
                    break

                if iteration > 0 and not had_terminal_action:
                    logging.error("Voice Agentic Loop terminated to prevent infinite empty audio loop. No terminal action provided by backend.")
                    break

            except requests.exceptions.RequestException as req_e:
                if isinstance(req_e, requests.exceptions.HTTPError) and req_e.response.status_code == 401:
                    handle_token_expiry()
                    break
                logging.info(f"Request failed: {req_e}")
                # Break the loop on network failure to avoid infinite errors
                break

            # 7. Sleep for 2 seconds before next iteration
            time.sleep(2)
            iteration += 1

    except Exception as e:
        logging.error(f"Error activating agent: {e}")
