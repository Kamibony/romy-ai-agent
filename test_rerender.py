import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://sk.wikipedia.org')
    page.wait_for_load_state('networkidle')

    # Simulate the exact test logic
    elements = page.locator('button, a, input, select, textarea, [role="button"], [role="link"], [onclick], .btn, .button, [class*="btn"]').all()

    target_el = None
    target_id = None
    i = 1
    for el in elements:
        try:
            if not el.is_visible(): continue
            box = el.bounding_box()
            if not box or box['width'] == 0 or box['height'] == 0: continue

            el.evaluate(f'(node) => {{ node.setAttribute("data-romy-id", "{i}"); }}')

            if el.evaluate('el => el.tagName.toLowerCase()') == 'input':
                if el.get_attribute('type') == 'search':
                    target_el = el
                    target_id = i
            i += 1
        except: pass

    print(f'Found search ID: {target_id}')

    loc = page.locator(f'[data-romy-id="{target_id}"]')
    print('Loc count:', loc.count())
    if loc.count() > 0:
        print('Before clicking, html:', loc.first.evaluate('node => node.outerHTML'))
        loc.first.click(force=True, click_count=3)
        time.sleep(0.1)
        page.keyboard.press('Backspace')
        time.sleep(0.2)

        # When we click, does Wikipedia remove/re-render the element?
        print('After clicking, count:', loc.count())
        loc.first.fill('Slovensko', force=True, timeout=5000)
        print('Filled!', loc.first.input_value())

    browser.close()
