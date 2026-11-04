#!/usr/bin/env bash
# Removes MusicMaid. Keeps your music, and your library database, settings, undo history and
# quarantined duplicates in ~/.local/share/musicmaid (delete that folder too for a clean slate).
set -eu
D="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$D/musicmaid/venv" "$D/musicmaid/lib" "$D/musicmaid/icons"
rm -f "$HOME/.local/bin/musicmaid" "$HOME/.local/bin/musicmaid-tui" "$HOME/.local/bin/musicmaid-cli" \
      "$D/applications/musicmaid.desktop" "$D/icons/hicolor/512x512/apps/musicmaid.png"
command -v update-desktop-database >/dev/null && update-desktop-database "$D/applications" >/dev/null 2>&1 || true
echo "MusicMaid removed. Your library data and settings are still in $D/musicmaid."
