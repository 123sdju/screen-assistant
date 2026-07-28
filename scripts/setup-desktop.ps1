$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"
Set-Location "$script:ProjectRoot\desktop"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
