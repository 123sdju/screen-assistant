# Screen Assistant

[简体中文](README.zh-CN.md)

Screen Assistant is a serverless Windows screenshot assistant with an Android LAN companion App. The Windows client captures and previews screenshots, calls an OpenAI-compatible model directly, stores optional local history, and hosts an embedded authenticated LAN gateway. No PostgreSQL, account service, billing backend, or separately deployed server is required.

## Highlights

- Full-screen, region, and multi-image capture with desktop preview.
- Multiple OpenAI-compatible model connections and reusable prompt profiles.
- Per-model reasoning effort with automatic omission or standard reasoning levels.
- Optional `extra_body` JSON passed unchanged to compatible providers.
- Configurable global shortcuts with conflict detection and Esc cancellation.
- Key-driven code replay with exact indentation, forced English input mode, and optional human-like hold repeat.
- Android pairing through mDNS discovery, QR code, or manual LAN address.
- SSE streaming for thinking, results, task state, profiles, and buffer changes.
- Result-view font scaling that leaves navigation and status UI unchanged.
- Desktop shortcuts can page and resize text on every connected App currently showing the result page.
- One App can page results on other Apps connected to the same desktop.
- Model and profile editing from the App; existing API keys are never returned over LAN.

## Download and install

Download the latest files from [GitHub Releases](../../releases/latest):

- `ScreenAssistant-Windows-x64.exe` — portable Windows desktop client.
- `ScreenAssistant-Android.apk` — Android ARM release App.
- `SHA256SUMS.txt` — SHA-256 checksums for both artifacts.

Place the EXE in its own writable directory and run it. Windows may show a SmartScreen warning because community builds are not code-signed. On Android, allow installation from the browser or file manager used to open the APK.

Both sides must use the same release version when protocol features change.

## First-time setup

1. Open **Model connections** on Windows and enter the provider Base URL, API Key, model name, optional reasoning effort, and total request timeout.
2. Open **Profiles** and configure the system prompt, user prompt, and optional `extra_body`.
3. Open **LAN & pairing**, generate a six-digit code/QR code, and keep the desktop running.
4. Connect the phone to the same trusted Wi-Fi, then discover, scan, or enter `http://<desktop-lan-ip>:18765`.
5. Allow `ScreenAssistant.exe` through Windows Firewall on private networks when prompted.

`127.0.0.1` and `localhost` on the phone point to the phone itself. Use the desktop's actual LAN IPv4 address, such as `192.168.1.10`.

Automatic discovery uses the DNS-SD service type `_screenasst._tcp.local`; QR and manual-IP pairing remain available when multicast discovery is blocked.

## Security and local data

- The desktop writes runtime settings to `config.json` beside the EXE. This file can contain plaintext API keys and is excluded from Git.
- Apps receive independent bearer tokens. Tokens can be revoked per device from the desktop.
- Existing API keys are write-only from the App: the LAN API returns only whether a key is configured.
- Screenshots stay on the desktop side and are never exposed through App APIs.
- Clearing the history directory disables SQLite and persistent screenshots; temporary captures are removed after use.
- The gateway is for trusted private LANs. Do not forward port `18765` to the public Internet.

See [SECURITY.md](SECURITY.md) for the disclosure and network policy.

## Code replay

Replay extracts Markdown code blocks only. In standard mode, each completed physical key press emits one code character. Fast mode repeats at a configured characters-per-second rate with bounded random timing. The replay engine cancels editor auto-indentation before applying source indentation and requests the English keyboard layout before injection.

After the final character, the replay hook remains active and suppresses input until you press Esc or click **Close code replay**.

## Repository layout

```text
screen-assistant/
├─ desktop/   PySide6 UI, task engine, history, LAN gateway
├─ mobile/    Flutter Android App
├─ docs/      Architecture, configuration, and protocol
└─ scripts/   Setup, test, build, and release packaging
```

The vendored `mobile_scanner` dependency remains under its original BSD-3-Clause license; see `mobile/third_party/mobile_scanner/LICENSE`.

## Development

Requirements:

- Windows 10/11 and Python 3.11+ for the desktop client.
- Flutter stable 3.29+, Android SDK, and JDK 17 for the Android App.
- PowerShell 5.1+.

```powershell
git clone <repository-url>
cd screen-assistant

.\scripts\setup-desktop.ps1
.\scripts\run-desktop.ps1
```

If Flutter is not already in `PATH`, set `SCREEN_ASSISTANT_FLUTTER` to the Flutter SDK directory. Standard `ANDROID_HOME` and `JAVA_HOME` variables are supported.

Run all checks:

```powershell
.\scripts\test.ps1
```

Build release artifacts:

```powershell
.\scripts\build-desktop.ps1
.\scripts\build-apk.ps1
.\scripts\package-release.ps1 -Version 1.0.0
```

Outputs are intentionally ignored by Git:

- `desktop/dist/ScreenAssistant.exe`
- `mobile/build/app/outputs/flutter-apk/app-release.apk`
- `release/v1.0.0/`

## Documentation

- [Architecture](docs/architecture.md)
- [Configuration and data](docs/configuration.md)
- [LAN protocol](docs/protocol.md)
- [v1.0.0 manual test checklist](docs/manual-test-v1.0.0.md)
- [Changelog](CHANGELOG.md)

## License

This project is released under the [MIT License](LICENSE). Third-party components retain their own licenses.
