from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from auth import verify_firebase_token
from db import check_user_license, get_task_session, update_task_session, create_task_session
from ai_service import process_with_gemini, transcribe_audio_with_gemini, classify_intent_with_gemini, pre_flight_check_with_gemini, supervisor_plan_with_gemini, critic_verify_with_gemini, synthesize_playbook_rule_with_gemini
from memory import get_playbook_rules
from firebase_admin import firestore

app = FastAPI(title="ROMY AI Agent Backend")

from typing import Optional, List, Dict, Any

class AgentCommandRequest(BaseModel):
    ui_elements: List[Dict[str, Any]]
    audio_base64: Optional[str] = None
    command_text: Optional[str] = None
    session_id: Optional[str] = None
    current_sub_task: Optional[str] = None
    screenshot_base64: Optional[str] = None
    current_url: Optional[str] = None
    client_context: Optional[Dict[str, Any]] = None
    clipboard_status: Optional[str] = "unknown"

class ClassifyIntentRequest(BaseModel):
    command_text: Optional[str] = None
    audio_base64: Optional[str] = None

class PreFlightRequest(BaseModel):
    command_text: str

class SupervisorPlanRequest(BaseModel):
    command_text: str

class EvaluatePlanProgressRequest(BaseModel):
    command_text: str
    current_sub_task: str
    remaining_plan: List[str]
    screenshot_base64: Optional[str] = None
    ui_elements: List[Dict[str, Any]]

class CriticVerifyRequest(BaseModel):
    sub_task: str
    action_taken: Dict[str, Any]
    before_state: Dict[str, Any]
    after_state: Dict[str, Any]

class SynthesizePlaybookRequest(BaseModel):
    domain: str
    execution_telemetry: str
    client_id: Optional[str] = None
    failed_sub_task: Optional[str] = None

# Restricted CORS policy for production security
origins = [
    "https://romy-ai-agent.web.app",
    "https://romy-ai-agent.firebaseapp.com",
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8764",
    "http://127.0.0.1:8764",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex="chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    """Health-check endpoint."""
    return {"status": "ROMY API is running"}

@app.post("/api/pre_flight")
def pre_flight_check(request: PreFlightRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to check if a task has missing necessary information before execution.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    result = pre_flight_check_with_gemini(request.command_text)
    return result

@app.post("/api/critic_verify")
def critic_verify(request: CriticVerifyRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to verify if a sub-task was successful.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    result = critic_verify_with_gemini(
        request.sub_task,
        request.before_state,
        request.action_taken,
        request.after_state
    )
    return result

@app.post("/api/supervisor_plan")
def supervisor_plan(request: SupervisorPlanRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to generate sequential sub-tasks for a given command.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    sub_tasks = supervisor_plan_with_gemini(request.command_text)
    return {"sub_tasks": sub_tasks}

@app.post("/api/evaluate_plan_progress")
def evaluate_plan_progress(request: EvaluatePlanProgressRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to evaluate if a sub-task is already accomplished based on the current DOM/vision state.
    Gracefully catches any internal errors and returns 200 with is_accomplished=False to prevent client-side infinite retry loops.
    """
    try:
        if not check_user_license(uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User license is not active.",
            )

        result = evaluate_plan_progress_with_gemini(
            request.command_text,
            request.current_sub_task,
            request.remaining_plan,
            request.screenshot_base64,
            request.ui_elements
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"Graceful fallback in evaluate_plan_progress due to error: {e}")
        return {"is_accomplished": False, "reason": f"Backend fallback due to error: {str(e)}"}

@app.get("/api/playbook_rules")
def fetch_playbook_rules(domain: str, client_id: Optional[str] = None, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to retrieve playbook rules for a specific domain and client_id from ChromaDB.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )
    rules = get_playbook_rules(domain=domain, client_id=client_id)
    return {"status": "ok", "rules": rules}

@app.post("/api/synthesize_playbook")
def synthesize_playbook(request: SynthesizePlaybookRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to manually trigger the synthesis of a playbook rule for a domain based on execution telemetry.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    rule = synthesize_playbook_rule_with_gemini(request.domain, request.execution_telemetry, client_id=request.client_id, failed_sub_task=request.failed_sub_task)
    return {"status": "ok", "rule": rule}

@app.post("/api/classify_intent")

def classify_intent(request: ClassifyIntentRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint to dynamically classify user intent (WEB or OS).
    Also transcribes audio if command_text is empty.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    command_text = request.command_text or ""

    if not command_text and request.audio_base64:
        # Transcribe audio to get the command text
        command_text = transcribe_audio_with_gemini(request.audio_base64)

    if not command_text:
        # If still empty, default to OS or could be an error
        return {"intent": "OS", "command_text": ""}

    intent = classify_intent_with_gemini(command_text)

    return {
        "intent": intent,
        "command_text": command_text
    }

@app.post("/api/v1/agent/command")
def agent_command(request: AgentCommandRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint that requires a valid Firebase token.
    Checks user license from Firestore before accepting the command.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    elements_count = len(request.ui_elements)
    audio_len = len(request.audio_base64) if request.audio_base64 else 0
    print(f"Received {elements_count} UI elements")
    print(f"Received audio length: {audio_len}")
    print(f"Received command text: {request.command_text}")

    try:
        thread_history = ""
        if request.session_id:
            session = get_task_session(request.session_id)
            if not session:
                create_task_session(request.session_id, request.command_text or "")
                session = get_task_session(request.session_id)
            if session:
                thread_history = session.get("thread_history", "")

                # Check status
                status = session.get("status", "pending")
                if status == "help_needed":
                    # We should not be processing if it's waiting for help
                    # but if we get a request, maybe the client is re-syncing
                    pass

        action_list = process_with_gemini(
            ui_elements=request.ui_elements,
            audio_b64=request.audio_base64,
            command_text=request.command_text,
            thread_history=thread_history,
            screenshot_base64=request.screenshot_base64,
            current_sub_task=request.current_sub_task,
            current_url=request.current_url,
            client_context=request.client_context,
            clipboard_status=request.clipboard_status
        )
        print(f"Gemini action list: {action_list}")

        if request.session_id and session:
            current_step = session.get("current_step", 0) + 1
            new_history = thread_history + f"\nStep {current_step} AI Action: {action_list}"
            updates = {
                "current_step": current_step,
                "thread_history": new_history,
                "status": "in_progress"
            }

            # Check for specific terminal actions in the sequence
            actions_to_check = action_list.get("actions", []) if isinstance(action_list, dict) else action_list
            for action in actions_to_check:
                if action.get("action") == "ASK_HUMAN":
                    updates["status"] = "help_needed"
                    break
                elif action.get("action") == "DONE":
                    updates["status"] = "completed"
                elif action.get("action") == "ERROR" or action.get("action") == "API_ERROR" or action.get("action") == "PARSE_ERROR" or action.get("action") == "PIPELINE_ERROR":
                    updates["status"] = "failed"
                    break

            update_task_session(request.session_id, updates)

        try:
            db = firestore.client()
            db.collection("telemetry").add({
                "timestamp": firestore.SERVER_TIMESTAMP,
                "gemini_context": str(action_list), # Storing the action list in place of context
                "claude_action": str(action_list), # Kept for backward compatibility if needed by frontend
                "uid": uid
            })
            print("Telemetry written to Firestore")
        except Exception as e:
            print(f"Error writing telemetry: {e}")

        # Directly return the list of actions to match extension expectations
        return action_list
    except Exception as e:
        print(f"Error in AI pipeline: {e}")
        return [{"action": "PIPELINE_ERROR", "error": str(e)}]
