"""Split CUE-sheet albums (one big audio file + .cue) into individual, tagged track files.

* Lossless images (FLAC, WAV, APE, WavPack, TTA, AIFF) become FLAC tracks, cut at exact sample positions
  so nothing is lost or duplicated between tracks (gaps are appended to the previous track, as most
  rippers and players expect).
* Lossy images (MP3, AAC, Ogg, Opus) are cut without re-encoding (cuts land on the nearest audio frame).
* Tags come from the CUE sheet (album, artists, titles, track and disc numbers, date, genre, ISRC,
  composer, catalog number), with the image's own tags and cover art as a fallback.
* CUE sheets embedded in FLAC/WavPack/APE files (a CUESHEET tag) are found too.

Splitting uses ffmpeg: from the system, from Settings, or (Windows) downloaded on request.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import tags as tagio
from .config import data_dir, load_settings
from .progress import NULL_TASK, Task
from .textutil import sanitize_component

LOSSLESS_EXT = {".flac", ".wav", ".ape", ".wv", ".tta", ".aiff", ".aif"}
LOSSY_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
AUDIO_EXT = LOSSLESS_EXT | LOSSY_EXT
_CREATE_FLAGS = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


class CueError(Exception):
    pass


# ---------------------------------------------------------------- parsing
@dataclass
class CueTrack:
    number: int
    title: str = ""
    performer: str = ""
    songwriter: str = ""
    isrc: str = ""
    file: str = ""            # audio file this track's INDEX 01 is in (resolved path, "" if missing)
    start: int = -1           # INDEX 01, in CD frames (1/75 s) from the start of `file`


@dataclass
class CueSheet:
    path: str                 # the .cue file, or the audio file that embeds the sheet
    title: str = ""
    performer: str = ""
    songwriter: str = ""
    date: str = ""
    genre: str = ""
    catalog: str = ""
    disc: str = ""
    total_discs: str = ""
    tracks: list[CueTrack] = field(default_factory=list)
    files: list[str] = field(default_factory=list)   # resolved audio files, in order
    problems: list[str] = field(default_factory=list)
    embedded: bool = False

    @property
    def folder(self) -> str:
        return str(Path(self.path).parent)

    @property
    def splittable(self) -> bool:
        """One audio file holding several tracks (a CUE per already-split album has nothing to split)."""
        return not self.problems and any(sum(1 for t in self.tracks if t.file == f) > 1 for f in self.files)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _value(rest: str) -> str:
    rest = rest.strip()
    if len(rest) >= 2 and rest[0] == '"' and rest.endswith('"'):
        return rest[1:-1].strip()
    return rest.strip('"').strip()


def _frames(mmssff: str) -> int:
    m = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2})", mmssff.strip())
    if not m:
        raise CueError(f"bad time {mmssff!r}")
    mm, ss, ff = (int(x) for x in m.groups())
    return (mm * 60 + ss) * 75 + ff


def resolve_audio(cue_path: str, name: str) -> str:
    """Find the audio file a CUE refers to; EAC often names "CDImage.wav" when the file is now a .flac."""
    folder = Path(cue_path).parent
    direct = folder / name.replace("\\", os.sep)
    if direct.is_file():
        return str(direct)
    stem = Path(name.replace("\\", "/")).stem
    for base in (stem, Path(cue_path).stem):
        for ext in sorted(AUDIO_EXT):
            cand = folder / f"{base}{ext}"
            if cand.is_file():
                return str(cand)
    # the folder's only audio file that isn't a single track
    audio = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT]
    if len(audio) == 1:
        return str(audio[0])
    return ""


def parse_text(text: str, path: str, audio_override: str = "") -> CueSheet:
    sheet = CueSheet(path=path, embedded=bool(audio_override))
    cur_file = ""
    track: CueTrack | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        cmd, _, rest = line.partition(" ")
        cmd = cmd.upper()
        if cmd == "REM":
            key, _, val = rest.strip().partition(" ")
            key, val = key.upper(), _value(val)
            if track is None:
                if key == "DATE":
                    sheet.date = val
                elif key == "GENRE":
                    sheet.genre = val
                elif key == "DISCNUMBER":
                    sheet.disc = val
                elif key == "TOTALDISCS":
                    sheet.total_discs = val
            continue
        if cmd == "FILE":
            m = re.match(r'^\s*"(.*)"\s*(\S+)?\s*$', rest) or re.match(r"^\s*(.*?)(?:\s+(\S+))?\s*$", rest)
            name = m.group(1) if m else rest
            if audio_override:
                cur_file = audio_override
            else:
                cur_file = resolve_audio(path, name)
                if not cur_file:
                    sheet.problems.append(f"audio file not found: {name}")
            if cur_file and cur_file not in sheet.files:
                sheet.files.append(cur_file)
            track = None
        elif cmd == "TRACK":
            parts = rest.split()
            if len(parts) >= 2 and parts[1].upper() == "AUDIO" and parts[0].isdigit():
                track = CueTrack(number=int(parts[0]), file=cur_file)
                sheet.tracks.append(track)
            else:
                track = None   # data track
        elif cmd == "INDEX" and track is not None:
            num, _, t = rest.strip().partition(" ")
            if num.strip() == "01":
                try:
                    track.start = _frames(t)
                except CueError as e:
                    sheet.problems.append(f"track {track.number}: {e}")
                track.file = cur_file
        elif cmd in ("TITLE", "PERFORMER", "SONGWRITER"):
            attr = cmd.lower()
            setattr(track if track is not None else sheet, attr, _value(rest))
        elif cmd == "ISRC" and track is not None:
            track.isrc = _value(rest)
        elif cmd == "CATALOG" and track is None:
            sheet.catalog = _value(rest)
    if not sheet.tracks:
        sheet.problems.append("no audio tracks")
    for t in sheet.tracks:
        if t.start < 0:
            sheet.problems.append(f"track {t.number} has no INDEX 01")
    return sheet


def parse(path: str) -> CueSheet:
    return parse_text(_decode(Path(path).read_bytes()), path)


def embedded_sheet(audio_path: str) -> CueSheet | None:
    """A CUE sheet stored inside a FLAC/WavPack/APE file (CUESHEET tag), if any."""
    try:
        import mutagen
        f = mutagen.File(audio_path)
    except Exception:
        return None
    if f is None or not f.tags:
        return None
    text = ""
    for key in ("CUESHEET", "cuesheet", "Cuesheet"):
        try:
            v = f.tags.get(key)
        except Exception:
            v = None
        if v:
            text = str(v[0] if isinstance(v, list) else v)
            break
    if not text:
        return None
    return parse_text(text, audio_path, audio_override=audio_path)


# ---------------------------------------------------------------- plan
@dataclass
class TrackJob:
    track: CueTrack
    src: str
    dst: str
    start_sample: int
    end_sample: int | None    # None = to the end of the file
    lossless: bool
    tags: dict[str, str]


def _sample_rate(path: str) -> int:
    try:
        import mutagen
        f = mutagen.File(path)
        return int(getattr(f.info, "sample_rate", 0) or 44100)
    except Exception:
        return 44100


def output_name(sheet: CueSheet, t: CueTrack, ext: str) -> str:
    title = t.title or f"Track {t.number}"
    various = t.performer and sheet.performer and t.performer != sheet.performer
    stem = f"{t.number:02d} - {t.performer} - {title}" if various else f"{t.number:02d} - {title}"
    return sanitize_component(stem, 150) + ext


def plan(sheet: CueSheet, dest: str | None = None) -> list[TrackJob]:
    """Work out every track file to create. Raises CueError when the sheet can't be split."""
    if sheet.problems:
        raise CueError("; ".join(sheet.problems))
    out_dir = Path(dest or sheet.folder)
    total = str(len(sheet.tracks))
    image_tags: dict[str, dict[str, str]] = {}
    jobs = []
    for i, t in enumerate(sheet.tracks):
        src = t.file
        ext = Path(src).suffix.lower()
        lossless = ext in LOSSLESS_EXT
        if src not in image_tags:
            try:
                image_tags[src] = tagio.read(src, with_artwork=False).tags
            except Exception:
                image_tags[src] = {}
        base = image_tags[src]
        rate = _sample_rate(src)
        nxt = next((n for n in sheet.tracks[i + 1:] if n.file == src), None)
        first_in_file = all(p.file != src for p in sheet.tracks[:i])
        start_frames = 0 if first_in_file else t.start      # audio before the first track stays with it
        start = round(start_frames * rate / 75)
        end = round(nxt.start * rate / 75) if nxt else None
        if end is not None and end <= start:
            raise CueError(f"track {t.number} has no length (check the INDEX times)")
        album_artist = sheet.performer or base.get("albumartist") or base.get("artist", "")
        tags = {
            "title": t.title or f"Track {t.number}",
            "artist": t.performer or album_artist,
            "album": sheet.title or base.get("album", ""),
            "albumartist": album_artist,
            "tracknumber": str(t.number),
            "totaltracks": total,
            "discnumber": sheet.disc or base.get("discnumber", ""),
            "totaldiscs": sheet.total_discs or base.get("totaldiscs", ""),
            "date": sheet.date or base.get("date", ""),
            "genre": sheet.genre or base.get("genre", ""),
            "composer": t.songwriter or sheet.songwriter or "",
            "isrc": t.isrc,
            "catalognumber": sheet.catalog or base.get("catalognumber", ""),
            "label": base.get("label", ""),
        }
        out_ext = ".flac" if lossless else ext
        jobs.append(TrackJob(t, src, str(out_dir / output_name(sheet, t, out_ext)), start, end, lossless,
                             {k: v for k, v in tags.items() if v}))
    return jobs


