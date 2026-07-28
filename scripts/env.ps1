$ErrorActionPreference = "Stop"
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot

if ($env:SCREEN_ASSISTANT_FLUTTER) {
    $flutterRoot = (Resolve-Path $env:SCREEN_ASSISTANT_FLUTTER).Path
    $env:Path = "$flutterRoot\bin;$env:Path"
}

if (-not $env:ANDROID_HOME) {
    $defaultAndroidSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path $defaultAndroidSdk) {
        $env:ANDROID_HOME = $defaultAndroidSdk
    }
}
if ($env:ANDROID_HOME) {
    $env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
    $env:Path = "$env:ANDROID_HOME\platform-tools;$env:Path"
}

if ($env:JAVA_HOME) {
    $env:Path = "$env:JAVA_HOME\bin;$env:Path"
}
