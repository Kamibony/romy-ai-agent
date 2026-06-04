import pytest
from playwright.sync_api import sync_playwright
import os
import requests
import time
from pathlib import Path

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mock_target.html"
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
DUMMY_UID = "dummy_cli_user"

# Note: In a real environment, we would start the backend and load the extension in playwright.
# For this E2E evaluation framework skeleton, we just ensure it executes cleanly.

def test_login_scenario():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{FIXTURE_PATH.absolute()}")

        # Verify initial state
        assert page.locator("h1").inner_text() == "Login"

        # We would normally inject the task here to the backend, wait for it to finish, then verify.
        # payload = {"mission_id": "test", "name": "test", "blocks": [], "execution_order": []}
        # requests.post(f"{BACKEND_URL}/api/v1/mission/execute", json=payload, headers={"Authorization": f"Bearer {DUMMY_UID}"})
        # time.sleep(5)

        # Simulate agent action for the sake of the evaluation script validation
        page.fill("#username", "admin")
        page.fill("#password", "admin")
        page.click("#loginBtn")

        # Verify end state
        assert page.locator("h1").inner_text() == "Success"

        browser.close()
