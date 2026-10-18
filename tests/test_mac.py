import os
import plistlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

if sys.platform != "darwin":
    raise unittest.SkipTest("macOS only")

from codex_speak import codex_rt  # noqa: E402
from codex_speak.mac import pasteboard, permission, selection, startup, voice  # noqa: E402


class AvRateTest(unittest.TestCase):
    def test_normal_speed_is_default_rate(self):
        self.assertAlmostEqual(voice.av_rate(1.0), voice.AVSpeechUtteranceDefaultSpeechRate)

    def test_rates_stay_in_range_and_increase(self):
        rates = [voice.av_rate(s) for s in (0.5, 0.75, 1.0, 1.5, 2.0)]
        self.assertEqual(rates, sorted(rates))
        self.assertGreaterEqual(rates[0], voice.AVSpeechUtteranceMinimumSpeechRate)
        self.assertLessEqual(rates[-1], voice.AVSpeechUtteranceMaximumSpeechRate)


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = mock.patch.dict(os.environ, {"HOME": self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enable_writes_open_command_and_disable_removes_it(self):
        self.assertFalse(startup.enabled())
        startup.set_enabled(True, "/Applications/Codex Speak.app")
        with open(startup.plist_path(), "rb") as f:
            data = plistlib.load(f)
        self.assertEqual(data["Label"], startup.LABEL)
        self.assertEqual(data["ProgramArguments"], ["/usr/bin/open", "-a", "/Applications/Codex Speak.app"])
        self.assertTrue(data["RunAtLoad"])
        startup.set_enabled(False)
        self.assertFalse(startup.enabled())
        startup.set_enabled(False)  # already off

    def test_source_run_cannot_enable(self):
        with mock.patch.object(startup, "bundle_path", return_value=None):
            self.assertRaises(OSError, startup.set_enabled, True)

    def test_refresh_follows_a_moved_app_only_when_enabled(self):
        startup.refresh("/Applications/New.app")
        self.assertFalse(startup.enabled())
        startup.set_enabled(True, "/Users/me/Downloads/Codex Speak.app")
        startup.refresh("/Applications/Codex Speak.app")
        with open(startup.plist_path(), "rb") as f:
            self.assertEqual(plistlib.load(f)["ProgramArguments"][-1], "/Applications/Codex Speak.app")


class PermissionTest(unittest.TestCase):
    def test_stale_only_when_another_build_was_granted(self):
        self.assertTrue(permission.is_stale("0.1.0+abc", "0.1.1+def"))
        self.assertFalse(permission.is_stale("0.1.1+def", "0.1.1+def"))
        self.assertFalse(permission.is_stale(None, "0.1.1+def"))  # never granted
        self.assertFalse(permission.is_stale("0.1.0+abc", None))  # source run has no build key

    def test_reset_uses_fixed_arguments(self):
        with mock.patch.object(permission.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(permission.reset_grant())
        self.assertEqual(run.call_args.args[0], ["/usr/bin/tccutil", "reset", "Accessibility", startup.LABEL])


class PasteboardTest(unittest.TestCase):
    def test_secrets_and_promises_are_never_borrowed(self):
        self.assertTrue(pasteboard.safe_to_borrow({"public.utf8-plain-text"}))
        self.assertTrue(pasteboard.safe_to_borrow(set()))
        self.assertFalse(pasteboard.safe_to_borrow({"public.utf8-plain-text", "org.nspasteboard.ConcealedType"}))
        self.assertFalse(pasteboard.safe_to_borrow({"com.agilebits.onepassword"}))
        self.assertFalse(pasteboard.safe_to_borrow({"com.apple.pasteboard.promised-file-url"}))

    def test_overlapping_reads_borrow_the_pasteboard_one_at_a_time(self):
        state = {"inside": 0, "most": 0}

        def borrow():
            state["inside"] += 1
            state["most"] = max(state["most"], state["inside"])
            time.sleep(0.05)
            state["inside"] -= 1
            return ""

        with mock.patch.object(pasteboard, "_copy_selection", side_effect=borrow):
            reads = [threading.Thread(target=pasteboard.copy_selection) for _ in range(3)]
            for t in reads:
                t.start()
            for t in reads:
                t.join()
        self.assertEqual(state["most"], 1)



class SelectionTest(unittest.TestCase):
    def read(self, *pids):
        with mock.patch.object(selection.permission, "trusted", return_value=True), \
                mock.patch.object(selection, "_frontmost_pid", side_effect=pids), \
                mock.patch.object(selection, "_expose"), \
                mock.patch.object(selection, "_via_ax", return_value=" hello "):
            return selection.read()

    def test_reads_the_app_that_stays_frontmost(self):
        self.assertEqual(self.read(111, 111), "hello")

    def test_drops_the_selection_when_the_user_switches_apps(self):
        self.assertEqual(self.read(111, 222), "")


class CodexPathTest(unittest.TestCase):
    def test_extended_path_adds_homebrew_and_keeps_current(self):
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            parts = codex_rt.extended_path().split(os.pathsep)
        self.assertIn("/opt/homebrew/bin", parts)
        self.assertIn("/usr/bin", parts)
        self.assertEqual(len(parts), len(set(parts)))

    def test_native_binary_behind_npm_shim(self):
        with tempfile.TemporaryDirectory() as root:
            pkg = os.path.join(root, "lib", "node_modules", "@openai", "codex")
            native = os.path.join(pkg, "node_modules", "@openai", "codex-darwin-arm64", "vendor",
                                  "aarch64-apple-darwin", "bin", "codex")
            os.makedirs(os.path.dirname(native))
            os.makedirs(os.path.join(pkg, "bin"))
            shim = os.path.join(pkg, "bin", "codex.js")
            with open(shim, "w") as f:
                f.write("#!/usr/bin/env node\n")
            open(native, "wb").close()
            link = os.path.join(root, "codex")
            os.symlink(shim, link)
            self.assertEqual(os.path.realpath(codex_rt._native_darwin(link)), os.path.realpath(native))

    def test_newest_codex_wins_over_path_order(self):
        with tempfile.TemporaryDirectory() as root:
            dirs = [os.path.join(root, name) for name in ("local-bin", "fnm", "brew")]
            for d in dirs:
                os.makedirs(d)
                exe = os.path.join(d, "codex")
                open(exe, "w").close()
                os.chmod(exe, 0o755)
            versions = {os.path.join(dirs[0], "codex"): (0, 144, 6), os.path.join(dirs[1], "codex"): (0, 163, 0),
                        os.path.join(dirs[2], "codex"): (0, 163, 0)}
            with mock.patch.object(codex_rt, "extended_path", return_value=os.pathsep.join(dirs)), \
                    mock.patch.object(codex_rt, "_native_darwin", side_effect=lambda shim: shim), \
                    mock.patch.object(codex_rt, "_version", side_effect=versions.get):
                self.assertEqual(codex_rt._newest_darwin(), os.path.join(dirs[1], "codex"))

    def test_mach_o_binary_is_used_directly(self):
        with tempfile.TemporaryDirectory() as root:
            exe = os.path.join(root, "codex")
            with open(exe, "wb") as f:
                f.write(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
            self.assertEqual(codex_rt._native_darwin(exe), os.path.realpath(exe))


if __name__ == "__main__":
    unittest.main()
