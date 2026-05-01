import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from the backend .env file
try:
    backend_dir = Path(__file__).resolve().parent
    dotenv_path = backend_dir / ".env"
    load_dotenv(dotenv_path=dotenv_path)
except Exception as e:
    logging.info(f"Failed to load .env file: {e}")

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from auth import verify_firebase_token
from db import check_user_license, get_task_session, update_task_session, create_task_session
from ai_service import process_with_gemini, transcribe_audio_with_gemini, classify_intent_with_gemini, pre_flight_check_with_gemini, supervisor_plan_with_gemini, critic_verify_with_gemini, synthesize_playbook_rule_with_gemini, compile_sop_with_gemini, rescue_element_with_gemini
from repositories import get_memory_repository, AbstractMemoryRepository
from mission_orchestrator import execute_mission_orchestrator
from firebase_admin import firestore
import traceback
from fastapi.responses import JSONResponse
from fastapi import Request
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all external services explicitly
    from firebase_config import initialize_firebase
    await run_in_threadpool(initialize_firebase)

    from ai_service import get_gemini_client
    await run_in_threadpool(get_gemini_client)

    yield

app = FastAPI(title="ROMY AI Agent Backend", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.info(f"Global Exception Handler Caught: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error. Please check the server logs."},
    )

from typing import Optional, List, Dict, Any

class AgentCommandRequest(BaseModel):
    ui_elements: List[Dict[str, Any]]
    raw_ui_elements: Optional[List[Dict[str, Any]]] = None
    audio_base64: Optional[str] = None
    command_text: Optional[str] = None
    session_id: Optional[str] = None
    current_sub_task: Optional[str] = None
    screenshot_base64: Optional[str] = None
    current_url: Optional[str] = None
    client_context: Optional[Dict[str, Any]] = None
    clipboard_status: Optional[str] = "unknown"
    differential_passing_active: Optional[bool] = False

class ClassifyIntentRequest(BaseModel):
    command_text: Optional[str] = None
    audio_base64: Optional[str] = None

class PreFlightRequest(BaseModel):
    command_text: str

class SupervisorPlanRequest(BaseModel):
    command_text: str
    completed_tasks: Optional[List[str]] = None
    task_index: Optional[int] = None
    roadblock_reason: Optional[str] = None

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

class SOPSaveRequest(BaseModel):
    domain: str
    raw_sop: str
    client_id: Optional[str] = None
    target_sub_task: Optional[str] = None

class SOPStudioSaveRequest(BaseModel):
    domain: str
    goal: str
    recorded_steps: List[Dict[str, Any]]
    client_id: Optional[str] = None

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

# Dynamically construct CORS regex for authorized Chrome Extensions
allowed_extension_ids = os.getenv("ALLOWED_EXTENSION_IDS", "").split(",")
allowed_extension_ids = [eid.strip() for eid in allowed_extension_ids if eid.strip()]

if allowed_extension_ids:
    # Construct regex like "chrome-extension://(id1|id2|id3)"
    # re.escape ensures special characters in IDs don't break the regex
    extension_ids_pattern = "|".join([re.escape(eid) for eid in allowed_extension_ids])
    allow_origin_regex = f"chrome-extension://({extension_ids_pattern})"
else:
    # Fallback to none if no IDs provided to maintain security by default
    allow_origin_regex = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=allow_origin_regex,
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

    sub_tasks = supervisor_plan_with_gemini(request.command_text, request.completed_tasks, request.task_index, request.roadblock_reason)
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
        logging.info(f"Graceful fallback in evaluate_plan_progress due to error: {e}")
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

@app.post("/api/v1/memory/inject_sop")
def inject_sop(request: SOPSaveRequest, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint for B2B clients to manually inject a text-based SOP.
    The SOP Compiler translates it into an agent-friendly rule and saves it.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    rule = compile_sop_with_gemini(request.domain, request.raw_sop, client_id=request.client_id, target_sub_task=request.target_sub_task)
    if rule:
        return {"status": "ok", "rule": rule}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compile SOP.",
        )

