from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from auth import verify_firebase_token
from db import check_user_license
from ai_service import process_with_gemini, get_action_from_claude
from firebase_admin import firestore

app = FastAPI(title="ROMY AI Agent Backend")

class AgentCommandRequest(BaseModel):
    image_base64: str
    audio_base64: Optional[str] = None

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

    image_len = len(request.image_base64)
    audio_len = len(request.audio_base64) if request.audio_base64 else 0
    print(f"Received image length: {image_len}")
    print(f"Received audio length: {audio_len}")

    try:
        context_text = process_with_gemini(
            image_b64=request.image_base64,
            audio_b64=request.audio_base64
        )
        print(f"Gemini context: {context_text}")

        action_dict = get_action_from_claude(
            image_b64=request.image_base64,
            context_text=context_text
        )
        print(f"Claude action: {action_dict}")

        try:
            db = firestore.client()
            db.collection("telemetry").add({
                "timestamp": firestore.SERVER_TIMESTAMP,
                "gemini_context": context_text,
                "claude_action": str(action_dict),
                "uid": uid
            })
            print("Telemetry written to Firestore")
        except Exception as e:
            print(f"Error writing telemetry: {e}")

        # Ensure 'status' is returned alongside 'action'
        result = {"status": "success"}
        result.update(action_dict)
        return result
    except Exception as e:
        print(f"Error in AI pipeline: {e}")
        return {"status": "error", "action": "PIPELINE_ERROR", "error": str(e)}
