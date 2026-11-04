import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from conftest import make_audio  # noqa: E402

from musicmaid import config, tags as tagio  # noqa: E402
from musicmaid.db import Database  # noqa: E402
from musicmaid.library import Library  # noqa: E402


def _setup(tmp_path, cover_jpg):
    root = tmp_path / "music"
    f = make_audio(root / "Air" / "Moon Safari" / "01 la femme.mp3", 1, 3,
                   ("-metadata", "artist=air", "-metadata", "title=la femme", "-metadata", "album=Moon Safari",
                    "-metadata", "track=1"))
    tagio.write(f, {}, cover_jpg)
    lib = Library()
    lib.add_folder(str(root))
    lib.scan()
    return lib, root, f


def test_changes_are_logged_in_the_library_and_revertable_without_the_app_db(home, tmp_path, cover_jpg):
    lib, root, f = _setup(tmp_path, cover_jpg)
    tid = lib.db.track_by_path(str(f)).id
    lib.set_new_value([tid], "title", "La Femme d'Argent")
    lib.set_new_value([tid], "artist", "Air")
    lib.propose_artwork([tid], cover_jpg[:-2] + b"\xff\xd9", "test")
    lib.apply([tid])
    moves = [m for m in lib.organize_plan([tid], "{albumartist}/{album}/{tracknumber:02} - {title}", str(root))
             if m.changed]
    lib.organize(moves)
    new_path = moves[0].dst
    assert os.path.exists(new_path) and not f.exists()

    snaps = lib.snapshots()
    assert [s.label for s in snaps] == ["Organize files", "Apply changes"]
    folder = root / "MusicMaid" / "Snapshots"
    assert (root / "MusicMaid" / "README.txt").exists()
    text = snaps[1].text_path.read_text(encoding="utf-8")
    assert "Title: la femme -> La Femme d'Argent" in text and "Cover art: replaced" in text
    assert list((folder / "artwork").iterdir())                      # the old cover was kept
    lines = [json.loads(x) for x in snaps[0].path.read_text(encoding="utf-8").splitlines()]
    assert lines[1]["file"] == "Air/Moon Safari/01 la femme.mp3"     # relative to the library folder

    # MusicMaid reinstalled: a brand-new database, only the files in the library remain
    os.remove(lib.db.path)
    config._settings = None
    fresh = Library(db=Database(str(tmp_path / "fresh.db")))
    fresh.add_folder(str(root))
    fresh.scan()
    done, problems = fresh.revert_snapshots(fresh.snapshots())
    assert not problems and done == 2
    assert f.exists() and not os.path.exists(new_path)
    t = tagio.read(f)
    assert t.tags["title"] == "la femme" and t.tags["artist"] == "air"
    assert t.artwork.data == cover_jpg
    assert all(s.reverted for s in fresh.snapshots())
    assert not (root / "Air" / "Air").exists()                       # emptied folders were tidied


def test_app_undo_marks_snapshot_reverted_and_setting_turns_logging_off(home, tmp_path, cover_jpg):
    lib, root, f = _setup(tmp_path, cover_jpg)
    tid = lib.db.track_by_path(str(f)).id
    lib.set_new_value([tid], "genre", "Downtempo")
    res = lib.apply([tid])
    lib.undo(res.batch)
    assert lib.snapshots()[0].reverted and "genre" not in tagio.read(f).tags
    lib.settings.keep_change_log = False
    lib.set_new_value([tid], "genre", "Trip-hop")
    lib.apply([tid])
    assert len(lib.snapshots()) == 1
