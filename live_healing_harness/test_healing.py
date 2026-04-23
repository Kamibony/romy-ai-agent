import asyncio
import os
import json
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import time

# Configurations
PLAYGROUND_HTML_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "playground.html"))
BACKEND_URL = "http://localhost:8000"
API_ENDPOINT = f"{BACKEND_URL}/api/v1/agent/rescue"

# Environment
os.environ["ROMY_TEST_MODE"] = "1"
os.environ["LOCAL_DEV"] = "True"

class Reporter:
    def __init__(self, filename="LIVE_HEALING_REPORT.md"):
        self.filename = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", filename))
        with open(self.filename, "w") as f:
            f.write("# Automated Live E2E Healing Harness Report\n\n")

    def log(self, text):
        print(text)
        with open(self.filename, "a") as f:
            f.write(text + "\n")

reporter = Reporter()

async def fetch_dom_snippet(page):
    # Simplified version, in reality we'd use DOM mapper or raw HTML
    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")
    # Clean up scripts
    for s in soup(["script", "style"]):
        s.decompose()
    return str(soup.body)

async def test_scenario(page, scenario_num, intent, original_selector, check_selector):
    reporter.log(f"## Scenario {scenario_num}: {intent}")

    # Reload page to reset state
    await page.goto(f"file://{PLAYGROUND_HTML_PATH}")

    # Check if element exists before mutation
    try:
        elements_before = await page.locator(check_selector).count()
        if elements_before == 0:
            reporter.log(f"❌ Setup error: Check selector '{check_selector}' not found before mutation.")
            return False
    except:
        pass

    # Trigger mutation
    await page.evaluate(f"window.mutateUI({scenario_num})")
    await asyncio.sleep(0.5) # Wait for mutation

    # Check if element exists
    try:
        elements = await page.locator(check_selector).count()
        if elements > 0:
             reporter.log(f"❌ Failed to mutate UI, check selector '{check_selector}' still works.")
             return False
    except:
        pass

    reporter.log(f"✅ Mutation applied. Check selector '{check_selector}' no longer works.")

    # Get current DOM snippet
    current_dom_snippet = await fetch_dom_snippet(page)

    # Trigger healing
    reporter.log("🔄 Triggering Healing API...")
    payload = {
        "intent": intent,
        "failed_selector": original_selector,
        "current_dom_snippet": current_dom_snippet
    }

    headers = {
        "Authorization": "Bearer local-dev-token",
        "Content-Type": "application/json"
    }

    start_time = time.time()
    try:
        response = requests.post(API_ENDPOINT, json=payload, headers=headers, timeout=30)
        latency = time.time() - start_time

        reporter.log(f"⏱️ LLM Latency: {latency:.2f}s")
        reporter.log(f"HTTP Status: {response.status_code}")

        if response.status_code != 200:
            reporter.log(f"❌ Healing API Failed: {response.text}")
            return False

        result = response.json()
        reporter.log(f"```json\n{json.dumps(result, indent=2)}\n```")

        if result.get("status") == "HEALED":
            new_selector = result.get("target_id")
            if not new_selector:
                reporter.log("❌ Response was HEALED but missing 'target_id'")
                return False

            reporter.log(f"✅ LLM returned new selector: {new_selector}")

            # Verify the new selector works
            new_elements = 0

            try:
                new_elements = await page.locator(f"#{new_selector}").count()
            except Exception as e:
                pass

            if new_elements == 0:
                try:
                    new_elements = await page.locator(new_selector).count()
                except Exception as e:
                    pass

            if new_elements > 0:
                reporter.log(f"✅ New selector found element(s) in the live DOM.")
                return True
            else:
                reporter.log(f"❌ New selector '{new_selector}' did NOT find any element in the live DOM.")
                return False
        else:
            reporter.log("❌ LLM failed to heal the element.")
            return False

    except Exception as e:
        reporter.log(f"❌ Exception calling API: {str(e)}")
        return False

async def run_harness():
    reporter.log("Starting Live E2E Healing Test Harness...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        scenarios = [
            (1, "Click the Login button", "#login-btn-v1", "#login-btn-v1"),
            (2, "Click the Checkout button", "#checkout-btn", "text=Proceed to Checkout"),
            (3, "Click the Settings button", "#settings-btn", "#sidebar > #settings-btn")
        ]

        success_count = 0
        for num, intent, selector, check_selector in scenarios:
            success = await test_scenario(page, num, intent, selector, check_selector)
            if success:
                success_count += 1
            reporter.log("---\n")

        reporter.log(f"## Final Results: {success_count}/{len(scenarios)} Scenarios Passed")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_harness())
