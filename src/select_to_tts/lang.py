"""Languages offered in the popup menu."""

# tag -> (menu label / name given to Codex, Edge voice, SAPI voice prefix)
LANGS = {
    "he-IL": ("Hebrew", "he-IL-AvriNeural", "Microsoft Asaf"),
    "en-US": ("English", "en-US-AvaMultilingualNeural", "Microsoft Zira"),
    "ar-SA": ("Arabic", "ar-SA-HamedNeural", None),
    "ru-RU": ("Russian", "ru-RU-DmitryNeural", None),
    "es-ES": ("Spanish", "es-ES-AlvaroNeural", None),
    "fr-FR": ("French", "fr-FR-DeniseNeural", None),
}


def name(tag: str | None) -> str | None:
    return LANGS[tag][0] if tag in LANGS else None


SCRIPTS = [("he-IL", 0x0590, 0x05FF), ("ar-SA", 0x0600, 0x06FF), ("ru-RU", 0x0400, 0x04FF)]


def detect(text: str) -> str:
    """Majority script wins. Latin and anything unknown fall back to English."""
    counts = {tag: sum(lo <= ord(c) <= hi for c in text) for tag, lo, hi in SCRIPTS}
    latin = sum(c.isascii() and c.isalpha() for c in text)
    tag, n = max(counts.items(), key=lambda kv: kv[1])
    return tag if n > latin else "en-US"
