# Changelog

## 1.2.2 (2026-08-21)

- Delayed LAN gateway startup until the desktop window is visible, so Windows can present its native network-access prompt at a usable time.
- Documented that users should select private networks only; the application does not create or modify Windows Firewall rules and cannot force the native prompt to show only one profile.
- Refined the Web layout: the Current Result page is focused on status and output, while screenshot, submit, clear, profile, and paging commands are centralized on Remote Control.
- Kept all Remote Control buttons visually consistent without a specially emphasized primary command.
- Updated the English and Chinese release documentation and added the v1.2.2 manual test checklist.

## 1.2.1 (2026-08-21)

- Changed the default desktop shortcut set to `F1`–`F12` in action order: capture, submit, profile, replay, and App/Web paging or font controls.
- Changed the default maximum output-token setting to `8192` for new or missing model fields while preserving existing explicit values.
- Added multi-image capture controls to the desktop remote gateway, Android App, and Web companion; each capture appends to the current buffer up to eight images.
- Improved provider compatibility by preferring modern Chat Completions token fields with fallback, handling optional Responses reasoning summaries, and reporting incomplete or invisible model output as failure.
- Added Android screen-awake behavior and browser Wake Lock/media fallback, plus clearer manual reconnect behavior after a client stream disconnects.
- Expanded configuration, gateway, provider, Web, and mobile regression coverage.

## 1.2.0 (2026-08-20)

- Added an embedded Web companion at `/` and `/web` with QR-link pairing, SSE task streaming, history, remote controls, settings, focus mode, and result font controls.
- Added direct Web URL QR payloads while keeping Android compatibility with legacy JSON pairing payloads.
- Hardened App connection lifecycle handling: switching desktops invalidates old tokens, stale streams are ignored, and revoked credentials require re-pairing instead of retrying.
- Bundled Web assets in the desktop package and expanded gateway/App regression coverage.

## 1.1.0 (2026-07-30)

- Added exact full-endpoint URL mode alongside API-root and automatic URL handling.
- Added Chat Completions and Responses protocol selection for arbitrary provider endpoints.
- Added Linux desktop platform backends, CI packaging, and tagged-release artifacts.
- Added full-width, soft-wrapped code blocks in the Android result view.

## 1.0.0 (2026-07-29)

- Portable Windows desktop client with local OpenAI-compatible model connections and configurable reasoning effort.
- Full-screen, region, and multi-image screenshot buffering with desktop preview.
- Configurable global shortcuts and key-driven code replay with exact indentation.
- Active model tasks can be superseded immediately by a new screenshot submission.
- Embedded authenticated LAN gateway with QR, `_screenasst._tcp.local` discovery, and manual pairing.
- Android App with streaming thinking/results, history, remote controls, and model/profile editing.
- Portrait and landscape layouts keep thinking and results vertically ordered.
- Result-only font scaling and synchronized multi-App paging through the desktop event hub.
- Existing API keys remain write-only over the LAN API.
