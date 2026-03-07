import threading
import sys
from tray_manager import run_tray_icon
from hotkey_manager import start_hotkey_listener
from auth_window import login_window
from agent import set_firebase_token, start_remote_listener

def main() -> None:
    """
    Main entry point for the local client application.
    Shows the login window, then starts the hotkey listener
    in a daemon thread and runs the system tray icon on the main thread.
    """
    try:
        print("Starting B2B AI Agent MVP Client...")

        # Show login window and get token
        token = login_window()
        if not token:
            print("Login failed or window closed. Exiting...")
            sys.exit(0)

        # Set the token for the agent
        set_firebase_token(token)

        print("Login successful. Starting background tasks...")

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

        # Run the system tray icon on the main thread. This call blocks
        # until the user clicks 'Quit' in the system tray menu.
        run_tray_icon()

    except Exception as e:
        print(f"Error starting main client application: {e}")

if __name__ == "__main__":
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass # Not running as a PyInstaller bundle with a splash screen

    main()
