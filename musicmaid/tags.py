"""Format-independent reading and writing of tags and embedded artwork.

Every supported container (ID3, Vorbis comments, MP4, ASF, APEv2) is mapped onto
a single flat dictionary of string fields, using MusicBrainz Picard's naming
conventions on disk so files stay interoperable with other taggers.
"""
from __future__ import annotations

import base64
import io
import struct
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.apev2 import APEBinaryValue, APEv2, APEv2File
from mutagen.asf import ASF, ASFByteArrayAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, COMM, ID3, ID3NoHeaderError, TALB, TBPM, TCMP, TCOM, TCON, TDOR, TDRC, TIT2,
    TPE1, TPE2, TPOS, TPUB, TRCK, TSRC, TXXX, UFID,
)
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.ogg import OggFileType

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".mp4", ".aac", ".alac",
    ".wma", ".asf", ".wav", ".aif", ".aiff", ".ape", ".wv", ".mpc", ".tta", ".ofr", ".dsf",
}
LOSSLESS_CODECS = {"flac", "alac", "wav", "aiff", "ape", "wavpack", "tta", "optimfrog", "dsd"}

# Canonical field names, in display order.
FIELDS: list[tuple[str, str]] = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("tracknumber", "Track #"),
    ("totaltracks", "Total Tracks"),
    ("discnumber", "Disc #"),
    ("totaldiscs", "Total Discs"),
    ("date", "Date"),
    ("originaldate", "Original Date"),
    ("genre", "Genre"),
    ("composer", "Composer"),
    ("label", "Label"),
    ("catalognumber", "Catalog #"),
    ("isrc", "ISRC"),
    ("bpm", "BPM"),
    ("compilation", "Compilation"),
    ("comment", "Comment"),
    ("releasecountry", "Release Country"),
    ("releasetype", "Release Type"),
    ("musicbrainz_recordingid", "MB Recording ID"),
    ("musicbrainz_releasetrackid", "MB Release Track ID"),
    ("musicbrainz_albumid", "MB Release ID"),
    ("musicbrainz_artistid", "MB Artist ID"),
    ("musicbrainz_albumartistid", "MB Album Artist ID"),
    ("musicbrainz_releasegroupid", "MB Release Group ID"),
    ("acoustid_id", "AcoustID"),
]
FIELD_NAMES = [f for f, _ in FIELDS]
FIELD_LABELS = dict(FIELDS)
EDITABLE_FIELDS = FIELD_NAMES[:20]


@dataclass
class AudioInfo:
    duration: float = 0.0
    bitrate: int = 0  # kbps
    sample_rate: int = 0
    channels: int = 0
    bits_per_sample: int = 0
    codec: str = ""
    lossless: bool = False


@dataclass
class Artwork:
    data: bytes
    mime: str = "image/jpeg"
    width: int = 0
    height: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "Artwork":
        mime, w, h = image_info(data)
        return cls(data=data, mime=mime, width=w, height=h)


@dataclass
class TagData:
    tags: dict[str, str] = field(default_factory=dict)
    info: AudioInfo = field(default_factory=AudioInfo)
    artwork: Artwork | None = None


class UnsupportedFile(Exception):
    pass


