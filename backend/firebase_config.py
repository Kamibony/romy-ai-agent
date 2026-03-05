import os
import firebase_admin
from firebase_admin import credentials
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def initialize_firebase() -> firebase_admin.App | None:
    """
    Initializes the Firebase Admin application securely using credentials
    specified in the environment variables.
    """
    try:
        # Check if the app is already initialized
        if not firebase_admin._apps:
            # We rely on GOOGLE_APPLICATION_CREDENTIALS being set in the environment
            # or .env file, which firebase_admin automatically picks up if we use
            # credentials.ApplicationDefault(), or we can pass the path directly if we prefer.
            # Using credentials.ApplicationDefault() is standard for GCP/Firebase.
            # However, since the requirement specifies using the path:
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                app = firebase_admin.initialize_app(cred)
                print("Firebase Admin initialized successfully with certificate.")
                return app
            else:
                # Fallback to application default credentials if path is not found/provided
                cred = credentials.ApplicationDefault()
                app = firebase_admin.initialize_app(cred)
                print("Firebase Admin initialized successfully with application default credentials.")
                return app
        else:
            return firebase_admin.get_app()
    except Exception as e:
        print(f"Error initializing Firebase Admin: {e}")
        # Depending on strictness, we might want to raise here
        return None

# Initialize on import
firebase_app = initialize_firebase()
