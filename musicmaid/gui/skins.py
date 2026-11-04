"""Skins: Windows XP-style chrome in dark colours, Winamp-Modern flavoured.

Ported from Spindle (github.com/voidxzero/spindle) so both apps look alike. The skin-file format is the same,
so a skin made for one app works in the other.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..config import data_dir


def _cache_dir() -> Path:
    return data_dir() / "cache"

THEMES: dict[str, dict[str, str]] = {
    # Winamp "Modern", but darker: gunmetal panels, green LCD, orange accents
    "Modern Night": dict(
        bg="#121419", panel_top="#2a2e37", panel_bot="#1b1e24", inset="#0e1014", border="#3b414d",
        hilite="#4a5262", text="#d7dce5", dim="#8a93a3", accent="#f29b30", accent_text="#1a1206",
        lcd_bg="#070a07", lcd_fg="#5cf08c", lcd_dim="#1f5a33", sel="#2e5a87", sel_text="#ffffff",
        title_top="#3a404c", title_bot="#262a32", btn_top="#3a3f4a", btn_bot="#23262d",
        good="#5cf08c", warn="#f2c230", bad="#ff5f56", alt="#16191e"),
    # Windows XP Luna after dark: deep blue chrome, green "Start" accent
    "Luna Midnight": dict(
        bg="#0c1424", panel_top="#1f3b6e", panel_bot="#132649", inset="#0a1120", border="#2f5395",
        hilite="#5d8ad8", text="#e3ebf8", dim="#93a7c8", accent="#3fae49", accent_text="#ffffff",
        lcd_bg="#05101f", lcd_fg="#8fd0ff", lcd_dim="#1d3f63", sel="#316ac5", sel_text="#ffffff",
        title_top="#2c63d4", title_bot="#173c8c", btn_top="#2d5296", btn_bot="#1a3466",
        good="#7ee787", warn="#ffd75e", bad="#ff7b72", alt="#0f192c"),
    # XP Olive Green, darkened
    "Olive Noir": dict(
        bg="#15170f", panel_top="#3a4026", panel_bot="#262a19", inset="#0f110a", border="#4f5733",
        hilite="#7a8650", text="#e6e8d6", dim="#a3a88a", accent="#d9b44a", accent_text="#1c1704",
        lcd_bg="#0a0c05", lcd_fg="#d4ea7a", lcd_dim="#4a5520", sel="#6b7a3a", sel_text="#ffffff",
        title_top="#5a6438", title_bot="#384021", btn_top="#4a5230", btn_bot="#2c311c",
        good="#c8f07a", warn="#f2c230", bad="#ff7058", alt="#1a1d12"),
    # Classic Winamp 2.x: black, green text, steel buttons
    "Amp Classic": dict(
        bg="#0b0b10", panel_top="#33334a", panel_bot="#1d1d2b", inset="#000000", border="#4c4c66",
        hilite="#8080a8", text="#d8d8e8", dim="#8c8ca8", accent="#e8c440", accent_text="#14100a",
        lcd_bg="#000000", lcd_fg="#00e639", lcd_dim="#0a4d18", sel="#2b4f9e", sel_text="#ffffff",
        title_top="#4b4b6e", title_bot="#25253a", btn_top="#4a4a62", btn_bot="#2a2a3a",
        good="#00e639", warn="#e8c440", bad="#ff4040", alt="#121218"),
    # Teal Winamp skin: aquamarine panels, cyan LCD
    "Aqua Deck": dict(
        bg="#0b2a2f", panel_top="#2f8f98", panel_bot="#1b5b64", inset="#062027", border="#3fb0b8",
        hilite="#8ff0f0", text="#e8fdff", dim="#9fd3d6", accent="#5ff2e4", accent_text="#03231f",
        lcd_bg="#031b1d", lcd_fg="#55f5dc", lcd_dim="#155a55", sel="#23a7b2", sel_text="#ffffff",
        title_top="#38a3ad", title_bot="#1d6670", btn_top="#3a9da6", btn_bot="#1f6870",
        good="#7dffb0", warn="#ffd86b", bad="#ff7b7b", alt="#0a262c"),
    # Glossy bright-blue player and equaliser
    "Ice Blue": dict(
        bg="#05244f", panel_top="#2f8de6", panel_bot="#1556ae", inset="#03183a", border="#53b3ff",
        hilite="#b5e2ff", text="#eef8ff", dim="#a3cbf0", accent="#86e6ff", accent_text="#03203b",
        lcd_bg="#021029", lcd_fg="#86e6ff", lcd_dim="#1d4d7c", sel="#3aa0ff", sel_text="#ffffff",
        title_top="#4aa8ff", title_bot="#1b62c4", btn_top="#3c9af0", btn_bot="#1a5cb4",
        good="#86f5ae", warn="#ffd86b", bad="#ff7f7f", alt="#041d43"),
    # Brushed-silver chrome with a deep-blue LCD (a light skin)
    "Chrome Deck": dict(
        bg="#8f98a3", panel_top="#eef1f4", panel_bot="#bcc4cd", inset="#f7f9fb", border="#7a8491",
        hilite="#ffffff", text="#16202d", dim="#4d5866", accent="#2a6ad8", accent_text="#ffffff",
        lcd_bg="#0a1d47", lcd_fg="#8fd2ff", lcd_dim="#264a84", sel="#2a6ad8", sel_text="#ffffff",
        title_top="#dfe4ea", title_bot="#aeb7c1", btn_top="#f4f6f8", btn_bot="#c4cbd3",
        good="#16834a", warn="#a8670e", bad="#cc2b2b", alt="#edf0f3", caption="#c9d0d8"),
    # Black console with a neon-green core
    "Emerald Core": dict(
        bg="#040705", panel_top="#1d2820", panel_bot="#0f1611", inset="#020403", border="#2d5a36",
        hilite="#4f8f5a", text="#dcf8df", dim="#80a886", accent="#3dff6e", accent_text="#02130a",
        lcd_bg="#010a03", lcd_fg="#4dff7a", lcd_dim="#155a27", sel="#1f7a3b", sel_text="#ffffff",
        title_top="#29382c", title_bot="#131b15", btn_top="#28362b", btn_bot="#131a15",
        good="#4dff7a", warn="#e8d24a", bad="#ff5a5a", alt="#090f0b"),
    # Windows 98 CD Player: grey 3D panels, navy title bars (a light skin)
    "Classic 98": dict(
        bg="#c0c0c0", panel_top="#d6d3ce", panel_bot="#c0c0c0", inset="#ffffff", border="#808080",
        hilite="#ffffff", text="#000000", dim="#555555", accent="#000080", accent_text="#ffffff",
        lcd_bg="#000000", lcd_fg="#00e000", lcd_dim="#1c4a1c", sel="#000080", sel_text="#ffffff",
        title_top="#d4d0c8", title_bot="#bdbab3", btn_top="#e3e1dc", btn_bot="#c0c0c0",
        good="#007a00", warn="#8a6100", bad="#c00000", alt="#f2f2f2", caption="#000080",
        style="classic98", r_panel="0px", r_rail="0px", r="0px", r_small="0px", r_knob="0px",
        font="'Microsoft Sans Serif', 'MS Sans Serif', Tahoma, 'Liberation Sans', 'DejaVu Sans', sans-serif",
        font_size="8pt"),
}

SYSTEM = "System"
DEFAULT_SKIN = "Amp Classic" if sys.platform == "win32" else "Modern Night"   # same defaults as Spindle
FONT = "'Tahoma', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif"
MONO = "'DejaVu Sans Mono', 'Liberation Mono', 'Noto Mono', 'Consolas', monospace"


def theme_names() -> list[str]:
    return [SYSTEM] + list(THEMES)


def _icons(name: str, p: dict) -> dict[str, str]:
    """Write tiny SVG arrows/checkmarks in the skin's colours (Qt style sheets can't draw them)."""
    d = _cache_dir() / "skin" / name.replace(" ", "_")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    shapes = {
        "down": '<path d="M1 3 L5 7 L9 3" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        "up": '<path d="M1 7 L5 3 L9 7" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        "check": '<path d="M1.5 5.2 L4 7.7 L8.6 2.4" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
        "dot": '<circle cx="5" cy="5" r="2.6" fill="{c}"/>',
    }
    out = {}
    for key, color in (("down", p["text"]), ("up", p["text"]), ("down_dim", p["dim"]), ("up_dim", p["dim"])):
        shape = shapes[key.split("_")[0]].format(c=color)
        f = d / f"{key}.svg"
        try:
            f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">{shape}</svg>')
        except OSError:
            continue
        out[key] = str(f).replace("\\", "/")
    # Complete checkbox / radio images (box, border, fill and tick in one picture). Qt draws item-view
    # check indicators from the image alone - background/border rules are ignored there.
    tick = '<path d="M3.6 8.2 L6.6 11.2 L12.4 4.8" fill="none" stroke="{t}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
    box = '<rect x="0.75" y="0.75" width="14.5" height="14.5" rx="3" fill="{f}" stroke="{b}" stroke-width="1.5"/>'
    ring = '<circle cx="8" cy="8" r="7.25" fill="{f}" stroke="{b}" stroke-width="1.5"/>'
    dot = '<circle cx="8" cy="8" r="3.4" fill="{t}"/>'
    states = {
        "cb_off": box.format(f=p["btn_top"], b=p["dim"]),
        "cb_off_hover": box.format(f=p["btn_top"], b=p["accent"]),
        "cb_on": box.format(f=p["accent"], b=p["accent"]) + tick.format(t=p["accent_text"]),
        "cb_off_dis": box.format(f=p["btn_bot"], b=p["border"]),
        "cb_on_dis": box.format(f=p["dim"], b=p["dim"]) + tick.format(t=p["btn_bot"]),
        "rb_off": ring.format(f=p["btn_top"], b=p["dim"]),
        "rb_off_hover": ring.format(f=p["btn_top"], b=p["accent"]),
        "rb_on": ring.format(f=p["btn_top"], b=p["accent"]) + dot.format(t=p["accent"]),
    }
    for key, body in states.items():
        f = d / f"{key}.svg"
        try:
            f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{body}</svg>')
        except OSError:
            continue
        out[key] = str(f).replace("\\", "/")
    return out


# --- Classic 98: real Windows 98 elements --------------------------------------------------------------
# Windows 98's 3D look is two-pixel bevels: white and light grey on the top/left, dark grey and black on
# the bottom/right (reversed for sunken fields and pressed buttons), square corners, flat grey. Qt style
# sheets can't draw two-tone borders, so the bevels are tiny pixel-exact images used as border-images.
W98 = {"face": "#c0c0c0", "light": "#dfdfdf", "white": "#ffffff", "shadow": "#808080", "dark": "#000000"}


def _px(x, y, w, h, c):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>'


def _bevel(size, outer_tl, inner_tl, outer_br, inner_br, face, frame=None):
    """A size x size image: two-pixel bevel around a face, optionally inside a 1px frame."""
    o = 1 if frame else 0
    n = size - 2 * o
    b = [_px(0, 0, size, size, frame)] if frame else []
    b.append(_px(o, o, n, n, face))
    b += [_px(o, o, n - 1, 1, outer_tl), _px(o, o, 1, n - 1, outer_tl),                       # outer top/left
          _px(o, o + n - 1, n, 1, outer_br), _px(o + n - 1, o, 1, n, outer_br),               # outer bottom/right
          _px(o + 1, o + 1, n - 3, 1, inner_tl), _px(o + 1, o + 1, 1, n - 3, inner_tl),       # inner top/left
          _px(o + 1, o + n - 2, n - 2, 1, inner_br), _px(o + n - 2, o + 1, 1, n - 2, inner_br)]  # inner bottom/right
    return b


def _classic98_assets(d) -> dict[str, str]:
    """Write the Windows 98 bevels, check boxes, radio buttons, arrows, slider thumb and the dithered
    scroll-bar track; returns {name: path}."""
    c = W98
    svgs = {
        "raised": (6, 6, _bevel(6, c["white"], c["light"], c["dark"], c["shadow"], c["face"])),
        "pressed": (6, 6, _bevel(6, c["dark"], c["shadow"], c["white"], c["light"], c["face"])),
        "default": (8, 8, _bevel(8, c["white"], c["light"], c["dark"], c["shadow"], c["face"], frame=c["dark"])),
        "sunken": (6, 6, _bevel(6, c["shadow"], c["dark"], c["white"], c["light"], c["white"])),
        "sunken_face": (6, 6, _bevel(6, c["shadow"], c["dark"], c["white"], c["light"], c["face"])),
        "dither": (2, 2, [_px(0, 0, 2, 2, c["face"]), _px(0, 0, 1, 1, c["white"]), _px(1, 1, 1, 1, c["white"])]),
    }
    tick = ('<path d="M3 6 L5 8 L10 3 L10 5 L5 10 L3 8 Z" fill="{t}"/>')
    for key, face, mark in (("cb_off", c["white"], None), ("cb_on", c["white"], c["dark"]),
                            ("cb_off_dis", c["face"], None), ("cb_on_dis", c["face"], c["shadow"])):
        svgs[key] = (13, 13, _bevel(13, c["shadow"], c["dark"], c["white"], c["light"], face)
                     + ([tick.format(t=mark)] if mark else []))
    # radio: a sunken circle (half-rings in the bevel colours) with an optional black dot
    ring = ('<path d="M10.2 1.8 A6 6 0 0 0 1.8 10.2" fill="none" stroke="{a}" stroke-width="1"/>'
            '<path d="M10.2 1.8 A6 6 0 0 1 1.8 10.2" fill="none" stroke="{b}" stroke-width="1"/>')
    for key, dot in (("rb_off", False), ("rb_on", True)):
        svgs[key] = (12, 12, ['<circle cx="6" cy="6" r="5" fill="#ffffff"/>',
                              ring.format(a=c["shadow"], b=c["white"]).replace("A6 6", "A6 6"),
                              '<g transform="translate(1 1) scale(0.8333)">' + ring.format(a=c["dark"], b=c["light"]) + "</g>"]
                     + (['<rect x="4" y="4" width="4" height="4" fill="#000000"/>'] if dot else []))
    for key, pts in (("a_down", "0,0 7,0 3.5,4"), ("a_up", "3.5,0 7,4 0,4"),
                     ("a_left", "4,0 4,7 0,3.5"), ("a_right", "0,0 4,3.5 0,7")):
        w, h = (7, 4) if key in ("a_down", "a_up") else (4, 7)
        svgs[key] = (w, h, [f'<polygon points="{pts}" fill="#000000"/>'])
        svgs[key + "_dis"] = (w, h, [f'<polygon points="{pts}" fill="{c["shadow"]}"/>'])
    # the trackbar thumb: a raised pentagon pointing down
    svgs["thumb"] = (11, 21, [
        '<polygon points="0,0 10,0 10,15 5,20 0,15" fill="#c0c0c0"/>',
        '<polyline points="0.5,15 0.5,0.5 9.5,0.5" fill="none" stroke="#ffffff"/>',
        '<polyline points="1.5,15 1.5,1.5 8.5,1.5" fill="none" stroke="#dfdfdf"/>',
        '<polyline points="10.5,0 10.5,15.2 5.2,20.5" fill="none" stroke="#000000"/>',
        '<polyline points="9.5,1 9.5,14.8 5,19.3" fill="none" stroke="#808080"/>',
        '<line x1="0.5" y1="15" x2="5" y2="19.5" stroke="#ffffff"/>'])
    out = {}
    for key, (w, h, body) in svgs.items():
        f = d / f"w98_{key}.svg"
        try:
            f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
                         f'shape-rendering="crispEdges">{"".join(body)}</svg>')
        except OSError:
            continue
        out[key] = str(f).replace("\\", "/")
    return out


CLASSIC98_QSS = """
/* ---- Classic 98: square, flat grey, two-pixel bevels ---- */
QFrame#panel, QFrame#rail, QFrame#header { background: #c0c0c0; border: 1px solid;
    border-color: #ffffff #808080 #808080 #ffffff; border-radius: 0px; }
