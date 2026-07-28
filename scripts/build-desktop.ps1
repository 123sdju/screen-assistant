$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"
Set-Location "$script:ProjectRoot\desktop"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run scripts\setup-desktop.ps1 first."
}
& ".venv\Scripts\python.exe" -m PyInstaller ScreenAssistant.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$exePath = "$script:ProjectRoot\desktop\dist\ScreenAssistant.exe"
$process = Start-Process -FilePath $exePath -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw "Packaged EXE self-test failed: $($process.ExitCode)" }
Write-Host "Desktop artifact: $exePath"
