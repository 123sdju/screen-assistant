#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/desktop"

python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install --upgrade pip
.venv-linux/bin/python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv-linux/bin/python -m pytest -q
.venv-linux/bin/python -m PyInstaller ScreenAssistant.spec --clean --noconfirm

artifact_dir="$project_root/release/linux"
mkdir -p "$artifact_dir"
tar -C dist -czf "$artifact_dir/ScreenAssistant-Linux-x86_64.tar.gz" ScreenAssistant
sha256sum "$artifact_dir/ScreenAssistant-Linux-x86_64.tar.gz" \
  > "$artifact_dir/ScreenAssistant-Linux-x86_64.tar.gz.sha256"
echo "Linux artifact: $artifact_dir/ScreenAssistant-Linux-x86_64.tar.gz"
