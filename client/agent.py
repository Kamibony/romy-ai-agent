import logging
import base64
import io
import time
import os
import re
import hashlib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import queue
import json
import threading
from datetime import datetime
from pydantic import BaseModel, ValidationError, Field
from typing import Optional

import io
import base64
from PIL import Image, ImageDraw, ImageFont
import asyncio
import traceback
from enum import Enum

try:
    import uiautomation as auto
    import ctypes
    # Enforce DPI awareness for accurate coordinates
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception as e:
    logging.warning(f"Could not set DPI awareness or import uiautomation: {e}")

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

import config
import os

# Dynamically inject the correct bridge based on the environment
if os.environ.get("ROMY_TEST_MODE") == "1":
    try:
        from tests.integration.test_sop_loop import MockExtensionBridge
        bridge = MockExtensionBridge("<html><body></body></html>")
    except ImportError:
        pass
else:
    pass



CURRENT_TOKEN = None

COMMAND_QUEUE = queue.Queue()
PROCESSED_DOC_IDS = set()
global_state_machine = None
global_asyncio_loop = None


class AgentState(Enum):
    INITIALIZING = "INITIALIZING"
    EVALUATING = "EVALUATING"
    THINKING = "THINKING"
    ACTING = "ACTING"
    SUSPENDED_HITL = "SUSPENDED_HITL"
    TRAINING_NEEDED = "TRAINING_NEEDED"
    LEARNING_ROUTINE = "LEARNING_ROUTINE"
    SELF_HEALING = "SELF_HEALING"
    TERMINATED = "TERMINATED"

ABORT_AGENT = False
PAUSE_AGENT = False
ACTIVE_DOC_ID = None

LOCAL_STATUS = {} # Dictionary to store local task statuses mapping doc_id to status

