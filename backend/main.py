from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from auth import verify_firebase_token
from db import check_user_license
from pydantic import BaseModel
from typing import Optional

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

    return {"status": "success", "action": "DONE"}
