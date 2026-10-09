"""One non-activating, per-pixel-alpha caption owned by the playback popup."""
import ctypes
import time
import tkinter as tk
import unicodedata
from ctypes import wintypes as wt

from PIL import Image, ImageChops, ImageDraw, ImageFilter


class _BitmapHeader(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG),
                ("planes", wt.WORD), ("bits", wt.WORD), ("compression", wt.DWORD),
                ("image_size", wt.DWORD), ("xppm", wt.LONG), ("yppm", wt.LONG),
                ("used", wt.DWORD), ("important", wt.DWORD)]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("header", _BitmapHeader), ("colors", wt.DWORD * 3)]


class _Size(ctypes.Structure):
    _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]


class _Blend(ctypes.Structure):
    _fields_ = [("operation", wt.BYTE), ("flags", wt.BYTE),
                ("constant_alpha", wt.BYTE), ("alpha_format", wt.BYTE)]


u32, g32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("gdi32", use_last_error=True)


def _bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, args
    return function


# Handles and LONG_PTR must stay pointer-sized on 64-bit Windows.
_get_parent = _bind(u32, "GetParent", wt.HWND, wt.HWND)
_get_style = _bind(u32, "GetWindowLongPtrW", ctypes.c_ssize_t, wt.HWND, ctypes.c_int)
_set_style = _bind(u32, "SetWindowLongPtrW", ctypes.c_ssize_t, wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
_get_dpi = _bind(u32, "GetDpiForWindow", wt.UINT, wt.HWND)
_position = _bind(u32, "SetWindowPos", wt.BOOL, wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                  ctypes.c_int, ctypes.c_int, wt.UINT)
_update = _bind(u32, "UpdateLayeredWindow", wt.BOOL, wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT),
                ctypes.POINTER(_Size), wt.HDC, ctypes.POINTER(wt.POINT), wt.DWORD,
                ctypes.POINTER(_Blend), wt.DWORD)
_create_dc = _bind(g32, "CreateCompatibleDC", wt.HDC, wt.HDC)
_delete_dc = _bind(g32, "DeleteDC", wt.BOOL, wt.HDC)
_create_bitmap = _bind(g32, "CreateDIBSection", wt.HBITMAP, wt.HDC, ctypes.POINTER(_BitmapInfo),
                       wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD)
_select = _bind(g32, "SelectObject", wt.HANDLE, wt.HDC, wt.HANDLE)
_delete = _bind(g32, "DeleteObject", wt.BOOL, wt.HANDLE)
_create_font = _bind(g32, "CreateFontW", wt.HFONT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     ctypes.c_int, ctypes.c_int, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                     wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR)
_bk_mode = _bind(g32, "SetBkMode", ctypes.c_int, wt.HDC, ctypes.c_int)
_text_color = _bind(g32, "SetTextColor", wt.DWORD, wt.HDC, wt.DWORD)
_draw_text = _bind(u32, "DrawTextW", ctypes.c_int, wt.HDC, wt.LPCWSTR, ctypes.c_int,
                   ctypes.POINTER(wt.RECT), wt.UINT)


def reading_rtl(text):
    """Use the paragraph's first strong character, leaving bidi shaping to Windows."""
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in ("L", "R", "AL"):
            return direction != "L"
    return False


