import logging
import os
import threading
import sys
import subprocess

def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def setup_playwright_bootstrapper():
    """
    Sets PLAYWRIGHT_BROWSERS_PATH to a persistent local directory
    and runs 'playwright install chromium' programmatically to self-heal
    and avoid bundling large Chromium binaries.
    """
    try:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        # fallback to current directory if LOCALAPPDATA is not available
        if not local_app_data:
            local_app_data = os.path.abspath(".")

        browsers_path = os.path.join(local_app_data, "RomyAgent", "Browsers")
        os.makedirs(browsers_path, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

        # Check if we need to install
        # Simple heuristic: if the folder is empty or doesn't have chromium, try installing.
        # Playwright install command itself is idempotent and checks for existing binaries.
        logging.info(f"Checking Playwright browsers at: {browsers_path}")

        # We can just invoke python -m playwright install chromium
        # which will be silent if already installed, or download it if not.
        # This uses the current Python executable.
        try:
            if hasattr(sys, '_MEIPASS'):
                # In PyInstaller, we might need to invoke playwright module directly if python executable is not the same
                import playwright._impl._driver
                driver_executable = playwright._impl._driver.compute_driver_executable()
                subprocess.run([str(driver_executable), "install", "chromium"], check=True, capture_output=True, text=True)
            else:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, capture_output=True, text=True)
            logging.info("Playwright browser check/install completed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to install Playwright browsers: {e.stdout}\n{e.stderr}")
        except Exception as e:
            logging.error(f"Unexpected error installing Playwright browsers: {e}")

    except Exception as e:
        logging.error(f"Error in setup_playwright_bootstrapper: {e}")

# -----------------------------------------------------------------------------
# Vendoring Bypass for playwright_stealth
# Inject the vendor directory into sys.path before any imports that might use it
# -----------------------------------------------------------------------------
vendor_dir = resource_path("vendor")
if os.path.isdir(vendor_dir) and vendor_dir not in sys.path:
    # Insert at the front so it takes precedence over any empty namespace packages
    sys.path.insert(0, vendor_dir)


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
    # Import agent modules AFTER bootstrapper has run
    from tray_manager import run_tray_icon
    from hotkey_manager import start_hotkey_listener
    from auth_window import login_window
    from agent import set_firebase_token, start_remote_listener, init_browser_workspace, agent_worker_loop

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
    # We close the splash screen AFTER main() starts and setup is mostly complete,
    # but since main() has blocking operations (login_window), we should close it
    # just before login_window, or inside setup_playwright_bootstrapper if it takes long.
    # Let's handle it here before main, or at the start of main.
    # The bootstrapper logic is inside main(), but we want the splash screen
    # visible during setup_playwright_bootstrapper.

    # Let's change the pattern: call setup, close splash, run main app
    setup_logging()
    setup_playwright_bootstrapper()

    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass # Not running as a PyInstaller bundle with a splash screen

    main()
