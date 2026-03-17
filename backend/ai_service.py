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

# Initialize clients globally if possible
gemini_client = None

if genai is not None:
    try:
        gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    except Exception as e:
        print(f"Failed to initialize Gemini client: {e}")

def transcribe_audio_with_gemini(audio_b64: str) -> str:
    """
    Transcribes audio to text using Gemini 2.5 Flash.
    """
    if not audio_b64 or gemini_client is None:
        return ""

    try:
        audio_data = base64.b64decode(audio_b64)
        if audio_data.startswith(b'\x1aE\xdf\xa3'):
            mime_type = "audio/webm"
        else:
            mime_type = "audio/wav"

        contents = [
            types.Part.from_bytes(
                data=audio_data,
                mime_type=mime_type
            ),
            "Transcribe this audio. Return ONLY the transcribed text without any extra explanation or formatting."
        ]

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.0,
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return ""

def classify_intent_with_gemini(command_text: str) -> str:
    """
    Classifies the user intent strictly as 'WEB' or 'OS' using Gemini 2.5 Flash.
    """
    if not command_text or gemini_client is None:
        return "OS"

    try:
        system_instruction = (
            "You are a routing dispatcher for an AI agent. Read the user's command. "
            "If the task requires a web browser (e.g., searching for flights, interacting with websites like pelikan.cz, scraping data), "
            "output exactly the word 'WEB'. If it requires interacting with native desktop applications or the OS, "
            "output exactly the word 'OS'. Do not include any other text."
        )

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[command_text],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
            )
        )

        result = response.text.strip().upper()
        if result == "WEB":
            return "WEB"
        return "OS"
    except Exception as e:
        print(f"Error classifying intent: {e}")
        return "OS"

