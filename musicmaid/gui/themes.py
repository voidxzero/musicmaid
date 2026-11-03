"""Colour themes for the Qt GUI (applied through the Fusion style and a QPalette)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

# name -> window, base (lists/fields), alternate rows, text, button, accent, accent text, link
_PALETTES: dict[str, tuple[str, ...]] = {
    "Light":    ("#f3f3f5", "#ffffff", "#f6f6f9", "#1d1d22", "#e9e9ee", "#3d6fd9", "#ffffff", "#2f62c9"),
    "Dark":     ("#26272b", "#1c1d20", "#232428", "#e6e6ea", "#323338", "#4f8cff", "#ffffff", "#7aa7ff"),
    "Midnight": ("#141a2a", "#0e1320", "#121829", "#d9e1f5", "#1f2840", "#6c7cff", "#ffffff", "#9aa6ff"),
    "Graphite": ("#2d2d2d", "#232323", "#292929", "#e8e8e8", "#3a3a3a", "#f08a24", "#1a1a1a", "#ffb062"),
    "Forest":   ("#1d2621", "#151c18", "#1a221d", "#dce8df", "#28352d", "#3fae6a", "#ffffff", "#6fd394"),
    "Rose":     ("#faf3f5", "#ffffff", "#fbf5f7", "#2a1d22", "#f1e3e8", "#d14d7a", "#ffffff", "#b8386a"),
}
THEMES = ["System", *_PALETTES]
_native_style: str | None = None
_native_palette: QPalette | None = None


def _system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark


def palette(name: str) -> QPalette:
    window, base, alt, text, button, accent, accent_text, link = (QColor(c) for c in _PALETTES[name])
    dark = window.lightness() < 128
    p = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, window), (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Base, base), (QPalette.ColorRole.AlternateBase, alt),
        (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, button),
        (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.BrightText, QColor("#ff5555")),
        (QPalette.ColorRole.Highlight, accent), (QPalette.ColorRole.HighlightedText, accent_text),
        (QPalette.ColorRole.Link, link), (QPalette.ColorRole.LinkVisited, link),
        (QPalette.ColorRole.ToolTipBase, base), (QPalette.ColorRole.ToolTipText, text),
        (QPalette.ColorRole.PlaceholderText, QColor(text.red(), text.green(), text.blue(), 120)),
        (QPalette.ColorRole.Light, button.lighter(130)), (QPalette.ColorRole.Midlight, button.lighter(115)),
        (QPalette.ColorRole.Mid, button.darker(130 if dark else 115)),
        (QPalette.ColorRole.Dark, button.darker(170 if dark else 140)),
        (QPalette.ColorRole.Shadow, QColor(0, 0, 0)),
    ):
        p.setColor(role, color)
    muted = QColor(text)
    muted.setAlpha(110)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, muted)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, button.darker(120))
    return p


def apply(name: str, app: QApplication | None = None) -> str:
    """Apply a theme by name; returns the name actually used."""
    global _native_style, _native_palette
    app = app or QApplication.instance()
    if _native_style is None:
        _native_style, _native_palette = app.style().name(), QPalette(app.palette())
    if name not in THEMES:
        name = "System"
    if name == "System":
        import sys
        if sys.platform == "win32":
            # the native Windows style ignores dark mode, so follow the OS setting ourselves
            app.setStyle("Fusion")
            app.setPalette(palette("Dark" if _system_is_dark() else "Light"))
        else:
            app.setStyle(_native_style)
            app.setPalette(_native_palette)  # the desktop's own colours
    else:
        app.setStyle("Fusion")
        app.setPalette(palette(name))
    return name


def follow_system_changes(app: QApplication, current) -> None:
    """Re-apply the System theme when the OS switches between light and dark."""
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: current() == "System" and apply("System", app))
