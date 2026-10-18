"""Renamed builds move the old app's folders on first start."""
import os
import sys
import tempfile
import unittest

from harness_discussion import settings


class RenameMigration(unittest.TestCase):
    """Select to TTS became Codex Speak, then Harness Discussion. Old folders and sign-in tasks move on first start."""

    def dirs(self, d):
        old, new = os.path.join(d, "select-to-tts"), os.path.join(d, "harness-discussion")
        os.makedirs(old)
        with open(os.path.join(old, "settings.json"), "w") as f:
            f.write('{"speed": 1.5}')
        return old, new, [(old, new, ("settings.json",))]

    def test_old_folder_moves(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            settings.migrate(dirs)
            self.assertFalse(os.path.exists(old))
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)

    def test_missing_files_are_copied_into_an_existing_folder(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            os.makedirs(new)
            settings.migrate(dirs)
            self.assertTrue(os.path.exists(os.path.join(old, "settings.json")))
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)

    def test_moved_folder_marker_keeps_new_settings_when_old_folder_returns(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            settings.migrate(dirs)
            self.assertTrue(os.path.isfile(os.path.join(new, ".migrated")))
            settings.save({"speed": 0.75}, os.path.join(new, "settings.json"))
            self.dirs(d)  # a legacy build recreates its folder
            settings.migrate(dirs)
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 0.75)

    def test_marker_failure_copies_before_moving_and_keeps_new_settings(self):
        from unittest.mock import patch
        real_open = open
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)

            def fail_old_marker(path, *args, **kwargs):
                if path == os.path.join(old, ".migrated"):
                    raise PermissionError
                return real_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=fail_old_marker), \
                    patch.object(settings.os, "rename", wraps=settings.os.rename) as move:
                settings.migrate(dirs)
            move.assert_not_called()
            self.assertTrue(os.path.isfile(os.path.join(new, ".migrated")))
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)
            settings.save({"speed": 0.75}, os.path.join(new, "settings.json"))
            settings.save({"speed": 2.0}, os.path.join(old, "settings.json"))
            settings.migrate(dirs)
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 0.75)

    def test_settings_saved_after_a_finished_copy_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            os.makedirs(new)
            settings.migrate(dirs)
            settings.save({"speed": 0.75}, os.path.join(new, "settings.json"))
            settings.migrate(dirs)
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 0.75)

    def test_failed_copy_never_raises_and_its_defaults_are_replaced(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            with patch.object(settings.os, "rename", side_effect=PermissionError), \
                    patch.object(settings.shutil, "copy2", side_effect=PermissionError):
                settings.migrate(dirs)
            settings.save(dict(settings.DEFAULTS), os.path.join(new, "settings.json"))  # the app started anyway
            with patch.object(settings.os, "rename", side_effect=PermissionError):
                settings.migrate(dirs)
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)


    def codex_speak(self, d):
        old, new = os.path.join(d, "codex-speak"), os.path.join(d, "harness-discussion")
        os.makedirs(old)
        for name, text in (("settings.json", '{"speed": 1.5}'), ("codex-speak.log", "log"),
                           ("stt-connection.json", "token"), ("other.txt", "x")):
            with open(os.path.join(old, name), "w") as f:
                f.write(text)
        keep = next(k for o, n, k in settings.LEGACY_DIRS if o.endswith("codex-speak") and n == settings.DIR)
        return old, new, [(old, new, keep)]

    def test_legacy_dirs_include_codex_speak_once_per_data_folder(self):
        entries = [(o, n, k) for o, n, k in settings.LEGACY_DIRS if os.path.basename(o) == "codex-speak"]
        if settings.APPDATA == settings.LOCALAPPDATA:  # macOS: one folder, so one entry moves it whole
            expected = [(os.path.join(settings.APPDATA, "codex-speak"), settings.DIR,
                         ("settings.json", "codex-speak.log", "stt-connection.json"))]
        else:
            expected = [(os.path.join(settings.APPDATA, "codex-speak"), settings.DIR, ("settings.json", "codex-speak.log")),
                        (os.path.join(settings.LOCALAPPDATA, "codex-speak"), settings.LOCAL_DIR, ("stt-connection.json",))]
        self.assertEqual(entries, expected)
        # newest app first, so an older folder cannot take the new name before it
        self.assertEqual([os.path.basename(o) for o, n, k in settings.LEGACY_DIRS],
                         ["codex-speak"] * len(expected) + ["select-to-tts"] * 2)
        self.assertEqual(os.path.basename(settings.DIR), "harness-discussion")
        self.assertEqual(os.path.basename(settings.LOCAL_DIR), "harness-discussion")

    def test_codex_speak_folder_moves_whole(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.codex_speak(d)
            self.assertTrue(settings.migrate(dirs))
            self.assertFalse(os.path.exists(old))
            self.assertEqual(sorted(os.listdir(new)),
                             [".migrated", "codex-speak.log", "other.txt", "settings.json", "stt-connection.json"])
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)
            self.assertFalse(settings.migrate(dirs))  # nothing left to move

    def test_locked_codex_speak_folder_copies_its_keep_list(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.codex_speak(d)
            with patch.object(settings.os, "rename", side_effect=PermissionError):
                self.assertTrue(settings.migrate(dirs))
            self.assertEqual(sorted(os.listdir(new)), sorted([".migrated", *dirs[0][2]]))
            self.assertIn("codex-speak.log", dirs[0][2])
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)
            self.assertTrue(os.path.exists(os.path.join(old, "settings.json")))
            with patch.object(settings.os, "rename", side_effect=PermissionError):
                self.assertFalse(settings.migrate(dirs))  # the marker stops further copies

    def test_new_folder_with_marker_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.codex_speak(d)
            settings.save({"speed": 0.75}, os.path.join(new, "settings.json"))
            open(os.path.join(new, ".migrated"), "w").close()
            self.assertFalse(settings.migrate(dirs))
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 0.75)
            self.assertTrue(os.path.isdir(old))

    def test_codex_speak_wins_over_a_leftover_select_to_tts_folder(self):
        with tempfile.TemporaryDirectory() as d:
            # LEGACY_DIRS in its real order, with the data folders moved into the temp dir
            roots = {settings.APPDATA: os.path.join(d, "roaming"), settings.LOCALAPPDATA: os.path.join(d, "local")}
            moved = lambda p: os.path.join(roots[os.path.dirname(p)], os.path.basename(p))
            dirs = [(moved(o), moved(n), k) for o, n, k in settings.LEGACY_DIRS]
            for root in set(roots.values()):
                for app, speed, token in (("select-to-tts", 0.5, "old"), ("codex-speak", 1.5, "new")):
                    os.makedirs(os.path.join(root, app))
                    settings.save({"speed": speed}, os.path.join(root, app, "settings.json"))
                    with open(os.path.join(root, app, "stt-connection.json"), "w") as f:
                        f.write(token)
            self.assertTrue(settings.migrate(dirs))
            self.assertEqual(settings.load(os.path.join(moved(settings.DIR), "settings.json"))["speed"], 1.5)
            with open(os.path.join(moved(settings.LOCAL_DIR), "stt-connection.json")) as f:
                self.assertEqual(f.read(), "new")

    def test_nothing_to_migrate_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(settings.migrate([(os.path.join(d, "codex-speak"), os.path.join(d, "new"), ())]))


if __name__ == "__main__":
    unittest.main()
