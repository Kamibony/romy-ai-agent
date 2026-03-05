import os
import json
import firebase_admin
from firebase_admin import credentials
from dotenv import load_dotenv

load_dotenv()

def initialize_firebase() -> firebase_admin.App | None:
    try:
        if not firebase_admin._apps:
            firebase_credentials_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
            if not firebase_credentials_json:
                raise ValueError("FIREBASE_CREDENTIALS_JSON environment variable is missing.")

            try:
                cred_dict = json.loads(firebase_credentials_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"FIREBASE_CREDENTIALS_JSON is not valid JSON: {e}")

            cred = credentials.Certificate(cred_dict)
            app = firebase_admin.initialize_app(cred)
            print("Firebase Admin initialized successfully.")
            return app
        else:
            return firebase_admin.get_app()
    except Exception as e:
        print(f"Error initializing Firebase Admin: {e}")
        # Depending on strictness, we might want to raise here
        return None

firebase_app = initialize_firebase()
