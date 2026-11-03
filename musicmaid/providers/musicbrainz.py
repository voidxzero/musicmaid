"""MusicBrainz web service (https://musicbrainz.org/doc/MusicBrainz_API)."""
from __future__ import annotations

import re
import threading
from collections import OrderedDict

from .. import net

BASE = "https://musicbrainz.org/ws/2"
VARIOUS_ARTISTS_ID = "89ad4ac3-39f7-470e-963a-56509c546377"

_cache_lock = threading.Lock()
_release_cache: "OrderedDict[str, dict]" = OrderedDict()
_RG_CACHE: dict[str, dict] = {}


def _lucene_escape(s: str) -> str:
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", s)


def artist_credit_phrase(credit: list[dict] | None) -> str:
    if not credit:
        return ""
    return "".join(c.get("name", c.get("artist", {}).get("name", "")) + c.get("joinphrase", "") for c in credit).strip()


def first_artist_id(credit: list[dict] | None) -> str:
    if not credit:
        return ""
    return credit[0].get("artist", {}).get("id", "")


def search_recordings(title: str, artist: str = "", album: str = "", duration: float | None = None, limit: int = 50,
                      studio_only: bool = False) -> list[dict]:
    # "+" terms are required, the others only boost relevance. MusicBrainz has many
    # live/bootleg recordings of popular songs, so boost official album releases and
    # the file's real duration to get the canonical recording into the results.
    parts = [f'+recording:"{_lucene_escape(title)}"']
    if artist:
        parts.append(f'+artist:"{_lucene_escape(artist)}"')
    if album:
        parts.append(f'release:"{_lucene_escape(album)}"^2')
    if studio_only:
        parts.append("+status:official +primarytype:album -secondarytype:compilation -secondarytype:live")
    else:
        parts.append("status:official^3 primarytype:album^2")
    if duration:
        ms = int(duration * 1000)
        parts.append(f"dur:[{ms - 10000} TO {ms + 10000}]^2")
    q = " ".join(parts)
    data = net.get_json(f"{BASE}/recording", params={"query": q, "limit": limit, "fmt": "json"})
    return (data or {}).get("recordings", [])


def search_releases(album: str, artist: str = "", limit: int = 25) -> list[dict]:
    parts = [f'+release:"{_lucene_escape(album)}"']
    if artist:
        parts.append(f'+artist:"{_lucene_escape(artist)}"')
    parts.append("status:official^3 primarytype:album^2")
    data = net.get_json(f"{BASE}/release", params={"query": " ".join(parts), "limit": limit, "fmt": "json"})
    return (data or {}).get("releases", [])


def get_release(release_id: str) -> dict | None:
    with _cache_lock:
        if release_id in _release_cache:
            _release_cache.move_to_end(release_id)
            return _release_cache[release_id]
    data = net.get_json(
        f"{BASE}/release/{release_id}",
        params={"inc": "recordings+artist-credits+labels+release-groups+genres+isrcs+media", "fmt": "json"},
    )
    if data:
        with _cache_lock:
            _release_cache[release_id] = data
            while len(_release_cache) > 300:
                _release_cache.popitem(last=False)
    return data


def get_release_group_genres(rg_id: str) -> list[dict]:
    if rg_id not in _RG_CACHE:
        _RG_CACHE[rg_id] = net.get_json(f"{BASE}/release-group/{rg_id}", params={"inc": "genres", "fmt": "json"}) or {}
    return _RG_CACHE[rg_id].get("genres", [])


def find_track_in_release(release: dict, recording_id: str) -> tuple[dict, dict] | None:
    """Return (medium, track) for a recording within a full release."""
    for medium in release.get("media", []):
        for track in medium.get("tracks", []) or []:
            if track.get("recording", {}).get("id") == recording_id:
                return medium, track
    return None


def tags_from_release(release: dict, medium: dict, track: dict, *, genre_fallback: bool = True) -> dict[str, str]:
    rec = track.get("recording", {})
    rg = release.get("release-group", {})
    album_credit = release.get("artist-credit")
    track_credit = track.get("artist-credit") or rec.get("artist-credit")
    out = {
        "title": track.get("title") or rec.get("title", ""),
        "artist": artist_credit_phrase(track_credit),
        "album": release.get("title", ""),
        "albumartist": artist_credit_phrase(album_credit),
        "tracknumber": str(track.get("position") or track.get("number") or ""),
        "totaltracks": str(medium.get("track-count") or len(medium.get("tracks", []))),
        "discnumber": str(medium.get("position", 1)),
        "totaldiscs": str(len(release.get("media", [])) or 1),
        "date": release.get("date", "") or rg.get("first-release-date", ""),
        "originaldate": rg.get("first-release-date", ""),
        "releasecountry": release.get("country", "") or "",
        "releasetype": (rg.get("primary-type") or "").lower(),
        "musicbrainz_recordingid": rec.get("id", ""),
        "musicbrainz_releasetrackid": track.get("id", ""),
        "musicbrainz_albumid": release.get("id", ""),
        "musicbrainz_artistid": first_artist_id(track_credit),
        "musicbrainz_albumartistid": first_artist_id(album_credit),
        "musicbrainz_releasegroupid": rg.get("id", ""),
    }
    isrcs = rec.get("isrcs") or []
    if isrcs:
        out["isrc"] = isrcs[0]
    labels = release.get("label-info") or []
    if labels:
        li = labels[0]
        if li.get("label"):
            out["label"] = li["label"].get("name", "")
        if li.get("catalog-number"):
            out["catalognumber"] = li["catalog-number"]
    if first_artist_id(album_credit) == VARIOUS_ARTISTS_ID:
        out["compilation"] = "1"
    genres = sorted(release.get("genres") or [], key=lambda g: -g.get("count", 0))
    if not genres and genre_fallback and rg.get("id"):
        try:
            genres = sorted(get_release_group_genres(rg["id"]), key=lambda g: -g.get("count", 0))
        except net.NetError:
            genres = []
    if genres:
        out["genre"] = genres[0]["name"].title()
    if int(out["totaldiscs"] or 1) <= 1:
        out["totaldiscs"] = "1"
    return {k: v for k, v in out.items() if v}
