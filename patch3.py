with open("client/agent.py", "r") as f:
    content = f.read()

# Fix the `auto` reference bug in `LAUNCH_APP` inside the Voice Loop and `state_acting`.
# The problem is if `auto` is not imported, it throws NameError.
# But `uiautomation as auto` is imported at the top globally.
# Let's import it locally or check if it exists in the module namespace, or just import it locally inside the try block.

search_1 = """                            try:
                                active_window = auto.GetForegroundControl()
                                if active_window:
                                    initial_window_name = active_window.Name
                            except Exception:
                                pass"""

replace_1 = """                            try:
                                import uiautomation as local_auto
                                active_window = local_auto.GetForegroundControl()
                                if active_window:
                                    initial_window_name = active_window.Name
                            except Exception:
                                pass"""

search_2 = """                            for i in range(max_polls):
                                await asyncio.sleep(poll_interval)
                                try:
                                    current_window = auto.GetForegroundControl()
                                    if current_window and current_window.Name != initial_window_name:
                                        logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                        break
                                except Exception:
                                    pass"""

replace_2 = """                            for i in range(max_polls):
                                await asyncio.sleep(poll_interval)
                                try:
                                    import uiautomation as local_auto
                                    current_window = local_auto.GetForegroundControl()
                                    if current_window and current_window.Name != initial_window_name:
                                        logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                        break
                                except Exception:
                                    pass"""

search_3 = """                            for i in range(max_polls):
                                time.sleep(poll_interval)
                                try:
                                    current_window = auto.GetForegroundControl()
                                    if current_window and current_window.Name != initial_window_name:
                                        logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                        break
                                except Exception:
                                    pass"""

replace_3 = """                            for i in range(max_polls):
                                time.sleep(poll_interval)
                                try:
                                    import uiautomation as local_auto
                                    current_window = local_auto.GetForegroundControl()
                                    if current_window and current_window.Name != initial_window_name:
                                        logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                        break
                                except Exception:
                                    pass"""


content = content.replace(search_1, replace_1)
content = content.replace(search_2, replace_2)
content = content.replace(search_3, replace_3)

with open("client/agent.py", "w") as f:
    f.write(content)
