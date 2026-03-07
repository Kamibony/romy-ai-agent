import base64
import io
import time
import os
import requests

import mss
import mss.tools
import sounddevice as sd
from scipy.io.wavfile import write as wav_write
import pyautogui
from plyer import notification
import winsound

pyautogui.FAILSAFE = False

BACKEND_URL = os.environ.get("BACKEND_URL", "https://romy-backend-1049976869239.europe-west1.run.app/api/v1/agent/command")

CURRENT_TOKEN = None

def set_firebase_token(token: str) -> None:
    """Sets the global Firebase token."""
    global CURRENT_TOKEN
    CURRENT_TOKEN = token


def capture_screen() -> str:
    """
    Captures the primary monitor using mss, saves it as PNG in memory,
    and returns the Base64 encoded string.
    """
    try:
        with mss.mss() as sct:
            # Monitor 1 is usually the primary monitor
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)

            # Save to an in-memory byte buffer
            img_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)

            # Encode to base64
            b64_str = base64.b64encode(img_bytes).decode('utf-8')
            return b64_str
    except Exception as e:
        print(f"Error capturing screen: {e}")
        return ""


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
            # 3. Capture screen
            image_b64 = capture_screen()

            # 4. Construct JSON payload
            payload = {
                "image_base64": image_b64
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
                elif action_upper == "PARSE_ERROR":
                    raw_response = data.get("raw_response", "No raw response provided")
                    print(f"Agent stopped due to PARSE_ERROR. Raw Claude response: {raw_response}")
                    break
                elif action_upper == "CLICK" and "x" in data and "y" in data:
                    try:
                        x = int(data["x"])
                        y = int(data["y"])
                        print(f"Moving mouse to ({x}, {y}) and clicking...")
                        pyautogui.moveTo(x, y, duration=0.5)
                        pyautogui.click()
                        print(f"Successfully clicked at ({x}, {y}).")
                    except ValueError:
                        print(f"Invalid coordinates received: x={data.get('x')}, y={data.get('y')}")
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
