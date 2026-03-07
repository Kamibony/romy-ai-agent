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


def process_with_gemini(image_b64: str, audio_b64: Optional[str] = None, command_text: Optional[str] = None) -> str:
    """
    Uses Gemini 2.5 Flash to transcribe the audio command (or process textual command) and describe the state of the UI.
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
        if command_text:
            prompt += f"\nAdditionally, the user provided this text command: '{command_text}'. Treat this as the primary instruction if provided."
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
    Uses Anthropic's native computer-use tool to get accurate X,Y coordinates.
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
            "You are a UI automation agent. You MUST use the provided computer tool to perform the next logical action. "
            "Use the `mouse_move` or `left_click` action with the computer tool to indicate where you want to click based on the user's intent.\n"
        )
        if global_prompt:
            system_prompt += f"Global Instructions:\n{global_prompt}\n\n"

        user_content = [
            {
                "type": "text",
                "text": f"Context from previous perception layer:\n{context_text}\n\nBased on this context and the screen image, use the computer tool to perform the next logical action (e.g. mouse_move or left_click) on the target."
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
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ],
            tools=[
                {
                    "type": "computer_20241022",
                    "name": "computer",
                    "display_width_px": 1920,
                    "display_height_px": 1080
                }
            ],
            extra_headers={"anthropic-beta": "computer-use-2024-10-22"}
        )

        extracted_x, extracted_y = None, None

        for block in response.content:
            if block.type == "tool_use" and block.name == "computer":
                if "coordinate" in block.input:
                    coords = block.input["coordinate"]
                    if len(coords) == 2:
                        extracted_x, extracted_y = coords[0], coords[1]
                        break

        if extracted_x is not None and extracted_y is not None:
            return {"action": "CLICK", "x": extracted_x, "y": extracted_y}

        return {"action": "PARSE_ERROR", "raw_response": str(response.content)}

    except Exception as e:
        print(f"Error calling Claude: {e}")
        return {"action": "API_ERROR", "error": str(e)}
