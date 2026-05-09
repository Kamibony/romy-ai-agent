import cv2
import numpy as np
import pyautogui
import time
import tkinter as tk
import threading
import subprocess
import os
import requests
import pyperclip
import platform
import pygetwindow as gw
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- KONFIGURÁCIA ---
OUTPUT_FILENAME = "ROMY_REAL_MISSION_LOG.mp4"
BACKEND_URL = "http://localhost:8000"
SCREEN_SIZE = tuple(pyautogui.size())
FPS = 10.0

class RealTelemetryOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ROMY SYSTEM TELEMETRY - LIVE")
        self.root.geometry("600x500+1300+50") 
        self.root.attributes("-topmost", True)
        self.root.configure(bg='#000000')
        self.text_area = tk.Text(self.root, bg='#000000', fg='#00FF00', font=('Consolas', 10), takefocus=0)
        self.text_area.pack(expand=True, fill='both', padx=5, pady=5)
        self.log("CONNECTING TO ROMY CORE...")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.text_area.insert(tk.END, f"[{ts}] {msg}\n")
        self.text_area.see(tk.END)
        self.root.update()

def record_screen(stop_event):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(OUTPUT_FILENAME, fourcc, FPS, SCREEN_SIZE)
    frame_time = 1.0 / FPS
    while not stop_event.is_set():
        start_time = time.time()
        try:
            img = pyautogui.screenshot()
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            out.write(frame)
        except:
            break

        elapsed = time.time() - start_time
        if elapsed < frame_time:
            time.sleep(frame_time - elapsed)

    out.release()

def launch_app(app_path):
    # Fallback to simple Popen if system is not Windows
    if platform.system() == "Windows":
        return subprocess.Popen(app_path)
    else:
        # Simplistic fallback for test env
        if "calc" in app_path.lower():
            return subprocess.Popen(["gnome-calculator"])
        elif "notepad" in app_path.lower():
            return subprocess.Popen(["gedit"])
    return None

def focus_window_by_title(title_substring, max_wait=5.0):
    start_time = time.time()
    while time.time() - start_time < max_wait:
        # Only use pygetwindow on Windows
        if platform.system() == "Windows":
            for win in gw.getAllWindows():
                if win.title and title_substring.lower() in win.title.lower():
                    try:
                        if win.isMinimized:
                            win.restore()
                        win.activate()
                        time.sleep(0.5) # Allow time for focus to shift
                        return True
                    except Exception:
                        pass
        time.sleep(0.5)
    return False

def handle_cookie_consent(page, overlay):
    try:
        # Common selectors for cookie consent buttons
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('I agree')",
            "button:has-text('Accept')",
            "button:has-text('Agree')",
            "[aria-label='Accept all']",
            "[aria-label='I agree']"
        ]

        for selector in selectors:
            try:
                # Use a short timeout to check for the button
                if page.locator(selector).is_visible(timeout=3000):
                    overlay.log(f"WEB: Interstitial detected. Clicking '{selector}'")
                    page.locator(selector).click(timeout=3000)
                    time.sleep(2)
                    return True
            except:
                continue

        # Specific scroll or overlay handling could be added here if needed
        overlay.log("WEB: No known interstitial detected.")
    except Exception as e:
        overlay.log(f"WEB: Interstitial handler error: {str(e)[:40]}")

    return False

