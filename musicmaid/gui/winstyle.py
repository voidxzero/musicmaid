"""Windows look: the System theme follows Windows' dark/light setting, and every MusicMaid window's title bar
takes the theme's colours (Windows 11) or at least its dark/light mode (Windows 10). The title bar stays
Windows' own, so snapping, dragging and the caption buttons behave normally.

Everything here does nothing on other systems."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

WINDOWS = sys.platform == "win32"

# DwmSetWindowAttribute attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20       # Windows 10 20H1+ / 11 (19 on older Windows 10 builds)
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_BORDER_COLOR = 34                  # Windows 11 only: exact colours
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_COLOR_DEFAULT = 0xFFFFFFFF


def colorref(color: str) -> int:
    """'#RRGGBB' -> COLORREF (0x00BBGGRR)."""
    c = QColor(color)
    return (c.blue() << 16) | (c.green() << 8) | c.red()


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        try:
            s = scheme()
            if s == Qt.ColorScheme.Dark:
                return True
            if s == Qt.ColorScheme.Light:
                return False
        except Exception:  # noqa: BLE001
            pass
    return QApplication.palette().color(QPalette.Window).lightness() < 128


def dark_palette(accent: QColor | None = None) -> QPalette:
    """A Windows 11-like dark palette for the Fusion style (Windows 10 has no native dark widgets)."""
    accent = accent or QColor("#4cc2ff")
    p = QPalette()
    roles = {
        QPalette.Window: "#202020", QPalette.WindowText: "#ffffff", QPalette.Base: "#1c1c1c",
        QPalette.AlternateBase: "#262626", QPalette.ToolTipBase: "#2b2b2b", QPalette.ToolTipText: "#ffffff",
        QPalette.Text: "#ffffff", QPalette.Button: "#2d2d2d", QPalette.ButtonText: "#ffffff",
        QPalette.BrightText: "#ff6b6b", QPalette.Light: "#3a3a3a", QPalette.Midlight: "#333333",
        QPalette.Mid: "#4a4a4a", QPalette.Dark: "#151515", QPalette.Shadow: "#000000",
        QPalette.Link: accent.name(), QPalette.HighlightedText: "#000000",
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.PlaceholderText, QColor("#9a9a9a"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#7a7a7a"))
    p.setColor(QPalette.Disabled, QPalette.Base, QColor("#232323"))
    return p


class _State:
    native_style = ""                    # the style Qt picked at start (windows11 / windowsvista)
    theme_colors: dict | None = None     # skin colours, or None for the System theme


def init(app: QApplication) -> None:
    """Call once after creating the QApplication: remembers the native style, styles title bars as
    windows appear, and follows Windows' dark/light switch live."""
    if not WINDOWS:
        return
    _State.native_style = app.style().name().lower()
    app.installEventFilter(_titlebars)
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: _scheme_changed())


_on_scheme_change = []                   # callbacks (the main window re-applies its theme)


def on_scheme_change(fn) -> None:
    _on_scheme_change.append(fn)


def _scheme_changed() -> None:
    for fn in list(_on_scheme_change):
        fn()


def apply(app: QApplication, skin: dict | None) -> None:
    """Called when the theme changes. skin = the skin's colours, or None for the System theme."""
    if not WINDOWS:
        return
    _State.theme_colors = skin
    if skin is None:
        _system_look(app)
    elif app.style().name().lower() != "fusion" and "fusion" in [k.lower() for k in QStyleFactory.keys()]:
        # skins draw everything themselves; Fusion follows style sheets fully, where Windows 11's native
        # style adds its own rounded corners and ignores parts of them
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
    for w in app.topLevelWidgets():
        if w.isVisible():
            style_titlebar(w)


def _system_look(app: QApplication) -> None:
    dark = system_is_dark()
    native = _State.native_style
    if native == "windows11" or (native and native not in ("windowsvista", "windows")):
        # Qt's Windows 11 style follows the system's dark/light setting by itself
        if app.style().name().lower() != native:
            app.setStyle(native)
        app.setPalette(app.style().standardPalette())
        return
    if dark:                                           # Windows 10: native style has no dark mode
        accent = QApplication.palette().color(QPalette.Highlight)
        if "fusion" in [k.lower() for k in QStyleFactory.keys()]:
            app.setStyle("Fusion")
        app.setPalette(dark_palette(accent if accent.lightness() > 60 else None))
    else:
        if native and app.style().name().lower() != native:
            app.setStyle(native)
        app.setPalette(app.style().standardPalette())


def titlebar_colors() -> tuple[bool, str | None, str | None, str | None]:
    """(dark, caption, text, border) for the current theme."""
    skin = _State.theme_colors
    if skin:
        caption = skin.get("caption") or skin.get("title_top") or skin.get("panel_top") or skin.get("bg")
        text = "#ffffff" if QColor(caption).lightness() < 140 else "#000000"     # readable on the caption
        return QColor(skin.get("bg", "#000")).lightness() < 128, caption, text, skin.get("border")
    pal = QApplication.palette()
    dark = pal.color(QPalette.Window).lightness() < 128
    return dark, pal.color(QPalette.Window).name(), pal.color(QPalette.WindowText).name(), None


def style_titlebar(w: QWidget) -> None:
    if not WINDOWS or not w.isWindow():
        return
    try:
        import ctypes
        hwnd = int(w.winId())
        dwm = ctypes.WinDLL("dwmapi")
        dark, caption, text, border = titlebar_colors()
        on = ctypes.c_int(1 if dark else 0)
        if dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(on), 4) != 0:
            dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ctypes.byref(on), 4)
        for attr, col in ((DWMWA_CAPTION_COLOR, caption), (DWMWA_TEXT_COLOR, text), (DWMWA_BORDER_COLOR, border)):
            val = ctypes.c_uint(colorref(col) if col else DWMWA_COLOR_DEFAULT)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)   # Windows 10 ignores these
    except Exception:  # noqa: BLE001 - cosmetic; never let it break a window
        pass


class _TitlebarStyler(QObject):
    """Styles each window's title bar as it appears (main window, dialogs, message boxes)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            style_titlebar(obj)
        return False


_titlebars = _TitlebarStyler()
