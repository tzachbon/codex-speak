"""Read-aloud prompts and the JSON envelope the Codex voice reads from. No network."""
import json
import unittest

from harness_discussion import codex_rt, prompts


class PromptsTest(unittest.TestCase):
    def test_prompts_format_with_their_json_braces(self):
        for prompt in (prompts.PROMPT, prompts.CUE_PROMPT):
            out = prompt.format(lang="Hebrew")
            self.assertIn('{"response_text"', out)
            self.assertIn("Hebrew", out)

    def test_envelope_round_trips_and_keeps_hebrew_readable(self):
        text = 'שלום "world"\nline two'
        out = prompts.envelope(text)
        self.assertEqual(json.loads(out), {"response_text": text, "require_repeat_verbatim": True})
        self.assertIn("שלום", out)

    def test_every_envelope_fits_one_appended_item(self):
        text = ('He said "stop" \\ then left.\n' * 20 + "Plain sentence here. " * 40).strip()
        pieces = codex_rt._pieces(text)
        self.assertTrue(all(len(prompts.envelope(p)) <= codex_rt.ITEM_CHARS for p in pieces))
        self.assertEqual(" ".join(" ".join(pieces).split()), " ".join(text.split()))


if __name__ == "__main__":
    unittest.main()
