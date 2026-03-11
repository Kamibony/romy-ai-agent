import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

def test_wikipedia_interaction():
    print("Starting Playwright Context with Stealth...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Apply stealth to the context
        stealth = Stealth()
        stealth.apply_stealth_sync(context)

        page = context.new_page()

        url = "https://sk.wikipedia.org"
        print(f"Navigating to {url}...")
        page.goto(url)
        page.wait_for_load_state('networkidle')

        # 1. Scan the DOM and inject 'data-romy-id'
        print("Scanning DOM and injecting 'data-romy-id'...")
        ui_elements = []
        memory_map = {}

        viewport = page.viewport_size
        vw = viewport['width'] if viewport else 1920
        vh = viewport['height'] if viewport else 1080

        elements = page.locator('button, a, input, select, textarea, [role="button"], [role="link"], [onclick], .btn, .button, [class*="btn"]').all()

        element_id = 1
        search_target_id = None

        for el in elements:
            try:
                if not el.is_visible():
                    continue

                box = el.bounding_box()
                if not box or box['width'] == 0 or box['height'] == 0:
                    continue

                tag_name = el.evaluate("el => el.tagName.toLowerCase()")

                # Get text or name
                text = el.inner_text().strip()
                if not text:
                    text = el.get_attribute('value') or el.get_attribute('name') or el.get_attribute('id') or el.get_attribute('placeholder') or ''

                center_x = int(box['x'] + box['width'] / 2)
                center_y = int(box['y'] + box['height'] / 2)

                if not (0 <= center_x <= vw and 0 <= center_y <= vh):
                    continue

                element_str_id = str(element_id)

                # Inject custom attribute into the live DOM
                el.evaluate(f'(node) => {{ node.setAttribute("data-romy-id", "{element_str_id}"); }}')

                ui_elements.append({
                    "id": element_str_id,
                    "type": tag_name,
                    "name": text
                })

                memory_map[element_str_id] = {
                    "x": center_x,
                    "y": center_y
                }

                # Try to identify the search input field
                if tag_name == 'input' and ('search' in text.lower() or el.get_attribute('type') == 'search'):
                    search_target_id = element_str_id
                    print(f"Found search bar with target_id: {search_target_id}")

                element_id += 1
            except Exception as e:
                pass

        print(f"Found {len(ui_elements)} elements.")

        # 2. Find search bar ID (fallback to manual search if auto-detect fails)
        if not search_target_id:
             print("Auto-detect failed, finding search input manually...")
             # Let's just find the first visible input
             for item in ui_elements:
                 if item['type'] == 'input':
                     search_target_id = item['id']
                     break

        if search_target_id:
            print(f"Using target_id {search_target_id} for typing...")
            text_to_type = "Slovensko"

            # 3. Simulate TYPE action
            print(f"Simulating TYPE action: '{text_to_type}' at element {search_target_id}...")
            locator = page.locator(f'[data-romy-id="{search_target_id}"]').first

            # Verify the element has the attribute
            has_attr = locator.evaluate('el => el.hasAttribute("data-romy-id")')
            print(f"Locator has data-romy-id attribute: {has_attr}")

            locator.click(force=True, click_count=3)
            time.sleep(0.1)
            page.keyboard.press("Backspace")
            time.sleep(0.2)
            page.keyboard.type(text_to_type)

            print("Action complete. Waiting 2 seconds to verify visually if headless=False...")
            time.sleep(2)

            # Verify the input value
            current_val = page.evaluate('() => document.querySelector("input[type=search]").value')
            if current_val == text_to_type:
                print(f"SUCCESS: Search bar contains '{current_val}'")
            else:
                print(f"FAILED: Search bar contains '{current_val}' instead of '{text_to_type}'")

        else:
            print("Could not find a search target to interact with.")

        browser.close()
        print("Test complete.")

if __name__ == "__main__":
    test_wikipedia_interaction()
