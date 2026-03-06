import firebase_admin

def initialize_firebase() -> firebase_admin.App | None:
    try:
        if not firebase_admin._apps:
            app = firebase_admin.initialize_app()
            print("Firebase Admin initialized successfully using ADC.")
            return app
        else:
            return firebase_admin.get_app()
    except Exception as e:
        print(f"Error initializing Firebase Admin: {e}")
        # Depending on strictness, we might want to raise here
        return None

firebase_app = initialize_firebase()
