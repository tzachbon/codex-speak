"""Small AppKit helpers: Python callables as button targets, labels, stacks and windows."""
import AppKit
import objc
from Foundation import NSObject

_keep = []  # AppKit holds targets weakly


class _Action(NSObject):
    def initWithFn_(self, fn):
        self = objc.super(_Action, self).init()
        if self is not None:
            self.fn = fn
        return self

    def run_(self, sender):
        self.fn(sender)


def target(fn):
    """An object whose `run:` selector calls fn(sender)."""
    t = _Action.alloc().initWithFn_(fn)
    _keep.append(t)
    return t


def bind(control, fn):
    control.setTarget_(target(fn))
    control.setAction_("run:")
    return control


def label(text, size=13, bold=False, secondary=False, width=None):
    field = AppKit.NSTextField.wrappingLabelWithString_(text) if width else AppKit.NSTextField.labelWithString_(text)
    font = AppKit.NSFont.boldSystemFontOfSize_(size) if bold else AppKit.NSFont.systemFontOfSize_(size)
    field.setFont_(font)
    if secondary:
        field.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    if width:
        field.setPreferredMaxLayoutWidth_(width)
        field.widthAnchor().constraintEqualToConstant_(width).setActive_(True)
    return field


def button(title, fn, primary=False):
    b = bind(AppKit.NSButton.buttonWithTitle_target_action_(title, None, None), lambda _s: fn())
    if primary:
        b.setKeyEquivalent_("\r")
    return b


def checkbox(title, value, fn):
    b = bind(AppKit.NSButton.checkboxWithTitle_target_action_(title, None, None),
             lambda s: fn(bool(s.state())))
    b.setState_(1 if value else 0)
    return b


def stack(views, vertical=True, spacing=8, inset=0):
    s = AppKit.NSStackView.stackViewWithViews_(views)
    s.setOrientation_(AppKit.NSUserInterfaceLayoutOrientationVertical if vertical
                      else AppKit.NSUserInterfaceLayoutOrientationHorizontal)
    s.setAlignment_(AppKit.NSLayoutAttributeLeading if vertical else AppKit.NSLayoutAttributeCenterY)
    s.setSpacing_(spacing)
    if inset:
        s.setEdgeInsets_((inset, inset, inset, inset))
    return s


def window(title, content):
    style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable)
    w = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), (100, 100)), style, AppKit.NSBackingStoreBuffered, False)
    w.setTitle_(title)
    w.setReleasedWhenClosed_(False)
    w.setContentView_(content)
    w.setContentSize_(content.fittingSize())
    w.center()
    return w


def show(w):
    AppKit.NSApp.activateIgnoringOtherApps_(True)
    w.makeKeyAndOrderFront_(None)


def timer(seconds, fn, repeats=False):
    """Main-thread timer. Common modes keep it firing while a menu is open."""
    t = AppKit.NSTimer.timerWithTimeInterval_repeats_block_(seconds, repeats, lambda _t: fn())
    AppKit.NSRunLoop.mainRunLoop().addTimer_forMode_(t, AppKit.NSRunLoopCommonModes)
    return t


def symbol(name, description=""):
    return AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, description)
