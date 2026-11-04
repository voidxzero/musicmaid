#!/usr/bin/env bash
# MusicMaid installer: system tools (optional), a private Python environment, launchers and a menu entry.
#   ./install.sh            install for the current user (~/.local), no root needed except for system packages
#   ./install.sh --no-deps  skip the package-manager step
# Your library database, settings and undo history (~/.local/share/musicmaid) are kept when you reinstall.
set -euo pipefail

APP=musicmaid
SRC="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/$APP"
BIN="$HOME/.local/bin"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor"
DEPS=1
[[ "${1:-}" == "--no-deps" ]] && DEPS=0

say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*"; }

[[ -f "$SRC/musicmaid/__init__.py" ]] || { warn "Run this from the MusicMaid folder (musicmaid/ not found)"; exit 1; }

if [[ $DEPS == 1 ]]; then
  say "Installing Chromaprint (fpcalc), ffmpeg and Python libraries with your package manager (sudo may ask for your password)"
  if command -v apt-get >/dev/null; then
    sudo apt-get install -y python3-venv python3-pip libchromaprint-tools libxcb-cursor0 ffmpeg \
      || warn "some packages failed to install"
  elif command -v dnf >/dev/null; then
    # Fedora ships everything MusicMaid needs, so pip has little or nothing left to download.
    if dnf --version 2>/dev/null | grep -qi dnf5; then SKIP=--skip-unavailable; else SKIP=--setopt=strict=0; fi
    # ffmpeg-free unless RPM Fusion's full ffmpeg is already installed (the two conflict)
    FF=ffmpeg-free
    rpm -q ffmpeg >/dev/null 2>&1 && FF=ffmpeg
    sudo dnf install -y $SKIP "$FF" chromaprint-tools xcb-util-cursor python3-pip python3-pyside6 python3-mutagen \
      python3-numpy python3-pillow python3-requests python3-send2trash python3-textual \
      || warn "some packages failed to install"
  elif command -v pacman >/dev/null; then
    sudo pacman -S --needed --noconfirm chromaprint ffmpeg python-pip xcb-util-cursor || warn "some packages failed to install"
  elif command -v zypper >/dev/null; then
    sudo zypper install -y chromaprint-fpcalc ffmpeg python3-pip || warn "some packages failed to install"
  else
    warn "Unknown package manager. Install Chromaprint's fpcalc if you can (MusicMaid can also download it)."
  fi
fi

PY=python3
command -v $PY >/dev/null || { warn "python3 not found"; exit 1; }
$PY - <<'EOF' || { warn "Python 3.10 or newer is required"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF

say "Installing MusicMaid into $PREFIX"
mkdir -p "$PREFIX/lib"
# copy first, then swap, so a failed copy never leaves you without a working MusicMaid
rm -rf "$PREFIX/lib/musicmaid.new" "$PREFIX/lib/musicmaid.old"
cp -r "$SRC/musicmaid" "$PREFIX/lib/musicmaid.new"
find "$PREFIX/lib/musicmaid.new" -name __pycache__ -prune -exec rm -rf {} +
if [[ -d "$PREFIX/lib/musicmaid" ]]; then mv "$PREFIX/lib/musicmaid" "$PREFIX/lib/musicmaid.old"; fi
mv "$PREFIX/lib/musicmaid.new" "$PREFIX/lib/musicmaid"
rm -rf "$PREFIX/lib/musicmaid.old"

# --system-site-packages lets the environment reuse distro packages (e.g. Fedora's python3-pyside6);
# pip only fetches what's still missing.
[[ -x "$PREFIX/venv/bin/python" ]] || $PY -m venv --system-site-packages "$PREFIX/venv"
MISSING=$("$PREFIX/venv/bin/python" - <<'EOF'
import importlib
checks = (("PySide6.QtWidgets", "PySide6>=6.5"), ("textual", "textual>=0.60"), ("mutagen", "mutagen>=1.45"),
          ("requests", "requests"), ("PIL", "pillow"), ("send2trash", "send2trash"))
for mod, req in checks:
    try:
        importlib.import_module(mod)
    except Exception:
        print(req)
try:
    import numpy
    if int(numpy.__version__.split(".")[0]) < 2:   # MusicMaid needs numpy 2's bitwise_count
        print("numpy>=2.0")
except Exception:
    print("numpy>=2.0")
EOF
)
if [[ -n "$MISSING" ]]; then
  say "Fetching from PyPI: $(echo $MISSING)"
  "$PREFIX/venv/bin/python" -m pip install --quiet --disable-pip-version-check $(echo $MISSING | tr ' ' '\n' | sort -u)
else
  say "All Python libraries provided by the system"
fi

say "Creating launchers in $BIN"
mkdir -p "$BIN"
# our lib goes first on sys.path, so a "musicmaid" folder in the current directory can't shadow it
launcher() {  # name, python code after the import
  cat > "$BIN/$1" <<EOF
#!/bin/sh
exec "$PREFIX/venv/bin/python" -c 'import sys; sys.path.insert(0, "$PREFIX/lib"); $2' "\$@"
EOF
  chmod +x "$BIN/$1"
}
launcher musicmaid     'from musicmaid.gui.mainwindow import main; sys.exit(main())'
launcher musicmaid-tui 'from musicmaid.tui.app import main; sys.exit(main())'
launcher musicmaid-cli 'from musicmaid.cli import main; sys.exit(main(sys.argv[1:]))'

say "Adding menu entry"
mkdir -p "$APPS" "$PREFIX/icons" "$ICONS/512x512/apps"
# the menu entry points at an absolute icon path (always works); the themed copy helps docks/launchers
cp "$SRC/musicmaid/assets/icon.png" "$PREFIX/icons/musicmaid.png"
cp "$SRC/musicmaid/assets/icon.png" "$ICONS/512x512/apps/musicmaid.png"
cat > "$APPS/musicmaid.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MusicMaid
GenericName=Music Tagger
Comment=Tag, clean up, de-duplicate and organize your music library
Exec=$BIN/musicmaid
Icon=$PREFIX/icons/musicmaid.png
Terminal=false
Categories=AudioVideo;Audio;
Keywords=music;tagger;tags;mp3;flac;duplicates;musicbrainz;artwork;
StartupWMClass=MusicMaid
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v xdg-desktop-menu >/dev/null && xdg-desktop-menu forceupdate >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$ICONS" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

say "Checking the installation"
"$BIN/musicmaid-cli" --help >/dev/null || { warn "MusicMaid didn't start; see the error above"; exit 1; }

case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN is not on your PATH; launch from the app menu or add it." ;; esac
command -v fpcalc >/dev/null || warn "fpcalc not found: MusicMaid will offer to download it on first start."
command -v ffmpeg >/dev/null || warn "ffmpeg not found: needed only to split CUE sheets."
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/musicmaid/__init__.py")
say "Done: MusicMaid $VER. Start it from your application menu, or run: musicmaid   (terminal UI: musicmaid-tui)"
