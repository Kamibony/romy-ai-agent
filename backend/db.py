from firebase_admin import firestore
from fastapi import HTTPException, status
from .firebase_config import firebase_app

def get_firestore_client() -> firestore.firestore.Client:
    """
    Returns an initialized Firestore client.
    """
    try:
        return firestore.client(app=firebase_app)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize Firestore client: {str(e)}",
        )

def check_user_license(uid: str) -> bool:
    """
    Connects to Firestore to check the `users` collection for a document
    matching the given `uid` and returns whether `is_active` is True.
    """
    try:
        db = get_firestore_client()
        user_ref = db.collection('users').document(uid)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            # Default to False if the field doesn't exist
            is_active = user_data.get('is_active', False)
            if not isinstance(is_active, bool):
                # Ensure it's a boolean explicitly if needed
                is_active = bool(is_active)
            return is_active
        else:
            # Document doesn't exist
            return False

    except Exception as e:
        # Rather than failing silently, raise an internal server error.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking user license: {str(e)}"
        )