@app.post("/api/v1/memory/sops")
async def save_sop(request: SOPStudioSaveRequest, uid: str = Depends(verify_firebase_token), memory_repo: AbstractMemoryRepository = Depends(get_memory_repository)):
    """
    Endpoint for SOP Studio to save a recorded process.
    The raw DOM steps are vectorized and saved via dual-write.
    """
    try:
        is_active = await run_in_threadpool(check_user_license, uid)
        if not is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User license is not active.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.info(f"Error checking user license in save_sop: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify user license.",
        )

    try:
        # Convert recorded steps to a format that can be vectorized
        raw_sop = f"Goal: {request.goal}\nSteps:\n" + str(request.recorded_steps)

        # Synthesize the rule
        rule = await run_in_threadpool(
            compile_sop_with_gemini,
            request.domain, raw_sop, client_id=request.client_id, target_sub_task=request.goal, memory_repo=memory_repo
        )

        if rule:
            await run_in_threadpool(
                memory_repo.save_playbook_rule,
                request.domain, rule, client_id=request.client_id, goal=request.goal, source="sop_studio"
            )
            return {"status": "ok", "rule": rule}
        else:
            # If Gemini fails, we shouldn't crash the UI but we should indicate failure.
            # We will use 500 but it's handled gracefully.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to compile and save SOP.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.info(f"Error saving SOP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while saving SOP: {str(e)}"
        )

@app.get("/api/v1/memory/sops")
async def get_sops(client_id: Optional[str] = None, uid: str = Depends(verify_firebase_token), memory_repo: AbstractMemoryRepository = Depends(get_memory_repository)):
    """
    Endpoint for Memory Manager to fetch all recorded SOPs.
    Retrieves rules directly from Firestore.
    """
    try:
        is_active = await run_in_threadpool(check_user_license, uid)
        if not is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User license is not active.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.info(f"Error checking user license in get_sops: {e}")
        # Graceful degradation if auth/DB fails entirely: Fail closed.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify user license.",
        )

    try:
        rules = await run_in_threadpool(memory_repo.list_playbook_rules, client_id=client_id)
        return {"status": "ok", "sops": rules}
    except Exception as e:
        logging.info(f"Error fetching SOPs: {e}")
        # Graceful degradation: Return empty list if DB connection fails
        return {"status": "ok", "sops": []}

@app.delete("/api/v1/memory/sops/{doc_id}")
def delete_sop(doc_id: str, client_id: Optional[str] = None, uid: str = Depends(verify_firebase_token), memory_repo: AbstractMemoryRepository = Depends(get_memory_repository)):
    """
    Endpoint for Memory Manager to delete a saved SOP.
    Deletes the rule from both ChromaDB and Firestore.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    success = memory_repo.delete_playbook_rule(doc_id, client_id=client_id)
    if success:
        return {"status": "ok"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete SOP.",
        )

@app.get("/api/v1/memory/rules")
async def get_dashboard_rules(client_id: Optional[str] = None, uid: str = Depends(verify_firebase_token), memory_repo: AbstractMemoryRepository = Depends(get_memory_repository)):
    """
    Endpoint for Dashboard to fetch all memory rules from Firestore (fast, no vector search).
    """
    try:
        if not check_user_license(uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User license is not active.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.info(f"Error checking user license in get_dashboard_rules: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify user license.",
        )

    try:
        rules = await run_in_threadpool(memory_repo.list_playbook_rules, client_id=client_id)
        return {"status": "ok", "rules": rules}
    except Exception as e:
        logging.info(f"Error fetching dashboard rules: {e}")
        return {"status": "ok", "rules": []}

@app.delete("/api/v1/memory/rules/{rule_id}")
def delete_dashboard_rule(rule_id: str, client_id: Optional[str] = None, uid: str = Depends(verify_firebase_token)):
    """
    Endpoint for Dashboard to delete a memory rule from both ChromaDB and Firestore.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    success = delete_playbook_rule(rule_id, client_id=client_id)
    if success:
        return {"status": "ok"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete playbook rule.",
        )

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

