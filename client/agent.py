import logging
import base64
import io
import time
import os
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import queue
import json
import threading
from datetime import datetime

import io
import base64
from PIL import Image, ImageDraw, ImageFont
import asyncio
import traceback
from enum import Enum

try:
    import uiautomation as auto
except:
    pass
try:
    import sounddevice as sd
except:
    pass
from scipy.io.wavfile import write as wav_write
try:
    import pyautogui
except:
    pass
from plyer import notification
try:
    import winsound
except ImportError:
    winsound = None
from typing import Dict, Any, Tuple

try:
    pyautogui.FAILSAFE = False
except:
    pass

BACKEND_URL = os.environ.get("BACKEND_URL", "https://romy-backend-1049976869239.europe-west1.run.app/api/v1/agent/command")

CURRENT_TOKEN = None

COMMAND_QUEUE = queue.Queue()
global_state_machine = None
global_asyncio_loop = None


class AgentState(Enum):
    INITIALIZING = "INITIALIZING"
    EVALUATING = "EVALUATING"
    THINKING = "THINKING"
    ACTING = "ACTING"
    SUSPENDED_HITL = "SUSPENDED_HITL"
    LEARNING_ROUTINE = "LEARNING_ROUTINE"
    TERMINATED = "TERMINATED"

ABORT_AGENT = False
PAUSE_AGENT = False
ACTIVE_DOC_ID = None

LOCAL_STATUS = {} # Dictionary to store local task statuses mapping doc_id to status

