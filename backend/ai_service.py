import os
import json
import base64
from typing import Dict, Any, Optional

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


# Initialize clients globally if possible
gemini_client = None
anthropic_client = None

if genai is not None:
    try:
        gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    except Exception as e:
        print(f"Failed to initialize Gemini client: {e}")

if Anthropic is not None:
    try:
        anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    except Exception as e:
        print(f"Failed to initialize Anthropic client: {e}")


def process_with_gemini(image_b64: str, audio_b64: Optional[str] = None) -> str:
    """
    Uses Gemini 2.5 Flash to transcribe the audio command and describe the state of the UI.
    """
    if gemini_client is None:
        print("Gemini client not initialized.")
        return "Error: Gemini client not initialized."

    try:
        client = gemini_client

        contents = []
        if image_b64:
            contents.append(
                types.Part.from_bytes(
                    data=base64.b64decode(image_b64),
                    mime_type="image/png"
                )
            )

        if audio_b64:
            contents.append(
                types.Part.from_bytes(
                    data=base64.b64decode(audio_b64),
                    mime_type="audio/wav"  # Defaulting to wav as client captures wav
                )
            )

        prompt = "Please transcribe the audio command (if any) and briefly describe the state of the UI shown in the image."
        contents.append(prompt)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents
        )

        return response.text
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return f"Error analyzing context with Gemini: {e}"


def get_action_from_claude(image_b64: str, context_text: str) -> Dict[str, Any]:
    """
    Uses Claude 3.5 Sonnet to determine the next logical action based on the Gemini context and screen image.
    Forces strict JSON response.
    """
    if anthropic_client is None:
        print("Anthropic client not initialized.")
        return {"action": "DONE"}

    try:
        client = anthropic_client

        system_prompt = (
            "You are an AI executing a computer task. "
            "You MUST reply with a strict JSON response and NOTHING ELSE. "
            "The JSON must follow one of these two formats:\n"
            "1. {\"action\": \"click\", \"x\": <int>, \"y\": <int>}\n"
            "2. {\"action\": \"DONE\"}\n"
            "Output 'DONE' if the task described in the context is complete or cannot be completed."
        )

        user_content = [
            {
                "type": "text",
                "text": f"Context from previous perception layer:\n{context_text}\n\nBased on this context and the screen image, determine the next logical action."
            }
        ]

        if image_b64:
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64
                }
            })

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=256,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ]
        )

        response_text = response.content[0].text

        # Ensure we can parse it as JSON
        try:
            action_dict = json.loads(response_text)
            if "action" not in action_dict:
                return {"action": "DONE"}
            return action_dict
        except json.JSONDecodeError as e:
            print(f"Failed to decode Claude response as JSON. Response: {response_text}, Error: {e}")
            return {"action": "DONE"}

    except Exception as e:
        print(f"Error calling Claude: {e}")
        return {"action": "DONE"}
