#Requires -Version 7.4
# Builds dist\SelectToTTS-Setup.exe: PyInstaller app folder, then the Inno Setup 6 installer.
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true  # a failing uv/pyinstaller/iscc stops the build
Set-Location (Split-Path $PSScriptRoot)
uv sync --locked
$version = uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
New-Item -ItemType Directory -Force build | Out-Null
uv run python -c "from select_to_tts.__main__ import icon_image; icon_image(256).save('build/icon.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 256)])"
uv run pyinstaller --noconfirm --clean --windowed --name SelectToTTS --icon "$PWD\build\icon.ico" `
    --collect-all uiautomation --hidden-import pystray._win32 `
    --distpath build\dist --workpath build\work --specpath build packaging\launcher.py
if ($LASTEXITCODE) { throw "pyinstaller failed" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }
& $iscc /Qp "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE) { throw "iscc failed" }
Get-Item dist\SelectToTTS-Setup.exe
