import base64
import io
import time
import os
import requests

import uiautomation as auto
import sounddevice as sd
from scipy.io.wavfile import write as wav_write
import pyautogui
from plyer import notification
import winsound
import firebase_admin
from firebase_admin import firestore
from typing import Dict, Any, Tuple
from playwright.sync_api import sync_playwright

pyautogui.FAILSAFE = False

BACKEND_URL = os.environ.get("BACKEND_URL", "https://romy-backend-1049976869239.europe-west1.run.app/api/v1/agent/command")

CURRENT_TOKEN = None
_db = None

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
                    print(f"Detected new remote command: {command_text}")

                    # Update status to in_progress
                    doc.reference.update({"status": "in_progress"})

                    # Execute the command
                    run_remote_agent_loop(doc_id, command_text)

        # Watch the collection query
        query.on_snapshot(on_snapshot)
        print("Started listening for remote commands on Firestore.")
    except Exception as e:
        print(f"Error starting remote listener: {e}")


_playwright = None
_browser = None
_page = None

def get_playwright_page(url: str):
    global _playwright, _browser, _page
    if _playwright is None:
        _playwright = sync_playwright().start()
        # Use --start-fullscreen to make viewport match screen coordinates for pyautogui
        _browser = _playwright.chromium.launch(headless=False, args=['--start-fullscreen'])
        context = _browser.new_context(viewport=None) # Use None to inherit fullscreen size
        _page = context.new_page()

    if _page.url != url and url:
        _page.goto(url)
        _page.wait_for_load_state('networkidle')

    return _page

