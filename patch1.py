with open("client/agent.py", "r") as f:
    content = f.read()

search_block = """                     # Execution Context Guarding for OS (Graceful Degradation)
                     if action_type in ["CLICK", "TYPE"]:
                         if "target_id" not in action_to_take:
                             raise ValueError(f"Missing 'target_id' for {action_type} action.")
                         target_id = str(action_to_take["target_id"])
                         if target_id not in getattr(self, "os_memory_map", {}):
                             logging.warning(f"Kinematic Wait: Target ID {target_id} not found in OS memory map. UI may be rendering. Bailing batch to re-evaluate.")
                             try:
                                 await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                                     "telemetry": f"Waiting for target {target_id} to render..."
                                 })
                             except Exception:
                                 pass
                             bail_out = True
                             break # Exit batch cleanly to force GET_STATE cycle

                     if action_type == "LAUNCH_APP":
                         app_name = action_to_take.get("app_name")
                         if not app_name:
                             raise ValueError("Missing 'app_name' for LAUNCH_APP action.")
                         logging.info(f"Deterministically launching application: {app_name}")
                         try:
                             # Use os.startfile on Windows to allow app resolution from PATH (e.g. calc.exe, notepad.exe) safely
                             os.startfile(app_name)
                             await asyncio.sleep(2.0)
                             # Break batch to force a fresh GET_STATE of the new window, letting ReAct loop wait for it natively
                             bail_out = True
                             break
                         except Exception as e:
                             logging.error(f"Failed to launch app {app_name}: {e}")
                             raise
                     elif action_type == "CLICK":
                         target_id = str(action_to_take.get("target_id"))
                         el = getattr(self, "os_memory_map", {})[target_id]
                         await desktop_env.click(el["center"]["x"], el["center"]["y"])
                     elif action_type == "TYPE":
                         target_id = str(action_to_take.get("target_id"))
                         text = action_to_take.get("text")
                         if text is None:
                             raise ValueError("Missing 'text' for TYPE action.")
                         el = getattr(self, "os_memory_map", {})[target_id]
                         await desktop_env.type(el["center"]["x"], el["center"]["y"], text, action_to_take.get("submit", False), target_id=target_id)
                     elif action_type == "DRAG_AND_DROP":
                         start_x = action_to_take.get("start_x")
                         start_y = action_to_take.get("start_y")
                         end_x = action_to_take.get("end_x")
                         end_y = action_to_take.get("end_y")
                         if start_x is None or start_y is None or end_x is None or end_y is None:
                             raise ValueError("Missing one or more coordinates (start_x, start_y, end_x, end_y) for DRAG_AND_DROP.")
                         await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y))"""

replace_block = """                     # Execution Context Guarding for OS (Graceful Degradation)
                     if action_type in ["CLICK", "TYPE"]:
                         if "target_id" in action_to_take:
                             target_id = str(action_to_take["target_id"])
                             if target_id not in getattr(self, "os_memory_map", {}):
                                 logging.warning(f"Kinematic Wait: Target ID {target_id} not found in OS memory map. UI may be rendering. Bailing batch to re-evaluate.")
                                 try:
                                     await asyncio.to_thread(firestore_update_document, "remote_commands", self.doc_id, {
                                         "telemetry": f"Waiting for target {target_id} to render..."
                                     })
                                 except Exception:
                                     pass
                                 bail_out = True
                                 break # Exit batch cleanly to force GET_STATE cycle
                         else:
                             # Spatial Fallback Execution Routing
                             if action_type == "CLICK" and ("x" not in action_to_take or "y" not in action_to_take):
                                 raise ValueError(f"Missing 'target_id' or spatial coordinates (x, y) for {action_type} action.")
                             if action_type == "TYPE" and ("x" not in action_to_take or "y" not in action_to_take):
                                 raise ValueError(f"Missing 'target_id' or spatial coordinates (x, y) for {action_type} action.")

                     if action_type == "LAUNCH_APP":
                         app_name = action_to_take.get("app_name")
                         if not app_name:
                             raise ValueError("Missing 'app_name' for LAUNCH_APP action.")
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

                             # Use os.startfile on Windows to allow app resolution from PATH (e.g. calc.exe, notepad.exe) safely
                             os.startfile(app_name)

                             # Kinematic Quiescence Polling
                             poll_interval = 0.5
                             max_polls = 20  # Max 10 seconds wait
                             for i in range(max_polls):
                                 await asyncio.sleep(poll_interval)
                                 try:
                                     current_window = auto.GetForegroundControl()
                                     if current_window and current_window.Name != initial_window_name:
                                         logging.info(f"OS Quiescence Reached: Foreground window changed from '{initial_window_name}' to '{current_window.Name}'.")
                                         break
                                 except Exception:
                                     pass

                             # Break batch to force a fresh GET_STATE of the new window, letting ReAct loop wait for it natively
                             bail_out = True
                             break
                         except Exception as e:
                             logging.error(f"Failed to launch app {app_name}: {e}")
                             raise
                     elif action_type == "CLICK":
                         if "target_id" in action_to_take:
                             target_id = str(action_to_take.get("target_id"))
                             el = getattr(self, "os_memory_map", {})[target_id]
                             await desktop_env.click(el["center"]["x"], el["center"]["y"])
                         else:
                             await desktop_env.click(int(action_to_take["x"]), int(action_to_take["y"]))
                     elif action_type == "TYPE":
                         text = action_to_take.get("text")
                         if text is None:
                             raise ValueError("Missing 'text' for TYPE action.")
                         if "target_id" in action_to_take:
                             target_id = str(action_to_take.get("target_id"))
                             el = getattr(self, "os_memory_map", {})[target_id]
                             await desktop_env.type(el["center"]["x"], el["center"]["y"], text, action_to_take.get("submit", False), target_id=target_id)
                         else:
                             await desktop_env.type(int(action_to_take["x"]), int(action_to_take["y"]), text, action_to_take.get("submit", False), target_id=None)
                     elif action_type == "DRAG_AND_DROP":
                         start_x = action_to_take.get("start_x")
                         start_y = action_to_take.get("start_y")
                         end_x = action_to_take.get("end_x")
                         end_y = action_to_take.get("end_y")
                         if start_x is None or start_y is None or end_x is None or end_y is None:
                             raise ValueError("Missing one or more coordinates (start_x, start_y, end_x, end_y) for DRAG_AND_DROP.")
                         await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y))"""

new_content = content.replace(search_block, replace_block)
with open("client/agent.py", "w") as f:
    f.write(new_content)
