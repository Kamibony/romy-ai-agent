import logging
import os
import firebase_admin

class MockCredential(firebase_admin.credentials.Base):
    def get_credential(self):
        from google.auth.credentials import AnonymousCredentials
        return AnonymousCredentials()

def initialize_firebase() -> firebase_admin.App | None:
    is_local = os.environ.get("LOCAL_DEV") == "True" or os.environ.get("ROMY_TEST_MODE") == "1"
    try:
        if not firebase_admin._apps:
            try:
                if is_local and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is None:
                    # In local mode without explicit credentials, default to mock to prevent ADC from throwing
                    app = firebase_admin.initialize_app(MockCredential(), options={'projectId': 'demo-project'})
                    logging.info("Firebase Admin initialized successfully using mock credentials.")
                    return app

                # Try to initialize with default credentials
                app = firebase_admin.initialize_app()

                # To really test if ADC works and avoid failing later when firestore.client() is called
                # We attempt to get the credential to see if it throws DefaultCredentialsError
                app.credential.get_credential()

                logging.info("Firebase Admin initialized successfully using ADC.")
                return app
            except Exception as e:
                # Clean up the failed default app initialization if any
                if "[DEFAULT]" in firebase_admin._apps:
                    del firebase_admin._apps["[DEFAULT]"]

                if is_local:
                    logging.info(f"ADC initialization failed, falling back to mock credentials for local dev. Reason: {e}")
                    app = firebase_admin.initialize_app(MockCredential(), options={'projectId': 'demo-project'})
                    logging.info("Firebase Admin initialized successfully using mock credentials (fallback).")
                    return app
                else:
                    raise e
        else:
            return firebase_admin.get_app()
    except Exception as e:
        logging.info(f"Error initializing Firebase Admin: {e}")
        # Depending on strictness, we might want to raise here
        return None

firebase_app = initialize_firebase()
