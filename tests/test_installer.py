"""Runs the installer cleanup code in a scratch-only Inno harness, without app or registry actions."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ISCC = next((p for p in (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6/ISCC.exe",
) if p.is_file()), None)


@unittest.skipUnless(ISCC, "Inno Setup 6 is required for installer runtime checks")
class Installer(unittest.TestCase):
    def test_upgrade_cleanup_preserves_shared_and_nested_installs(self):
        source = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8")
        definitions = source.split("[Setup]", 1)[0]
        default_dir = source.split("function DefaultDir", 1)[1].split("// Upgrades", 1)[0]
        prepare = source.split("function PrepareToInstall", 1)[1].split("procedure CurStepChanged", 1)[0]
        cleanup = source.split("procedure CurStepChanged", 1)[1].split("procedure CurUninstallStepChanged", 1)[0]
        deletes = source.split("[InstallDelete]", 1)[1].split("[UninstallDelete]", 1)[0]

        for case in ("default", "custom", "nested-default", "same-folder", "current-custom"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                scratch = Path(temporary).resolve()
                programs = scratch / "programs"
                old = programs / "Select to TTS" if case in ("default", "nested-default") else scratch / "custom"
                app = old / "Codex Speak" if case == "nested-default" else (
                    old if case in ("same-folder", "current-custom") else programs / "Codex Speak")
                self.assertTrue(old.is_relative_to(scratch) and app.is_relative_to(scratch))
                (old / "_internal").mkdir(parents=True)
                (old / "keep.txt").write_text("unrelated user data")
                previous_exe = "CodexSpeak.exe" if case == "current-custom" else "SelectToTTS.exe"
                uninstaller = old / ("unins001.exe" if case == "custom" else "unins000.exe")
                for path in (old / previous_exe, uninstaller, uninstaller.with_suffix(".dat"), old / "_internal/old.data"):
                    path.write_text("old app")
                if case == "custom":
                    (old / "unins000.exe").write_text("another app's uninstaller")
                    (old / "unins000.dat").write_text("another app's uninstall data")
                (scratch / "new.exe").write_text("new app")
                (scratch / "new.data").write_text("new runtime")

                isolated_deletes = deletes
                for constant, replacement in {
                    "{autopf}": programs,
                    "{autoprograms}": scratch / "shortcuts",
                    "{autodesktop}": scratch / "desktop",
                    "{%TEMP}": scratch / "cache",
                }.items():
                    isolated_deletes = isolated_deletes.replace(constant, str(replacement))
                for target in re.findall(r'Name: "([^"]+)"', isolated_deletes):
                    self.assertTrue(target.startswith("{app}\\") or target.startswith(str(scratch) + "\\"), target)

                # Registry reads are fixtures. Process shutdown and app launches are omitted.
                isolated_default = "function DefaultDir" + default_dir.replace(
                    "RegQueryStringValue", "PreviousInstall").replace("{autopf}", str(programs))
                isolated_prepare = "function PrepareToInstall" + prepare.replace(
                    "RegQueryStringValue", "PreviousInstall").replace("StopApp;", "")
                old_literal = str(old).replace("'", "''")
                uninstall_literal = str(uninstaller).replace("'", "''")
                script = definitions + f'''
[Setup]
AppName=Codex Speak installer regression check
AppVersion=1.0
DefaultDirName={{code:DefaultDir}}
UsePreviousAppDir=no
PrivilegesRequired=lowest
Uninstallable=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir={scratch}
OutputBaseFilename=check

[Files]
Source: "{scratch}\\new.exe"; DestDir: "{{app}}"; DestName: "{{#AppExe}}"
Source: "{scratch}\\new.data"; DestDir: "{{app}}\\_internal"

[InstallDelete]
{isolated_deletes}

[Code]
var OldDir, OldUninstaller: String;

function PreviousInstall(RootKey: Integer; const SubKey, ValueName: String; var Value: String): Boolean;
begin
  if ValueName = 'UninstallString' then
    Value := '"{uninstall_literal}"'
  else
    Value := '{old_literal}';
  Result := True;
end;

{isolated_default}

{isolated_prepare}

procedure CurStepChanged{cleanup}
'''
                harness = scratch / "check.iss"
                harness.write_text(script, encoding="utf-8")
                compiled = subprocess.run([str(ISCC), "/Q", str(harness)], capture_output=True, text=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                args = [str(scratch / "check.exe"), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        f"/LOG={scratch / 'setup.log'}"]
                if case in ("nested-default", "same-folder"):
                    args.append(f"/DIR={app}")
                installed = subprocess.run(args, capture_output=True, text=True, timeout=60)
                self.assertEqual(installed.returncode, 0, (scratch / "setup.log").read_text())
                self.assertEqual((old / "keep.txt").read_text(), "unrelated user data")
                self.assertEqual((app / "CodexSpeak.exe").read_text(), "new app")
                self.assertEqual((app / "_internal/new.data").read_text(), "new runtime")
                if case in ("default", "custom"):
                    self.assertFalse((old / "SelectToTTS.exe").exists())
                    self.assertFalse((old / "_internal").exists())
                if case == "nested-default":
                    self.assertEqual((old / "_internal/old.data").read_text(), "old app")
                if case == "custom":
                    self.assertEqual((old / "unins000.exe").read_text(), "another app's uninstaller")
                    self.assertEqual((old / "unins000.dat").read_text(), "another app's uninstall data")
                    self.assertFalse(uninstaller.exists())
                    self.assertFalse(uninstaller.with_suffix(".dat").exists())


if __name__ == "__main__":
    unittest.main()