def process_with_gemini(ui_elements: list[Dict[str, Any]], audio_b64: Optional[str] = None, command_text: Optional[str] = None, thread_history: str = "", screenshot_base64: Optional[str] = None) -> list[Dict[str, Any]]:
    """
    Uses Gemini 2.5 Flash to process audio/text commands, a visual screenshot, and UI elements, returning exactly ONE action in a list.
    """
    if not audio_b64 and not command_text:
        return [{"action": "ASK_HUMAN", "reason": "EMPTY_AUDIO"}]

    if gemini_client is None:
        print("Gemini client not initialized.")
        return [{"action": "API_ERROR", "error": "Gemini client not initialized."}]

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

        client = gemini_client

        contents = []
        if screenshot_base64:
            try:
                # Remove data URI scheme if present (e.g., data:image/webp;base64,)
                if "," in screenshot_base64:
                    _, screenshot_base64 = screenshot_base64.split(",", 1)
                img_data = base64.b64decode(screenshot_base64)
                contents.append(
                    types.Part.from_bytes(
                        data=img_data,
                        mime_type="image/webp"
                    )
                )
            except Exception as e:
                print(f"Error processing screenshot: {e}")

        if audio_b64:
            audio_data = base64.b64decode(audio_b64)
            # Detect mime type based on magic bytes
            # WebM starts with 1A 45 DF A3
            if audio_data.startswith(b'\x1aE\xdf\xa3'):
                mime_type = "audio/webm"
            else:
                mime_type = "audio/wav"

            contents.append(
                types.Part.from_bytes(
                    data=audio_data,
                    mime_type=mime_type
                )
            )

        system_instruction = (
            "You are a structural RPA assistant implementing a ReAct Loop. You are provided with a visual screenshot showing Set-of-Mark (SoM) labels, "
            "along with a simplified list of UI elements on the screen. Each element in the list has an ID corresponding to the visual label, xpath, and a description.\n\n"
            "Based on the user's command and current state, identify the correct target element and return strictly ONE action to execute next.\n\n"
            "Supported actions:\n"
            "- {\"action\": \"CLICK\", \"target_id\": \"<the_number>\", \"xpath\": \"<optional_xpath_fallback>\"}\n"
            "- {\"action\": \"TYPE\", \"target_id\": \"<the_number>\", \"xpath\": \"<optional_xpath_fallback>\", \"text\": \"<text to type>\"}\n"
            "- {\"action\": \"SCROLL\", \"direction\": \"down\"} (or \"up\")\n"
            "- {\"action\": \"NAVIGATE\", \"url\": \"<url>\"}\n"
            "- {\"action\": \"OPEN_TAB\", \"url\": \"<url>\"}\n"
            "- {\"action\": \"PRESS_KEY\", \"key\": \"<key>\"}\n"
            "- {\"action\": \"HOVER\", \"target_id\": \"<the_number>\", \"xpath\": \"<optional_xpath_fallback>\"}\n"
            "- {\"action\": \"WAIT_FOR\", \"selector\": \"<css_selector>\", \"max_wait_seconds\": 5}\n"
            "- {\"action\": \"REPLY\", \"text\": \"<the answer>\"}\n"
            "- {\"action\": \"DONE\"} (when the task is fully completed)\n"
            "If you cannot determine the next step or encounter an unexpected state, return: [{\"action\": \"ASK_HUMAN\", \"reason\": \"<your specific question>\"}].\n\n"
            "CRUCIAL INSTRUCTION: Return ONLY a valid JSON array containing exactly ONE action object. Do not return multiple actions. Do not return text outside the array.\n"
            "Example: [{\"action\": \"CLICK\", \"target_id\": \"1\", \"xpath\": \"//button\", \"thought\": \"Clicking the login button.\"}]\n"
        )
        if global_prompt:
            system_instruction += f"Global Instructions:\n{global_prompt}\n\n"

        ui_elements_str = json.dumps(ui_elements, indent=2)
        prompt = f"UI Elements:\n{ui_elements_str}\n\nDetermine the correct target element and output the JSON array of actions."

        if command_text:
            prompt += f"\n\nAdditional text command provided by user: {command_text}"
        if thread_history:
            prompt += f"\n\nThread History:\n{thread_history}"

        contents.append(prompt)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
            )
        )

        response_text = response.text

        # Try to parse the JSON array from the response
        match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if match:
            try:
                actions_data = json.loads(match.group(0))
                if isinstance(actions_data, list):
                    parsed_actions = []
                    for action_data in actions_data:
                        if action_data.get("action") == "CLICK" and "target_id" in action_data:
                            action_dict = {
                                "action": "CLICK",
                                "target_id": str(action_data["target_id"])
                            }
                            if "xpath" in action_data:
                                action_dict["xpath"] = str(action_data["xpath"])
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "TYPE" and "target_id" in action_data and "text" in action_data:
                            action_dict = {
                                "action": "TYPE",
                                "target_id": str(action_data["target_id"]),
                                "text": str(action_data["text"])
                            }
                            if "xpath" in action_data:
                                action_dict["xpath"] = str(action_data["xpath"])
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "SCROLL" and "direction" in action_data:
                            parsed_actions.append({
                                "action": "SCROLL",
                                "direction": str(action_data["direction"])
                            })
                        elif action_data.get("action") == "NAVIGATE" and "url" in action_data:
                            parsed_actions.append({
                                "action": "NAVIGATE",
                                "url": str(action_data["url"])
                            })
                        elif action_data.get("action") == "OPEN_TAB" and "url" in action_data:
                            parsed_actions.append({
                                "action": "OPEN_TAB",
                                "url": str(action_data["url"])
                            })
                        elif action_data.get("action") == "PRESS_KEY" and "key" in action_data:
                            parsed_actions.append({
                                "action": "PRESS_KEY",
                                "key": str(action_data["key"])
                            })
                        elif action_data.get("action") == "HOVER" and "target_id" in action_data:
                            action_dict = {
                                "action": "HOVER",
                                "target_id": str(action_data["target_id"])
                            }
                            if "xpath" in action_data:
                                action_dict["xpath"] = str(action_data["xpath"])
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "WAIT_FOR" and "selector" in action_data:
                            parsed_actions.append({
                                "action": "WAIT_FOR",
                                "selector": str(action_data["selector"]),
                                "max_wait_seconds": float(action_data.get("max_wait_seconds", 5))
                            })
                        elif action_data.get("action") == "REPLY" and "text" in action_data:
                            parsed_actions.append({
                                "action": "REPLY",
                                "text": str(action_data["text"])
                            })
                        elif action_data.get("action") == "ASK_HUMAN" and "reason" in action_data:
                            parsed_actions.append({
                                "action": "ASK_HUMAN",
                                "reason": str(action_data["reason"])
                            })
                        elif action_data.get("action") == "DONE":
                            parsed_actions.append({"action": "DONE"})
                        else:
                            # Keep it but let client figure it out or log it
                            parsed_actions.append(action_data)

                    if parsed_actions:
                        return parsed_actions
            except json.JSONDecodeError:
                pass

        # Fallback to single object if model ignored array instruction
        match_single = re.search(r'\{[^{}]*\}', response_text)
        if match_single:
            try:
                action_data = json.loads(match_single.group(0))
                if action_data.get("action") == "CLICK" and "target_id" in action_data:
                    action_dict = {
                        "action": "CLICK",
                        "target_id": str(action_data["target_id"])
                    }
                    if "xpath" in action_data:
                        action_dict["xpath"] = str(action_data["xpath"])
                    return [action_dict]
                elif action_data.get("action") == "TYPE" and "target_id" in action_data and "text" in action_data:
                    action_dict = {
                        "action": "TYPE",
                        "target_id": str(action_data["target_id"]),
                        "text": str(action_data["text"])
                    }
                    if "xpath" in action_data:
                        action_dict["xpath"] = str(action_data["xpath"])
                    return [action_dict]
                elif action_data.get("action") == "SCROLL" and "direction" in action_data:
                    return [{
                        "action": "SCROLL",
                        "direction": str(action_data["direction"])
                    }]
                elif action_data.get("action") == "NAVIGATE" and "url" in action_data:
                    return [{
                        "action": "NAVIGATE",
                        "url": str(action_data["url"])
                    }]
                elif action_data.get("action") == "OPEN_TAB" and "url" in action_data:
                    return [{
                        "action": "OPEN_TAB",
                        "url": str(action_data["url"])
                    }]
                elif action_data.get("action") == "PRESS_KEY" and "key" in action_data:
                    return [{
                        "action": "PRESS_KEY",
                        "key": str(action_data["key"])
                    }]
                elif action_data.get("action") == "HOVER" and "target_id" in action_data:
                    action_dict = {
                        "action": "HOVER",
                        "target_id": str(action_data["target_id"])
                    }
                    if "xpath" in action_data:
                        action_dict["xpath"] = str(action_data["xpath"])
                    return [action_dict]
                elif action_data.get("action") == "WAIT_FOR" and "selector" in action_data:
                    return [{
                        "action": "WAIT_FOR",
                        "selector": str(action_data["selector"]),
                        "max_wait_seconds": float(action_data.get("max_wait_seconds", 5))
                    }]
                elif action_data.get("action") == "REPLY" and "text" in action_data:
                    return [{
                        "action": "REPLY",
                        "text": str(action_data["text"])
                    }]
                elif action_data.get("action") == "ASK_HUMAN" and "reason" in action_data:
                    return [{
                        "action": "ASK_HUMAN",
                        "reason": str(action_data["reason"])
                    }]
                elif action_data.get("action") == "DONE":
                    return [{"action": "DONE"}]
            except json.JSONDecodeError:
                pass

        return [{"action": "PARSE_ERROR", "raw_response": str(response_text)}]

    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return [{"action": "API_ERROR", "error": str(e)}]
