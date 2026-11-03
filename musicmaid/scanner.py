"""Walk library folders and keep the database in sync with the files on disk."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import tags as tagio
from .db import Database
from .progress import NULL_TASK, Task


def find_audio_files(folder: str | Path) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.startswith("._") and tagio.is_audio_file(f):
                out.append(os.path.join(root, f))
    return out


def _read_one(path: str):
    try:
        st = os.stat(path)
    except OSError as e:
        return path, None, None, None, None, str(e)
    try:
        data = tagio.read(path)
        return path, st.st_size, st.st_mtime, data.info, data, None
    except Exception as e:  # corrupt or unsupported file
        return path, st.st_size, st.st_mtime, None, None, f"{type(e).__name__}: {e}"


def scan(db: Database, folders: list[str], task: Task = NULL_TASK, *, force: bool = False) -> dict[str, int]:
    """Add new/changed files, refresh modified ones and forget deleted ones."""
    stats = {"added": 0, "updated": 0, "removed": 0, "errors": 0, "unchanged": 0}
    task.progress(0, 0, "Listing files…")
    files: list[str] = []
    for folder in folders:
        files += find_audio_files(folder)
    known: dict[str, tuple[int, int, float]] = {}
    for folder in folders:
        known.update(db.known_files(str(Path(folder))))

    present = set(files)
    gone = [tid for path, (tid, _, _) in known.items() if path not in present and not os.path.exists(path)]
    if gone:
        db.remove_tracks(gone)
        stats["removed"] = len(gone)

    todo = []
    for path in files:
        k = known.get(path)
        if k and not force:
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_size == k[1] and abs(st.st_mtime - (k[2] or 0)) < 0.001:
                stats["unchanged"] += 1
                continue
        todo.append(path)

    total = len(todo)
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) * 2)) as pool:
        for n, (path, size, mtime, info, data, err) in enumerate(pool.map(_read_one, todo), 1):
            task.progress(n, total, f"Reading {Path(path).name}")
            if size is None:
                continue
            db.upsert_track(
                path, size=size, mtime=mtime, info=info, tags=data.tags if data else {},
                artwork=data.artwork if data else None, error=err,
            )
            if err:
                stats["errors"] += 1
                task.log(f"Could not read {path}: {err}")
            elif path in known:
                stats["updated"] += 1
            else:
                stats["added"] += 1
    return stats


def refresh_track(db: Database, path: str) -> int | None:
    path, size, mtime, info, data, err = _read_one(path)
    if size is None:
        return None
    return db.upsert_track(path, size=size, mtime=mtime, info=info, tags=data.tags if data else {},
                           artwork=data.artwork if data else None, error=err)
