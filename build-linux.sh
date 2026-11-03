#!/bin/sh
# Builds MusicMaid for Linux: release/MusicMaid-<ver>-linux-<arch>.tar.gz (+ AppImage with --appimage)
set -e
cd "$(dirname "$0")"
[ -x .venv-build/bin/python ] || python3 -m venv .venv-build
.venv-build/bin/pip install -q --upgrade pip
.venv-build/bin/pip install -q ".[gui]" pyinstaller
.venv-build/bin/python packaging/build.py "$@"
QT_QPA_PLATFORM=offscreen dist/MusicMaid/MusicMaid --self-test
