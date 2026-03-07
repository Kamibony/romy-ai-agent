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
        return {"action": "API_ERROR", "error": "Anthropic client not initialized"}

    try:
        from firebase_admin import firestore
        db = firestore.client()
        global_prompt = ""
        try:
            settings_ref = db.collection("settings").document("global_prompt")
            settings_doc = settings_ref.get()
            if settings_doc.exists:
                global_prompt = settings_doc.to_dict().get("prompt", "")
        except Exception as e:
            print(f"Error reading global prompt from Firestore: {e}")

        client = anthropic_client

        system_prompt = (
            "You are a UI automation agent. You MUST extract X and Y coordinates and return "
            "ONLY a raw JSON object: {\"action\": \"CLICK\", \"x\": <int>, \"y\": <int>}.\n"
            "You are strictly forbidden from returning 'DONE', conversational text, or Markdown formatting (like ```json).\n"
            "If exact precision is difficult, you must estimate the coordinates based on the visual layout.\n\n"
        )
        if global_prompt:
            system_prompt += f"Global Instructions:\n{global_prompt}\n\n"

        system_prompt += (
            "You are an AI executing a computer task. "
            "You MUST reply with the strict JSON response and NOTHING ELSE. "
            "Do not wrap the JSON in markdown blocks. "
            "The JSON must follow this exact format: {\"action\": \"CLICK\", \"x\": <int>, \"y\": <int>}"
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
            model="claude-3-5-sonnet-latest",
            max_tokens=256,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ]
        )

        response_text = response.content[0].text

        # Robust data extraction: Strip markdown formatting and extraneous whitespace
        sanitized_text = response_text.strip()
        if sanitized_text.startswith("```json"):
            sanitized_text = sanitized_text[len("```json"):].strip()
        elif sanitized_text.startswith("```"):
            sanitized_text = sanitized_text[len("```"):].strip()

        if sanitized_text.endswith("```"):
            sanitized_text = sanitized_text[:-len("```")].strip()

        # Also handle potential conversational text before/after JSON by finding { and }
        start_idx = sanitized_text.find('{')
        end_idx = sanitized_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            sanitized_text = sanitized_text[start_idx:end_idx+1]

        # Ensure we can parse it as JSON
        try:
            action_dict = json.loads(sanitized_text)
            if "action" not in action_dict:
                return {"action": "FORMAT_ERROR", "error": "Missing 'action' key in JSON", "raw_response": action_dict}
            return action_dict
        except json.JSONDecodeError as e:
            print(f"Failed to decode Claude response as JSON. Original Response: {response_text}, Sanitized: {sanitized_text}, Error: {e}")
            return {"action": "PARSE_ERROR", "raw_response": response_text}

    except Exception as e:
        print(f"Error calling Claude: {e}")
        return {"action": "API_ERROR", "error": str(e)}
