$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"
Set-Location "$script:ProjectRoot\desktop"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run scripts\setup-desktop.ps1 first."
}
& ".venv\Scripts\python.exe" -m app.main
