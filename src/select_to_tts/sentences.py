"""Source-preserving sentence/paragraph reading units."""
import re

# shortcut: abbreviations can end a unit, upgrade only if real passages need grammar-aware splitting.
_BOUNDARY = re.compile(r'''[.!?؟]+["'”’»\)\]\}]*?(?=\s|$)|\r?\n[\t ]*\r?\n''')


def split(text):
    units, start = [], 0
    for match in _BOUNDARY.finditer(text):
        unit = text[start:match.end()].strip()
        if unit:
            units.append(unit)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units
