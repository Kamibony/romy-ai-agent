import logging
import base64
import io
import time
import os
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
import firebase_admin
from firebase_admin import firestore
from typing import Dict, Any, Tuple
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

pyautogui.FAILSAFE = False

BACKEND_URL = os.environ.get("BACKEND_URL", "https://romy-backend-1049976869239.europe-west1.run.app/api/v1/agent/command")

CURRENT_TOKEN = None
_db = None

COMMAND_QUEUE = queue.Queue()
ABORT_AGENT = False

def trigger_abort() -> None:
    """Sets the global abort flag to instantly stop the agent execution loop."""
    global ABORT_AGENT
    logging.critical("User requested emergency abort. Stopping agent loops...")
    ABORT_AGENT = True

def agent_worker_loop() -> None:
    """
    Main Loop running on the primary thread to process commands from the COMMAND_QUEUE.
    This ensures Playwright actions are safely isolated to the main thread.
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
                command_text = task.get("command_text")
                run_remote_agent_loop(doc_id, command_text)
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

def get_firestore_client():
    """Initializes Firebase Admin if not already initialized and returns a Firestore client."""
    global _db
    if _db is None:
        if not firebase_admin._apps:
            # We assume ADC is set up for the desktop client, or the token is enough for our MVP.
            # In a real environment with a desktop client, you might want to authenticate using
            # custom tokens or a specific service account. Since the MVP requirement indicates
            # "uses Google Cloud's Application Default Credentials (ADC) for zero-config initialization",
            # we will initialize without credentials, which relies on ADC.
            firebase_admin.initialize_app()
        _db = firestore.client()
    return _db

def start_remote_listener() -> None:
    """Starts a Firestore listener for pending remote commands."""
    try:
        db = get_firestore_client()
        query = db.collection("remote_commands").where("status", "==", "pending")

        def on_snapshot(col_snapshot, changes, read_time):
            for change in changes:
                if change.type.name == 'ADDED':
                    doc = change.document
                    doc_id = doc.id
                    data = doc.to_dict()
                    command_text = data.get("command", "")
                    logging.info(f"Detected new remote command: {command_text}")

                    # Update status to in_progress
                    doc.reference.update({"status": "in_progress"})

                    # Add to command queue instead of executing directly
                    COMMAND_QUEUE.put({
                        "type": "remote",
                        "doc_id": doc_id,
                        "command_text": command_text
                    })

        # Watch the collection query
        query.on_snapshot(on_snapshot)
        logging.info("Started listening for remote commands on Firestore.")
    except Exception as e:
        logging.error(f"Error starting remote listener: {e}")

def handle_token_expiry():
    """Handles 401 Unauthorized by deleting the token and prompting for re-login."""
    logging.critical("Handling Token Expiry (401 Unauthorized).")

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
        notification.notify(title="ROMY AI Error", message="Authentication expired. Please re-login.", app_name="ROMY", timeout=5)
    except Exception:
        pass

    # 2. Trigger Auth Window to get a new token
    try:
        import auth_window
        new_token = auth_window.login_window()
        if new_token:
            set_firebase_token(new_token)
            logging.info("Successfully acquired new token.")
        else:
            logging.error("Failed to acquire new token. Prompting user to restart.")
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Authentication Error", "Session expired and login failed. Please restart the application.")
            root.destroy()
    except Exception as e:
        logging.error(f"Error showing auth window during token expiry: {e}")
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Authentication Error", "Session expired. Please restart the application to log in again.")
        root.destroy()

_playwright = None
_browser = None
_context = None
_page = None

def get_playwright_page(url: str):
    global _playwright, _browser, _context, _page
    if _playwright is None:
        logging.info("Starting Persistent Playwright Context with Stealth...")
        _playwright = sync_playwright().start()

        user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RomyAgentBrowserData", "PlaywrightProfile")
        os.makedirs(user_data_dir, exist_ok=True)

        try:
            # Launch a persistent context
            _context = _playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled"
                ]
            )

            _page = _context.pages[0] if _context.pages else _context.new_page()

            # Apply stealth to the context
            stealth = Stealth()
            stealth.apply_stealth_sync(_context)

            _browser = _context.browser

        except Exception as e:
            logging.critical(f"Failed to launch Playwright persistent context: {e}")
            return None

    if _page and _page.url == "about:blank" and url:
        try:
            _page.goto(url)
            _page.wait_for_load_state('networkidle')
        except Exception as e:
            logging.error(f"Error navigating to {url}: {e}")

    return _page

def _get_active_page():
    """Returns the currently visible Playwright page."""
    # Ensure browser is initialized
    get_playwright_page(None)

    active_page = None
    if _context:
        for page in _context.pages:
            try:
                if page.evaluate("document.visibilityState") == "visible":
                    active_page = page
                    break
            except Exception:
                continue

    if not active_page:
        active_page = get_playwright_page(None)

    return active_page

def init_browser_workspace():
    """Pre-launches the browser workspace and loads the default workspace URL from Firestore."""
    logging.info("Pre-launching Romy Workspace...")

    default_url = "about:blank"
    try:
        url_endpoint = "https://firestore.googleapis.com/v1/projects/romy-ai-agent/databases/(default)/documents/settings/default_workspace_url"
        headers = {"Authorization": f"Bearer {CURRENT_TOKEN}"}
        response = requests.get(url_endpoint, headers=headers)
        response.raise_for_status()
        url = response.json().get('fields', {}).get('url', {}).get('stringValue')
        if url:
            default_url = url
    except Exception as e:
        logging.error(f"Error fetching default workspace URL from Firestore: {e}")

    get_playwright_page(default_url)

def scan_web_ui() -> Tuple[list[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """
    Scans the web DOM for interactive elements.
    ROUTE: Playwright.
    Returns a list of UI element dictionaries and a memory map of ID to coordinates.
    """
    ui_elements = []
    memory_map = {}

    logging.info("Using Playwright for DOM scan...")
    try:
        # Strictly passive scanning: never pass a URL or trigger a reload
        active_page = _get_active_page()

        logging.info(f"Scanning active page URL: {active_page.url}")

        # Fetch viewport dimensions
        viewport = active_page.viewport_size
        vw = viewport['width'] if viewport else 1920
        vh = viewport['height'] if viewport else 1080

        elements = active_page.locator('button, a, input, select, textarea, [role="button"], [role="link"], [onclick], .btn, .button, [class*="btn"]').all()

        element_id = 1
        for el in elements:
            try:
                if not el.is_visible():
                    continue

                box = el.bounding_box()
                if not box or box['width'] == 0 or box['height'] == 0:
                    continue

                tag_name = el.evaluate("el => el.tagName.toLowerCase()")

                # Get text or name
                text = el.inner_text().strip()
                if not text:
                    text = el.get_attribute('value') or el.get_attribute('name') or el.get_attribute('id') or ''

                # Bounding box coordinates (center X, center Y)
                center_x = int(box['x'] + box['width'] / 2)
                center_y = int(box['y'] + box['height'] / 2)

                # Viewport pruning: Only keep elements within current viewport boundaries
                if not (0 <= center_x <= vw and 0 <= center_y <= vh):
                    continue

                element_str_id = str(element_id)

                # Inject custom attribute into the live DOM
                el.evaluate(f'(node) => {{ node.setAttribute("data-romy-id", "{element_str_id}"); }}')

                ui_elements.append({
                    "id": element_str_id,
                    "type": tag_name, # The prompt says Tag
                    "name": text      # The prompt says Text/Name
                })

                memory_map[element_str_id] = {
                    "x": center_x,
                    "y": center_y
                }

                element_id += 1
            except Exception as e:
                logging.error(f"Error extracting element {element_id}: {e}")

        logging.info(f"Found {len(ui_elements)} Web UI elements.")

    except Exception as e:
        logging.error(f"Error scanning web UI: {e}")

    return ui_elements, memory_map


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
        for control, depth in auto.WalkTree(active_window, getChildren=lambda c: c.GetChildren(), includeTop=True):
            # Filter for elements that are likely interactive or provide context
            control_type = control.ControlTypeName
            name = control.Name

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

def run_remote_agent_loop(doc_id: str, command_text: str) -> None:
    """Runs the agent loop triggered by a remote text command."""
    if not CURRENT_TOKEN:
        logging.error("Error: Missing Firebase Token. Cannot execute remote command.")
        return

    try:
        logging.info(f"=== Remote Agent Activated for Document: {doc_id} ===")
        try:
            notification.notify(title="ROMY AI", message=f"Remote command received: {command_text}", app_name="ROMY", timeout=2)
            if winsound: winsound.Beep(800, 200)
        except Exception:
            if winsound: winsound.Beep(800, 200)

        db = get_firestore_client()
        doc_ref = db.collection("remote_commands").document(doc_id)

        iteration = 0
        final_status = "completed"

        while True:
            if ABORT_AGENT:
                logging.info("Emergency abort triggered. Stopping remote agent loop.")
                final_status = "failed"
                break

            # Check for human response
            doc_snapshot = doc_ref.get()
            if doc_snapshot.exists:
                data = doc_snapshot.to_dict()
                if data.get("status") == "help_needed":
                    logging.info("Agent paused, waiting for human input...")
                    time.sleep(2)
                    continue

                if data.get("human_response"):
                    command_text += "\nHuman instruction: " + data.get("human_response")
                    doc_ref.update({"human_response": firestore.DELETE_FIELD})

            ui_elements, memory_map = scan_ui_elements()

            payload = {
                "ui_elements": ui_elements,
                "session_id": doc_id
            }
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

                actions = data.get("actions", [])

                # If backend returned older single-action format, wrap it
                if not actions and "action" in data:
                    actions = [data]

                break_outer = False
                had_terminal_action = False
                for act in actions:
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
                            doc_ref.update({
                                "status": "help_needed",
                                "help_reason": reason,
                                "screenshot_b64": img_str
                            })
                        except Exception as img_e:
                            logging.error(f"Error capturing screenshot: {img_e}")
                            doc_ref.update({
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
                    break
                logging.info(f"Request failed: {req_e}")
                final_status = "failed"
                break

            time.sleep(2)
            iteration += 1

        # Update final document status
        doc_ref.update({"status": final_status})
        logging.info(f"Remote command {doc_id} marked as {final_status}.")

    except Exception as e:
        logging.error(f"Error executing remote command: {e}")
        try:
            db = get_firestore_client()
            db.collection("remote_commands").document(doc_id).update({"status": "failed"})
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
        db = get_firestore_client()
        doc_ref = db.collection("remote_commands").document(doc_id)

        # Create or ensure the document exists
        try:
            doc_ref.set({"status": "in_progress", "command": "voice command"}, merge=True)
        except Exception as e:
            logging.error(f"Error setting up voice session document: {e}")

        while True:
            if ABORT_AGENT:
                logging.info("Emergency abort triggered. Stopping voice agent loop.")
                break

            # Check for human response
            try:
                doc_snapshot = doc_ref.get()
                if doc_snapshot.exists:
                    data = doc_snapshot.to_dict()
                    if data.get("status") == "help_needed":
                        logging.info("Agent paused, waiting for human input...")
                        time.sleep(2)
                        continue

                    if data.get("human_response"):
                        command_text += "\nHuman instruction: " + data.get("human_response")
                        doc_ref.update({"human_response": firestore.DELETE_FIELD})
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
                actions = data.get("actions", [])

                if not actions and "action" in data:
                    actions = [data]

                break_outer = False
                had_terminal_action = False
                for act in actions:
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
                            doc_ref.update({
                                "status": "help_needed",
                                "help_reason": reason,
                                "screenshot_b64": img_str
                            })
                        except Exception as img_e:
                            logging.error(f"Error capturing screenshot: {img_e}")
                            doc_ref.update({
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
