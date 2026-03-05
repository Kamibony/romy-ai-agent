import firebase_admin
from firebase_admin import firestore

def check_user_license(uid: str) -> bool:
    """
    Connects to Firestore, checks the `users` collection for the given `uid`,
    and returns True if `is_active` is boolean True.
    """
    try:
        db = firestore.client()
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            return user_data.get("is_active") is True
        return False
    except Exception as e:
        print(f"Error checking user license for {uid}: {e}")
        return False
