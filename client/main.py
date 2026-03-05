import threading
from tray_manager import run_tray_icon
from hotkey_manager import start_hotkey_listener

def main() -> None:
    """
    Main entry point for the local client application.
    Starts the hotkey listener in a daemon thread and then
    runs the system tray icon on the main thread.
    """
    try:
        print("Starting B2B AI Agent MVP Client...")

        # Start the hotkey listener in a daemon thread so it doesn't
        # block the main thread and will automatically exit when the
        # main program exits.
        hotkey_thread = threading.Thread(
            target=start_hotkey_listener,
            daemon=True
        )
        hotkey_thread.start()

        # Run the system tray icon on the main thread. This call blocks
        # until the user clicks 'Quit' in the system tray menu.
        run_tray_icon()

    except Exception as e:
        print(f"Error starting main client application: {e}")

if __name__ == "__main__":
    main()
