"""User settings in %APPDATA%, plus start-at-sign-in through the HKCU Run key."""
import json
import math
import os
import sys
import winreg

DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "select-to-tts")
PATH = os.path.join(DIR, "settings.json")
DEFAULTS = {"engine": None, "speed": 1.0, "clipboard_fallback": True}
SPEEDS = (0.5, 2.0)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "select-to-tts"  # the installer's uninstall step deletes this same value


def load(path=PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    s = {k: saved.get(k, v) for k, v in DEFAULTS.items()} if isinstance(saved, dict) else dict(DEFAULTS)
    if s["engine"] not in (None, "Codex", "Edge", "Windows"):
        s["engine"] = None
    speed = s["speed"]
    ok = isinstance(speed, (int, float)) and not isinstance(speed, bool) and math.isfinite(speed)
    s["speed"] = min(max(float(speed), SPEEDS[0]), SPEEDS[1]) if ok else DEFAULTS["speed"]
    if not isinstance(s["clipboard_fallback"], bool):
        s["clipboard_fallback"] = DEFAULTS["clipboard_fallback"]
    return s


def save(s: dict, path=PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, path)  # never leaves a half-written file behind


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pythonw}" -m select_to_tts'


def startup_enabled(name=RUN_VALUE) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, name)
        return True
    except OSError:
        return False


def set_startup(on: bool, name=RUN_VALUE) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, launch_command())
        elif startup_enabled(name):
            winreg.DeleteValue(k, name)
