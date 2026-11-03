"""SQLite-backed library cache, pending-change proposals and an undo journal."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    folder TEXT NOT NULL,
    size INTEGER, mtime REAL,
    codec TEXT, lossless INTEGER, duration REAL, bitrate INTEGER,
    sample_rate INTEGER, channels INTEGER, bits INTEGER,
    tags TEXT NOT NULL DEFAULT '{}',
    has_art INTEGER DEFAULT 0, art_w INTEGER DEFAULT 0, art_h INTEGER DEFAULT 0,
    fp_raw BLOB, fp TEXT, fp_duration REAL,
    error TEXT,
    scanned_at REAL
);
CREATE INDEX IF NOT EXISTS tracks_folder ON tracks(folder);
CREATE TABLE IF NOT EXISTS proposals (
    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    tags TEXT NOT NULL DEFAULT '{}',
    art BLOB, art_source TEXT,
    source TEXT, score REAL, note TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY,
    batch TEXT NOT NULL, label TEXT,
    ts REAL, op TEXT NOT NULL,
    track_id INTEGER, src TEXT, dst TEXT, data TEXT,
    undone INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS journal_batch ON journal(batch);
"""


@dataclass
class Track:
    id: int
    path: str
    folder: str
    size: int = 0
    mtime: float = 0.0
    codec: str = ""
    lossless: bool = False
    duration: float = 0.0
    bitrate: int = 0
    sample_rate: int = 0
    channels: int = 0
    bits: int = 0
    tags: dict[str, str] = field(default_factory=dict)
    has_art: bool = False
    art_w: int = 0
    art_h: int = 0
    fp: str | None = None
    fp_duration: float | None = None
    has_fp: bool = False
    error: str | None = None

    def get(self, key: str, default: str = "") -> str:
        return self.tags.get(key, default)

    @property
    def filename(self) -> str:
        return Path(self.path).name

    @property
    def quality_score(self) -> float:
        """Higher = better copy (used to choose which duplicate to keep)."""
        s = 0.0
        if self.lossless:
            s += 10000 + self.bits * 10 + self.sample_rate / 1000
        else:
            s += min(self.bitrate, 500) * 10
            if self.codec in ("opus", "aac", "vorbis"):
                s += self.bitrate * 3  # modern codecs are more efficient
        s += sum(1 for k in ("title", "artist", "album", "tracknumber", "date", "genre") if self.tags.get(k)) * 20
        if self.tags.get("musicbrainz_recordingid"):
            s += 100
        if self.has_art:
            s += 50
        return s


_COLS = "id, path, folder, size, mtime, codec, lossless, duration, bitrate, sample_rate, channels, bits, tags, has_art, art_w, art_h, fp, fp_duration, fp_raw IS NOT NULL, error"


def _row_to_track(r) -> Track:
    return Track(
        id=r[0], path=r[1], folder=r[2], size=r[3] or 0, mtime=r[4] or 0, codec=r[5] or "",
        lossless=bool(r[6]), duration=r[7] or 0.0, bitrate=r[8] or 0, sample_rate=r[9] or 0,
        channels=r[10] or 0, bits=r[11] or 0, tags=json.loads(r[12] or "{}"), has_art=bool(r[13]),
        art_w=r[14] or 0, art_h=r[15] or 0, fp=r[16], fp_duration=r[17], has_fp=bool(r[18]), error=r[19],
    )


