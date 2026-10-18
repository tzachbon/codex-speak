"""The floating button bar next to a selection: a non-activating panel that never takes focus."""
import AppKit
import objc

from .. import lang, settings
from . import ui

IDLE_HIDE_S = 4.0


class _Panel(AppKit.NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


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


def _icon_button(name, description, fn):
    b = _Button.alloc().init()
    b.setBezelStyle_(AppKit.NSBezelStyleRegularSquare)
    b.setBordered_(False)
    b.setImage_(ui.symbol(name, description))
    b.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
    b.widthAnchor().constraintEqualToConstant_(28).setActive_(True)
    b.heightAnchor().constraintEqualToConstant_(26).setActive_(True)
    return ui.bind(b, lambda _s: fn())


def _text_button(title, fn):
    b = _Button.alloc().init()
    b.setBezelStyle_(AppKit.NSBezelStyleRegularSquare)
    b.setBordered_(False)
    b.setTitle_(title + " ▾")
    b.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    return ui.bind(b, lambda s: fn(s))


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
                 on_source, sources):
        """sources: returns the source names the menu offers; on_source(name) picks one."""
        self.on_play, self.on_stop, self.on_pause, self.on_resume = on_play, on_stop, on_pause, on_resume
        self.on_lang, self.on_speed, self.on_settings = on_lang, on_speed, on_settings
        self.on_source, self.sources = on_source, sources
        self.text, self.playing, self.paused, self.menu_open, self.loading = "", False, False, False, False
        self._lang, self._speed, self._source, self._hide_timer = None, speed, None, None

        self.btn = _icon_button("play.fill", "Play", self._toggle)
        self.stop_btn = _icon_button("stop.fill", "Stop", self._stop)
        self.spinner = AppKit.NSProgressIndicator.alloc().init()
        self.spinner.setStyle_(AppKit.NSProgressIndicatorStyleSpinning)
        self.spinner.setControlSize_(AppKit.NSControlSizeSmall)
        self.lang_btn = _text_button("Auto", self._lang_menu)
        self.speed_btn = _text_button(settings.speed_label(speed), self._speed_menu)
        self.source_btn = _text_button("", self._source_menu)
        settings_btn = _icon_button("gearshape", "Settings", self._open_settings)
        close_btn = _icon_button("xmark", "Close", self.close)
        divider = AppKit.NSBox.alloc().init()
        divider.setBoxType_(AppKit.NSBoxSeparator)
        row = ui.stack([self.btn, self.spinner, self.stop_btn, divider, self.lang_btn, self.speed_btn,
                        self.source_btn, settings_btn, close_btn], vertical=False, spacing=2)
        row.setEdgeInsets_((3, 6, 3, 6))
        self.spinner.setHidden_(True)
        self.stop_btn.setHidden_(True)

        effect = AppKit.NSVisualEffectView.alloc().init()
        effect.setMaterial_(AppKit.NSVisualEffectMaterialPopover)
        effect.setState_(AppKit.NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(8)
        effect.layer().setMasksToBounds_(True)
        hover = _Hover.alloc().initWithOwner_(self)
        for parent, child in ((hover, effect), (effect, row)):
            child.setTranslatesAutoresizingMaskIntoConstraints_(False)
            parent.addSubview_(child)
            for a, b in (("leadingAnchor", "leadingAnchor"), ("trailingAnchor", "trailingAnchor"),
                         ("topAnchor", "topAnchor"), ("bottomAnchor", "bottomAnchor")):
                getattr(child, a)().constraintEqualToAnchor_(getattr(parent, b)()).setActive_(True)

        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        p = self.win = _Panel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (10, 10)), style, AppKit.NSBackingStoreBuffered, False)
        p.setContentView_(hover)
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
            self.set_loading(False)
        pausing = playing and not paused
        self.btn.setImage_(ui.symbol("pause.fill" if pausing else "play.fill", "Pause" if pausing else "Play"))
        self.stop_btn.setHidden_(not playing)
        if not playing:
            self.schedule_hide()

    def set_caption(self, text):
        pass  # captions are Windows only for now

    def set_caption_paused(self, paused):
        pass

    def configure_captions(self, font_size, background, background_opacity):
        pass

    def set_speed(self, speed):
        self._speed = speed
        self.speed_btn.setTitle_(settings.speed_label(speed) + " ▾")

    def set_source(self, name):
        self._source = name
        self.source_btn.setTitle_(name + " ▾")
        if self.visible:  # names differ in width; show() sizes the panel otherwise
            self.win.setContentSize_(self.win.contentView().fittingSize())

    def schedule_hide(self):
        self.cancel_hide()
        if not (self.playing or self.menu_open) and self.visible:  # a hidden popup must not stop reads
            self._hide_timer = ui.timer(IDLE_HIDE_S, self.hide)

    def cancel_hide(self):
        if self._hide_timer:
            self._hide_timer.invalidate()
            self._hide_timer = None

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
        """choices: [(value, title)]. Blocks while the menu is open; timers keep running."""
        menu = AppKit.NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for value, title in choices:
            item = menu.addItemWithTitle_action_keyEquivalent_(title, "run:", "")
            item.setTarget_(ui.target(lambda _s, value=value: pick(value)))
            item.setState_(1 if value == current else 0)
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
        self._popup(button, [(n, n) for n in self.sources()], self._source, self.on_source)

    def _set_lang(self, tag):
        self._lang = tag
        self.lang_btn.setTitle_((lang.name(tag) or "Auto") + " ▾")

    def _lang_changed(self, tag):
        self._set_lang(tag)
        self.on_lang(tag)

    def _speed_changed(self, speed):
        self.set_speed(speed)
        self.on_speed(speed)
