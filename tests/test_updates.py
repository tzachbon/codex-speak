import io
import json
import os
from pathlib import Path
import tempfile
import sys
import shutil
import subprocess
import unittest
from unittest.mock import patch

from codex_speak import updates


class Response(io.BytesIO):
    def geturl(self):
        return self.url


def response(data, url):
    result = Response(data)
    result.url = url
    return result


def release(tag="v0.10.0"):
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [{
        "name": "CodexSpeak-Setup.exe", "state": "uploaded", "size": 3,
        "digest": "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "browser_download_url": f"https://github.com/tzachbon/codex-speak/releases/download/{tag}/CodexSpeak-Setup.exe"}]}


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
    def test_cleanup_failure_preserves_the_download_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updates, "CACHE", Path(directory)), patch.object(
                updates, "urlopen", return_value=response(b"abd", "https://release-assets.githubusercontent.com/file")):
            with patch("shutil.os.unlink", side_effect=PermissionError("installer is locked")):
                with self.assertRaisesRegex(ValueError, "Installer verification failed"):
                    updates.download(release()["assets"][0])

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
                sys, "frozen", True, create=True), patch.object(sys, "executable", r"C:\Apps\Codex Speak\CodexSpeak.exe"), patch(
                "subprocess.Popen") as launch:
            path = Path(directory) / "update-123" / updates.ASSET
            path.parent.mkdir()
            path.write_bytes(b"abc")
            updates.install(path)
            args = launch.call_args.args[0]
            self.assertEqual(args[:4], [str(path), "/SP-", "/SILENT", "/NORESTART"])
            self.assertIn(r"/DIR=C:\Apps\Codex Speak", args)
            self.assertEqual(launch.call_args.kwargs["shell"], False)
        with patch.object(sys, "frozen", False, create=True), patch("subprocess.Popen") as launch:
            with self.assertRaises(ValueError):
                updates.install(Path("anything.exe"))
            launch.assert_not_called()


class Packaging(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is needed for the build script")
    def test_build_rejects_a_mismatched_tag_without_changing_workflow_permissions(self):
        script = Path(__file__).resolve().parents[1] / "packaging" / "build.ps1"
        command = r"""
        $ast = [Management.Automation.Language.Parser]::ParseFile($env:CODEX_SPEAK_BUILD_SCRIPT, [ref]$null, [ref]$null)
        $guard = $ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.IfStatementAst] } | Select-Object -First 1
        if (-not $guard) { throw 'Release guard missing' }
        $version = '0.1.1'
        foreach ($pair in @(@('branch','master'), @('tag','v0.1.1'), @('tag','v0.1.2'))) {
            $env:GITHUB_REF_TYPE, $env:GITHUB_REF_NAME = $pair
            $rejected = $false
            try { & ([scriptblock]::Create($guard.Extent.Text)) } catch { $rejected = $true }
            if ($rejected -ne ($pair[1] -eq 'v0.1.2')) { throw "Unexpected guard result for $pair" }
        }
        """
        # Pass the path as data to avoid PowerShell interpolation.
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True,
                                env={**os.environ, "CODEX_SPEAK_BUILD_SCRIPT": str(script)})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
