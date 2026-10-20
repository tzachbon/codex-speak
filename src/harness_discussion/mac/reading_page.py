"""Settings → Reading: copying hidden selections, early speech, and the read shortcut."""
import AppKit

from .. import hotkeys
from . import trigger, ui


class ReadingPage:
    """Mixed into SettingsWindow, which owns cfg, _set and _recorder."""

    def _reading_page(self):
        from .settings_ui import WIDTH, _card, _divider, _note  # settings_ui imports this module
        hidden, _ = ui.option("Read apps that hide their selection",
                              "Copies the selection with ⌘C, then puts your clipboard back.",
                              self.cfg["clipboard_fallback"], lambda on: self._set("clipboard_fallback", on), WIDTH)
        early, _ = ui.option("Prepare speech when I select text",
                             "When Cursor reads first, sends the first sentence to Cursor before you press "
                             "Play, so speech starts sooner.", self.cfg["prefetch"], lambda on: self._set("prefetch", on), WIDTH)
        return [_card([hidden, _divider(), early, _divider(), self._shortcut_row()]),
                _note("Reads the selected text without clicking the bar. Pressing it again stops the read.")]

    def _shortcut_row(self):
        from .settings_ui import WIDTH, _spacer
        self.hotkey_label = ui.label(hotkeys.label(self.cfg["hotkey"]), 13, bold=True)
        row = ui.stack([ui.label("Read shortcut", 13), _spacer(), self.hotkey_label,
                        ui.button("Change…", self._record_hotkey),
                        ui.button("Off", lambda: self._set_hotkey(""))], vertical=False, spacing=8)
        row.widthAnchor().constraintEqualToConstant_(WIDTH).setActive_(True)
        return row

    def _record_hotkey(self):
        """Change…: the next key combination with a modifier becomes the shortcut; Esc keeps the old one."""
        if self._recorder:
            return
        self.hotkey_label.setStringValue_("Press keys…")

        def key(event):
            if event.keyCode() == 53:  # Esc
                self._stop_recording()
            elif spec := trigger.event_spec(event):
                self._set_hotkey(spec)
            return None  # keys pressed while recording don't reach the window
        self._recorder = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskKeyDown, key)

    def _stop_recording(self):
        if self._recorder:
            AppKit.NSEvent.removeMonitor_(self._recorder)
            self._recorder = None
            self.hotkey_label.setStringValue_(hotkeys.label(self.cfg["hotkey"]))

    def _set_hotkey(self, spec):
        if spec != self.cfg["hotkey"]:
            self._set("hotkey", spec)
        self._stop_recording()
        self.hotkey_label.setStringValue_(hotkeys.label(spec))

