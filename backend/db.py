import firebase_admin
from firebase_admin import firestore

from typing import Dict, Any, Optional

def get_task_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a task_session from Firestore.
    """
    try:
        db = firestore.client()
        doc_ref = db.collection("task_sessions").document(session_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error getting task session {session_id}: {e}")
        return None

def update_task_session(session_id: str, updates: Dict[str, Any]) -> None:
    """
    Updates a task_session in Firestore.
    """
    try:
        db = firestore.client()
        doc_ref = db.collection("task_sessions").document(session_id)
        doc_ref.set(updates, merge=True)
    except Exception as e:
        print(f"Error updating task session {session_id}: {e}")

def create_task_session(session_id: str, initial_command: str = "") -> None:
    """
    Creates a new task_session if it doesn't exist.
    """
    try:
        db = firestore.client()
        doc_ref = db.collection("task_sessions").document(session_id)
        if not doc_ref.get().exists:
            doc_ref.set({
                "status": "pending",
                "current_step": 0,
                "thread_history": initial_command,
                "created_at": firestore.SERVER_TIMESTAMP
            })
    except Exception as e:
        print(f"Error creating task session {session_id}: {e}")

def check_user_license(uid: str) -> bool:
    """
    Connects to Firestore, checks the `users` collection for the given `uid`,
    and returns True if `is_active` is boolean True or if the user has a 'partner' or 'admin' role.
    """
    try:
        db = firestore.client()
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            role = user_data.get("role")
            if isinstance(role, str):
                role = role.lower()
            if role in ["admin", "partner"]:
                return True
            return user_data.get("is_active") is True
        return False
    except Exception as e:
        print(f"Error checking user license for {uid}: {e}")
        return False
