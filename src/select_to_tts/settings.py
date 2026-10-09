"""User settings in %APPDATA%, plus start-at-sign-in through a Task Scheduler logon task."""
import json
import math
import os
import sys
import tempfile
import winreg

DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "select-to-tts")
PATH = os.path.join(DIR, "settings.json")
TEMP_DIR = os.path.join(tempfile.gettempdir(), "select-to-tts")  # uninstall deletes it
DEFAULTS = {"engine": None, "speed": 1.0, "clipboard_fallback": True, "stt_server": False,
            "prefetch": False, "auto_update": False, "caption_font_size": 10, "caption_background": False,
            "caption_background_opacity": 0.6}
SPEEDS = (0.5, 2.0)
SPEED_PRESETS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)  # the popup's speed menu
TASK = "Select to TTS"  # the installer creates and removes it with `--startup on|off`
# Earlier builds used this Run value. Windows starts Run entries one at a time after sign-in,
# waiting up to 30 s on each, which delayed the app by minutes.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "select-to-tts"


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
    try:
        ok = isinstance(speed, (int, float)) and not isinstance(speed, bool) and math.isfinite(speed)
    except OverflowError:  # an integer too large for a float
        ok = False
    s["speed"] = min(max(float(speed), SPEEDS[0]), SPEEDS[1]) if ok else DEFAULTS["speed"]
    font_size = s["caption_font_size"]
    s["caption_font_size"] = (min(max(font_size, 8), 24)
                               if isinstance(font_size, int) and not isinstance(font_size, bool)
                               else DEFAULTS["caption_font_size"])
    opacity = s["caption_background_opacity"]
    try:
        ok = isinstance(opacity, (int, float)) and not isinstance(opacity, bool) and math.isfinite(opacity)
    except OverflowError:  # an integer too large for a float
        ok = False
    s["caption_background_opacity"] = (min(max(float(opacity), 0.0), 1.0)
                                        if ok else DEFAULTS["caption_background_opacity"])
    for key in ("clipboard_fallback", "stt_server", "prefetch", "caption_background", "auto_update"):
        if not isinstance(s[key], bool):
            s[key] = DEFAULTS[key]
    return s


def save(s: dict, path=PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, path)  # never leaves a half-written file behind


def speed_label(speed: float) -> str:
    return f"{speed:g}×"


def launch_command() -> tuple[str, str]:
    """(program, arguments) that start this app."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    return os.path.join(os.path.dirname(sys.executable), "pythonw.exe"), "-m select_to_tts"


def _scheduler():
    import comtypes.client
    service = comtypes.client.CreateObject("Schedule.Service", dynamic=True)
    service.Connect()
    return service


def startup_enabled(name=TASK) -> bool:
    try:
        _scheduler().GetFolder("\\").GetTask(name)
        return True
    except Exception:  # COMError when the task does not exist
        return False


def set_startup(on: bool, name=TASK) -> None:
    """A logon task for this user only, which needs no admin rights. Also drops the old Run value."""
    from comtypes import COMError
    try:
        service = _scheduler()
        folder = service.GetFolder("\\")
        if on:
            user = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
            d = _logon_task(service, user, *launch_command())
            folder.RegisterTaskDefinition(name, d, 6, user, None, 3)  # create or update, interactive
        elif startup_enabled(name):
            folder.DeleteTask(name, 0)
    except COMError as e:
        raise OSError(str(e)) from e
    if name == TASK:
        _drop_run_value()


def _logon_task(service, user, program, args):
    d = service.NewTask(0)
    d.RegistrationInfo.Description = "Starts Select to TTS when you sign in."
    trigger = d.Triggers.Create(9)  # TASK_TRIGGER_LOGON
    trigger.UserId = user
    action = d.Actions.Create(0)  # TASK_ACTION_EXEC
    action.Path, action.Arguments, action.WorkingDirectory = program, args, os.path.dirname(program)
    d.Settings.DisallowStartIfOnBatteries = False
    d.Settings.StopIfGoingOnBatteries = False
    d.Settings.ExecutionTimeLimit = "PT0S"  # the default would stop the app after 72 hours
    d.Settings.Priority = 5  # the default 7 runs below normal priority
    return d


def _drop_run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
    except OSError:
        pass  # not there


def refresh_startup() -> None:
    """Points an enabled sign-in task at this install (it may have moved) and moves an older
    build's Run value to the task. Source runs leave an installed copy's task alone."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
        legacy = True
    except OSError:
        legacy = False
    if legacy or (getattr(sys, "frozen", False) and startup_enabled()):
        set_startup(True)
