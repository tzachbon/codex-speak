"""The floating button bar next to a selection: a non-activating panel that never takes focus."""
import AppKit
import objc

from .. import lang, settings
from . import ui
from .caption import Caption

IDLE_HIDE_S = 4.0


class _Button(AppKit.NSButton):
    def acceptsFirstMouse_(self, event):
        return True  # one click works while another app stays active


class _Hover(AppKit.NSView):
    """Content view that reports mouse enter and exit, so the idle timer pauses while hovered."""

    def initWithOwner_(self, owner):
        self = objc.super(_Hover, self).init()
        if self is not None:
            self.owner = owner
        return self

    def updateTrackingAreas(self):
        objc.super(_Hover, self).updateTrackingAreas()
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        options = (AppKit.NSTrackingMouseEnteredAndExited | AppKit.NSTrackingActiveAlways
                   | AppKit.NSTrackingInVisibleRect)
        self.addTrackingArea_(AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), options, self, None))

    def mouseEntered_(self, event):
        self.owner.cancel_hide()

    def mouseExited_(self, event):
        self.owner.schedule_hide()


def _icon_button(name, description, fn, tint=None):
    b = _Button.alloc().init()
    b.setBezelStyle_(AppKit.NSBezelStyleRegularSquare)
    b.setBordered_(False)
    b.setImage_(ui.symbol(name, description))
    b.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
    b.setContentTintColor_(tint or AppKit.NSColor.colorWithWhite_alpha_(1, 0.6))
    b.widthAnchor().constraintEqualToConstant_(26).setActive_(True)
    b.heightAnchor().constraintEqualToConstant_(26).setActive_(True)
    return ui.bind(b, lambda _s: fn())


def _play_button(fn):
    """Play/Pause: a filled circle in the system accent color, the one control that stands out."""
    b = _icon_button("play.fill", "Play", fn, tint=AppKit.NSColor.whiteColor())
    for c in b.constraints():
        c.setConstant_(30)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(15)
    b.layer().setBackgroundColor_(ui.cg(AppKit.NSColor.controlAccentColor()))
    return b


def _text_button(fn, title, titles, icon=lambda _t: None):
    """A rounded chip that opens a menu, as wide as its widest title so a pick never moves the bar."""
    b = _Button.alloc().init()
    b.setBezelStyle_(AppKit.NSBezelStyleRegularSquare)
    b.setBordered_(False)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(8)
    b.layer().setBackgroundColor_(ui.cg(AppKit.NSColor.colorWithWhite_alpha_(1, 0.1)))
    b.setContentTintColor_(AppKit.NSColor.labelColor())
    b.heightAnchor().constraintEqualToConstant_(26).setActive_(True)
    widest = 0
    for option in titles:
        _set_title(b, option, icon(option))
        widest = max(widest, b.cell().cellSize().width)
    b.widthAnchor().constraintEqualToConstant_(widest + 24).setActive_(True)
    _set_title(b, title, icon(title) if title else None)
    return ui.bind(b, lambda s: fn(s))


def _set_title(button, title, image=None):
    """`[icon] title ▾` with a dimmed chevron; the icon is inline so it centers with the title."""
    font = AppKit.NSFont.systemFontOfSize_weight_(12, AppKit.NSFontWeightMedium)
    text = AppKit.NSMutableAttributedString.alloc().init()
    if image:
        icon = AppKit.NSTextAttachment.alloc().init()
        icon.setImage_(image)
        size = image.size()
        icon.setBounds_(((0, (font.capHeight() - size.height) / 2), (size.width, size.height)))
        text.appendAttributedString_(AppKit.NSAttributedString.attributedStringWithAttachment_(icon))
        title = " " + title
    text.appendAttributedString_(AppKit.NSAttributedString.alloc().initWithString_attributes_(
        title + " ", {AppKit.NSFontAttributeName: font,
                       AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor()}))
    text.appendAttributedString_(AppKit.NSAttributedString.alloc().initWithString_attributes_(
        "▾", {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(9),
              AppKit.NSForegroundColorAttributeName: AppKit.NSColor.colorWithWhite_alpha_(1, 0.55),
              AppKit.NSBaselineOffsetAttributeName: 1}))
    button.setAttributedTitle_(text)


