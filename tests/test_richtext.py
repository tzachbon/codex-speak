"""Markup stripping, speakable tokens, and rich-text list numbers."""
import unittest

from codex_speak import richtext


class StripMarkup(unittest.TestCase):
    def test_removes_markup_and_keeps_words(self):
        cases = [
            ("**Dirty audio** (`67aa9fd`):", "Dirty audio (67aa9fd):"),
            ("- Cushion: waits.", "Cushion: waits."),
            ("  * nested item", "nested item"),
            ("• bullet", "bullet"),
            ("## Code map", "Code map"),
            ("1. Click", "1. Click"),
            ("a - b and 2 * 3", "a - b and 2 * 3"),
            ("snake_case stays", "snake_case stays"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(richtext.strip_markup(source), expected)

    def test_has_numbers(self):
        self.assertTrue(richtext.has_numbers("Please:\n2. Read"))
        self.assertTrue(richtext.has_numbers("1) First"))
        self.assertFalse(richtext.has_numbers("v1.2 now"))
        self.assertFalse(richtext.has_numbers("Please:\nRead"))


class Speakable(unittest.TestCase):
    def test_shortens_links_paths_and_hashes(self):
        cases = [
            ("See https://github.com/tzachbon/codex-speak/pull/11 now.", "See github.com now."),
            ("Pushed to https://www.example.com/a.", "Pushed to example.com."),
            ("Open https://example.com?token=abc now.", "Open example.com now."),
            ("Open https://example.com#top now.", "Open example.com now."),
            ("Open packaging/setup_signing_mac.sh and check.", "Open setup signing mac.sh and check."),
            ("See src/codex_speak/audio.py for it.", "See audio.py for it."),
            ("Dirty audio (67aa9fd): gaps.", "Dirty audio: gaps."),
            ("Commit 0025d63 handles it.", "Commit handles it."),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(richtext.speakable(source), expected)

    def test_leaves_ordinary_text_alone(self):
        for text in ("and/or 24/7 km/h", "Read 156 tests in 2026.", "deadline facade", "e.g. this."):
            with self.subTest(text=text):
                self.assertEqual(richtext.speakable(text), text)


class HtmlToText(unittest.TestCase):
    def test_ordered_lists_keep_their_numbers(self):
        cases = [
            ("<p>Please:</p><ol><li>A</li><li>B</li></ol>", "Please:\n1. A\n2. B"),
            ('<ol start="3"><li>C</li><li>D</li></ol>', "3. C\n4. D"),
            ('<ol reversed start="3"><li>C</li><li>D</li></ol>', "3. C\n2. D"),
            ('<ol reversed><li>C</li></ol>', "C"),
            ("<ul><li>x<ol><li>y</li></ol></li><li>z</li></ul>", "x\n1. y\nz"),
            ("<p>a &amp; b</p><script>alert(1)</script>", "a & b"),
            ("<ol><li><b>Bold</b> item</li></ol>", "1. Bold item"),
        ]
        for html, expected in cases:
            with self.subTest(html=html):
                self.assertEqual(richtext.html_to_text(html), expected)

    def test_windows_clipboard_html_uses_only_the_fragment(self):
        cf_html = ("Version:0.9\r\nStartHTML:0\r\n<html><body>outside<!--StartFragment-->"
                   "<ol><li>A</li></ol><!--EndFragment-->after</body></html>")
        self.assertEqual(richtext.html_to_text(cf_html), "1. A")


if __name__ == "__main__":
    unittest.main()
