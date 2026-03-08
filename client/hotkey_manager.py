import logging
import keyboard
from agent import activate_agent, trigger_abort

def start_hotkey_listener(hotkey: str = 'ctrl+space', abort_hotkey: str = 'ctrl+esc') -> None:
    """
    Registers global hotkeys to activate or abort the agent.
    This function blocks, so it should be run in a separate thread.

    Args:
        hotkey (str): The hotkey combination to listen for activation. Defaults to 'ctrl+space'.
        abort_hotkey (str): The hotkey combination to listen for emergency abort. Defaults to 'ctrl+esc'.
    """
    try:
        logging.info(f"Listening for hotkey: {hotkey} and abort hotkey: {abort_hotkey}")
        # Add the hotkey. When triggered, it calls `activate_agent`.
        keyboard.add_hotkey(hotkey, activate_agent)

        # Add the abort hotkey. When triggered, it calls `trigger_abort`.
        keyboard.add_hotkey(abort_hotkey, trigger_abort)

        # Block the thread to keep listening for hotkeys.
        # We can use keyboard.wait() to block indefinitely,
        # but since we are running in a daemon thread, it will
        # exit when the main program finishes.
        keyboard.wait()
    except Exception as e:
        logging.error(f"Error starting hotkey listener: {e}")
