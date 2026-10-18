"""macOS host: AppKit on the main thread, a menu bar item, Accessibility for the selection."""
import AppKit
import objc
from Foundation import NSObject

from ..codex_rt import CodexEngine
from ..cursor_tts import CursorEngine
from . import selection, ui
from .popup import Popup
from .settings_ui import SettingsWindow
from .trigger import SelectionTrigger
from .voice import MacVoiceEngine


class _Delegate(NSObject):
    def initWithHost_(self, host):
        self = objc.super(_Delegate, self).init()
        if self is not None:
            self.host = host
        return self

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        self.host.app.events.put(("settings",))  # opening the app again shows Settings
        return False

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return False

    def menuWillOpen_(self, menu):
        self.host.refresh_menu()


class MacHost:
    def __init__(self):
        self.app = None  # set by core.App
        self.watcher = None  # set by mac.main
        self.trigger, self._missing, self._error = None, False, None
        self.ns = AppKit.NSApplication.sharedApplication()
        self.ns.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        self.delegate = _Delegate.alloc().initWithHost_(self)
        self.ns.setDelegate_(self.delegate)
        self.item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        self.menu = AppKit.NSMenu.alloc().init()
        self.menu.setAutoenablesItems_(False)
        self.menu.setDelegate_(self.delegate)
        put = lambda *event: lambda _s: self.app.events.put(event)
        self._add("Settings…", put("settings"))
        self.permission_item = self._add("Permission needed…", lambda _s: self.watcher and self.watcher.show_guide())
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self.engine_item = self._add("Last voice source: -", None)
        self.error_item = self._add("", None)
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add("Quit Harness Discussion", put("quit"))
        self.item.setMenu_(self.menu)
        self.refresh_menu()

    def _add(self, title, fn):
        item = self.menu.addItemWithTitle_action_keyEquivalent_(title, "run:" if fn else None, "")
        if fn:
            item.setTarget_(ui.target(fn))
        item.setEnabled_(fn is not None)
        return item

    def refresh_menu(self):
        image = ui.symbol("exclamationmark.triangle.fill" if self._missing else "speaker.wave.2.fill",
                          "Harness Discussion")
        image.setTemplate_(not self._missing)
        self.item.button().setImage_(image)
        self.item.button().setToolTip_("Harness Discussion needs Accessibility permission" if self._missing
                                       else "Harness Discussion")
        self.permission_item.setHidden_(not self._missing)
        self.engine_item.setTitle_(f"Last voice source: {(self.app and self.app.chain.last) or '-'}")
        self.error_item.setHidden_(self._error is None)
        self.error_item.setTitle_(f"Last error: {self._error or ''}")

    def set_permission_missing(self, missing):
        self._missing = missing
        self.refresh_menu()
        win = self.app.settings_win
        if win and win.alive:
            win.refresh_permission()

    def engines(self):
        return [CursorEngine(), CodexEngine(), MacVoiceEngine()]

    def make_popup(self, speed, **callbacks):
        return Popup(speed, **callbacks)

    def open_settings(self, welcome=False):
        return SettingsWindow(self.app, lambda: self.watcher and self.watcher.show_guide(), welcome)

    def read_selection(self, clipboard_fallback):
        return selection.read(clipboard_fallback)

    def start_trigger(self, on_selection, on_press):
        if self.trigger is None:
            self.trigger = SelectionTrigger(on_selection, on_press)
            self.trigger.start()

    def stop_trigger(self):
        if self.trigger:
            self.trigger.stop()
            self.trigger = None

    def after(self, ms, fn):
        ui.timer(ms / 1000, fn)

    def notify(self, message):
        self._error = message[:80]
        self.refresh_menu()

    def run(self, pump):
        def tick():
            pump()
            if self.app._closing:
                timer.invalidate()
        timer = ui.timer(0.03, tick, repeats=True)
        self.ns.run()

    def quit(self):
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        self.ns.terminate_(None)
