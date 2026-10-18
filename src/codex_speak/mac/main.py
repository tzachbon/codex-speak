"""macOS entry point: single instance, logging, start at login, the permission watcher."""
import fcntl
import logging
import logging.handlers
import os
import sys

from .. import settings
from ..core import App, log


def _self_test():
    """Used by CI on the built app: every module imports and the system frameworks answer."""
    import ctypes

    import AVFoundation
    from ApplicationServices import AXIsProcessTrusted

    from . import guide, host, pasteboard, permission, popup, selection, settings_ui, startup, trigger, voice  # noqa: F401
    AXIsProcessTrusted()
    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    carbon.IsSecureEventInputEnabled()
    AVFoundation.AVSpeechSynthesizer.alloc().init()
    host.MacHost()
    print("self-test ok")


def main():
    if sys.argv[1:2] == ["--self-test"]:
        _self_test()
        return
    os.makedirs(settings.DIR, exist_ok=True)
    lock = open(os.path.join(settings.DIR, "app.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another copy runs. Opening the app through Finder reaches it as a reopen
    handler = logging.handlers.RotatingFileHandler(os.path.join(settings.DIR, "codex-speak.log"),
                                                   maxBytes=256_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler],  # libraries log IPs at INFO
                        format="%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    log.info("start")
    from . import permission, startup
    from .host import MacHost
    try:
        startup.refresh()
    except OSError:
        log.exception("could not update the login item")
    try:
        host = MacHost()
        app = App(host)
        host.watcher = permission.Watcher(app)
        host.watcher.tick()
        app.start()
        host.run(app.pump)
    except Exception:
        log.exception("crashed")
        raise
