"""Rename and move files into a folder structure built from their tags."""
from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

from .db import Track
from .textutil import first_int, sanitize_component, year_of

SIDE_CAR_EXTS = {".lrc", ".cue", ".txt"}
FOLDER_IMAGES = {"cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "albumart.jpg"}

PATTERN_HELP = (
    "Fields: {title} {artist} {album} {albumartist} {year} {date} {genre} {tracknumber} {discnumber} "
    "{totaltracks} {totaldiscs} {disc_prefix} {composer} {label} {codec} {bitrate} {artist_initial}, "
    "{current_folder} (keep the current folders) and {current_name} (keep the current file name). "
    "Numbers accept format specs, e.g. {tracknumber:02}. Use / for folders."
)


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


class _Formatter(string.Formatter):
    def format_field(self, value, spec):
        if spec and isinstance(value, str):
            # numeric spec on a missing/textual value -> fall back to plain text
            try:
                return format(int(value), spec)
            except ValueError:
                return value
        return super().format_field(value, spec)


_fmt = _Formatter()


def template_values(t: Track, various_artists: str = "Various Artists") -> dict:
    g = t.tags.get
    artist = g("artist") or "Unknown Artist"
    albumartist = g("albumartist") or artist
    if g("compilation") in ("1", "true") and not g("albumartist"):
        albumartist = various_artists
    disc = first_int(g("discnumber")) or 1
    tdisc = first_int(g("totaldiscs")) or 1
    track = first_int(g("tracknumber"))
    v = _SafeDict(
        title=g("title") or Path(t.path).stem,
        artist=artist,
        albumartist=albumartist,
        album=g("album") or "Unknown Album",
        year=year_of(g("originaldate")) or year_of(g("date")) or "",
        date=g("date"),
        genre=(g("genre") or "").split(";")[0].strip(),
        tracknumber=track if track is not None else "",
        discnumber=disc,
        totaltracks=first_int(g("totaltracks")) or "",
        totaldiscs=tdisc,
        disc_prefix=f"{disc}-" if tdisc > 1 or disc > 1 else "",
        composer=g("composer"),
        label=g("label"),
        codec=t.codec,
        bitrate=t.bitrate,
        artist_initial=(re.sub(r"^the\s+", "", albumartist, flags=re.I).strip()[:1] or "_").upper(),
    )
    return v


def render(pattern: str, t: Track, various_artists: str = "Various Artists", root: str | None = None) -> str:
    values = template_values(t, various_artists)
    values["current_name"] = Path(t.path).stem
    parts = []
    for comp in pattern.replace("\\", "/").split("/"):
        if not comp:
            continue
        if comp == "{current_folder}":
            # the track's folder path below its library folder, kept as it is
            try:
                rel = Path(t.folder).relative_to(root) if root else Path(Path(t.folder).name)
            except ValueError:
                rel = Path(Path(t.folder).name)
            parts.extend(p for p in rel.parts if p not in ("", "."))
            continue
        s = _fmt.vformat(comp, (), values)
        # tidy leftovers of empty fields: "()" "[]" leading/trailing separators
        s = re.sub(r"\(\s*\)|\[\s*\]", "", s)
        s = re.sub(r"(\S)-\s+-\s+", r"\1-", s)  # "2-" + "" + " - Title" -> "2-Title"
        s = re.sub(r"\s+-\s+-\s+", " - ", s)
        s = re.sub(r"^\s*[-–.]\s*|\s*[-–]\s*$", "", s).strip()
        parts.append(sanitize_component(s))
    if not parts:
        parts = [sanitize_component(Path(t.path).stem)]
    return "/".join(parts) + Path(t.path).suffix.lower()


@dataclass
class Move:
    track: Track
    src: str
    dst: str

    @property
    def changed(self) -> bool:
        return os.path.normcase(os.path.abspath(self.src)) != os.path.normcase(os.path.abspath(self.dst))


class _CaseFolder:
    """Re-use the casing of folders that already exist (or are already planned).

    Avoids 'RADIOHEAD/' next to 'Radiohead/' - which is the same folder on Windows.
    """

    def __init__(self, root: Path):
        self.root = root
        self.known: dict[str, str] = {}

    def resolve(self, rel_dirs: list[str]) -> Path:
        cur = self.root
        for comp in rel_dirs:
            key = os.path.normcase(str(cur / comp)).lower()
            if key not in self.known:
                actual = comp
                try:
                    for entry in os.scandir(cur):
                        if entry.is_dir() and entry.name.lower() == comp.lower():
                            actual = entry.name
                            break
                except OSError:
                    pass
                self.known[key] = actual
            cur = cur / self.known[key]
        return cur


def plan(tracks: list[Track], pattern: str, destination: str, various_artists: str = "Various Artists",
         taken: set[str] | None = None) -> list[Move]:
    dest = Path(destination)
    folders = _CaseFolder(dest)
    taken = taken if taken is not None else set()
    moves = []
    for t in tracks:
        rel = render(pattern, t, various_artists, str(dest))
        parts = rel.split("/")
        base = folders.resolve(parts[:-1])
        name = parts[-1]
        target = base / name
        key = os.path.normcase(str(target)).lower()
        n = 2
        while key in taken or (target.exists() and os.path.normcase(str(target)) != os.path.normcase(t.path)):
            target = base / (Path(name).stem + f" ({n})" + Path(name).suffix)
            key = os.path.normcase(str(target)).lower()
            n += 1
        taken.add(key)
        moves.append(Move(track=t, src=t.path, dst=str(target)))
    return moves


def sidecars(path: str) -> list[str]:
    p = Path(path)
    return [str(p.with_suffix(e)) for e in SIDE_CAR_EXTS if p.with_suffix(e).exists()]


def remove_empty_dirs(start: str, stop_at: list[str]) -> None:
    """Delete now-empty folders upward from start, never crossing a library root."""
    stops = {os.path.normcase(os.path.abspath(s)) for s in stop_at}
    d = Path(start)
    while os.path.normcase(os.path.abspath(d)) not in stops and d.parent != d:
        try:
            leftovers = list(d.iterdir())
        except OSError:
            return
        junk = [x for x in leftovers if x.name.lower() in ("thumbs.db", "desktop.ini", ".ds_store")]
        if len(junk) != len(leftovers):
            return
        for j in junk:
            try:
                j.unlink()
            except OSError:
                return
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent
