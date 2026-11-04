"""End-to-end library operations on real (synthesized) audio files."""
import shutil

import pytest

from musicmaid import tags as tagio
from musicmaid.library import Library

from .conftest import make_audio, requires_ffmpeg

FORMATS = [("mp3", ("-b:a", "128k")), ("flac", ()), ("ogg", ()), ("opus", ()), ("m4a", ()), ("wma", ()),
           ("wav", ()), ("aiff", ()), ("wv", ())]


@requires_ffmpeg
@pytest.mark.parametrize("ext,args", FORMATS)
def test_tag_roundtrip(tmp_path, cover_jpg, ext, args):
    f = make_audio(tmp_path / f"t.{ext}", seconds=3, args=args)
    tagio.write(f, {"title": "Héllo", "artist": "Art", "album": "Alb", "tracknumber": "3", "totaltracks": "12",
                    "discnumber": "1", "totaldiscs": "2", "date": "1999", "musicbrainz_recordingid": "abc",
                    "comment": "hi"}, cover_jpg)
    d = tagio.read(f)
    assert d.tags["title"] == "Héllo" and d.tags["tracknumber"] == "3" and d.tags["totaltracks"] == "12"
    assert d.tags["totaldiscs"] == "2" and d.tags["musicbrainz_recordingid"] == "abc"
    assert d.artwork and (d.artwork.width, d.artwork.height) == (600, 600)
    tagio.write(f, {"comment": None}, None)
    d = tagio.read(f)
    assert "comment" not in d.tags and d.artwork is None and d.tags["title"] == "Héllo"


@pytest.fixture
def library(tmp_path, home, cover_jpg):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    root = tmp_path / "music"
    a = make_audio(root / "Radiohead" / "OK Computer" / "01 - Airbag.mp3", 1, 30, ("-b:a", "192k"))
    tagio.write(a, {"title": "Airbag", "artist": "Radiohead", "album": "OK Computer", "tracknumber": "1"}, cover_jpg)
    b = make_audio(root / "Radiohead" / "OK Computer" / "02 - x.mp3", 2, 30, ("-b:a", "192k"))
    tagio.write(b, {"title": "PARANOID ANDROID", "artist": "RADIOHEAD", "album": "OK Computer", "tracknumber": "02"})
    make_audio(root / "Backup" / "airbag.flac", 1, 30)  # same audio as a, lossless, untagged
    c = make_audio(root / "Downloads" / "Airbag [www.junk.com].mp3", 1, 30, ("-b:a", "96k"))
    tagio.write(c, {"title": "Airbag (www.junk.com)", "artist": "Radiohead", "comment": "get it at www.junk.com"})
    lib = Library()
    lib.add_folder(str(root))
    lib.scan()
    return lib, root


def test_scan_and_views(library):
    lib, root = library
    counts = lib.counts()
    assert counts["all"] == 4 and counts["untagged"] == 1 and counts["noart"] == 3


def test_cleanup_apply_undo(library):
    lib, root = library
    ids = [t.id for t in lib.tracks()]
    assert lib.cleanup(ids) >= 2
    pa = lib.db.track_by_path(str(root / "Radiohead" / "OK Computer" / "02 - x.mp3"))
    prop = lib.db.proposal(pa.id)
    assert prop.tags["title"] == "Paranoid Android" and prop.tags["artist"] == "Radiohead"
    assert prop.tags["tracknumber"] == "2" and prop.tags["albumartist"] == "Radiohead"
    junk = lib.db.track_by_path(str(root / "Downloads" / "Airbag [www.junk.com].mp3"))
    assert lib.db.proposal(junk.id).tags == {"title": "Airbag", "comment": ""}

    res = lib.apply([pa.id, junk.id])
    assert res.written == 2
    assert tagio.read(pa.path).tags["title"] == "Paranoid Android"
    assert "comment" not in tagio.read(junk.path).tags
    lib.undo(res.batch)
    assert tagio.read(pa.path).tags["title"] == "PARANOID ANDROID"
    assert tagio.read(junk.path).tags["comment"] == "get it at www.junk.com"


@pytest.mark.skipif(not shutil.which("fpcalc"), reason="fpcalc not installed")
def test_duplicates_quarantine_and_undo(library):
    lib, root = library
    groups = lib.find_duplicates()
    assert len(groups) == 1
    g = groups[0]
    assert len(g.tracks) == 3 and g.keep.codec == "flac"  # lossless copy is kept
    remove = {t.id: g.keep.id for t in g.extras}
    n, batch = lib.remove_duplicates(list(remove), remove)
    assert n == 2 and lib.counts()["all"] == 2
    # the untagged FLAC inherits tags + artwork from its better-tagged duplicate
    p = lib.db.proposal(g.keep.id)
    assert p.tags["title"] == "Airbag" and p.tags["album"] == "OK Computer" and p.art
    assert not (root / "Downloads" / "Airbag [www.junk.com].mp3").exists()
    lib.undo(batch)
    assert (root / "Downloads" / "Airbag [www.junk.com].mp3").exists() and lib.counts()["all"] == 4


def test_organize_and_undo(library):
    lib, root = library
    ids = [t.id for t in lib.tracks()]
    moves = [m for m in lib.organize_plan(ids, "{albumartist}/{album}/{tracknumber:02} - {title}", str(root))
             if m.changed]
    # untagged flac is skipped, the rest is renamed
    assert {m.dst.replace(str(root), "") for m in moves} == {
        "/Radiohead/OK Computer/02 - PARANOID ANDROID.mp3",
        "/Radiohead/Unknown Album/Airbag (www.junk.com).mp3",
    }
    n, batch = lib.organize(moves)
    assert n == 2 and not (root / "Downloads").exists()  # emptied folder removed
    assert lib.db.track_by_path(str(root / "Radiohead" / "OK Computer" / "02 - PARANOID ANDROID.mp3"))
    lib.undo(batch)
    assert (root / "Downloads" / "Airbag [www.junk.com].mp3").exists()
    assert (root / "Radiohead" / "OK Computer" / "02 - x.mp3").exists()


def test_txxx_comment_is_read_and_replaced(tmp_path):
    from mutagen.id3 import ID3, TXXX
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from conftest import make_audio
    from musicmaid import tags as tagio
    f = make_audio(tmp_path / "a.mp3", 1, 2)
    t = ID3(f)
    t.add(TXXX(encoding=3, desc="comment", text=["ripped by www.example.com"]))
    t.save()
    assert tagio.read(f).tags["comment"] == "ripped by www.example.com"
    tagio.write(f, {"comment": ""})
    assert "comment" not in tagio.read(f).tags and not ID3(f).getall("TXXX:comment")