@dataclass
class Proposal:
    track_id: int
    tags: dict[str, str]
    art: bytes | None = None
    art_source: str | None = None
    source: str = ""
    score: float = 0.0
    note: str = ""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or data_dir() / "library.db")
        self._local = threading.local()
        self._write_lock = threading.RLock()
        with self.conn() as c:
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    # ------------------------------------------------------------ tracks
    def upsert_track(self, path: str, *, size: int, mtime: float, info, tags: dict, artwork, error: str | None = None) -> int:
        p = Path(path)
        with self._write_lock, self.conn() as c:
            old = c.execute("SELECT id, size, mtime FROM tracks WHERE path=?", (path,)).fetchone()
            values = dict(
                path=path, folder=str(p.parent), size=size, mtime=mtime,
                codec=info.codec if info else None, lossless=int(bool(info and info.lossless)),
                duration=info.duration if info else None, bitrate=info.bitrate if info else None,
                sample_rate=info.sample_rate if info else None, channels=info.channels if info else None,
                bits=info.bits_per_sample if info else None, tags=json.dumps(tags, ensure_ascii=False),
                has_art=int(artwork is not None), art_w=artwork.width if artwork else 0,
                art_h=artwork.height if artwork else 0, error=error, scanned_at=time.time(),
            )
            if old:
                # audio content may have changed -> drop fingerprint if size changed
                sets = ", ".join(f"{k}=:{k}" for k in values)
                if old[1] != size:
                    sets += ", fp_raw=NULL, fp=NULL, fp_duration=NULL"
                c.execute(f"UPDATE tracks SET {sets} WHERE id=:id", {**values, "id": old[0]})
                return old[0]
            cols = ", ".join(values)
            ph = ", ".join(f":{k}" for k in values)
            return c.execute(f"INSERT INTO tracks ({cols}) VALUES ({ph})", values).lastrowid

    def known_files(self, under: str | None = None) -> dict[str, tuple[int, int, float]]:
        q = "SELECT path, id, size, mtime FROM tracks"
        args: tuple = ()
        if under:
            q += " WHERE path LIKE ?"
            args = (under.rstrip("/\\") + "%",)
        return {r[0]: (r[1], r[2], r[3]) for r in self.conn().execute(q, args)}

    def tracks(self, ids: Iterable[int] | None = None, where: str = "", args: tuple = ()) -> list[Track]:
        q = f"SELECT {_COLS} FROM tracks"
        if ids is not None:
            ids = list(ids)
            if not ids:
                return []
            out: list[Track] = []
            for i in range(0, len(ids), 900):
                chunk = ids[i:i + 900]
                out += [_row_to_track(r) for r in self.conn().execute(
                    f"{q} WHERE id IN ({','.join('?' * len(chunk))})", chunk)]
            order = {tid: n for n, tid in enumerate(ids)}
            out.sort(key=lambda t: order.get(t.id, 0))
            return out
        if where:
            q += " WHERE " + where
        q += " ORDER BY folder, path"
        return [_row_to_track(r) for r in self.conn().execute(q, args)]

    def track(self, track_id: int) -> Track | None:
        r = self.tracks([track_id])
        return r[0] if r else None

    def track_by_path(self, path: str) -> Track | None:
        r = self.conn().execute(f"SELECT {_COLS} FROM tracks WHERE path=?", (path,)).fetchone()
        return _row_to_track(r) if r else None

    def remove_tracks(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        with self._write_lock, self.conn() as c:
            c.executemany("DELETE FROM tracks WHERE id=?", [(i,) for i in ids])

    def update_path(self, track_id: int, new_path: str) -> None:
        with self._write_lock, self.conn() as c:
            c.execute("UPDATE tracks SET path=?, folder=? WHERE id=?", (new_path, str(Path(new_path).parent), track_id))

    def set_fingerprint(self, track_id: int, raw: bytes | None, fp: str | None, duration: float | None) -> None:
        with self._write_lock, self.conn() as c:
            if raw is not None:
                c.execute("UPDATE tracks SET fp_raw=?, fp_duration=? WHERE id=?", (raw, duration, track_id))
            if fp is not None:
                c.execute("UPDATE tracks SET fp=?, fp_duration=? WHERE id=?", (fp, duration, track_id))

    def raw_fingerprints(self) -> Iterator[tuple[int, bytes, float]]:
        yield from self.conn().execute("SELECT id, fp_raw, fp_duration FROM tracks WHERE fp_raw IS NOT NULL")

    def count(self) -> int:
        return self.conn().execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    # ------------------------------------------------------------ proposals
    def set_proposal(self, p: Proposal, *, merge: bool = True) -> None:
        with self._write_lock, self.conn() as c:
            if merge:
                old = self.proposal(p.track_id)
                if old:
                    p = Proposal(
                        track_id=p.track_id, tags={**old.tags, **p.tags},
                        art=p.art if p.art is not None else old.art,
                        art_source=p.art_source if p.art is not None else old.art_source,
                        source=", ".join(dict.fromkeys(filter(None, [*old.source.split(", "), p.source]))),
                        score=p.score if p.tags else old.score,
                        note=p.note or old.note,
                    )
            c.execute(
                "INSERT OR REPLACE INTO proposals (track_id, tags, art, art_source, source, score, note, created)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (p.track_id, json.dumps(p.tags, ensure_ascii=False), p.art, p.art_source, p.source, p.score, p.note, time.time()),
            )

    def proposal(self, track_id: int) -> Proposal | None:
        r = self.conn().execute(
            "SELECT track_id, tags, art, art_source, source, score, note FROM proposals WHERE track_id=?", (track_id,)
        ).fetchone()
        if not r:
            return None
        return Proposal(r[0], json.loads(r[1]), r[2], r[3], r[4] or "", r[5] or 0.0, r[6] or "")

    def proposal_ids(self) -> set[int]:
        return {r[0] for r in self.conn().execute("SELECT track_id FROM proposals")}

    def proposal_summary(self) -> dict[int, tuple[str, float, bool]]:
        return {r[0]: (r[1] or "", r[2] or 0.0, bool(r[3])) for r in
                self.conn().execute("SELECT track_id, source, score, art IS NOT NULL FROM proposals")}

    def delete_proposals(self, ids: Iterable[int]) -> None:
        with self._write_lock, self.conn() as c:
            c.executemany("DELETE FROM proposals WHERE track_id=?", [(i,) for i in ids])

    # ------------------------------------------------------------ journal (undo)
    def new_batch(self) -> str:
        return uuid.uuid4().hex[:12]

    def journal(self, batch: str, label: str, op: str, track_id: int | None, src: str | None, dst: str | None, data=None) -> None:
        with self._write_lock, self.conn() as c:
            c.execute(
                "INSERT INTO journal (batch, label, ts, op, track_id, src, dst, data) VALUES (?,?,?,?,?,?,?,?)",
                (batch, label, time.time(), op, track_id, src, dst, json.dumps(data, ensure_ascii=False) if data is not None else None),
            )

    def batches(self, limit: int = 30) -> list[tuple[str, str, float, int]]:
        return list(self.conn().execute(
            "SELECT batch, label, MIN(ts), COUNT(*) FROM journal WHERE undone=0 GROUP BY batch ORDER BY MIN(ts) DESC LIMIT ?",
            (limit,),
        ))

    def batch_entries(self, batch: str) -> list[tuple]:
        return list(self.conn().execute(
            "SELECT id, op, track_id, src, dst, data FROM journal WHERE batch=? AND undone=0 ORDER BY id DESC", (batch,)
        ))

    def mark_undone(self, entry_ids: Iterable[int]) -> None:
        with self._write_lock, self.conn() as c:
            c.executemany("UPDATE journal SET undone=1 WHERE id=?", [(i,) for i in entry_ids])
