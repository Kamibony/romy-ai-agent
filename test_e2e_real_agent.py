import time
import subprocess
import pyautogui
import pyperclip
from playwright.sync_api import sync_playwright

def log_telemetry(message):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] ROMY_CORE: {message}")

def run_mission():
    log_telemetry("ŠTART MISIE: REÁLNA EXTRAKCIA DÁT")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()
        
        log_telemetry("NAVIGÁCIA: Otváram finance.yahoo.com/quote/AAPL")
        page.goto("https://finance.yahoo.com/quote/AAPL", timeout=60000)
        
        # --- REÁLNA SÉMANTICKÁ EXTRAKCIA ---
        # Tu nepoužívame fallbacky. Ak Yahoo zmenilo selektor, test nahlási chybu.
        log_telemetry("SÉMANTICKÝ ENGINE: Identifikujem element 'regularMarketPrice'...")
        
        try:
            # Toto je hlavný dátový tag Yahoo Finance. 
            # Ak ho Romy v DOMe nenájde, misia končí - žiadne klamanie.
            price_element = page.wait_for_selector('fin-streamer[data-field="regularMarketPrice"]', timeout=20000)
            real_price = price_element.inner_text().strip().replace(',', '')
            
            log_telemetry(f"VERIFIKÁCIA: Dáta vyextrahované. Hodnota: {real_price}")
            time.sleep(3) 
        except Exception as e:
            log_telemetry("KRITICKÁ CHYBA: Element 'regularMarketPrice' nebol v DOMe nájdený.")
            log_telemetry("VÝSLEDOK: Misia neúspešná (Integrita dát zachovaná).")
            browser.close()
            return

        browser.close()

        # OS EXEKÚCIA (Bez klávesy WIN, priamy štart)
        log_telemetry("OS BRIDGE: Inicializujem prenos do natívnych aplikácií")
        
        # Kalkulačka
        subprocess.Popen('calc.exe')
        time.sleep(4)
        # Píšeme reálne vyextrahovanú hodnotu
        pyautogui.write(f"{real_price}*150", interval=0.1)
        pyautogui.press('enter')
        time.sleep(3)

        # Notepad
        subprocess.Popen('notepad.exe')
        time.sleep(3)

        report = (
            f"ROMY AI - AUTENTICKÝ SYSTÉMOVÝ REPORT\n"
            f"------------------------------------\n"
            f"VYEXTRAHOVANÁ CENA: {real_price} USD\n"
            f"METÓDA: Live DOM Extraction (Playwright)\n"
            f"STATUS: ŽIADNE MOCKUPY, ŽIADNE HARDCODED DÁTA."
        )
        pyperclip.copy(report)
        pyautogui.hotkey('ctrl', 'v')
        log_telemetry("MISIA KOMPLETNÁ. SYSTÉM REAGOVAL SPRÁVNE.")

if __name__ == "__main__":
    run_mission()
