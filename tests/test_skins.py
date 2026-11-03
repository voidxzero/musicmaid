"""Skin files: bundled skins load, bad files are rejected with a reason, import/export round-trips."""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import mock

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from musicmaid.gui import skins as themes        # noqa: E402


def _bad(data, word):
    try:
        themes.parse_skin(data)
    except ValueError as e:
        assert word in str(e), (word, str(e))
        return
    raise AssertionError(f"accepted: {data}")


def test_bundled_skins_load():
    files = sorted(themes.bundled_skin_dir().glob("*.json"))
    assert files, "musicmaid/skins/ has no skins"
    for f in files:
        name, pal = themes.parse_skin(json.loads(f.read_text(encoding="utf-8")))
        assert all(k in pal for k in themes.COLOR_KEYS), (f.name, name)
        assert themes.stylesheet  # renders below
    themes.load_skins()
    assert not themes.skin_errors, themes.skin_errors


def test_parse_rules():
    name, pal = themes.parse_skin({"name": "Tiny", "base": "Amp Classic", "colors": {"accent": "#ff0000"}})
    assert pal["accent"] == "#ff0000" and pal["bg"] == themes.THEMES["Amp Classic"]["bg"]
    name, pal = themes.parse_skin({"name": "Square", "corners": {"r": 0, "r_panel": 0}, "font_size": 8,
                                   "style": "classic98", "caption": "#000080"})
    assert pal["r"] == "0px" and pal["font_size"] == "8pt" and pal["style"] == "classic98"
    _bad({"colors": {}}, "name")
    _bad({"name": "X", "colors": {"accent": "red"}}, "#rrggbb")
    _bad({"name": "X", "colors": {"sparkle": "#ffffff"}}, "unknown colour")
    _bad({"name": "X", "base": "Nope"}, "base")
    _bad({"name": "X", "corners": {"r": 99}}, "corner")
    _bad({"name": "X", "font": "Tahoma; } * { background: url(/etc/passwd)"}, "font")
    _bad({"name": "X", "style": "glitter"}, "style")
    _bad({"name": "System"}, "System")
    _bad(["not", "an", "object"], "object")


def test_import_export_roundtrip():
    tmp = tempfile.mkdtemp()
    with mock.patch.object(themes, "user_skin_dir", lambda: themes.Path(tmp) / "skins"):
        src = os.path.join(tmp, "mine.json")
        json.dump({"name": "Amp Classic", "colors": {"accent": "#00ff00"}}, open(src, "w"))
        name = themes.import_skin(src)
        assert name == "Amp Classic (custom)", name           # can't replace a built-in skin
        assert themes.THEMES["Amp Classic"]["accent"] != "#00ff00"
        assert os.path.exists(os.path.join(tmp, "skins", "amp-classic.json"))
        out = os.path.join(tmp, "copy.json")
        themes.export_skin("Classic 98", out)
        data = json.load(open(out))
        assert data["style"] == "classic98" and len(data["colors"]) == len(themes.COLOR_KEYS)
        data["name"] = "My Retro"
        json.dump(data, open(out, "w"))
        assert themes.import_skin(out) == "My Retro"
        qss = themes.stylesheet("My Retro")
        assert "w98_raised" in qss and "border-radius: 0px" in qss
        bad = os.path.join(tmp, "bad.json")
        open(bad, "w").write("{ not json")
        try:
            themes.import_skin(bad)
            raise AssertionError("accepted a broken file")
        except ValueError as e:
            assert "couldn't read" in str(e)
    themes.load_skins()                                       # back to the real skins



def test_every_skin_renders_and_applies(home):
    """Each skin produces a style sheet whose images exist, and applying it sets the app palette."""
    import re
    from pathlib import Path
    for name in themes.theme_names():
        qss = themes.stylesheet(name)
        for url in re.findall(r'url\("([^"]+)"\)', qss):
            assert Path(url).is_file(), (name, url)
        assert str(home) in qss or name == themes.SYSTEM     # generated images go to MusicMaid's data dir
        assert themes.apply(name) == name
        if name != themes.SYSTEM:
            assert app.palette().color(app.palette().ColorRole.Window).name() == themes.THEMES[name]["bg"]
    assert themes.apply("No Such Skin") == themes.DEFAULT_SKIN


def test_spindle_skin_files_work_unchanged():
    data = json.loads((themes.bundled_skin_dir() / "vapor-dusk.json").read_text(encoding="utf-8"))
    assert data["spindle_skin"] == 1
    assert themes.parse_skin(data)[0] == "Vapor Dusk"
