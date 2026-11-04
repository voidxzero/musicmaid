import os

from musicmaid import foldertree
from musicmaid.db import Track

ROOT = os.path.join(os.sep, "music")


def T(i, rel, **tags):
    path = os.path.join(ROOT, rel)
    return Track(id=i, path=path, folder=os.path.dirname(path), tags=tags)


TRACKS = [
    T(1, "Radiohead/OK Computer/02 Paranoid Android.mp3"),               # no track tag: number from the name
    T(2, "Radiohead/OK Computer/01 Airbag.mp3", tracknumber="1"),
    T(3, "Radiohead/Kid A/Kid A.mp3", tracknumber="2/10"),
    T(4, "Radiohead/Kid A/Everything.mp3", tracknumber="1"),
    T(5, "Loose song.mp3"),
    T(6, "Box Set/CD2/01 B.flac", discnumber="2", tracknumber="1"),
    T(7, "Box Set/CD1/01 A.flac", discnumber="1", tracknumber="1"),
]


def test_tree_mirrors_folders_with_counts():
    (root,) = foldertree.build(TRACKS, [ROOT])
    assert root.name == "music" and root.count == 7
    names = [(c.name, c.count) for c in root.children]
    assert names == [("Box Set", 2), ("Radiohead", 4)]
    rh = root.children[1]
    assert [(c.name, c.count) for c in rh.children] == [("Kid A", 2), ("OK Computer", 2)]
    assert root.find(os.path.join(ROOT, "Radiohead", "Kid A")).count == 2


def test_tracks_outside_library_folders_get_their_own_node():
    stray = Track(id=9, path=os.path.join(os.sep, "elsewhere", "x.mp3"), folder=os.path.join(os.sep, "elsewhere"))
    nodes = foldertree.build(TRACKS + [stray], [ROOT])
    assert [n.path for n in nodes] == [os.path.join(os.sep, "elsewhere"), ROOT]


def test_nested_library_folders_use_the_deepest():
    sub = os.path.join(ROOT, "Radiohead")
    nodes = foldertree.build(TRACKS, [ROOT, sub])
    assert sorted(n.name for n in nodes) == ["Radiohead", "music"]
    assert next(n for n in nodes if n.name == "music").count == 3


def test_in_folder_includes_subfolders_but_not_lookalikes():
    rh = os.path.join(ROOT, "Radiohead")
    assert {t.id for t in foldertree.in_folder(TRACKS, rh)} == {1, 2, 3, 4}
    lookalike = Track(id=10, path=os.path.join(ROOT, "Radiohead Live", "a.mp3"),
                      folder=os.path.join(ROOT, "Radiohead Live"))
    assert lookalike not in foldertree.in_folder(TRACKS + [lookalike], rh)
    assert len(foldertree.in_folder(TRACKS, None)) == len(TRACKS)


def test_album_order():
    order = [t.id for t in sorted(TRACKS, key=foldertree.album_order)]
    # loose files in the library folder first, then folders alphabetically; within a folder by disc, then
    # track number (from the tag, or the file name when there's no tag)
    assert order == [5, 7, 6, 4, 3, 2, 1]
    ok = [t.id for t in sorted(TRACKS[:2], key=foldertree.album_order)]
    assert ok == [2, 1]
