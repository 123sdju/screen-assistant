$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"
Set-Location "$script:ProjectRoot\mobile"
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter was not found. Add it to PATH or set SCREEN_ASSISTANT_FLUTTER."
}
flutter pub get
if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }
flutter analyze
if ($LASTEXITCODE -ne 0) { throw "flutter analyze failed" }
flutter test
if ($LASTEXITCODE -ne 0) { throw "flutter test failed" }
flutter build apk --release --target-platform android-arm,android-arm64
if ($LASTEXITCODE -ne 0) { throw "flutter build apk failed" }
Write-Host "Android artifact: $script:ProjectRoot\mobile\build\app\outputs\flutter-apk\app-release.apk"
