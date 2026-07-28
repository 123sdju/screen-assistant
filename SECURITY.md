# Security

## Sensitive local data

`config.json` contains model endpoints and plaintext API keys. It is a runtime file and must never be committed, attached to issues, or included in release archives. Paired-device token hashes, task databases, screenshots, logs, Android signing files, and local environment files are also excluded by `.gitignore`.

The Android App can replace or clear an API key, but the desktop API never returns an existing key to the LAN. Screenshots are processed by the desktop and are not sent to paired Apps.

## Reporting a vulnerability

Do not open a public issue containing credentials, tokens, private screenshots, or exploit details. Contact the repository owner privately through their GitHub profile and include only the minimum information needed to reproduce the issue.

## Network boundary

The gateway is intended for trusted private LANs. Pair only devices you control, revoke unused devices from the desktop UI, and do not expose port `18765` directly to the public Internet.
