"""Group tracks into a folder tree (library folders at the top), shared by the GUI and the TUI."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .db import Track
from .textutil import first_int


@dataclass
class FolderNode:
    path: str                    # absolute folder path
    name: str                    # what the tree shows
    count: int = 0               # tracks in this folder and everything below it
    flagged: int = 0             # of those, how many the caller flagged (e.g. tracks with problems)
    children: list["FolderNode"] = field(default_factory=list)

    def find(self, path: str) -> "FolderNode | None":
        if self.path == path:
            return self
        for c in self.children:
            if path == c.path or path.startswith(c.path.rstrip(os.sep) + os.sep):
                return c.find(path)
        return None


def _norm(p: str) -> str:
    return os.path.normpath(p)


def build(tracks: list[Track], roots: list[str], flag=None) -> list[FolderNode]:
    """One node per library folder (plus one per outside folder), with nested subfolders.

    Only folders that contain tracks (directly or below) appear. Chains of folders that hold nothing but a
    single subfolder are kept as they are, so the tree mirrors the disk exactly.
    """
    roots = sorted({_norm(r) for r in roots}, key=len, reverse=True)   # deepest root wins
    top: dict[str, FolderNode] = {}
    index: dict[str, FolderNode] = {}

    def node_for(folder: str) -> FolderNode:
        if folder in index:
            return index[folder]
        root = next((r for r in roots if folder == r or folder.startswith(r.rstrip(os.sep) + os.sep)), None)
        if root is None or folder == root:
            n = FolderNode(folder, folder if root is None else (os.path.basename(root) or root))
            index[folder] = top[folder] = n
            return n
        parent = node_for(os.path.dirname(folder))
        n = FolderNode(folder, os.path.basename(folder))
        parent.children.append(n)
        index[folder] = n
        return n

    per_folder: dict[str, list[int]] = {}
    for t in tracks:
        c = per_folder.setdefault(t.folder, [0, 0])
        c[0] += 1
        if flag and flag(t):
            c[1] += 1
    for folder, (count, flagged) in per_folder.items():
        n = node_for(_norm(folder))
        # count this folder's tracks on its node and every ancestor
        while True:
            n.count += count
            n.flagged += flagged
            parent = os.path.dirname(n.path)
            if n.path in top or parent == n.path:
                break
            n = index[parent]

    def sort(nodes: list[FolderNode]) -> list[FolderNode]:
        nodes.sort(key=lambda n: n.name.casefold())
        for n in nodes:
            sort(n.children)
        return nodes
    return sort(list(top.values()))


def in_folder(tracks: list[Track], folder: str | None) -> list[Track]:
    """Tracks in folder or below (all tracks when folder is None)."""
    if not folder:
        return tracks
    f = _norm(folder)
    prefix = f.rstrip(os.sep) + os.sep
    return [t for t in tracks if _norm(t.folder) == f or _norm(t.folder).startswith(prefix)]


def album_order(t: Track) -> tuple:
    """Sort key: folder, then disc and track number, then file name, so albums read in order."""
    name = Path(t.path).name
    track = first_int(t.get("tracknumber")) or first_int(name) or 0   # "02 Song.mp3" without a tag
    return (_norm(t.folder).casefold(), first_int(t.get("discnumber")) or 0, track, name.casefold())
