from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any

from .auth import verify_firebase_token
from .db import check_user_license

# Initialize FastAPI application
app = FastAPI(
    title="ROMY Backend API",
    description="Secure brain, license manager, and AI router for the ROMY B2B AI Agent MVP.",
    version="0.1.0",
)

# CORS configuration
# Using a permissive origin initially, but should be restricted in production
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8080",
    # Add other origins as needed
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CommandResponse(BaseModel):
    status: str
    message: str
    uid: str

@app.post("/api/v1/agent/command", response_model=CommandResponse, status_code=status.HTTP_200_OK)
async def agent_command(uid: str = Depends(verify_firebase_token)) -> CommandResponse:
    """
    Dummy endpoint that simulates an agent command.
    Verifies the user's license in Firestore based on the Firebase token uid.
    """
    try:
        is_active = check_user_license(uid)

        if not is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User license is not active.",
            )

        # Return success if license is valid
        return CommandResponse(
            status="success",
            message="Backend connected, license valid.",
            uid=uid
        )

    except HTTPException:
        # Re-raise known HTTP exceptions (like the one we just raised or from dependencies)
        raise
    except Exception as e:
        # Catch any unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )

# Root endpoint for basic health check
@app.get("/", status_code=status.HTTP_200_OK)
async def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "ROMY Backend API is running."}
