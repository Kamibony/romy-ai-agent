import os
import sys
import argparse
from dotenv import load_dotenv

# Load environment variables as early as possible so that module-level constants
# in other files (like config.py) can access them.
load_dotenv()

import logging

# Inject app directory into sys.path to fix ModuleNotFoundError in embedded environment
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

import threading

# Import logger_setup explicitly at the top to configure logging for the entire app before any other imports grab the root logger
import logger_setup

def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="ROMY AI Agent Client")
    return parser.parse_args()

def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def authenticate() -> str:
    """
    Handles silent and manual authentication.
    Returns the Firebase token.
    """
    from local_bridge import bridge
    from auth_window import login_window

    # Start local bridge for Chrome Extension early to try silent token refresh
    bridge.start()

    # Try to get a fresh token silently
    token = bridge.request_fresh_token(timeout=5)

    if token:
        logging.info("Silent auth successful via Chrome Extension token.")
    else:
        logging.info("Silent auth failed or timed out. Showing login window.")
        # Show login window and get token
        token = login_window()

    return token

def start_background_services() -> None:
    """Starts all daemon background threads and local API."""
    from tray_manager import run_tray_icon
    from hotkey_manager import start_hotkey_listener
    from agent import start_remote_listener, start_local_api

    logging.info("Starting background tasks...")

    # Start the hotkey listener in a daemon thread
    hotkey_thread = threading.Thread(
        target=start_hotkey_listener,
        daemon=True
    )
    hotkey_thread.start()

    # Start the remote command listener in a daemon thread.
    remote_thread = threading.Thread(
        target=start_remote_listener,
        daemon=True
    )
    remote_thread.start()

    # Run the system tray icon in a daemon thread
    tray_thread = threading.Thread(
        target=run_tray_icon,
        daemon=True
    )
    tray_thread.start()

    # Start local API for E2E testing
    start_local_api()

def main() -> None:
    """
    Main entry point for the local client application.
    Shows the login window, then starts background services
    and runs the agent worker loop on the main thread.
    """
    from agent import set_firebase_token, set_agent_online, set_agent_offline, agent_worker_loop

    try:
        logging.info("Starting B2B AI Agent MVP Client...")

        # Parse command line arguments
        args = parse_arguments()

        # Authenticate
        token = authenticate()
        if not token:
            logging.info("Login failed or window closed. Exiting...")
            sys.exit(0)

        # Set the token for the agent
        set_firebase_token(token)

        # Set agent to online
        set_agent_online()

        logging.info("Login successful.")

        # Start background services
        start_background_services()

        try:
            # Run the agent worker loop on the main thread
            agent_worker_loop()
        finally:
            set_agent_offline()

    except Exception as e:
        logging.error(f"Error starting main client application: {e}")

if __name__ == "__main__":
    main()
