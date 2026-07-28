$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"
Set-Location "$script:ProjectRoot\desktop"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run scripts\setup-desktop.ps1 first."
}
& ".venv\Scripts\python.exe" -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Desktop tests failed." }
Set-Location "$script:ProjectRoot\mobile"
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter was not found. Add it to PATH or set SCREEN_ASSISTANT_FLUTTER."
}
flutter analyze
if ($LASTEXITCODE -ne 0) { throw "Flutter analyze failed." }
flutter test
if ($LASTEXITCODE -ne 0) { throw "Flutter tests failed." }