def already_split(jobs: list[TrackJob]) -> bool:
    return bool(jobs) and all(os.path.exists(j.dst) for j in jobs)


# ---------------------------------------------------------------- ffmpeg
FFMPEG_VERSION = "9.0.2"
_FFMPEG_WIN = ("https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip",
               "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba")
_FFMPEG_EXE = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


def downloaded_ffmpeg_path() -> Path:
    return data_dir() / "bin" / _FFMPEG_EXE


def find_ffmpeg() -> str | None:
    configured = getattr(load_settings(), "ffmpeg_path", "")
    if configured and Path(configured).is_file():
        return configured
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for cand in (here / _FFMPEG_EXE, here / "vendor" / _FFMPEG_EXE, Path(sys.executable).parent / _FFMPEG_EXE):
        if cand.is_file():
            return str(cand)
    found = shutil.which(_FFMPEG_EXE)
    if found:
        return found
    d = downloaded_ffmpeg_path()
    return str(d) if d.is_file() else None


def can_download_ffmpeg() -> bool:
    return sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64", "x64")


def ffmpeg_help() -> str:
    if can_download_ffmpeg():
        return "MusicMaid can download ffmpeg for you (about 115 MB, once)."
    if sys.platform.startswith("linux"):
        return ("Install it with your package manager, e.g. 'sudo dnf install ffmpeg-free' (Fedora) or "
                "'sudo apt install ffmpeg' (Debian/Ubuntu), or set its location in Settings.")
    return "Install ffmpeg and make sure it's on your PATH, or set its location in Settings."


