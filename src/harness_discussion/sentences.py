"""Source-preserving sentence/paragraph reading units."""
import re

# shortcut: abbreviations can end a unit, upgrade only if real passages need grammar-aware splitting.
# A newline before a list number is a boundary, and the number's own dot is not.
_BOUNDARY = re.compile(r'''[.!?؟]+["'”’»\)\]\}]*?(?=\s|$)|\r?\n[\t ]*\r?\n|\r?\n(?=[\t ]*\d+[.)][\t ]+\S)''')
_PARAGRAPH = re.compile(r"\r?\n[\t ]*\r?\n")
_NUMBER = re.compile(r"\d+[.)]")


def split(text):
    units, start = [], 0
    for match in _BOUNDARY.finditer(text):
        if text[text.rfind("\n", 0, match.start()) + 1:match.start()].strip().isdigit():
            continue  # "2." opening a list item
        unit = text[start:match.end()].strip()
        if unit:
            units.append(unit)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units


def chunks(text, limit):
    """Paragraphs packed into pieces of at most `limit` characters; a longer paragraph is split at sentences."""
    pieces = []

    def pack(parts, joiner):
        for part in parts:
            if pieces and pieces[-1][1] == joiner and len(pieces[-1][0]) + len(joiner) + len(part) <= limit:
                pieces[-1][0] += joiner + part
            else:
                pieces.append([part, joiner])

    for paragraph in filter(None, (p.strip() for p in _PARAGRAPH.split(text))):
        pack([cut for unit in split(paragraph) for cut in _fit(unit, limit)] if len(paragraph) > limit else [paragraph],
             " " if len(paragraph) > limit else "\n\n")
    return [piece for piece, _ in pieces]


def _fit(unit, limit):
    """A unit longer than `limit` cut at spaces, or mid-word when one word is longer."""
    while len(unit) > limit:
        cut = unit.rfind(" ", 0, limit + 1)
        cut = cut if cut > 0 else limit
        yield unit[:cut]
        unit = unit[cut:].lstrip()
    if unit:
        yield unit


def at(text, pos):
    """The unit holding character `pos` of `text`; past the end, the last unit."""
    end, units = 0, split(text) or [text]
    for unit in units:
        end = text.find(unit, end) + len(unit)
        if pos < end:
            return unit
    return units[-1]


def current(text):
    """The sentence being spoken at the end of a growing transcript, with a list number kept on its item."""
    units = split(text)
    if len(units) > 1 and _NUMBER.fullmatch(units[-1]):
        return units[-2]  # the number joins its item once the next words arrive
    if len(units) > 1 and _NUMBER.fullmatch(units[-2]):
        return f"{units[-2]} {units[-1]}"
    return units[-1] if units else ""
