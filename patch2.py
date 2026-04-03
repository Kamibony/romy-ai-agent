with open("client/agent.py", "r") as f:
    content = f.read()

search_block = """                    # Execution Context Guarding for OS inside Voice Loop
                    if action_upper in ["CLICK", "TYPE"]:
                        if "target_id" not in act:
                            logging.error(f"Safety Bailout: Missing 'target_id' for {action_upper} action. Re-evaluating...")
                            try:
                                firestore_update_document("remote_commands", doc_id, {
                                    "telemetry": f"Safety Bailout: Missing 'target_id' for {action_upper} action. Retrying..."
                                })
                            except Exception as e:
                                pass
                            break
                        target_id = str(act["target_id"])
                        if target_id not in memory_map:
                            logging.error(f"Safety Bailout: Target ID {target_id} not found in OS memory map. The expected window might not be focused or ready.")
                            try:
                                firestore_update_document("remote_commands", doc_id, {
                                    "telemetry": f"Safety Bailout: Target ID {target_id} not found. Window state may have shifted. Retrying..."
                                })
                            except Exception as e:
                                pass
                            break

                    if action_upper == "SUB_TASK_COMPLETE":
                        logging.info(f"Sub-task completed: {current_sub_task}")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif action_upper == "DONE":
                        logging.info("Task finished.")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif "ERROR" in action_upper:
                        raw_response = act.get("raw_response", "No raw response provided")
                        error_msg = act.get("error", "No error message provided")
                        logging.error(f"Agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif action_upper == "LAUNCH_APP" and "app_name" in act:
                        app_name = act["app_name"]
                        logging.info(f"Deterministically launching application: {app_name}")
                        try:
                            # Use os.startfile on Windows to allow app resolution from PATH safely
                            os.startfile(app_name)
                            time.sleep(2)
                            had_terminal_action = True
                            break_outer = True
                            break
                        except Exception as e:
                            logging.error(f"Failed to launch app {app_name}: {e}")
                    elif action_upper == "CLICK":
                        target_id = str(act["target_id"])
                        # Existence verified by context guard
                        logging.info(f"Clicking element with ID {target_id} using PyAutoGUI...")
                        try:
                            x = memory_map[target_id]["x"]
                            y = memory_map[target_id]["y"]
                            pyautogui.moveTo(x, y, duration=0.5)
                            pyautogui.click()
                        except Exception as click_e:
                            logging.error(f"Error executing click via PyAutoGUI: {click_e}.")

                    elif action_upper == "TYPE":
                        target_id = str(act["target_id"])
                        text_to_type = act.get("text", "")
                        # Existence verified by context guard
                        logging.info(f"Typing '{text_to_type}' at element {target_id} using PyAutoGUI...")
                        try:
                            x = memory_map[target_id]["x"]
                            y = memory_map[target_id]["y"]
                            pyautogui.moveTo(x, y, duration=0.5)
                            pyautogui.click()
                            pyautogui.hotkey('ctrl', 'a')
                            pyautogui.press('backspace')
                            time.sleep(0.2)
                            pyautogui.write(text_to_type)
                        except Exception as type_e:
                            logging.error(f"Error executing type via PyAutoGUI: {type_e}.")"""

replace_block = """                    # Execution Context Guarding for OS inside Voice Loop
                    if action_upper in ["CLICK", "TYPE"]:
                        if "target_id" in act:
                            target_id = str(act["target_id"])
                            if target_id not in memory_map:
                                logging.error(f"Safety Bailout: Target ID {target_id} not found in OS memory map. The expected window might not be focused or ready.")
                                try:
                                    firestore_update_document("remote_commands", doc_id, {
                                        "telemetry": f"Safety Bailout: Target ID {target_id} not found. Window state may have shifted. Retrying..."
                                    })
                                except Exception as e:
                                    pass
                                break
                        else:
                            # Spatial Fallback Execution Routing
                            if action_upper == "CLICK" and ("x" not in act or "y" not in act):
                                logging.error(f"Safety Bailout: Missing 'target_id' or spatial coordinates (x, y) for {action_upper} action.")
                                break
                            if action_upper == "TYPE" and ("x" not in act or "y" not in act):
                                logging.error(f"Safety Bailout: Missing 'target_id' or spatial coordinates (x, y) for {action_upper} action.")
                                break

                    if action_upper == "SUB_TASK_COMPLETE":
                        logging.info(f"Sub-task completed: {current_sub_task}")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif action_upper == "DONE":
                        logging.info("Task finished.")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif "ERROR" in action_upper:
                        raw_response = act.get("raw_response", "No raw response provided")
                        error_msg = act.get("error", "No error message provided")
                        logging.error(f"Agent stopped due to {action_upper}. Error: {error_msg} | Raw response: {raw_response}")
                        had_terminal_action = True
                        break_outer = True
                        break
                    elif action_upper == "LAUNCH_APP" and "app_name" in act:
                        app_name = act["app_name"]
                        logging.info(f"Deterministically launching application: {app_name}")
                        try:
                            # Capture active window before launch
                            initial_window_name = "Unknown"
                            try:
                                active_window = auto.GetForegroundControl()
                                if active_window:
                                    initial_window_name = active_window.Name
                            except Exception:
                                pass

                            # Use os.startfile on Windows to allow app resolution from PATH safely
                            os.startfile(app_name)

                            # Kinematic Quiescence Polling
                            poll_interval = 0.5
                            max_polls = 20  # Max 10 seconds wait
                            for i in range(max_polls):
                                time.sleep(poll_interval)
                                try:
                                    current_window = auto.GetForegroundControl()
                                    if current_window and current_window.Name != initial_window_name:
                                        logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                        break
                                except Exception:
                                    pass

                            had_terminal_action = True
                            break_outer = True
                            break
                        except Exception as e:
                            logging.error(f"Failed to launch app {app_name}: {e}")
                    elif action_upper == "CLICK":
                        try:
                            if "target_id" in act:
                                target_id = str(act["target_id"])
                                logging.info(f"Clicking element with ID {target_id} using PyAutoGUI...")
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                            else:
                                logging.info(f"Clicking coordinate ({act['x']}, {act['y']}) using PyAutoGUI...")
                                x = int(act["x"])
                                y = int(act["y"])
                            pyautogui.moveTo(x, y, duration=0.5)
                            pyautogui.click()
                        except Exception as click_e:
                            logging.error(f"Error executing click via PyAutoGUI: {click_e}.")

                    elif action_upper == "TYPE":
                        text_to_type = act.get("text", "")
                        try:
                            if "target_id" in act:
                                target_id = str(act["target_id"])
                                logging.info(f"Typing '{text_to_type}' at element {target_id} using PyAutoGUI...")
                                x = memory_map[target_id]["x"]
                                y = memory_map[target_id]["y"]
                            else:
                                logging.info(f"Typing '{text_to_type}' at coordinate ({act['x']}, {act['y']}) using PyAutoGUI...")
                                x = int(act["x"])
                                y = int(act["y"])
                            pyautogui.moveTo(x, y, duration=0.5)
                            pyautogui.click()
                            pyautogui.hotkey('ctrl', 'a')
                            pyautogui.press('backspace')
                            time.sleep(0.2)
                            pyautogui.write(text_to_type)
                        except Exception as type_e:
                            logging.error(f"Error executing type via PyAutoGUI: {type_e}.")"""

new_content = content.replace(search_block, replace_block)
with open("client/agent.py", "w") as f:
    f.write(new_content)
