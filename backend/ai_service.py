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

from memory import save_playbook_rule, get_playbook_rules

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

def pre_flight_check_with_gemini(command_text: str) -> dict:
    """
    Checks if a given command has missing necessary information (like dates, cities).
    Returns {"status": "ok"} if all good, or {"status": "ASK_HUMAN", "reason": "..."} if missing info.
    """
    if not command_text or gemini_client is None:
        return {"status": "ok"}

    try:
        system_instruction = (
            "You are a pre-flight schema extraction agent for an AI assistant. "
            "Analyze the user's task description. Identify if any critical information required to complete the task is missing. "
            "For example, booking a flight requires a destination and dates (and optionally a departure city). "
            "If information is missing, return a JSON object like {\"status\": \"ASK_HUMAN\", \"reason\": \"I need to know the dates for your flight to Paris.\"} "
            "If the task seems fully specified or if it's a general task that doesn't need specific structured data, return strictly {\"status\": \"ok\"}."
        )

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[command_text],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "status": types.Schema(type=types.Type.STRING, description="'ok' or 'ASK_HUMAN'"),
                        "reason": types.Schema(type=types.Type.STRING, description="The reason if status is ASK_HUMAN"),
                    },
                    required=["status"]
                )
            )
        )
        result = json.loads(response.text.strip())
        return result
    except Exception as e:
        print(f"Error in pre-flight check: {e}")
        return {"status": "ok"}

def supervisor_plan_with_gemini(command_text: str) -> list[str]:
    """
    Breaks down a given task into sequential sub-tasks.
    Returns a list of strings representing the sub-tasks.
    """
    if not command_text or gemini_client is None:
        return []

    try:
        system_instruction = (
            "You are a Supervisor Agent. Your job is to take a high-level user request and break it down into a strictly sequential list of concrete sub-tasks. "
            "These sub-tasks will be executed by a web automation agent. "
            "Keep the sub-tasks concise and descriptive. Do not include execution details like 'click the button' or 'type text' unless necessary, instead use goals like 'Navigate to the website', 'Search for flights', etc. "
            "Output strictly a JSON array of strings, where each string is a sub-task. "
            "Example output: [\"Navigate to pelikan.cz\", \"Enter origin city\", \"Enter destination city\", \"Select departure date\", \"Click search\"]"
        )

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[command_text],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING)
                )
            )
        )

        result = json.loads(response.text.strip())
        if isinstance(result, list):
            return result
        return []
    except Exception as e:
        print(f"Error in supervisor planning: {e}")
        return []


def _run_critic_verification(sub_task: str, action_taken: dict, before_state: dict, after_state: dict, include_images: bool) -> dict:
    if gemini_client is None:
        return {"success": False, "reason": "Gemini client not initialized"}

    system_instruction = (
        "You are a Critic Verification Agent. Your job is to analyze the 'before' state of a UI, the specific 'action taken', and the 'after' state. "
        "Based on this, determine if the high-level 'sub-task' was successfully completed. "
        "For example, if the sub-task was 'Navigate to pelikan.cz', and the action was NAVIGATE, check if the after state reflects being on that site. "
        "If the sub-task was 'Enter destination city', and the action was TYPE, check if the text appears in the correct field in the after state. "
        "Output strictly a JSON object with a boolean 'success' and a string 'reason' explaining why."
    )

    prompt = (
        f"Sub-task to verify: {sub_task}\n\n"
        f"Action taken:\n{json.dumps(action_taken, indent=2)}\n\n"
        f"Before State UI Elements:\n{json.dumps(before_state.get('ui_elements', []), indent=2)}\n\n"
        f"After State UI Elements:\n{json.dumps(after_state.get('ui_elements', []), indent=2)}\n\n"
    )

    contents = []

    if include_images:
        before_screenshot = before_state.get("screenshot_base64")
        if before_screenshot:
            try:
                if "," in before_screenshot:
                    _, before_screenshot = before_screenshot.split(",", 1)
                img_data = base64.b64decode(before_screenshot)
                contents.append("Before State Screenshot:")
                contents.append(
                    types.Part.from_bytes(
                        data=img_data,
                        mime_type="image/webp"
                    )
                )
            except Exception as e:
                pass

        after_screenshot = after_state.get("screenshot_base64")
        if after_screenshot:
            try:
                if "," in after_screenshot:
                    _, after_screenshot = after_screenshot.split(",", 1)
                img_data = base64.b64decode(after_screenshot)
                contents.append("After State Screenshot:")
                contents.append(
                    types.Part.from_bytes(
                        data=img_data,
                        mime_type="image/webp"
                    )
                )
            except Exception as e:
                pass

    contents.append(prompt)

    response = gemini_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "success": types.Schema(type=types.Type.BOOLEAN),
                    "reason": types.Schema(type=types.Type.STRING),
                },
                required=["success", "reason"]
            )
        )
    )

    return json.loads(response.text.strip())

