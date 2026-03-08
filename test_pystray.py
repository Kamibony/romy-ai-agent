import pystray
import threading
from PIL import Image

def run_tray():
    image = Image.new('RGB', (64, 64), (0, 0, 255))
    icon = pystray.Icon("test", image, "Test", pystray.Menu(pystray.MenuItem("Quit", lambda i, j: i.stop())))
    icon.run()

t = threading.Thread(target=run_tray, daemon=True)
t.start()
print("Tray started in thread")
import time
time.sleep(2)
print("Done")
