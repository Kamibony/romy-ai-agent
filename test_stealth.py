from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

def test_stealth_configuration():
    print("Starting Playwright Stealth Test...")
    with sync_playwright() as p:
        # 2. Masking WebDriver flags properly
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
            ]
        )

        # 1. Injecting a highly credible, modern Windows/Chrome User-Agent
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'

        # 3. Randomizing or adjusting viewport, hardware concurrency, and generic navigator signals
        context = browser.new_context(
            user_agent=user_agent,
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/New_York',
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
            color_scheme='light'
        )

        # Apply stealth at context level (playwright-stealth >= 2.0.0 API)
        stealth = Stealth(
            # We can override default stealth options if needed
        )
        stealth.apply_stealth_sync(context)

        page = context.new_page()

        # Adjust hardware concurrency and device memory just in case
        page.add_init_script("""
            Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
            Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
        """)

        print("Navigating to https://bot.sannysoft.com/...")
        page.goto("https://bot.sannysoft.com/", wait_until="networkidle")

        print("Waiting for Sannysoft tests to complete...")
        page.wait_for_timeout(5000) # Give it 5 seconds to run the bot tests

        screenshot_path = "sannysoft_stealth_results.png"
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"Test complete. Screenshot saved to {screenshot_path}")

        browser.close()

if __name__ == "__main__":
    test_stealth_configuration()
