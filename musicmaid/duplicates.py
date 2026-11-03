"""Duplicate detection: identical files, identical audio (fingerprints) and matching tags."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from . import fingerprint as fpmod
from .db import Database, Track
from .progress import NULL_TASK, Task
from .textutil import is_generic_title, norm


@dataclass
class DupeGroup:
    tracks: list[Track]  # best copy first
    reasons: set[str] = field(default_factory=set)
    similarity: float = 1.0

    @property
    def keep(self) -> Track:
        return self.tracks[0]

    @property
    def extras(self) -> list[Track]:
        return self.tracks[1:]

    @property
    def title(self) -> str:
        best = max(self.tracks, key=lambda t: len(t.tags))  # best-tagged copy names the group
        if best.get("artist") and best.get("title"):
            return f"{best.get('artist')} – {best.get('title')}"
        return best.get("title") or best.filename


class _UnionFind:
    def __init__(self):
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _file_hash(path: str) -> str | None:
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(
    db: Database,
    tracks: list[Track],
    *,
    use_fingerprints: bool = True,
    use_tags: bool = True,
    same_album_only: bool = False,
    threshold: float = 0.80,
    task: Task = NULL_TASK,
) -> list[DupeGroup]:
    tracks = [t for t in tracks if not t.error]
    by_id = {t.id: t for t in tracks}
    uf = _UnionFind()
    reasons: dict[tuple[int, int], str] = {}
    sims: dict[tuple[int, int], float] = {}

    def link(a: int, b: int, why: str, sim: float = 1.0) -> None:
        if same_album_only and norm(by_id[a].get("album")) != norm(by_id[b].get("album")):
            return
        uf.union(a, b)
        key = (min(a, b), max(a, b))
        reasons[key] = why
        sims[key] = min(sims.get(key, 1.0), sim)

    # 1) byte-identical files (cheap: only hash files of equal size)
    by_size: dict[int, list[Track]] = defaultdict(list)
    for t in tracks:
        by_size[t.size].append(t)
    same_size = [g for g in by_size.values() if len(g) > 1]
    for i, g in enumerate(same_size):
        task.progress(i, len(same_size), "Comparing identical file sizes")
        hashes: dict[str, int] = {}
        for t in g:
            h = _file_hash(t.path)
            if h is None:
                continue
            if h in hashes:
                link(hashes[h], t.id, "identical file")
            else:
                hashes[h] = t.id

    # 2) matching artist + title + similar duration
    if use_tags:
        by_key: dict[tuple[str, str], list[Track]] = defaultdict(list)
        for t in tracks:
            title, artist = t.get("title"), t.get("artist")
            if title and artist and not is_generic_title(title):
                by_key[(norm(artist), norm(title, drop_junk=False))].append(t)
        for group in by_key.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda t: t.duration)
            for a_i, a in enumerate(group):
                for b in group[a_i + 1:]:
                    if b.duration - a.duration > 4:
                        break
                    link(a.id, b.id, "same artist/title/length", 0.95)

    # 3) acoustic fingerprints
    if use_fingerprints:
        if fpmod.find_fpcalc():
            fpmod.ensure_raw(db, tracks, task)
        fps: dict[int, tuple] = {}
        for tid, blob, dur in db.raw_fingerprints():
            if tid in by_id:
                arr = fpmod.decode_raw(blob)
                if arr.size >= 40:
                    fps[tid] = (arr, dur or by_id[tid].duration)
        # inverted index on fingerprint words to avoid an O(n^2) comparison
        index: dict[int, list[int]] = defaultdict(list)
        for tid, (arr, _) in fps.items():
            for w in set(arr[:240].tolist()):
                index[w].append(tid)
        pair_counts: dict[tuple[int, int], int] = defaultdict(int)
        for w, ids in index.items():
            if len(ids) < 2 or len(ids) > 50:  # very common words = silence/noise
                continue
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    pair_counts[(min(a, b), max(a, b))] += 1
        pairs = [p for p, c in pair_counts.items() if c >= 3]
        for i, (a, b) in enumerate(pairs):
            if i % 20 == 0:
                task.progress(i, len(pairs), "Comparing fingerprints")
            if uf.find(a) == uf.find(b) and (a, b) in reasons:
                continue
            (fa, da), (fb, db_) = fps[a], fps[b]
            if da and db_ and abs(da - db_) > max(10.0, 0.1 * max(da, db_)):
                continue  # different edits (radio edit vs extended) are not dupes
            sim = fpmod.similarity(fa, fb)
            if sim >= threshold:
                link(a, b, "same audio (fingerprint)", sim)

    groups: dict[int, list[int]] = defaultdict(list)
    for tid in list(uf.parent):
        groups[uf.find(tid)].append(tid)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ts = sorted((by_id[m] for m in members), key=lambda t: -t.quality_score)
        why = {r for (a, b), r in reasons.items() if a in members}
        sim = min((s for (a, b), s in sims.items() if a in members), default=1.0)
        out.append(DupeGroup(tracks=ts, reasons=why, similarity=sim))
    out.sort(key=lambda g: (g.keep.get("artist").lower(), g.keep.get("title").lower()))
    return out
