from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from auth import verify_firebase_token
from db import check_user_license

app = FastAPI(title="ROMY AI Agent Backend")

# Allow all origins, methods, and headers for CORS (adjust as needed in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/agent/command")
def agent_command(uid: str = Depends(verify_firebase_token)):
    """
    Endpoint that requires a valid Firebase token.
    Checks user license from Firestore before accepting the command.
    """
    if not check_user_license(uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User license is not active.",
        )

    return {"status": "success", "message": "Backend connected, license valid.", "uid": uid}
