import os

import pytest

from musicmaid import pathtags
from musicmaid.db import Track

ROOT = os.path.join(os.sep, "music")


def T(rel, **tags):
    path = os.path.join(ROOT, *rel.split("/"))
    return Track(id=1, path=path, folder=os.path.dirname(path), tags=tags)


@pytest.mark.parametrize("pattern,rel,expected", [
    ("%artist%/%album%/%track% - %title%", "Radiohead/OK Computer/02 - Paranoid Android.mp3",
     {"artist": "Radiohead", "album": "OK Computer", "tracknumber": "2", "title": "Paranoid Android"}),
    ("%artist%/%album% (%year%)/%track% - %title%", "Radiohead/Kid A (2000)/01 - Everything.flac",
     {"artist": "Radiohead", "album": "Kid A", "date": "2000", "tracknumber": "1", "title": "Everything"}),
    ("%artist%/%year% - %album%/%track% - %title%", "Daft Punk/2001 - Discovery/03 - Digital_Love.mp3",
     {"artist": "Daft Punk", "date": "2001", "album": "Discovery", "tracknumber": "3", "title": "Digital Love"}),
    ("%artist%/%album%/CD%disc%/%track% - %title%", "Box/Set/CD2/07 - Song.mp3",
     {"artist": "Box", "album": "Set", "discnumber": "2", "tracknumber": "7", "title": "Song"}),
    ("%ignore%/%album%/%title%", "x/Album/Song.mp3", {"album": "Album", "title": "Song"}),
])
def test_patterns(pattern, rel, expected):
    assert pathtags.guess(T(rel), [ROOT], pattern) == expected


def test_pattern_must_match_and_be_valid():
    assert pathtags.guess(T("Loose.mp3"), [ROOT], "%artist%/%album%/%title%") == {}       # too few levels
    assert pathtags.guess(T("A/B/no number.mp3"), [ROOT], "%artist%/%album%/%track% - %title%") == {}
    with pytest.raises(ValueError):
        pathtags.compile_pattern("%artist%/%nonsense%")
    with pytest.raises(ValueError):
        pathtags.compile_pattern("just text")


def test_automatic_guess_and_overwrite_rules():
    t = T("Radiohead/OK Computer (1997)/02 Paranoid Android.mp3", title="Track 2", tracknumber="2/12")
    g = pathtags.guess(t, [ROOT])
    assert g["artist"] == "Radiohead" and g["album"] == "OK Computer" and g["date"] == "1997"
    only_empty = pathtags.changes(t, g, overwrite=False)
    assert "title" not in only_empty and "tracknumber" not in only_empty and only_empty["artist"] == "Radiohead"
    assert pathtags.changes(t, g, overwrite=True)["title"] == "Paranoid Android"


def test_library_creates_reviewable_proposals(home, tmp_path):
    from musicmaid.library import Library
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from conftest import make_audio
    f = make_audio(tmp_path / "lib" / "Massive Attack" / "Mezzanine" / "03 - Teardrop.mp3", 3, 3)
    lib = Library()
    lib.add_folder(str(tmp_path / "lib"))
    lib.scan()
    ids = [t.id for t in lib.view("all")]
    assert lib.tags_from_paths(ids, pattern="%artist%/%album%/%track% - %title%") == 1
    p = lib.db.proposal(ids[0])
    assert p.tags == {"artist": "Massive Attack", "album": "Mezzanine", "tracknumber": "3", "title": "Teardrop"}
    assert p.score < lib.settings.auto_apply_threshold          # always reviewed, never auto-applied


def test_partial_apply_keeps_unticked_changes_proposed(home, tmp_path):
    from musicmaid import tags as tagio
    from musicmaid.library import Library
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from conftest import make_audio
    f = make_audio(tmp_path / "lib" / "Portishead" / "Dummy" / "04 - Glory Box.mp3", 4, 3)
    lib = Library()
    lib.add_folder(str(tmp_path / "lib"))
    lib.scan()
    tid = lib.view("all")[0].id
    lib.tags_from_paths([tid], pattern="%artist%/%album%/%track% - %title%")
    res = lib.apply([tid], exclude={tid: {"album"}})
    assert res.written == 1
    written = tagio.read(f).tags
    assert written["artist"] == "Portishead" and written["title"] == "Glory Box" and "album" not in written
    assert lib.db.proposal(tid).tags == {"album": "Dummy"}            # still waiting for review
