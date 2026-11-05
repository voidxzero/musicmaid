"""Cover art search: Cover Art Archive, iTunes/Apple Music and Deezer."""
from __future__ import annotations

from dataclasses import dataclass

from .. import net
from ..textutil import norm, similarity


@dataclass
class ArtCandidate:
    url: str
    thumb_url: str
    source: str
    title: str = ""
    artist: str = ""
    width: int = 0  # 0 = unknown
    height: int = 0
    score: float = 0.0

    @property
    def label(self) -> str:
        size = f"{self.width}×{self.height}" if self.width else "original size"
        what = " – ".join(x for x in (self.artist, self.title) if x)
        return f"{self.source}: {what} ({size})" if what else f"{self.source} ({size})"


def coverartarchive(release_id: str = "", release_group_id: str = "") -> list[ArtCandidate]:
    out: list[ArtCandidate] = []
    for kind, mbid in (("release", release_id), ("release-group", release_group_id)):
        if not mbid:
            continue
        data = net.get_json(f"https://coverartarchive.org/{kind}/{mbid}")
        if not data:
            continue
        for img in data.get("images", []):
            if not img.get("front"):
                continue
            th = img.get("thumbnails", {})
            url = th.get("1200") or img.get("image")
            out.append(ArtCandidate(
                url=url, thumb_url=th.get("250") or th.get("small") or url, source="Cover Art Archive",
                title="" if kind == "release" else "release group", width=1200 if th.get("1200") else 0, height=1200 if th.get("1200") else 0, score=1.0,
            ))
            if img.get("image") and th.get("1200"):
                out.append(ArtCandidate(url=img["image"], thumb_url=th.get("250") or url,
                                        source="Cover Art Archive", title="full size", score=0.99))
        if out:
            break
    return out


def itunes(artist: str, album: str, limit: int = 8) -> list[ArtCandidate]:
    term = f"{artist} {album}".strip()
    if not term:
        return []
    data = net.get_json("https://itunes.apple.com/search", params={"term": term, "entity": "album", "limit": limit})
    out = []
    for r in (data or {}).get("results", []):
        art = r.get("artworkUrl100")
        if not art:
            continue
        score = 0.6 * similarity(album, r.get("collectionName")) + 0.4 * similarity(artist, r.get("artistName"))
        out.append(ArtCandidate(
            url=art.replace("100x100bb", "1400x1400bb"), thumb_url=art.replace("100x100bb", "250x250bb"),
            source="iTunes", title=r.get("collectionName", ""), artist=r.get("artistName", ""),
            width=1400, height=1400, score=score,
        ))
    return out


def deezer(artist: str, album: str, limit: int = 8) -> list[ArtCandidate]:
    if not album:
        return []
    q = f'album:"{album}"' + (f' artist:"{artist}"' if artist else "")
    data = net.get_json("https://api.deezer.com/search/album", params={"q": q, "limit": limit})
    out = []
    for r in (data or {}).get("data", []):
        if not r.get("cover_xl"):
            continue
        a = (r.get("artist") or {}).get("name", "")
        score = 0.6 * similarity(album, r.get("title")) + 0.4 * similarity(artist, a)
        out.append(ArtCandidate(
            url=r["cover_xl"], thumb_url=r.get("cover_medium") or r["cover_xl"], source="Deezer",
            title=r.get("title", ""), artist=a, width=1000, height=1000, score=score,
        ))
    return out


def search(artist: str, album: str, release_id: str = "", release_group_id: str = "",
           sources: list[str] | None = None) -> list[ArtCandidate]:
    sources = sources or ["coverartarchive", "itunes", "deezer"]
    out: list[ArtCandidate] = []
    for s in sources:                      # the order of `sources` is the priority: earlier sources come first
        found: list[ArtCandidate] = []
        try:
            if s == "coverartarchive":
                found = coverartarchive(release_id, release_group_id)
            elif s == "itunes":
                found = itunes(artist, album)
            elif s == "deezer":
                found = deezer(artist, album)
        except net.NetError:
            continue
        out += sorted(found, key=lambda c: -c.score)       # best match first within one source
    return out


def best(artist: str, album: str, release_id: str = "", release_group_id: str = "",
         sources: list[str] | None = None, min_score: float = 0.75) -> tuple[ArtCandidate, bytes] | None:
    """Pick and download a cover: the first one, by source priority, that is a good enough match."""
    for cand in search(artist, album, release_id, release_group_id, sources):
        if cand.score < min_score:
            continue
        data = net.get_bytes(cand.url, timeout=40)
        if data and len(data) > 1000:
            return cand, data
    return None


def album_key(artist: str, album: str) -> tuple[str, str]:
    return norm(artist), norm(album)