def download_ffmpeg(task: Task = NULL_TASK) -> str:
    from . import net
    if not can_download_ffmpeg():
        raise CueError("No ffmpeg download for this system. " + ffmpeg_help())
    url, sha = _FFMPEG_WIN
    work = Path(tempfile.mkdtemp(prefix="musicmaid-ffmpeg-"))
    try:
        archive = net.download_file(url, work / "ffmpeg.zip", sha256=sha, task=task,
                                    label=f"Downloading ffmpeg {FFMPEG_VERSION}", timeout=120)
        with zipfile.ZipFile(archive) as z:
            name = next((m for m in z.namelist() if m.endswith("/bin/ffmpeg.exe")), None)
            if not name:
                raise CueError("The ffmpeg download didn't contain ffmpeg.exe.")
            target = downloaded_ffmpeg_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".part")
            tmp.write_bytes(z.read(name))
            os.replace(tmp, target)
    except net.NetError as e:
        raise CueError(str(e)) from e
    finally:
        shutil.rmtree(work, ignore_errors=True)
    task.log(f"Installed ffmpeg {FFMPEG_VERSION} to {target}")
    return str(target)


# ---------------------------------------------------------------- splitting
def _cmd(ffmpeg: str, j: TrackJob, out: str) -> list[str]:
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if j.lossless:
        trim = f"atrim=start_sample={j.start_sample}" + (f":end_sample={j.end_sample}" if j.end_sample else "")
        cmd += ["-i", j.src, "-map", "0:a:0", "-af", f"{trim},asetpts=PTS-STARTPTS",
                "-c:a", "flac", "-compression_level", "5", "-map_metadata", "-1", "-f", "flac", out]
    else:
        rate = _sample_rate(j.src)
        cmd += ["-i", j.src, "-ss", f"{j.start_sample / rate:.6f}"]
        if j.end_sample:
            cmd += ["-to", f"{j.end_sample / rate:.6f}"]
        fmt = {".m4a": "ipod", ".aac": "adts", ".ogg": "ogg", ".opus": "ogg", ".wma": "asf"}.get(
            Path(j.dst).suffix.lower(), Path(j.dst).suffix.lower().lstrip("."))
        cmd += ["-map", "0:a:0", "-c", "copy", "-map_metadata", "-1", "-f", fmt, out]
    return cmd