def save_flight_record(doc_id: str, iteration: int, payload: dict, response: dict, action_executed: dict, screenshot_b64: str) -> None:
    """Saves a timestamped record of the ReAct cycle locally for debugging."""
    try:
        user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RomyAgentBrowserData", "flight_records", doc_id)
        os.makedirs(user_data_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record_file = os.path.join(user_data_dir, f"record_{iteration}_{timestamp}.json")

        # Don't save the full screenshot in the prompt payload or response to avoid huge json files if we also save the image itself,
        # but let's just save everything as requested. We can save the screenshot as a separate file if it exists.
        record_data = {
            "timestamp": datetime.now().isoformat(),
            "doc_id": doc_id,
            "iteration": iteration,
            "prompt_payload": payload,
            "llm_response": response,
            "action_executed": action_executed
        }

        with open(record_file, "w", encoding="utf-8") as f:
            json.dump(record_data, f, indent=2, ensure_ascii=False)

        if screenshot_b64:
            img_file = os.path.join(user_data_dir, f"screenshot_{iteration}_{timestamp}.png")
            try:
                img_data = base64.b64decode(screenshot_b64)
                with open(img_file, "wb") as f:
                    f.write(img_data)
            except Exception as e:
                logging.error(f"Failed to save screenshot for flight record: {e}")

        logging.info(f"Flight record saved for iteration {iteration} to {record_file}")
    except Exception as e:
        logging.error(f"Failed to save flight record: {e}")

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
                client_context = task.get("client_context")
                run_remote_agent_loop(doc_id, command_text, audio_b64, client_context)
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

def get_resilient_session() -> requests.Session:
    """Returns a requests.Session configured with exponential backoff and retries."""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,  # 1s, 2s, 4s, 8s, 16s
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PATCH", "PUT", "DELETE"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def firestore_update_document(collection: str, doc_id: str, updates: Dict[str, Any], delete_fields: list = None) -> None:
    """Updates a Firestore document using the REST API with retries for network resilience."""
    if "status" in updates:
        LOCAL_STATUS[doc_id] = updates["status"]

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
            # Using resilient session for robust retries
            with get_resilient_session() as session:
                response = session.patch(url, json=payload, headers=headers, timeout=10)
                logging.info(f"Status update response for {doc_id}: {response.status_code}")
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
        with get_resilient_session() as session:
            response = session.get(url, headers=headers, timeout=10)
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
        session = get_resilient_session()

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
            except requests.exceptions.SSLError as e:
                error_count += 1
                logging.error(f"SSL/Network error in remote listener poll (attempt {error_count}): {e}")
                if error_count >= 3:
                    session.close()
                    session = get_resilient_session()
                    logging.warning("Re-initializing resilient requests session due to repeated errors.")
            except requests.exceptions.RequestException as e:
                error_count += 1
                logging.error(f"Network error in remote listener poll (attempt {error_count}): {e}")
                # Re-initialize session on network errors to clear potentially bad sockets
                if error_count >= 3:
                    session.close()
                    session = get_resilient_session()
                    logging.warning("Re-initializing resilient requests session due to repeated errors.")

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


def annotate_image_with_crosshair(base64_img: str, x: int, y: int) -> str:
    """Draws a green crosshair on the raw un-tagged coordinate."""
    try:
        if base64_img.startswith('data:image'):
            img_data = base64.b64decode(base64_img.split(',')[1])
            prefix = base64_img.split(',')[0] + ','
        else:
            img_data = base64.b64decode(base64_img)
            prefix = "data:image/png;base64,"

        image = Image.open(io.BytesIO(img_data)).convert("RGBA")
        draw = ImageDraw.Draw(image)

        # Draw crosshair
        r = 15
        draw.ellipse((x-r, y-r, x+r, y+r), outline=(0, 255, 0, 255), width=3)
        draw.line((x-r-5, y, x+r+5, y), fill=(0, 255, 0, 255), width=3)
        draw.line((x, y-r-5, x, y+r+5), fill=(0, 255, 0, 255), width=3)

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return prefix + base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception as e:
        logging.error(f"Failed to apply crosshair annotation: {e}")
        return base64_img

def annotate_image_with_som(base64_img: str, ui_elements: list) -> str:
    """Draws Set-of-Mark numbered bounding boxes over interactive elements."""
    try:
        if base64_img.startswith('data:image'):
            img_data = base64.b64decode(base64_img.split(',')[1])
            prefix = base64_img.split(',')[0] + ','
        else:
            img_data = base64.b64decode(base64_img)
            prefix = "data:image/png;base64,"

        image = Image.open(io.BytesIO(img_data)).convert("RGBA")
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.load_default()
        except:
            font = None

        for el in ui_elements:
            box = el.get("bounds")
            target_id = el.get("target_id")

            if box and target_id is not None:
                try:
                    x, y, width, height = map(int, box)
                    draw.rectangle([x, y, x + width, y + height], outline=(255, 0, 0, 255), width=2)
                    text = f" [{target_id}] "
                    if hasattr(font, 'getbbox'):
                        bbox = font.getbbox(text)
                        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    else:
                        tw, th = len(text) * 6, 12
                    draw.rectangle([x, max(0, y - th), x + tw, y], fill=(255, 0, 0, 255))
                    draw.text((x, max(0, y - th)), text, fill=(255, 255, 255, 255), font=font)
                except Exception as e:
                    logging.warning(f"Error drawing SoM box for ID {target_id}: {e}")

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return prefix + base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception as e:
        logging.error(f"Failed to apply SoM annotation: {e}")
        return base64_img

def annotate_image_with_crosshair(base64_img: str, x: int, y: int) -> str:
    """Draws a green crosshair on the raw un-tagged coordinate."""
    try:
        if base64_img.startswith('data:image'):
            img_data = base64.b64decode(base64_img.split(',')[1])
            prefix = base64_img.split(',')[0] + ','
        else:
            img_data = base64.b64decode(base64_img)
            prefix = "data:image/png;base64,"

        image = Image.open(io.BytesIO(img_data)).convert("RGBA")
        draw = ImageDraw.Draw(image)

        r = 15
        draw.ellipse((x-r, y-r, x+r, y+r), outline=(0, 255, 0, 255), width=3)
        draw.line((x-r-5, y, x+r+5, y), fill=(0, 255, 0, 255), width=3)
        draw.line((x, y-r-5, x, y+r+5), fill=(0, 255, 0, 255), width=3)

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return prefix + base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception as e:
        logging.error(f"Failed to apply crosshair annotation: {e}")
        return base64_img

def pre_flight_check(command_text: str) -> dict:
    if not CURRENT_TOKEN:
        return {"status": "ok"}
    base_url = BACKEND_URL.split("/api/v1")[0] if "/api/v1" in BACKEND_URL else BACKEND_URL.rsplit('/', 1)[0]
    if not base_url.endswith("/"):
        base_url += "/"
    url = f"{base_url.rstrip('/')}/api/pre_flight"

    payload = {"command_text": command_text}
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        with get_resilient_session() as session:
            response = session.post(url, json=payload, headers=headers, timeout=(10, 20))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error in pre-flight check: {e}")
        return {"status": "ok"}

def supervisor_plan(command_text: str) -> list:
    if not CURRENT_TOKEN:
        return []
    base_url = BACKEND_URL.split("/api/v1")[0] if "/api/v1" in BACKEND_URL else BACKEND_URL.rsplit('/', 1)[0]
    if not base_url.endswith("/"):
        base_url += "/"
    url = f"{base_url.rstrip('/')}/api/supervisor_plan"

    payload = {"command_text": command_text}
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        with get_resilient_session() as session:
            response = session.post(url, json=payload, headers=headers, timeout=(10, 30))
        response.raise_for_status()
        return response.json().get("sub_tasks", [])
    except Exception as e:
        logging.error(f"Error getting supervisor plan: {e}")
        return []

def verify_action_natively(action, before_state, after_state):
    from urllib.parse import urlparse
    action_type = str(action.get("action", "")).upper()
    logging.info(f"Attempting native verification for action: {action_type}")

    # Extract metadata and states safely
    before_meta = before_state.get("metadata", {}) or {}
    after_meta = after_state.get("metadata", {}) or {}
    before_url = before_meta.get("current_url", "")
    after_url = after_meta.get("current_url", "")

    before_ui = before_state.get("ui_elements", []) or []
    after_ui = after_state.get("ui_elements", []) or []

    if action_type in ["NAVIGATE", "OPEN_TAB"]:
        if before_url != after_url and after_url:
            return {"success": True, "reason": "URL changed natively verified."}

        target_url = action.get("url", "")
        if target_url and after_url:
            # Fuzzy verification: checking domain match instead of exact URL match
            target_domain = urlparse(target_url).netloc.replace("www.", "")
            after_domain = urlparse(after_url).netloc.replace("www.", "")
            if target_domain and after_domain and target_domain == after_domain:
                return {"success": True, "reason": "Navigated to target URL domain natively verified."}

            if target_url in after_url:
                 return {"success": True, "reason": "Navigated to target URL natively verified."}

        return {"success": False, "reason": "URL did not change as expected."}

    elif action_type == "TYPE":
        text_to_type = action.get("text", "")
        if not text_to_type:
            return {"success": True, "reason": "No text to verify, returning true."}

        # Check if typed text exists in the new UI elements natively
        for el in after_ui:
            # Check value or text attributes mapped by DOMSnapshot
            el_text = el.get("text", "") or ""
            el_value = el.get("attributes", {}).get("value", "") or ""
            el_placeholder = el.get("attributes", {}).get("placeholder", "") or ""

            if text_to_type.lower() in str(el_text).lower() or text_to_type.lower() in str(el_value).lower():
                return {"success": True, "reason": f"Text '{text_to_type}' natively verified in DOM."}

        return {"success": False, "reason": f"Text '{text_to_type}' not found natively in new DOM."}

    elif action_type == "CLICK":
        # If URL changed, click definitely did something
        if before_url != after_url and after_url:
            return {"success": True, "reason": "URL changed after click natively verified."}

        # If DOM changed significantly (e.g. elements appeared/disappeared)
        before_ids = {el.get("id") for el in before_ui if el.get("id")}
        after_ids = {el.get("id") for el in after_ui if el.get("id")}

        # If new elements appeared or old ones disappeared, the state changed
        if before_ids != after_ids:
             return {"success": True, "reason": "DOM state changed after click natively verified."}

        # If state didn't change significantly (or we can't be sure), fallback to LLM Critic
        return {"success": False, "reason": "No deterministic DOM or URL change natively detected after click."}

    elif action_type in ["RESET_VIEW", "SCROLL"]:
        return {"success": True, "reason": f"{action_type} natively verified."}

    # For other actions or complex semantic checks, return False to fallback to LLM Critic
    return {"success": False, "reason": "Action cannot be verified natively."}

def critic_verify(sub_task: str, action_taken: dict, before_state: dict, after_state: dict) -> dict:
    if not CURRENT_TOKEN:
        return {"success": True, "reason": "No token"}
    base_url = BACKEND_URL.split("/api/v1")[0] if "/api/v1" in BACKEND_URL else BACKEND_URL.rsplit('/', 1)[0]
    if not base_url.endswith("/"):
        base_url += "/"
    url = f"{base_url.rstrip('/')}/api/critic_verify"

    payload = {
        "sub_task": sub_task,
        "action_taken": action_taken,
        "before_state": before_state,
        "after_state": after_state
    }
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        with get_resilient_session() as session:
            response = session.post(url, json=payload, headers=headers, timeout=(10, 30))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error in critic verify: {e}")
        return {"success": True, "reason": f"Verification error: {e}"}

def classify_intent(command_text: str, audio_b64: str) -> Tuple[str, str]:
    """
    Calls the backend API to dynamically classify if a command is meant for WEB or OS.
    If command_text is empty, the backend uses audio_b64 to transcribe first.
    Returns (intent_string, transcribed_or_original_command_text).
    """
    if not CURRENT_TOKEN:
        logging.error("Missing token, cannot classify intent.")
        return "OS", command_text

    # Derive base URL from BACKEND_URL, replacing the path
    # Default is https://romy-backend-1049976869239.europe-west1.run.app/api/v1/agent/command
    # We want https://romy-backend-1049976869239.europe-west1.run.app/api/classify_intent
    base_url = BACKEND_URL.split("/api/v1")[0] if "/api/v1" in BACKEND_URL else BACKEND_URL.rsplit('/', 1)[0]
    # Handle local cases where it might just be the base URL
    if not base_url.endswith("/"):
        base_url += "/"
    url = f"{base_url.rstrip('/')}/api/classify_intent"

    payload = {
        "command_text": command_text,
        "audio_base64": audio_b64
    }

    headers = {
        "Authorization": f"Bearer {CURRENT_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        with get_resilient_session() as session:
            response = session.post(url, json=payload, headers=headers, timeout=(10, 20))
        response.raise_for_status()
        data = response.json()

        intent = data.get("intent", "OS")
        final_text = data.get("command_text", command_text)

        logging.info(f"Intent classified dynamically as '{intent}' with text: '{final_text}'")
        return intent, final_text
    except Exception as e:
        logging.error(f"Error classifying intent with backend: {e}. Defaulting to OS.")
        return "OS", command_text

def load_client_profile() -> Dict[str, Any]:
    """Loads the client profile from client_profile.json if it exists."""
    profile_path = os.path.join(os.path.dirname(__file__), "client_profile.json")
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load client_profile.json: {e}")
    return {}


class AgentStateMachine:
    def __init__(self):
        self.state = AgentState.INITIALIZING
        self.hitl_event = asyncio.Event()
        self.hitl_action = None
        self.doc_id = None
        self.command_text = None
        self.audio_b64 = None
        self.client_context = None
        self.sub_tasks = []
        self.current_sub_task_index = 0
        self.iteration = 0
        self.sub_task_iteration = 0
        self.history = []
        self.previous_action = None
        self.previous_state_metadata = None
        self.previous_state_ui = None
        self.max_sub_task_iterations = 5

    async def run(self, doc_id, command_text, audio_b64="", client_context=None):
        global ACTIVE_DOC_ID
        ACTIVE_DOC_ID = doc_id

        self.doc_id = doc_id
        self.command_text = command_text
        self.audio_b64 = audio_b64
        self.client_context = client_context or load_client_profile()
        self.state = AgentState.INITIALIZING
        self.iteration = 0
        self.sub_tasks = []
        self.current_sub_task_index = 0
        self.sub_task_iteration = 0

        logging.info(f"=== Remote Agent Activated for Document: {doc_id} ===")
        from local_bridge import bridge

        while self.state != AgentState.TERMINATED:
            if ABORT_AGENT:
                logging.info("Emergency abort triggered. Stopping state machine.")
                self.state = AgentState.TERMINATED
                break
            if PAUSE_AGENT:
                await asyncio.sleep(1)
                continue

            if self.state == AgentState.INITIALIZING:
                await self.state_initializing()
            elif self.state == AgentState.EVALUATING:
                await self.state_evaluating(bridge)
            elif self.state == AgentState.THINKING:
                await self.state_thinking(bridge)
            elif self.state == AgentState.ACTING:
                await self.state_acting(bridge)
            elif self.state == AgentState.SUSPENDED_HITL:
                await self.state_suspended_hitl()
            elif self.state == AgentState.LEARNING_ROUTINE:
                await self.state_learning_routine()

            await asyncio.sleep(0.1)

    async def state_initializing(self):
        intent, cmd_text = classify_intent(self.command_text, self.audio_b64)
        self.command_text = cmd_text

        if intent != "WEB":
            logging.info("Non-WEB commands not supported in Async State Machine yet.")
            self.state = AgentState.TERMINATED
            return

        logging.info("Running Pre-Flight check...")
        pre_flight = pre_flight_check(self.command_text)
        if pre_flight.get("status") == "ASK_HUMAN":
            reason = pre_flight.get("reason", "Missing required information.")
            logging.info(f"Pre-flight failed: {reason}")
            try:
                firestore_update_document("remote_commands", self.doc_id, {
                    "status": "AWAITING_HUMAN_INPUT",
                    "help_reason": reason
                })
            except Exception as e:
                logging.error(f"Error saving pre-flight help request: {e}")
            self.state = AgentState.TERMINATED
            return

        logging.info("Requesting Supervisor Plan...")
        self.sub_tasks = supervisor_plan(self.command_text)
        if not self.sub_tasks:
            self.sub_tasks = [self.command_text]

        logging.info(f"Supervisor plan generated: {self.sub_tasks}")
        self.current_sub_task_index = 0
        self.history = []
        self.state = AgentState.EVALUATING

    async def state_evaluating(self, bridge):
        if self.current_sub_task_index >= len(self.sub_tasks):
            logging.info("All sub-tasks completed.")
            self.state = AgentState.TERMINATED
            firestore_update_document("remote_commands", self.doc_id, {"status": "completed"})
            return

        if self.sub_task_iteration >= self.max_sub_task_iterations:
            logging.info("Max iterations reached for sub-task.")
            self.current_sub_task_index += 1
            self.sub_task_iteration = 0
            self.previous_action = None
            return

        current_sub_task = self.sub_tasks[self.current_sub_task_index]
        logging.info(f"--- Executing Sub-Task {self.current_sub_task_index + 1}/{len(self.sub_tasks)}: {current_sub_task} ---")

        logging.info("Requesting GET_STATE from bridge...")
        state_payload = {
            "action_type": "GET_STATE",
            "commandText": self.command_text,
            "audioBase64": self.audio_b64 if self.iteration == 0 else "",
            "iteration": self.iteration
        }
        state_result = bridge.delegate_command(state_payload)
        if not state_result.get("success"):
            logging.error(f"Failed to get state from extension: {state_result.get('error')}")
            self.state = AgentState.TERMINATED
            return

        self.current_clean_screenshot = state_result.get("screenshot_base64", "")
        self.current_ui_elements = state_result.get("ui_elements", [])
        self.current_url = state_result.get("url", "")

        self.current_annotated_screenshot = annotate_image_with_som(
            self.current_clean_screenshot,
            self.current_ui_elements
        )

        if self.previous_action:
            logging.info("Attempting Orchestrator-Level Native Verification of previous action...")
            native_res = verify_action_natively(
                self.previous_action,
                {"metadata": self.previous_state_metadata, "ui_elements": self.previous_state_ui},
                {"metadata": {"current_url": self.current_url}, "ui_elements": self.current_ui_elements}
            )

            if native_res.get("success"):
                logging.info(f"Native verification succeeded: {native_res.get('reason')}")
                self.command_text += f"\n[System Note: Action {self.previous_action.get('action', 'UNKNOWN')} verified successfully natively: {native_res.get('reason')}]"
            else:
                logging.info(f"Native verification didn't match: {native_res.get('reason')}")

        self.state = AgentState.THINKING

    async def state_thinking(self, bridge):
        current_sub_task = self.sub_tasks[self.current_sub_task_index]
        payload = {
            "ui_elements": [], # Stripped out to enforce Vision-First SoM reasoning
            "raw_ui_elements": self.current_ui_elements,
            "command_text": self.command_text,
            "current_sub_task": current_sub_task,
            "history": self.history,
            "iteration": self.iteration,
            "screenshot_base64": getattr(self, "current_annotated_screenshot", self.current_clean_screenshot),
            "client_context": self.client_context
        }

        logging.info("Sending state to backend for decision...")
        try:
            session = get_resilient_session()
            headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}
            backend_url = f"{BACKEND_URL}/process"
            response = session.post(backend_url, json=payload, headers=headers)
            response.raise_for_status()
            self.ai_response = response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Backend API call failed: {e}")
            self.state = AgentState.TERMINATED
            return

        actions = self.ai_response.get("actions", [])
        if not actions:
             if "action" in self.ai_response:
                 actions = [self.ai_response]
             else:
                 logging.error("No actions returned by AI.")
                 self.state = AgentState.TERMINATED
                 return

        for act in actions:
             if act.get("action") == "ASK_HUMAN":
                 help_reason = act.get("reason", "I am stuck and need help.")
                 contextual_help_reason = f"{help_reason} | Stuck trying to execute: [{current_sub_task}]"
                 logging.info(f"AI requested human help: {contextual_help_reason}")
                 try:
                     firestore_update_document("remote_commands", self.doc_id, {
                         "status": "AWAITING_HUMAN_INPUT",
                         "help_reason": contextual_help_reason
                     })
                 except Exception as e:
                     logging.error(f"Error saving help request to Firestore: {e}")
                 self.state = AgentState.SUSPENDED_HITL
                 return

        current_state_str = str([{"id": el.get("target_id", "N/A"), "text": el.get("text", "")[:20]} for el in self.current_ui_elements[:5]])
        if self.history and self.history[-1] == current_state_str:
            self.stuck_counter = getattr(self, 'stuck_counter', 0) + 1
            if self.stuck_counter >= 5:
                 logging.warning("Stuck detector triggered! Same visual state for 5 iterations.")
                 try:
                     firestore_update_document("remote_commands", self.doc_id, {
                         "status": "AWAITING_HUMAN_INPUT",
                         "help_reason": f"I am stuck in a loop trying to execute: [{current_sub_task}]"
                     })
                 except Exception as e:
                     logging.error(f"Error saving stuck state to Firestore: {e}")
                 self.state = AgentState.SUSPENDED_HITL
                 return
        else:
            self.stuck_counter = 0

        self.history.append(current_state_str)
        if len(self.history) > 10:
             self.history.pop(0)

        self.actions_to_execute = actions
        self.state = AgentState.ACTING

    async def state_acting(self, bridge):
        current_sub_task = self.sub_tasks[self.current_sub_task_index]
        bail_out = False

        for action_idx, action_to_take in enumerate(self.actions_to_execute):
             if action_to_take.get("action") == "SUB_TASK_COMPLETE":
                 logging.info(f"Sub-Task '{current_sub_task}' marked as complete by AI.")
                 self.current_sub_task_index += 1
                 self.sub_task_iteration = 0
                 self.previous_action = None
                 self.history.clear()
                 bail_out = True
                 break

             if action_to_take.get("action") == "WAIT":
                 wait_time = action_to_take.get("wait_time", 2)
                 logging.info(f"Executing explicit WAIT for {wait_time} seconds...")
                 await asyncio.sleep(wait_time)
                 bail_out = True
                 break

             logging.info(f"Executing Macro-Action {action_idx + 1}/{len(self.actions_to_execute)}: {action_to_take.get('action')}")
             action_type = action_to_take.get("action")

             exec_payload = {"action_type": "EXECUTE_ACTION", "action": action_to_take, "iteration": self.iteration}
             exec_result = bridge.delegate_command(exec_payload)

             if not exec_result.get("success"):
                 logging.warning(f"Macro-action execution failed via bridge: {exec_result.get('error')}. Bailing out of batch.")
                 bail_out = True
                 break

             self.previous_action = action_to_take
             self.previous_state_metadata = {"current_url": self.current_url}
             self.previous_state_ui = self.current_ui_elements

        try:
             save_flight_record(
                 doc_id=self.doc_id,
                 iteration=self.iteration,
                 payload={"command_text": self.command_text, "sub_task": current_sub_task},
                 response=self.ai_response,
                 action_executed=self.actions_to_execute,
                 screenshot_b64=self.current_clean_screenshot
             )
        except Exception as e:
             logging.error(f"Failed to save flight record: {e}")

        self.iteration += 1
        self.sub_task_iteration += 1
        self.state = AgentState.EVALUATING

    async def state_suspended_hitl(self):
        logging.info("Agent is SUSPENDED, awaiting HITL event (Ghost Click)...")
        await self.hitl_event.wait()
        logging.info("Agent WOKE UP from HITL suspension.")
        self.hitl_event.clear()
        self.state = AgentState.LEARNING_ROUTINE

    async def state_learning_routine(self):
        logging.info(f"LEARNING_ROUTINE: Processing human guidance action: {self.hitl_action}")
        from local_bridge import bridge

        if self.hitl_action:
            x = self.hitl_action.get("x")
            y = self.hitl_action.get("y")

            if x is not None and y is not None:
                css_x, css_y = float(x), float(y)

                intersecting_boxes = []
                for el in getattr(self, 'current_ui_elements', []):
                    box = el.get("bounds")
                    if box and len(box) == 4:
                        bx, by, bwidth, bheight = box
                        if bx <= css_x <= bx + bwidth and by <= css_y <= by + bheight:
                            area = bwidth * bheight
                            intersecting_boxes.append({"el": el, "area": area})

                target_box = None
                prompt_text = ""
                image_to_send = ""

                if intersecting_boxes:
                    intersecting_boxes.sort(key=lambda item: item["area"])
                    target_box = intersecting_boxes[0]["el"]
                    target_id = target_box.get("target_id")

                    logging.info(f"HITL click at ({css_x}, {css_y}) intersected with SoM Box [{target_id}].")
                    prompt_text = (f"The human operator intervened and clicked on SoM Box ID [{target_id}]. "
                                   f"You failed to execute this step correctly in the previous iteration. "
                                   f"Analyze the visual features and semantic context of Box [{target_id}] "
                                   f"and generate a universal visual rule for the Playbook.")
                    image_to_send = getattr(self, "current_annotated_screenshot", self.current_clean_screenshot)
                else:
                    logging.info(f"HITL click at ({css_x}, {css_y}) did not intersect any SoM Box.")
                    prompt_text = (f"The human operator intervened and clicked exactly at coordinates (X: {css_x}, Y: {css_y}). "
                                   f"There was no numbered SoM box at this location (AOM failure). "
                                   f"Analyze the raw visual area inside the green crosshair I have drawn at those coordinates "
                                   f"and generate a universal visual rule for the Playbook.")
                    image_to_send = annotate_image_with_crosshair(self.current_clean_screenshot, int(css_x), int(css_y))

                logging.info("Sending HITL learning package to Synthesizer Agent...")
                try:
                    session = get_resilient_session()
                    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}
                    client_id = self.client_context.get("client_id", "default") if self.client_context else "default"
                    domain = self.current_url.split('/')[2] if '//' in self.current_url else "unknown_domain"

                    synth_payload = {
                        "prompt": prompt_text,
                        "image_base64": image_to_send,
                        "domain": domain,
                        "client_id": client_id,
                        "failed_sub_task": self.sub_tasks[self.current_sub_task_index]
                    }

                    synth_url = f"{BACKEND_URL}/synthesize_playbook"
                    response = session.post(synth_url, json=synth_payload, headers=headers)
                    if response.ok:
                        logging.info("Synthesizer Agent successfully generated a new Playbook Rule!")
                    else:
                        logging.error(f"Synthesizer failed: {response.status_code} - {response.text}")
                except Exception as e:
                    logging.error(f"Error calling Synthesizer API: {e}")

                try:
                    logging.info(f"Executing HITL Ghost Click natively via Bridge at ({css_x}, {css_y})")
                    exec_payload = {
                        "action_type": "EXECUTE_ACTION",
                        "action": {
                            "action": "CLICK",
                            "coordinates": [css_x, css_y]
                        },
                        "iteration": self.iteration
                    }
                    exec_result = bridge.delegate_command(exec_payload)
                    if not exec_result.get("success"):
                        logging.error(f"Failed to execute Bridge click for HITL: {exec_result.get('error')}")
                except Exception as e:
                    logging.error(f"Failed to execute Bridge click for HITL: {e}")

            try:
                firestore_update_document("remote_commands", self.doc_id, {
                    "status": "in_progress"
                }, delete_fields=["human_response", "help_reason"])
            except Exception as e:
                logging.error(f"Failed to reset task status after HITL: {e}")

        self.hitl_action = None
        self.iteration += 1
        self.sub_task_iteration += 1
        self.state = AgentState.EVALUATING


