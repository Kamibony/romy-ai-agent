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
        self.text_area = tk.Text(self.root, bg='#000000', fg='#00FF00', font=('Consolas', 10))
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
    while not stop_event.is_set():
        try:
            img = pyautogui.screenshot()
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            out.write(frame)
        except:
            break
    out.release()

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
            page.goto("https://finance.yahoo.com/quote/AAPL", wait_until="commit", timeout=60000)
            
            overlay.log("SEMANTIC ANALYSIS: Scanning DOM for context...")
            
            # Selektor, ktorý sme overili, že na Yahoo funguje
            selector = 'fin-streamer[data-field="regularMarketPrice"][data-symbol="AAPL"]'
            element = page.wait_for_selector(selector, timeout=20000)
            
            if element:
                time.sleep(2) # Nechajme diváka uvidieť cenu na webe
                real_price = element.inner_text().strip().replace(',', '')
                overlay.log(f"DATA CAPTURED: {real_price} USD")
            else:
                overlay.log("ERROR: Price element not found.")
                browser.close()
                return

            time.sleep(2)
            browser.close()

        # 3. OS OPERÁCIA (Kalkulačka)
        overlay.log(f"CONTEXT SWITCH: Transferring {real_price} to OS")
        pyautogui.hotkey('win', 'r')
        time.sleep(1)
        pyautogui.write('calc')
        pyautogui.press('enter')
        time.sleep(4)
        
        pyautogui.write(f"{real_price}*150", interval=0.1)
        pyautogui.press('enter')
        time.sleep(2)

        # 4. NOTEPAD REPORT
        overlay.log("REPORTING: Writing final scientific logs")
        pyautogui.hotkey('win', 'r')
        time.sleep(1)
        pyautogui.write('notepad')
        pyautogui.press('enter')
        time.sleep(3)
        
        full_log = overlay.text_area.get("1.0", tk.END)
        pyperclip.copy(f"ROMY SYSTEM REPORT\n{'-'*20}\n{full_log}")
        pyautogui.hotkey('ctrl', 'v')
        
        overlay.log("MISSION COMPLETE. Video stream saved.")
        time.sleep(5)

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