import os
import json
import base64
import io
import re
from typing import Dict, Any, Optional, Tuple

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

def process_with_gemini(audio_b64: Optional[str] = None, command_text: Optional[str] = None, thread_history: str = "") -> str:
    """
    Uses Gemini 2.5 Flash to transcribe the audio command (or process textual command) and describe the state of the UI.
    """
    if gemini_client is None:
        print("Gemini client not initialized.")
        return "Error: Gemini client not initialized."

    try:
        client = gemini_client

        contents = []
        if audio_b64:
            contents.append(
                types.Part.from_bytes(
                    data=base64.b64decode(audio_b64),
                    mime_type="audio/wav"  # Defaulting to wav as client captures wav
                )
            )

        prompt = "Please transcribe the audio command (if any)."
        if command_text:
            prompt += f"\nAdditionally, the user provided this text command: '{command_text}'. Treat this as the primary instruction if provided."
        if thread_history:
            prompt += f"\nHere is the history of the current task session:\n{thread_history}"
        contents.append(prompt)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents
        )

        return response.text
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return f"Error analyzing context with Gemini: {e}"

def get_action_from_claude(ui_elements: list[Dict[str, Any]], context_text: str) -> Dict[str, Any]:
    """
    Uses Claude 3.5 Sonnet to determine the next logical action based on the Gemini context and UI elements list.
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
            "You are a structural RPA assistant. You are provided with a list of UI elements currently on the screen. "
            "Each element has an ID and a description/name. Based on the user's command, identify the correct target "
            "element and return ONLY a JSON block: {\"action\": \"CLICK\", \"target_id\": \"<the_number>\"}.\n"
            "If you encounter an unexpected popup, captcha, or cannot find the target, DO NOT guess or fail. "
            "Instead, return a JSON action: {\"action\": \"ASK_HUMAN\", \"reason\": \"<your specific question>\"}.\n"
        )
        if global_prompt:
            system_prompt += f"Global Instructions:\n{global_prompt}\n\n"

        ui_elements_str = json.dumps(ui_elements, indent=2)

        user_content = [
            {
                "type": "text",
                "text": f"Context from previous perception layer:\n{context_text}\n\nUI Elements:\n{ui_elements_str}\n\nBased on this context and the UI elements list, determine the correct target element."
            }
        ]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ],
            extra_headers={"anthropic-beta": "computer-use-2024-10-22"}
        )

        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        match = re.search(r'\{[^{}]*\}', response_text)
        if match:
            try:
                action_data = json.loads(match.group(0))
                if action_data.get("action") == "CLICK" and "target_id" in action_data:
                    return {
                        "action": "CLICK",
                        "target_id": str(action_data["target_id"])
                    }
                elif action_data.get("action") == "ASK_HUMAN" and "reason" in action_data:
                    return {
                        "action": "ASK_HUMAN",
                        "reason": str(action_data["reason"])
                    }
            except json.JSONDecodeError:
                pass

        return {"action": "PARSE_ERROR", "raw_response": str(response.content)}

    except Exception as e:
        print(f"Error calling Claude: {e}")
        return {"action": "API_ERROR", "error": str(e)}
