"""The Settings window on macOS. Changes apply at once."""
import sys

import AppKit
from Foundation import NSURL

from .. import settings, updates
from ..stt_server import connection as stt_connection
from . import permission, startup, ui

WIDTH = 440
RELEASES = "https://github.com/tzachbon/harness-discussion/releases/tag/v{}"


def _section(title, views):
    return ui.stack([ui.label(title, 13, bold=True)] + views, spacing=8)


class SettingsWindow:
    def __init__(self, app, show_guide, welcome=False):
        self.app, self.cfg = app, dict(app.cfg)
        self._save_timer = None

        self.startup = ui.checkbox("Start Harness Discussion when I log in", startup.enabled(), self._startup_changed)
        self.update_button = ui.button("Check for updates", app.check_update)
        self.download_button = ui.button("Download", self._download)
        self.update_status = ui.label("", 11, secondary=True, width=WIDTH)
        self.auto_update = ui.checkbox("Check for updates automatically", self.cfg["auto_update"],
                                       lambda on: self._set("auto_update", on))
        general = _section("General", [
            self.startup,
            ui.stack([ui.label(f"Harness Discussion {updates.current_version()}"), self.update_button,
                      self.download_button], vertical=False),
            self.auto_update, self.update_status])

        self.permission_row = ui.stack([
            ui.label("Harness Discussion can't read selected text yet.", 12, width=WIDTH - 120),
            ui.button("Fix this", show_guide)], vertical=False, spacing=10)

        self.speed = AppKit.NSSlider.sliderWithValue_minValue_maxValue_target_action_(
            self.cfg["speed"], settings.SPEEDS[0], settings.SPEEDS[1], None, None)
        ui.bind(self.speed, lambda s: self._speed_changed(s.doubleValue()))
        self.speed.widthAnchor().constraintEqualToConstant_(260).setActive_(True)
        self.speed_label = ui.label(settings.speed_label(self.cfg["speed"]))
        self._engines = {e.name: e for e in app.chain.engines}
        self.source_rows = {name: self._source_row(name) for name, _ in self.cfg["sources"]}
        self.sources = ui.stack([], spacing=6)
        self.refresh_sources()
        self.welcome = ui.label(settings.WELCOME, 13, bold=True) if welcome else None
        reading = _section("Reading", [
            ui.stack([ui.label("Speed"), self.speed, self.speed_label], vertical=False),
            *([self.welcome] if welcome else []), self.sources,
            ui.label("Voice sources read in this order. If one can't read, the next one does. Codex uses your "
                     "ChatGPT sign-in and can read slower but not faster, so above 1× the next source reads. "
                     "macOS voices stay on this Mac. Add voices in System Settings > Accessibility > Spoken "
                     "Content.", 11, secondary=True, width=WIDTH),
            ui.button("Test voice", self._test)])

        selection = _section("Selection", [
            ui.checkbox("Read apps that hide their selection", self.cfg["clipboard_fallback"],
                        lambda on: self._set("clipboard_fallback", on)),
            ui.label("Copies the selection with ⌘C, then restores your clipboard.", 11, secondary=True),
            ui.checkbox("Prepare speech as soon as I select text", self.cfg["prefetch"],
                        lambda on: self._set("prefetch", on)),
            ui.label("Starts the first source before you press play, so speech begins sooner.", 11,
                     secondary=True)])

        self.stt_fields, self.stt_copy = {}, []
        rows = []
        for name in ("Server URL", "Model"):
            field = AppKit.NSTextField.alloc().init()
            field.setEditable_(False)
            field.setSelectable_(True)
            field.widthAnchor().constraintEqualToConstant_(270).setActive_(True)
            copy = ui.button("Copy", lambda name=name: self._copy_stt(name))
            self.stt_fields[name] = field
            self.stt_copy.append(copy)
            rows.append(ui.stack([ui.label(name, 12), field, copy], vertical=False))
        self.stt_status = ui.label("", 11, secondary=True, width=WIDTH - 90)
        stt = _section("Speech-to-text · OpenAI-compatible", [
            ui.checkbox("Run the speech-to-text server for other apps, such as OpenWhispr",
                        self.cfg["stt_server"], self._stt_toggled),
            *rows,
            ui.label("Paste into OpenWhispr → Self-Hosted. No API key needed. The URL stays the same after "
                     "restarts. Transcription only: JSON or text, up to 60 seconds.", 11, secondary=True,
                     width=WIDTH),
            ui.stack([self.stt_status, ui.button("Refresh", self._refresh_stt)], vertical=False)])

        self.content = ui.stack([general, self.permission_row, reading, selection, stt], spacing=20, inset=22)
        self.win = ui.window("Harness Discussion Settings", self.content)
        self.refresh_permission()
        self.focus()

    @property
    def alive(self):
        return bool(self.win.isVisible())

    def focus(self):
        self._refresh_stt()
        self.refresh_updates()
        self.refresh_permission()
        ui.show(self.win)

    def _fit(self):
        self.win.setContentSize_(self.content.fittingSize())

    def refresh_permission(self):
        self.permission_row.setHidden_(permission.trusted())
        self._fit()

    def refresh_updates(self):
        text, busy = self.app.update_state()
        installed = getattr(sys, "frozen", False)
        self.update_button.setEnabled_(installed and not busy)
        self.auto_update.setEnabled_(installed)
        self.download_button.setHidden_(self.app.available_version() is None)
        self.update_status.setStringValue_(text if installed else "Updates are available in installed builds.")

    def set_speed(self, speed):
        """Mirrors a speed picked in the popup, without saving it again."""
        self.speed.setDoubleValue_(speed)
        self.cfg["speed"] = speed
        self.speed_label.setStringValue_(settings.speed_label(speed))

    def close(self):
        self._flush()
        self.win.close()

    def _source_row(self, name):
        """(enabled, status, voice picker or None, row, (test, up, down)) for one voice source."""
        check = ui.checkbox(name, False, lambda on: self._set_sources(
            [[n, on if n == name else was] for n, was in self.cfg["sources"]]))
        status = ui.label("", 11, secondary=True, width=140)
        choices = getattr(self._engines.get(name), "voices", ())
        voice = AppKit.NSPopUpButton.alloc().init() if choices else None
        if voice:
            voice.addItemsWithTitles_([label for _, label in choices])
            ui.bind(voice, lambda s: self._set("voices", {**self.cfg["voices"],
                                                          name: choices[s.indexOfSelectedItem()][0]}))
        slot = voice or ui.label("Default voice" if name == "Codex" else "", 12, secondary=True)
        buttons = (ui.button("Test", lambda: self._test_source(name)),
                   ui.button("↑", lambda: self._move(name, -1)), ui.button("↓", lambda: self._move(name, 1)))
        buttons[1].setAccessibilityLabel_(f"Move {name} up")
        buttons[2].setAccessibilityLabel_(f"Move {name} down")
        for view, width in ((check, 80), (slot, 90)):
            view.widthAnchor().constraintEqualToConstant_(width).setActive_(True)
        return check, status, voice, ui.stack([check, status, slot, *buttons], vertical=False), buttons

    def refresh_sources(self):
        """Shows the rows in the saved order, with the statuses core last checked."""
        sources = self.cfg["sources"]
        for view in list(self.sources.arrangedSubviews()):
            self.sources.removeArrangedSubview_(view)
            view.removeFromSuperview()
        for i, (name, enabled) in enumerate(sources):
            check, status, voice, row, (_, up, down) = self.source_rows[name]
            check.setState_(1 if enabled else 0)
            status.setStringValue_(settings.status_text(self.app.statuses.get(name)))
            if voice:
                engine = self._engines[name]
                ids = [v for v, _ in engine.voices]
                chosen = self.cfg["voices"].get(name)
                chosen = chosen if chosen in ids else getattr(engine, "default_voice", ids[0])
                voice.selectItemAtIndex_(ids.index(chosen))
            up.setEnabled_(i > 0)
            down.setEnabled_(i < len(sources) - 1)
            self.sources.addArrangedSubview_(row)
        if hasattr(self, "win"):  # a status that wraps makes its row taller
            self._fit()

    def set_sources(self, sources):
        """Mirrors an order changed elsewhere, without saving it again."""
        self.cfg["sources"] = sources
        self.refresh_sources()

    def _set_sources(self, sources):
        self._set("sources", sources)
        self.refresh_sources()

    def _move(self, name, step):
        sources = [list(s) for s in self.cfg["sources"]]
        i = [n for n, _ in sources].index(name)
        if 0 <= i + step < len(sources):
            sources[i], sources[i + step] = sources[i + step], sources[i]
            self._set_sources(sources)

    def _test_source(self, name):
        self._flush()
        self.app.play(f"This is {name}.", None, only=name)

    def _set(self, key, value):
        self.cfg[key] = value
        self.app.change(key, value)

    def _speed_changed(self, value):
        value = round(value * 20) / 20  # 0.05 steps
        self.set_speed(value)
        self.app.change("speed", value, False)  # the next read uses it at once
        if self._save_timer:
            self._save_timer.invalidate()
        self._save_timer = ui.timer(0.4, self._flush)

    def _flush(self):
        if self._save_timer:
            self._save_timer.invalidate()
            self._save_timer = None
            self._set("speed", self.cfg["speed"])

    def _startup_changed(self, on):
        try:
            startup.set_enabled(on)
        except OSError as e:
            self.startup.setState_(1 if startup.enabled() else 0)
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_(f"Could not change start at login: {e}")
            alert.runModal()

    def _download(self):
        version = self.app.available_version()
        if version:
            AppKit.NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(RELEASES.format(version)))

    def _test(self):
        self._flush()
        self.app.test_voice(f"This is how Harness Discussion sounds at {settings.speed_label(self.cfg['speed'])} speed.")

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
