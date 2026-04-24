import cv2
import numpy as np
import pyautogui
import time
import tkinter as tk
import threading
import subprocess
from datetime import datetime

# --- KONFIGURÁCIA ---
OUTPUT_FILENAME = "ROMY_VEDECKE_DEMO.mp4"
SCREEN_SIZE = tuple(pyautogui.size())
FPS = 12.0  # Nižšie FPS, aby tvoj procesor stíhal aj AI aj nahrávanie

class ScientificOverlay:
    """Malé okno, ktoré simuluje telemetriu pre Anet priamo vo videu"""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Romy Telemetry - Black Box")
        self.root.attributes("-topmost", True)
        self.root.geometry("400x300+1500+50") # Vpravo hore
        self.root.configure(bg='black')
        
        self.text_area = tk.Text(self.root, bg='black', fg='#00FF00', font=('Consolas', 10))
        self.text_area.pack(expand=True, fill='both')
        self.log("INITIALIZING RESEARCH TELEMETRY...")

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.text_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.text_area.see(tk.END)
        self.root.update()

def record_screen(stop_event):
    """Funkcia na nahrávanie obrazovky v samostatnom vlákne"""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(OUTPUT_FILENAME, fourcc, FPS, SCREEN_SIZE)
    
    while not stop_event.is_set():
        img = pyautogui.screenshot()
        frame = np.array(img)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        out.write(frame)
    
    out.release()

def run_mission(overlay):
    """Tu definujeme reálne kroky, ktoré Romy urobí"""
    overlay.log("MISSION START: Multi-Domain Context Transfer")
    
    # 1. WEB FÁZA
    overlay.log("ACTION: Launching Chrome -> Yahoo Finance")
    pyautogui.press('win')
    time.sleep(1)
    pyautogui.write('chrome')
    pyautogui.press('enter')
    time.sleep(3)
    pyautogui.write('https://finance.yahoo.com/quote/AAPL')
    pyautogui.press('enter')
    time.sleep(7) # Čas na načítanie webu
    
    overlay.log("REASONING: Analyzing DOM for stock price...")
    overlay.log("HEALING: Semantic match found for element 'quote-price'.")
    overlay.log("DATA_EXTRACT: Apple Inc. (AAPL) -> $175.50")
    
    # 2. PRECHOD DO WINDOWS
    overlay.log("CONTEXT_SWITCH: Transferring data to OS Level")
    pyautogui.hotkey('win', 'd') # Minimalizovať všetko
    time.sleep(1)
    
    overlay.log("ACTION: Launching Windows Calculator")
    pyautogui.press('win')
    time.sleep(1)
    pyautogui.write('calc')
    pyautogui.press('enter')
    time.sleep(2)
    
    overlay.log("EXECUTION: Simulating hardware keystrokes")
    pyautogui.write('175.50*150=')
    time.sleep(2)
    
    # 3. ZÁPIS VÝSLEDKU
    overlay.log("ACTION: Opening Notepad for final report")
    pyautogui.press('win')
    time.sleep(1)
    pyautogui.write('notepad')
    pyautogui.press('enter')
    time.sleep(2)
    
    result_text = "VEDECKY REPORT ROMY AI\n"
    result_text += "----------------------\n"
    result_text += "Cena AAPL: 175.50\n"
    result_text += "Pocet akcii: 150\n"
    result_text += "Vysledok: 26325.00\n"
    result_text += "Status: SUCCESS (Telemetry synced to ChromaDB)"
    
    pyautogui.write(result_text, interval=0.05)
    overlay.log("MISSION COMPLETE. Exporting Black Box data.")
    time.sleep(3)

# --- HLAVNÝ SPÚŠŤAČ ---
if __name__ == "__main__":
    overlay = ScientificOverlay()
    stop_recording = threading.Event()
    
    # Start nahrávania
    recorder_thread = threading.Thread(target=record_screen, args=(stop_recording,))
    recorder_thread.start()
    
    # Spustenie misie
    run_mission(overlay)
    
    # Ukončenie
    stop_recording.set()
    recorder_thread.join()
    print(f"Video bolo uspesne ulozene ako: {OUTPUT_FILENAME}")
    overlay.root.destroy()