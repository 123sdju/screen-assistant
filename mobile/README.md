# Screen Assistant Android App

Flutter companion App for the Screen Assistant desktop client. It discovers and pairs with a desktop over the local network, receives task streams over SSE, controls screenshots and profiles, synchronizes result paging across paired Apps, and edits desktop model/profile settings without reading existing API keys.

From the repository root:

```powershell
.\scripts\build-apk.ps1
```

The release APK is written to `mobile/build/app/outputs/flutter-apk/app-release.apk`. It targets physical ARM Android devices (`arm64-v8a` and `armeabi-v7a`).
