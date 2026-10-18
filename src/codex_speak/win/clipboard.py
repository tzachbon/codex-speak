"""Snapshot and restore the whole clipboard, so a borrowed Ctrl+C leaves no trace."""
import ctypes
import time
from ctypes import c_size_t, c_uint, c_void_p

u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
u32.GetClipboardData.restype = k32.GlobalLock.restype = k32.GlobalAlloc.restype = c_void_p
u32.GetClipboardData.argtypes, u32.SetClipboardData.argtypes = [c_uint], [c_uint, c_void_p]
k32.GlobalLock.argtypes = k32.GlobalUnlock.argtypes = k32.GlobalSize.argtypes = [c_void_p]
k32.GlobalSize.restype, k32.GlobalAlloc.argtypes = c_size_t, [c_uint, c_size_t]

BITMAP, DIB, DIBV5 = 2, 8, 17
METAFILES = {3, 14}  # CF_METAFILEPICT, CF_ENHMETAFILE: GDI handles, not byte-copyable
SKIP = {BITMAP, 9, 0x80, 0x82, 0x83, 0x8E}  # synthesized or GDI-handle formats we don't copy


def safe_to_borrow(formats: set[int]) -> bool:
    """True when snapshot() can capture everything the clipboard holds."""
    if formats & METAFILES:
        return False
    return BITMAP not in formats or bool(formats & {DIB, DIBV5})


class _Open:
    def __enter__(self):
        for _ in range(20):  # another app may hold it briefly
            if u32.OpenClipboard(None):
                return self
            time.sleep(0.01)
        raise OSError("clipboard busy")

    def __exit__(self, *exc):
        u32.CloseClipboard()


def formats() -> set[int]:
    with _Open():
        found, fmt = set(), 0
        while fmt := u32.EnumClipboardFormats(fmt):
            found.add(fmt)
        return found


def sequence() -> int:
    return u32.GetClipboardSequenceNumber()


def snapshot() -> list[tuple[int, bytes]]:
    with _Open():
        saved, fmt = [], 0
        while fmt := u32.EnumClipboardFormats(fmt):
            h = None if fmt in SKIP else u32.GetClipboardData(fmt)
            if h and (p := k32.GlobalLock(h)):
                saved.append((fmt, ctypes.string_at(p, k32.GlobalSize(h))))
                k32.GlobalUnlock(h)
        return saved


def restore(saved: list[tuple[int, bytes]]) -> None:
    with _Open():
        u32.EmptyClipboard()
        for fmt, data in saved:
            h = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE, owned by the clipboard after Set
            ctypes.memmove(k32.GlobalLock(h), data, len(data))
            k32.GlobalUnlock(h)
            u32.SetClipboardData(fmt, h)


def text() -> str:
    with _Open():
        h = u32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h or not (p := k32.GlobalLock(h)):
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
