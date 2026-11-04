"""Change snapshots kept inside the music library itself.

Every change MusicMaid makes (tag writes, renames/moves, created files, files moved to quarantine) is
recorded as it happens in ``<library folder>/MusicMaid/Snapshots/``:

* ``<when>_<what>_<id>.jsonl`` - one JSON object per line, enough to revert the change, even after a
  reinstall or on another computer (paths are stored relative to the library folder);
* ``<when>_<what>_<id>.txt``   - the same changes in plain words, for people;
* ``artwork/<hash>.<ext>``     - cover art as it was before it was replaced (stored once per image);
* ``<when>_<what>_<id>.reverted`` - present once that snapshot has been reverted.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

FOLDER = "MusicMaid"
SUB = "Snapshots"
VERSION = 1
FIELD_LABELS = None   # filled lazily from tags.FIELD_LABELS

README = """This folder was made by MusicMaid (https://github.com/voidxzero/musicmaid).

Snapshots/ holds a record of every change MusicMaid made to the music in this folder:
  *.txt        what was changed, in plain words (old -> new)
  *.jsonl      the same, in a form MusicMaid can use to put things back
  artwork/     cover art as it was before MusicMaid replaced it
  *.reverted   marks a snapshot that has been reverted

To go back, open MusicMaid and use Undo / History (or: musicmaid-cli snapshots, musicmaid-cli revert).
It's safe to delete old snapshots you no longer need; MusicMaid itself never deletes them.
"""


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40] or "changes"


def _labels() -> dict:
    global FIELD_LABELS
    if FIELD_LABELS is None:
        from .tags import FIELD_LABELS as fl
        FIELD_LABELS = fl
    return FIELD_LABELS


def _image_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".img"


class Recorder:
    """Receives journal entries from the database and writes them into the library's MusicMaid folder."""

    def __init__(self, roots_fn, enabled_fn=lambda: True):
        self.roots_fn = roots_fn
        self.enabled_fn = enabled_fn
        self._files: dict[tuple[str, str], Path] = {}
        self._lock = threading.Lock()
        self.errors: list[str] = []

    def root_of(self, path: str | None) -> str | None:
        if not path:
            return None
        best = None
        for r in self.roots_fn():
            r2 = r.rstrip("/\\")
            if (path == r2 or path.startswith(r2 + os.sep) or path.startswith(r2 + "/")) and \
                    (best is None or len(r2) > len(best)):
                best = r2
        return best

    @staticmethod
    def rel(path: str | None, root: str) -> str | None:
        if not path:
            return None
        try:
            return Path(path).relative_to(root).as_posix()
        except ValueError:
            return None

    def _snapshot_base(self, root: str, batch: str, label: str, ts: float) -> Path:
        key = (root, batch)
        if key not in self._files:
            folder = Path(root) / FOLDER / SUB
            folder.mkdir(parents=True, exist_ok=True)
            readme = Path(root) / FOLDER / "README.txt"
            if not readme.exists():
                readme.write_text(README, encoding="utf-8")
            stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts))
            base = folder / f"{stamp}_{_slug(label)}_{batch}"
            from . import __version__
            header = {"type": "snapshot", "version": VERSION, "batch": batch, "label": label, "created": ts,
                      "app": f"MusicMaid {__version__}", "library": root}
            with open(base.with_suffix(".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
            with open(base.with_suffix(".txt"), "a", encoding="utf-8") as f:
                f.write(f"MusicMaid change log - {label}\n{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}"
                        f" - library folder: {root}\n(revert with MusicMaid: Undo / History)\n\n")
            self._files[key] = base
        return self._files[key]

    def _save_art(self, root: str, b64: str | None) -> str | None:
        if not b64:
            return None
        data = base64.b64decode(b64)
        name = hashlib.sha1(data).hexdigest()[:20] + _image_ext(data)
        folder = Path(root) / FOLDER / SUB / "artwork"
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / name
        if not p.exists():
            p.write_bytes(data)
        return f"artwork/{name}"

    def record(self, batch: str, label: str, ts: float, op: str, track_id, src, dst, data) -> None:
        if not self.enabled_fn():
            return
        try:
            with self._lock:
                roots = {r for r in (self.root_of(src), self.root_of(dst)) if r}
                for root in roots:
                    self._write(root, batch, label, ts, op, src, dst, data)
        except OSError as e:
            msg = f"Couldn't save the change log in the library folder: {e}"
            if msg not in self.errors:
                self.errors.append(msg)

    def _write(self, root, batch, label, ts, op, src, dst, data) -> None:
        base = self._snapshot_base(root, batch, label, ts)
        entry = {"type": "change", "op": op, "time": ts,
                 "file": self.rel(src, root), "file_abs": src, "to": self.rel(dst, root), "to_abs": dst}
        words = ""
        shown_src = entry["file"] or src or ""
        shown_dst = entry["to"] or dst or ""
        if op == "tags":
            data = data or {}
            entry["old"] = data.get("tags", {})
            entry["new"] = data.get("new", {})
            art = data.get("art", "__keep__")
            entry["art_before"] = "keep" if art == "__keep__" else self._save_art(root, art)
            if art != "__keep__":
                entry["art_changed"] = True
            lines = []
            labels = _labels()
            for k, old in entry["old"].items():
                new = entry["new"].get(k, "")
                lines.append(f"    {labels.get(k, k)}: {old or '(empty)'!s} -> {new or '(removed)'!s}")
            if art != "__keep__":
                lines.append("    Cover art: " + ("replaced (old cover saved in " + entry["art_before"] + ")"
                                                  if entry["art_before"] else "added"))
            words = f"Changed tags: {shown_src}\n" + "\n".join(lines)
        elif op == "move":
            words = f"Moved/renamed: {shown_src}\n            -> {shown_dst}"
        elif op == "copy":
            words = f"Copied: {shown_src}\n     -> {shown_dst}"
        elif op == "create":
            words = f"Created: {shown_dst}"
        elif op == "quarantine":
            words = f"Moved to quarantine: {shown_src}\n    (kept in {dst})"
        elif op == "trash":
            words = f"Sent to the recycle bin: {shown_src}"
        else:
            words = f"{op}: {shown_src} {shown_dst}".strip()
        with open(base.with_suffix(".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        with open(base.with_suffix(".txt"), "a", encoding="utf-8") as f:
            f.write(words + "\n\n")


# ---------------------------------------------------------------- reading
@dataclass
class Snapshot:
    path: Path              # the .jsonl file
    root: str               # the library folder it belongs to (where it was found)
    batch: str
    label: str
    created: float
    changes: int
    reverted: bool

    @property
    def text_path(self) -> Path:
        return self.path.with_suffix(".txt")

    @property
    def marker(self) -> Path:
        return self.path.with_suffix(".reverted")


def _read(path: Path) -> tuple[dict, list[dict]]:
    header, changes = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue                     # a half-written last line after a crash
            if obj.get("type") == "snapshot" and not header:
                header = obj
            elif obj.get("type") == "change":
                changes.append(obj)
    return header, changes


def list_snapshots(roots: list[str]) -> list[Snapshot]:
    out = []
    for root in roots:
        folder = Path(root) / FOLDER / SUB
        if not folder.is_dir():
            continue
        for p in folder.glob("*.jsonl"):
            try:
                header, changes = _read(p)
            except OSError:
                continue
            if not header:
                continue
            out.append(Snapshot(p, root, header.get("batch", ""), header.get("label", ""),
                                float(header.get("created", p.stat().st_mtime)), len(changes),
                                p.with_suffix(".reverted").exists()))
    out.sort(key=lambda s: s.created, reverse=True)
    return out


def mark_reverted(roots: list[str], batch: str) -> None:
    for root in roots:
        for p in (Path(root) / FOLDER / SUB).glob(f"*_{batch}.jsonl"):
            try:
                p.with_suffix(".reverted").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n", encoding="utf-8")
            except OSError:
                pass


# ---------------------------------------------------------------- reverting
def _resolve(root: str, rel: str | None, absolute: str | None) -> str | None:
    if rel:
        return str(Path(root) / Path(rel))
    return absolute


def revert(snap: Snapshot, lib, task=None) -> tuple[int, list[str]]:
    """Undo one snapshot, newest change first. Returns (changes reverted, problems)."""
    from . import organizer, scanner
    from . import tags as tagio
    header, changes = _read(snap.path)
    done, problems = 0, []
    folder = snap.path.parent
    for i, c in enumerate(reversed(changes)):
        if task is not None:
            task.progress(i, len(changes), f"Reverting {snap.label}")
        op = c.get("op")
        src = _resolve(snap.root, c.get("file"), c.get("file_abs"))
        dst = _resolve(snap.root, c.get("to"), c.get("to_abs"))
        try:
            if op == "tags":
                if not src or not os.path.exists(src):
                    problems.append(f"Not found (moved or deleted since?): {c.get('file') or src}")
                    continue
                art = tagio._KEEP
                if c.get("art_changed"):
                    before = c.get("art_before")
                    art = (folder / before).read_bytes() if before else None
                tagio.write(src, c.get("old", {}), art)
                scanner.refresh_track(lib.db, src)
            elif op in ("move", "quarantine"):
                if dst and os.path.exists(dst) and src and not os.path.exists(src):
                    Path(src).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(dst, src)
                    t = lib.db.track_by_path(dst)
                    if t:
                        lib.db.update_path(t.id, src)
                    else:
                        scanner.refresh_track(lib.db, src)
                    organizer.remove_empty_dirs(str(Path(dst).parent),
                                                lib.folders + [str(lib.settings.quarantine_path)])
                elif src and os.path.exists(src):
                    pass                                  # already back where it was
                else:
                    problems.append(f"Can't put back {c.get('file') or src}: {dst} is gone")
                    continue
            elif op in ("create", "copy"):
                if dst and os.path.exists(dst):
                    os.remove(dst)
                    gone = lib.db.track_by_path(dst)
                    if gone:
                        lib.db.remove_tracks([gone.id])
            elif op == "trash":
                problems.append(f"{c.get('file') or src} is in the recycle bin - restore it from there")
                continue
            done += 1
        except Exception as e:  # keep going; report what couldn't be done
            problems.append(f"{c.get('file') or src}: {e}")
    try:
        snap.marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n", encoding="utf-8")
    except OSError:
        pass
    # the app's own undo journal shouldn't undo the same change twice
    lib.db.mark_undone([eid for eid, *_ in lib.db.batch_entries(snap.batch)])
    return done, problems