# ---------------------------------------------------------------- image helpers
def image_info(data: bytes) -> tuple[str, int, int]:
    """Return (mime, width, height) of an image without requiring Pillow."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return "image/png", w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "image/jpeg", w, h
            i += 2 + seglen
        return "image/jpeg", 0, 0
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return "image/gif", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", 0, 0
    return "image/jpeg", 0, 0


def prepare_artwork(data: bytes, max_size: int = 0) -> bytes:
    """Downscale/convert artwork to JPEG if it is larger than max_size (needs Pillow)."""
    mime, w, h = image_info(data)
    if (not max_size or max(w, h) <= max_size) and mime in ("image/jpeg", "image/png"):
        return data
    try:
        from PIL import Image
    except ImportError:
        return data
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        if max_size and max(im.size) > max_size:
            im.thumbnail((max_size, max_size), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=90, optimize=True)
        return out.getvalue()
    except Exception:
        return data


# ---------------------------------------------------------------- helpers
def _split_pair(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    parts = str(value).split("/", 1)
    a = parts[0].strip()
    b = parts[1].strip() if len(parts) > 1 else ""
    return a, b


def _pair(n: str | None, total: str | None) -> str:
    n = (n or "").strip()
    total = (total or "").strip()
    if not n:
        return ""
    return f"{n}/{total}" if total else n


def _int(v: str | None) -> int:
    try:
        return int(str(v).split("/")[0].strip())
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------- ID3
_ID3_SIMPLE = {
    "title": TIT2, "artist": TPE1, "album": TALB, "albumartist": TPE2, "date": TDRC,
    "originaldate": TDOR, "genre": TCON, "composer": TCOM, "label": TPUB, "isrc": TSRC,
    "bpm": TBPM, "compilation": TCMP,
}
_ID3_TXXX = {
    "catalognumber": "CATALOGNUMBER",
    "releasecountry": "MusicBrainz Album Release Country",
    "releasetype": "MusicBrainz Album Type",
    "musicbrainz_releasetrackid": "MusicBrainz Release Track Id",
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "acoustid_id": "Acoustid Id",
}
_MB_UFID_OWNER = "http://musicbrainz.org"


def _id3_read(tags: ID3, out: dict[str, str]) -> Artwork | None:
    for name, cls in _ID3_SIMPLE.items():
        frame = tags.get(cls.__name__)
        if frame is not None and frame.text:
            out[name] = "; ".join(str(t) for t in frame.text)
    for name, desc in _ID3_TXXX.items():
        for frame in tags.getall("TXXX"):
            if frame.desc.lower() == desc.lower() and frame.text:
                out[name] = "; ".join(str(t) for t in frame.text)
                break
    ufid = tags.get(f"UFID:{_MB_UFID_OWNER}")
    if ufid is not None:
        out["musicbrainz_recordingid"] = ufid.data.decode("ascii", "replace")
    out["tracknumber"], out["totaltracks"] = _split_pair(str(tags["TRCK"].text[0]) if "TRCK" in tags and tags["TRCK"].text else "")
    out["discnumber"], out["totaldiscs"] = _split_pair(str(tags["TPOS"].text[0]) if "TPOS" in tags and tags["TPOS"].text else "")
    comms = [c for c in tags.getall("COMM") if not c.desc or c.desc.lower() == "comment"]
    if comms and comms[0].text:
        out["comment"] = str(comms[0].text[0])
    else:
        # some tools (e.g. ffmpeg) store the comment as a TXXX:comment frame instead
        txxx = [f for f in tags.getall("TXXX") if f.desc.lower() == "comment" and f.text]
        if txxx:
            out["comment"] = str(txxx[0].text[0])
    pics = tags.getall("APIC")
    if pics:
        front = next((p for p in pics if p.type == 3), pics[0])
        return Artwork.from_bytes(front.data)
    return None


def _id3_write(tags: ID3, merged: dict[str, str], changed: set[str]) -> None:
    for name in changed:
        val = merged.get(name, "")
        if name in _ID3_SIMPLE:
            cls = _ID3_SIMPLE[name]
            tags.delall(cls.__name__)
            if val:
                tags.add(cls(encoding=3, text=[val]))
        elif name in _ID3_TXXX:
            desc = _ID3_TXXX[name]
            for frame in list(tags.getall("TXXX")):
                if frame.desc.lower() == desc.lower():
                    tags.delall(frame.HashKey)
            if val:
                tags.add(TXXX(encoding=3, desc=desc, text=[val]))
        elif name == "musicbrainz_recordingid":
            tags.delall(f"UFID:{_MB_UFID_OWNER}")
            if val:
                tags.add(UFID(owner=_MB_UFID_OWNER, data=val.encode("ascii", "replace")))
        elif name == "comment":
            for c in list(tags.getall("COMM")):
                if not c.desc or c.desc.lower() == "comment":
                    tags.delall(c.HashKey)
            for x in list(tags.getall("TXXX")):
                if x.desc.lower() == "comment":
                    tags.delall(x.HashKey)
            if val:
                tags.add(COMM(encoding=3, lang="eng", desc="", text=[val]))
    if changed & {"tracknumber", "totaltracks"}:
        tags.delall("TRCK")
        v = _pair(merged.get("tracknumber"), merged.get("totaltracks"))
        if v:
            tags.add(TRCK(encoding=3, text=[v]))
    if changed & {"discnumber", "totaldiscs"}:
        tags.delall("TPOS")
        v = _pair(merged.get("discnumber"), merged.get("totaldiscs"))
        if v:
            tags.add(TPOS(encoding=3, text=[v]))


def _id3_set_art(tags: ID3, art: Artwork | None) -> None:
    tags.delall("APIC")
    if art is not None:
        tags.add(APIC(encoding=3, mime=art.mime, type=3, desc="Cover", data=art.data))


# ---------------------------------------------------------------- Vorbis comments
_VORBIS = {
    "title": "TITLE", "artist": "ARTIST", "album": "ALBUM", "albumartist": "ALBUMARTIST",
    "tracknumber": "TRACKNUMBER", "totaltracks": "TRACKTOTAL", "discnumber": "DISCNUMBER",
    "totaldiscs": "DISCTOTAL", "date": "DATE", "originaldate": "ORIGINALDATE", "genre": "GENRE",
    "composer": "COMPOSER", "label": "LABEL", "catalognumber": "CATALOGNUMBER", "isrc": "ISRC",
    "bpm": "BPM", "compilation": "COMPILATION", "comment": "COMMENT",
    "releasecountry": "RELEASECOUNTRY", "releasetype": "RELEASETYPE",
    "musicbrainz_recordingid": "MUSICBRAINZ_TRACKID",
    "musicbrainz_releasetrackid": "MUSICBRAINZ_RELEASETRACKID",
    "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID", "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_albumartistid": "MUSICBRAINZ_ALBUMARTISTID",
    "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID", "acoustid_id": "ACOUSTID_ID",
}
_VORBIS_ALIASES = {"totaltracks": ["TOTALTRACKS"], "totaldiscs": ["TOTALDISCS"], "albumartist": ["ALBUM ARTIST"], "comment": ["DESCRIPTION"]}


def _vorbis_read(vc, out: dict[str, str]) -> None:
    keys = {k.upper(): k for k in vc.keys()}
    for name, key in _VORBIS.items():
        for candidate in [key, *_VORBIS_ALIASES.get(name, [])]:
            if candidate in keys:
                vals = vc[keys[candidate]]
                if vals:
                    out[name] = "; ".join(vals)
                    break
    for name, total in (("tracknumber", "totaltracks"), ("discnumber", "totaldiscs")):
        if "/" in out.get(name, ""):
            n, t = _split_pair(out[name])
            out[name] = n
            out.setdefault(total, t)


def _vorbis_write(vc, merged: dict[str, str], changed: set[str]) -> None:
    existing = {k.upper(): k for k in vc.keys()}
    for name in changed:
        key = _VORBIS.get(name)
        if not key:
            continue
        for candidate in [key, *_VORBIS_ALIASES.get(name, [])]:
            if candidate in existing:
                del vc[existing[candidate]]
        val = merged.get(name, "")
        if val:
            vc[key] = [val]


def _vorbis_art_read(vc) -> Artwork | None:
    for key in ("METADATA_BLOCK_PICTURE", "metadata_block_picture"):
        if key in vc:
            for b64 in vc[key]:
                try:
                    pic = Picture(base64.b64decode(b64))
                except Exception:
                    continue
                return Artwork.from_bytes(pic.data)
    return None


def _make_flac_picture(art: Artwork) -> Picture:
    pic = Picture()
    pic.type = 3
    pic.mime = art.mime
    pic.desc = "Cover"
    pic.width, pic.height = art.width, art.height
    pic.depth = 24
    pic.data = art.data
    return pic


# ---------------------------------------------------------------- MP4
_MP4_SIMPLE = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART",
    "date": "\xa9day", "genre": "\xa9gen", "composer": "\xa9wrt", "comment": "\xa9cmt",
}
_MP4_FREEFORM = {
    "label": "LABEL", "catalognumber": "CATALOGNUMBER", "isrc": "ISRC", "originaldate": "originaldate",
    "releasecountry": "MusicBrainz Album Release Country", "releasetype": "MusicBrainz Album Type",
    "musicbrainz_recordingid": "MusicBrainz Track Id",
    "musicbrainz_releasetrackid": "MusicBrainz Release Track Id",
    "musicbrainz_albumid": "MusicBrainz Album Id", "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id", "acoustid_id": "Acoustid Id",
}
_FF = "----:com.apple.iTunes:"


def _mp4_read(tags, out: dict[str, str]) -> Artwork | None:
    for name, key in _MP4_SIMPLE.items():
        if key in tags and tags[key]:
            out[name] = "; ".join(str(v) for v in tags[key])
    for name, key in _MP4_FREEFORM.items():
        if _FF + key in tags and tags[_FF + key]:
            out[name] = "; ".join(bytes(v).decode("utf-8", "replace") for v in tags[_FF + key])
    if "trkn" in tags and tags["trkn"]:
        n, t = tags["trkn"][0]
        out["tracknumber"], out["totaltracks"] = str(n) if n else "", str(t) if t else ""
    if "disk" in tags and tags["disk"]:
        n, t = tags["disk"][0]
        out["discnumber"], out["totaldiscs"] = str(n) if n else "", str(t) if t else ""
    if "tmpo" in tags and tags["tmpo"]:
        out["bpm"] = str(tags["tmpo"][0])
    if "cpil" in tags:
        out["compilation"] = "1" if tags["cpil"] else ""
    if "covr" in tags and tags["covr"]:
        return Artwork.from_bytes(bytes(tags["covr"][0]))
    return None


def _mp4_write(tags, merged: dict[str, str], changed: set[str]) -> None:
    for name in changed:
        val = merged.get(name, "")
        if name in _MP4_SIMPLE:
            key = _MP4_SIMPLE[name]
            tags.pop(key, None)
            if val:
                tags[key] = [val]
        elif name in _MP4_FREEFORM:
            key = _FF + _MP4_FREEFORM[name]
            tags.pop(key, None)
            if val:
                tags[key] = [MP4FreeForm(val.encode("utf-8"))]
        elif name == "bpm":
            tags.pop("tmpo", None)
            if _int(val):
                tags["tmpo"] = [_int(val)]
        elif name == "compilation":
            tags.pop("cpil", None)
            if val and val not in ("0", "false"):
                tags["cpil"] = True
    if changed & {"tracknumber", "totaltracks"}:
        tags.pop("trkn", None)
        if _int(merged.get("tracknumber")):
            tags["trkn"] = [(_int(merged.get("tracknumber")), _int(merged.get("totaltracks")))]
    if changed & {"discnumber", "totaldiscs"}:
        tags.pop("disk", None)
        if _int(merged.get("discnumber")):
            tags["disk"] = [(_int(merged.get("discnumber")), _int(merged.get("totaldiscs")))]


# ---------------------------------------------------------------- ASF / WMA
_ASF = {
    "title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "albumartist": "WM/AlbumArtist",
    "date": "WM/Year", "originaldate": "WM/OriginalReleaseYear", "genre": "WM/Genre",
    "composer": "WM/Composer", "comment": "Description", "label": "WM/Publisher",
    "catalognumber": "WM/CatalogNo", "isrc": "WM/ISRC", "bpm": "WM/BeatsPerMinute",
    "compilation": "WM/IsCompilation", "totaltracks": "TotalTracks", "totaldiscs": "TotalDiscs",
    "tracknumber": "WM/TrackNumber",
    "musicbrainz_recordingid": "MusicBrainz/Track Id",
    "musicbrainz_releasetrackid": "MusicBrainz/Release Track Id",
    "musicbrainz_albumid": "MusicBrainz/Album Id", "musicbrainz_artistid": "MusicBrainz/Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz/Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz/Release Group Id", "acoustid_id": "Acoustid/Id",
    "releasecountry": "MusicBrainz/Album Release Country", "releasetype": "MusicBrainz/Album Type",
}


def _asf_read(tags, out: dict[str, str]) -> Artwork | None:
    for name, key in _ASF.items():
        if key in tags and tags[key]:
            out[name] = "; ".join(str(v.value) for v in tags[key])
    if "WM/PartOfSet" in tags and tags["WM/PartOfSet"]:
        n, t = _split_pair(str(tags["WM/PartOfSet"][0].value))
        out["discnumber"] = n
        if t:
            out.setdefault("totaldiscs", t)
    for v in tags.get("WM/Picture", []):
        raw = bytes(v.value)
        try:
            ptype, size = struct.unpack_from("<bi", raw)
            pos = 5
            mime_end = raw.index(b"\x00\x00", pos)
            while (mime_end - pos) % 2:
                mime_end = raw.index(b"\x00\x00", mime_end + 1)
            pos = mime_end + 2
            desc_end = raw.index(b"\x00\x00", pos)
            while (desc_end - pos) % 2:
                desc_end = raw.index(b"\x00\x00", desc_end + 1)
            pos = desc_end + 2
            return Artwork.from_bytes(raw[pos:pos + size])
        except (ValueError, struct.error):
            continue
    return None


def _asf_del(tags, key: str) -> None:
    if key in tags:
        del tags[key]


def _asf_write(tags, merged: dict[str, str], changed: set[str]) -> None:
    for name in changed:
        val = merged.get(name, "")
        if name == "discnumber" or name == "totaldiscs":
            _asf_del(tags, "WM/PartOfSet")
            v = _pair(merged.get("discnumber"), merged.get("totaldiscs"))
            if v:
                tags["WM/PartOfSet"] = [v]
        key = _ASF.get(name)
        if not key:
            continue
        _asf_del(tags, key)
        if val:
            tags[key] = [val]


def _asf_picture(art: Artwork) -> ASFByteArrayAttribute:
    data = (struct.pack("<bi", 3, len(art.data)) + art.mime.encode("utf-16-le") + b"\x00\x00"
            + "Cover".encode("utf-16-le") + b"\x00\x00" + art.data)
    return ASFByteArrayAttribute(data)


# ---------------------------------------------------------------- APEv2
_APE = {
    "title": "Title", "artist": "Artist", "album": "Album", "albumartist": "Album Artist",
    "date": "Year", "originaldate": "Original Date", "genre": "Genre", "composer": "Composer",
    "comment": "Comment", "label": "Label", "catalognumber": "CatalogNumber", "isrc": "ISRC",
    "bpm": "BPM", "compilation": "Compilation", "releasecountry": "ReleaseCountry",
    "releasetype": "MUSICBRAINZ_ALBUMTYPE",
    "musicbrainz_recordingid": "MUSICBRAINZ_TRACKID",
    "musicbrainz_releasetrackid": "MUSICBRAINZ_RELEASETRACKID",
    "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID", "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_albumartistid": "MUSICBRAINZ_ALBUMARTISTID",
    "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID", "acoustid_id": "ACOUSTID_ID",
}
_APE_COVER = "Cover Art (Front)"


def _ape_read(tags, out: dict[str, str]) -> Artwork | None:
    lower = {k.lower(): k for k in tags.keys()}
    for name, key in _APE.items():
        k = lower.get(key.lower())
        if k and not isinstance(tags[k], APEBinaryValue):
            out[name] = "; ".join(tags[k])
    if "track" in lower:
        out["tracknumber"], out["totaltracks"] = _split_pair(str(tags[lower["track"]]))
    if "disc" in lower:
        out["discnumber"], out["totaldiscs"] = _split_pair(str(tags[lower["disc"]]))
    k = lower.get(_APE_COVER.lower())
    if k:
        raw = bytes(tags[k].value)
        return Artwork.from_bytes(raw.split(b"\x00", 1)[1] if b"\x00" in raw[:256] else raw)
    return None


def _ape_write(tags, merged: dict[str, str], changed: set[str]) -> None:
    lower = {k.lower(): k for k in tags.keys()}

    def _del(key: str) -> None:
        k = lower.get(key.lower())
        if k:
            del tags[k]

    for name in changed:
        if name in _APE:
            _del(_APE[name])
            if merged.get(name):
                tags[_APE[name]] = merged[name]
    if changed & {"tracknumber", "totaltracks"}:
        _del("Track")
        v = _pair(merged.get("tracknumber"), merged.get("totaltracks"))
        if v:
            tags["Track"] = v
    if changed & {"discnumber", "totaldiscs"}:
        _del("Disc")
        v = _pair(merged.get("discnumber"), merged.get("totaldiscs"))
        if v:
            tags["Disc"] = v


# ---------------------------------------------------------------- public API
def _open(path: str | Path):
    try:
        f = mutagen.File(str(path))
    except mutagen.MutagenError as e:
        raise UnsupportedFile(str(e)) from e
    if f is None:
        raise UnsupportedFile(f"Unrecognised audio file: {path}")
    return f


def _audio_info(f, path: str | Path) -> AudioInfo:
    i = f.info
    codec = type(f).__name__.lower()
    name_map = {"mp3": "mp3", "flac": "flac", "oggvorbis": "vorbis", "oggopus": "opus", "oggflac": "flac",
                "mp4": "aac", "asf": "wma", "wave": "wav", "aiff": "aiff", "monkeysaudio": "ape",
                "wavpack": "wavpack", "musepack": "musepack", "trueaudio": "tta", "optimfrog": "optimfrog",
                "dsf": "dsd", "easymp3": "mp3", "easymp4": "aac"}
    codec = name_map.get(codec, codec)
    if codec == "aac" and getattr(i, "codec", "").startswith("alac"):
        codec = "alac"
    if codec == "wma" and "lossless" in str(getattr(i, "codec_name", "")).lower():
        codec = "wma lossless"
    bitrate = int(getattr(i, "bitrate", 0) or 0)
    length = float(getattr(i, "length", 0.0) or 0.0)
    if not bitrate and length > 0:
        try:
            bitrate = int(Path(path).stat().st_size * 8 / length)
        except OSError:
            pass
    return AudioInfo(
        duration=float(getattr(i, "length", 0.0) or 0.0),
        bitrate=bitrate // 1000 if bitrate > 10000 else bitrate,
        sample_rate=int(getattr(i, "sample_rate", 0) or 0),
        channels=int(getattr(i, "channels", 0) or 0),
        bits_per_sample=int(getattr(i, "bits_per_sample", 0) or 0),
        codec=codec,
        lossless=codec in LOSSLESS_CODECS or codec == "wma lossless",
    )


def read(path: str | Path, *, with_artwork: bool = True) -> TagData:
    f = _open(path)
    out: dict[str, str] = {}
    art = None
    tags = f.tags
    if isinstance(f, MP4):
        if tags is not None:
            art = _mp4_read(tags, out)
    elif isinstance(f, ASF):
        if tags is not None:
            art = _asf_read(tags, out)
    elif isinstance(f, FLAC):
        if tags is not None:
            _vorbis_read(tags, out)
        if f.pictures:
            front = next((p for p in f.pictures if p.type == 3), f.pictures[0])
            art = Artwork.from_bytes(front.data)
    elif isinstance(f, OggFileType):
        if tags is not None:
            _vorbis_read(tags, out)
            art = _vorbis_art_read(tags)
    elif isinstance(tags, ID3):
        art = _id3_read(tags, out)
    elif isinstance(tags, APEv2):
        art = _ape_read(tags, out)
    out = {k: v.strip() for k, v in out.items() if v and v.strip()}
    return TagData(tags=out, info=_audio_info(f, path), artwork=art if with_artwork else None)


_KEEP = object()


def write(path: str | Path, changes: dict[str, str | None], artwork=_KEEP) -> None:
    """Apply tag changes to a file.

    ``changes`` maps field -> new value ("" or None deletes the field).
    ``artwork`` is left untouched by default; pass ``None`` to remove the front
    cover or an :class:`Artwork`/``bytes`` to replace it.
    """
    if isinstance(artwork, (bytes, bytearray)):
        artwork = Artwork.from_bytes(bytes(artwork))
    f = _open(path)
    current = read(path, with_artwork=False).tags
    merged = dict(current)
    for k, v in changes.items():
        merged[k] = (v or "").strip()
    changed = {k for k in changes if (current.get(k) or "") != merged.get(k, "")}
    if not changed and artwork is _KEEP:
        return

    if isinstance(f, MP4):
        if f.tags is None:
            f.add_tags()
        _mp4_write(f.tags, merged, changed)
        if artwork is not _KEEP:
            f.tags.pop("covr", None)
            if artwork is not None:
                fmt = MP4Cover.FORMAT_PNG if artwork.mime == "image/png" else MP4Cover.FORMAT_JPEG
                f.tags["covr"] = [MP4Cover(artwork.data, imageformat=fmt)]
        f.save()
    elif isinstance(f, ASF):
        _asf_write(f.tags, merged, changed)
        if artwork is not _KEEP:
            _asf_del(f.tags, "WM/Picture")
            if artwork is not None:
                f.tags["WM/Picture"] = [_asf_picture(artwork)]
        f.save()
    elif isinstance(f, FLAC):
        if f.tags is None:
            f.add_tags()
        _vorbis_write(f.tags, merged, changed)
        if artwork is not _KEEP:
            others = [p for p in f.pictures if p.type != 3]
            f.clear_pictures()
            for p in others:
                f.add_picture(p)
            if artwork is not None:
                f.add_picture(_make_flac_picture(artwork))
        f.save()
    elif isinstance(f, OggFileType):
        if f.tags is None:
            f.add_tags()
        _vorbis_write(f.tags, merged, changed)
        if artwork is not _KEEP:
            for key in [k for k in f.tags.keys() if k.upper() in ("METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME")]:
                del f.tags[key]
            if artwork is not None:
                f.tags["METADATA_BLOCK_PICTURE"] = [base64.b64encode(_make_flac_picture(artwork).write()).decode("ascii")]
        f.save()
    elif isinstance(f, APEv2File):
        if f.tags is None:
            f.add_tags()
        _ape_write(f.tags, merged, changed)
        if artwork is not _KEEP:
            for k in [k for k in f.tags.keys() if k.lower() == _APE_COVER.lower()]:
                del f.tags[k]
            if artwork is not None:
                ext = "png" if artwork.mime == "image/png" else "jpg"
                f.tags[_APE_COVER] = APEBinaryValue(f"cover.{ext}".encode() + b"\x00" + artwork.data)
        f.save()
    else:
        # MP3, WAV, AIFF, DSF ... -> ID3
        if f.tags is None:
            try:
                f.add_tags()
            except Exception:
                pass
        if not isinstance(f.tags, ID3):
            try:
                tags = ID3(str(path))
            except ID3NoHeaderError:
                tags = ID3()
            f = None
        else:
            tags = f.tags
        _id3_write(tags, merged, changed)
        if artwork is not _KEEP:
            _id3_set_art(tags, artwork)
        if f is not None:
            f.save(v2_version=3) if type(f).__name__ == "MP3" else f.save()
        else:
            tags.save(str(path), v2_version=3)


def read_artwork(path: str | Path) -> Artwork | None:
    try:
        return read(path).artwork
    except UnsupportedFile:
        return None


def is_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS
