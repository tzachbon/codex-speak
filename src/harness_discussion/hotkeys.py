"""The read-selection shortcut, stored as a pynput hotkey string such as "<ctrl>+<alt>+r"."""
import sys

MODS = ("ctrl", "alt", "shift", "cmd")  # display order
KEYS = {*"abcdefghijklmnopqrstuvwxyz0123456789", *(f"f{n}" for n in range(1, 13))}
DEFAULT = "<cmd>+<alt>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"


def parse(spec):
    """(modifiers, key) for a valid shortcut with at least one modifier, else None."""
    if not isinstance(spec, str) or not spec:
        return None
    mods, keys = set(), []
    for part in spec.lower().split("+"):
        name = part[1:-1] if part.startswith("<") and part.endswith(">") else part
        if part == f"<{name}>" and name in MODS:
            mods.add(name)
        elif name in KEYS and (part == name) == (len(name) == 1):  # letters bare, function keys in <>
            keys.append(name)
        else:
            return None
    return (frozenset(mods), keys[0]) if mods and len(keys) == 1 else None


def spec(mods, key):
    """The stored string for modifiers and a key, or None when they don't make a valid shortcut."""
    key = key.lower()
    text = "+".join([f"<{m}>" for m in MODS if m in mods] + [key if len(key) == 1 else f"<{key}>"])
    return text if parse(text) else None


def label(text):
    parsed = parse(text)
    if not parsed:
        return "Off"
    mods, key = parsed
    if sys.platform == "darwin":
        return "".join({"ctrl": "⌃", "alt": "⌥", "shift": "⇧", "cmd": "⌘"}[m] for m in MODS if m in mods) + key.upper()
    return "+".join([{"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}[m] for m in MODS if m in mods]
                    + [key.upper()])
