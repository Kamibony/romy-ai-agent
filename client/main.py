import logging
import os
import sys

# Inject app directory into sys.path to fix ModuleNotFoundError in embedded environment
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

import threading

# Import logger_setup explicitly at the top to configure logging for the entire app before any other imports grab the root logger
import logger_setup

def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def main() -> None:
    """
    Main entry point for the local client application.
    Shows the login window, then starts the hotkey listener
    in a daemon thread and runs the system tray icon on the main thread.
    """
    from tray_manager import run_tray_icon
    from hotkey_manager import start_hotkey_listener
    from auth_window import login_window
    from agent import set_firebase_token, start_remote_listener, agent_worker_loop

    try:
        logging.info("Starting B2B AI Agent MVP Client...")

        # Show login window and get token
        token = login_window()
        if not token:
            logging.info("Login failed or window closed. Exiting...")
            sys.exit(0)

        # Set the token for the agent
        set_firebase_token(token)

        # Import to handle graceful shutdown
        from agent import set_agent_online, set_agent_offline

        # Set agent to online
        set_agent_online()

        logging.info("Login successful. Starting background tasks...")

        # Start the hotkey listener in a daemon thread so it doesn't
        # block the main thread and will automatically exit when the
        # main program exits.
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

        # Run the system tray icon in a daemon thread so the main thread
        # is free to run the agent worker loop.
        tray_thread = threading.Thread(
            target=run_tray_icon,
            daemon=True
        )
        tray_thread.start()

        # Start local bridge for Chrome Extension
        from local_bridge import bridge
        bridge.start()

        try:
            # Run the agent worker loop on the main thread
            agent_worker_loop()
        finally:
            set_agent_offline()

    except Exception as e:
        logging.error(f"Error starting main client application: {e}")

if __name__ == "__main__":
    main()
