"""Offline tag clean-up rules and problem detection."""
from __future__ import annotations

import re
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass

from .db import Database, Proposal, Track
from .progress import NULL_TASK, Task
from .textutil import (
    clean_whitespace, first_int, is_generic_title, norm, parse_filename, remove_urls, smart_title_case,
)

TEXT_FIELDS = ("title", "artist", "album", "albumartist", "genre", "composer", "comment", "label")
CASE_FIELDS = ("title", "artist", "album", "albumartist", "genre")


@dataclass
class CleanupOptions:
    fix_whitespace: bool = True
    remove_urls: bool = True
    fix_case: bool = True
    fill_from_filename: bool = True
    split_artist_title: bool = True
    normalize_numbers: bool = True
    album_consistency: bool = True
    fill_albumartist: bool = True
    fill_totals: bool = False  # risky for incomplete albums


def _track_rules(t: Track, o: CleanupOptions, root: str | None = None) -> dict[str, str]:
    cur = dict(t.tags)
    new = dict(cur)
    for f in TEXT_FIELDS:
        v = new.get(f)
        if not v:
            continue
        if o.fix_whitespace:
            v = clean_whitespace(v)
        if o.remove_urls and f != "comment":
            v = remove_urls(v) or v
        if o.fix_case and f in CASE_FIELDS and len(v) > 3:
            v = smart_title_case(v)
        new[f] = v
    if o.remove_urls and new.get("comment") and re.search(r"(https?://|www\.)", new["comment"], re.I):
        new["comment"] = ""  # comments containing URLs are almost always download-site spam

    # "Artist - Title" crammed into the title field
    if o.split_artist_title and new.get("title") and " - " in new["title"]:
        a, ttl = new["title"].split(" - ", 1)
        if not new.get("artist") or norm(new.get("artist")) == norm(a):
            new["artist"] = a.strip()
            new["title"] = ttl.strip()

    if o.fill_from_filename:
        parsed = parse_filename(t.path, root)
        if is_generic_title(new.get("title")) and parsed.get("title") and not is_generic_title(parsed["title"]):
            new["title"] = parsed["title"]
        for f in ("artist", "album", "tracknumber", "discnumber", "date"):
            if not new.get(f) and parsed.get(f):
                new[f] = parsed[f]
        if o.fix_case:
            for f in ("title", "artist", "album"):
                if new.get(f) and new.get(f) != cur.get(f):
                    new[f] = smart_title_case(new[f])

    if o.normalize_numbers:
        for f in ("tracknumber", "totaltracks", "discnumber", "totaldiscs"):
            n = first_int(new.get(f))
            if new.get(f) and n is not None and str(n) != new[f]:
                new[f] = str(n)
            if n == 0:
                new[f] = ""
        y = new.get("date", "")
        if y and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", y):
            m = re.search(r"(19|20)\d{2}", y)
            if m:
                new["date"] = m.group(0)
    return {k: v for k, v in new.items() if (cur.get(k) or "") != (v or "")}


def _album_rules(tracks: list[Track], pending: dict[int, dict[str, str]], o: CleanupOptions) -> None:
    """Make album-level fields consistent inside a folder."""
    if len(tracks) < 2:
        return

    def val(t: Track, f: str) -> str:
        return pending.get(t.id, {}).get(f, t.tags.get(f, ""))

    n = len(tracks)
    if o.album_consistency and n >= 3:
        for f in ("album", "albumartist", "date", "genre", "totaldiscs"):
            counts = Counter(val(t, f) for t in tracks if val(t, f))
            if not counts:
                continue
            top, c = counts.most_common(1)[0]
            if c >= max(2, -(-n * 3 // 5)) and c < n:
                # only fill blanks or fix near-identical spellings - never overwrite a clearly different value
                for t in tracks:
                    v = val(t, f)
                    if not v or (v != top and norm(v) == norm(top)):
                        pending.setdefault(t.id, {})[f] = top
    if o.fill_albumartist:
        albums = {norm(t.tags.get("album")) for t in tracks}
        if len(albums) == 1 and "" not in albums and any(not val(t, "albumartist") for t in tracks):
            artists = Counter(val(t, "artist") for t in tracks if val(t, "artist"))
            if artists:
                if len(artists) == 1:
                    aa = next(iter(artists))
                else:
                    top, c = artists.most_common(1)[0]
                    aa = top if c >= n * 0.75 else "Various Artists"
                for t in tracks:
                    if not val(t, "albumartist"):
                        pending.setdefault(t.id, {})["albumartist"] = aa
                        if aa == "Various Artists" and not val(t, "compilation"):
                            pending[t.id]["compilation"] = "1"
    if o.fill_totals:
        by_disc: dict[int, list[Track]] = defaultdict(list)
        for t in tracks:
            by_disc[first_int(val(t, "discnumber")) or 1].append(t)
        for disc_tracks in by_disc.values():
            nums = sorted(first_int(val(t, "tracknumber")) or 0 for t in disc_tracks)
            if nums and nums == list(range(1, len(nums) + 1)):
                for t in disc_tracks:
                    if not val(t, "totaltracks"):
                        pending.setdefault(t.id, {})["totaltracks"] = str(len(nums))


def library_root(path: str, roots: list[str]) -> str | None:
    """The (deepest) library folder that contains path."""
    best = None
    pp = Path(path)
    for r in roots:
        if Path(r) in pp.parents and (best is None or len(r) > len(best)):
            best = r
    return best


def propose_cleanup(db: Database, tracks: list[Track], options: CleanupOptions | None = None,
                    task: Task = NULL_TASK, roots: list[str] | None = None) -> int:
    o = options or CleanupOptions()
    pending: dict[int, dict[str, str]] = {}
    for i, t in enumerate(tracks):
        task.progress(i, len(tracks), f"Checking {t.filename}")
        ch = _track_rules(t, o, library_root(t.path, roots or []))
        if ch:
            pending[t.id] = ch
    by_folder: dict[str, list[Track]] = defaultdict(list)
    for t in tracks:
        by_folder[t.folder].append(t)
    for ftracks in by_folder.values():
        _album_rules(ftracks, pending, o)
    count = 0
    by_id = {t.id: t for t in tracks}
    for tid, ch in pending.items():
        ch = {k: v for k, v in ch.items() if (by_id[tid].tags.get(k) or "") != v}
        if ch:
            db.set_proposal(Proposal(track_id=tid, tags=ch, source="Cleanup", score=1.0, note="local clean-up rules"))
            count += 1
    return count


# ---------------------------------------------------------------- problem detection
def problems(t: Track, min_art: int = 500) -> list[str]:
    p = []
    if t.error:
        return ["unreadable file"]
    if not t.tags.get("title"):
        p.append("no title")
    elif is_generic_title(t.tags["title"]):
        p.append("generic title")
    if not t.tags.get("artist"):
        p.append("no artist")
    if not t.tags.get("album"):
        p.append("no album")
    if not t.tags.get("tracknumber"):
        p.append("no track #")
    if not t.has_art:
        p.append("no artwork")
    elif t.art_w and min(t.art_w, t.art_h) < min_art:
        p.append(f"small artwork ({t.art_w}px)")
    if not t.lossless and t.bitrate and t.bitrate < 128:
        p.append(f"low bitrate ({t.bitrate}k)")
    if any(re.search(r"(https?://|www\.)", t.tags.get(f, ""), re.I) for f in ("title", "artist", "album", "comment")):
        p.append("URL in tags")
    return p


def is_untagged(t: Track) -> bool:
    return not t.tags.get("artist") or not t.tags.get("title") or is_generic_title(t.tags.get("title"))