def save_flight_record(doc_id: str, iteration: int, payload: dict, response: dict, action_executed: dict, screenshot_b64: str, system_state: dict = None) -> None:
    """Saves a timestamped record of the ReAct cycle locally for debugging."""
    try:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base_dir = os.path.join(local_app_data, "RomyAgentBrowserData")
        else:
            # Fallback if LOCALAPPDATA is not set (e.g., Linux/macOS or restricted environments)
            # Use the root of the project by going up from client/agent.py
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "RomyAgentBrowserData"))

        user_data_dir = os.path.join(base_dir, "flight_records", doc_id)
        os.makedirs(user_data_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record_file = os.path.join(user_data_dir, f"record_{iteration}_{timestamp}.json")

        # Fallbacks for missing/uninitialized attributes
        safe_payload = payload if payload is not None else {}
        safe_response = response if response is not None else {}
        safe_action = action_executed if action_executed is not None else {}
        safe_system_state = system_state if system_state is not None else {}

        record_data = {
            "timestamp": datetime.now().isoformat(),
            "doc_id": doc_id,
            "iteration": iteration,
            "system_state": safe_system_state,
            "prompt_payload": safe_payload,
            "llm_response": safe_response,
            "action_executed": safe_action
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

def sanitize_extracted_parameter(val: str, param_type: str = "text") -> str:
    """Systemic Fix: Context-aware sanitization of LLM-extracted parameters to strip stray trailing punctuation."""
    if not isinstance(val, str):
        return val

    val = val.strip()

    if param_type == "url":
        # Unconditionally sanitize known URL structures
        return re.sub(r'[.,;!?\'"]+$', '', val)

    if param_type == "text":
        # 1. Structural matches (Email or URL-like strings)
        if "@" in val or val.startswith("www.") or val.startswith("http"):
            return re.sub(r'[.,;!?\'"]+$', '', val)

        # 2. Purely numeric strings (allowing internal formatting but stripping trailing artifacts)
        # e.g. "12345." -> "12345", "1,000;" -> "1,000"
        if re.match(r'^[\d\s,]+[.,;!?\'"]+$', val):
            return re.sub(r'[.,;!?\'"]+$', '', val)

        # 3. Short search terms (1-3 words) with trailing punctuation, avoiding common abbreviations
        words = val.split()
        if len(words) <= 3 and len(val) > 0 and val[-1] in ".,;!?'\"":
            if val.lower() not in ["dr.", "mr.", "mrs.", "ms.", "inc.", "ltd.", "co.", "corp.", "st.", "rd.", "ave."]:
                return re.sub(r'[.,;!?\'"]+$', '', val)

    return val

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

_GLOBAL_SESSION = None

def get_resilient_session() -> requests.Session:
    """Returns a global requests.Session configured with exponential backoff and retries."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is None:
        _GLOBAL_SESSION = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,  # 1s, 2s, 4s, 8s, 16s
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PATCH", "PUT", "DELETE"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _GLOBAL_SESSION.mount("https://", adapter)
        _GLOBAL_SESSION.mount("http://", adapter)
    return _GLOBAL_SESSION

def authenticated_request(method: str, url: str, **kwargs) -> requests.Response:
    """Performs an authenticated request with silent token refresh on 401 and exponential backoff for connection errors."""
    session = get_resilient_session()

    headers = kwargs.get('headers', {})
    if "Authorization" not in headers and CURRENT_TOKEN:
        headers["Authorization"] = f"Bearer {CURRENT_TOKEN}"
    kwargs['headers'] = headers

    max_retries = 3
    retry_delay = 2

    # Add a global timeout if not explicitly provided
    if 'timeout' not in kwargs:
        kwargs['timeout'] = (10, 60) # (connect timeout, read timeout)

    for attempt in range(max_retries):
        try:
            response = session.request(method, url, **kwargs)

            if response.status_code == 401:
                logging.warning(f"Unauthorized (401) during {method} {url}. Attempting silent token refresh...")
                try:
                    pass
                    new_token = bridge.request_fresh_token()
                    if new_token:
                        set_firebase_token(new_token)
                        headers["Authorization"] = f"Bearer {new_token}"
                        kwargs['headers'] = headers
                        logging.info("Token refreshed successfully. Retrying request...")
                        response = session.request(method, url, **kwargs)
                    else:
                        handle_token_expiry()
                        return response
                except Exception as e:
                    logging.error(f"Error during silent token refresh: {e}")
                    handle_token_expiry()
                    return response

            return response
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logging.warning(f"Network error (Connection/Timeout) during {method} {url} on attempt {attempt+1}: {e}")
            if attempt < max_retries - 1:
                logging.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logging.error(f"Max retries reached for {method} {url}.")
                raise


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
            # Universally format ISO 8601 strings to timestampValue to enforce strict schema consistency
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?$", val):
                # Firestore REST requires 'Z' at the end for UTC timestamps
                if not val.endswith("Z"):
                    val += "Z"
                fields[key] = {"timestampValue": val}
            else:
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
            # Using authenticated request for silent token refresh
            response = authenticated_request("PATCH", url, json=payload, headers=headers, timeout=10)
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
        response = authenticated_request("GET", url, headers=headers, timeout=10)
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
            elif "timestampValue" in val_dict:
                result[key] = val_dict["timestampValue"]
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
        return payload.get('user_id') or payload.get('sub')
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
        global _GLOBAL_SESSION
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

                        if doc_id in PROCESSED_DOC_IDS:
                            continue
                        PROCESSED_DOC_IDS.add(doc_id)

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
                    if _GLOBAL_SESSION:
                        _GLOBAL_SESSION.close()
                        _GLOBAL_SESSION = None
                    session = get_resilient_session()
                    logging.warning("Re-initializing resilient requests session due to repeated errors.")
            except requests.exceptions.RequestException as e:
                error_count += 1
                logging.error(f"Network error in remote listener poll (attempt {error_count}): {e}")
                # Re-initialize session on network errors to clear potentially bad sockets
                if error_count >= 3:
                    if _GLOBAL_SESSION:
                        _GLOBAL_SESSION.close()
                        _GLOBAL_SESSION = None
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


import concurrent.futures
import queue
import threading
import random

class DesktopEnvironment:
    """Wrapper to handle thread-blocking OS automation tasks securely with a dedicated daemon thread."""
    def __init__(self):
        self.task_queue = queue.Queue()
        self.native_controls = {}  # Store COM objects for setting focus
        self.daemon_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.daemon_thread.start()

    def _worker_loop(self):
        # Initialize COM once on the dedicated thread
        com_initialized = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com_initialized = True
            logging.info("COM successfully initialized on DesktopEnvironment worker thread.")
        except ImportError:
            try:
                import ctypes
                ctypes.windll.ole32.CoInitialize(None)
                com_initialized = True
                logging.info("COM successfully initialized on DesktopEnvironment worker thread via ctypes.")
            except Exception as e:
                logging.warning(f"Could not initialize COM: {e}")

        while True:
            task = self.task_queue.get()
            if task is None:
                # Stop signal
                break

            func, args, kwargs, future = task
            try:
                result = func(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                self.task_queue.task_done()

        if com_initialized:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except ImportError:
                try:
                    import ctypes
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

    def _submit_task(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        # We need a synchronous future for the worker thread to set,
        # which we then resolve the asyncio future with.
        sync_future = concurrent.futures.Future()

        def _resolve_async_future(fut):
            try:
                result = fut.result()
                loop.call_soon_threadsafe(future.set_result, result)
            except Exception as e:
                loop.call_soon_threadsafe(future.set_exception, e)

        sync_future.add_done_callback(_resolve_async_future)

        self.task_queue.put((func, args, kwargs, sync_future))
        return future

    async def check_occlusion(self) -> dict:
        return await self._submit_task(self._sync_check_occlusion)

    def _sync_check_occlusion(self) -> dict:
        try:
            active_window = auto.GetForegroundControl()
            if not active_window:
                return {"occluded": False}
            name = active_window.Name
            class_name = active_window.ClassName

            # Detect native OS dialogs or popups that block the main browser window
            is_dialog = False
            # #32770 is the standard Win32 dialog box class (File Open/Save, Print, Alerts)
            if class_name == '#32770':
                is_dialog = True
            # Chrome native popups (Print, Open, Save) sometimes appear as Chrome_WidgetWin_1
            elif class_name == 'Chrome_WidgetWin_1' and name in ['Open', 'Save As', 'Print']:
                is_dialog = True

            if is_dialog:
                return {"occluded": True, "name": name, "class_name": class_name}
        except Exception as e:
            logging.debug(f"Error checking occlusion: {e}")
        return {"occluded": False}

    async def scan_ui_elements(self) -> Tuple[list[Dict[str, Any]], Dict[str, Dict[str, int]], str, str]:
        return await self._submit_task(self._sync_scan)

    def _sync_scan(self) -> Tuple[list[Dict[str, Any]], Dict[str, Dict[str, int]], str, str]:
        ui_elements = []
        memory_map = {}
        window_name = "OS_Environment"
        self.native_controls.clear()

        try:
            # Enforce strict Active Window Pruning
            active_window = auto.GetForegroundControl()
            if not active_window:
                active_window = auto.GetRootControl()

            try:
                window_name = active_window.Name
            except Exception:
                pass

            logging.info(f"Scanning UI tree for window: {window_name}")

            element_id = 1
            # Filter generic control types to reduce noise
            target_types = ['ButtonControl', 'HyperlinkControl', 'TextControl', 'EditControl', 'MenuItemControl', 'ListItemControl', 'TabItemControl', 'DocumentControl', 'CheckBoxControl']

            for walk_result in auto.WalkTree(active_window, getChildren=lambda c: c.GetChildren(), includeTop=True, maxDepth=15):
                if isinstance(walk_result, (tuple, list)):
                    control = walk_result[0] if len(walk_result) > 0 else None
                else:
                    control = walk_result

                if not control:
                    continue

                try:
                    control_type = control.ControlTypeName
                    name = control.Name
                except Exception:
                    continue

                if control_type in target_types:
                    try:
                        rect = control.BoundingRectangle
                        if rect and rect.width() > 0 and rect.height() > 0:
                            center_x = rect.left + rect.width() // 2
                            center_y = rect.top + rect.height() // 2

                            element_str_id = str(element_id)

                            # Standardize output for LLM
                            el_data = {
                                "id": element_str_id,
                                "type": control_type,
                                "name": name,
                                "bounds": {
                                    "x": rect.left,
                                    "y": rect.top,
                                    "width": rect.width(),
                                    "height": rect.height()
                                },
                                "center": {"x": center_x, "y": center_y}
                            }
                            ui_elements.append(el_data)
                            memory_map[element_str_id] = el_data
                            self.native_controls[element_str_id] = control
                            element_id += 1
                    except Exception:
                        continue

            logging.info(f"Found {len(ui_elements)} interactive OS UI elements.")
        except Exception as e:
            logging.error(f"Error scanning OS UI tree: {e}")

        clipboard_status = "empty"
        try:
            # Avoid focus-stealing by using ctypes to check clipboard without creating a GUI window
            import ctypes
            user32 = ctypes.windll.user32
            if user32.OpenClipboard(0):
                # Format 1 is CF_TEXT, 13 is CF_UNICODETEXT
                if user32.IsClipboardFormatAvailable(13) or user32.IsClipboardFormatAvailable(1):
                    clipboard_status = "contains text"
                elif user32.CountClipboardFormats() > 0:
                    clipboard_status = "contains data (non-text)"
                user32.CloseClipboard()
        except Exception as e:
            logging.debug(f"Failed to read clipboard status via ctypes: {e}")
            # Fallback to pyperclip if installed, which might use different mechanisms
            try:
                import pyperclip
                if pyperclip.paste():
                    clipboard_status = "contains text"
                else:
                    clipboard_status = "empty or non-text"
            except Exception:
                clipboard_status = "unknown"

        return ui_elements, memory_map, window_name, clipboard_status

    async def click(self, x: int, y: int, dpr: float = 1.0):
        await self._submit_task(self._sync_click, x, y, dpr)

    def _sync_click(self, x, y, dpr=1.0):
        try:
            x, y = int(x * dpr), int(y * dpr)
            if config.STEALTH_MODE:
                duration = random.uniform(0.15, 0.45)
                # Use a basic tween if available, otherwise default
                tween = pyautogui.easeInOutQuad if hasattr(pyautogui, 'easeInOutQuad') else pyautogui.linear
                pyautogui.moveTo(x, y, duration=duration, tween=tween)
                time.sleep(random.uniform(0.05, 0.15))
            else:
                pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()
        except Exception as e:
            logging.error(f"Error clicking at ({x}, {y}): {e}")

    async def type(self, x: int, y: int, text: str, submit: bool = False, target_id: Optional[str] = None, dpr: float = 1.0):
        await self._submit_task(self._sync_type, x, y, text, submit, target_id, dpr)

    async def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int, dpr: float = 1.0):
        await self._submit_task(self._sync_drag_and_drop, start_x, start_y, end_x, end_y, dpr)

    def _sync_drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int, dpr: float = 1.0):
        try:
            start_x, start_y = int(start_x * dpr), int(start_y * dpr)
            end_x, end_y = int(end_x * dpr), int(end_y * dpr)
            if config.STEALTH_MODE:
                tween = pyautogui.easeInOutQuad if hasattr(pyautogui, 'easeInOutQuad') else pyautogui.linear
                pyautogui.moveTo(start_x, start_y, duration=random.uniform(0.15, 0.45), tween=tween)
                time.sleep(random.uniform(0.05, 0.15))
                pyautogui.mouseDown()
                time.sleep(random.uniform(0.05, 0.1))
                pyautogui.moveTo(end_x, end_y, duration=random.uniform(0.3, 0.8), tween=tween)
                time.sleep(random.uniform(0.05, 0.1))
                pyautogui.mouseUp()
            else:
                pyautogui.moveTo(start_x, start_y, duration=0.2)
                pyautogui.mouseDown()
                pyautogui.moveTo(end_x, end_y, duration=0.5)
                pyautogui.mouseUp()
        except Exception as e:
            logging.error(f"Error executing drag and drop from ({start_x}, {start_y}) to ({end_x}, {end_y}): {e}")

    def _sync_type(self, x, y, text, submit, target_id=None, dpr=1.0):
        try:
            x, y = int(x * dpr), int(y * dpr)
            # Kinematic Fix: Physical click is mandatory to guarantee focus before typing,
            # especially since programmatic SetFocus() often fails on complex OS UI frameworks.
            if config.STEALTH_MODE:
                duration = random.uniform(0.15, 0.45)
                tween = pyautogui.easeInOutQuad if hasattr(pyautogui, 'easeInOutQuad') else pyautogui.linear
                pyautogui.moveTo(x, y, duration=duration, tween=tween)
                time.sleep(random.uniform(0.05, 0.15))
            else:
                pyautogui.moveTo(x, y, duration=0.2)

            pyautogui.click()
            time.sleep(0.1) # Short physical cooldown after click

            if target_id and target_id in self.native_controls:
                try:
                    control = self.native_controls[target_id]
                    control.SetFocus()
                    logging.info(f"Programmatically focused OS control ID: {target_id} as secondary fallback.")
                    time.sleep(0.1)
                except Exception as e:
                    logging.warning(f"Failed to programmatically focus control {target_id}: {e}")

            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            time.sleep(0.1)

            if config.STEALTH_MODE:
                for char in text:
                    pyautogui.write(char)
                    time.sleep(random.uniform(0.02, 0.08))
            else:
                pyautogui.write(text, interval=0.01)

            if submit:
                if config.STEALTH_MODE:
                    time.sleep(random.uniform(0.1, 0.3))
                pyautogui.press('enter')
        except Exception as e:
            logging.error(f"Error typing '{text}' at ({x}, {y}): {e}")

    async def screenshot(self):
        return await self._submit_task(self._sync_screenshot)

    def _sync_screenshot(self):
        try:
            screenshot = pyautogui.screenshot()
            if screenshot.width > 1920:
                new_width = 1920
                new_height = int(screenshot.height * (1920 / screenshot.width))
                screenshot = screenshot.resize((new_width, new_height), Image.Resampling.LANCZOS)
            buffered = io.BytesIO()
            screenshot.convert("RGB").save(buffered, format="JPEG", quality=60)
            return buffered.getvalue()
        except Exception as e:
            logging.error(f"Error capturing OS screenshot: {e}")
            return b""

    def close(self):
        self.task_queue.put(None)
        self.daemon_thread.join()

desktop_env = DesktopEnvironment()


def annotate_image_with_som(img_data: bytes, ui_elements: list, dpr: float = 1.0) -> bytes:
    """Draws Set-of-Mark numbered bounding boxes over interactive elements."""
    if not img_data:
        return b""
    try:
        image = Image.open(io.BytesIO(img_data)).convert("RGBA")
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.load_default()
        except:
            font = None

        for el in ui_elements:
            box = el.get("bounds")
            target_id = el.get("target_id", el.get("id"))

            if box and target_id is not None:
                try:
                    if isinstance(box, dict):
                        bx = box.get("x", 0)
                        by = box.get("y", 0)
                        bwidth = box.get("width", 0)
                        bheight = box.get("height", 0)
                    elif isinstance(box, list) and len(box) == 4:
                        bx, by, bwidth, bheight = box
                    else:
                        continue

                    # Scale CSS pixels to Physical pixels for the screenshot
                    x = int(bx * dpr)
                    y = int(by * dpr)
                    width = int(bwidth * dpr)
                    height = int(bheight * dpr)

                    if width <= 0 or height <= 0:
                        continue

                    # Standardize coordinates to prevent mathematical errors (y1 < y0)
                    x0, y0 = x, y
                    x1, y1 = max(x0 + 1, x + width), max(y0 + 1, y + height)

                    draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0, 255), width=2)
                    text = f" [{target_id}] "
                    if hasattr(font, 'getbbox'):
                        bbox = font.getbbox(text)
                        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    else:
                        tw, th = len(text) * 6, 12

                    label_y0 = max(0, y0 - th)
                    label_y1 = max(label_y0 + 1, y0)
                    label_x1 = max(x0 + 1, x0 + tw)

                    draw.rectangle([x0, label_y0, label_x1, label_y1], fill=(255, 0, 0, 255))
                    draw.text((x0, label_y0), text, fill=(255, 255, 255, 255), font=font)
                except Exception as e:
                    logging.warning(f"Error drawing SoM box for ID {target_id}: {e}")

        buffered = io.BytesIO()
        image.convert("RGB").save(buffered, format="JPEG", quality=60)
        return buffered.getvalue()
    except Exception as e:
        logging.error(f"Failed to apply SoM annotation: {e}")
        return img_data

def annotate_image_with_crosshair(img_data: bytes, x: int, y: int) -> bytes:
    """Draws a green crosshair on the raw un-tagged coordinate."""
    if not img_data:
        return b""
    try:
        image = Image.open(io.BytesIO(img_data)).convert("RGBA")
        draw = ImageDraw.Draw(image)

        r = 15
        draw.ellipse((x-r, y-r, x+r, y+r), outline=(0, 255, 0, 255), width=3)
        draw.line((x-r-5, y, x+r+5, y), fill=(0, 255, 0, 255), width=3)
        draw.line((x, y-r-5, x, y+r+5), fill=(0, 255, 0, 255), width=3)

        buffered = io.BytesIO()
        image.convert("RGB").save(buffered, format="JPEG", quality=60)
        return buffered.getvalue()
    except Exception as e:
        logging.error(f"Failed to apply crosshair annotation: {e}")
        return img_data

def pre_flight_check(command_text: str) -> dict:
    if not CURRENT_TOKEN:
        return {"status": "ok"}

    url = config.PRE_FLIGHT_ENDPOINT

    payload = {"command_text": command_text}
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        response = authenticated_request("POST", url, json=payload, headers=headers, timeout=(10, 20))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error in pre-flight check: {e}")
        return {"status": "ok"}

def supervisor_plan(command_text: str, completed_tasks: list = None, task_index: int = None, roadblock_reason: str = None) -> list:
    if not CURRENT_TOKEN:
        return []

    url = config.SUPERVISOR_PLAN_ENDPOINT

    payload = {"command_text": command_text}
    if completed_tasks is not None:
        payload["completed_tasks"] = completed_tasks
    if task_index is not None:
        payload["task_index"] = task_index
    if roadblock_reason is not None:
        payload["roadblock_reason"] = roadblock_reason
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        response = authenticated_request("POST", url, json=payload, headers=headers, timeout=(10, 30))
        response.raise_for_status()
        return response.json().get("sub_tasks", [])
    except Exception as e:
        logging.error(f"Error getting supervisor plan: {e}")
        return []

def evaluate_plan_progress(command_text: str, current_sub_task: str, remaining_plan: list, screenshot_base64: str, ui_elements: list) -> dict:
    if not CURRENT_TOKEN:
        return {"is_accomplished": False, "reason": "No token"}

    url = config.EVALUATE_PLAN_PROGRESS_ENDPOINT

    # Trim UI elements heavily to reduce payload and backend memory pressure
    trimmed_ui = []
    for el in ui_elements[:50]:
        trimmed_ui.append({
            "target_id": el.get("target_id", el.get("id")),
            "type": el.get("type", ""),
            "text": str(el.get("text", ""))[:50]
        })

    payload = {
        "command_text": command_text,
        "current_sub_task": current_sub_task,
        "remaining_plan": remaining_plan,
        "screenshot_base64": screenshot_base64,
        "ui_elements": trimmed_ui
    }
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        # Use authenticated request for silent token refresh
        response = authenticated_request("POST", url, json=payload, headers=headers, timeout=(10, 20))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ChunkedEncodingError as e:
        logging.error(f"ChunkedEncodingError in evaluate_plan_progress: {e}. Defaulting to not accomplished.")
        return {"is_accomplished": False, "reason": f"Local graceful fallback due to ChunkedEncodingError: {e}"}
    except requests.exceptions.SSLError as e:
        logging.error(f"SSLError in evaluate_plan_progress: {e}. Defaulting to not accomplished.")
        return {"is_accomplished": False, "reason": f"Local graceful fallback due to SSLError: {e}"}
    except requests.exceptions.ConnectionError as e:
        logging.error(f"ConnectionError in evaluate_plan_progress: {e}. Defaulting to not accomplished.")
        return {"is_accomplished": False, "reason": f"Local graceful fallback due to ConnectionError: {e}"}
    except Exception as e:
        logging.error(f"Graceful fallback in evaluate_plan_progress: {e}. Defaulting to not accomplished.")
        return {"is_accomplished": False, "reason": f"Local graceful fallback due to error: {e}"}

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
            # Check value or text attributes mapped by DOMSnapshot (Web) or Name (OS)
            el_text = el.get("text", "") or ""
            el_value = el.get("attributes", {}).get("value", "") or ""
            el_name = el.get("name", "") or "" # For OS elements

            if text_to_type.lower() in str(el_text).lower() or text_to_type.lower() in str(el_value).lower() or text_to_type.lower() in str(el_name).lower():
                return {"success": True, "reason": f"Text '{text_to_type}' natively verified in state."}

        return {"success": False, "reason": f"Text '{text_to_type}' not found natively in new state."}

    elif action_type == "CLICK":
        # If URL (or Window Name) changed, click definitely did something
        if before_url != after_url and after_url:
            return {"success": True, "reason": "Context (URL/Window) changed after click natively verified."}

        # If DOM/UI Tree changed significantly (e.g. elements appeared/disappeared)
# Check by target_id as well
        before_ids = {el.get("target_id", el.get("id")) for el in before_ui if el.get("target_id", el.get("id"))}
        after_ids = {el.get("target_id", el.get("id")) for el in after_ui if el.get("target_id", el.get("id"))}

        before_names = {el.get("name") for el in before_ui if el.get("name")}
        after_names = {el.get("name") for el in after_ui if el.get("name")}

        # If new elements appeared or old ones disappeared, the state changed
        if before_ids != after_ids or before_names != after_names:
             return {"success": True, "reason": "UI state changed after click natively verified."}

        # Soft verification for async transitions
        return {"success": True, "reason": "Click executed, assuming async state transition."}

    elif action_type in ["RESET_VIEW", "SCROLL", "PRESS_ENTER", "PRESS", "PRESS_KEY", "HOVER", "REPLY", "LAUNCH_APP", "DRAG_AND_DROP", "EXECUTE_JS"]:
        return {"success": True, "reason": f"{action_type} natively verified as NON_VISUAL or inherently self-resolving."}

    # For other actions or complex semantic checks, return False to fallback to LLM Critic
    return {"success": False, "reason": "Action cannot be verified natively."}

def critic_verify(sub_task: str, action_taken: dict, before_state: dict, after_state: dict) -> dict:
    if not CURRENT_TOKEN:
        return {"success": True, "reason": "No token"}

    url = config.CRITIC_VERIFY_ENDPOINT

    payload = {
        "sub_task": sub_task,
        "action_taken": action_taken,
        "before_state": before_state,
        "after_state": after_state
    }
    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}", "Content-Type": "application/json"}
    try:
        response = authenticated_request("POST", url, json=payload, headers=headers, timeout=(10, 30))
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

    url = config.CLASSIFY_INTENT_ENDPOINT

    payload = {
        "command_text": command_text,
        "audio_base64": audio_b64
    }

    headers = {
        "Authorization": f"Bearer {CURRENT_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        response = authenticated_request("POST", url, json=payload, headers=headers, timeout=(10, 20))
        response.raise_for_status()
        data = response.json()

        intent = data.get("intent", "OS")
        final_text = data.get("command_text", command_text)

        logging.info(f"Intent classified dynamically as '{intent}' with text: '{final_text}'")
        return intent, final_text
    except Exception as e:
        logging.error(f"Error classifying intent with backend: {e}. Defaulting to OS.")
        return "OS", command_text

def load_client_profile(client_id: str = "default") -> Dict[str, Any]:
    """Loads the client profile config from Firestore (Phase 6 Architecture)."""
    try:
        # Phase 6: We use the new multi-tenant structure: tenants/{client_id}/config/main
        profile_data = firestore_get_document(f"tenants/{client_id}/config", "main")
        if profile_data:
            # Inject the client_id back in for downstream compatibility
            profile_data["client_id"] = client_id
            return profile_data

        # Fallback to old collection if new tenant structure doesn't exist yet
        profile_data_fallback = firestore_get_document("client_profiles", client_id)
        if profile_data_fallback:
            return profile_data_fallback

    except Exception as e:
        logging.error(f"Failed to load client profile '{client_id}' from Firestore: {e}")
    return {"client_id": client_id, "rules": []}


class AgentStateMachine:
    def __init__(self):
        self.state = AgentState.INITIALIZING
        self.hitl_event = asyncio.Event()
        self.interrupt_event = asyncio.Event()
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
        self.max_sub_task_iterations = 3
        self.any_subtask_failed = False
        self.help_reason = None

    async def run(self, doc_id, command_text, audio_b64="", client_context=None):
        global ACTIVE_DOC_ID
        ACTIVE_DOC_ID = doc_id

        self.doc_id = doc_id
        self.command_text = command_text
        self.audio_b64 = audio_b64

        # If client_context is passed (e.g., from an API call that provides it), use it.
        # Otherwise, dynamically fetch the active client profile from Firestore.
        if client_context:
            self.client_context = client_context
        else:
            # We attempt to fetch the profile by ID if we somehow knew it, but for now we'll default to 'sreality'
            # since we don't have a global settings config storing the "active" one locally anymore.
            # In a robust setup, the dashboard would pass the active client_id in the /run_command payload.
            self.client_context = await asyncio.to_thread(load_client_profile, "sreality")

        self.state = AgentState.INITIALIZING
        self.iteration = 0
        self.sub_tasks = []
        self.current_sub_task_index = 0
        self.sub_task_iteration = 0

        logging.info(f"=== Remote Agent Activated for Document: {doc_id} ===")
        pass

        loop_counter = 0
        while self.state != AgentState.TERMINATED:
            try:
                loop_counter += 1
                if ABORT_AGENT:
                    logging.info("Emergency abort triggered. Stopping state machine.")
                    self.state = AgentState.TERMINATED
                    break
                if PAUSE_AGENT:
                    await asyncio.sleep(1)
                    continue

                # Check if there is a manual human_response update via Firebase (for mobile semantic interrupts)
                if self.doc_id and loop_counter % 20 == 0:  # Check every ~2 seconds
                    try:
                        doc_data = await asyncio.to_thread(firestore_get_document, "remote_commands", self.doc_id)
                        if doc_data and doc_data.get("human_response"):
                            human_resp = doc_data.get("human_response")
                            logging.info(f"Detected semantic guidance from Firestore: {human_resp}")
                            # Process the human response as an interrupt
                            self.hitl_action = {"type": "SEMANTIC", "xpath": human_resp}

                            # Only interrupt if we are actively executing, otherwise it's just handled when suspended
                            if self.state != AgentState.SUSPENDED_HITL:
                                self.interrupt_event.set()
                            else:
                                self.hitl_event.set()

                            # Clear it from Firestore
                            try:
                                await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {}, delete_fields=["human_response"])
                            except Exception as e:
                                logging.error(f"Failed to clear human_response: {e}")
                    except Exception as e:
                        logging.error(f"Error checking for semantic interrupts: {e}")

                if self.interrupt_event.is_set():
                    logging.info("Asynchronous interrupt detected!")
                    self.interrupt_event.clear()
                    if self.hitl_action:
                        # Spatial interrupt (CLICK)
                        if self.hitl_action.get("type") == "CLICK" or (self.hitl_action.get("x") is not None and self.hitl_action.get("y") is not None):
                            logging.info("Processing asynchronous spatial interrupt (Ghost Click).")
                            self.state = AgentState.LEARNING_ROUTINE
                            continue
                        # Semantic interrupt
                        elif "xpath" in self.hitl_action:
                            semantic_guidance = self.hitl_action.get("xpath", "")
                            if semantic_guidance:
                                logging.info(f"Processing asynchronous semantic guidance: {semantic_guidance}")
                                self.command_text += f"\n[System Note: Immediate Human Override Received: '{semantic_guidance}'. Adjust your execution plan accordingly.]"
                                self.sub_task_iteration = 0
                                self.state = AgentState.EVALUATING
                                self.hitl_action = None
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
                elif self.state == AgentState.TRAINING_NEEDED:
                    await self.state_training_needed()
                elif self.state == AgentState.LEARNING_ROUTINE:
                    await self.state_learning_routine()
                elif self.state == AgentState.SELF_HEALING:
                    await self.state_self_healing(bridge)

                await asyncio.sleep(0.1)
            except Exception as e:
                logging.error(f"Catastrophic failure in AgentStateMachine loop: {e}\n{traceback.format_exc()}")
                self.any_subtask_failed = True
                try:
                    await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                        "status": "failed",
                        "error": f"Agent crashed unexpectedly: {str(e)}"
                    })
                except Exception as fs_e:
                    logging.error(f"Failed to update task status after catastrophic crash: {fs_e}")
                self.state = AgentState.TERMINATED
                break

    async def state_initializing(self):
        intent, cmd_text = classify_intent(self.command_text, self.audio_b64)
        self.command_text = cmd_text
        self.intent = intent

        logging.info("Running Pre-Flight check...")
        pre_flight = pre_flight_check(self.command_text)
        if pre_flight.get("status") == "ASK_HUMAN":
            reason = pre_flight.get("reason", "Missing required information.")
            logging.info(f"Pre-flight failed: {reason}")
            try:
                await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
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
            await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {"status": "completed"})
            return

        current_sub_task = self.sub_tasks[self.current_sub_task_index]
        logging.info(f"--- Executing Sub-Task {self.current_sub_task_index + 1}/{len(self.sub_tasks)}: {current_sub_task} ---")

        if self.sub_task_iteration == 0:
            # Deterministically parse intent from the [WEB] or [OS] prefix
            if current_sub_task.strip().upper().startswith("[OS]"):
                self.intent = "OS"
                logging.info(f"Deterministically parsed intent for sub-task as {self.intent}")
            elif current_sub_task.strip().upper().startswith("[WEB]"):
                self.intent = "WEB"
                logging.info(f"Deterministically parsed intent for sub-task as {self.intent}")
            else:
                # Fallback to dynamic classification if prefix is missing
                dynamic_intent_text = f"Overall Goal: {self.command_text}\nSub-task: {current_sub_task}"
                intent, _ = classify_intent(dynamic_intent_text, "")
                self.intent = intent
                logging.info(f"Prefix missing. Dynamic intent for sub-task '{current_sub_task}' classified as {self.intent}")

        if self.sub_task_iteration > 0:
            try:
                await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                    "telemetry": f"Retrying sub-task '{current_sub_task}' (Attempt {self.sub_task_iteration + 1}/{self.max_sub_task_iterations})."
                })
            except Exception as e:
                logging.error(f"Failed to update telemetry for retry: {e}")

        # Cross-Boundary Handoff: Detect if the Web environment is occluded by a native OS window
        if self.intent == "WEB":
            occlusion_status = await desktop_env.check_occlusion()
            if occlusion_status.get("occluded"):
                window_name = occlusion_status.get("name", "Unknown Window")
                logging.warning(f"Cross-Boundary Handoff Triggered: Web intent occluded by native OS window '{window_name}'. Forcing execution domain to OS.")
                self.intent = "OS"
                self.command_text += f"\n[System Note: A native OS window or dialog ('{window_name}') has appeared and is blocking the browser. You MUST resolve this native window before returning to the web task.]"

        if self.intent == "WEB":
            logging.info("Requesting GET_STATE from bridge...")
            state_payload = {
                "action_type": "GET_STATE",
                "commandText": self.command_text,
                "audioBase64": self.audio_b64 if self.iteration == 0 else "",
                "iteration": self.iteration
            }

            try:
                state_result = await asyncio.wait_for(
                     asyncio.to_thread(bridge.delegate_command, state_payload, timeout=60),
                    timeout=65
                )
            except asyncio.TimeoutError:
                logging.error("Bridge communication timeout during GET_STATE. Triggering fallback recovery.")
                state_result = {"success": False, "error": "WebSocket Timeout"}

            if not state_result.get("success"):
                error_msg = state_result.get('error', 'Unknown error')
                logging.error(f"Failed to get state from extension: {error_msg}")

                # Treat environment failures (like detached tabs) as a retryable/failing sub-task rather than full agent crash
                if "Session detached" in error_msg or "No active tab" in error_msg or "closed" in error_msg.lower() or "Timeout" in error_msg:
                     logging.warning("Environment volatility detected. Triggering retry or failure logic.")
                     self.sub_task_iteration += 1
                     if self.sub_task_iteration >= self.max_sub_task_iterations:
                          try:
                              await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                                  "status": "AWAITING_HUMAN_INPUT",
                                  "help_reason": f"Environment failure (e.g., target tab closed or timeout): {error_msg}"
                              })
                          except Exception as fs_e:
                              logging.error(f"Error saving help request: {fs_e}")
                          self.help_reason = f"Environment failure (e.g., target tab closed or timeout): {error_msg}"
                          self.state = AgentState.SUSPENDED_HITL
                     else:
                          self.command_text += f"\n[System Note: Environment error occurred: {error_msg}. Recovering state.]"
                          self.state = AgentState.EVALUATING
                     return

                self.state = AgentState.TERMINATED
                return

            b64_str = state_result.get("screenshot_base64", "")
            if b64_str.startswith('data:image'):
                b64_str = b64_str.split(',')[1]
            try:
                self.current_clean_screenshot = base64.b64decode(b64_str) if b64_str else b""
            except Exception:
                self.current_clean_screenshot = b""
            self.current_ui_elements = state_result.get("ui_elements", [])
            self.current_url = state_result.get("url", "")
            self.current_dpr = state_result.get("dpr", 1.0)
            self.clipboard_status = state_result.get("clipboard_status", "unknown")
        else:
            logging.info("Requesting GET_STATE from Desktop Environment...")
            ui_elements, memory_map, window_name, clipboard_status = await desktop_env.scan_ui_elements()
            screenshot = await desktop_env.screenshot()

            self.current_ui_elements = ui_elements
            self.os_memory_map = memory_map
            self.current_clean_screenshot = screenshot
            # For OS, we identify apps by window name or just OS
            self.current_url = window_name
            self.clipboard_status = clipboard_status
            self.current_dpr = 1.0
        try:
            self.current_annotated_screenshot = annotate_image_with_som(
                self.current_clean_screenshot,
                self.current_ui_elements,
                self.current_dpr
            )
        except Exception as e:
            logging.error(f"Error annotating image with SoM: {e}")
            self.current_annotated_screenshot = self.current_clean_screenshot

        if getattr(self, "previous_action", None):
            logging.info("Attempting Orchestrator-Level Native Verification of previous action...")
            native_res = verify_action_natively(
                self.previous_action,
                {"metadata": self.previous_state_metadata, "ui_elements": self.previous_state_ui},
                {"metadata": {"current_url": self.current_url}, "ui_elements": self.current_ui_elements}
            )

            if native_res.get("success"):
                logging.info(f"Native verification succeeded: {native_res.get('reason')}")
                self.command_text += f"\n[System Note: Action {self.previous_action.get('action', 'UNKNOWN')} verified successfully natively: {native_res.get('reason')}]"

                # Smart Circuit Breaker Reset
                # If we natively verified a state change, we reset the iteration counter
                # to prevent premature timeouts, but we do NOT force task completion.
                # The LLM must still evaluate the final visual state.
                self.sub_task_iteration = 0
                logging.info("Native verification succeeded, resetting sub_task_iteration to 0 to prevent circuit breaker.")
            else:
                logging.info(f"Native verification didn't match: {native_res.get('reason')}")

        # Dynamic Sub-Task Evaluation
        if self.sub_task_iteration == 0:
            logging.info(f"Evaluating if current sub-task '{current_sub_task}' is already accomplished...")
            eval_res = evaluate_plan_progress(
                command_text=self.command_text,
                current_sub_task=current_sub_task,
                remaining_plan=self.sub_tasks[self.current_sub_task_index:],
                screenshot_base64=base64.b64encode(self.current_clean_screenshot).decode('utf-8') if self.current_clean_screenshot else "",
                ui_elements=self.current_ui_elements
            )
            if eval_res.get("is_accomplished"):
                logging.info(f"Sub-task '{current_sub_task}' is ALREADY ACCOMPLISHED: {eval_res.get('reason')}. Skipping...")
                self.command_text += f"\n[System Note: Sub-task '{current_sub_task}' was dynamically evaluated as already accomplished. Advancing plan automatically.]"
                self.current_sub_task_index += 1
                self.sub_task_iteration = 0
                self.previous_action = None
                self.history.clear()
                # Skip thinking and acting, re-evaluate the next sub-task
                return

        if self.sub_task_iteration >= self.max_sub_task_iterations:
            logging.warning(f"Circuit Breaker triggered: Max iterations ({self.max_sub_task_iterations}) reached for sub-task '{current_sub_task}'. Fast-Failing to TRAINING_NEEDED state.")
            self.any_subtask_failed = True

            try:
                await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                    "telemetry": f"Circuit Breaker triggered: Max retries ({self.max_sub_task_iterations}) reached for sub-task '{current_sub_task}'. Transitioning to TRAINING_NEEDED."
                })
            except Exception as e:
                logging.error(f"Failed to update telemetry for Circuit Breaker: {e}")

            # Capture failing context for SOP Studio
            self.failing_actions_array = self.actions_to_execute if getattr(self, 'actions_to_execute', None) else [{"action": "UNKNOWN", "error": "Max retries reached"}]
            self.state = AgentState.TRAINING_NEEDED
            return

        self.state = AgentState.THINKING

    def trigger_supervisor_feedback_loop(self, reason: str):
        """Dynamic feedback loop to re-plan when the agent encounters an unexpected state or deadlocks."""
        logging.warning(f"Triggering dynamic Supervisor Feedback Loop. Reason: {reason}")

        # Implement a limit to prevent infinite replanning loops
        self.replan_count = getattr(self, 'replan_count', 0) + 1
        if self.replan_count > 3:
            logging.error("Dynamic replanning loop limit reached. Falling back to HITL suspension.")
            # Triggering a non-blocking background write to update firestore before suspending
            def firestore_update():
                try:
                    firestore_update_document("remote_commands", self.doc_id, {
                        "status": "AWAITING_HUMAN_INPUT",
                        "help_reason": "Dynamic replanning loop limit reached. The agent repeatedly failed to make progress."
                    })
                except Exception as e:
                    logging.error(f"Failed to update firestore on replan limit: {e}")
            threading.Thread(target=firestore_update, daemon=True).start()

            self.help_reason = "Dynamic replanning loop limit reached. The agent repeatedly failed to make progress."
            self.state = AgentState.SUSPENDED_HITL
            return

        # Context mismatch and request re-evaluation of plan
        completed_tasks = self.sub_tasks[:self.current_sub_task_index]
        # We NO LONGER append to self.command_text. Contextual Plan Splicing is handled by API arguments directly.

        # Fetch a new plan based on the original command text with exact state context injected via kwargs
        logging.info("Requesting dynamically adjusted Supervisor Plan...")
        new_plan = supervisor_plan(self.command_text, completed_tasks=completed_tasks, task_index=self.current_sub_task_index, roadblock_reason=reason)

        if new_plan:
            logging.info(f"Dynamically adjusted plan received: {new_plan}")
            # Replace the subtasks with the new complete plan
            self.sub_tasks = new_plan

            # Fast-forward the index logically matching the new plan
            # Assuming the LLM returns the *entire* plan and the first N items are the identical completed tasks
            new_index = 0
            for i, task in enumerate(new_plan):
                if i < len(completed_tasks) and task == completed_tasks[i]:
                    new_index = i + 1
                else:
                    break

            # Natively fast-forward context to the newly created divergence step
            self.current_sub_task_index = new_index
            self.sub_task_iteration = 0
            self.history.clear()
            self.previous_action = None

            # Transition back to evaluating the new plan
            self.state = AgentState.EVALUATING
        else:
            logging.error("Failed to generate a dynamic plan. Proceeding with the original plan.")

    async def state_thinking(self, bridge):
        current_sub_task = self.sub_tasks[self.current_sub_task_index]

        # Trim raw_ui_elements for payload size reduction (Phase 3 Optimization)
        trimmed_ui_elements = []
        for el in self.current_ui_elements[:100]:
            trimmed_el = {
                "target_id": el.get("target_id", el.get("id")),
                "type": el.get("type", ""),
            }
            if "text" in el:
                trimmed_el["text"] = str(el["text"])[:50]
            if "bounds" in el:
                # keep coarse bounds
                trimmed_el["bounds"] = el["bounds"]
            trimmed_ui_elements.append(trimmed_el)

        # Phase 3: Differential Passing (Structural Hashing)
        # We hash the trimmed structure + URL to detect if visually nothing meaningful changed
        # We explicitly omit bounding boxes from the hash as they might slightly jitter
        structure_to_hash = [{"id": el.get("target_id"), "type": el.get("type"), "text": el.get("text")} for el in trimmed_ui_elements]
        current_state_hash = hashlib.md5(json.dumps({
            "url": self.current_url,
            "ui": structure_to_hash
        }, sort_keys=True).encode('utf-8')).hexdigest()

        # Check if we should omit the image payload
        # STEP 2: The Blindness Fix. Disable differential passing to ensure Vision-First coordinates.
        omit_image = False

        self.previous_state_hash = current_state_hash

        payload = {
            "ui_elements": [], # Stripped out to enforce Vision-First SoM reasoning
            "raw_ui_elements": trimmed_ui_elements,
            "command_text": self.command_text,
            "current_sub_task": current_sub_task,
            "history": self.history,
            "iteration": self.iteration,
            "screenshot_base64": "" if omit_image else (base64.b64encode(getattr(self, "current_annotated_screenshot", self.current_clean_screenshot)).decode('utf-8') if getattr(self, "current_annotated_screenshot", self.current_clean_screenshot) else ""),
            "client_context": self.client_context,
            "clipboard_status": getattr(self, "clipboard_status", "unknown"),
            "differential_passing_active": omit_image
        }

        logging.info(f"Sending state to backend for decision (Image omitted: {omit_image})...")
        try:
            headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}
            backend_url = config.GET_COMMAND_ENDPOINT
            # STEP 1: The Watchdog Fix. Align timeout to Gemini maximum processing time.
            response = authenticated_request("POST", backend_url, json=payload, headers=headers, timeout=(15, 120))
            response.raise_for_status()
            try:
                self.ai_response = response.json()
            except json.JSONDecodeError as je:
                raise ValueError(f"Invalid JSON returned from backend: {je}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Backend API call failed: {e}")
            self.actions_to_execute = [{"action": "ERROR", "error": f"Backend API failed: {str(e)}"}]
            self.state = AgentState.ACTING
            return
        except ValueError as ve:
            logging.error(f"Data schema or parsing error: {ve}")
            self.actions_to_execute = [{"action": "ERROR", "error": f"Data error: {str(ve)}"}]
            self.state = AgentState.ACTING
            return

        try:
            if isinstance(self.ai_response, list):
                actions = self.ai_response
            elif isinstance(self.ai_response, dict):
                actions = self.ai_response.get("actions", [])
                if not actions and "action" in self.ai_response:
                    actions = [self.ai_response]
            else:
                actions = []

            # Strict Data Validation Layer
            validated_actions = []
            if not isinstance(actions, list):
                raise ValueError(f"Expected list of actions, got {type(actions)}")

            for act in actions:
                if not isinstance(act, dict):
                    logging.warning(f"Discarding invalid action (not a dict): {act}")
                    continue
                if "action" not in act:
                    logging.warning(f"Discarding action missing 'action' key: {act}")
                    continue

                # Strict Data Validation Layer & Graceful Degradation
                action_type = str(act.get("action")).upper()
                is_valid = True
                error_reason = ""

                # Check for spatial coordinates or target
                has_spatial = "target_id" in act or "coordinates" in act or ("x" in act and "y" in act)

                if action_type == "CLICK" and not has_spatial:
                    is_valid = False
                    error_reason = "Missing spatial data ('target_id' or 'coordinates' or 'x,y') for CLICK."
                elif action_type == "TYPE":
                    if "text" not in act:
                        is_valid = False
                        error_reason = "Missing 'text' key for TYPE action."
                    elif not has_spatial:
                        # Allow Active Window Center Fallback for OS, but for WEB it's an error
                        if self.intent == "WEB":
                            is_valid = False
                            error_reason = "Missing spatial data ('target_id' or 'coordinates' or 'x,y') for TYPE on WEB."
                elif action_type == "LAUNCH_APP" and "app_name" not in act:
                    is_valid = False
                    error_reason = "Missing 'app_name' for LAUNCH_APP."
                elif action_type in ["NAVIGATE", "OPEN_TAB"]:
                    if "url" not in act or not str(act["url"]).strip():
                        # Intelligent URL Extraction Fallback
                        import re
                        current_task_str = getattr(self, "sub_tasks", [""])[getattr(self, "current_sub_task_index", 0)] if hasattr(self, "sub_tasks") else ""
                        url_match = re.search(r"(?P<url>(?:https?://|www\.)[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)", current_task_str)
                        if url_match:
                            act["url"] = url_match.group("url")
                            logging.info(f"Intelligently extracted fallback URL '{act['url']}' for {action_type} from task string.")
                        else:
                            is_valid = False
                            error_reason = f"Missing or empty 'url' for {action_type} and could not intelligently extract."

                    if is_valid and "url" in act:
                        url = str(act["url"]).strip()
                        if not url.startswith("http://") and not url.startswith("https://"):
                            if url.startswith("localhost") or url.startswith("127.0.0.1"):
                                act["url"] = "http://" + url
                            else:
                                act["url"] = "https://" + url
                            logging.info(f"Standardized URL protocol to '{act['url']}'.")
                elif action_type in ["PRESS", "PRESS_KEY"] and "key" not in act:
                    is_valid = False
                    error_reason = f"Missing 'key' for {action_type}."

                if not is_valid:
                    logging.warning(f"Invalid AI Action generated: {act}. Reason: {error_reason}. Degrading to ERROR action.")
                    validated_actions.append({
                        "action": "ERROR",
                        "error": f"Invalid action payload generated by AI: {error_reason}",
                        "raw_response": json.dumps(act)
                    })
                else:
                    validated_actions.append(act)

            actions = validated_actions

            if not actions:
                 raise ValueError("No actions returned by AI after validation.")
        except Exception as e:
            resp_str = str(getattr(self, 'ai_response', 'None'))
            if len(resp_str) > 200:
                resp_str = resp_str[:200] + "... [TRUNCATED]"
            logging.error(f"Data validation error for API payload: {e}. Raw response: {resp_str}")
            # Treat as a cognitive misfire and increment sub-task iteration, retrying
            self.sub_task_iteration += 1
            if self.sub_task_iteration >= self.max_sub_task_iterations:
                try:
                    await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                        "status": "AWAITING_HUMAN_INPUT",
                        "help_reason": f"System error parsing AI response after retries. Payload: {resp_str}"
                    })
                except Exception as fs_e:
                    logging.error(f"Error saving help request to Firestore: {fs_e}")
                self.help_reason = f"System error parsing AI response after retries. Payload: {resp_str}"
                self.state = AgentState.SUSPENDED_HITL
            else:
                self.command_text += f"\n[System Note: AI generated invalid JSON or invalid actions structure. Try again.]"
                self.state = AgentState.EVALUATING
            return

        for act in actions:
             if act.get("action") == "ASK_HUMAN":
                 help_reason = act.get("reason", "I am stuck and need help.")
                 contextual_help_reason = f"{help_reason} | Stuck trying to execute: [{current_sub_task}]"
                 logging.info(f"AI requested human help: {contextual_help_reason}")
                 self.trigger_supervisor_feedback_loop(contextual_help_reason)
                 return

        current_state_str = str([{"id": el.get("target_id", "N/A"), "text": el.get("text", "")[:20]} for el in self.current_ui_elements[:5]])

        # If the only action is WAIT, do not trigger the stuck detectors (unless waiting forever)
        is_only_wait = len(actions) == 1 and str(actions[0].get("action")).upper() == "WAIT"

        # Fast-Fail to Memory (Action Hash Circuit Breaker)
        current_actions_str = json.dumps(actions, sort_keys=True)
        current_action_hash = hashlib.md5(current_actions_str.encode('utf-8')).hexdigest()

        if hasattr(self, 'previous_action_hash') and self.previous_action_hash == current_action_hash:
            self.action_stuck_counter = getattr(self, 'action_stuck_counter', 0) + 1
            max_stuck_actions = 10 if is_only_wait else 2 # Fast fail after 2 identical repeating loops
            if self.action_stuck_counter >= max_stuck_actions:
                logging.warning("Action Hash Circuit Breaker tripped! AI repeatedly issuing identical actions.")
                self.failing_actions_array = actions
                self.state = AgentState.TRAINING_NEEDED
                return
        else:
            self.action_stuck_counter = 0
            self.previous_action_hash = current_action_hash

        if self.history and self.history[-1] == current_state_str:
            self.stuck_counter = getattr(self, 'stuck_counter', 0) + 1
            max_stuck_visual = 15 if is_only_wait else 5
            if self.stuck_counter >= max_stuck_visual:
                 logging.warning("Visual Stuck detector triggered! Same visual state for 5 iterations.")
                 self.trigger_supervisor_feedback_loop(f"Stuck in a visual loop trying to execute: [{current_sub_task}]")
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
        has_mutated_state = False
        mutating_actions = {"CLICK", "TYPE", "PRESS", "PRESS_KEY", "PRESS_ENTER", "DRAG_AND_DROP", "SCROLL", "LAUNCH_APP", "EXECUTE_JS", "NAVIGATE", "OPEN_TAB"}
        non_visual_actions = {"RESET_VIEW", "SCROLL", "PRESS_ENTER", "PRESS", "PRESS_KEY", "HOVER", "REPLY", "LAUNCH_APP", "DRAG_AND_DROP", "EXECUTE_JS"}

        # Look-Ahead Flagging
        has_mutating_action = any(str(act.get("action", "")).upper() in mutating_actions for act in self.actions_to_execute)

        for action_idx, action_to_take in enumerate(self.actions_to_execute):
             if self.interrupt_event.is_set():
                 logging.info("Asynchronous semantic interrupt detected during action execution! Bailing out early.")
                 bail_out = True
                 break

             action_type = str(action_to_take.get("action", "")).upper()

             # Systemic Parameter Sanitization (Trailing Punctuation from LLM Extraction)
             if "url" in action_to_take:
                 action_to_take["url"] = sanitize_extracted_parameter(action_to_take["url"], param_type="url")
             if "text" in action_to_take:
                 action_to_take["text"] = sanitize_extracted_parameter(action_to_take["text"], param_type="text")

             if action_type == "REPLY" or action_type == "DONE":
                 logging.info(f"Terminal action {action_type} encountered. Concluding execution loop.")
                 self.state = AgentState.TERMINATED
                 try:
                     asyncio.create_task(asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {"status": "completed"}))
                 except:
                     pass
                 bail_out = True
                 break

             if action_type == "SUB_TASK_COMPLETE":
                 # Handled by Look-Ahead Flagging after mutating actions to enforce visual evaluation
                 if has_mutating_action:
                     logging.info(f"Skipping inline SUB_TASK_COMPLETE execution to allow visual evaluation post-action.")
                     continue
                 else:
                     # Standard behavior if it's the only action
                     logging.info(f"Sub-Task '{current_sub_task}' marked as complete by AI.")
                     self.current_sub_task_index += 1
                     self.sub_task_iteration = 0
                     self.previous_action = None
                     self.history.clear()
                     bail_out = True
                     break

             if action_type in mutating_actions:
                 if action_type not in non_visual_actions:
                     has_mutated_state = True

             if action_to_take.get("action") == "WAIT":
                 wait_time = action_to_take.get("seconds", action_to_take.get("wait_time", 2))
                 logging.info(f"Executing explicit WAIT for {wait_time} seconds...")
                 await asyncio.sleep(float(wait_time))
                 bail_out = True
                 # If the action is a WAIT, do not increment the sub_task_iteration to prevent impatience
                 self.sub_task_iteration -= 1
                 break

             logging.info(f"Executing Macro-Action {action_idx + 1}/{len(self.actions_to_execute)}: {action_type}")

             # Ensure coordinates provided as a list map to x and y for compatibility with execution layer
             if "coordinates" in action_to_take and isinstance(action_to_take["coordinates"], list) and len(action_to_take["coordinates"]) >= 2:
                 if "x" not in action_to_take:
                     action_to_take["x"] = action_to_take["coordinates"][0]
                 if "y" not in action_to_take:
                     action_to_take["y"] = action_to_take["coordinates"][1]
             # Handle fallback if top level x and y are strings or exist without coordinates list
             if "x" in action_to_take and isinstance(action_to_take["x"], str):
                 try: action_to_take["x"] = float(action_to_take["x"])
                 except ValueError: pass
             if "y" in action_to_take and isinstance(action_to_take["y"], str):
                 try: action_to_take["y"] = float(action_to_take["y"])
                 except ValueError: pass

             if action_type in ["ERROR", "API_ERROR", "PARSE_ERROR", "PIPELINE_ERROR"]:
                 error_msg = action_to_take.get("error", action_to_take.get("raw_response", "Unknown error"))
                 logging.error(f"Backend returned an error action: {action_type} - {error_msg}")
                 self.sub_task_iteration += 1
                 if self.sub_task_iteration >= self.max_sub_task_iterations:
                     self.trigger_supervisor_feedback_loop(f"System error repeatedly encountered: {action_type} - {error_msg}")
                 else:
                     self.command_text += f"\n[System Note: Backend error encountered: {error_msg}. Retrying.]"
                     self.state = AgentState.EVALUATING
                 bail_out = True
                 break

             # Enrich action with fallback selectors if target_id is present
             if "target_id" in action_to_take:
                 target_id = str(action_to_take["target_id"])
                 for el in self.current_ui_elements:
                     # target_id might be under 'id' or 'target_id'
                     if str(el.get("target_id", el.get("id", ""))) == target_id:
                         if "xpath" in el:
                             action_to_take["fallback_xpath"] = el["xpath"]
                         if "css_selector" in el:
                             action_to_take["fallback_css"] = el["css_selector"]
                         if "center" in el:
                             action_to_take["fallback_x"] = el["center"].get("x")
                             action_to_take["fallback_y"] = el["center"].get("y")
                         if "frameId" in el:
                             action_to_take["frameId"] = el["frameId"]
                         break

             # Check if we should override routing to OS despite WEB intent
             # (e.g. for OS-specific hotkeys like Win or Meta that shouldn't go to Chrome CDP)
             force_os = False

             if self.intent == "WEB" and action_type in ["PRESS", "PRESS_KEY"]:
                 key = action_to_take.get("key", "").lower()
                 if key in ["win", "windows", "meta", "command"]:
                     logging.info(f"Systemic guard: Rerouting {action_type} '{key}' from WEB to OS to prevent state bleed. Applying strict context lock for the remainder of this sub-task.")
                     force_os = True
                     self.intent = "OS"

             # Universal Execution Router: Dynamic Domain Switching
             # Force domain switch based on explicit action types even within a batch
             if action_type == "LAUNCH_APP":
                 logging.info(f"Universal Execution Router: Action {action_type} detected. Forcing execution domain to OS.")
                 self.intent = "OS"
                 force_os = True

             if action_type in ["NAVIGATE", "OPEN_TAB"]:
                 logging.info(f"Universal Execution Router: Action {action_type} detected. Forcing execution domain to WEB.")
                 self.intent = "WEB"
                 force_os = False

             # Execution Strategy Routing
             # Ensure target_id is always a string to prevent issues downstream
             if "target_id" in action_to_take and action_to_take["target_id"] is not None:
                 action_to_take["target_id"] = str(action_to_take["target_id"])

             if self.intent == "WEB" and not force_os:
                 # === Web Execution Strategy ===
                 action_to_take["stealth_mode"] = config.STEALTH_MODE
                 exec_payload = {"action_type": "EXECUTE_ACTION", "action": action_to_take, "iteration": self.iteration}

                 # Wrap bridge call to make it non-blocking and timeout-aware
                 try:
                     # local_bridge's delegate_command signature is delegate_command(self, payload: dict, timeout=300)
                     exec_result = await asyncio.wait_for(
                         asyncio.to_thread(bridge.delegate_command, exec_payload, timeout=60),
                         timeout=65
                     )
                 except asyncio.TimeoutError:
                     logging.error("Bridge communication timeout during execution. Triggering fallback recovery.")
                     exec_result = {"success": False, "error": "WebSocket Timeout"}

                 if not exec_result.get("success"):
                     error_msg = exec_result.get('error', 'Unknown error')
                     logging.warning(f"Macro-action execution failed via bridge: {error_msg}. Bailing out of batch.")

                     if "Session detached" in error_msg or "No active tab" in error_msg or "closed" in error_msg.lower():
                         logging.warning("Environment volatility detected during action execution.")

                     try:
                         await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                             "telemetry": f"Macro-action '{action_type}' failed: {error_msg}. Retrying..."
                         })
                     except Exception as e:
                         pass
                     self.command_text += f"\n[System Note: Last action {action_type} failed: {error_msg}]"

                     if action_type not in ["REPLY", "DONE", "SUB_TASK_COMPLETE"]:
                         # Enter Self-Healing
                         self.any_subtask_failed = True
                         logging.info("Entering Phase 4: Self-Healing due to action failure.")
                         self.failed_action = action_to_take
                         self.failed_error = error_msg
                         self.state = AgentState.SELF_HEALING
                         return

                     bail_out = True
                     break

                 if action_type in ["NAVIGATE", "OPEN_TAB"]:
                     # Cleanly break batch so next GET_STATE natively reads the new WEB domain.
                     bail_out = True
                     break
             else:
                 # === OS Execution Strategy ===
                 try:
                     # Execution Context Guarding for OS (Graceful Degradation)
                     if action_type in ["CLICK", "TYPE"]:
                         if "target_id" in action_to_take:
                             target_id = str(action_to_take["target_id"])
                             if target_id not in getattr(self, "os_memory_map", {}):
                                 logging.warning(f"Kinematic Wait: Target ID {target_id} not found in OS memory map. UI may be rendering. Bailing batch to re-evaluate.")
                                 try:
                                     await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                                         "telemetry": f"Waiting for target {target_id} to render..."
                                     })
                                 except Exception:
                                     pass
                                 bail_out = True
                                 break # Exit batch cleanly to force GET_STATE cycle
                         else:
                             # Spatial Fallback Execution Routing
                             if action_type == "CLICK" and ("x" not in action_to_take or "y" not in action_to_take):
                                 raise ValueError(f"Missing 'target_id' or spatial coordinates (x, y) for {action_type} action.")

                     if action_type == "LAUNCH_APP":
                         app_name = action_to_take.get("app_name")
                         if not app_name:
                             raise ValueError("Missing 'app_name' for LAUNCH_APP action.")
                         logging.info(f"Deterministically launching application: {app_name}")
                         try:
                             # Capture active window before launch
                             initial_window_name = "Unknown"
                             try:
                                 active_window = auto.GetForegroundControl()
                                 if active_window:
                                     initial_window_name = active_window.Name
                             except Exception:
                                 pass

                             # Use os.startfile on Windows to allow app resolution from PATH (e.g. calc.exe, notepad.exe) safely
                             os.startfile(app_name)

                             # Kinematic Quiescence Polling
                             poll_interval = 0.5
                             max_polls = 20  # Max 10 seconds wait
                             for i in range(max_polls):
                                 await asyncio.sleep(poll_interval)
                                 try:
                                     current_window = auto.GetForegroundControl()
                                     if current_window and current_window.Name != initial_window_name:
                                         logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                         success_msg = f"Action LAUNCH_APP natively verified. Active window is now {current_window.Name}"
                                         self.history.append(success_msg)
                                         self.command_text += f"\n[System Note: {success_msg}]"
                                         break
                                 except Exception:
                                     pass

                             # Break batch to force a fresh GET_STATE of the new window, letting ReAct loop wait for it natively
                             bail_out = True
                             break
                         except Exception as e:
                             logging.error(f"Failed to launch app {app_name}: {e}")
                             raise
                     elif action_type == "CLICK":
                         if "target_id" in action_to_take:
                             target_id = str(action_to_take.get("target_id"))
                             el = getattr(self, "os_memory_map", {})[target_id]
                             await desktop_env.click(el["center"]["x"], el["center"]["y"])
                         else:
                             await desktop_env.click(int(action_to_take["x"]), int(action_to_take["y"]), getattr(self, 'current_dpr', 1.0))
                     elif action_type == "TYPE":
                         text = action_to_take.get("text")
                         if text is None:
                             raise ValueError("Missing 'text' for TYPE action.")
                         if "target_id" in action_to_take:
                             target_id = str(action_to_take.get("target_id"))
                             el = getattr(self, "os_memory_map", {})[target_id]
                             await desktop_env.type(el["center"]["x"], el["center"]["y"], text, action_to_take.get("submit", False), target_id=target_id)
                         elif "x" in action_to_take and "y" in action_to_take:
                             await desktop_env.type(int(action_to_take["x"]), int(action_to_take["y"]), text, action_to_take.get("submit", False), target_id=None, dpr=getattr(self, 'current_dpr', 1.0))
                         else:
                             logging.info("TYPE action missing target_id and coordinates. Using Active Window Center Fallback.")
                             active_window = auto.GetForegroundControl()
                             if not active_window:
                                 active_window = auto.GetRootControl()
                             rect = active_window.BoundingRectangle
                             if rect and rect.width() > 0 and rect.height() > 0:
                                 center_x = rect.left + rect.width() // 2
                                 center_y = rect.top + rect.height() // 2
                                 await desktop_env.type(center_x, center_y, text, action_to_take.get("submit", False), target_id=None, dpr=1.0)
                             else:
                                 logging.warning("Active Window Center Fallback failed (no bounding rectangle). Bailing out.")
                                 bail_out = True
                                 break
                     elif action_type == "DRAG_AND_DROP":
                         start_x = action_to_take.get("start_x")
                         start_y = action_to_take.get("start_y")
                         end_x = action_to_take.get("end_x")
                         end_y = action_to_take.get("end_y")
                         if start_x is None or start_y is None or end_x is None or end_y is None:
                             raise ValueError("Missing one or more coordinates (start_x, start_y, end_x, end_y) for DRAG_AND_DROP.")
                         if "target_id" not in action_to_take:
                             await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y), getattr(self, 'current_dpr', 1.0))
                         else:
                             await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y))
                     elif action_type in ["PRESS", "PRESS_KEY"]:
                         key = action_to_take.get("key")
                         if not key:
                             raise ValueError(f"Missing 'key' for {action_type} action.")
                         logging.info(f"Executing OS hotkey via PyAutoGUI: {key}")
                         # Map generic meta to windows key
                         if key.lower() in ["meta", "command", "win", "windows"]:
                             key = "win"
                         pyautogui.press(key)
                 except Exception as e:
                     logging.error(f"Desktop execution failed: {e}")
                     self.command_text += f"\n[System Note: Desktop action {action_type} failed: {e}]"
                     bail_out = True
                     break

             self.previous_action = action_to_take
             self.previous_state_metadata = {"current_url": self.current_url}
             self.previous_state_ui = self.current_ui_elements

        try:
             safe_ai_response = getattr(self, 'ai_response', {})
             safe_actions = getattr(self, 'actions_to_execute', [])
             safe_screenshot_bytes = getattr(self, 'current_clean_screenshot', b"")
             safe_screenshot = base64.b64encode(safe_screenshot_bytes).decode('utf-8') if safe_screenshot_bytes else ""
             save_flight_record(
                 doc_id=self.doc_id,
                 iteration=self.iteration,
                 payload={"command_text": self.command_text, "sub_task": current_sub_task},
                 response=safe_ai_response,
                 action_executed=safe_actions,
                 screenshot_b64=safe_screenshot,
                 system_state={
                     "intent": getattr(self, "intent", "UNKNOWN"),
                     "sub_task_iteration": self.sub_task_iteration,
                     "any_subtask_failed": self.any_subtask_failed,
                     "memory_rules_applied": safe_ai_response.get("memory_rules", []) if isinstance(safe_ai_response, dict) else []
                 }
             )
        except Exception as e:
             logging.error(f"Failed to save flight record: {e}")

        self.iteration += 1
        self.sub_task_iteration += 1
        self.state = AgentState.EVALUATING

    async def state_training_needed(self):
        logging.warning("Entering TRAINING_NEEDED state. Capturing structured context and transitioning to HITL.")
        current_sub_task = self.sub_tasks[self.current_sub_task_index] if self.current_sub_task_index < len(self.sub_tasks) else "Unknown Task"

        # Save exact structured context to Firestore for the Flutter SOP Studio
        try:
            safe_screenshot_bytes = getattr(self, 'current_clean_screenshot', b"")
            safe_screenshot = base64.b64encode(safe_screenshot_bytes).decode('utf-8') if safe_screenshot_bytes else ""

            failing_actions = getattr(self, 'failing_actions_array', [])
            dom_snapshot = []
            if getattr(self, 'current_ui_elements', None):
                # Trim the DOM snapshot to keep payload manageable while preserving structural context
                for el in self.current_ui_elements[:50]:
                    dom_snapshot.append({
                        "target_id": el.get("target_id", el.get("id", "")),
                        "type": el.get("type", ""),
                        "text": str(el.get("text", ""))[:50],
                        "bounds": el.get("bounds", {})
                    })

            await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                "status": "AWAITING_HUMAN_INPUT",
                "help_reason": f"Fast-Fail Circuit Breaker tripped on physical bottleneck. Repeatedly failed on sub-task: [{current_sub_task}]",
                "screenshot_b64": safe_screenshot,
                "failing_actions": failing_actions,
                "failing_goal": current_sub_task,
                "dom_snapshot": dom_snapshot,
                "target_url": getattr(self, "current_url", "unknown")
            })
        except Exception as e:
            logging.error(f"Failed to update firestore with TRAINING_NEEDED context: {e}")

        self.help_reason = f"Fast-Fail Circuit Breaker tripped on physical bottleneck. Repeatedly failed on sub-task: [{current_sub_task}]"
        self.state = AgentState.SUSPENDED_HITL

    async def state_suspended_hitl(self):
        logging.info("Agent is SUSPENDED, awaiting HITL event (Ghost Click)...")
        await self.hitl_event.wait()
        logging.info("Agent WOKE UP from HITL suspension.")
        self.hitl_event.clear()
        self.state = AgentState.LEARNING_ROUTINE

    async def state_self_healing(self, bridge):
        logging.info("=== State: SELF_HEALING ===")
        current_sub_task = self.sub_tasks[self.current_sub_task_index]

        failed_selector = self.failed_action.get("target_id", self.failed_action.get("xpath", "Unknown Selector"))
        logging.info(f"Attempting to heal failure for intent: '{current_sub_task}', failed selector: '{failed_selector}'")

        try:
            # Capture current state visually
            state_payload = {
                "action_type": "GET_STATE",
                "commandText": "Self-healing state capture",
                "audioBase64": "",
                "iteration": self.iteration
            }
            state_result = await asyncio.wait_for(
                asyncio.to_thread(bridge.delegate_command, state_payload, timeout=60),
                timeout=65
            )

            if not state_result.get("success"):
                logging.error("Failed to capture state for healing.")
                self.help_reason = "UI update failed and cannot capture state to self-heal."
                self.state = AgentState.SUSPENDED_HITL
                return

            dom_snippet = state_result.get("state", {}).get("ui_elements", [])
            # Convert UI elements back to string snippet for LLM
            import json
            dom_str = json.dumps(dom_snippet)[:5000] # Limiting to 5000 chars to avoid massive context

            # Call backend to rescue element
            import urllib.parse

            domain = urllib.parse.urlparse(state_result.get("state", {}).get("metadata", {}).get("url", "")).netloc
            if not domain:
                domain = "unknown"

            rescue_payload = {
                "intent": current_sub_task,
                "failed_selector": failed_selector,
                "current_dom_snippet": dom_str
            }

            import config
            global CURRENT_TOKEN
            backend_url = f"{config.BACKEND_API_URL}/api/v1/agent/rescue"
            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            logging.info(f"Calling backend rescue endpoint: {backend_url}")
            from agent import authenticated_request
            response = await asyncio.to_thread(authenticated_request, "POST", backend_url, json=rescue_payload, headers=headers, timeout=15)

            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "HEALED":
                    new_selector = result.get("target_id")
                    thought = result.get("thought", "")
                    logging.info(f"Self-Healing SUCCESS! New selector: '{new_selector}'. Reason: {thought}")

                    # Update action and retry
                    self.failed_action["target_id"] = new_selector
                    self.actions_to_execute = [self.failed_action]
                    self.state = AgentState.ACTING

                    # Store as a playbook rule for the future (lessons learned)
                    try:
                        rule_payload = {
                            "domain": domain,
                            "goal": current_sub_task,
                            "action": str(self.failed_action),
                            "rule": f"Element moved. Old selector: {failed_selector}. New selector: {new_selector}. Intent: {thought}"
                        }
                        rule_url = f"{config.BACKEND_API_URL}/api/v1/playbook/rules"
                        await asyncio.to_thread(authenticated_request, "POST", rule_url, json=rule_payload, headers=headers, timeout=5)
                    except Exception as e:
                        logging.warning(f"Failed to save semantic recall rule to ChromaDB: {e}")

                    return
                else:
                    logging.warning(f"Self-Healing failed to find a valid target: {result.get('reason')}")
            else:
                logging.error(f"Backend rescue API returned {response.status_code}: {response.text}")

        except Exception as e:
            logging.error(f"Exception during Self-Healing: {e}")

        # Fallback if healing fails
        logging.info("Self-healing could not resolve the issue. Falling back to HITL.")
        self.help_reason = f"Action failed ({getattr(self, 'failed_error', 'Unknown Error')}) and Self-Healing was unable to find the new target."
        self.state = AgentState.SUSPENDED_HITL

    async def state_learning_routine(self):
        logging.info(f"LEARNING_ROUTINE: Processing human guidance action: {self.hitl_action}")
        pass

        if self.hitl_action:
            x = self.hitl_action.get("x")
            y = self.hitl_action.get("y")

            if x is not None and y is not None:
                css_x, css_y = float(x), float(y)

                intersecting_boxes = []
                for el in getattr(self, 'current_ui_elements', []):
                    box = el.get("bounds")
                    if box:
                        try:
                            if isinstance(box, dict):
                                bx = float(box.get("x", 0))
                                by = float(box.get("y", 0))
                                bwidth = float(box.get("width", 0))
                                bheight = float(box.get("height", 0))
                            elif isinstance(box, list) and len(box) == 4:
                                bx, by, bwidth, bheight = [float(val) for val in box]
                            else:
                                continue

                            if bx <= css_x <= bx + bwidth and by <= css_y <= by + bheight:
                                area = bwidth * bheight
                                intersecting_boxes.append({"el": el, "area": area})
                        except Exception:
                            continue

                target_box = None
                prompt_text = ""
                image_to_send = ""

                if intersecting_boxes:
                    intersecting_boxes.sort(key=lambda item: item["area"])
                    target_box = intersecting_boxes[0]["el"]
                    target_id = target_box.get("target_id", target_box.get("id"))

                    logging.info(f"HITL click at ({css_x}, {css_y}) intersected with SoM Box [{target_id}].")
                    prompt_text = (f"The human operator intervened and clicked on SoM Box ID [{target_id}]. "
                                   f"You failed to execute this step correctly in the previous iteration. "
                                   f"Analyze the visual features and semantic context of Box [{target_id}] "
                                   f"and generate a universal visual rule for the Playbook.")
                    image_to_send_bytes = getattr(self, "current_annotated_screenshot", self.current_clean_screenshot)
                    image_to_send = base64.b64encode(image_to_send_bytes).decode('utf-8') if image_to_send_bytes else ""
                else:
                    logging.info(f"HITL click at ({css_x}, {css_y}) did not intersect any SoM Box.")
                    prompt_text = (f"The human operator intervened and clicked exactly at coordinates (X: {css_x}, Y: {css_y}). "
                                   f"There was no numbered SoM box at this location (AOM failure). "
                                   f"Analyze the raw visual area inside the green crosshair I have drawn at those coordinates "
                                   f"and generate a universal visual rule for the Playbook.")
                    # HITL click coordinates are CSS, image is Physical
                    current_dpr = getattr(self, "current_dpr", 1.0)
                    phys_x = int(css_x * current_dpr)
                    phys_y = int(css_y * current_dpr)
                    try:
                        image_to_send_bytes = annotate_image_with_crosshair(self.current_clean_screenshot, phys_x, phys_y)
                        image_to_send = base64.b64encode(image_to_send_bytes).decode('utf-8') if image_to_send_bytes else ""
                    except Exception as e:
                         logging.error(f"Error drawing crosshair: {e}")
                         image_to_send = base64.b64encode(self.current_clean_screenshot).decode('utf-8') if self.current_clean_screenshot else ""

                logging.info("Sending HITL learning package to Synthesizer Agent...")
                try:
                    headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}
                    client_id = self.client_context.get("client_id", "default") if self.client_context else "default"

                    if getattr(self, "current_url", ""):
                        domain = self.current_url.split('/')[2] if '//' in self.current_url else self.current_url
                    else:
                        domain = "unknown_domain"

                    # The backend expects execution_telemetry, mapping prompt_text to it
                    synth_payload = {
                        "execution_telemetry": prompt_text,
                        "domain": domain,
                        "client_id": client_id,
                        "failed_sub_task": self.sub_tasks[self.current_sub_task_index]
                    }

                    synth_url = config.SYNTHESIZE_PLAYBOOK_ENDPOINT
                    response = authenticated_request("POST", synth_url, json=synth_payload, headers=headers)

                    if response.ok:
                        logging.info("Synthesizer Agent successfully generated a new Playbook Rule!")
                    else:
                        logging.error(f"Synthesizer failed: {response.status_code} - {response.text}")
                except Exception as e:
                    logging.error(f"Error calling Synthesizer API: {e}")

                try:
                    if self.intent == "WEB":
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
                    else:
                        logging.info(f"Executing HITL Ghost Click natively via DesktopEnv at ({css_x}, {css_y})")
                        await desktop_env.click(int(css_x), int(css_y))
                except Exception as e:
                    logging.error(f"Failed to execute click for HITL: {e}")
            else:
                # Semantic Override
                semantic_guidance = self.hitl_action.get("xpath", "")
                if semantic_guidance:
                    logging.info(f"Received semantic guidance: {semantic_guidance}")
                    self.command_text += f"\n[System Note: Human Guidance received: '{semantic_guidance}'. Adjust your execution plan accordingly.]"

                    # Generate playbook rule for semantic guidance
                    try:
                        headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}
                        client_id = self.client_context.get("client_id", "default") if self.client_context else "default"

                        if getattr(self, "current_url", ""):
                            domain = self.current_url.split('/')[2] if '//' in self.current_url else self.current_url
                        else:
                            domain = "unknown_domain"

                        synth_payload = {
                            "execution_telemetry": f"The human operator intervened with semantic guidance: '{semantic_guidance}'. Please extract a universal text-based rule.",
                            "domain": domain,
                            "client_id": client_id,
                            "failed_sub_task": self.sub_tasks[self.current_sub_task_index]
                        }

                        synth_url = config.SYNTHESIZE_PLAYBOOK_ENDPOINT
                        response = authenticated_request("POST", synth_url, json=synth_payload, headers=headers)
                        if response.ok:
                            logging.info("Synthesizer Agent successfully generated a new Playbook Rule for semantic guidance!")
                        else:
                            logging.error(f"Synthesizer failed: {response.status_code} - {response.text}")
                    except Exception as e:
                        logging.error(f"Error calling Synthesizer API for semantic guidance: {e}")

            try:
                await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                    "status": "in_progress"
                }, delete_fields=["human_response", "help_reason"])
            except Exception as e:
                logging.error(f"Failed to reset task status after HITL: {e}")

        self.hitl_action = None
        self.iteration += 1
        # Trap D: Reset sub_task_iteration to 0 so the agent gets a fresh set of attempts after human guidance
        self.sub_task_iteration = 0
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

    # In a full implementation, the user's active profile choice would dictate this.
    # Defaulting to sreality as the pilot.
    client_context = load_client_profile("sreality")

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
            pass

            import uuid
            iteration = 0
            doc_id = f"voice_session_{uuid.uuid4().hex[:8]}"
            final_status = "completed"

            # Create or ensure the document exists
            try:
                uid = _get_uid_from_token()
                payload = {
                    "status": "in_progress",
                    "command": "voice command"
                }
                if uid:
                    payload["uid"] = uid
                    payload["created_at"] = datetime.utcnow().isoformat() + "Z"
                firestore_update_document("remote_commands", doc_id, payload)
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
                                response = authenticated_request("POST", config.GET_COMMAND_ENDPOINT, json=payload, headers=headers, timeout=(15, 60))
                                response.raise_for_status()
                                backend_data = response.json()
                                break
                            except requests.exceptions.RequestException as req_err:
                                if isinstance(req_err, requests.exceptions.HTTPError) and req_err.response.status_code == 401:
                                    # Already tried refreshing above, if it still fails 401, bail
                                    raise
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

                            save_flight_record(
                                doc_id,
                                iteration,
                                payload,
                                backend_data,
                                act,
                                screenshot_base64,
                                system_state={
                                    "intent": "WEB",
                                    "sub_task_iteration": sub_task_iteration,
                                    "memory_rules_applied": backend_data.get("memory_rules", []) if isinstance(backend_data, dict) else []
                                }
                            )
                            if not isinstance(act, dict):
                                logging.warning(f"Skipping invalid action type: {type(act)}")
                                continue

                            # Enrich action with fallback selectors if target_id is present
                            if "target_id" in act:
                                target_id = str(act["target_id"])
                                for el in ui_elements:
                                    if str(el.get("target_id", el.get("id", ""))) == target_id:
                                        if "xpath" in el:
                                            act["fallback_xpath"] = el["xpath"]
                                        if "css_selector" in el:
                                            act["fallback_css"] = el["css_selector"]
                                        if "center" in el:
                                            act["fallback_x"] = el["center"].get("x")
                                            act["fallback_y"] = el["center"].get("y")
                                        if "frameId" in el:
                                            act["frameId"] = el["frameId"]
                                        break

                            # Ensure coordinates provided as a list map to x and y for compatibility with execution layer
                            if "coordinates" in act and isinstance(act["coordinates"], list) and len(act["coordinates"]) >= 2:
                                if "x" not in act:
                                    act["x"] = act["coordinates"][0]
                                if "y" not in act:
                                    act["y"] = act["coordinates"][1]

                            action_type = act.get("action", "")
                            action_upper = str(action_type).upper()

                            # Systemic Parameter Sanitization (Voice loop)
                            if "url" in act:
                                act["url"] = sanitize_extracted_parameter(act["url"], param_type="url")
                            if "text" in act:
                                act["text"] = sanitize_extracted_parameter(act["text"], param_type="text")

                            if action_upper == "TYPE":
                                has_typed_in_batch = True



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
                                command_text += f"\n[System Note: Last action {action_upper} failed: {exec_result.get('error')}]"
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
        import uuid
        iteration = 0
        doc_id = f"voice_session_{uuid.uuid4().hex[:8]}"
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
            uid = _get_uid_from_token()
            payload = {
                "status": "in_progress",
                "command": "voice command"
            }
            if uid:
                payload["uid"] = uid
                payload["created_at"] = datetime.utcnow().isoformat() + "Z"
            firestore_update_document("remote_commands", doc_id, payload)
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
            ui_elements, memory_map, window_name, clipboard_status = desktop_env._sync_scan()

            # 4. Construct JSON payload
            payload = {
                "ui_elements": ui_elements,
                "session_id": doc_id,
                "command_text": command_text,
                "current_sub_task": current_sub_task,
                "client_context": client_context,
                "current_url": window_name,
                "clipboard_status": clipboard_status
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
                        response = authenticated_request("POST", config.GET_COMMAND_ENDPOINT, json=payload, headers=headers, timeout=(15, 60))
                        response.raise_for_status()
                        backend_data = response.json()
                        break
                    except requests.exceptions.RequestException as req_err:
                        if isinstance(req_err, requests.exceptions.HTTPError) and req_err.response.status_code == 401:
                             raise
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

                    save_flight_record(
                        doc_id,
                        iteration,
                        payload,
                        backend_data,
                        act,
                        os_screenshot_b64,
                        system_state={
                            "intent": "OS",
                            "sub_task_iteration": sub_task_iteration,
                            "memory_rules_applied": backend_data.get("memory_rules", []) if isinstance(backend_data, dict) else []
                        }
                    )

                    if ABORT_AGENT:
                        logging.info("Emergency abort triggered during action sequence.")
                        break_outer = True
                        break

                    action_type = act.get("action", "")
                    action_upper = str(action_type).upper()

                    # Systemic Parameter Sanitization (OS voice loop)
                    if "url" in act:
                        act["url"] = sanitize_extracted_parameter(act["url"], param_type="url")
                    if "text" in act:
                        act["text"] = sanitize_extracted_parameter(act["text"], param_type="text")

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

                    # Execution Context Guarding for OS inside Voice Loop
                    if action_upper in ["CLICK", "TYPE"]:
                        if "target_id" in act:
                            target_id = str(act["target_id"])
                            if target_id not in memory_map:
                                logging.error(f"Safety Bailout: Target ID {target_id} not found in OS memory map. The expected window might not be focused or ready.")
                                try:
                                    firestore_update_document("remote_commands", doc_id, {
                                        "telemetry": f"Safety Bailout: Target ID {target_id} not found. Window state may have shifted. Retrying..."
                                    })
                                except Exception as e:
                                    pass
                                break
                        else:
                            # Spatial Fallback Execution Routing
                            if action_upper == "CLICK" and ("x" not in act or "y" not in act):
                                logging.error(f"Safety Bailout: Missing 'target_id' or spatial coordinates (x, y) for {action_upper} action.")
                                break
                            # TYPE is allowed without coordinates (uses Active Window Center Fallback)

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
                    elif action_upper == "LAUNCH_APP" and "app_name" in act:
                        app_name = act["app_name"]
                        logging.info(f"Deterministically launching application: {app_name}")
                        try:
                            # Capture active window before launch
                            initial_window_name = "Unknown"
                            try:
                                import uiautomation as local_auto
                                active_window = local_auto.GetForegroundControl()
                                if active_window:
                                    initial_window_name = active_window.Name
                            except Exception as e:
                                logging.warning(f"Failed to capture initial foreground window: {e}")

                            # Use os.startfile on Windows to allow app resolution from PATH safely
                            os.startfile(app_name)

                            # Kinematic Quiescence Polling
                            poll_interval = 0.5
                            max_polls = 20  # Max 10 seconds wait
                            for i in range(max_polls):
                                time.sleep(poll_interval)
                                try:
                                    import uiautomation as local_auto
                                    current_window = local_auto.GetForegroundControl()
                                    if current_window and current_window.Name != initial_window_name:
                                        logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                        break
                                except Exception as e:
                                    logging.debug(f"Failed to capture current foreground window during polling: {e}")

                            had_terminal_action = True
                            break_outer = True
                            break
                        except Exception as e:
                            logging.error(f"Failed to launch app {app_name}: {e}")
                    elif action_upper == "CLICK":
                        try:
                            if "target_id" in act:
                                target_id = str(act["target_id"])
                                logging.info(f"Clicking element with ID {target_id} using PyAutoGUI...")
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                            else:
                                logging.info(f"Clicking coordinate ({act['x']}, {act['y']}) using PyAutoGUI...")
                                x = int(act["x"])
                                y = int(act["y"])
                            pyautogui.moveTo(x, y, duration=0.5)
                            pyautogui.click()
                        except Exception as click_e:
                            logging.error(f"Error executing click via PyAutoGUI: {click_e}.")

                    elif action_upper == "TYPE":
                        text_to_type = act.get("text", "")
                        try:
                            if "target_id" in act:
                                target_id = str(act["target_id"])
                                logging.info(f"Typing '{text_to_type}' at element {target_id} using PyAutoGUI...")
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                            else:
                                logging.info(f"Typing '{text_to_type}' at coordinate ({act['x']}, {act['y']}) using PyAutoGUI...")
                                x = int(act["x"])
                                y = int(act["y"])
                            pyautogui.moveTo(x, y, duration=0.5)
                            pyautogui.click()
                            pyautogui.hotkey('ctrl', 'a')
                            pyautogui.press('backspace')
                            time.sleep(0.2)
                            pyautogui.write(text_to_type)
                        except Exception as type_e:
                            logging.error(f"Error executing type via PyAutoGUI: {type_e}.")

                    elif action_upper == "DRAG_AND_DROP":
                        start_x = act.get("start_x")
                        start_y = act.get("start_y")
                        end_x = act.get("end_x")
                        end_y = act.get("end_y")
                        if start_x is not None and start_y is not None and end_x is not None and end_y is not None:
                             logging.info(f"Executing DRAG_AND_DROP from ({start_x}, {start_y}) to ({end_x}, {end_y})...")
                             try:
                                 # This is a synchronous function so we can't use await desktop_env.drag_and_drop, we execute pyautogui synchronously instead like the other actions in this method
                                 pyautogui.moveTo(int(start_x), int(start_y), duration=0.2)
                                 pyautogui.mouseDown()
                                 pyautogui.moveTo(int(end_x), int(end_y), duration=0.5)
                                 pyautogui.mouseUp()
                             except Exception as drag_e:
                                 logging.error(f"Error executing drag_and_drop: {drag_e}")

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
from datetime import datetime

RECORDING_MODE = False
RECORDED_STEPS = []

class HumanGuidanceRequest(BaseModel):
    type: str = ""
    xpath: str = "Unknown element"
    x: Optional[float] = Field(default=None, ge=0)
    y: Optional[float] = Field(default=None, ge=0)
    dpr: float = 1.0


class LocalAPIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Truncate long URLs and payloads to prevent terminal flooding and hanging
        msg = format % args
        if len(msg) > 200:
            msg = msg[:200] + "... [TRUNCATED]"
        logging.info("%s - - [%s] %s\n" %
                         (self.client_address[0],
                          self.log_date_time_string(),
                          msg))

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def do_POST(self):
        global LOCAL_STATUS, ACTIVE_DOC_ID, RECORDING_MODE, RECORDED_STEPS
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
                            "status": "in_progress",
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

                PROCESSED_DOC_IDS.add(doc_id)
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
                raw_data = json.loads(post_data.decode('utf-8'))

                # Strict Data Validation Layer via Pydantic
                try:
                    validated_request = HumanGuidanceRequest(**raw_data)
                except ValidationError as ve:
                    logging.error(f"Validation error for human guidance payload: {ve.errors()}")
                    self.send_response(HTTPStatus.BAD_REQUEST)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Validation failed", "details": ve.errors()}).encode())
                    return

                type_of_guidance = validated_request.type
                xpath = validated_request.xpath
                x = validated_request.x
                y = validated_request.y
                dpr = validated_request.dpr

                # Dynamic Clamping against original width/height
                global global_state_machine
                if x is not None and y is not None:
                    clean_screenshot_bytes = getattr(global_state_machine, "current_clean_screenshot", None)
                    if clean_screenshot_bytes:
                        try:
                            from PIL import Image
                            import io
                            img = Image.open(io.BytesIO(clean_screenshot_bytes))
                            img_w, img_h = img.size
                            x = min(max(0.0, float(x)), float(img_w))
                            y = min(max(0.0, float(y)), float(img_h))
                            # Update the validated request to pass clamped values to the state machine
                            validated_request.x = x
                            validated_request.y = y
                        except Exception as e:
                            logging.error(f"Error clamping coordinates: {e}")

                is_semantic = (type_of_guidance == "SEMANTIC" or xpath != "Unknown element")

                if type_of_guidance == "CLICK" and x is not None and y is not None:
                    guidance = f"Click at (X: {x}, Y: {y})"
                    if is_semantic:
                        guidance += f" - {xpath}"
                elif is_semantic:
                    guidance = f"Semantic Override: {xpath}"
                else:
                    # Fallback for legacy format or just text
                    guidance = f"Semantic Override: {raw_data}"

                if RECORDING_MODE:
                    step_data = {
                        "type": type_of_guidance,
                        "xpath": xpath,
                        "x": x,
                        "y": y,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "description": guidance
                    }
                    RECORDED_STEPS.append(step_data)
                    logging.info(f"Recorded step: {guidance}")

                if ACTIVE_DOC_ID:
                    is_suspended = (global_state_machine and global_state_machine.state == AgentState.SUSPENDED_HITL)

                    firestore_update_document("remote_commands", ACTIVE_DOC_ID, {
                        "status": "in_progress",
                        "human_response": guidance
                    })
                    logging.info(f"Teleoperation ghost click registered for doc {ACTIVE_DOC_ID}: {guidance}")

                    def set_event():
                        # Pass the validated dictionary back to the state machine
                        global_state_machine.hitl_action = validated_request.model_dump()
                        if is_suspended:
                            global_state_machine.hitl_event.set()
                        else:
                            global_state_machine.interrupt_event.set()

                    if global_asyncio_loop:
                        global_asyncio_loop.call_soon_threadsafe(set_event)

                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
                return
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
                pass
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
        elif self.path == '/api/recording/start':
            RECORDING_MODE = True
            RECORDED_STEPS.clear()
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "recording_started"}).encode())
        elif self.path == '/api/recording/stop':
            RECORDING_MODE = False
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "recording_stopped"}).encode())
        elif self.path == '/api/reset':
            # Handle clean state reset
            try:
                trigger_abort()

                # Clear the COMMAND_QUEUE
                while not COMMAND_QUEUE.empty():
                    try:
                        COMMAND_QUEUE.get_nowait()
                        COMMAND_QUEUE.task_done()
                    except queue.Empty:
                        break

                # We optionally could also clear PROCESSED_DOC_IDS, but leaving it as-is is safer
                # Reset local status
                if ACTIVE_DOC_ID and ACTIVE_DOC_ID in LOCAL_STATUS:
                    LOCAL_STATUS[ACTIVE_DOC_ID] = "failed"

                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "reset"}).encode())
            except Exception as e:
                logging.error(f"Error handling /api/reset: {e}")
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
        global RECORDED_STEPS
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path.startswith('/api/status/'):
            doc_id = parsed_path.path.split('/')[-1]

            if doc_id == "active":
                doc_id = ACTIVE_DOC_ID

            status = LOCAL_STATUS.get(doc_id, "unknown")

            # Expose iteration count and state for active scenarios
            iteration = 0
            agent_state = "unknown"
            any_subtask_failed = False
            intent = None
            current_action = None
            current_url = None
            screenshot_base64 = None
            original_width = None
            original_height = None
            help_reason = None
            image_hash = None

            global global_state_machine
            if global_state_machine and getattr(global_state_machine, "doc_id", None) == doc_id:
                iteration = getattr(global_state_machine, "iteration", 0)
                agent_state = getattr(global_state_machine, "state", AgentState.TERMINATED).name
                any_subtask_failed = getattr(global_state_machine, "any_subtask_failed", False)

                # Expose richer state variables
                intent = getattr(global_state_machine, "intent", None)
                help_reason = getattr(global_state_machine, "help_reason", None)
                current_url = getattr(global_state_machine, "current_url", None)

                # Current action / sub-task
                try:
                    current_idx = getattr(global_state_machine, "current_sub_task_index", 0)
                    sub_tasks = getattr(global_state_machine, "sub_tasks", [])
                    if current_idx < len(sub_tasks):
                        current_action = sub_tasks[current_idx]
                except Exception:
                    pass

                # Current screenshot
                clean_screenshot_bytes = getattr(global_state_machine, "current_clean_screenshot", None)
                if clean_screenshot_bytes:
                    import hashlib
                    image_hash = hashlib.md5(clean_screenshot_bytes).hexdigest()

                    # Only calculate base64 if hash is different
                    query = urllib.parse.parse_qs(parsed_path.query)
                    client_hash = query.get('image_hash', [None])[0]

                    if client_hash != image_hash:
                        screenshot_base64 = base64.b64encode(clean_screenshot_bytes).decode('utf-8')

                    try:
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(clean_screenshot_bytes))
                        original_width, original_height = img.size
                    except Exception:
                        pass

            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            response_data = {
                "doc_id": doc_id,
                "status": status,
                "iteration": iteration,
                "agent_state": agent_state,
                "any_subtask_failed": any_subtask_failed,
                "intent": intent,
                "current_action": current_action,
                "current_url": current_url,
                "original_width": original_width,
                "original_height": original_height,
                "help_reason": help_reason,
                "image_hash": image_hash
            }
            if screenshot_base64 is not None:
                response_data["screenshot"] = screenshot_base64

            self.wfile.write(json.dumps(response_data).encode())
        elif parsed_path.path == '/api/recording/steps':
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"steps": RECORDED_STEPS}).encode())
        elif parsed_path.path == '/api/ping':
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        elif parsed_path.path == '/api/bridge_status':
            try:
                pass
                has_active_ws = False
                if bridge.active_websocket is not None:
                    has_active_ws = True

                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "active_websocket": has_active_ws}).encode())
            except Exception as e:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
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

            backend_url = f"{config.PLAYBOOK_RULES_ENDPOINT}?domain={urllib.parse.quote(domain)}"
            if client_id:
                backend_url += f"&client_id={urllib.parse.quote(client_id)}"

            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            try:
                response = authenticated_request("GET", backend_url, headers=headers, timeout=10)
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

def execute_mission(mission_graph, doc_id):
    global LOCAL_STATUS, ACTIVE_DOC_ID, global_state_machine

    LOCAL_STATUS[doc_id] = "executing_mission"
    ACTIVE_DOC_ID = doc_id

    execution_order = mission_graph.get("execution_order", [])
    blocks = {b["block_id"]: b for b in mission_graph.get("blocks", [])}

    context = {}

    for idx, block_id in enumerate(execution_order):
        block = blocks.get(block_id)
        if not block:
            continue

        block_type = block.get("type")
        inputs = block.get("inputs", {})

        # Expose current action for UI visualization (Step X/Y)
        try:
            class DummyMachine:
                pass
            global_state_machine = DummyMachine()
            global_state_machine.doc_id = doc_id
            global_state_machine.state = AgentState.RUNNING
            global_state_machine.sub_tasks = [f"Krok {idx+1}/{len(execution_order)}: {block_type} ({block_id})"]
            global_state_machine.current_sub_task_index = 0
            global_state_machine.intent = "WEB"
            global_state_machine.any_subtask_failed = False
        except Exception:
            pass

        # Resolve templates in inputs (loop through all matches)
        resolved_inputs = {}
        for k, v in inputs.items():
            if isinstance(v, str):
                import re
                matches = re.findall(r"\{\{(.*?)\}\}", v)
                for match in matches:
                    v = v.replace(f"{{{{{match}}}}}", str(context.get(match, "")))
            resolved_inputs[k] = v

        if block_type == "AUTOMATION":
            instruction = resolved_inputs.get("instruction", resolved_inputs.get("url", "Run SOP"))

            global_state_machine = AgentStateMachine(instruction, doc_id=doc_id, client_context="Mission")
            global_state_machine.intent = "WEB"

            error_occurred = False
            while global_state_machine.state not in [AgentState.TERMINATED, AgentState.ERROR, AgentState.SUSPENDED_HITL]:
                try:
                    # In MVP we might not have a full browser session, so we guard step()
                    global_state_machine.step()
                except Exception as e:
                    import logging
                    logging.error(f"Error in automation block {block_id}: {e}")
                    global_state_machine.state = AgentState.ERROR
                    error_occurred = True
                    break

            if global_state_machine.state == AgentState.ERROR or error_occurred:
                LOCAL_STATUS[doc_id] = "failed"
                logging.error(f"Mission aborted: Automation block {block_id} failed.")
                return # GRACEFUL ABORT

            # Simple context extraction - grab the thread history or a known state
            thread_history = getattr(global_state_machine, "thread_history", "")
            context[f"{block_id}.thread_history"] = thread_history
            context[f"{block_id}.status"] = global_state_machine.state.name

        elif block_type == "AI_LOGIC":
            instruction = block.get("instruction", "")
            raw_text = resolved_inputs.get("raw_text", "")

            prompt = f"{instruction}\n\nData:\n{raw_text}"

            try:
                import sys
                import os

                # Try to use Gemini directly
                import google.generativeai as genai
                import config

                if config.GEMINI_API_KEY:
                    genai.configure(api_key=config.GEMINI_API_KEY)
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    response = model.generate_content(prompt)
                    context[f"{block_id}.output"] = response.text.strip()
                else:
                    context[f"{block_id}.output"] = "Error: GEMINI_API_KEY not found in config"
                    LOCAL_STATUS[doc_id] = "failed"
                    return # GRACEFUL ABORT

            except Exception as e:
                import logging
                logging.error(f"Error in AI Logic block {block_id}: {e}")
                context[f"{block_id}.output"] = f"Error: {e}"
                LOCAL_STATUS[doc_id] = "failed"
                return # GRACEFUL ABORT

    LOCAL_STATUS[doc_id] = "completed"

def start_local_api(port=8764):
    """Starts the local API server in a daemon thread."""
    def run_server():
        try:
            with socketserver.ThreadingTCPServer(("0.0.0.0", port), LocalAPIHandler) as httpd:
                logging.info(f"Started Local API Server on http://0.0.0.0:{port}")
                httpd.serve_forever()
        except OSError as e:
            logging.error(f"Failed to start Local API Server: {e}")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()