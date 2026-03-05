import keyboard
from agent import activate_agent

def start_hotkey_listener(hotkey: str = 'ctrl+space') -> None:
    """
    Registers a global hotkey to activate the agent.
    This function blocks, so it should be run in a separate thread.

    Args:
        hotkey (str): The hotkey combination to listen for. Defaults to 'ctrl+space'.
    """
    try:
        print(f"Listening for hotkey: {hotkey}")
        # Add the hotkey. When triggered, it calls `activate_agent`.
        keyboard.add_hotkey(hotkey, activate_agent)

        # Block the thread to keep listening for hotkeys.
        # We can use keyboard.wait() to block indefinitely,
        # but since we are running in a daemon thread, it will
        # exit when the main program finishes.
        keyboard.wait()
    except Exception as e:
        print(f"Error starting hotkey listener: {e}")
