param(
    [string]$Version = "1.2.2"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"

$exe = Join-Path $script:ProjectRoot "desktop\dist\ScreenAssistant.exe"
$apk = Join-Path $script:ProjectRoot "mobile\build\app\outputs\flutter-apk\app-release.apk"
if (-not (Test-Path $exe)) { throw "Desktop artifact is missing. Run scripts\build-desktop.ps1 first." }
if (-not (Test-Path $apk)) { throw "Android artifact is missing. Run scripts\build-apk.ps1 first." }

$releaseDir = Join-Path $script:ProjectRoot "release\v$Version"
if (Test-Path -LiteralPath $releaseDir) {
    $existing = @(Get-ChildItem -LiteralPath $releaseDir -Force)
    if ($existing.Count -gt 0) {
        throw "Release staging already exists and is not empty: $releaseDir. Choose a new version or remove it explicitly."
    }
} else {
    New-Item -ItemType Directory -Path $releaseDir | Out-Null
}
$releaseExe = Join-Path $releaseDir "ScreenAssistant-Windows-x64.exe"
$releaseApk = Join-Path $releaseDir "ScreenAssistant-Android.apk"
Copy-Item -LiteralPath $exe -Destination $releaseExe -Force
Copy-Item -LiteralPath $apk -Destination $releaseApk -Force

$checksums = @(
    "$((Get-FileHash $releaseExe -Algorithm SHA256).Hash)  ScreenAssistant-Windows-x64.exe"
    "$((Get-FileHash $releaseApk -Algorithm SHA256).Hash)  ScreenAssistant-Android.apk"
)
Set-Content -LiteralPath (Join-Path $releaseDir "SHA256SUMS.txt") -Value $checksums -Encoding ascii
Write-Host "Release staging: $releaseDir"
