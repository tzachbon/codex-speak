import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from select_to_tts import updates


class Response(io.BytesIO):
    def geturl(self):
        return self.url


def response(data, url):
    result = Response(data)
    result.url = url
    return result


def release(tag="v0.10.0"):
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [{
        "name": "SelectToTTS-Setup.exe", "state": "uploaded", "size": 3,
        "digest": "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "browser_download_url": f"https://github.com/tzachbon/select-to-tts/releases/download/{tag}/SelectToTTS-Setup.exe"}]}


class Releases(unittest.TestCase):
    def test_only_a_newer_numeric_version_is_selected(self):
        for current, expected in (("0.9.0", True), ("0.10.0", False), ("1.0.0", False)):
            with patch.object(updates, "current_version", return_value=current), patch.object(
                    updates, "urlopen", return_value=response(json.dumps(release()).encode(), updates.API)):
                self.assertEqual(updates.check() is not None, expected)

    def test_invalid_release_cannot_be_selected(self):
        for field, value in (("tag_name", "v0.11.0-beta"), ("draft", True), ("prerelease", True),
                             ("assets", []), ("assets", None)):
            data = release()
            data[field] = value
            with self.subTest(field=field, value=value), patch.object(updates, "current_version", return_value="0.9.0"), patch.object(
                    updates, "urlopen", return_value=response(json.dumps(data).encode(), updates.API)):
                with self.assertRaises(ValueError):
                    updates.check()
        for field, value in (("browser_download_url", "https://evil.test/setup.exe"),
                             ("digest", None), ("digest", "sha256:bad"), ("size", True),
                             ("size", 0), ("size", 2**40), ("state", "new")):
            data = release()
            data["assets"][0][field] = value
            with self.subTest(field=field), patch.object(updates, "current_version", return_value="0.9.0"), patch.object(
                    updates, "urlopen", return_value=response(json.dumps(data).encode(), updates.API)):
                with self.assertRaises(ValueError):
                    updates.check()


class Downloads(unittest.TestCase):
    def test_bytes_are_verified_and_bad_downloads_are_removed(self):
        asset = {**release()["assets"][0], "version": "0.10.0"}
        for body, valid in ((b"abc", True), (b"abd", False), (b"ab", False), (b"abcd", False)):
            with tempfile.TemporaryDirectory() as directory, patch.object(updates, "CACHE", Path(directory)), patch.object(
                    updates, "urlopen", return_value=response(body, "https://release-assets.githubusercontent.com/file")):
                if valid:
                    path = updates.download(asset)
                    self.assertEqual(path.read_bytes(), b"abc")
                    self.assertTrue(path.is_relative_to(Path(directory)))
                else:
                    with self.assertRaises(ValueError):
                        updates.download(asset)
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_network_failure_and_untrusted_redirect_leave_no_installer(self):
        asset = release()["assets"][0]
        for url in ("http://github.com/file", "https://evil.test/file", "https://user@github.com/file"):
            with tempfile.TemporaryDirectory() as directory, patch.object(updates, "CACHE", Path(directory)), patch.object(
                    updates, "urlopen", return_value=response(b"abc", url)):
                with self.assertRaises(ValueError):
                    updates.download(asset)
                self.assertEqual(list(Path(directory).iterdir()), [])
            with self.assertRaises(ValueError):
                updates._HTTPSRedirect().redirect_request(None, None, 302, "", {}, url)
        with tempfile.TemporaryDirectory() as directory, patch.object(updates, "CACHE", Path(directory)), patch.object(
                updates, "urlopen", side_effect=TimeoutError("offline")):
            with self.assertRaises(TimeoutError):
                updates.download(asset)
            self.assertEqual(list(Path(directory).iterdir()), [])


class Installation(unittest.TestCase):
    def test_installer_targets_running_install_without_a_shell_or_reboot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updates, "CACHE", Path(directory)), patch.object(
                sys, "frozen", True, create=True), patch.object(sys, "executable", r"C:\Apps\Select to TTS\SelectToTTS.exe"), patch(
                "subprocess.Popen") as launch:
            path = Path(directory) / "update-123" / updates.ASSET
            path.parent.mkdir()
            path.write_bytes(b"abc")
            updates.install(path)
            args = launch.call_args.args[0]
            self.assertEqual(args[:4], [str(path), "/SP-", "/SILENT", "/NORESTART"])
            self.assertIn(r"/DIR=C:\Apps\Select to TTS", args)
            self.assertEqual(launch.call_args.kwargs["shell"], False)
        with patch.object(sys, "frozen", False, create=True), patch("subprocess.Popen") as launch:
            with self.assertRaises(ValueError):
                updates.install(Path("anything.exe"))
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
