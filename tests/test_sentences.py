"""Reading units: list numbers, the pieces Codex reads, and the caption's current sentence."""
import unittest

from codex_speak import sentences


def letters(text):
    return "".join(c for c in text if not c.isspace())


class Split(unittest.TestCase):
    def test_list_numbers_stay_on_their_items(self):
        source = "Please:\n1. Click it. Then wait.\n2. Read some text.\n10) Last one"
        self.assertEqual(sentences.split(source),
                         ["Please:", "1. Click it.", "Then wait.", "2. Read some text.", "10) Last one"])

    def test_a_line_that_ends_in_a_year_still_ends_the_unit(self):
        self.assertEqual(sentences.split("Shipped in 2026.\nNext"), ["Shipped in 2026.", "Next"])


class Chunks(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        text = "First one. Second one.\n\nNew paragraph."
        self.assertEqual(sentences.chunks(text, 100), [text])

    def test_paragraphs_pack_up_to_the_limit(self):
        paras = ["A" * 40 + ".", "B" * 40 + ".", "C" * 40 + "."]
        self.assertEqual(sentences.chunks("\n\n".join(paras), 90),
                         [paras[0] + "\n\n" + paras[1], paras[2]])

    def test_a_long_paragraph_splits_at_sentences(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(10))
        pieces = sentences.chunks(text, 60)
        self.assertTrue(all(len(p) <= 60 for p in pieces))
        self.assertEqual(letters("".join(pieces)), letters(text))

    def test_nothing_is_lost_or_reordered(self):
        text = "One.\n\n" + "Two is long. " * 20 + "\n\nThree."
        self.assertEqual(letters("".join(sentences.chunks(text, 50))), letters(text))
        self.assertEqual(sentences.chunks(" \n\n ", 50), [])


class Current(unittest.TestCase):
    def test_follows_the_end_of_the_transcript(self):
        cases = [
            ("", ""),
            ("Dirty audio", "Dirty audio"),
            ("First one. Sec", "Sec"),
            ("First one.", "First one."),
            ("Do this: 1. Click it. 2.", "Click it."),
            ("Do this: 1. Click it. 2. Read", "2. Read"),
            ("Plain sentence. Next", "Next"),
        ]
        for transcript, expected in cases:
            with self.subTest(transcript=transcript):
                self.assertEqual(sentences.current(transcript), expected)


if __name__ == "__main__":
    unittest.main()
