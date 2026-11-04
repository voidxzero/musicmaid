"""Fill in tags from folder and file names.

Two ways:
* automatic: guesses from common layouts such as ``Artist/Album (Year)/01 - Title`` or ``Artist - Album/Title``
  (the same rules Clean up uses for empty fields, but here they can also overwrite);
* a pattern such as ``%artist%/%album% (%year%)/%track% - %title%``, matched against the end of each file's
  path (relative to its library folder, without the extension).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .db import Proposal, Track
from .textutil import clean_whitespace, parse_filename

FIELDS = {
    "artist": "artist", "albumartist": "albumartist", "album": "album", "title": "title", "genre": "genre",
    "year": "date", "date": "date", "track": "tracknumber", "tracknumber": "tracknumber",
    "disc": "discnumber", "discnumber": "discnumber", "composer": "composer", "comment": "comment",
    "ignore": None, "dummy": None,
}
PATTERN_HELP = ("Placeholders: %artist% %albumartist% %album% %year% %track% %disc% %title% %genre% %composer% "
                "and %ignore% for parts to skip. Use / between folder levels; the pattern matches the end of "
                "the path, e.g. %artist%/%album% (%year%)/%track% - %title%")
EXAMPLES = [
    "%artist%/%album%/%track% - %title%",
    "%artist%/%album% (%year%)/%track% - %title%",
    "%artist%/%year% - %album%/%track% - %title%",
    "%artist% - %album%/%track% - %title%",
    "%albumartist%/%album%/%track% - %artist% - %title%",
    "%artist%/%album%/CD%disc%/%track% - %title%",
]


def compile_pattern(pattern: str) -> tuple[re.Pattern, int]:
    """Regex for a pattern, and how many path levels it covers. Raises ValueError for a bad pattern."""
    pattern = pattern.strip().strip("/").replace("\\", "/")
    if not pattern:
        raise ValueError("the pattern is empty")
    out, pos, seen = [], 0, set()
    for m in re.finditer(r"%(\w+)%", pattern):
        out.append(re.escape(pattern[pos:m.start()]).replace("/", "/"))
        name = m.group(1).lower()
        if name not in FIELDS:
            raise ValueError(f"unknown placeholder %{name}%")
        field = FIELDS[name]
        if field is None:
            out.append(r"[^/]*?")
        else:
            group = name if name not in seen else f"{name}_{len(seen)}"
            seen.add(name)
            if field in ("tracknumber", "discnumber"):
                out.append(rf"(?P<{group}>\d+)")
            elif name == "year":
                out.append(rf"(?P<{group}>\d{{4}})")
            else:
                out.append(rf"(?P<{group}>[^/]+?)")
        pos = m.end()
    out.append(re.escape(pattern[pos:]))
    if not seen:
        raise ValueError("the pattern has no placeholders")
    return re.compile("".join(out) + r"$", re.I), pattern.count("/") + 1


def _relative_parts(path: str, root: str | None) -> list[str]:
    p = Path(path)
    parts = list(p.with_suffix("").parts)
    if root:
        try:
            parts = list(p.with_suffix("").relative_to(root).parts)
        except ValueError:
            pass
    return parts


def from_pattern(path: str, pattern: str, root: str | None = None, compiled=None) -> dict[str, str]:
    rx, levels = compiled or compile_pattern(pattern)
    parts = _relative_parts(path, root)
    if len(parts) < levels:
        return {}
    m = rx.fullmatch("/".join(parts[-levels:]))
    if not m:
        return {}
    out = {}
    for group, val in m.groupdict().items():
        if val is None:
            continue
        field = FIELDS[group.split("_")[0]]
        val = clean_whitespace(val.replace("_", " "))
        if field in ("tracknumber", "discnumber"):
            val = str(int(val))
        if val:
            out[field] = val
    return out


def guess(track: Track, roots: list[str], pattern: str | None = None, compiled=None) -> dict[str, str]:
    from .cleanup import library_root
    root = library_root(track.path, roots)
    if pattern:
        return from_pattern(track.path, pattern, root, compiled)
    return parse_filename(track.path, root)


def changes(track: Track, guessed: dict[str, str], overwrite: bool) -> dict[str, str]:
    """The tag changes guessed would make: only empty fields unless overwrite."""
    out = {}
    for k, v in guessed.items():
        cur = track.tags.get(k, "")
        if k == "tracknumber" and cur.split("/")[0].lstrip("0") == v:
            continue
        if v and v != cur and (overwrite or not cur):
            out[k] = v
    return out


def propose(db, tracks: list[Track], roots: list[str], pattern: str | None = None, overwrite: bool = False,
            task=None) -> int:
    compiled = compile_pattern(pattern) if pattern else None
    n = 0
    for i, t in enumerate(tracks):
        if task is not None:
            task.progress(i, len(tracks), f"Reading folder names: {os.path.basename(t.path)}")
        ch = changes(t, guess(t, roots, pattern, compiled), overwrite)
        if ch:
            db.set_proposal(Proposal(track_id=t.id, tags=ch, source="Folder names", score=0.8,
                                     note=f"from the path ({pattern or 'automatic'})"))
            n += 1
    return n
