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

def get_gemini_client():
    global gemini_client

    if gemini_client is not None:
        return gemini_client

    if genai is None:
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY environment variable is missing. AI functionality will be severely limited or return mock responses.")
        return None

    try:
        # Configure the Gemini client with a systemic timeout
        # http_options is used to set the timeout on the underlying httpx client
        http_options = genai.types.HttpOptions(
            timeout=120000,
            client_args={'timeout': 120},
            async_client_args={'timeout': 120}
        ) # 120 seconds total timeout
        gemini_client = genai.Client(
            api_key=api_key,
            http_options=http_options
        )
        return gemini_client
    except Exception as e:
        print(f"Failed to initialize Gemini client: {e}")
        return None

# Attempt to initialize immediately if the key is already present
get_gemini_client()

def transcribe_audio_with_gemini(audio_b64: str) -> str:
    """
    Transcribes audio to text using Gemini 2.5 Flash.
    """
    client = get_gemini_client()
    if not audio_b64 or client is None:
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

        response = client.models.generate_content(
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
    client = get_gemini_client()
    if not command_text or client is None:
        return {"status": "ok"}

    try:
        system_instruction = (
            "You are a pre-flight schema extraction agent for an AI assistant. "
            "AGENT ONTOLOGY: You are a hybrid automation agent equipped with a physical kinematic engine. "
            "You have full capability to physically control the native OS mouse and keyboard (CLICK, TYPE, DRAG_AND_DROP). "
            "Do NOT reject tasks involving spatial interaction, drawing, or native OS manipulation. "
            "Analyze the user's task description. Identify if any critical information required to complete the task is missing. "
            "For example, booking a flight requires a destination and dates (and optionally a departure city). "
            "If information is missing, return a JSON object like {\"status\": \"ASK_HUMAN\", \"reason\": \"I need to know the dates for your flight to Paris.\"} "
            "If the task seems fully specified or if it's a general task that doesn't need specific structured data, return strictly {\"status\": \"ok\"}."
        )

        response = client.models.generate_content(
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

def supervisor_plan_with_gemini(command_text: str, completed_tasks: list[str] = None, task_index: int = None, roadblock_reason: str = None) -> list[str]:
    """
    Breaks down a given task into sequential sub-tasks.
    Returns a list of strings representing the sub-tasks.
    """
    client = get_gemini_client()
    if not command_text or client is None:
        return []

    try:
        system_instruction = (
            "You are a Supervisor Agent. Your job is to take a high-level user request and break it down into a strictly sequential list of concrete sub-tasks. "
            "AGENT ONTOLOGY: The execution agent is a hybrid engine with a physical kinematic body. It has full mouse and keyboard capabilities across both Web and OS. It will not reject physical/spatial tasks. "
            "These sub-tasks will be executed by a hybrid automation agent (capable of both WEB and OS interactions). "
            "Keep the sub-tasks concise and descriptive. Do not include execution details like 'click the button' or 'type text' unless necessary, instead use goals like 'Navigate to the website', 'Search for flights', 'Open Calculator', etc. "
            "Crucially, you MUST prefix each sub-task string with either `[WEB]` or `[OS]` to explicitly tag the target environment. "
            "Output strictly a JSON array of strings, where each string is a prefixed sub-task. "
            "Example output: [\"[WEB] Navigate to pelikan.cz\", \"[WEB] Enter origin city\", \"[OS] Open Calculator\", \"[WEB] Select departure date\"]"
        )

        if roadblock_reason:
            system_instruction += (
                f"\n\nThe agent encountered a roadblock while executing task {task_index}. Reason: {roadblock_reason}. "
                f"The following tasks have already been completed: {completed_tasks}. "
                "Do NOT re-generate the completed tasks. Instead, generate a NEW sequence of sub-tasks to complete the remaining work, adjusting for the roadblock. "
                "Output ONLY the new sub-tasks that need to be appended to the completed tasks."
            )

        response = client.models.generate_content(
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


def evaluate_plan_progress_with_gemini(command_text: str, current_sub_task: str, remaining_plan: list[str], screenshot_base64: str, ui_elements: list[Dict[str, Any]]) -> dict:
    """
    Evaluates if the current sub-task is already accomplished based on the current UI state.
    """
    client = get_gemini_client()
    if client is None:
        return {"is_accomplished": False, "reason": "Gemini client not initialized"}

    system_instruction = (
        "You are a State Evaluation Agent. Your job is to analyze the current visual and structural state of a UI "
        "and determine if the 'Current Sub-Task' has ALREADY been successfully accomplished. "
        "For example, if the sub-task is 'Search for YouTube videos' and the current screen already shows YouTube search results for the query, "
        "you must mark it as accomplished. If the sub-task is 'Navigate to pelikan.cz' and the browser is already on pelikan.cz, it is accomplished.\n\n"
        "Output strictly a JSON object with a boolean 'is_accomplished' and a string 'reason' explaining why."
    )

    prompt = (
        f"Overall Command: {command_text}\n\n"
        f"Current Sub-Task to evaluate: {current_sub_task}\n\n"
        f"Remaining Plan:\n{json.dumps(remaining_plan, indent=2)}\n\n"
        f"Current UI Elements:\n{json.dumps(ui_elements[:50], indent=2)}\n\n"
    )

    contents = []

    if screenshot_base64:
        try:
            if "," in screenshot_base64:
                _, screenshot_base64 = screenshot_base64.split(",", 1)
            img_data = base64.b64decode(screenshot_base64)
            contents.append("Current State Screenshot:")

            mime_type = "image/webp"
            if img_data.startswith(b'\xff\xd8\xff'):
                mime_type = "image/jpeg"
            elif img_data.startswith(b'\x89PNG\r\n\x1a\n'):
                mime_type = "image/png"

            contents.append(
                types.Part.from_bytes(
                    data=img_data,
                    mime_type=mime_type
                )
            )
        except Exception as e:
            pass

    contents.append(prompt)

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "is_accomplished": types.Schema(type=types.Type.BOOLEAN),
                        "reason": types.Schema(type=types.Type.STRING),
                    },
                    required=["is_accomplished", "reason"]
                )
            )
        )
        return json.loads(response.text.strip())
    except Exception as e:
        print(f"Error in evaluate_plan_progress: {e}")
        return {"is_accomplished": False, "reason": str(e)}

