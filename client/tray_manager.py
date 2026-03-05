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
        print(f"Error creating tray icon image: {e}")
        # Return a fallback image just in case
        return Image.new('RGB', (width, height), (0, 0, 0))

def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """
    Callback function to handle shutting down the application.

    Args:
        icon (pystray.Icon): The system tray icon.
        item (pystray.MenuItem): The menu item clicked.
    """
    try:
        print("Shutting down the client...")
        icon.stop()
    except Exception as e:
        print(f"Error during shutdown: {e}")

def run_tray_icon() -> None:
    """
    Initializes and runs the system tray icon.
    This function blocks and must be run on the main thread.
    """
    try:
        # Create the icon image
        icon_image = create_image()

        # Define the menu
        # The 'Status: Waiting' item is disabled so it cannot be clicked
        menu = pystray.Menu(
            pystray.MenuItem("Status: Waiting", None, enabled=False),
            pystray.MenuItem("Quit", on_quit)
        )

        # Create the icon object
        icon = pystray.Icon(
            "b2b_ai_agent_mvp",
            icon_image,
            "B2B AI Agent MVP",
            menu
        )

        # Run the icon (blocks the thread)
        icon.run()
    except Exception as e:
        print(f"Error running system tray icon: {e}")