QLabel#railTitle { color: #000080; letter-spacing: 0px; }
QToolTip { background: #ffffe1; color: #000000; border: 1px solid #000000; padding: 2px; }

QPushButton, QToolButton { background: transparent; border-width: 2px; border-style: solid;
    border-image: url("%(raised)s") 2 2 2 2 stretch stretch; color: #000000; padding: 1px 10px; }
QPushButton:hover, QToolButton:hover { border-image: url("%(raised)s") 2 2 2 2 stretch stretch; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {
    border-image: url("%(pressed)s") 2 2 2 2 stretch stretch; padding: 2px 9px 0px 11px; }
QPushButton:disabled, QToolButton:disabled { color: #808080; }
QPushButton#primary, QToolButton#primary, QToolButton#railButton[accent="true"] { background: transparent;
    color: #000000; font-weight: bold; border-width: 3px; border-image: url("%(default)s") 3 3 3 3 stretch stretch; }
QPushButton#primary:disabled, QToolButton#primary:disabled, QToolButton#railButton[accent="true"]:disabled {
    background: transparent; color: #808080; }
QToolButton#railButton { padding: 2px; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget, QTableView {
    background: #ffffff; border-width: 2px; border-style: solid;
    border-image: url("%(sunken)s") 2 2 2 2 stretch stretch; border-radius: 0px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QListWidget:focus { border-image: url("%(sunken)s") 2 2 2 2 stretch stretch; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { background: #c0c0c0; }
QComboBox::drop-down { width: 16px; border-width: 2px; border-style: solid;
    border-image: url("%(raised)s") 2 2 2 2 stretch stretch; }
QComboBox::down-arrow { image: url("%(a_down)s"); width: 7px; height: 4px; }
QComboBox::down-arrow:disabled { image: url("%(a_down_dis)s"); }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #000000; selection-background-color: #000080;
    selection-color: #ffffff; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; background: transparent; border-width: 2px;
    border-style: solid; border-image: url("%(raised)s") 2 2 2 2 stretch stretch; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { border-image: url("%(pressed)s") 2 2 2 2 stretch stretch; }
QSpinBox::up-arrow { image: url("%(a_up)s"); width: 7px; height: 4px; }
QSpinBox::down-arrow { image: url("%(a_down)s"); width: 7px; height: 4px; }
QPlainTextEdit#log { background: #000000; border-image: none; border: 2px solid;
    border-color: #808080 #ffffff #ffffff #808080; }
QLabel#lcd, QLabel#lcdBig, QLabel#cover { border: 2px solid; border-color: #808080 #ffffff #ffffff #808080;
    border-radius: 0px; }
QLabel#cover:hover { border-color: #808080 #ffffff #ffffff #808080; }

QHeaderView::section { background: transparent; color: #000000; padding: 1px 6px; border-width: 2px;
    border-style: solid; border-image: url("%(raised)s") 2 2 2 2 stretch stretch; }
QTableWidget, QTableView { gridline-color: #c0c0c0; alternate-background-color: #ffffff; }

QGroupBox { background: transparent; border: 2px groove #c0c0c0; border-radius: 0px; margin-top: 14px; }
QGroupBox::title { background: #c0c0c0; color: #000000; border: none; font-weight: normal; padding: 0px 3px; }

QTabWidget::pane { border: 1px solid; border-color: #ffffff #000000 #000000 #ffffff; background: #c0c0c0;
    border-radius: 0px; top: -1px; }
QTabBar::tab { background: #c0c0c0; color: #000000; border: 1px solid; border-color: #ffffff #000000 #c0c0c0 #ffffff;
    border-bottom: none; padding: 3px 10px; margin-top: 2px; margin-right: 0px; border-radius: 0px; }
QTabBar::tab:selected { margin-top: 0px; padding-bottom: 5px; border-top: 1px solid #ffffff; color: #000000; }

QProgressBar { background: #ffffff; color: transparent; border-width: 2px; border-style: solid;
    border-image: url("%(sunken)s") 2 2 2 2 stretch stretch; border-radius: 0px; }
QProgressBar::chunk { background: #000080; width: 8px; margin: 1px; border-radius: 0px; }

QMenuBar { background: #c0c0c0; border: none; }
QMenuBar::item:selected { background: #000080; color: #ffffff; border-radius: 0px; }
QMenu { background: #c0c0c0; border-width: 2px; border-style: solid;
    border-image: url("%(raised)s") 2 2 2 2 stretch stretch; padding: 1px; }
QMenu::item { padding: 3px 22px 3px 20px; border-radius: 0px; }
QMenu::item:selected { background: #000080; color: #ffffff; }
QMenu::separator { height: 2px; margin: 3px 2px; border-top: 1px solid #808080; border-bottom: 1px solid #ffffff; }
QStatusBar { background: #c0c0c0; }
QStatusBar::item { border: 1px solid; border-color: #808080 #ffffff #ffffff #808080; }

QCheckBox::indicator, QTableView::indicator, QTableWidget::indicator, QListView::indicator,
QListWidget::indicator, QTreeView::indicator { width: 13px; height: 13px; }
QCheckBox::indicator:unchecked:hover, QTableView::indicator:unchecked:hover, QTableWidget::indicator:unchecked:hover,
QListView::indicator:unchecked:hover, QListWidget::indicator:unchecked:hover, QTreeView::indicator:unchecked:hover { image: url("%(cb_off)s"); }
QRadioButton::indicator { width: 12px; height: 12px; }
QRadioButton::indicator:unchecked:hover { image: url("%(rb_off)s"); }

QSlider::groove:horizontal { height: 2px; background: #c0c0c0; border: 2px solid;
    border-color: #808080 #ffffff #ffffff #808080; border-radius: 0px; }
QSlider::sub-page:horizontal { background: transparent; border-radius: 0px; }
QSlider::handle:horizontal { image: url("%(thumb)s"); width: 11px; height: 21px; margin: -10px 0px;
    border: none; background: transparent; border-radius: 0px; }

QScrollBar:vertical { background: url("%(dither)s"); width: 16px; margin: 16px 0px 16px 0px; }
QScrollBar:horizontal { background: url("%(dither)s"); height: 16px; margin: 0px 16px 0px 16px; }
QScrollBar::handle { background: #c0c0c0; border-width: 2px; border-style: solid; border-radius: 0px;
    border-image: url("%(raised)s") 2 2 2 2 stretch stretch; min-height: 16px; min-width: 16px; }
QScrollBar::add-line, QScrollBar::sub-line { background: #c0c0c0; border-width: 2px; border-style: solid;
    border-image: url("%(raised)s") 2 2 2 2 stretch stretch; subcontrol-origin: margin; }
QScrollBar::add-line:vertical { height: 16px; subcontrol-position: bottom; }
QScrollBar::sub-line:vertical { height: 16px; subcontrol-position: top; }
QScrollBar::add-line:horizontal { width: 16px; subcontrol-position: right; }
QScrollBar::sub-line:horizontal { width: 16px; subcontrol-position: left; }
QScrollBar::up-arrow:vertical { image: url("%(a_up)s"); width: 7px; height: 4px; }
QScrollBar::down-arrow:vertical { image: url("%(a_down)s"); width: 7px; height: 4px; }
QScrollBar::left-arrow:horizontal { image: url("%(a_left)s"); width: 4px; height: 7px; }
QScrollBar::right-arrow:horizontal { image: url("%(a_right)s"); width: 4px; height: 7px; }
QSplitter::handle { background: #c0c0c0; }
"""


SYSTEM_QSS = """
QLabel#lcdBig { font-family: %(MONO)s; font-size: 11pt; font-weight: bold; padding: 0px 10px;
    border: 1px solid palette(mid); border-radius: 4px; background: palette(base); }
QLabel#lcd { font-family: %(MONO)s; padding: 3px 8px; border: 1px solid palette(mid); border-radius: 4px;
    background: palette(base); }
QLabel#railTitle { font-weight: bold; letter-spacing: 2px; color: palette(highlight); }
QLabel#cover { border: 1px solid palette(mid); border-radius: 4px; background: palette(base); color: palette(placeholder-text); }
QLabel#fieldLabel, QLabel#dim { color: palette(placeholder-text); }
QToolButton#railButton { min-width: 92px; max-width: 92px; min-height: 64px; padding: 4px 2px; }
QToolButton#railButton[accent="true"] { font-weight: bold; }
QPlainTextEdit#log { font-family: %(MONO)s; font-size: 9pt; }
""" % dict(MONO=MONO)


def stylesheet(name: str) -> str:
    if name == SYSTEM or name not in THEMES:
        return SYSTEM_QSS
    p = dict(THEMES[name])
    # corner radii and font are skin settings (Classic 98: square corners, 8pt MS Sans Serif)
    p.setdefault("r_panel", "3px")
    p.setdefault("r_rail", "4px")
    p.setdefault("r", "2px")
    p.setdefault("r_small", "1px")
    p.setdefault("r_knob", "6px")
    p.setdefault("font", FONT)
    p.setdefault("font_size", "9pt")
    icons = _icons(name, p)
    classic = p.get("style") == "classic98"
    if classic:
        w98 = _classic98_assets(_cache_dir() / "skin" / name.replace(" ", "_"))
        icons.update({k: w98[k] for k in ("cb_off", "cb_on", "cb_off_dis", "cb_on_dis", "rb_off", "rb_on") if k in w98})
        icons["cb_off_hover"], icons["rb_off_hover"] = w98.get("cb_off", ""), w98.get("rb_off", "")
        icons["down"], icons["up"] = w98.get("a_down", ""), w98.get("a_up", "")
        icons["down_dim"], icons["up_dim"] = w98.get("a_down_dis", ""), w98.get("a_up_dis", "")
    p.update({k: icons.get(k, "") for k in ("down", "up", "down_dim", "up_dim", "cb_off", "cb_off_hover", "cb_on",
                                            "cb_off_dis", "cb_on_dis", "rb_off", "rb_off_hover", "rb_on")})
    return """
* { font-family: %(font)s; font-size: %(font_size)s; color: %(text)s; }
*:disabled { color: %(dim)s; }
QMainWindow, QDialog { background: %(bg)s; }
QWidget#central { background: %(bg)s; }
QToolTip { background: %(inset)s; color: %(text)s; border: 1px solid %(accent)s; padding: 4px; }

/* panels: raised XP-style bevel */
QFrame#panel, QFrame#rail, QFrame#header {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(panel_top)s, stop:1 %(panel_bot)s);
    border: 1px solid %(border)s; border-top-color: %(hilite)s; border-radius: %(r_panel)s; }
QFrame#rail { border-radius: %(r_rail)s; }
QLabel#railTitle { color: %(accent)s; font-weight: bold; letter-spacing: 1px; font-size: 8pt; }

/* the LCD readout */
QLabel#lcd, QLabel#lcdBig {
    background: %(lcd_bg)s; color: %(lcd_fg)s; font-family: %(MONO)s;
    border: 2px solid %(inset)s; border-bottom-color: %(hilite)s; border-right-color: %(hilite)s;
    border-radius: %(r)s; padding: 0px 10px; }
QLabel#lcdBig { font-size: 11pt; font-weight: bold; }
QLabel#lcdDim { color: %(lcd_dim)s; background: transparent; font-family: %(MONO)s; }

QLabel#cover { background: %(inset)s; border: 2px solid %(inset)s; border-bottom-color: %(hilite)s;
    border-right-color: %(hilite)s; color: %(dim)s; }
QLabel#cover:hover { border-color: %(accent)s; }
QLabel#fieldLabel { color: %(dim)s; }
QLabel#dim { color: %(dim)s; }

/* group boxes with XP task-pane title strips */
QGroupBox { background: %(panel_bot)s; border: 1px solid %(border)s; border-radius: %(r_panel)s;
    margin-top: 16px; padding: 14px 10px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 6px; padding: 1px 8px;
    color: %(text)s; font-weight: bold; border-radius: %(r)s;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %(title_top)s, stop:1 %(title_bot)s);
    border: 1px solid %(border)s; }

/* inputs: one consistent height for every single-line control */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QListWidget {
    background: %(inset)s; border: 1px solid %(border)s; border-radius: %(r)s;
    selection-background-color: %(sel)s; selection-color: %(sel_text)s; }
QLineEdit, QSpinBox, QComboBox { min-height: 20px; padding: 0px 6px; color: %(text)s; }
QSpinBox { selection-background-color: %(sel)s; selection-color: %(sel_text)s; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QListWidget:focus { border-color: %(accent)s; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: %(dim)s; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 20px;
    border: none; border-left: 1px solid %(border)s; }
QComboBox::down-arrow { image: url("%(down)s"); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url("%(down_dim)s"); }
QComboBox QAbstractItemView { background: %(inset)s; border: 1px solid %(accent)s; padding: 2px;
    selection-background-color: %(sel)s; outline: none; }
QSpinBox { padding-right: 20px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 18px;
    background: %(btn_bot)s; border: none; border-left: 1px solid %(border)s; }
QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: %(r)s; }
QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: %(r)s;
    border-top: 1px solid %(border)s; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(btn_top)s; }
QSpinBox::up-arrow { image: url("%(up)s"); width: 7px; height: 7px; }
QSpinBox::down-arrow { image: url("%(down)s"); width: 7px; height: 7px; }
QPlainTextEdit#log { font-family: %(MONO)s; font-size: 8pt; color: %(lcd_fg)s; background: %(lcd_bg)s;
    padding: 4px; }

/* glossy XP buttons */
QPushButton, QToolButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(btn_top)s, stop:0.5 %(btn_bot)s, stop:1 %(btn_bot)s);
    border: 1px solid %(border)s; border-top-color: %(hilite)s; border-radius: %(r)s; padding: 1px 12px;
    min-height: 22px; }
QToolButton#transport { min-width: 28px; max-width: 28px; padding: 1px; }
QToolButton#iconButton { padding: 0px; }
QPushButton:hover, QToolButton:hover { border-color: %(accent)s; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {
    background: %(inset)s; border-top-color: %(inset)s; border-bottom-color: %(hilite)s; }
QPushButton:disabled, QToolButton:disabled { color: %(dim)s; border-color: %(border)s; }
QPushButton#primary, QToolButton#primary {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(accent)s, stop:1 %(btn_bot)s);
    color: %(accent_text)s; font-weight: bold; border-color: %(accent)s; }
QPushButton#primary:disabled, QToolButton#primary:disabled { background: %(btn_bot)s; color: %(dim)s; }
QToolButton#railButton { min-width: 92px; max-width: 92px; min-height: 64px; padding: 4px; }
QToolButton#railButton[accent="true"] {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(accent)s, stop:1 %(btn_bot)s);
    color: %(accent_text)s; font-weight: bold; border-color: %(accent)s; }
QToolButton#railButton[accent="true"]:disabled { background: %(btn_bot)s; color: %(dim)s; border-color: %(border)s; }
QToolButton::menu-indicator { image: url("%(down)s"); subcontrol-position: right center; width: 10px; right: 6px; }
QToolButton#formatButton { padding-right: 24px; }

QCheckBox, QRadioButton { spacing: 6px; }
QCheckBox::indicator, QTableView::indicator, QTableWidget::indicator, QListView::indicator, QListWidget::indicator, QTreeView::indicator {
    width: 15px; height: 15px; background: transparent; border: none; }
QCheckBox::indicator:unchecked, QTableView::indicator:unchecked, QTableWidget::indicator:unchecked, QListView::indicator:unchecked, QListWidget::indicator:unchecked, QTreeView::indicator:unchecked { image: url("%(cb_off)s"); }
QCheckBox::indicator:unchecked:hover, QTableView::indicator:unchecked:hover, QTableWidget::indicator:unchecked:hover, QListView::indicator:unchecked:hover, QListWidget::indicator:unchecked:hover, QTreeView::indicator:unchecked:hover { image: url("%(cb_off_hover)s"); }
QCheckBox::indicator:unchecked:disabled, QTableView::indicator:unchecked:disabled, QTableWidget::indicator:unchecked:disabled, QListView::indicator:unchecked:disabled, QListWidget::indicator:unchecked:disabled, QTreeView::indicator:unchecked:disabled { image: url("%(cb_off_dis)s"); }
QCheckBox::indicator:checked, QTableView::indicator:checked, QTableWidget::indicator:checked, QListView::indicator:checked, QListWidget::indicator:checked, QTreeView::indicator:checked { image: url("%(cb_on)s"); }
QCheckBox::indicator:checked:disabled, QTableView::indicator:checked:disabled, QTableWidget::indicator:checked:disabled, QListView::indicator:checked:disabled, QListWidget::indicator:checked:disabled, QTreeView::indicator:checked:disabled { image: url("%(cb_on_dis)s"); }
QRadioButton::indicator { width: 15px; height: 15px; background: transparent; border: none; }
QRadioButton::indicator:unchecked { image: url("%(rb_off)s"); }
QRadioButton::indicator:unchecked:hover { image: url("%(rb_off_hover)s"); }
QRadioButton::indicator:checked { image: url("%(rb_on)s"); }
QSlider::groove:horizontal { height: 4px; background: %(inset)s; border: 1px solid %(border)s; border-radius: %(r_small)s; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: %(r_small)s; }
QSlider::handle:horizontal { width: 12px; margin: -6px 0; border-radius: %(r_knob)s; border: 1px solid %(border)s;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(btn_top)s, stop:1 %(btn_bot)s); }
QSlider::handle:horizontal:hover { border-color: %(accent)s; }

/* track list */
QTableWidget, QTableView { background: %(inset)s; alternate-background-color: %(alt)s;
    gridline-color: %(panel_bot)s; border: 1px solid %(border)s; border-radius: %(r)s;
    selection-background-color: %(sel)s; selection-color: %(sel_text)s; }
QHeaderView::section { color: %(text)s; padding: 4px 6px; border: none;
    border-right: 1px solid %(border)s; border-bottom: 2px solid %(accent)s;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(title_top)s, stop:1 %(title_bot)s); }
QTableCornerButton::section { background: %(title_bot)s; border: none; }

/* XP tabs: the selected tab gets the orange (accent) top line */
QTabBar { background: %(bg)s; qproperty-drawBase: 0; }
QTabWidget::tab-bar { left: 0px; }
QTabWidget::pane { border: 1px solid %(border)s; border-radius: %(r)s; background: %(panel_bot)s; top: -1px; }
QTabBar::tab { background: %(btn_bot)s; border: 1px solid %(border)s; border-bottom: none;
    padding: 5px 12px; margin-right: 2px; border-top-left-radius: %(r)s; border-top-right-radius: %(r)s;
    color: %(dim)s; }
QTabBar::tab:selected { background: %(panel_bot)s; color: %(text)s; border-top: 3px solid %(accent)s; }
QTabBar::tab:hover:!selected { color: %(text)s; }

QProgressBar { background: %(lcd_bg)s; border: 1px solid %(inset)s; border-bottom-color: %(hilite)s;
    border-radius: %(r)s; text-align: center; color: %(lcd_fg)s; font-family: %(MONO)s; height: 16px; }
QProgressBar::chunk { border-radius: %(r_small)s;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(lcd_fg)s, stop:1 %(lcd_dim)s); }

QMenuBar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(panel_top)s, stop:1 %(panel_bot)s);
    border-bottom: 1px solid %(border)s; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected { background: %(sel)s; border-radius: %(r)s; }
QMenu { background: %(panel_bot)s; border: 1px solid %(border)s; padding: 3px; }
QMenu::item { padding: 5px 24px 5px 20px; border-radius: %(r_small)s; }
QMenu::item:selected { background: %(sel)s; color: %(sel_text)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 6px; }
QStatusBar { background: %(panel_bot)s; border-top: 1px solid %(border)s; color: %(dim)s; }
QStatusBar QLabel { color: %(dim)s; padding: 0 8px; }
QSplitter::handle { background: %(bg)s; }
QSplitter::handle:hover { background: %(accent)s; }

QScrollBar:vertical { background: %(inset)s; width: 12px; margin: 0; }
QScrollBar:horizontal { background: %(inset)s; height: 12px; margin: 0; }
QScrollBar::handle { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %(btn_top)s, stop:1 %(btn_bot)s);
    border: 1px solid %(border)s; border-radius: %(r)s; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { border-color: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
""" % dict(p, FONT=FONT, MONO=MONO) + (CLASSIC98_QSS % w98 if classic else "")


def colors(name: str) -> dict[str, str]:
    if name in THEMES:
        return THEMES[name]
    # System theme: derive from the desktop palette so it fits light and dark setups
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    pal = QApplication.palette()
    c = lambda role: pal.color(role).name()  # noqa: E731
    dark = pal.color(QPalette.Window).lightness() < 128
    return dict(sel=c(QPalette.Highlight), sel_text=c(QPalette.HighlightedText), text=c(QPalette.Text),
                lcd_bg=c(QPalette.Base), lcd_fg=c(QPalette.Highlight), lcd_dim=c(QPalette.Mid),
                border=c(QPalette.Mid), good="#3fb950" if dark else "#1a7f37",
                warn="#d29922" if dark else "#9a6700", bad="#f85149" if dark else "#cf222e",
                accent=c(QPalette.Highlight), dim=c(QPalette.PlaceholderText))


# --- skin files: share and import skins as JSON -----------------------------------------------------------
# A skin file holds colours and a few settings - never code - so skins are safe to share. Bundled extra
# skins live in musicmaid/skins/ (shipped with the app); imported ones in <data dir>/skins.
import json as _json
import re as _re

BUILTIN_SKINS = tuple(THEMES)
COLOR_KEYS = tuple(THEMES["Modern Night"])           # every colour a skin can set
_HEX = _re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_FONT = _re.compile(r"^[\w\s,'.-]{1,200}$")
_SIZE = _re.compile(r"^\d{1,2}(?:pt|px)$")
RADII = ("r", "r_panel", "r_rail", "r_small", "r_knob")
skin_errors: list[str] = []                           # problems with skin files, shown in the log
skin_files: dict[str, str] = {}                       # skin name -> the file it came from


def bundled_skin_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "skins"


def user_skin_dir() -> Path:
    return data_dir() / "skins"


def parse_skin(data) -> tuple[str, dict]:
    """Validate a skin file's contents. Returns (name, palette); raises ValueError saying what's wrong."""
    if not isinstance(data, dict):
        raise ValueError("a skin file must be a JSON object")
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 40 or not _re.match(r"^[\w &'().,+-]+$", name):
        raise ValueError("the skin needs a \"name\" (up to 40 letters, digits, spaces and & ' ( ) . , + -)")
    if name == SYSTEM:
        raise ValueError("\"System\" is taken by the built-in theme")
    base = str(data.get("base") or "Modern Night")
    if base not in THEMES or base == name:
        raise ValueError(f"unknown \"base\" skin: {base}")
    pal = {k: v for k, v in THEMES[base].items() if k in COLOR_KEYS}
    colors_ = data.get("colors", {})
    if not isinstance(colors_, dict):
        raise ValueError("\"colors\" must be an object of name: \"#rrggbb\"")
    for k, v in colors_.items():
        if k not in COLOR_KEYS:
            raise ValueError(f"unknown colour \"{k}\" (known: {', '.join(COLOR_KEYS)})")
        if not isinstance(v, str) or not _HEX.match(v):
            raise ValueError(f"colour \"{k}\" must look like #rrggbb, not {v!r}")
        pal[k] = v
    if "caption" in data:
        if not isinstance(data["caption"], str) or not _HEX.match(data["caption"]):
            raise ValueError("\"caption\" must look like #rrggbb")
        pal["caption"] = data["caption"]
    corners = data.get("corners", {})
    if not isinstance(corners, dict):
        raise ValueError("\"corners\" must be an object like {\"r\": 2, \"r_panel\": 3}")
    for k, v in corners.items():
        if k not in RADII or not isinstance(v, int) or not 0 <= v <= 20:
            raise ValueError(f"corner \"{k}\" must be one of {', '.join(RADII)} with a whole number 0-20")
        pal[k] = f"{v}px"
    if "font" in data:
        if not isinstance(data["font"], str) or not _FONT.match(data["font"]):
            raise ValueError("\"font\" must be a list of font names, e.g. \"Tahoma, sans-serif\"")
        pal["font"] = data["font"]
    if "font_size" in data:
        fs = f"{data['font_size']}pt" if isinstance(data["font_size"], int) else str(data["font_size"])
        if not _SIZE.match(fs):
            raise ValueError("\"font_size\" must be a number of points, e.g. 9")
        pal["font_size"] = fs
    if "style" in data:
        if data["style"] != "classic98":
            raise ValueError("\"style\" can only be \"classic98\" (Windows 98 bevels and icons)")
        pal["style"] = "classic98"
    return name, pal


def _register(name: str, pal: dict, source: str) -> str:
    if name in BUILTIN_SKINS:
        name = f"{name} (custom)"
    THEMES[name] = pal
    skin_files[name] = source
    return name


def load_skins() -> None:
    """(Re)load the bundled and imported skin files. Imported skins override bundled ones of the same name."""
    for n in [n for n in THEMES if n not in BUILTIN_SKINS]:
        del THEMES[n]
    skin_files.clear()
    skin_errors.clear()
    for d in (bundled_skin_dir(), user_skin_dir()):
        try:
            files = sorted(d.glob("*.json"))
        except OSError:
            continue
        for f in files:
            try:
                name, pal = parse_skin(_json.loads(f.read_text(encoding="utf-8")))
                _register(name, pal, str(f))
            except (OSError, ValueError) as e:
                skin_errors.append(f"skin {f.name}: {e}")


def _slug(name: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "skin"


def import_skin(path: str) -> str:
    """Check a skin file and copy it into the user's skins folder. Returns the skin's name."""
    try:
        data = _json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"couldn't read {Path(path).name}: {e}") from e
    name, pal = parse_skin(data)
    d = user_skin_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{_slug(name)}.json"
    dest.write_text(_json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return _register(name, pal, str(dest))


def export_skin(name: str, path: str) -> None:
    """Write a skin as a complete, editable skin file (every colour spelled out)."""
    pal = THEMES[name]
    data = {"spindle_skin": 1, "name": f"My {name}"[:40], "author": "", "base": name,
            "colors": {k: pal[k] for k in COLOR_KEYS if k in pal}}
    if "caption" in pal:
        data["caption"] = pal["caption"]
    corners = {k: int(str(pal[k]).rstrip("px")) for k in RADII if k in pal}
    if corners:
        data["corners"] = corners
    for k in ("font", "font_size", "style"):
        if k in pal:
            data[k] = pal[k]
    Path(path).write_text(_json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


load_skins()


# --- applying a skin to the whole app ---------------------------------------------------------------------
def apply(name: str) -> str:
    """Apply a skin (or "System") to the running app; returns the name actually used."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    from . import winstyle
    if name != SYSTEM and name not in THEMES:
        name = DEFAULT_SKIN
    app = QApplication.instance()
    global _native_palette
    if _native_palette is None:
        _native_palette = QPalette(app.palette())   # the desktop's own colours, for "System"
    winstyle.apply(app, THEMES.get(name))          # Windows: Fusion for skins, dark/light + title bars
    global _native_link
    if _native_link is None:
        _native_link = app.palette().color(QPalette.ColorRole.Link)
    pal = app.palette()                            # links readable in every skin
    pal.setColor(QPalette.ColorRole.Link, QColor(THEMES[name]["accent"]) if name in THEMES else _native_link)
    if name in THEMES:
        # areas the style sheet doesn't reach (scroll-area viewports, docks) take these palette colours
        p = THEMES[name]
        R = QPalette.ColorRole
        for role, key in ((R.Window, "bg"), (R.WindowText, "text"), (R.Base, "inset"), (R.AlternateBase, "alt"),
                          (R.Text, "text"), (R.Button, "btn_bot"), (R.ButtonText, "text"),
                          (R.Highlight, "sel"), (R.HighlightedText, "sel_text"), (R.PlaceholderText, "dim"),
                          (R.ToolTipBase, "inset"), (R.ToolTipText, "text"), (R.Mid, "border"),
                          (R.LinkVisited, "accent")):
            pal.setColor(role, QColor(p[key]))
        for role in (R.WindowText, R.Text, R.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p["dim"]))
    elif _native_palette is not None:
        pal = QPalette(_native_palette)
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(name) + _extra_qss(name))
    return name


def _extra_qss(name: str) -> str:
    """Rules for MusicMaid widgets Spindle doesn't have (split toolbar buttons like Auto-Tag ▾)."""
    if name not in THEMES:
        return ""
    p = THEMES[name]
    icons = _icons(name, p)
    return """
QToolButton[popupMode="1"] { padding-right: 16px; }
QToolButton::menu-button { border: none; border-left: 1px solid %(border)s; width: 14px; background: transparent; }
QToolButton::menu-button:hover { background: %(btn_top)s; }
QToolButton::menu-arrow { image: url("%(down)s"); width: 9px; height: 9px; }
QToolBar#selection-bar { spacing: 3px; }
QToolBar#selection-bar QToolButton { padding: 1px 7px; min-height: 20px; }
""" % dict(p, down=icons.get("down", ""))


_native_link = None
_native_palette = None
