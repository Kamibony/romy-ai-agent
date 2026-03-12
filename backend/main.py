from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from auth import verify_firebase_token
from db import check_user_license, get_task_session, update_task_session, create_task_session
from ai_service import process_with_gemini
from firebase_admin import firestore

app = FastAPI(title="ROMY AI Agent Backend")

from typing import Optional, List, Dict, Any

class AgentCommandRequest(BaseModel):
    ui_elements: List[Dict[str, Any]]
    audio_base64: Optional[str] = None
    command_text: Optional[str] = None
    session_id: Optional[str] = None

# Allow all origins, methods, and headers for CORS (adjust as needed in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    """Health-check endpoint."""
    return {"status": "ROMY API is running"}

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
            thread_history=thread_history
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
            for action in action_list:
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
