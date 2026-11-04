"""Identify tracks against MusicBrainz using AcoustID fingerprints and metadata search.

The algorithm, per folder ("album cluster"):

1. Gather candidate recordings for every track:
   * AcoustID fingerprint lookup (works even when tags are wrong or missing), then
   * album-level search when the folder has usable album/artist tags, then
   * per-track recording search from existing tags or tags parsed from the filename.
2. Vote on release groups across the folder so all tracks of an album end up on
   the *same* release instead of random compilations.
3. Pull the full release from MusicBrainz and turn it into a tag proposal,
   scored 0..1 so confident matches can be applied automatically.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import fingerprint as fpmod
from .config import Settings, load_settings
from .db import Database, Proposal, Track
from .net import NetError
from .progress import NULL_TASK, Task
from .providers import acoustid
from .providers import musicbrainz as mb
from .textutil import first_int, is_generic_title, norm, parse_filename, similarity  # noqa: F401


@dataclass
class RelInfo:
    release_id: str
    recording_id: str = ""
    release_group_id: str = ""
    title: str = ""
    primary_type: str = ""
    secondary_types: tuple[str, ...] = ()
    status: str = ""
    country: str = ""
    date: str = ""
    track_count: int = 0
    disc: int = 0
    track_pos: int = 0
    artist: str = ""          # the release's own artist credit ("Various Artists" for compilations)


@dataclass
class Candidate:
    recording_id: str
    title: str
    artist: str
    length: float = 0.0
    releases: list[RelInfo] = field(default_factory=list)
    fp_score: float | None = None
    search_score: float | None = None
    acoustid_id: str = ""


@dataclass
class Match:
    track: Track
    candidate: Candidate
    release: RelInfo | None
    confidence: float
    tags: dict[str, str] = field(default_factory=dict)
    note: str = ""

    @property
    def summary(self) -> str:
        rel = self.release.title if self.release else "?"
        return f"{self.candidate.artist} – {self.candidate.title}  [{rel}]"


# ---------------------------------------------------------------- candidate gathering
def _rel_from_acoustid(rg: dict, rel: dict, recording_id: str = "") -> list[RelInfo]:
    out = []
    d = rel.get("date") or {}
    date = "-".join(f"{d[k]:02d}" if k != "year" else str(d[k]) for k in ("year", "month", "day") if k in d)
    for medium in rel.get("mediums", []) or [{}]:
        pos = 0
        for t in medium.get("tracks", []) or []:
            pos = t.get("position", 0)
        out.append(RelInfo(
            release_id=rel.get("id", ""), recording_id=recording_id, release_group_id=rg.get("id", ""),
            title=rel.get("title") or rg.get("title", ""),
            primary_type=(rg.get("type") or "").lower(), secondary_types=tuple(s.lower() for s in rg.get("secondarytypes", [])),
            status="official", country=rel.get("country", ""), date=date,
            track_count=medium.get("track_count") or rel.get("track_count", 0), disc=medium.get("position", 1), track_pos=pos,
            artist="".join(a.get("name", "") + a.get("joinphrase", "") for a in (rel.get("artists") or rg.get("artists") or [])),
        ))
    return out


def candidates_from_acoustid(results: list[dict]) -> list[Candidate]:
    cands: dict[str, Candidate] = {}
    for res in results:
        score = float(res.get("score", 0))
        for rec in res.get("recordings", []) or []:
            if "id" not in rec:
                continue
            c = cands.get(rec["id"])
            if c is None:
                artists = rec.get("artists") or []
                artist = "".join(a.get("name", "") + a.get("joinphrase", "") for a in artists)
                c = Candidate(recording_id=rec["id"], title=rec.get("title", ""), artist=artist,
                              length=float(rec.get("duration") or 0), fp_score=score, acoustid_id=res.get("id", ""))
                cands[rec["id"]] = c
            for rg in rec.get("releasegroups", []) or []:
                for rel in rg.get("releases", []) or []:
                    c.releases += _rel_from_acoustid(rg, rel, rec["id"])
    # recordings without title/releases are orphans in AcoustID - drop them
    return [c for c in cands.values() if c.title]


def _rel_from_search(rel: dict, recording_id: str = "") -> list[RelInfo]:
    rg = rel.get("release-group", {}) or {}
    out = []
    for medium in rel.get("media", []) or []:
        tracks = medium.get("track") or medium.get("tracks") or []
        pos = first_int(str(tracks[0].get("number"))) if tracks else 0
        if tracks and not pos:
            pos = (medium.get("track-offset") or 0) + 1
        out.append(RelInfo(
            release_id=rel.get("id", ""), recording_id=recording_id, release_group_id=rg.get("id", ""),
            title=rel.get("title", ""), primary_type=(rg.get("primary-type") or "").lower(),
            secondary_types=tuple(s.lower() for s in rg.get("secondary-types", []) or []),
            status=(rel.get("status") or "").lower(), country=rel.get("country", "") or "", date=rel.get("date", "") or "",
            track_count=medium.get("track-count", 0), disc=medium.get("position", 1), track_pos=pos or 0,
            artist=mb.artist_credit_phrase(rel.get("artist-credit") or rg.get("artist-credit")),
        ))
    return out


def candidates_from_search(recordings: list[dict]) -> list[Candidate]:
    out = []
    for rec in recordings:
        if rec.get("video"):  # music videos are separate recordings in MusicBrainz
            continue
        c = Candidate(
            recording_id=rec["id"], title=rec.get("title", ""), artist=mb.artist_credit_phrase(rec.get("artist-credit")),
            length=(rec.get("length") or 0) / 1000.0, search_score=(rec.get("score", 0) or 0) / 100.0,
        )
        for rel in rec.get("releases", []) or []:
            c.releases += _rel_from_search(rel, rec["id"])
        out.append(c)
    return out


def candidates_from_release(release: dict) -> list[tuple[Candidate, dict]]:
    """Every track of a full release as (candidate, track-json)."""
    out = []
    rg = release.get("release-group", {}) or {}
    for medium in release.get("media", []):
        for t in medium.get("tracks", []) or []:
            rec = t.get("recording", {})
            rel = RelInfo(
                release_id=release["id"], recording_id=rec.get("id", ""), release_group_id=rg.get("id", ""),
                title=release.get("title", ""),
                primary_type=(rg.get("primary-type") or "").lower(),
                secondary_types=tuple(s.lower() for s in rg.get("secondary-types", []) or []),
                status=(release.get("status") or "").lower(), country=release.get("country", "") or "",
                date=release.get("date", "") or "", track_count=medium.get("track-count", 0),
                disc=medium.get("position", 1), track_pos=t.get("position", 0),
                artist=mb.artist_credit_phrase(release.get("artist-credit")),
            )
            c = Candidate(recording_id=rec.get("id", ""), title=t.get("title") or rec.get("title", ""),
                          artist=mb.artist_credit_phrase(t.get("artist-credit") or rec.get("artist-credit")),
                          length=(t.get("length") or rec.get("length") or 0) / 1000.0, releases=[rel])
            out.append((c, t))
    return out


# ---------------------------------------------------------------- scoring
def query_tags(track: Track, roots: list[str] | None = None) -> tuple[dict[str, str], bool]:
    """Tags to search with; falls back to filename parsing. Returns (tags, from_filename)."""
    t = track.tags
    if t.get("title") and not is_generic_title(t.get("title")) and t.get("artist"):
        return dict(t), False
    from .cleanup import library_root
    parsed = parse_filename(track.path, library_root(track.path, roots or load_settings().library_folders))
    merged = dict(parsed)
    for k, v in t.items():
        if v and not (k == "title" and is_generic_title(v)):
            merged[k] = v
    return merged, True


def duration_score(a: float, b: float) -> float:
    if not a or not b:
        return 0.5
    d = abs(a - b)
    if d <= 2:
        return 1.0
    if d >= 20:
        return 0.0
    return 1.0 - (d - 2) / 18.0


def metadata_similarity(q: dict[str, str], cand: Candidate, duration: float) -> float | None:
    title, artist = q.get("title", ""), q.get("artist", "")
    if not title or is_generic_title(title):
        return None
    ts = similarity(title, cand.title)
    if artist:
        a = similarity(artist, cand.artist)
        return 0.5 * ts + 0.3 * a + 0.2 * duration_score(duration, cand.length)
    # title alone is ambiguous (many songs share a title) - keep it well below auto-apply
    return min(0.6, 0.45 * ts + 0.15 * duration_score(duration, cand.length))


def confidence(track: Track, cand: Candidate, q: dict[str, str], from_filename: bool) -> tuple[float, str]:
    meta = metadata_similarity(q, cand, track.duration)
    dur = duration_score(track.duration, cand.length)
    if cand.fp_score is not None:
        fp = cand.fp_score
        if meta is None:
            conf = fp * (0.88 + 0.08 * dur)
            note = "fingerprint match (file had no usable tags)"
        else:
            conf = fp * (0.84 + 0.16 * meta)
            note = "fingerprint match" + ("; existing tags differ a lot - were they wrong?" if meta < 0.5 else "")
        return min(conf, 1.0), note
    if meta is None:
        return 0.0, "no usable tags to search with"
    conf = meta * 0.97
    if from_filename:
        conf = min(conf, 0.85)
        note = "matched from file name"
    else:
        note = "matched from existing tags"
    return conf, note


def release_preference(rel: RelInfo, q: dict[str, str], settings: Settings, votes: float, folder_size: int,
                       earliest_year: int = 0) -> float:
    s = 0.0
    if settings.prefer_album_releases:
        s += {"album": 0.3, "ep": 0.15, "single": 0.1}.get(rel.primary_type, 0.0)
    if "compilation" in rel.secondary_types:
        s -= 0.25
    if set(rel.secondary_types) & {"dj-mix", "mixtape/street", "remix"}:
        s -= 0.25
    # another artist's release (a DJ mix, a tribute, a "chip mix" …) is rarely the one people mean
    wanted = q.get("albumartist") or q.get("artist") or ""
    various = ("various artists", "various", "va")
    if rel.artist and wanted and rel.artist.lower() not in various and wanted.lower() not in various:
        if similarity(wanted, rel.artist) < 0.5 and norm(wanted) not in norm(rel.artist):
            s -= 0.35
    if "live" in rel.secondary_types and "live" not in (q.get("album", "") + q.get("title", "")).lower():
        s -= 0.3
    if rel.status == "official":
        s += 0.2
    elif rel.status in ("bootleg", "promotion"):
        s -= 0.4
    if settings.prefer_country:
        if rel.country == settings.prefer_country:
            s += 0.1
    elif rel.country in ("XW", "US", "GB", "XE"):
        s += 0.05
    if q.get("album"):
        s += 0.7 * similarity(q["album"], rel.title)
    if folder_size > 1 and rel.track_count == folder_size:
        s += 0.15
    tn = first_int(q.get("tracknumber"))
    if tn and rel.track_pos == tn:
        s += 0.15
    s += 1.2 * votes
    year = first_int(rel.date[:4]) if rel.date else None
    if year and earliest_year:
        # prefer the original edition over later reissues / deluxe editions
        s -= min(0.2, (year - earliest_year) * 0.02)
    elif not year:
        s -= 0.05
    return s


# ---------------------------------------------------------------- engine
class Identifier:
    def __init__(self, db: Database, settings: Settings | None = None, task: Task = NULL_TASK):
        self.db = db
        self.settings = settings or load_settings()
        self.task = task
        self.use_acoustid = bool(self.settings.acoustid_key) and fpmod.find_fpcalc() is not None

    # -- per-track candidates
    def _acoustid_candidates(self, track: Track) -> list[Candidate]:
        try:
            duration, fp = fpmod.ensure_compressed(self.db, track)
            if not fp:
                return []
            return candidates_from_acoustid(acoustid.lookup(self.settings.acoustid_key, fp, duration))
        except acoustid.AcoustIDError as e:
            self.task.log(str(e))
            if "api key" in str(e).lower():
                self.task.log("Disabling AcoustID for this run - check the API key in Settings.")
                self.use_acoustid = False
            return []
        except (fpmod.FingerprintError, NetError) as e:
            self.task.log(f"{track.filename}: {e}")
            return []

    def _search_candidates(self, track: Track) -> list[Candidate]:
        q, _ = query_tags(track)
        if not q.get("title") or is_generic_title(q["title"]):
            return []
        dur = track.duration or None
        try:
            recs = []
            if q.get("artist"):
                # studio-album recordings first: popular songs have dozens of live/compilation versions
                recs = mb.search_recordings(q["title"], q["artist"], q.get("album", ""), dur, limit=25, studio_only=True)
            recs += mb.search_recordings(q["title"], q.get("artist", ""), q.get("album", ""), dur)
            if not recs and q.get("artist"):
                # artist might be wrong/misspelled - retry with title + duration only
                recs = mb.search_recordings(q["title"], "", q.get("album", ""), dur)
        except NetError as e:
            self.task.log(f"{track.filename}: {e}")
            return []
        seen: set[str] = set()
        recs = [r for r in recs if not (r["id"] in seen or seen.add(r["id"]))]
        cands = candidates_from_search(recs)
        return [c for c in cands if (c.search_score or 0) >= 0.5]

    def _album_candidates(self, tracks: list[Track]) -> dict[int, list[Candidate]]:
        """Look up a whole folder as one album when album/artist tags are present."""
        albums = Counter(t.get("album") for t in tracks if t.get("album"))
        if not albums:
            return {}
        album, n = albums.most_common(1)[0]
        if n < max(2, len(tracks) // 2):
            return {}
        artists = Counter(t.get("albumartist") or t.get("artist") for t in tracks if t.get("artist"))
        artist = artists.most_common(1)[0][0] if artists else ""
        try:
            releases = mb.search_releases(album, artist, limit=5)
        except NetError as e:
            self.task.log(str(e))
            return {}
        out: dict[int, list[Candidate]] = defaultdict(list)
        good = self._pick_releases(releases, len(tracks))
        for rel in good:
            try:
                full = mb.get_release(rel["id"])
            except NetError:
                continue
            if not full:
                continue
            rel_tracks = candidates_from_release(full)
            for t in tracks:
                q, _ = query_tags(t)
                best, best_s = None, 0.0
                for cand, _tj in rel_tracks:
                    s = metadata_similarity(q, cand, t.duration) or 0.0
                    if first_int(q.get("tracknumber")) == cand.releases[0].track_pos and \
                            (first_int(q.get("discnumber")) or 1) == cand.releases[0].disc:
                        s = max(s, 0.5 * duration_score(t.duration, cand.length) + 0.3) + 0.1
                    if s > best_s:
                        best, best_s = cand, s
                if best and best_s >= 0.6:
                    best.search_score = min(1.0, best_s)
                    out[t.id].append(best)
        return out

    def _pick_releases(self, releases: list[dict], n_tracks: int) -> list[dict]:
        """Best release of the top 2 release groups from a release search."""
        groups: dict[str, list[dict]] = {}
        for r in releases:
            if r.get("score", 0) < 80:
                continue
            groups.setdefault((r.get("release-group") or {}).get("id", r["id"]), []).append(r)
        pref = self.settings.prefer_country

        def rank(r: dict):
            country = r.get("country", "")
            c = 2 if pref and country == pref else 1 if country in ("XW", "US", "GB", "XE") else 0
            status = 1 if (r.get("status") or "").lower() == "official" else 0
            fits = 1 if r.get("track-count") and r["track-count"] >= n_tracks else 0
            return (status, fits, c, -int((r.get("date") or "9999")[:4] or 9999))

        return [max(g, key=rank) for g in list(groups.values())[:2]]

    # -- main entry
    def identify(self, tracks: list[Track]) -> list[Match]:
        by_folder: dict[str, list[Track]] = defaultdict(list)
        for t in tracks:
            if not t.error:
                by_folder[t.folder].append(t)
        matches: list[Match] = []
        done = 0
        total = len(tracks)
        for folder, ftracks in by_folder.items():
            cands: dict[int, list[Candidate]] = {}
            for t in ftracks:
                self.task.progress(done, total, f"Identifying {t.filename}")
                done += 1
                c = self._acoustid_candidates(t) if self.use_acoustid else []
                cands[t.id] = c
            missing = [t for t in ftracks if not cands[t.id]]
            if missing:
                self.task.progress(done, total, f"Looking up album in {folder}")
                for tid, cs in self._album_candidates(missing).items():
                    cands[tid] = cs
            for t in ftracks:
                if not cands[t.id]:
                    self.task.progress(done, total, f"Searching {t.filename}")
                    cands[t.id] = self._search_candidates(t)
            matches += self._resolve_folder(ftracks, cands)
        self.task.progress(total, total, "Fetching release details")
        self._fill_tags(matches)
        return matches

    def _resolve_folder(self, tracks: list[Track], cands: dict[int, list[Candidate]]) -> list[Match]:
        # best candidate per track (by confidence)
        best_per_track: dict[int, tuple[Candidate, float, str]] = {}
        for t in tracks:
            q, from_fn = query_tags(t)
            scored = []
            for c in cands.get(t.id, []):
                conf, note = confidence(t, c, q, from_fn)
                scored.append((conf, c, note))
            if not scored:
                continue
            # among equally good matches prefer recordings that appear on a studio album
            def canonical(c: Candidate) -> float:
                return 1.0 if any(r.status == "official" and r.primary_type == "album" and not r.secondary_types
                                  for r in c.releases) else 0.0
            scored.sort(key=lambda x: -(x[0] + 0.03 * canonical(x[1])))
            conf, c, note = scored[0]
            # Pool releases of equivalent recordings (same song, other MB recording ids,
            # e.g. remasters) so the release choice can see the original album.
            pooled = list(c.releases)
            for conf2, c2, _ in scored[1:]:
                if conf2 < conf - 0.1 or c2 is c:
                    continue
                if norm(c2.title, drop_junk=False) != norm(c.title, drop_junk=False) \
                        or similarity(c2.artist, c.artist) < 0.9:
                    continue
                if not (c.length and c2.length) or abs(c.length - c2.length) > 6:
                    continue
                pooled += c2.releases
            c.releases = pooled
            best_per_track[t.id] = (c, conf, note)

        # release-group votes across the folder
        votes: Counter = Counter()
        for c, conf, _ in best_per_track.values():
            for rg in {r.release_group_id for r in c.releases if r.release_group_id}:
                votes[rg] += conf
        n = max(1, len(tracks))
        out = []
        for t in tracks:
            if t.id not in best_per_track:
                continue
            c, conf, note = best_per_track[t.id]
            q, _ = query_tags(t)
            rel = None
            if c.releases:
                years = [first_int(r.date[:4]) for r in c.releases if r.date]
                earliest = min((y for y in years if y), default=0)
                rel = max(c.releases, key=lambda r: release_preference(
                    r, q, self.settings, votes.get(r.release_group_id, 0) / n, len(tracks), earliest))
                share = votes.get(rel.release_group_id, 0) / n
                if len(tracks) >= 3 and share >= 0.5:
                    conf = min(1.0, conf + 0.04)
                album_ok = bool(q.get("album")) and similarity(q["album"], rel.title) >= 0.8
                studio = rel.status == "official" and rel.primary_type in ("album", "ep", "single") \
                    and not rel.secondary_types
                if not album_ok and not studio:
                    # right song, but probably not the album the user has - let them review it
                    conf -= 0.12
                    note += "; only found on a compilation/live release"
            out.append(Match(track=t, candidate=c, release=rel, confidence=round(conf, 3), note=note))
        return out

    def _fill_tags(self, matches: list[Match]) -> None:
        for i, m in enumerate(matches):
            self.task.progress(i, len(matches), f"Release details: {m.summary}")
            tags: dict[str, str] = {}
            if m.release:
                try:
                    release = mb.get_release(m.release.release_id)
                except NetError as e:
                    self.task.log(str(e))
                    release = None
                if release:
                    found = mb.find_track_in_release(release, m.release.recording_id or m.candidate.recording_id)
                    if found is None:
                        found = mb.find_track_in_release(release, m.candidate.recording_id)
                    if found is None and m.release.track_pos:
                        # recording id merged/changed - fall back to position
                        for med in release.get("media", []):
                            if med.get("position") == m.release.disc:
                                for tr in med.get("tracks", []) or []:
                                    if tr.get("position") == m.release.track_pos:
                                        found = (med, tr)
                    if found:
                        tags = mb.tags_from_release(release, *found, genre_fallback=self.settings.genre_from_musicbrainz)
            if not tags:
                tags = {"title": m.candidate.title, "artist": m.candidate.artist,
                        "musicbrainz_recordingid": m.candidate.recording_id}
            if m.candidate.acoustid_id:
                tags["acoustid_id"] = m.candidate.acoustid_id
            if not self.settings.genre_from_musicbrainz:
                tags.pop("genre", None)
            if not self.settings.write_musicbrainz_ids:
                tags = {k: v for k, v in tags.items() if not k.startswith(("musicbrainz_", "acoustid"))}
            m.tags = tags

    @staticmethod
    def diff(track: Track, tags: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in tags.items() if (track.tags.get(k) or "") != v}


def identify_and_propose(db: Database, tracks: list[Track], task: Task = NULL_TASK,
                         settings: Settings | None = None) -> tuple[list[Match], list[Track]]:
    """Run identification and store results as proposals. Returns (matches, unmatched)."""
    ident = Identifier(db, settings, task)
    matches = ident.identify(tracks)
    matched_ids = set()
    for m in matches:
        changes = Identifier.diff(m.track, m.tags)
        matched_ids.add(m.track.id)
        if changes:
            db.set_proposal(Proposal(track_id=m.track.id, tags=changes, source="MusicBrainz",
                                     score=m.confidence, note=f"{m.summary} — {m.note}"))
    unmatched = [t for t in tracks if t.id not in matched_ids]
    return matches, unmatched
