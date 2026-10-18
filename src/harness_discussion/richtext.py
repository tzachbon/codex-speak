"""Turns chat markup and copied rich text into plain text that reads well aloud."""
import re
from html.parser import HTMLParser

_NUMBERED = re.compile(r"(?m)^\s*\d+[.)]\s")
_MARKUP = re.compile(r"\*\*|__|`+|^[ \t]*(?:#{1,6}|[-*•])[ \t]+", re.M)
_URL = re.compile(r"https?://(?:www\.)?([^/?#\s]+)\S*?(?=[.,;:!?)\]]*(?:\s|$))")
# two folders deep, or a file with an extension: "and/or" and "24/7" stay as written
_PATH = re.compile(r"(?<![\w/.])(?:[\w.-]+/){2,}([\w.-]+)|(?<![\w/.])[\w.-]+/([\w-]+\.\w{1,5})\b")
_HASH = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")


def has_numbers(text):
    """True when some line starts with a list number such as "2." or "2)"."""
    return bool(_NUMBERED.search(text))


def strip_markup(text):
    """Deletes markup characters only. Words, list numbers and punctuation stay."""
    return _MARKUP.sub("", text)


def speakable(text):
    """Links read as their site, paths as their file name, and commit hashes are dropped."""
    text = _URL.sub(r"\1", text)
    text = _PATH.sub(lambda m: (m[1] or m[2]).replace("_", " "), text)
    text = _HASH.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"[ \t]*\(\s*\)", "", text))


class _Text(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "ol", "ul", "tr", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.lists, self.skip = [], [], 0  # lists: [next number, step] per open list, None for <ul>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "ol":
            attrs = dict(attrs)
            start, down = attrs.get("start") or "", "reversed" in attrs
            # ponytail: a reversed list without start would need its item count first, so it reads unnumbered
            self.lists.append([int(start), -1 if down else 1] if start.isdigit() else None if down else [1, 1])
        elif tag == "ul":
            self.lists.append(None)
        if tag in self.BLOCKS:
            self.out.append("\n")
        if tag == "li" and self.lists and self.lists[-1] is not None:
            self.out.append(f"{self.lists[-1][0]}. ")
            self.lists[-1][0] += self.lists[-1][1]

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(self.skip - 1, 0)
        elif tag in ("ol", "ul") and self.lists:
            self.lists.pop()
        if tag in self.BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    """Ordered lists keep their numbers, which the selected text of web pages often drops."""
    fragment = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", html, re.S)  # Windows CF_HTML
    parser = _Text()
    parser.feed(fragment[1] if fragment else html)
    parser.close()
    return re.sub(r"[ \t]*\n\s*", "\n", "".join(parser.out)).strip()