def run_remote_agent_loop(doc_id: str, command_text: str, audio_b64: str = "", client_context: dict = None) -> None:
    global global_state_machine, global_asyncio_loop
    global_state_machine = AgentStateMachine()

    loop = asyncio.new_event_loop()
    global_asyncio_loop = loop
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(global_state_machine.run(doc_id, command_text, audio_b64, client_context))
    finally:
        loop.close()
        global_state_machine = None
        global_asyncio_loop = None


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

    client_context = load_client_profile()

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

        # 2. Command Routing via AI
        intent, command_text = classify_intent("", audio_b64)

        # If it's a web intent, pass to the Chrome Extension
        if intent == "WEB":
            logging.info("Voice command routed to Web (Chrome Extension). Starting ReAct loop.")
            from local_bridge import bridge

            iteration = 0
            doc_id = "voice_session_1"
            final_status = "completed"

            # Create or ensure the document exists
            try:
                firestore_update_document("remote_commands", doc_id, {
                    "status": "in_progress",
                    "command": "voice command"
                })
            except Exception as e:
                logging.error(f"Error setting up voice session document: {e}")

            # Pre-flight Check
            logging.info("Running Pre-Flight check...")
            pre_flight = pre_flight_check(command_text)
            if pre_flight.get("status") == "ASK_HUMAN":
                reason = pre_flight.get("reason", "Missing required information.")
                logging.info(f"Pre-flight failed: {reason}")
                try:
                    firestore_update_document("remote_commands", doc_id, {
                        "status": "AWAITING_HUMAN_INPUT",
                        "help_reason": reason
                    })
                except Exception as img_e:
                    logging.error(f"Error saving pre-flight help request: {img_e}")
                return

            # Supervisor Plan
            logging.info("Requesting Supervisor Plan...")
            sub_tasks = supervisor_plan(command_text)
            if not sub_tasks:
                sub_tasks = [command_text]  # fallback

            logging.info(f"Supervisor plan generated: {sub_tasks}")

            # Continuous Voice Session requires outer loop if multi-command
            # Stuck detector state
            history = []

            for sub_task_idx, current_sub_task in enumerate(sub_tasks):
                logging.info(f"--- Executing Sub-Task {sub_task_idx + 1}/{len(sub_tasks)}: {current_sub_task} ---")

                sub_task_iteration = 0
                max_sub_task_iterations = 5

                # Keep track of previous action state to verify in next iteration
                previous_action = None
                previous_state_metadata = None
                previous_state_ui = None

                while sub_task_iteration < max_sub_task_iterations:
                    break_outer = False
                    if ABORT_AGENT:
                        logging.info("Emergency abort triggered. Stopping voice agent loop.")
                        final_status = "failed"
                        break

                    if PAUSE_AGENT:
                        time.sleep(1)
                        continue

                    # Check for human response
                    try:
                        data = firestore_get_document("remote_commands", doc_id)
                        if data:
                            if data.get("status") in ["help_needed", "AWAITING_HUMAN_INPUT"]:
                                logging.info("Agent paused, waiting for human input...")
                                time.sleep(2)
                                continue

                            if data.get("human_response"):
                                command_text += "\nHuman instruction: " + data.get("human_response")
                                firestore_update_document("remote_commands", doc_id, {}, delete_fields=["human_response"])
                    except Exception as e:
                        logging.error(f"Error checking human response: {e}")

                    # 1. Ask extension for the current state
                    state_payload = {
                        "action_type": "GET_STATE",
                        "commandText": command_text,
                        "audioBase64": audio_b64 if iteration == 0 else "",
                        "iteration": iteration
                    }
                    logging.info(f"Requesting WEB state from extension (iteration {iteration})...")
                    state_result = bridge.delegate_command(state_payload)

                    if not state_result.get("success"):
                        logging.error(f"Failed to get state from extension: {state_result.get('error')}")
                        break

                    ui_elements = state_result.get("ui_elements", [])
                    screenshot_base64 = state_result.get("screenshot_base64", "")
                    current_url = state_result.get("url", "")

                    # Native Verification of Previous Action
                    if previous_action:
                        logging.info("Attempting Orchestrator-Level Native Verification of previous action...")
                        native_res = verify_action_natively(
                            previous_action,
                            {"metadata": previous_state_metadata, "ui_elements": previous_state_ui},
                            {"metadata": {"current_url": current_url}, "ui_elements": ui_elements}
                        )

                        if native_res.get("success"):
                            logging.info(f"Native verification succeeded: {native_res.get('reason')}")
                            command_text += f"\n[System Note: Action {previous_action.get('action', 'UNKNOWN')} verified successfully natively: {native_res.get('reason')}]"
                        else:
                            logging.info(f"Native verification didn't match: {native_res.get('reason')}")

                    # 2. Send state to backend to receive ONE OR MORE actions
                    payload = {
                        "ui_elements": ui_elements,
                        "session_id": doc_id,
                        "command_text": command_text,
                        "current_sub_task": current_sub_task,
                        "screenshot_base64": screenshot_base64,
                        "current_url": current_url,
                        "client_context": client_context
                    }
                    if sub_task_iteration == 0 and sub_task_idx == 0 and audio_b64:
                        payload["audio_base64"] = audio_b64
                    else:
                        payload["audio_base64"] = ""

                    headers = {
                        "Authorization": f"Bearer {CURRENT_TOKEN}",
                        "Content-Type": "application/json"
                    }

                    logging.info("Sending WEB state payload to backend...")
                    try:
                        max_retries = 3
                        retry_delay = 5
                        for attempt in range(max_retries):
                            try:
                                with get_resilient_session() as session:
                                    response = session.post(BACKEND_URL, json=payload, headers=headers, timeout=(15, 60))
                                response.raise_for_status()
                                backend_data = response.json()
                                break
                            except requests.exceptions.RequestException as req_err:
                                logging.warning(f"Network error on attempt {attempt + 1}/{max_retries}: {req_err}")
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    retry_delay *= 2
                                else:
                                    raise

                        if isinstance(backend_data, list):
                            actions = backend_data
                        elif isinstance(backend_data, dict):
                            actions = backend_data.get("actions", [])
                            if not actions and "action" in backend_data:
                                actions = [backend_data]
                        else:
                            logging.warning(f"Unexpected response type from backend: {type(backend_data)}")
                            actions = []

                        if not actions:
                            logging.info("No actions returned from backend. Considering task completed.")
                            break

                        has_typed_in_batch = False
                        for action_idx, act in enumerate(actions):
                            if ABORT_AGENT:
                                logging.info("Emergency abort triggered. Stopping voice agent loop.")
                                final_status = "failed"
                                break_outer = True
                                break

                            # Pre-check for target ID dynamically changing during batch
                            if action_idx > 0 and "target_id" in act:
                                # We need to fetch the state to ensure the target_id is still valid.
                                # But getting the full state is slow, so we rely on the extension execution
                                # to fail if the ID is missing. But let's verify if we need to bailout
                                pass

                            save_flight_record(doc_id, iteration, payload, backend_data, act, screenshot_base64)
                            if not isinstance(act, dict):
                                logging.warning(f"Skipping invalid action type: {type(act)}")
                                continue

                            action_type = act.get("action", "")
                            action_upper = str(action_type).upper()

                            if action_upper == "TYPE":
                                has_typed_in_batch = True

                            # Intercept premature sub-task completions to enforce Stable State Law
                            if action_upper == "SUB_TASK_COMPLETE" and has_typed_in_batch:
                                logging.warning("Systemic Safety Intercept: Dropping SUB_TASK_COMPLETE because a TYPE action occurred in this batch. Forcing a state check for dynamic overlays.")
                                break

                            logging.info(f"Backend returned action [{action_idx+1}/{len(actions)}]: {action_upper}")

                            # Stuck Detector Logic
                            # We only append to history on the first action of the batch to avoid triggering false positives
                            if action_idx == 0:
                                history.append(payload.get("ui_elements", []))
                                if len(history) > 5:
                                    history.pop(0)

                                if len(history) == 5:
                                    u1, u2, u3, u4, u5 = history
                                    if u1 == u2 == u3 == u4 == u5:
                                        logging.warning("Stuck Detector triggered! State (ui_elements) remained identical for 5 consecutive iterations.")
                                        reason = f"I am stuck trying to execute: [{current_sub_task}]. Please assist."
                                        try:
                                            firestore_update_document("remote_commands", doc_id, {
                                                "status": "AWAITING_HUMAN_INPUT",
                                                "help_reason": reason,
                                                "screenshot_b64": screenshot_base64
                                            })
                                        except Exception as img_e:
                                            logging.error(f"Error saving stuck detector help request: {img_e}")
                                        final_status = "AWAITING_HUMAN_INPUT"
                                        break_outer = True
                                        break


                            if action_upper == "SUB_TASK_COMPLETE":
                                logging.info(f"Sub-task completed: {current_sub_task}")
                                break_outer = True
                                break
                            elif action_upper == "DONE":
                                logging.info("Web task finished successfully.")
                                break_outer = True
                                break
                            elif "ERROR" in action_upper:
                                raw_response = act.get("raw_response", "No raw response provided")
                                error_msg = act.get("error", "No error message provided")
                                logging.error(f"Web agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                                final_status = "failed"
                                break_outer = True
                                break
                            elif action_upper == "WAIT":
                                wait_seconds = float(act.get("seconds", 2))
                                logging.info(f"Agent requested WAIT for {wait_seconds} seconds.")
                                time.sleep(wait_seconds)
                                # No need to delegate to extension, just sleep locally and loop will get fresh state next
                                break
                            elif action_upper == "ASK_HUMAN":
                                reason = act.get("reason", "No reason provided")
                                logging.info(f"Agent asking human for help: {reason}")
                                try:
                                    firestore_update_document("remote_commands", doc_id, {
                                        "status": "AWAITING_HUMAN_INPUT",
                                        "help_reason": reason,
                                        "screenshot_b64": screenshot_base64
                                    })
                                except Exception as img_e:
                                    logging.error(f"Error saving help request: {img_e}")

                                final_status = "AWAITING_HUMAN_INPUT"
                                break_outer = True
                                break

                            # 3. Delegate action to the extension
                            exec_payload = {
                                "action_type": "EXECUTE_ACTION",
                                "action": act
                            }
                            logging.info("Delegating action to extension...")
                            exec_result = bridge.delegate_command(exec_payload)

                            if not exec_result.get("success"):
                                logging.error(f"Failed to execute action in extension: {exec_result.get('error')}")
                                # Safety Bailout: Abort the rest of the batch and trigger a fresh GET_STATE
                                logging.info("Safety Bailout: Action failed. Aborting remaining batch actions and fetching new state.")
                                break

                            if action_upper == "EXECUTE_JS":
                                js_result = exec_result.get("result")
                                logging.info(f"JS Execution Result: {js_result}")
                                command_text += f"\n[System Note: Last EXECUTE_JS returned: {js_result}]"

                            # Save state for verification in next iteration
                            previous_action = act
                            previous_state_metadata = {"current_url": current_url}
                            previous_state_ui = ui_elements

                            if action_idx < len(actions) - 1:
                                # Micro-sleep between sequential actions
                                time.sleep(0.5)

                    except requests.exceptions.RequestException as req_e:
                        if isinstance(req_e, requests.exceptions.HTTPError) and req_e.response.status_code == 401:
                            handle_token_expiry()
                            break_outer = True
                            break
                        logging.info(f"Request failed: {req_e}")
                        break_outer = True
                        break

                    if break_outer:
                        break

                    time.sleep(1)
                    iteration += 1
                    sub_task_iteration += 1

                # Subtask retry limit reached
                if sub_task_iteration >= max_sub_task_iterations:
                    logging.error(f"Max retries reached for sub-task: {current_sub_task}")
                    final_status = "failed"
                    break

                if final_status != "completed":
                    break

            # Update final document status
            try:
                if final_status != "AWAITING_HUMAN_INPUT":
                    update_payload = {"status": final_status}
                    if final_status == "failed" and "error_msg" in locals():
                        update_payload["error"] = error_msg
                    firestore_update_document("remote_commands", doc_id, update_payload)
                    logging.info(f"Remote command {doc_id} marked as {final_status} from Web execution.")
            except Exception as e:
                pass

            # Finish voice loop for Web
            return

        # Start Agentic Loop for OS
        logging.info("Voice command routed to OS (Native).")
        iteration = 0
        doc_id = "voice_session_1"
        final_status = "completed"

        # Pre-flight Check
        logging.info("Running Pre-Flight check...")
        pre_flight = pre_flight_check(command_text)
        if pre_flight.get("status") == "ASK_HUMAN":
            reason = pre_flight.get("reason", "Missing required information.")
            logging.info(f"Pre-flight failed: {reason}")
            try:
                firestore_update_document("remote_commands", doc_id, {
                    "status": "AWAITING_HUMAN_INPUT",
                    "help_reason": reason
                })
            except Exception as img_e:
                logging.error(f"Error saving pre-flight help request: {img_e}")
            return

        # Supervisor Plan
        logging.info("Requesting Supervisor Plan...")
        sub_tasks = supervisor_plan(command_text)
        if not sub_tasks:
            sub_tasks = [command_text]  # fallback

        logging.info(f"Supervisor plan generated: {sub_tasks}")

        # Stuck detector state
        history = []

        # Create or ensure the document exists
        try:
            # For set with merge = true using REST we can just patch
            firestore_update_document("remote_commands", doc_id, {
                "status": "in_progress",
                "command": "voice command"
            })
        except Exception as e:
            logging.error(f"Error setting up voice session document: {e}")

        for sub_task_idx, current_sub_task in enumerate(sub_tasks):
            logging.info(f"--- Executing Sub-Task {sub_task_idx + 1}/{len(sub_tasks)}: {current_sub_task} ---")

            sub_task_iteration = 0
            max_sub_task_iterations = 5

            while sub_task_iteration < max_sub_task_iterations:
                break_outer = False
                if ABORT_AGENT:
                    logging.info("Emergency abort triggered. Stopping voice agent loop.")
                    final_status = "failed"
                    break

                if PAUSE_AGENT:
                    time.sleep(1)
                    continue

            # Check for human response
            try:
                fs_doc = firestore_get_document("remote_commands", doc_id)
                if fs_doc:
                    if fs_doc.get("status") in ["help_needed", "AWAITING_HUMAN_INPUT"]:
                        logging.info("Agent paused, waiting for human input...")
                        time.sleep(2)
                        continue

                    if fs_doc.get("human_response"):
                        command_text += "\nHuman instruction: " + fs_doc.get("human_response")
                        firestore_update_document("remote_commands", doc_id, {}, delete_fields=["human_response"])
            except Exception as e:
                logging.error(f"Error checking human response: {e}")

            # 3. Scan UI Elements
            ui_elements, memory_map = scan_ui_elements()

            # 4. Construct JSON payload
            payload = {
                "ui_elements": ui_elements,
                "session_id": doc_id,
                "command_text": command_text,
                "current_sub_task": current_sub_task,
                "client_context": client_context
            }
            if sub_task_iteration == 0 and sub_task_idx == 0 and audio_b64:
                payload["audio_base64"] = audio_b64
            else:
                payload["audio_base64"] = ""

            # 5. Send POST to backend
            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            logging.info(f"Sending payload to backend (iteration {iteration})...")
            try:
                max_retries = 3
                retry_delay = 5
                for attempt in range(max_retries):
                    try:
                        with get_resilient_session() as session:
                            response = session.post(BACKEND_URL, json=payload, headers=headers, timeout=(15, 60))
                        response.raise_for_status()
                        backend_data = response.json()
                        break
                    except requests.exceptions.RequestException as req_err:
                        logging.warning(f"Network error on attempt {attempt + 1}/{max_retries}: {req_err}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            raise

                # 6. Check response
                if isinstance(backend_data, list):
                    actions = backend_data
                elif isinstance(backend_data, dict):
                    actions = backend_data.get("actions", [])
                    if not actions and "action" in backend_data:
                        actions = [backend_data]
                else:
                    logging.warning(f"Unexpected response type from backend: {type(backend_data)}")
                    actions = []

                break_outer = False
                had_terminal_action = False
                for act in actions:
                    if not isinstance(act, dict):
                        logging.warning(f"Skipping invalid action type: {type(act)}")
                        continue

                    # Capture OS screenshot for flight record
                    try:
                        screenshot = pyautogui.screenshot()
                        buffered = io.BytesIO()
                        screenshot.save(buffered, format="PNG")
                        os_screenshot_b64 = base64.b64encode(buffered.getvalue()).decode()
                    except Exception:
                        os_screenshot_b64 = ""

                    save_flight_record(doc_id, iteration, payload, backend_data, act, os_screenshot_b64)

                    if ABORT_AGENT:
                        logging.info("Emergency abort triggered during action sequence.")
                        break_outer = True
                        break

                    action_type = act.get("action", "")
                    action_upper = str(action_type).upper()

                    # Stuck Detector Logic
                    if act == actions[0]:
                        history.append(payload.get("ui_elements", []))
                        if len(history) > 5:
                            history.pop(0)

                        if len(history) == 5:
                            u1, u2, u3, u4, u5 = history
                            if u1 == u2 == u3 == u4 == u5:
                                logging.warning("Stuck Detector triggered! State (ui_elements) remained identical for 5 consecutive iterations.")
                                reason = f"I am stuck trying to execute: [{current_sub_task if 'current_sub_task' in locals() else 'OS command'}]. Please assist."
                                try:
                                    firestore_update_document("remote_commands", doc_id, {
                                        "status": "AWAITING_HUMAN_INPUT",
                                        "help_reason": reason,
                                        "screenshot_b64": os_screenshot_b64
                                    })
                                except Exception as img_e:
                                    logging.error(f"Error saving stuck detector help request: {img_e}")
                                final_status = "AWAITING_HUMAN_INPUT"
                                had_terminal_action = True
                                break_outer = True
                                break

                    if action_upper == "SUB_TASK_COMPLETE":
                        logging.info(f"Sub-task completed: {current_sub_task}")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif action_upper == "DONE":
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
                                "status": "AWAITING_HUMAN_INPUT",
                                "help_reason": reason,
                                "screenshot_b64": img_str
                            })
                        except Exception as img_e:
                            logging.error(f"Error capturing screenshot: {img_e}")
                            firestore_update_document("remote_commands", doc_id, {
                                "status": "AWAITING_HUMAN_INPUT",
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


import http.server
import socketserver
import urllib.parse
from http import HTTPStatus

class LocalAPIHandler(http.server.BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/run_command':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))
                doc_id = data.get("doc_id")
                command_text = data.get("command_text", "")
                client_context = data.get("client_context")

                if not doc_id or not command_text:
                    self.send_response(HTTPStatus.BAD_REQUEST)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Missing doc_id or command_text"}).encode())
                    return

                # Update status locally to pending immediately
                LOCAL_STATUS[doc_id] = "pending"

                # Push dummy document to Firestore to make it appear in the dashboard's live feed
                # since the live feed queries remote_commands with a created_at timestamp
                try:
                    uid = _get_uid_from_token()
                    if uid:
                        # Use local time for timestamp in REST API if serverTimestamp() is not available
                        now_str = datetime.utcnow().isoformat() + "Z"
                        firestore_update_document("remote_commands", doc_id, {
                            "uid": uid,
                            "command": command_text,
                            "status": "pending",
                            "created_at": now_str
                        })
                except Exception as e:
                    logging.error(f"Failed to create dummy remote command document for local API run: {e}")

                command_payload = {
                    "type": "remote",
                    "doc_id": doc_id,
                    "command_text": command_text,
                    "audio_b64": ""
                }

                if client_context:
                    command_payload["client_context"] = client_context

                COMMAND_QUEUE.put(command_payload)

                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "queued", "doc_id": doc_id}).encode())

            except json.JSONDecodeError:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
        elif self.path == '/api/human_guidance':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))
                global ACTIVE_DOC_ID

                if ACTIVE_DOC_ID:
                    if global_state_machine and global_state_machine.state == AgentState.SUSPENDED_HITL:
                        xpath = data.get("xpath", "Unknown element")
                        x = data.get("x")
                        y = data.get("y")
                        dpr = data.get("dpr", 1.0)

                        if x is not None and y is not None:
                            guidance = f"Click at (X: {x}, Y: {y})"
                        else:
                            guidance = f"Click the element with XPath: {xpath}"

                        firestore_update_document("remote_commands", ACTIVE_DOC_ID, {
                            "status": "in_progress",
                            "human_response": guidance
                        })
                        logging.info(f"Teleoperation ghost click registered for doc {ACTIVE_DOC_ID}: {guidance}")

                        def set_event():
                            global_state_machine.hitl_action = data
                            global_state_machine.hitl_event.set()

                        if global_asyncio_loop:
                            global_asyncio_loop.call_soon_threadsafe(set_event)

                        self.send_response(HTTPStatus.OK)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "ok"}).encode())
                        return
                    else:
                        logging.info("Ignored ghost click: Agent not in SUSPENDED_HITL state.")
                        self.send_response(HTTPStatus.OK)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "ignored"}).encode())
                        return
                else:
                    self.send_response(HTTPStatus.BAD_REQUEST)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "No active task"}).encode())
            except json.JSONDecodeError:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            except Exception as e:
                logging.error(f"Error processing human guidance: {e}")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif self.path == '/api/focus_tab':
            try:
                from local_bridge import bridge
                exec_payload = {
                    "action_type": "EXECUTE_ACTION",
                    "action": {"action": "FOCUS_TAB"}
                }
                bridge.delegate_command(exec_payload)
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            except Exception as e:
                logging.error(f"Error focusing tab: {e}")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path.startswith('/api/status/'):
            doc_id = parsed_path.path.split('/')[-1]
            status = LOCAL_STATUS.get(doc_id, "unknown")

            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"doc_id": doc_id, "status": status}).encode())
        elif parsed_path.path == '/api/ping':
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        elif parsed_path.path == '/api/playbook_rules':
            # Extract domain and client_id from query params
            query_params = urllib.parse.parse_qs(parsed_path.query)
            domain = query_params.get('domain', [''])[0]
            client_id = query_params.get('client_id', [''])[0]

            if not domain:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing domain parameter"}).encode())
                return

            if not CURRENT_TOKEN:
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                return

            base_url = BACKEND_URL.split("/api/v1")[0] if "/api/v1" in BACKEND_URL else BACKEND_URL.rsplit('/', 1)[0]
            if not base_url.endswith("/"):
                base_url += "/"

            backend_url = f"{base_url.rstrip('/')}/api/playbook_rules?domain={urllib.parse.quote(domain)}"
            if client_id:
                backend_url += f"&client_id={urllib.parse.quote(client_id)}"

            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            try:
                with get_resilient_session() as session:
                    response = session.get(backend_url, headers=headers, timeout=10)
                response.raise_for_status()

                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(response.content)
            except Exception as e:
                logging.error(f"Error fetching playbook rules from backend: {e}")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            # Try to serve static files from web/public
            import mimetypes

            # Map paths
            filepath = parsed_path.path
            if filepath == '/':
                filepath = '/index.html'

            # Construct absolute path to web/public directory
            # Assuming agent.py is in client/
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            public_dir = os.path.join(base_dir, 'web', 'public')

            # Remove leading slash for os.path.join
            if filepath.startswith('/'):
                filepath = filepath[1:]

            full_path = os.path.abspath(os.path.join(public_dir, filepath))

            # Security check to prevent path traversal
            if not full_path.startswith(os.path.abspath(public_dir)):
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
                return

            if os.path.exists(full_path) and os.path.isfile(full_path):
                try:
                    with open(full_path, 'rb') as f:
                        content = f.read()

                    content_type, _ = mimetypes.guess_type(full_path)
                    if not content_type:
                        content_type = 'application/octet-stream'

                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-type', content_type)
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as e:
                    self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            else:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not found"}).encode())

def start_local_api(port=8764):
    """Starts the local API server in a daemon thread."""
    def run_server():
        try:
            with socketserver.TCPServer(("127.0.0.1", port), LocalAPIHandler) as httpd:
                logging.info(f"Started Local API Server on http://127.0.0.1:{port}")
                httpd.serve_forever()
        except OSError as e:
            logging.error(f"Failed to start Local API Server: {e}")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
