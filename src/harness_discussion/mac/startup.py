"""Start at login through a per-user LaunchAgent. Works with any code signature, unlike SMAppService."""
import os
import plistlib
import subprocess

LABEL = "com.tzachbon.harnessdiscussion"
OLD_LABEL = "com.tzachbon.codexspeak"  # Codex Speak, the app's earlier name


def plist_path(label=LABEL):
    return os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")


def bundle_path():
    """The running .app, or None for a source run."""
    from Foundation import NSBundle
    path = NSBundle.mainBundle().bundlePath()
    return str(path) if str(path).endswith(".app") else None


def enabled() -> bool:
    return os.path.exists(plist_path())


def set_enabled(on: bool, app=None) -> None:
    path = plist_path()
    if not on:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    app = app or bundle_path()
    if not app:
        raise OSError("Start at login needs the installed app, not a source run")
    # `open -a` lets LaunchServices keep a single copy running.
    data = {"Label": LABEL, "ProgramArguments": ["/usr/bin/open", "-a", app],
            "RunAtLoad": True, "ProcessType": "Interactive"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        plistlib.dump(data, f)
    os.replace(tmp, path)


def refresh(app=None) -> None:
    """Points an enabled login item at this copy of the app, which may have moved. Replaces
    Codex Speak's login item with this app's, so only one of them starts."""
    app = app or bundle_path()
    old = plist_path(OLD_LABEL)
    if os.path.exists(old):
        try:
            subprocess.run(["/bin/launchctl", "bootout", f"gui/{os.getuid()}", old], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass  # not loaded
        os.remove(old)
        if app:
            set_enabled(True, app)
    if not app or not enabled():
        return
    try:
        with open(plist_path(), "rb") as f:
            current = plistlib.load(f).get("ProgramArguments", [])
    except (OSError, plistlib.InvalidFileException):
        current = []
    if current[-1:] != [app]:
        set_enabled(True, app)
