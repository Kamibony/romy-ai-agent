from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from auth import verify_firebase_token
from db import check_user_license

class AgentCommandRequest(BaseModel):
    image_base64: str
    audio_base64: str

app = FastAPI(title="ROMY AI Agent Backend")

@app.get("/")
def health_check():
    return {"status": "ROMY API is running", "version": "1.0.0"}

# Allow all origins, methods, and headers for CORS (adjust as needed in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

    print(f"Received image_base64 length: {len(request.image_base64)}")
    print(f"Received audio_base64 length: {len(request.audio_base64)}")

    return {"status": "success", "message": "Backend connected, license valid.", "uid": uid}
