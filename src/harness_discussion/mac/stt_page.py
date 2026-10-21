"""Settings → Speech to Text on macOS: the local OpenAI-compatible server and its connection details."""
import AppKit

from ..stt_server import connection as stt_connection
from . import ui


class SttPage:
    """Mixed into SettingsWindow, which owns app, cfg and _set."""

    def _stt_page(self):
        from .settings_ui import WIDTH, _card, _note, _spacer  # settings_ui imports this module
        self.stt_fields, self.stt_copy = {}, []
        rows = []
        for name in ("Server URL", "Model"):
            field = AppKit.NSTextField.alloc().init()
            field.setEditable_(False)
            field.setSelectable_(True)
            field.widthAnchor().constraintEqualToConstant_(WIDTH - 160).setActive_(True)
            copy = ui.button("Copy", lambda name=name: self._copy_stt(name))
            self.stt_fields[name] = field
            self.stt_copy.append(copy)
            rows.append(ui.stack([ui.label(name, 12, width=80), field, copy], vertical=False))
        self.stt_status = ui.label("", 11, secondary=True, width=WIDTH - 90)
        server, _ = ui.option("Run the speech-to-text server",
                              "An OpenAI-compatible endpoint on this Mac for apps such as OpenWhispr.",
                              self.cfg["stt_server"], self._stt_toggled, WIDTH)
        return [_card([server]),
                _card([*rows, ui.stack([self.stt_status, _spacer(), ui.button("Refresh", self._refresh_stt)],
                                       vertical=False)]),
                _note("Paste into OpenWhispr → Self-Hosted. No API key needed. The URL stays the same after "
                      "restarts. Transcription only: JSON or text, up to 60 seconds.")]

    def _stt_toggled(self, on):
        self._set("stt_server", on)
        ui.timer(0.3, self._refresh_stt)

    def _refresh_stt(self):
        try:
            values = stt_connection()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            values = ("", "")
        for field, value in zip(self.stt_fields.values(), values):
            field.setStringValue_(value)
        for button in self.stt_copy:
            button.setEnabled_(bool(values[0]))
        problem = self.app.stt_error
        self.stt_status.setStringValue_(problem if problem else "Running." if values[0]
                                        else "Turn on the server above.")

    def _copy_stt(self, name):
        self._refresh_stt()
        value = self.stt_fields[name].stringValue()
        if value:
            board = AppKit.NSPasteboard.generalPasteboard()
            board.clearContents()
            board.setString_forType_(value, AppKit.NSPasteboardTypeString)
            self.stt_status.setStringValue_(f"{name} copied.")
