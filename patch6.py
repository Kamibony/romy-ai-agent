import re
with open("client/agent.py", "r") as f:
    content = f.read()

# Update DesktopEnvironment methods to accept dpr
search_1 = """    async def click(self, x: int, y: int):
        await self._submit_task(self._sync_click, x, y)

    def _sync_click(self, x, y):
        try:"""

replace_1 = """    async def click(self, x: int, y: int, dpr: float = 1.0):
        await self._submit_task(self._sync_click, x, y, dpr)

    def _sync_click(self, x, y, dpr=1.0):
        try:
            x, y = int(x * dpr), int(y * dpr)"""

search_2 = """    async def type(self, x: int, y: int, text: str, submit: bool = False, target_id: Optional[str] = None):
        await self._submit_task(self._sync_type, x, y, text, submit, target_id)

    async def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int):
        await self._submit_task(self._sync_drag_and_drop, start_x, start_y, end_x, end_y)

    def _sync_drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int):
        try:"""

replace_2 = """    async def type(self, x: int, y: int, text: str, submit: bool = False, target_id: Optional[str] = None, dpr: float = 1.0):
        await self._submit_task(self._sync_type, x, y, text, submit, target_id, dpr)

    async def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int, dpr: float = 1.0):
        await self._submit_task(self._sync_drag_and_drop, start_x, start_y, end_x, end_y, dpr)

    def _sync_drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int, dpr: float = 1.0):
        try:
            start_x, start_y = int(start_x * dpr), int(start_y * dpr)
            end_x, end_y = int(end_x * dpr), int(end_y * dpr)"""

search_3 = """    def _sync_type(self, x, y, text, submit, target_id=None):
        try:
            # Kinematic Fix: Physical click is mandatory to guarantee focus before typing,
            # especially since programmatic SetFocus() often fails on complex OS UI frameworks.
            if target_id is None:
                # Apply scaling for spatial fallbacks
                pass

            if config.STEALTH_MODE:"""

replace_3 = """    def _sync_type(self, x, y, text, submit, target_id=None, dpr=1.0):
        try:
            x, y = int(x * dpr), int(y * dpr)
            # Kinematic Fix: Physical click is mandatory to guarantee focus before typing,
            # especially since programmatic SetFocus() often fails on complex OS UI frameworks.
            if config.STEALTH_MODE:"""

content = content.replace(search_1, replace_1)
content = content.replace(search_2, replace_2)
content = content.replace(search_3, replace_3)

# Now update the calls to `await desktop_env.click`, `await desktop_env.type`, `await desktop_env.drag_and_drop` in state_acting to pass dpr
search_4 = """                             await desktop_env.click(int(action_to_take["x"]), int(action_to_take["y"]))"""
replace_4 = """                             await desktop_env.click(int(action_to_take["x"]), int(action_to_take["y"]), getattr(self, 'current_dpr', 1.0))"""

search_5 = """                             await desktop_env.type(int(action_to_take["x"]), int(action_to_take["y"]), text, action_to_take.get("submit", False), target_id=None)"""
replace_5 = """                             await desktop_env.type(int(action_to_take["x"]), int(action_to_take["y"]), text, action_to_take.get("submit", False), target_id=None, dpr=getattr(self, 'current_dpr', 1.0))"""

search_6 = """                         await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y))"""
replace_6 = """                         if "target_id" not in action_to_take:
                             await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y), getattr(self, 'current_dpr', 1.0))
                         else:
                             await desktop_env.drag_and_drop(int(start_x), int(start_y), int(end_x), int(end_y))"""

content = content.replace(search_4, replace_4)
content = content.replace(search_5, replace_5)
content = content.replace(search_6, replace_6)

# The reviewer also said: "physical focus is gained by clicking before simulating keystrokes".
# `_sync_type` already does this:
# pyautogui.click()
# time.sleep(0.1) # Short physical cooldown after click

with open("client/agent.py", "w") as f:
    f.write(content)
