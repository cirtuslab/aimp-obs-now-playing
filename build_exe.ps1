# Build a standalone exe with PyInstaller (optional convenience).
param(
    [switch]$Console
)
$ErrorActionPreference = "Stop"
python -m pip install --upgrade pyinstaller
$args = @("--name", "AIMPNowPlaying", "--clean", "--noconfirm", "--onefile", "--icon", "assets\icon.ico", "--collect-all", "customtkinter", "--exclude-module", "numpy", "--add-data", "assets/icon.ico;assets")
if (-not $Console) { $args += "--noconsole" }
python -m PyInstaller $args main.py
Write-Host ""
Write-Host "Build complete: dist\AIMPNowPlaying.exe"
