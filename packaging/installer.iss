; Per-user installer for Select to TTS. Built by packaging\build.ps1 (Inno Setup 6).
#define AppName "Select to TTS"
#define AppExe "SelectToTTS.exe"
#define AppId "FED44346-501C-414C-A557-8F7BDA1AC94A"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"
; The app's settings page writes and removes this same value
#define RunValue "select-to-tts"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{{#AppId}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=tzachbon
AppPublisherURL=https://github.com/tzachbon/select-to-tts
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SelectToTTS-Setup
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
Source: "..\build\dist\SelectToTTS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files from an older version that this version no longer ships
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; App-owned caches outside {app}. Settings and the log in %APPDATA%\select-to-tts are kept.
Type: filesandordirs; Name: "{%TEMP}\comtypes_cache\SelectToTTS-311"
Type: filesandordirs; Name: "{%TEMP}\select-to-tts"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "{#RunValue}"; ValueData: """{app}\{#AppExe}"""; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall

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
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopApp;
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    StopApp;
    RegDeleteValue(HKCU, '{#RunKey}', '{#RunValue}');
  end;
end;