def critic_verify_with_gemini(sub_task: str, before_state: dict, action_taken: dict, after_state: dict) -> dict:
    """
    Verifies if a specific sub-task succeeded based on the states before and after an action.
    Implements a tiered approach: first checks strictly using text/JSON of pruned DOM.
    If uncertain or verification fails, falls back to multimodal image evaluation.
    Returns {"success": true/false, "reason": "..."}
    """
    try:
        # Tier 1: Fast path - Text-based JSON DOM evaluation only
        result = _run_critic_verification(sub_task, action_taken, before_state, after_state, include_images=False)

        # Tier 2: Slow path - Multimodal fallback if Tier 1 fails and images are available
        if not result.get("success"):
            has_before_image = bool(before_state.get("screenshot_base64"))
            has_after_image = bool(after_state.get("screenshot_base64"))

            if has_before_image or has_after_image:
                print("Text-based critic verify failed, falling back to multimodal verification...")
                fallback_result = _run_critic_verification(sub_task, action_taken, before_state, after_state, include_images=True)
                return fallback_result

        return result
    except Exception as e:
        print(f"Error in critic verification: {e}")
        return {"success": False, "reason": str(e)}


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

def synthesize_playbook_rule_with_gemini(domain: str, execution_telemetry: str) -> Optional[str]:
    """
    Synthesizer Agent (Sleep Cycle): Reviews execution telemetry for a domain and extracts a universal rule.
    Saves the rule to ChromaDB if found.
    """
    if not execution_telemetry or gemini_client is None:
        return None

    try:
        system_instruction = (
            "You are a Synthesizer Agent for an AI web assistant. Your job is to review the execution telemetry "
            "(the history of actions, successes, and especially failures/retries) for a specific website. "
            "Extract a single, concise, universal rule or 'playbook' for successfully interacting with this site. "
            "For example, 'On pelikan.cz, after typing the city, you must wait for the dropdown and explicitly click the suggestion.' "
            "If the telemetry is straightforward and no special rule is needed, return an empty string. "
            "Return ONLY the extracted rule string, or nothing."
        )

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[f"Domain: {domain}\nTelemetry:\n{execution_telemetry}"],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
            )
        )

        rule = response.text.strip()
        if rule:
            save_playbook_rule(domain, rule)
            return rule
        return None
    except Exception as e:
        print(f"Error synthesizing playbook rule: {e}")
        return None

