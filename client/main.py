import logging
import os
import threading
import sys
from tray_manager import run_tray_icon
from hotkey_manager import start_hotkey_listener
from auth_window import login_window
from agent import set_firebase_token, start_remote_listener, init_browser_workspace, agent_worker_loop
from extension_server import extension_server

def setup_logging():
    user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RomyAgentBrowserData")
    os.makedirs(user_data_dir, exist_ok=True)
    log_file = os.path.join(user_data_dir, "romy_agent.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

def main() -> None:
    """
    Main entry point for the local client application.
    Shows the login window, then starts the hotkey listener
    in a daemon thread and runs the system tray icon on the main thread.
    """
    setup_logging()
    try:
        logging.info("Starting B2B AI Agent MVP Client...")

        # Show login window and get token
        token = login_window()
        if not token:
            logging.info("Login failed or window closed. Exiting...")
            sys.exit(0)

        # Set the token for the agent
        set_firebase_token(token)

        logging.info("Login successful. Starting background tasks...")

        # Pre-launch the browser workspace on the main thread for Playwright stability
        try:
            init_browser_workspace()
        except Exception as workspace_e:
            logging.error(f"Error pre-launching workspace: {workspace_e}")

        # Start the hotkey listener in a daemon thread so it doesn't
        # block the main thread and will automatically exit when the
        # main program exits.
        hotkey_thread = threading.Thread(
            target=start_hotkey_listener,
            daemon=True
        )
        hotkey_thread.start()

        # Start the extension WebSocket server in a daemon thread.
        extension_thread = threading.Thread(
            target=extension_server.run_server,
            daemon=True
        )
        extension_thread.start()

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

        # Run the agent worker loop on the main thread
        agent_worker_loop()

    except Exception as e:
        logging.error(f"Error starting main client application: {e}")

if __name__ == "__main__":
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass # Not running as a PyInstaller bundle with a splash screen

    main()