def run_real_mission(overlay):
    overlay.log("MISSION INITIALIZED: Semantic DOM Extraction")
    
    # 1. Kontrola backendu
    try:
        overlay.log(f"CHECKING BACKEND AT {BACKEND_URL}...")
        # Skúsime health check, ak tvoj backend nemá /health, stačí /
        response = requests.get(BACKEND_URL, timeout=5)
        overlay.log(f"BACKEND STATUS: {response.status_code} OK")
    except Exception as e:
        overlay.log(f"WARNING: Backend connection failed ({str(e)[:40]}). Proceeding in standalone mode...")

    # 2. Webová fáza cez Playwright
    real_price = "0.00"
    try:
        with sync_playwright() as p:
            overlay.log("ACTION: Launching Playwright Engine...")
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            
            overlay.log("NAVIGATING: https://finance.yahoo.com/quote/AAPL")
            page.goto("https://finance.yahoo.com/quote/AAPL", wait_until="domcontentloaded", timeout=60000)

            # Handle cookies
            handle_cookie_consent(page, overlay)
            
            overlay.log("SEMANTIC ANALYSIS: Scanning DOM for context...")
            
            # Selektor, ktorý sme overili, že na Yahoo funguje
            selector = 'fin-streamer[data-field="regularMarketPrice"][data-symbol="AAPL"]'
            try:
                element = page.wait_for_selector(selector, timeout=20000)
            except Exception as e:
                overlay.log("WEB: Initial selector failed, trying fallback selectors...")
                element = None

            if not element:
                fallback_selectors = [
                    'fin-streamer[data-symbol="AAPL"]',
                    'span[data-testid="qsp-price"]'
                ]
                for fallback in fallback_selectors:
                    try:
                        element = page.wait_for_selector(fallback, timeout=5000)
                        if element:
                            overlay.log(f"WEB: Fallback selector found: {fallback}")
                            break
                    except:
                        continue
            
            if element:
                time.sleep(2) # Nechajme diváka uvidieť cenu na webe
                real_price = element.inner_text().strip().replace(',', '')
                overlay.log(f"DATA CAPTURED: {real_price} USD")
            else:
                overlay.log("ERROR: Price element not found.")
                # We can still proceed to demonstrate OS automation with a dummy price
                real_price = "150.00"
                overlay.log(f"WARNING: Using dummy price {real_price} USD for OS automation.")

            time.sleep(2)
            browser.close()

        # 3. OS OPERÁCIA (Kalkulačka)
        overlay.log(f"CONTEXT SWITCH: Transferring {real_price} to OS")

        calc_path = r"C:\Windows\System32\calc.exe"
        overlay.log(f"OS: Launching {calc_path}")
        calc_process = launch_app(calc_path)

        # We need to ensure calculator has focus before typing
        calc_focused = focus_window_by_title("Calculator", max_wait=5.0)
        if not calc_focused:
            overlay.log("WARNING: Could not guarantee focus on Calculator. Inputs may be dropped.")
        
        pyautogui.write(f"{real_price}*150", interval=0.1)
        pyautogui.press('enter')
        time.sleep(2)

        if calc_process:
            try:
                calc_process.terminate()
            except:
                pass

        # 4. NOTEPAD REPORT
        overlay.log("REPORTING: Writing final scientific logs")
        notepad_path = r"C:\Windows\System32\notepad.exe"
        overlay.log(f"OS: Launching {notepad_path}")
        notepad_process = launch_app(notepad_path)
        
        notepad_focused = focus_window_by_title("Notepad", max_wait=5.0)
        if not notepad_focused:
            overlay.log("WARNING: Could not guarantee focus on Notepad. Inputs may be dropped.")

        full_log = overlay.text_area.get("1.0", tk.END)
        pyperclip.copy(f"ROMY SYSTEM REPORT\n{'-'*20}\n{full_log}")
        pyautogui.hotkey('ctrl', 'v')
        
        overlay.log("MISSION COMPLETE. Video stream saved.")
        time.sleep(5)

        if notepad_process:
            try:
                notepad_process.terminate()
            except:
                pass

    except Exception as e:
        overlay.log(f"CRITICAL FAILURE: {str(e)}")
        time.sleep(5)

if __name__ == "__main__":
    overlay = RealTelemetryOverlay()
    stop_event = threading.Event()
    recorder = threading.Thread(target=record_screen, args=(stop_event,))
    
    recorder.start()
    try:
        run_real_mission(overlay)
    finally:
        stop_event.set()
        recorder.join()
        overlay.root.destroy()
        print(f"Hotovo. Súbor: {os.path.abspath(OUTPUT_FILENAME)}")