def _run_critic_verification(sub_task: str, action_taken: dict, before_state: dict, after_state: dict, include_images: bool) -> dict:
    client = get_gemini_client()
    if client is None:
        return {"success": False, "reason": "Gemini client not initialized"}

    system_instruction = (
        "You are a Critic Verification Agent. Your job is to analyze the 'before' state of a UI, the specific 'action taken', and the 'after' state. "
        "Based on this, determine if the high-level 'sub-task' was successfully completed. "
        "For example, if the sub-task was 'Navigate to pelikan.cz', and the action was NAVIGATE, check if the after state reflects being on that site. "
        "If the sub-task was 'Enter destination city', and the action was TYPE, check if the text appears in the correct field in the after state. "
        "STATE EXCLUSIVITY: When evaluating completion, verify that ONLY the requested state is active. If the sub-task requires a specific value (e.g., 'Enter origin city Prague'), you must ensure that ANY pre-existing, conflicting, or default values (e.g., 'Vienna') have been successfully removed or overwritten. Partial presence is a failure.\n"
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

                mime_type = "image/webp"
                if img_data.startswith(b'\xff\xd8\xff'):
                    mime_type = "image/jpeg"
                elif img_data.startswith(b'\x89PNG\r\n\x1a\n'):
                    mime_type = "image/png"

                contents.append(
                    types.Part.from_bytes(
                        data=img_data,
                        mime_type=mime_type
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

                mime_type = "image/webp"
                if img_data.startswith(b'\xff\xd8\xff'):
                    mime_type = "image/jpeg"
                elif img_data.startswith(b'\x89PNG\r\n\x1a\n'):
                    mime_type = "image/png"

                contents.append(
                    types.Part.from_bytes(
                        data=img_data,
                        mime_type=mime_type
                    )
                )
            except Exception as e:
                pass

    contents.append(prompt)

    response = client.models.generate_content(
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
    client = get_gemini_client()
    if not command_text or client is None:
        return "OS"

    try:
        system_instruction = (
            "You are a routing dispatcher for an AI agent. Read the user's command. "
            "AGENT ONTOLOGY: The executing agent is a hybrid automation bot with a physical kinematic body capable of manipulating both Web and Native OS environments. "
            "If the task requires a web browser (e.g., searching for flights, interacting with websites like pelikan.cz, scraping data), "
            "output exactly the word 'WEB'. If it requires interacting with native desktop applications or the OS, "
            "output exactly the word 'OS'. Do not include any other text."
        )

        response = client.models.generate_content(
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

def compile_sop_with_gemini(domain: str, raw_sop: str, client_id: str = None, target_sub_task: str = None) -> Optional[str]:
    """
    SOP Compiler Pipeline: Takes raw human SOP text and translates it into an agent-friendly
    playbook rule, checking for existing rules to consolidate.
    """
    client = get_gemini_client()
    if not raw_sop or client is None:
        return None

    try:
        existing_rules = []
        if target_sub_task:
            existing_rules = get_playbook_rules(domain, client_id=client_id, goal=target_sub_task)

        system_instruction = (
            "You are an SOP Compiler Agent. A human operator has provided raw text outlining a "
            "Standard Operating Procedure (SOP). Your job is to translate this human text into a strict, "
            "universal playbook rule that an automated RPA agent can reliably follow.\n"
            "Format the rule clearly, typically as 'Condition -> Action'. Ensure it uses the agent's ontology "
            "(CLICK, TYPE, WAIT, WAIT_FOR, etc.).\n"
            "CRITICAL ASYNC RACE CONDITION FIX: You MUST inject explicit visual 'Wait' conditions for dynamic UI changes. "
            "If the human SOP implies an action that triggers a loading state, a modal, or a page navigation, you MUST add a rule like: "
            "'WAIT_FOR modal to appear' or 'WAIT 2 seconds' before the next action. Do not assume immediate rendering."
        )

        if existing_rules:
            system_instruction += (
                "\nCRITICAL: There are existing rules for this domain. "
                "Analyze the new SOP AND the existing rules. Generate a NEW, updated rule that "
                "incorporates the human SOP and safely replaces the old ones without losing critical context."
            )

        system_instruction += (
            "\nReturn ONLY the final compiled rule string."
        )

        prompt = f"Domain: {domain}\nRaw Human SOP:\n{raw_sop}"
        if target_sub_task:
            prompt += f"\nTarget Sub-task: {target_sub_task}"
        if existing_rules:
            prompt += f"\n\n[EXISTING RULES]:\n" + "\n".join(existing_rules)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,
            )
        )

        rule = response.text.strip()
        if rule:
            save_playbook_rule(domain, rule, client_id=client_id, goal=target_sub_task, source="manual_sop")
            return rule
        return None
    except Exception as e:
        print(f"Error compiling SOP: {e}")
        return None

def synthesize_playbook_rule_with_gemini(domain: str, execution_telemetry: str, client_id: str = None, failed_sub_task: str = None) -> Optional[str]:
    """
    Synthesizer Agent (Sleep Cycle): Reviews execution telemetry or human correction for a domain and extracts a universal rule.
    Implements Memory Lifecycle Management: if old rules exist for the subtask, updates/replaces them.
    Saves the rule to ChromaDB if found.
    """
    client = get_gemini_client()
    if not execution_telemetry or client is None:
        return None

    try:
        existing_rules = []
        if failed_sub_task:
            existing_rules = get_playbook_rules(domain, client_id=client_id, goal=failed_sub_task)

        system_instruction = (
            "You are a Synthesizer Agent (Memory Lifecycle Manager) for an AI assistant. "
            "Your job is to review execution telemetry or a human operator's correction for a specific website or OS app, "
            "and extract a single, concise, universal rule or 'SOP' (Standard Operating Procedure) for successfully completing the failed sub-task. "
        )

        if existing_rules:
            system_instruction += (
                "CRITICAL: There are existing rules for this sub-task that failed. The human's intervention means the OLD rule might be stale, incomplete, or incorrect. "
                "Analyze the new telemetry AND the old rule. Generate a NEW, updated, consolidated rule that completely replaces the old one. "
            )

        system_instruction += (
            "Return ONLY the final, updated rule string. If no special rule is needed, return an empty string."
        )

        prompt = f"Domain: {domain}\nTelemetry/Human Correction:\n{execution_telemetry}"
        if failed_sub_task:
            prompt += f"\nGoal/Failed Sub-task: {failed_sub_task}"
        if existing_rules:
            prompt += f"\n\n[EXISTING STALE RULES TO REPLACE]:\n" + "\n".join(existing_rules)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
            )
        )

        rule = response.text.strip()
        if rule:
            save_playbook_rule(domain, rule, client_id=client_id, goal=failed_sub_task)
            return rule
        return None
    except Exception as e:
        print(f"Error synthesizing playbook rule: {e}")
        return None

def process_with_gemini(ui_elements: list[Dict[str, Any]], audio_b64: Optional[str] = None, command_text: Optional[str] = None, thread_history: str = "", screenshot_base64: Optional[str] = None, current_sub_task: Optional[str] = None, current_url: Optional[str] = None, client_context: Optional[Dict[str, Any]] = None, clipboard_status: Optional[str] = "unknown", differential_passing_active: bool = False) -> Dict[str, Any]:
    """
    Uses Gemini 2.5 Flash to process audio/text commands, a visual screenshot, and UI elements, returning an array of one or more actions.
    """
    if not audio_b64 and not command_text:
        return {"actions": [{"action": "ASK_HUMAN", "reason": "EMPTY_AUDIO"}], "memory_rules": []}

    client = get_gemini_client()
    if client is None:
        print("Gemini client not initialized.")
        return {"actions": [{"action": "API_ERROR", "error": "Gemini client not initialized (missing API Key)."}], "memory_rules": []}

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

        contents = []

        # Vision-First Paradigm: The Navigator relies on the screenshot to output precise coordinates.
        if screenshot_base64:
            try:
                if "," in screenshot_base64:
                    _, screenshot_base64 = screenshot_base64.split(",", 1)
                img_data = base64.b64decode(screenshot_base64)

                # Detect mime type from magic bytes
                mime_type = "image/webp" # default
                if img_data.startswith(b'\xff\xd8\xff'):
                    mime_type = "image/jpeg"
                elif img_data.startswith(b'\x89PNG\r\n\x1a\n'):
                    mime_type = "image/png"

                contents.append(
                    types.Part.from_bytes(
                        data=img_data,
                        mime_type=mime_type
                    )
                )
            except Exception as e:
                print(f"Error decoding screenshot: {e}")

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
            "You are a Vision-First RPA assistant implementing a ReAct Loop. You will be provided with "
            "a screenshot of the current state of the application.\n\n"
            "AGENT ONTOLOGY: You are a hybrid automation agent equipped with a physical kinematic body integrated with the host OS. "
            "You have full capability to physically move the mouse, click, type on the keyboard, and perform spatial actions like DRAG_AND_DROP across both Web and Native Desktop environments. "
            "Confidently attempt any spatial, drawing, or physical interaction requested without rejecting it.\n\n"
            "Based on the user's command, the current sub-task, and the visual state, locate the correct target element. "
            "You must output the exact target_id of the Set-of-Mark box, or if unavailable, the [x, y] coordinates representing the center of the target element.\n\n"
            "Supported actions:\n"
            "- {\"action\": \"CLICK\", \"target_id\": \"<id>\", \"coordinates\": [x, y]} (CRUCIAL: If there is a GDPR cookie banner, consent modal, or popup overlapping the page, your VERY FIRST action MUST be to CLICK its \"Accept\", \"Agree\", or \"Close\" button before attempting to interact with any other elements on the main page.)\n"
            "- {\"action\": \"HOVER\", \"target_id\": \"<id>\", \"coordinates\": [x, y]} (CRITICAL: When interacting with complex navigation bars, mega-menus, or elements that might be hidden inside dropdowns (like on e-commerce sites), you MUST output a HOVER action on the parent category to reveal the sub-menu BEFORE attempting to CLICK the child item.)\n"
            "- {\"action\": \"TYPE\", \"target_id\": \"<id>\", \"coordinates\": [x, y], \"text\": \"<text to type>\", \"submit\": true} (this automatically focuses the element, types, and natively submits by pressing Enter if submit=true)\n"
            "- {\"action\": \"DRAG_AND_DROP\", \"start_x\": <x1>, \"start_y\": <y1>, \"end_x\": <x2>, \"end_y\": <y2>} (Executes a continuous physical mouse drag from start coordinates to end coordinates. Required for drawing or moving items in OS.)\n"
            "- {\"action\": \"SEARCH\", \"target_id\": \"<id>\", \"coordinates\": [x, y], \"text\": \"<search query>\"} (use this explicitly when searching. It acts identically to TYPE with submit=true, bypassing autocomplete dropdowns completely.)\n"
            "- {\"action\": \"SCROLL\", \"direction\": \"down\"} (or \"up\")\n"
            "- {\"action\": \"NAVIGATE\", \"url\": \"<url>\"}\n"
            "- {\"action\": \"OPEN_TAB\", \"url\": \"<url>\"}\n"
            "- {\"action\": \"LAUNCH_APP\", \"app_name\": \"<executable_name>\"} (Deterministic OS app launch. Provide the core executable name, e.g., 'calc.exe', 'mspaint.exe', 'notepad.exe'. This action MUST be the final action in a batch, allowing the UI to stabilize and fetch the next state.)\n"
            "- {\"action\": \"PRESS_KEY\", \"key\": \"<key>\"}\n"
            "- {\"action\": \"WAIT_FOR\", \"selector\": \"<css_selector>\", \"max_wait_seconds\": 5}\n"
            "- {\"action\": \"WAIT\", \"seconds\": 2} (CRITICAL: Use this to explicitly self-regulate patience if you detect \"Skeleton UIs\", visible loading spinners, progress bars, or a half-loaded page. Do not attempt to click or read data until the data fetch finishes and the final UI is rendered.)\n"
            "- {\"action\": \"RESET_VIEW\"} (use this to click outside or press Escape to close active overlays, dropdowns, date pickers, or modals and let the UI settle before verifying the state)\n"
            "- {\"action\": \"EXECUTE_JS\", \"code\": \"<javascript_code>\"}\n"
            "- {\"action\": \"REPLY\", \"text\": \"<the answer>\"}\n"
            "- {\"action\": \"SUB_TASK_COMPLETE\"} (use this when the current sub-task has been successfully achieved, and you are ready to move on to the next one)\n"
            "- {\"action\": \"DONE\"} (when the entire task across all sub-tasks is fully completed)\n"
            "If you cannot determine the next step or encounter an unexpected state, return: [{\"action\": \"ASK_HUMAN\", \"reason\": \"<your specific question>\"}].\n\n"
            "UNIVERSAL LAW OF STABLE STATE: Never fire SUB_TASK_COMPLETE immediately after interacting with a dynamic element. Typing text or clicking an input often triggers dynamic overlays (dropdowns, popups, date-pickers, hover menus). You must expect these to appear in the subsequent GET_STATE. Your task is NOT complete until the target UI reaches a final, stable state. Always explicitly use CLICK (to lock in an autocomplete suggestion or date) or RESET_VIEW (to dismiss an overlay) before considering the interaction finished. Never proceed to the next field or sub-task while an overlay is active.\n\n"
            "EPISTEMOLOGICAL BARRIER (EXECUTION VS VERIFICATION): Never assume an action (like TYPE, CLICK, or DRAG_AND_DROP) succeeded simply because you dispatched it. You MUST separate the ACTING phase from the VERIFYING phase. After executing a state-mutating action, you are strictly FORBIDDEN from immediately outputting SUB_TASK_COMPLETE in the same batch. You must either end the batch or use a WAIT action to allow a new visual frame/DOM tree to be captured. You may only mark a sub-task as complete in a subsequent iteration AFTER visually or structurally verifying the physical state change (e.g., observing the text physically present in the target UI).\n\n"
            "STATE EXCLUSIVITY: Fulfilling a sub-task inherently requires validating that no conflicting or unrequested state remains active. If the requested data exists, do NOT assume success if legacy or conflicting data (e.g., default UI chips, leftover shopping cart items, conflicting search filters) is also present. You must actively remove or overwrite conflicting values to achieve exclusive state.\n\n"
            "MACRO-ACTIONS & BATCHING: If you can confidently predict the next several deterministic steps (e.g., filling out a static form), return them as a batch in the array. If an action requires waiting for a dynamic UI element (like an autocomplete dropdown that hasn't rendered yet), end the batch at that action and wait for the next state. CRITICAL: Never include SUB_TASK_COMPLETE in the same batch as a TYPE action. You must always wait for the next state after typing to verify if an autocomplete dropdown appeared.\n\n"
            "SUB-TASK COMPLETION & STATE ADVANCEMENT: It is critical that you advance the state when a sub-task is met. If the sequence of actions you are about to output successfully fulfills the goal of the 'Current Sub-Task to execute', you MUST append {\"action\": \"SUB_TASK_COMPLETE\", \"thought\": \"Goal met, advancing...\"} as the FINAL object in your returned array. If you do not explicitly output this, the system will infinitely loop on the current sub-task. Only execute actions related to the current sub-task; do not preemptively perform actions for the next logical step until the system prompts you with the next sub-task.\n\n"
            "CRUCIAL INSTRUCTION: Return a valid JSON array containing one or more action objects. Do not return text outside the array.\n"
            "Example: [{\"action\": \"TYPE\", \"target_id\": \"5\", \"text\": \"London\", \"thought\": \"Typing origin\"}, {\"action\": \"CLICK\", \"target_id\": \"12\", \"thought\": \"Clicking search\"}]\n"
        )
        if global_prompt:
            system_instruction += f"Global Instructions:\n{global_prompt}\n\n"

        playbook_rules_applied = []
        client_id = None
        if client_context:
            system_instruction += "\n\n[CLIENT PROFILE CONTEXT]:\n"
            system_instruction += f"You are acting on behalf of the following client profile:\n"
            system_instruction += json.dumps(client_context, indent=2) + "\n"
            system_instruction += "Adhere to these business rules, preferred UI behaviors, and roles when executing tasks.\n\n"
            client_id = client_context.get("client_id")

        if current_url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(current_url).netloc
                if domain:
                    domain = domain.replace("www.", "")
                    # Optionally, if it's an OS app, it might not have 'www.'. We can use the current_url as domain.
                    if "://" not in current_url:
                        domain = current_url
                    playbook_rules = get_playbook_rules(domain, client_id=client_id, goal=current_sub_task)
                    if playbook_rules:
                        playbook_rules_applied = playbook_rules
                        system_instruction += f"\n\n[SITE_SPECIFIC_RULE] for {domain}:\n"
                        for rule in playbook_rules:
                            system_instruction += f"- {rule}\n"
            except Exception as e:
                print(f"Error fetching playbook rules for {current_url}: {e}")

        prompt = f"Determine the correct target element from the image and output the JSON array of actions using target_id or [x, y] coordinates."

        if differential_passing_active:
             prompt += "\n\nNote: The visual state has not changed meaningfully since the last action. The screenshot has been omitted to save bandwidth. Please refer to your previous visual analysis or rely on the text/DOM structure to determine the next step."

        if current_sub_task:
            prompt += f"\n\nCurrent Sub-Task to execute: {current_sub_task}"
        if command_text:
            prompt += f"\n\nAdditional text command provided by user: {command_text}"
        if thread_history:
            prompt += f"\n\nThread History:\n{thread_history}"
        if clipboard_status:
            prompt += f"\n\nMulti-Modal System State: Clipboard status is '{clipboard_status}'."

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
                            "action": types.Schema(
                                type=types.Type.STRING,
                                    enum=["CLICK", "TYPE", "SEARCH", "SCROLL", "NAVIGATE", "OPEN_TAB", "LAUNCH_APP", "PRESS_KEY", "WAIT_FOR", "WAIT", "RESET_VIEW", "EXECUTE_JS", "REPLY", "SUB_TASK_COMPLETE", "DONE", "ASK_HUMAN", "DRAG_AND_DROP", "HOVER"]
                            ),
                            "target_id": types.Schema(
                                type=types.Type.STRING,
                                description="The ID of the Set-of-Mark box to interact with (preferred over coordinates)"
                            ),
                            "x": types.Schema(
                                type=types.Type.NUMBER,
                                description="Fallback X coordinate if target_id is not available"
                            ),
                            "y": types.Schema(
                                type=types.Type.NUMBER,
                                description="Fallback Y coordinate if target_id is not available"
                            ),
                            "coordinates": types.Schema(
                                type=types.Type.ARRAY,
                                items=types.Schema(type=types.Type.NUMBER),
                                description="Fallback [x, y] coordinates if target_id is not available"
                            ),
                                "start_x": types.Schema(type=types.Type.NUMBER, description="Starting X coordinate for DRAG_AND_DROP"),
                                "start_y": types.Schema(type=types.Type.NUMBER, description="Starting Y coordinate for DRAG_AND_DROP"),
                                "end_x": types.Schema(type=types.Type.NUMBER, description="Ending X coordinate for DRAG_AND_DROP"),
                                "end_y": types.Schema(type=types.Type.NUMBER, description="Ending Y coordinate for DRAG_AND_DROP"),
                            "text": types.Schema(type=types.Type.STRING),
                            "submit": types.Schema(type=types.Type.BOOLEAN, description="Set to true to press Enter after typing"),
                            "direction": types.Schema(type=types.Type.STRING),
                            "url": types.Schema(type=types.Type.STRING),
                            "app_name": types.Schema(type=types.Type.STRING, description="The executable name of the app to launch (e.g., 'calc.exe')"),
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

        # Helper function to extract spatial info from an action dict
        def _extract_spatial(action_data, action_dict):
            if "target_id" in action_data:
                action_dict["target_id"] = str(action_data["target_id"])
            elif "id" in action_data:
                action_dict["target_id"] = str(action_data["id"])

            if "coordinates" in action_data:
                action_dict["coordinates"] = action_data["coordinates"]
            if "x" in action_data:
                action_dict["x"] = action_data["x"]
            if "y" in action_data:
                action_dict["y"] = action_data["y"]

            return "target_id" in action_dict or "coordinates" in action_dict or ("x" in action_dict and "y" in action_dict)

        # Try to parse the JSON array from the response
        match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if match:
            try:
                actions_data = json.loads(match.group(0))
                if isinstance(actions_data, list):
                    parsed_actions = []
                    for action_data in actions_data:
                        thought = action_data.get("thought", "")
                        if action_data.get("action") == "CLICK":
                            action_dict = {"action": "CLICK", "thought": thought}
                            if _extract_spatial(action_data, action_dict):
                                parsed_actions.append(action_dict)
                        elif action_data.get("action") == "TYPE" and "text" in action_data:
                            action_dict = {"action": "TYPE", "text": str(action_data["text"]), "thought": thought}
                            if "submit" in action_data:
                                action_dict["submit"] = bool(action_data["submit"])
                            # TYPE is allowed without explicit coordinates if it can use center fallback, but try to extract
                            _extract_spatial(action_data, action_dict)
                            parsed_actions.append(action_dict)
                        elif action_data.get("action") == "SEARCH" and "text" in action_data:
                            # Map SEARCH directly to TYPE with submit=True to leverage existing native submit implementation
                            action_dict = {"action": "TYPE", "text": str(action_data["text"]), "submit": True, "thought": thought}
                            _extract_spatial(action_data, action_dict)
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
                        elif action_data.get("action") == "LAUNCH_APP" and "app_name" in action_data:
                            parsed_actions.append({
                                "action": "LAUNCH_APP",
                                "app_name": str(action_data["app_name"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "PRESS_KEY" and "key" in action_data:
                            parsed_actions.append({
                                "action": "PRESS_KEY",
                                "key": str(action_data["key"]),
                                "thought": thought
                            })
                        elif action_data.get("action") == "WAIT_FOR" and "selector" in action_data:
                            parsed_actions.append({
                                "action": "WAIT_FOR",
                                "selector": str(action_data["selector"]),
                                "max_wait_seconds": float(action_data.get("max_wait_seconds", 5)),
                                "thought": thought
                            })
                        elif action_data.get("action") == "WAIT" and "seconds" in action_data:
                            parsed_actions.append({
                                "action": "WAIT",
                                "seconds": float(action_data.get("seconds", 2)),
                                "thought": thought
                            })
                        elif action_data.get("action") == "DRAG_AND_DROP" and all(k in action_data for k in ["start_x", "start_y", "end_x", "end_y"]):
                            parsed_actions.append({
                                "action": "DRAG_AND_DROP",
                                "start_x": float(action_data["start_x"]),
                                "start_y": float(action_data["start_y"]),
                                "end_x": float(action_data["end_x"]),
                                "end_y": float(action_data["end_y"]),
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
                        return {"actions": parsed_actions, "memory_rules": playbook_rules_applied}
            except json.JSONDecodeError:
                pass

        # Fallback to single object if model ignored array instruction
        match_single = re.search(r'\{[^{}]*\}', response_text)
        if match_single:
            try:
                action_data = json.loads(match_single.group(0))
                thought = action_data.get("thought", "")
                if action_data.get("action") == "CLICK":
                    action_dict = {"action": "CLICK", "thought": thought}
                    if _extract_spatial(action_data, action_dict):
                        return {"actions": [action_dict], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "HOVER":
                    action_dict = {"action": "HOVER", "thought": thought}
                    if _extract_spatial(action_data, action_dict):
                        return {"actions": [action_dict], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "TYPE" and "text" in action_data:
                    action_dict = {"action": "TYPE", "text": str(action_data["text"]), "thought": thought}
                    if "submit" in action_data:
                        action_dict["submit"] = bool(action_data["submit"])
                    _extract_spatial(action_data, action_dict)
                    return {"actions": [action_dict], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "SEARCH" and "text" in action_data:
                    action_dict = {"action": "TYPE", "text": str(action_data["text"]), "submit": True, "thought": thought}
                    _extract_spatial(action_data, action_dict)
                    return {"actions": [action_dict], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "SCROLL" and "direction" in action_data:
                    return {"actions": [{
                        "action": "SCROLL",
                        "direction": str(action_data["direction"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "NAVIGATE" and "url" in action_data:
                    return {"actions": [{
                        "action": "NAVIGATE",
                        "url": str(action_data["url"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "OPEN_TAB" and "url" in action_data:
                    return {"actions": [{
                        "action": "OPEN_TAB",
                        "url": str(action_data["url"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "LAUNCH_APP" and "app_name" in action_data:
                    return {"actions": [{
                        "action": "LAUNCH_APP",
                        "app_name": str(action_data["app_name"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "PRESS_KEY" and "key" in action_data:
                    return {"actions": [{
                        "action": "PRESS_KEY",
                        "key": str(action_data["key"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "WAIT_FOR" and "selector" in action_data:
                    return {"actions": [{
                        "action": "WAIT_FOR",
                        "selector": str(action_data["selector"]),
                        "max_wait_seconds": float(action_data.get("max_wait_seconds", 5)),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "WAIT" and "seconds" in action_data:
                    return {"actions": [{
                        "action": "WAIT",
                        "seconds": float(action_data.get("seconds", 2)),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "DRAG_AND_DROP" and all(k in action_data for k in ["start_x", "start_y", "end_x", "end_y"]):
                    return {"actions": [{
                        "action": "DRAG_AND_DROP",
                        "start_x": float(action_data["start_x"]),
                        "start_y": float(action_data["start_y"]),
                        "end_x": float(action_data["end_x"]),
                        "end_y": float(action_data["end_y"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "REPLY" and "text" in action_data:
                    return {"actions": [{
                        "action": "REPLY",
                        "text": str(action_data["text"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "ASK_HUMAN" and "reason" in action_data:
                    return {"actions": [{
                        "action": "ASK_HUMAN",
                        "reason": str(action_data["reason"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "RESET_VIEW":
                    return {"actions": [{
                        "action": "RESET_VIEW",
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "EXECUTE_JS" and "code" in action_data:
                    return {"actions": [{
                        "action": "EXECUTE_JS",
                        "code": str(action_data["code"]),
                        "thought": thought
                    }], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "SUB_TASK_COMPLETE":
                    return {"actions": [{"action": "SUB_TASK_COMPLETE", "thought": thought}], "memory_rules": playbook_rules_applied}
                elif action_data.get("action") == "DONE":
                    return {"actions": [{"action": "DONE", "thought": thought}], "memory_rules": playbook_rules_applied}
            except json.JSONDecodeError:
                pass

        return {"actions": [{"action": "PARSE_ERROR", "error": "Model response could not be parsed as valid JSON actions.", "raw_response": str(response_text)}], "memory_rules": playbook_rules_applied}

    except Exception as e:
        print(f"Error calling Gemini: {e}")
        import traceback
        traceback.print_exc()
        return {"actions": [{"action": "API_ERROR", "error": f"Exception occurred during model generation: {str(e)}"}], "memory_rules": playbook_rules_applied if 'playbook_rules_applied' in locals() else []}
