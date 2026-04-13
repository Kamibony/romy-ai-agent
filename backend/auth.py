import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
import firebase_admin
from firebase_config import firebase_app

security = HTTPBearer()

def verify_firebase_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Extracts a Bearer token from the Authorization header, verifies it using
    firebase_admin.auth.verify_id_token(), and returns the decoded uid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Bypass for local development
    if token == "local-dev-token" and (os.environ.get("LOCAL_DEV") == "True" or os.environ.get("ROMY_TEST_MODE") == "1"):
        return "local-dev-uid"

    try:
        decoded_token = auth.verify_id_token(token)
        uid: str = decoded_token.get("uid")

        if not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain a valid UID",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return uid
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
