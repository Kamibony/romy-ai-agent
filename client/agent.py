import os
import io
import base64
import requests
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile
from mss import mss

def capture_screen() -> str:
    """
    Captures the primary monitor using mss, saves it to an in-memory PNG buffer,
    and returns the Base64 string.
    """
    try:
        with mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            sct_img = sct.grab(monitor)
            png_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
            return base64.b64encode(png_bytes).decode('utf-8')
    except Exception as e:
        print(f"Error capturing screen: {e}")
        return ""

def record_audio(duration: int = 5) -> str:
    """
    Records audio for `duration` seconds using sounddevice,
    saves it to an in-memory WAV buffer using scipy,
    and returns the Base64 string.
    """
    try:
        sample_rate = 44100
        print(f"Recording audio for {duration} seconds...")
        # Record audio
        recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='int16')
        sd.wait()  # Wait until recording is finished
        print("Audio recording complete.")

        # Save to in-memory buffer
        buffer = io.BytesIO()
        wavfile.write(buffer, sample_rate, recording)
        buffer.seek(0)

        return base64.b64encode(buffer.read()).decode('utf-8')
    except Exception as e:
        print(f"Error recording audio: {e}")
        return ""

def activate_agent() -> None:
    """
    Activates the agent.
    Captures screen and records audio, then sends to the backend.
    """
    try:
        print("=== Agent Activated: Processing commands ===")

        # Capture screen and record audio
        image_base64 = capture_screen()
        audio_base64 = record_audio()

        payload = {
            "image_base64": image_base64,
            "audio_base64": audio_base64
        }

        # Fetch environment variables
        backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
        firebase_token = os.environ.get("FIREBASE_TOKEN", "")

        headers = {
            "Authorization": f"Bearer {firebase_token}"
        }

        endpoint = f"{backend_url}/api/v1/agent/command"
        print(f"Sending payload to {endpoint}...")

        # Send POST request
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            print("Successfully sent command to backend:")
            print(response.json())
        else:
            print(f"Failed to send command. Status code: {response.status_code}")
            print(response.text)

    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
    except Exception as e:
        print(f"Error activating agent: {e}")
