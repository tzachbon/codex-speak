"""The read-along caption: one line above the playback bar that scrolls when the sentence is wider."""
import time

import AppKit
import Quartz

from .. import lang
from . import ui

CAPTION_WIDTH = 340
CAPTION_PAD = 12
CAPTION_SPEED = 18  # points per second, the Windows caption's pace
CAPTION_FADE = 0.06  # share of the width that fades at each edge


class Caption:
    """Read-along: the sentence being read, as one line that scrolls, in a click-through panel above the bar."""

    def __init__(self):
        field = self.field = AppKit.NSTextField.labelWithString_("")
        field.setTextColor_(AppKit.NSColor.whiteColor())
        field.setLineBreakMode_(AppKit.NSLineBreakByClipping)
        shadow = AppKit.NSShadow.alloc().init()
        shadow.setShadowBlurRadius_(3)
        shadow.setShadowOffset_((0, -1))
        shadow.setShadowColor_(AppKit.NSColor.colorWithWhite_alpha_(0, 0.9))
        field.setShadow_(shadow)  # keeps white text readable over any page without a backdrop
        clip = self.clip = AppKit.NSView.alloc().init()
        clip.setWantsLayer_(True)
        clip.layer().setMasksToBounds_(True)
        fade = Quartz.CAGradientLayer.layer()  # text fades out at both edges, as on Windows
        fade.setStartPoint_((0, 0.5))
        fade.setEndPoint_((1, 0.5))
        clear, solid = ui.cg(AppKit.NSColor.clearColor()), ui.cg(AppKit.NSColor.blackColor())
        fade.setColors_([clear, solid, solid, clear])
        fade.setLocations_([0, CAPTION_FADE, 1 - CAPTION_FADE, 1])
        clip.layer().setMask_(fade)
        clip.addSubview_(field)
        box = self.box = AppKit.NSView.alloc().init()
        box.setWantsLayer_(True)
        box.layer().setCornerRadius_(10)
        box.addSubview_(clip)
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        p = self.win = ui.Panel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (10, 10)), style, AppKit.NSBackingStoreBuffered, False)
        p.setContentView_(box)
        self._place, self._timer, self._last_tick = None, None, None
        self.text, self.offset, self.paused = "", 0.0, False
        p.setIgnoresMouseEvents_(True)
        p.setLevel_(AppKit.NSStatusWindowLevel)
        p.setOpaque_(False)
        p.setBackgroundColor_(AppKit.NSColor.clearColor())
        p.setHasShadow_(False)
        p.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | AppKit.NSWindowCollectionBehaviorTransient)
        self.configure(10, False, 0.6)

    def configure(self, font_size, background, background_opacity):
        """font_size in Windows points, which render at 96 dpi: 4/3 of a Mac point."""
        self.field.setFont_(AppKit.NSFont.systemFontOfSize_weight_(font_size * 4 / 3, AppKit.NSFontWeightMedium))
        self.box.layer().setBackgroundColor_(ui.cg(AppKit.NSColor.colorWithWhite_alpha_(
            0.1, background_opacity if background else 0)))
        if self.win.isVisible():  # a font change from Settings resizes the caption on screen
            self.show(self.text, *self._place)

    def show(self, text, bar, area):
        """Centered above `bar`, or below it when the screen top is too close."""
        text = " ".join(text.split())
        if not text:
            return self.hide()
        growing = self.text and text.startswith(self.text)  # a Codex caption growing word by word keeps scrolling
        self.text = text
        self.field.setStringValue_(text)
        self._place = bar, area
        size = self.field.fittingSize()
        self.text_width, h = size.width, size.height
        self.clip.setFrame_(((0, 0), (CAPTION_WIDTH, h + 12)))
        self.clip.layer().mask().setFrame_(self.clip.bounds())
        if not growing:
            self._cancel()
            self.offset = self._end() if lang.reading_rtl(text) else 0.0
        self._layout()
        self.win.setContentSize_((CAPTION_WIDTH, h + 12))
        w = CAPTION_WIDTH
        x = bar.origin.x + (bar.size.width - w) / 2
        x = max(area.origin.x, min(x, area.origin.x + area.size.width - w))
        y = bar.origin.y + bar.size.height + 8
        if y + h + 12 > area.origin.y + area.size.height:
            y = bar.origin.y - 8 - h - 12
        self.win.setFrameOrigin_((x, y))
        self.win.orderFrontRegardless()
        self._schedule()

    def set_paused(self, paused):
        self.paused = paused
        self._cancel()
        if not paused:
            self._schedule()

    def hide(self):
        self._cancel()
        self.text, self.offset = "", 0.0
        self.win.orderOut_(None)

    def _end(self):
        """How far the line scrolls: 0 when it fits between the padding."""
        return max(0.0, self.text_width - (CAPTION_WIDTH - 2 * CAPTION_PAD))

    def _layout(self):
        self.offset = max(0.0, min(self.offset, self._end()))
        fits = not self._end()
        x = (CAPTION_WIDTH - self.text_width) / 2 if fits else CAPTION_PAD - self.offset
        self.field.setFrame_(((x, 6), (self.text_width, self.clip.frame().size.height - 12)))

    def _schedule(self):
        if self.text and not self.paused and self._end() and self._timer is None:
            self._last_tick = time.monotonic()
            self._timer = ui.timer(0.04, self._tick, repeats=True)

    def _tick(self):
        now = time.monotonic()
        distance = CAPTION_SPEED * (now - self._last_tick)
        self._last_tick = now
        rtl = lang.reading_rtl(self.text)
        self.offset += -distance if rtl else distance
        self._layout()
        if self.offset == (0 if rtl else self._end()):
            self._cancel()

    def _cancel(self):
        if self._timer:
            self._timer.invalidate()
            self._timer = None
