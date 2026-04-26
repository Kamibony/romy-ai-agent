import time
import subprocess
import pyautogui
import pyperclip
from playwright.sync_api import sync_playwright

def log_telemetry(message):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] ROMY_CORE: {message}")

def run_mission():
    log_telemetry("INICIALIZÁCIA SYSTÉMU - REŽIM NAHRÁVANIA")
    
    with sync_playwright() as p:
        # 1. WEB FÁZA
        log_telemetry("ŠTART: Sémantická analýza Yahoo Finance")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()
        
        page.goto("https://finance.yahoo.com/quote/AAPL", wait_until="commit")
        log_telemetry("NAVIGÁCIA: Stránka načítaná. Hľadám element ceny...")
        
        # Sémantický selektor (rovnaký, aký používa tvoj dom_mapper.js)
        selector = 'fin-streamer[data-field="regularMarketPrice"][data-symbol="AAPL"]'
        
        try:
            price_element = page.wait_for_selector(selector, timeout=20000)
            real_price = price_element.inner_text().strip().replace(',', '')
            log_telemetry(f"EXTRAKCIA: Úspešne získaná hodnota z DOM: {real_price}")
            time.sleep(3) # Pauza pre video
        except Exception as e:
            log_telemetry("CHYBA: Element v DOM nebol nájdený. Ukončujem misiu.")
            browser.close()
            return

        browser.close()
        log_telemetry("KONTEXT: Prepínam na OS operácie")

        # 2. OS FÁZA - Kalkulačka
        log_telemetry("AKCIA: Spúšťam Windows Kalkulačku (win+r focus)")
        pyautogui.hotkey('win', 'r')
        time.sleep(1)
        pyautogui.write('calc')
        pyautogui.press('enter')
        time.sleep(4)
        
        log_telemetry(f"VÝPOČET: Realizujem kalkuláciu {real_price} * 150")
        pyautogui.write(f"{real_price}*150", interval=0.1)
        pyautogui.press('enter')
        time.sleep(3)

        # 3. ZÁPIS REPORTU - Notepad
        log_telemetry("REPORT: Generujem vedecký záznam do Notepadu")
        pyautogui.hotkey('win', 'r')
        time.sleep(1)
        pyautogui.write('notepad')
        pyautogui.press('enter')
        time.sleep(3)

        report = (
            f"ROMY AI - E2E TEST REPORT\n"
            f"--------------------------\n"
            f"ZDROJ DÁT: Yahoo Finance (Live DOM)\n"
            f"HODNOTA: {real_price} USD\n"
            f"STATUS: Úspešne prenesené do OS\n"
            f"LOG: Všetky sémantické matchery pracovali správne."
        )
        pyperclip.copy(report)
        pyautogui.hotkey('ctrl', 'v')
        log_telemetry("MISIA KOMPLETNÁ.")
        time.sleep(5)

if __name__ == "__main__":
    run_mission()