class GdiLine:
    """Bounded Unicode glyph raster and its native drawing resources."""

    def __init__(self, text, family, pixel_size, width, height):
        self.text, self.width, self.height = text, width, height
        self.dc = self.bitmap = self.font = self.old_bitmap = self.old_font = None
        self.bits = ctypes.c_void_p()
        self.flags = 0x20 | 0x800 | (0x20000 if reading_rtl(text) else 0)  # single line, no prefix
        try:
            self.dc = _create_dc(None)
            if not self.dc:
                raise ctypes.WinError(ctypes.get_last_error())
            info = _BitmapInfo(header=_BitmapHeader(size=ctypes.sizeof(_BitmapHeader), width=width,
                                                    height=-height, planes=1, bits=32))
            self.bitmap = _create_bitmap(self.dc, ctypes.byref(info), 0, ctypes.byref(self.bits), None, 0)
            self.font = _create_font(-pixel_size, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, family)
            if not self.bitmap or not self.font:
                raise ctypes.WinError(ctypes.get_last_error())
            self.old_bitmap = _select(self.dc, self.bitmap)
            self.old_font = _select(self.dc, self.font)
            if self.old_bitmap in (None, ctypes.c_void_p(-1).value) or self.old_font in (None, ctypes.c_void_p(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
            _bk_mode(self.dc, 1)
            _text_color(self.dc, 0xFFFFFF)
            rect = wt.RECT()
            _draw_text(self.dc, text, -1, ctypes.byref(rect), self.flags | 0x400)
            self.text_width, self.text_height = rect.right, rect.bottom
        except Exception:
            self.close()
            raise

    def mask(self, offset):
        ctypes.memset(self.bits, 0, self.width * self.height * 4)
        left = round((self.width - self.text_width) / 2) if self.text_width <= self.width else -round(offset)
        top = max(0, (self.height - self.text_height) // 2)
        rect = wt.RECT(left, top, left + self.text_width, top + self.text_height)
        _draw_text(self.dc, self.text, -1, ctypes.byref(rect), self.flags)
        return Image.frombytes("RGB", (self.width, self.height),
                               ctypes.string_at(self.bits, self.width * self.height * 4),
                               "raw", "BGRX").getchannel("R")

    def close(self):
        if self.dc:
            if self.old_font and self.old_font != ctypes.c_void_p(-1).value:
                _select(self.dc, self.old_font)
            if self.old_bitmap and self.old_bitmap != ctypes.c_void_p(-1).value:
                _select(self.dc, self.old_bitmap)
        if self.font:
            _delete(self.font)
        if self.bitmap:
            _delete(self.bitmap)
        if self.dc:
            _delete_dc(self.dc)
        self.dc = self.bitmap = self.font = self.old_bitmap = self.old_font = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def compose_caption(mask, background, background_opacity):
    """Fade glyphs at both edges, keeping optional backdrop opacity independent."""
    width, height = mask.size
    edge = max(1, round(width * 0.12))
    ramp = Image.new("L", (width, 1))
    ramp.putdata([round(255 * min(1, x / edge, (width - 1 - x) / edge)) for x in range(width)])
    fade = ramp.resize(mask.size)
    stroke_mask = ImageChops.multiply(mask.filter(ImageFilter.MaxFilter(3)), fade)
    mask = ImageChops.multiply(mask, fade)
    result = Image.new("RGBA", mask.size)
    if background:
        ImageDraw.Draw(result).rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 3,
                                                 fill=(24, 24, 24, round(255 * background_opacity)))
    outline = Image.new("RGBA", mask.size, (20, 20, 20))
    outline.putalpha(stroke_mask)
    result = Image.alpha_composite(result, outline)
    ink = Image.new("RGBA", mask.size, (249, 249, 249))
    ink.putalpha(mask)
    return Image.alpha_composite(result, ink)
def caption_layout(bar, area, width, height, gap):
    """Keep the caption above its controls, including on negative-coordinate monitors."""
    x, y, bw, bh = bar
    left, top, right, bottom = area
    width, bw = min(width, right - left), min(bw, right - left)
    x = max(left, min(x, right - bw))
    y = max(top + height + gap, min(y, bottom - bh))
    cx = max(left, min(x + (bw - width) // 2, right - width))
    return (x, y, bw, bh), (cx, y - gap - height, width, height)


class CaptionSurface:
    """Tk owns window/timers. GDI supplies shaping, ULW supplies actual transparency."""

    def __init__(self, parent, family, placement):
        self.parent, self.family, self.placement = parent, family, placement
        self.text, self.paused, self.offset, self._job, self._line = "", False, 0.0, None, None
        self.font_size, self.background, self.background_opacity = 10, False, 0.6
        self.bounds, self._key, self._last_tick = None, None, None
        self.win = tk.Toplevel(parent)
        self.win.overrideredirect(True)
        self.win.withdraw()
        self.win.update_idletasks()
        self.hwnd = _get_parent(self.win.winfo_id())
        _set_style(self.hwnd, -20, _get_style(self.hwnd, -20)
                   | 0x08000000 | 0x80 | 0x8 | 0x80000 | 0x20)
        parent.bind("<Configure>", self._parent_changed, add="+")
        parent.bind("<Destroy>", self._parent_destroyed, add="+")

    def show_text(self, text):
        self._cancel()
        self.text = " ".join(text.split())
        self.offset, self._last_tick, self._key = 0.0, None, None
        if self.text:
            self._redraw()
            self._schedule()
        else:
            self.hide()

    def set_paused(self, paused):
        self.paused = paused
        self._cancel()
        self._last_tick = None
        if not paused:
            self._schedule()

    def configure(self, font_size, background, background_opacity):
        self.font_size, self.background, self.background_opacity = font_size, background, background_opacity
        if self.text:
            self._redraw()
            self._schedule()

    def hide(self):
        self._cancel()
        self.text, self.offset, self.bounds, self._last_tick = "", 0.0, None, None
        self.win.withdraw()
        if self._line:
            self._line.close()
            self._line = None
        self._key = None

    def close(self):
        if self.win.winfo_exists():
            self.hide()
            self.win.destroy()

    def _parent_changed(self, event):
        if event.widget == self.parent and self.text:
            self._redraw()

    def _parent_destroyed(self, event):
        if event.widget == self.parent:
            self._cancel()
            if self._line:
                self._line.close()
                self._line = None

    def _redraw(self):
        try:
            self._draw()
        except (OSError, ValueError, tk.TclError):
            self.hide()  # a failed caption must not stop speech or leave a topmost orphan

    def _draw(self):
        bar, area = self.placement()
        parent_hwnd = _get_parent(self.parent.winfo_id())
        dpi = _get_dpi(parent_hwnd) or 96
        scale = dpi / 96
        pixel_size = max(1, round(self.font_size * dpi / 72))
        height = round(pixel_size * 1.5) + round(4 * scale)
        bar, self.bounds = caption_layout(bar, area, round(340 * scale), height, round(10 * scale))
        x, y, width, height = self.bounds
        key = self.text, pixel_size, width, height
        if self._key != key:
            if self._line:
                self._line.close()
                self._line = None
            self._line = GdiLine(self.text, self.family, pixel_size, width, height)
            if self._key is None and reading_rtl(self.text):
                self.offset = max(0, self._line.text_width - width)
            self._key = key
        self.offset = max(0, min(self.offset, max(0, self._line.text_width - width)))
        image = compose_caption(self._line.mask(self.offset), self.background, self.background_opacity)
        alpha = image.getchannel("A")
        image = Image.merge("RGBA", tuple(ImageChops.multiply(image.getchannel(c), alpha) for c in "RGB")
                            + (alpha,))
        data = image.tobytes("raw", "BGRA")
        ctypes.memmove(self._line.bits, data, len(data))
        destination, size, origin, blend = wt.POINT(x, y), _Size(width, height), wt.POINT(), _Blend(0, 0, 255, 1)
        if not _update(self.hwnd, None, ctypes.byref(destination), ctypes.byref(size), self._line.dc,
                       ctypes.byref(origin), 0, ctypes.byref(blend), 2):
            raise ctypes.WinError(ctypes.get_last_error())
        bx, by, bw, bh = bar
        _position(parent_hwnd, None, bx, by, bw, bh, 0x4 | 0x10)
        self.win.deiconify()
        _position(self.hwnd, wt.HWND(-1), x, y, width, height, 0x10 | 0x40)

    def _schedule(self):
        if self.text and not self.paused and self._line and self._line.text_width > self._line.width:
            if self._job is None:
                self._last_tick = time.monotonic()
                self._job = self.parent.after(40, self._tick)

    def _tick(self):
        self._job = None
        now = time.monotonic()
        distance = 18 * ((_get_dpi(self.hwnd) or 96) / 96) * (now - self._last_tick)
        self.offset += -distance if reading_rtl(self.text) else distance
        self._redraw()
        if self._line:
            end = 0 if reading_rtl(self.text) else self._line.text_width - self._line.width
            if self.offset != end:
                self._schedule()

    def _cancel(self):
        if self._job:
            self.parent.after_cancel(self._job)
            self._job = None