def split(jobs: list[TrackJob], task: Task = NULL_TASK, *, overwrite: bool = False,
          on_created=lambda path: None) -> tuple[list[str], list[str]]:
    """Create the track files. Returns (created, skipped). Stops at the first failure (CueError) after
    removing that track's partial file; files already created stay (and were reported via on_created)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise CueError("ffmpeg is needed to split CUE sheets. " + ffmpeg_help())
    created, skipped = [], []
    art_cache: dict[str, object] = {}
    for i, j in enumerate(jobs):
        task.progress(i, len(jobs), f"Splitting: {Path(j.dst).name}")
        if os.path.exists(j.dst) and not overwrite:
            skipped.append(j.dst)
            continue
        Path(j.dst).parent.mkdir(parents=True, exist_ok=True)
        part = j.dst + ".part"
        proc = subprocess.run(_cmd(ffmpeg, j, part), capture_output=True, creationflags=_CREATE_FLAGS)
        if proc.returncode != 0 or not os.path.exists(part):
            Path(part).unlink(missing_ok=True)
            err = proc.stderr.decode(errors="replace").strip().splitlines()
            raise CueError(f"ffmpeg couldn't split track {j.track.number}: {err[-1] if err else 'unknown error'}")
        os.replace(part, j.dst)
        if j.src not in art_cache:
            art_cache[j.src] = tagio.read_artwork(j.src)
        art = art_cache[j.src]
        tagio.write(j.dst, j.tags, art if art is not None else tagio._KEEP)
        created.append(j.dst)
        on_created(j.dst)
    task.progress(len(jobs), len(jobs), "")
    return created, skipped


# ---------------------------------------------------------------- finding sheets
def find_sheets(folders: list[str], long_tracks: list[str] = ()) -> list[CueSheet]:
    """All .cue files under folders, plus CUE sheets embedded in the given (long) audio files."""
    sheets: list[CueSheet] = []
    covered: set[str] = set()
    for root in folders:
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if name.lower().endswith(".cue"):
                    path = os.path.join(dirpath, name)
                    try:
                        s = parse(path)
                    except (OSError, CueError) as e:
                        s = CueSheet(path=path, problems=[str(e)])
                    sheets.append(s)
                    covered.update(s.files)
    for p in long_tracks:
        if p not in covered and Path(p).suffix.lower() in {".flac", ".wv", ".ape"}:
            s = embedded_sheet(p)
            if s:
                sheets.append(s)
    return sheets