def _background_update_session_and_telemetry(session_id: str, updates: dict, action_list: dict, uid: str):
    """Background task to update Firestore and telemetry to avoid blocking HTTP response."""
    if session_id:
        update_task_session(session_id, updates)

    try:
        db = firestore.client()
        db.collection("telemetry").add({
            "timestamp": firestore.SERVER_TIMESTAMP,
            "gemini_context": str(action_list), # Storing the action list in place of context
            "claude_action": str(action_list), # Kept for backward compatibility if needed by frontend
            "uid": uid
        })
        logging.info("Telemetry written to Firestore in background")
    except Exception as e:
        logging.info(f"Error writing telemetry in background: {e}")

@app.post("/api/v1/agent/command")
def agent_command(request: AgentCommandRequest, background_tasks: BackgroundTasks, uid: str = Depends(verify_firebase_token)):
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
    logging.info(f"Received {elements_count} UI elements")
    logging.info(f"Received audio length: {audio_len}")
    logging.info(f"Received command text: {request.command_text}")

    try:
        thread_history = ""
        session = None
        if request.session_id:
            session = get_task_session(request.session_id)
            if not session:
                create_task_session(request.session_id, request.command_text or "")
                session = get_task_session(request.session_id)
            if session:
                thread_history = session.get("thread_history", "")

                # Check status
                session_status = session.get("status", "pending")
                if session_status == "help_needed":
                    # We should not be processing if it's waiting for help
                    # but if we get a request, maybe the client is re-syncing
                    pass

        differential_passing_active = getattr(request, 'differential_passing_active', False)

        action_list = process_with_gemini(
            ui_elements=request.ui_elements,
            audio_b64=request.audio_base64,
            command_text=request.command_text,
            thread_history=thread_history,
            screenshot_base64=request.screenshot_base64,
            current_sub_task=request.current_sub_task,
            current_url=request.current_url,
            client_context=request.client_context,
            clipboard_status=request.clipboard_status,
            differential_passing_active=differential_passing_active
        )
        logging.info(f"Gemini action list: {action_list}")

        updates = {}
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

        # STEP 3: The Stagnation Fix. Offload Firestore writes to BackgroundTasks.
        background_tasks.add_task(
            _background_update_session_and_telemetry,
            request.session_id,
            updates,
            action_list,
            uid
        )

        # Directly return the list of actions to match extension expectations
        return action_list
    except Exception as e:
        logging.info(f"Error in AI pipeline: {e}")
        return [{"action": "PIPELINE_ERROR", "error": str(e)}]

class MissionBlock(BaseModel):
    block_id: str
    type: str
    sop_reference_id: Optional[str] = None
    instruction: Optional[str] = None
    inputs: Dict[str, str] = Field(default_factory=dict)
    outputs: List[str] = Field(default_factory=list)

class MissionGraph(BaseModel):
    mission_id: str
    name: str
    blocks: List[MissionBlock]
    execution_order: List[str]

@app.post("/api/v1/mission/execute")
async def execute_mission(mission: MissionGraph, uid: str = Depends(verify_firebase_token)):
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )
    logging.info(f"Executing mission {mission.mission_id}: {mission.name}")
    import asyncio
    asyncio.create_task(execute_mission_orchestrator(mission, "dummy_doc_id"))
    return {"status": "ok", "message": "Mission started"}


class RescueRequest(BaseModel):
    intent: str
    failed_selector: str
    current_dom_snippet: str

@app.post("/api/v1/agent/rescue")
async def api_rescue_element(request: RescueRequest, uid: str = Depends(verify_firebase_token)):
    await run_in_threadpool(check_user_license, uid)
    result = await run_in_threadpool(
        rescue_element_with_gemini,
        request.intent,
        request.failed_selector,
        request.current_dom_snippet
    )
    if result.get("status") == "FAILED":
        raise HTTPException(status_code=404, detail=result.get("reason", "Element could not be rescued"))
    return result
