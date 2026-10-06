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