def scan_web_ui(url="https://romy-ai-agent.web.app/sandbox.html") -> Tuple[list[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """
    Scans the web DOM for interactive elements using Playwright.
    Returns a list of UI element dictionaries and a memory map of ID to coordinates.
    """
    ui_elements = []
    memory_map = {}

    try:
        page = get_playwright_page(url)

        # Get elements
        # The prompt says: "extract all interactive elements (buttons, a, input)."
        elements = page.locator('button, a, input').all()

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

                element_str_id = str(element_id)

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
                print(f"Error extracting element {element_id}: {e}")

        print(f"Found {len(ui_elements)} Web UI elements.")

    except Exception as e:
        print(f"Error scanning web UI: {e}")

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

        print(f"Scanning UI tree for window: {active_window.Name}")

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

        print(f"Found {len(ui_elements)} UI elements.")
    except Exception as e:
        print(f"Error scanning UI tree: {e}")

    return ui_elements, memory_map

def run_remote_agent_loop(doc_id: str, command_text: str) -> None:
    """Runs the agent loop triggered by a remote text command."""
    if not CURRENT_TOKEN:
        print("Error: Missing Firebase Token. Cannot execute remote command.")
        return

    try:
        print(f"=== Remote Agent Activated for Document: {doc_id} ===")
        try:
            notification.notify(title="ROMY AI", message=f"Remote command received: {command_text}", app_name="ROMY", timeout=2)
            winsound.Beep(800, 200)
        except Exception:
            winsound.Beep(800, 200)

        db = get_firestore_client()
        doc_ref = db.collection("remote_commands").document(doc_id)

        iteration = 0
        final_status = "completed"

        while True:
            ui_elements, memory_map = scan_web_ui()

            payload = {
                "ui_elements": ui_elements
            }
            if iteration == 0:
                payload["command_text"] = command_text

            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            print(f"Sending remote payload to backend (iteration {iteration})...")
            try:
                response = requests.post(BACKEND_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                action = data.get("action", "")
                if isinstance(action, str):
                    action_upper = action.upper()
                else:
                    action_upper = str(action).upper()

                if action_upper == "DONE":
                    print("Remote task finished successfully.")
                    break
                elif "ERROR" in action_upper:
                    raw_response = data.get("raw_response", "No raw response provided")
                    error_msg = data.get("error", "No error message provided")
                    print(f"Remote agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                    final_status = "failed"
                    break
                elif action_upper == "CLICK" and "target_id" in data:
                    target_id = str(data["target_id"])
                    if target_id in memory_map:
                        x = memory_map[target_id]["x"]
                        y = memory_map[target_id]["y"]
                        print(f"Moving mouse to ({x}, {y}) and clicking...")
                        pyautogui.moveTo(x, y, duration=0.5)
                        pyautogui.click()
                        print(f"Successfully clicked at ({x}, {y}).")
                    else:
                        print(f"Error: target_id {target_id} not found in memory map.")
                else:
                    print(f"Received action: {action}. Continuing loop...")
            except requests.exceptions.RequestException as req_e:
                print(f"Request failed: {req_e}")
                final_status = "failed"
                break

            time.sleep(2)
            iteration += 1

        # Update final document status
        doc_ref.update({"status": final_status})
        print(f"Remote command {doc_id} marked as {final_status}.")

    except Exception as e:
        print(f"Error executing remote command: {e}")
        try:
            db = get_firestore_client()
            db.collection("remote_commands").document(doc_id).update({"status": "failed"})
        except Exception:
            pass


def record_audio(duration: int = 5) -> str:
    """
    Records microphone input for `duration` seconds, saves as WAV in memory,
    and returns the Base64 encoded string.
    """
    try:
        sample_rate = 44100
        print(f"Recording audio for {duration} seconds...")
        # Record audio
        recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='int16')
        sd.wait()  # Wait until recording is finished
        print("Recording finished.")

        # Save to an in-memory byte buffer
        wav_io = io.BytesIO()
        wav_write(wav_io, sample_rate, recording)
        wav_bytes = wav_io.getvalue()

        # Encode to base64
        b64_str = base64.b64encode(wav_bytes).decode('utf-8')
        return b64_str
    except Exception as e:
        print(f"Error recording audio: {e}")
        return ""


def activate_agent() -> None:
    """
    Activates the agent. Captures initial audio command, then enters the
    Agentic Loop, sending screen and audio data to the backend until DONE.
    """
    if not CURRENT_TOKEN:
        print("Error: Missing Firebase Token. Please log in first.")
        return

    try:
        print("=== Agent Activated: Ready for commands ===")

        # 1. Capture initial audio command
        try:
            notification.notify(title="ROMY AI", message="🎙️ Recording started... Speak your command now.", app_name="ROMY", timeout=2)
            winsound.Beep(1000, 200)
        except Exception:
            winsound.Beep(1000, 200)

        audio_b64 = record_audio(duration=5)

        try:
            notification.notify(title="ROMY AI", message="🧠 Processing command...", app_name="ROMY", timeout=2)
            winsound.Beep(800, 200)
        except Exception:
            winsound.Beep(800, 200)

        # 2. Start Agentic Loop
        iteration = 0
        while True:
            # 3. Scan UI Elements
            ui_elements, memory_map = scan_web_ui()

            # 4. Construct JSON payload
            payload = {
                "ui_elements": ui_elements
            }
            if iteration == 0:
                payload["audio_base64"] = audio_b64
            else:
                payload["audio_base64"] = ""

            # 5. Send POST to backend
            headers = {
                "Authorization": f"Bearer {CURRENT_TOKEN}",
                "Content-Type": "application/json"
            }

            print(f"Sending payload to backend (iteration {iteration})...")
            try:
                response = requests.post(BACKEND_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                # 6. Check response
                action = data.get("action", "")
                if isinstance(action, str):
                    action_upper = action.upper()
                else:
                    action_upper = str(action).upper()

                if action_upper == "DONE":
                    print("Task finished.")
                    break
                elif "ERROR" in action_upper:
                    raw_response = data.get("raw_response", "No raw response provided")
                    error_msg = data.get("error", "No error message provided")
                    print(f"Agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                    break
                elif action_upper == "CLICK" and "target_id" in data:
                    target_id = str(data["target_id"])
                    if target_id in memory_map:
                        x = memory_map[target_id]["x"]
                        y = memory_map[target_id]["y"]
                        print(f"Moving mouse to ({x}, {y}) and clicking...")
                        pyautogui.moveTo(x, y, duration=0.5)
                        pyautogui.click()
                        print(f"Successfully clicked at ({x}, {y}).")
                    else:
                        print(f"Error: target_id {target_id} not found in memory map.")
                else:
                    print(f"Received action: {action}. Continuing loop...")
            except requests.exceptions.RequestException as req_e:
                print(f"Request failed: {req_e}")
                # Break the loop on network failure to avoid infinite errors
                break

            # 7. Sleep for 2 seconds before next iteration
            time.sleep(2)
            iteration += 1

    except Exception as e:
        print(f"Error activating agent: {e}")