def _divider():
    line = AppKit.NSBox.alloc().init()
    line.setBoxType_(AppKit.NSBoxSeparator)
    line.heightAnchor().constraintEqualToConstant_(18).setActive_(True)
    return line


def _cocoa_y(top):
    """Top-left y of the main screen to AppKit's bottom-left y."""
    return AppKit.NSScreen.screens()[0].frame().size.height - top


def _screen_at(x, y):
    point = (x, _cocoa_y(y))
    for screen in AppKit.NSScreen.screens():
        if AppKit.NSPointInRect(point, screen.frame()):
            return screen
    return AppKit.NSScreen.mainScreen()


class Popup:
    def __init__(self, speed, *, on_play, on_stop, on_pause, on_resume, on_lang, on_speed, on_settings,
                 on_source, sources, on_skip, on_summarize=lambda text, tag: None):
        """sources: returns the source names the menu offers; on_source(name) picks one. on_skip(-1 or 1)."""
        self.on_play, self.on_stop, self.on_pause, self.on_resume = on_play, on_stop, on_pause, on_resume
        self.on_summarize = on_summarize
        self.on_lang, self.on_speed, self.on_settings = on_lang, on_speed, on_settings
        self.on_source, self.sources = on_source, sources
        self.text, self.playing, self.paused, self.menu_open, self.loading = "", False, False, False, False
        self._lang, self._speed, self._source, self._hide_timer = None, speed, None, None

        self.btn = _play_button(self._toggle)
        self.stop_btn = _icon_button("stop.fill", "Stop", self._stop, tint=AppKit.NSColor.whiteColor())
        self.back_btn = _icon_button("backward.fill", "Previous sentence", lambda: on_skip(-1))
        self.next_btn = _icon_button("forward.fill", "Next sentence", lambda: on_skip(1))
        self.spinner = AppKit.NSProgressIndicator.alloc().init()
        self.spinner.setStyle_(AppKit.NSProgressIndicatorStyleSpinning)
        self.spinner.setControlSize_(AppKit.NSControlSizeSmall)
        for anchor in (self.spinner.widthAnchor(), self.spinner.heightAnchor()):
            anchor.constraintEqualToConstant_(30).setActive_(True)
        self.ai_btn = _icon_button("sparkles", "Summarize", self._summarize, tint=AppKit.NSColor.whiteColor())
        self.ai_btn.setToolTip_("Summarize")
        self.ai_btn.setWantsLayer_(True)
        self.ai_btn.layer().setCornerRadius_(8)
        self.ai_progress = AppKit.NSProgressIndicator.alloc().init()  # a filling ring while the model downloads
        self.ai_progress.setStyle_(AppKit.NSProgressIndicatorStyleSpinning)
        self.ai_progress.setControlSize_(AppKit.NSControlSizeSmall)
        self.ai_progress.setIndeterminate_(False)
        self.ai_progress.setMaxValue_(1.0)
        for anchor in (self.ai_progress.widthAnchor(), self.ai_progress.heightAnchor()):
            anchor.constraintEqualToConstant_(26).setActive_(True)
        self.lang_btn = _text_button(self._lang_menu, "Auto", ["Auto"] + [v[0] for v in lang.LANGS.values()])
        self.speed_btn = _text_button(self._speed_menu, settings.speed_label(speed),
                                      [settings.speed_label(s) for s in settings.SPEED_PRESETS])
        self.source_btn = _text_button(self._source_menu, "", settings.DEFAULT_SOURCES, ui.source_icon)
        settings_btn = _icon_button("gearshape.fill", "Settings", self._open_settings)
        close_btn = _icon_button("xmark", "Close", self.close)
        row = ui.stack([self.btn, self.spinner, self.back_btn, self.next_btn, self.stop_btn, self.ai_btn,
                        self.ai_progress, _divider(), self.source_btn, self.lang_btn, self.speed_btn, _divider(),
                        settings_btn, close_btn], vertical=False, spacing=6)
        row.setEdgeInsets_((6, 7, 6, 8))
        self.spinner.setHidden_(True)
        self.ai_progress.setHidden_(True)

        effect = AppKit.NSVisualEffectView.alloc().init()
        effect.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        effect.setState_(AppKit.NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(21)  # a pill: half of the 42-point height
        effect.layer().setMasksToBounds_(True)
        effect.layer().setBorderWidth_(0.5)
        effect.layer().setBorderColor_(ui.cg(AppKit.NSColor.colorWithWhite_alpha_(1, 0.15)))
        hover = _Hover.alloc().initWithOwner_(self)
        for parent, child in ((hover, effect), (effect, row)):
            child.setTranslatesAutoresizingMaskIntoConstraints_(False)
            parent.addSubview_(child)
            for a, b in (("leadingAnchor", "leadingAnchor"), ("trailingAnchor", "trailingAnchor"),
                         ("topAnchor", "topAnchor"), ("bottomAnchor", "bottomAnchor")):
                getattr(child, a)().constraintEqualToAnchor_(getattr(parent, b)()).setActive_(True)

        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        p = self.win = ui.Panel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (10, 10)), style, AppKit.NSBackingStoreBuffered, False)
        p.setContentView_(hover)
        self.caption = Caption()
        p.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameVibrantDark))
        p.setLevel_(AppKit.NSStatusWindowLevel)
        p.setFloatingPanel_(True)
        p.setBecomesKeyOnlyIfNeeded_(True)
        p.setHidesOnDeactivate_(False)
        p.setOpaque_(False)
        p.setBackgroundColor_(AppKit.NSColor.clearColor())
        p.setHasShadow_(True)
        p.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | AppKit.NSWindowCollectionBehaviorTransient)

    def show(self, text, x, y):
        self.text = text
        self.set_playing(False)
        self._set_lang(None)
        p = self.win
        p.setContentSize_(p.contentView().fittingSize())
        w, h = p.frame().size.width, p.frame().size.height
        area = _screen_at(x, y).visibleFrame()
        area_top = _cocoa_y(area.origin.y + area.size.height)  # top-left y of the usable area
        area_bottom = area_top + area.size.height
        top = y - h - 14 if y - h - 14 >= area_top else y + 16
        top = max(area_top, min(top, area_bottom - h))
        left = max(area.origin.x, min(x + 12, area.origin.x + area.size.width - w))
        p.setFrameOrigin_((left, _cocoa_y(top + h)))
        p.orderFrontRegardless()
        self.schedule_hide()

    def close(self):
        """The ✕ button: stop any read and hide."""
        self.set_playing(False)
        self.hide()

    def hide(self):
        self.cancel_hide()
        self.caption.hide()
        self.win.orderOut_(None)
        self.on_stop()  # drops the Codex session warmed up for this popup

    @property
    def visible(self):
        return bool(self.win.isVisible())

    def contains(self, x, y):
        f = self.win.frame()
        top = _cocoa_y(f.origin.y + f.size.height)
        return self.visible and f.origin.x <= x < f.origin.x + f.size.width and top <= y < top + f.size.height

    def lang_tag(self):
        return self._lang

    def set_loading(self, loading):
        if loading == self.loading:
            return
        self.loading = loading
        self.btn.setHidden_(loading)
        self.spinner.setHidden_(not loading)
        self.spinner.startAnimation_(None) if loading else self.spinner.stopAnimation_(None)

    def set_playing(self, playing, paused=False):
        self.playing, self.paused = playing, playing and paused
        if not playing:
            self.caption.hide()
            self.set_loading(False)
            self._highlight(False)
        self.caption.set_paused(self.paused)  # a read stopped while paused must not freeze the next one
        pausing = playing and not paused
        self.btn.setImage_(ui.symbol("pause.fill" if pausing else "play.fill", "Pause" if pausing else "Play"))
        for button in (self.stop_btn, self.back_btn, self.next_btn):
            button.setEnabled_(playing)  # dimmed, not hidden, so the bar keeps its width
            button.setAlphaValue_(1 if playing else 0.3)
        if not playing:
            self.schedule_hide()

    def set_summary(self):
        """A summary is on its way: the spinner until its first audio, and ✦ marked until it ends."""
        self.cancel_hide()
        self.set_playing(True)
        self.set_loading(True)
        self._highlight(True)

    def _highlight(self, on):
        self.ai_btn.layer().setBackgroundColor_(ui.cg(AppKit.NSColor.colorWithWhite_alpha_(1, 0.14 if on else 0)))

    def set_summarize_progress(self, fraction):
        """0..1 while the model downloads, None after."""
        self.ai_btn.setHidden_(fraction is not None)
        self.ai_progress.setHidden_(fraction is None)
        self.ai_progress.setDoubleValue_(fraction or 0)

    def _summarize(self):
        self.cancel_hide()
        self.on_summarize(self.text, self._lang)
        if not self.playing:  # nothing started, such as a cancelled download
            self.schedule_hide()

    def set_caption(self, text):
        if self.playing:
            screen = self.win.screen() or AppKit.NSScreen.mainScreen()
            self.caption.show(text, self.win.frame(), screen.visibleFrame())

    def set_caption_paused(self, paused):
        self.caption.set_paused(paused)

    def configure_captions(self, font_size, background, background_opacity):
        self.caption.configure(font_size, background, background_opacity)

    def set_speed(self, speed):
        self._speed = speed
        _set_title(self.speed_btn, settings.speed_label(speed))

    def set_source(self, name):
        self._source = name
        _set_title(self.source_btn, name, ui.source_icon(name))

    def schedule_hide(self):
        self.cancel_hide()
        if not (self.playing or self.menu_open) and self.visible:  # a hidden popup must not stop reads
            self._hide_timer = ui.timer(IDLE_HIDE_S, self.hide)

    def cancel_hide(self):
        if self._hide_timer:
            self._hide_timer.invalidate()
            self._hide_timer = None

    def play(self):
        """Starts reading the shown text, as ▶ does."""
        if not self.playing:
            self._toggle()

    def _toggle(self):
        if not self.playing:
            self.cancel_hide()
            self.set_playing(True)
            self.set_loading(True)
            self.on_play(self.text, self._lang)
        elif self.paused:
            self.on_resume()
            self.set_playing(True)
        else:
            self.on_pause()
            self.set_playing(True, paused=True)

    def _open_settings(self):
        if self.playing and not self.paused:
            self._toggle()
        self.on_settings()

    def _stop(self):
        self.on_stop()
        self.set_playing(False)

    def _popup(self, button, choices, current, pick):
        """choices: [(value, title)] or [(value, title, image)], None for a separator. Blocks while the menu
        is open; timers keep running."""
        menu = AppKit.NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for choice in choices:
            if choice is None:
                menu.addItem_(AppKit.NSMenuItem.separatorItem())
                continue
            value, title, *image = choice
            item = menu.addItemWithTitle_action_keyEquivalent_(title, "run:", "")
            item.setTarget_(ui.target(lambda _s, value=value: pick(value)))
            item.setState_(1 if value == current else 0)
            if image:
                item.setImage_(image[0])
        self.menu_open = True
        self.cancel_hide()
        try:
            menu.popUpMenuPositioningItem_atLocation_inView_(None, (0, button.bounds().size.height + 4), button)
        finally:
            self.menu_open = False
            self.schedule_hide()

    def _lang_menu(self, button):
        self._popup(button, [(None, "Auto")] + [(t, v[0]) for t, v in lang.LANGS.items()], self._lang,
                    self._lang_changed)

    def _speed_menu(self, button):
        self._popup(button, [(s, settings.speed_label(s)) for s in settings.SPEED_PRESETS], self._speed,
                    self._speed_changed)

    def _source_menu(self, button):
        """Ready sources to pick from; below them, each source that needs an install or sign-in offers it."""
        choices = self.sources()
        ready = [(n, n, ui.source_icon(n)) for n, fix in choices if not fix]
        broken = [(n, f"{n}: {fix}", ui.source_icon(n)) for n, fix in choices if fix]
        self._popup(button, ready + ([None] if ready and broken else []) + broken, self._source, self.on_source)

    def _set_lang(self, tag):
        self._lang = tag
        _set_title(self.lang_btn, lang.name(tag) or "Auto")

    def _lang_changed(self, tag):
        self._set_lang(tag)
        self.on_lang(tag)

    def _speed_changed(self, speed):
        self.set_speed(speed)
        self.on_speed(speed)
