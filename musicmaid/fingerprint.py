"""Chromaprint audio fingerprints via the ``fpcalc`` tool, plus raw-fingerprint comparison."""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import stat
import tarfile
import zipfile
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .config import data_dir, load_settings
from .db import Database, Track
from .progress import NULL_TASK, Task

_CREATE_FLAGS = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


class FingerprintError(Exception):
    pass


# Official Chromaprint builds, pinned by SHA-256 so a tampered download is rejected.
CHROMAPRINT_VERSION = "1.5.1"
_DOWNLOADS = {
    ("win32", "x86_64"): ("windows-x86_64.zip",
                          "36b478e16aa69f757f376645db0d436073a42c0097b6bb2677109e7835b59bbc"),
    ("linux", "x86_64"): ("linux-x86_64.tar.gz",
                          "4d7433a7f778e5946d7225230681cbcd634e153316ecac87c538c33ac32387a5"),
}
_EXE = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"


def _download_key() -> tuple[str, str]:
    machine = platform.machine().lower()
    return sys.platform, "x86_64" if machine in ("amd64", "x86_64", "x64") else machine


def can_download_fpcalc() -> bool:
    return _download_key() in _DOWNLOADS


def downloaded_fpcalc_path() -> Path:
    return data_dir() / "bin" / _EXE


def download_fpcalc(task: Task = NULL_TASK) -> str:
    """Fetch fpcalc from Chromaprint's GitHub releases into the MusicMaid data folder."""
    from . import net

    entry = _DOWNLOADS.get(_download_key())
    if not entry:
        raise FingerprintError(f"No prebuilt fpcalc for {sys.platform}/{platform.machine()}; "
                               "install Chromaprint with your package manager.")
    suffix, sha256 = entry
    url = (f"https://github.com/acoustid/chromaprint/releases/download/v{CHROMAPRINT_VERSION}/"
           f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-{suffix}")
    task.progress(0, 0, "Downloading fpcalc (Chromaprint)...")
    try:
        data = net.get_bytes(url, timeout=120)
    except net.NetError as e:
        raise FingerprintError(f"Could not download fpcalc: {e}") from e
    if not data:
        raise FingerprintError(f"Could not download fpcalc from {url}")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FingerprintError("Downloaded fpcalc failed its checksum check; not installed.")
    try:
        if suffix.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                name = next(m for m in z.namelist() if m.rsplit("/", 1)[-1] == _EXE)
                binary = z.read(name)
        else:
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                member = next(m for m in t.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == _EXE)
                binary = t.extractfile(member).read()
    except (StopIteration, zipfile.BadZipFile, tarfile.TarError) as e:
        raise FingerprintError("The fpcalc download didn't contain the expected program.") from e
    target = downloaded_fpcalc_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(binary)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, target)
    task.log(f"Installed fpcalc {CHROMAPRINT_VERSION} to {target}")
    return str(target)


def find_fpcalc() -> str | None:
    configured = load_settings().fpcalc_path
    if configured and Path(configured).is_file():
        return configured
    exe = _EXE
    # bundled next to the app (PyInstaller) or in ./vendor
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for cand in (here / exe, here / "vendor" / exe, Path(sys.executable).parent / exe):
        if cand.is_file():
            return str(cand)
    found = shutil.which(exe)
    if found:
        return found
    downloaded = downloaded_fpcalc_path()
    return str(downloaded) if downloaded.is_file() else None


def _run_fpcalc(path: str, raw: bool, length: int = 120) -> tuple[float, object]:
    fpcalc = find_fpcalc()
    if not fpcalc:
        raise FingerprintError("fpcalc (Chromaprint) not found. Install chromaprint or set its path in Settings.")
    cmd = [fpcalc, "-json", "-length", str(length)]
    if raw:
        cmd.append("-raw")
    cmd.append(path)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, creationflags=_CREATE_FLAGS)
    except subprocess.TimeoutExpired as e:
        raise FingerprintError(f"fpcalc timed out on {path}") from e
    if proc.returncode != 0 and not proc.stdout:
        raise FingerprintError(proc.stderr.decode(errors="replace").strip() or f"fpcalc failed on {path}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as e:
        raise FingerprintError(f"Bad fpcalc output for {path}") from e
    return float(data.get("duration", 0)), data.get("fingerprint")


def raw_fingerprint(path: str) -> tuple[float, np.ndarray]:
    duration, fp = _run_fpcalc(path, raw=True)
    return duration, np.asarray(fp or [], dtype=np.uint32)


def compressed_fingerprint(path: str) -> tuple[float, str]:
    duration, fp = _run_fpcalc(path, raw=False)
    return duration, fp or ""


def ensure_raw(db: Database, tracks: list[Track], task: Task = NULL_TASK) -> int:
    """Compute raw fingerprints for tracks lacking one. Returns number computed."""
    todo = [t for t in tracks if not t.has_fp and not t.error]
    if not todo:
        return 0
    done = 0

    def work(t: Track):
        try:
            return t, raw_fingerprint(t.path), None
        except Exception as e:
            return t, None, e

    workers = max(1, min(8, (os.cpu_count() or 2)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (t, res, err) in enumerate(pool.map(work, todo), 1):
            task.progress(n, len(todo), f"Fingerprinting {t.filename}")
            if err:
                task.log(f"Fingerprint failed for {t.path}: {err}")
                if isinstance(err, FingerprintError) and "not found" in str(err):
                    raise err
                continue
            duration, arr = res
            if arr.size:
                db.set_fingerprint(t.id, arr.astype("<u4").tobytes(), None, duration)
                done += 1
    return done


def ensure_compressed(db: Database, track: Track) -> tuple[float, str]:
    if track.fp:
        return track.fp_duration or track.duration, track.fp
    duration, fp = compressed_fingerprint(track.path)
    db.set_fingerprint(track.id, None, fp, duration)
    return duration, fp


# ---------------------------------------------------------------- comparison
def decode_raw(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<u4")


def similarity(a: np.ndarray, b: np.ndarray, max_offset: int = 80, min_overlap: int = 40) -> float:
    """Return 1 - bit error rate at the best alignment (1.0 = identical audio)."""
    if a.size < min_overlap or b.size < min_overlap:
        return 0.0
    best = 0.0
    # coarse search on offsets, then the best region is fine anyway because step is 1
    for off in range(-max_offset, max_offset + 1):
        if off >= 0:
            x, y = a[off:], b
        else:
            x, y = a, b[-off:]
        n = min(x.size, y.size)
        if n < min_overlap:
            continue
        diff = np.bitwise_xor(x[:n], y[:n])
        ber = np.bitwise_count(diff).sum() / (32.0 * n)
        sim = 1.0 - ber
        if sim > best:
            best = sim
            if best > 0.97:
                break
    return float(best)
