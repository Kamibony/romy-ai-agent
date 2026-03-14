import logging
import logging
import pystray
from PIL import Image

def create_image(width: int = 64, height: int = 64, color: tuple = (0, 0, 255)) -> Image.Image:
    """
    Creates a simple square image for the system tray icon.

    Args:
        width (int): Image width. Defaults to 64.
        height (int): Image height. Defaults to 64.
        color (tuple): RGB color tuple. Defaults to (0, 0, 255) for blue.

    Returns:
        Image.Image: A PIL Image object.
    """
    try:
        # Create a solid color image
        image = Image.new('RGB', (width, height), color)
        return image
    except Exception as e:
        logging.error(f"Error creating tray icon image: {e}")
        # Return a fallback image just in case
        return Image.new('RGB', (width, height), (0, 0, 0))

import os
import signal

def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """
    Callback function to handle shutting down the application.

    Args:
        icon (pystray.Icon): The system tray icon.
        item (pystray.MenuItem): The menu item clicked.
    """
    try:
        logging.info("Shutting down the client...")
        icon.stop()
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception as e:
        logging.error(f"Error during shutdown: {e}")

import sys

def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

def on_pause_resume(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """
    Callback function to handle pausing/resuming the agent.
    """
    try:
        from agent import toggle_pause
        is_paused = toggle_pause()

        # We need to recreate the menu to update the status text if we want,
        # but pystray dynamically updates if we provide a callable for text.
        # Alternatively, we can use item.checked or dynamic text.
    except Exception as e:
        logging.error(f"Error toggling pause: {e}")

def get_pause_text(item: pystray.MenuItem) -> str:
    from agent import PAUSE_AGENT
    return "Resume" if PAUSE_AGENT else "Pause"

def get_status_text(item: pystray.MenuItem) -> str:
    from agent import PAUSE_AGENT
    return "Status: Paused" if PAUSE_AGENT else "Status: Listening for mobile..."

def run_tray_icon() -> None:
    """
    Initializes and runs the system tray icon.
    """
    try:
        # Load custom icon if available, otherwise fallback to generated image
        icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            icon_image = Image.open(icon_path)
        else:
            icon_image = create_image()

        # Define the menu
        menu = pystray.Menu(
            pystray.MenuItem(get_status_text, None, enabled=False),
            pystray.MenuItem(get_pause_text, on_pause_resume),
            pystray.MenuItem("Exit", on_quit)
        )

        # Create the icon object
        icon = pystray.Icon(
            "b2b_ai_agent_mvp",
            icon_image,
            "ROMY AI Agent",
            menu
        )

        # Run the icon (blocks the thread)
        icon.run()
    except Exception as e:
        logging.error(f"Error running system tray icon: {e}")
