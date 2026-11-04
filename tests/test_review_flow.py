import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from conftest import make_audio  # noqa: E402

from musicmaid import tags as tagio  # noqa: E402
from musicmaid.library import Library  # noqa: E402


def _lib(tmp_path):
    root = tmp_path / "music"
    a = make_audio(root / "Air" / "Moon Safari" / "01 - La Femme.mp3", 1, 3,
                   ("-metadata", "artist=AIR", "-metadata", "title=la femme", "-metadata", "album=moon safari",
                    "-metadata", "track=1"))
    b = make_audio(root / "Air" / "Moon Safari" / "02 - Sexy Boy.mp3", 2, 3,
                   ("-metadata", "artist=AIR", "-metadata", "title=sexy boy", "-metadata", "album=moon safari",
                    "-metadata", "track=2"))
    c = make_audio(root / "Loose" / "something.mp3", 3, 3)
    lib = Library()
    lib.add_folder(str(root))
    lib.scan()
    return lib, root, (a, b, c)


def test_typed_new_values_only_touch_selected(home, tmp_path):
    lib, _, (a, b, _c) = _lib(tmp_path)
    ta = lib.db.track_by_path(str(a))
    lib.set_new_value([ta.id], "genre", "Electronic")
    assert lib.db.proposal(ta.id).tags == {"genre": "Electronic"}
    lib.set_new_value([ta.id], "genre", "")             # back to the original (empty): change dropped
    assert lib.db.proposal(ta.id) is None
    lib.set_new_value([ta.id], "genre", "Electronic")
    lib.apply([ta.id])
    assert tagio.read(a).tags["genre"] == "Electronic" and "genre" not in tagio.read(b).tags


def test_fix_library_proposes_only_and_groups_by_album(home, tmp_path):
    lib, root, (a, b, c) = _lib(tmp_path)
    ids = [t.id for t in lib.view("all")]
    res = lib.fix_library(ids, lookup=False, artwork=False)
    assert res["waiting"] >= 2
    assert tagio.read(a).tags["title"] == "la femme"          # nothing written yet
    groups = dict(lib.review_groups("album"))
    album = [k for k in groups if "Moon Safari" in k]
    assert album and len(groups[album[0]]) == 2
    by_folder = dict(lib.review_groups("folder"))
    assert str(root / "Air" / "Moon Safari") in by_folder


def test_organize_keep_folders_or_names(home, tmp_path):
    lib, root, (a, b, c) = _lib(tmp_path)
    ids = [lib.db.track_by_path(str(a)).id]
    keep_folders = lib.organize_plan(ids, "{current_folder}/{tracknumber:02}. {title}")
    assert keep_folders[0].dst == str(root / "Air" / "Moon Safari" / "01. la femme.mp3")
    keep_names = lib.organize_plan(ids, "{albumartist}/{album} ({year})/{current_name}", str(root))
    # existing "Air/Moon Safari" folders are reused rather than creating "AIR/moon safari" next to them
    assert keep_names[0].dst == str(root / "Air" / "Moon Safari" / "01 - La Femme.mp3")


def test_folder_images_are_found_and_used(home, tmp_path):
    from PIL import Image
    lib, root, (a, b, c) = _lib(tmp_path)
    album = root / "Air" / "Moon Safari"
    Image.new("RGB", (300, 300), "red").save(album / "back.jpg")
    Image.new("RGB", (900, 900), "blue").save(album / "Folder.jpg")
    (album / "notes.txt").write_text("not an image")
    imgs = lib.folder_images(str(album))
    assert [os.path.basename(p) for p, _, _ in imgs] == ["Folder.jpg", "back.jpg"]   # the likely cover first
    assert imgs[0][1:] == (900, 900)
    ids = [lib.db.track_by_path(str(a)).id, lib.db.track_by_path(str(b)).id]
    lib.use_folder_image(ids, imgs[0][0])
    p = lib.db.proposal(ids[0])
    assert p.art_source == "folder: Folder.jpg" and p.art == (album / "Folder.jpg").read_bytes()