def process_with_gemini(ui_elements: list[Dict[str, Any]], audio_b64: Optional[str] = None, command_text: Optional[str] = None, thread_history: str = "", screenshot_base64: Optional[str] = None, current_sub_task: Optional[str] = None, current_url: Optional[str] = None) -> list[Dict[str, Any]]:
    """
    Uses Gemini 2.5 Flash to process audio/text commands, a visual screenshot, and UI elements, returning an array of one or more actions.
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

        # Tiered Modality: The Navigator no longer receives the heavy screenshot_base64.
        # It relies entirely on the fast/cheap text-based ui_elements.
        # We leave the parameter in the signature for backward compatibility or if needed later.

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
            "You are a structural RPA assistant implementing a ReAct Loop. You are provided with "
            "a simplified list of UI elements on the screen. Each element in the list has an ID, xpath, and a description.\n\n"
            "Based on the user's command and current state, identify the correct target element and return one or more actions to execute next.\n\n"
            "Supported actions:\n"
            "- {\"action\": \"CLICK\", \"target_id\": \"<the_number>\", \"xpath\": \"<optional_xpath_fallback>\"}\n"
            "- {\"action\": \"TYPE\", \"target_id\": \"<the_number>\", \"xpath\": \"<optional_xpath_fallback>\", \"text\": \"<text to type>\"} (this automatically clears existing text first)\n"
            "- {\"action\": \"SCROLL\", \"direction\": \"down\"} (or \"up\")\n"
            "- {\"action\": \"NAVIGATE\", \"url\": \"<url>\"}\n"
            "- {\"action\": \"OPEN_TAB\", \"url\": \"<url>\"}\n"
            "- {\"action\": \"PRESS_KEY\", \"key\": \"<key>\"}\n"
            "- {\"action\": \"HOVER\", \"target_id\": \"<the_number>\", \"xpath\": \"<optional_xpath_fallback>\"}\n"
            "- {\"action\": \"WAIT_FOR\", \"selector\": \"<css_selector>\", \"max_wait_seconds\": 5}\n"
            "- {\"action\": \"RESET_VIEW\"} (use this to click outside or press Escape to close active overlays, dropdowns, date pickers, or modals and let the UI settle before verifying the state)\n"
            "- {\"action\": \"EXECUTE_JS\", \"code\": \"<javascript_code>\"} (use this to execute strictly read-only JS to extract DOM values or state variables missed by normal extraction, runs in isolated world)\n"
            "- {\"action\": \"REPLY\", \"text\": \"<the answer>\"}\n"
            "- {\"action\": \"SUB_TASK_COMPLETE\"} (use this when the current sub-task has been successfully achieved, and you are ready to move on to the next one)\n"
            "- {\"action\": \"DONE\"} (when the entire task across all sub-tasks is fully completed)\n"
            "If you cannot determine the next step or encounter an unexpected state, return: [{\"action\": \"ASK_HUMAN\", \"reason\": \"<your specific question>\"}].\n\n"
            "UNIVERSAL LAW OF STABLE STATE: Never fire SUB_TASK_COMPLETE immediately after interacting with a dynamic element. Typing text or clicking an input often triggers dynamic overlays (dropdowns, popups, date-pickers, hover menus). You must expect these to appear in the subsequent GET_STATE. Your task is NOT complete until the target UI reaches a final, stable state. Always explicitly use CLICK (to lock in an autocomplete suggestion or date) or RESET_VIEW (to dismiss an overlay) before considering the interaction finished. Never proceed to the next field or sub-task while an overlay is active.\n\n"
            "MACRO-ACTIONS & BATCHING: If you can confidently predict the next several deterministic steps (e.g., filling out a static form), return them as a batch in the array. If an action requires waiting for a dynamic UI element (like an autocomplete dropdown that hasn't rendered yet), end the batch at that action and wait for the next state. CRITICAL: Never include SUB_TASK_COMPLETE in the same batch as a TYPE action. You must always wait for the next state after typing to verify if an autocomplete dropdown appeared.\n\n"
            "SUB-TASK COMPLETION & STATE ADVANCEMENT: It is critical that you advance the state when a sub-task is met. If the sequence of actions you are about to output successfully fulfills the goal of the 'Current Sub-Task to execute', you MUST append {\"action\": \"SUB_TASK_COMPLETE\", \"thought\": \"Goal met, advancing...\"} as the FINAL object in your returned array. If you do not explicitly output this, the system will infinitely loop on the current sub-task. Only execute actions related to the current sub-task; do not preemptively perform actions for the next logical step until the system prompts you with the next sub-task.\n\n"
            "CRUCIAL INSTRUCTION: Return a valid JSON array containing one or more action objects. Do not return text outside the array.\n"
            "Example: [{\"action\": \"TYPE\", \"target_id\": \"1\", \"text\": \"London\", \"thought\": \"Typing origin\"}, {\"action\": \"CLICK\", \"target_id\": \"2\", \"thought\": \"Clicking search\"}]\n"
        )
        if global_prompt:
            system_instruction += f"Global Instructions:\n{global_prompt}\n\n"

        if current_url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(current_url).netloc
                if domain:
                    domain = domain.replace("www.", "")
                    playbook_rules = get_playbook_rules(domain)
                    if playbook_rules:
                        system_instruction += f"\n\n[SITE_SPECIFIC_RULE] for {domain}:\n"
                        for rule in playbook_rules:
                            system_instruction += f"- {rule}\n"
            except Exception as e:
                print(f"Error fetching playbook rules for {current_url}: {e}")

        ui_elements_str = json.dumps(ui_elements, indent=2)
        prompt = f"UI Elements:\n{ui_elements_str}\n\nDetermine the correct target element and output the JSON array of actions."

        if current_sub_task:
            prompt += f"\n\nCurrent Sub-Task to execute: {current_sub_task}"
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
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "action": types.Schema(type=types.Type.STRING),
                            "target_id": types.Schema(type=types.Type.STRING),
                            "xpath": types.Schema(type=types.Type.STRING),
                            "text": types.Schema(type=types.Type.STRING),
                            "direction": types.Schema(type=types.Type.STRING),
                            "url": types.Schema(type=types.Type.STRING),
                            "key": types.Schema(type=types.Type.STRING),
                            "selector": types.Schema(type=types.Type.STRING),
                            "max_wait_seconds": types.Schema(type=types.Type.NUMBER),
                            "reason": types.Schema(type=types.Type.STRING),
                            "code": types.Schema(type=types.Type.STRING, description="JavaScript code to execute"),
                            "thought": types.Schema(type=types.Type.STRING, description="The reasoning behind why this action was chosen")
                        },
                        required=["action", "thought"]
                    )
                )
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
                        thought = action_data.get("thought", "")
                        if action_data.get("action") == "CLICK" and "target_id" in action_data:
                            action_dict = {
                                "action": "CLICK",
                                "target_id": str(action_data["target_id"]),
                                "thought": thought
                            }
                            if "xpath" in action_data:
                                action_dict["xpath"] = str(action_data["xpath"])
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "TYPE" and "target_id" in action_data and "text" in action_data:
                            action_dict = {
                                "action": "TYPE",
                                "target_id": str(action_data["target_id"]),
                                "text": str(action_data["text"]),
                                "thought": thought
                            }
                            if "xpath" in action_data:
                                action_dict["xpath"] = str(action_data["xpath"])
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "SCROLL" and "direction" in action_data:
                            parsed_actions.append({
                                "action": "SCROLL",
                                "direction": str(action_data["direction"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "NAVIGATE" and "url" in action_data:
                            parsed_actions.append({
                                "action": "NAVIGATE",
                                "url": str(action_data["url"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "OPEN_TAB" and "url" in action_data:
                            parsed_actions.append({
                                "action": "OPEN_TAB",
                                "url": str(action_data["url"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "PRESS_KEY" and "key" in action_data:
                            parsed_actions.append({
                                "action": "PRESS_KEY",
                                "key": str(action_data["key"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "HOVER" and "target_id" in action_data:
                            action_dict = {
                                "action": "HOVER",
                                "target_id": str(action_data["target_id"]),
                                "thought": thought
                            }
                            if "xpath" in action_data:
                                action_dict["xpath"] = str(action_data["xpath"])
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "WAIT_FOR" and "selector" in action_data:
                            parsed_actions.append({
                                "action": "WAIT_FOR",
                                "selector": str(action_data["selector"]),
                                "max_wait_seconds": float(action_data.get("max_wait_seconds", 5)),
                                "thought": thought
                            })
                        elif action_data.get("action") == "REPLY" and "text" in action_data:
                            parsed_actions.append({
                                "action": "REPLY",
                                "text": str(action_data["text"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "ASK_HUMAN" and "reason" in action_data:
                            parsed_actions.append({
                                "action": "ASK_HUMAN",
                                "reason": str(action_data["reason"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "RESET_VIEW":
                            parsed_actions.append({
                                "action": "RESET_VIEW",
                                "thought": thought
                            })
                        elif action_data.get("action") == "EXECUTE_JS" and "code" in action_data:
                            parsed_actions.append({
                                "action": "EXECUTE_JS",
                                "code": str(action_data["code"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "SUB_TASK_COMPLETE":
                            parsed_actions.append({"action": "SUB_TASK_COMPLETE", "thought": thought})
                        elif action_data.get("action") == "DONE":
                            parsed_actions.append({"action": "DONE", "thought": thought})
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
                thought = action_data.get("thought", "")
                if action_data.get("action") == "CLICK" and "target_id" in action_data:
                    action_dict = {
                        "action": "CLICK",
                        "target_id": str(action_data["target_id"]),
                        "thought": thought
                    }
                    if "xpath" in action_data:
                        action_dict["xpath"] = str(action_data["xpath"])
                    return [action_dict]
                elif action_data.get("action") == "TYPE" and "target_id" in action_data and "text" in action_data:
                    action_dict = {
                        "action": "TYPE",
                        "target_id": str(action_data["target_id"]),
                        "text": str(action_data["text"]),
                        "thought": thought
                    }
                    if "xpath" in action_data:
                        action_dict["xpath"] = str(action_data["xpath"])
                    return [action_dict]
                elif action_data.get("action") == "SCROLL" and "direction" in action_data:
                    return [{
                        "action": "SCROLL",
                        "direction": str(action_data["direction"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "NAVIGATE" and "url" in action_data:
                    return [{
                        "action": "NAVIGATE",
                        "url": str(action_data["url"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "OPEN_TAB" and "url" in action_data:
                    return [{
                        "action": "OPEN_TAB",
                        "url": str(action_data["url"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "PRESS_KEY" and "key" in action_data:
                    return [{
                        "action": "PRESS_KEY",
                        "key": str(action_data["key"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "HOVER" and "target_id" in action_data:
                    action_dict = {
                        "action": "HOVER",
                        "target_id": str(action_data["target_id"]),
                        "thought": thought
                    }
                    if "xpath" in action_data:
                        action_dict["xpath"] = str(action_data["xpath"])
                    return [action_dict]
                elif action_data.get("action") == "WAIT_FOR" and "selector" in action_data:
                    return [{
                        "action": "WAIT_FOR",
                        "selector": str(action_data["selector"]),
                        "max_wait_seconds": float(action_data.get("max_wait_seconds", 5)),
                        "thought": thought
                    }]
                elif action_data.get("action") == "REPLY" and "text" in action_data:
                    return [{
                        "action": "REPLY",
                        "text": str(action_data["text"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "ASK_HUMAN" and "reason" in action_data:
                    return [{
                        "action": "ASK_HUMAN",
                        "reason": str(action_data["reason"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "RESET_VIEW":
                    return [{
                        "action": "RESET_VIEW",
                        "thought": thought
                    }]
                elif action_data.get("action") == "EXECUTE_JS" and "code" in action_data:
                    return [{
                        "action": "EXECUTE_JS",
                        "code": str(action_data["code"]),
                        "thought": thought
                    }]
                elif action_data.get("action") == "SUB_TASK_COMPLETE":
                    return [{"action": "SUB_TASK_COMPLETE", "thought": thought}]
                elif action_data.get("action") == "DONE":
                    return [{"action": "DONE", "thought": thought}]
            except json.JSONDecodeError:
                pass

        return [{"action": "PARSE_ERROR", "raw_response": str(response_text)}]

    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return [{"action": "API_ERROR", "error": str(e)}]
