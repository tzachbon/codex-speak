"""The Captions page of Settings on macOS: font size, background and background opacity."""
import AppKit

from . import ui


class CaptionsPage:
    """Mixed into SettingsWindow, which owns cfg and _set."""

    def _captions_page(self):
        from .settings_ui import WIDTH, _card, _divider, _note, _spacer  # settings_ui imports this module
        self.font_size = AppKit.NSStepper.alloc().init()
        self.font_size.setMinValue_(8)
        self.font_size.setMaxValue_(24)
        self.font_size.setIntValue_(self.cfg["caption_font_size"])
        ui.bind(self.font_size, lambda s: self._font_size_changed(s.intValue()))
        self.font_size_label = ui.label(f"{self.cfg['caption_font_size']} pt", 13)
        size = ui.stack([ui.label("Font size", 13), _spacer(), self.font_size_label, self.font_size], vertical=False)
        size.widthAnchor().constraintEqualToConstant_(WIDTH).setActive_(True)
        backdrop, _ = ui.option("Show a background behind captions", "A dark box behind the text, for busy pages.",
                                self.cfg["caption_background"], self._background_changed, WIDTH)
        self.opacity = AppKit.NSSlider.sliderWithValue_minValue_maxValue_target_action_(
            round(self.cfg["caption_background_opacity"] * 100), 0, 100, None, None)
        self.opacity.setContinuous_(False)  # saves once, when the drag ends
        ui.bind(self.opacity, lambda s: self._set("caption_background_opacity", round(s.doubleValue()) / 100))
        self.opacity.widthAnchor().constraintEqualToConstant_(WIDTH - 190).setActive_(True)
        self.opacity.setEnabled_(self.cfg["caption_background"])
        opacity = ui.stack([ui.label("Background opacity", 13), _spacer(), self.opacity], vertical=False)
        opacity.widthAnchor().constraintEqualToConstant_(WIDTH).setActive_(True)
        return [_card([size, _divider(), backdrop, _divider(), opacity]),
                _note("While a selection is read, the sentence being read shows above the bar.")]

    def _font_size_changed(self, size):
        self.font_size_label.setStringValue_(f"{size} pt")
        self._set("caption_font_size", size)

    def _background_changed(self, on):
        self.opacity.setEnabled_(on)
        self._set("caption_background", on)
