# Changelog

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
