; Per-user installer for Codex Speak. Built by packaging\build.ps1 (Inno Setup 6).
#define AppName "Codex Speak"
#define AppExe "CodexSpeak.exe"
#define AppId "FED44346-501C-414C-A557-8F7BDA1AC94A"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"
; Older builds started at sign-in through this Run value
#define RunValue "select-to-tts"
; The app was called Select to TTS before 0.5.0. Setup replaces that install in place (same AppId).
#define OldExe "SelectToTTS.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{{#AppId}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=tzachbon
AppPublisherURL=https://github.com/tzachbon/codex-speak
DefaultDirName={autopf}\{#AppName}
UsePreviousAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=CodexSpeak-Setup
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Tasks]
Name: startup; Description: "Start {#AppName} when I sign in to Windows"; Check: IsFreshInstall
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\build\dist\CodexSpeak\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files from an older version that this version no longer ships
Type: filesandordirs; Name: "{app}\_internal"
; Leftovers from Select to TTS. The app moves its settings and sign-in task on first start.
Type: filesandordirs; Name: "{autopf}\Select to TTS"
Type: files; Name: "{autoprograms}\Select to TTS.lnk"
Type: files; Name: "{autodesktop}\Select to TTS.lnk"
Type: filesandordirs; Name: "{%TEMP}\select-to-tts"
Type: filesandordirs; Name: "{%TEMP}\comtypes_cache\SelectToTTS-311"

[UninstallDelete]
; App-owned caches outside {app}. Settings and the log in %APPDATA%\codex-speak are kept.
Type: filesandordirs; Name: "{%TEMP}\comtypes_cache\CodexSpeak-311"
Type: filesandordirs; Name: "{%TEMP}\codex-speak"
Type: filesandordirs; Name: "{localappdata}\codex-speak\updates"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Start-at-sign-in is a Task Scheduler logon task, so it starts at once instead of queueing
; behind every Run-key app. The app creates and removes it.
Filename: "{app}\{#AppExe}"; Parameters: "--startup on"; Tasks: startup; Flags: runhidden waituntilterminated
; An existing sign-in task is re-pointed here, even if the app isn't launched after setup
Filename: "{app}\{#AppExe}"; Parameters: "--startup refresh"; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--startup off"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveStartupTask"

[Code]
// Upgrades keep the user's sign-in choice from the Settings page instead of re-asking.
function IsFreshInstall: Boolean;
begin
  Result := not RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppId}}_is1');
end;

procedure StopApp;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe} /IM {#OldExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

var
  OldDir: String;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopApp;
  // Where Select to TTS was installed, possibly not the default folder
  if not RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppId}}_is1',
                             'InstallLocation', OldDir) then
    OldDir := '';
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Only a folder that still holds the old app is removed, never the new one
  if (CurStep = ssPostInstall) and (OldDir <> '') and FileExists(AddBackslash(OldDir) + '{#OldExe}')
     and (CompareText(RemoveBackslash(OldDir), RemoveBackslash(ExpandConstant('{app}'))) <> 0) then
    DelTree(RemoveBackslash(OldDir), True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    StopApp;
    RegDeleteValue(HKCU, '{#RunKey}', '{#RunValue}');  // left by builds before the logon task
  end;
end;
