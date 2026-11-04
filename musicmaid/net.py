"""HTTP session with polite per-host rate limiting and retries."""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

import requests

from . import __version__

# MusicBrainz asks clients to identify themselves; users can add contact info via env var.
USER_AGENT = f"MusicMaid/{__version__} ( {os.environ.get('MUSICMAID_CONTACT', 'desktop music tagger')} )"

# minimum seconds between requests per host
_HOST_INTERVAL = {
    "musicbrainz.org": 1.05,
    "api.acoustid.org": 0.34,
    "itunes.apple.com": 0.5,
    "api.deezer.com": 0.12,
}


class NetError(Exception):
    pass


class _Limiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str) -> None:
        interval = next((v for k, v in _HOST_INTERVAL.items() if host.endswith(k)), 0.0)
        if not interval:
            return
        with self._lock:
            now = time.monotonic()
            t = max(now, self._next.get(host, 0.0))
            self._next[host] = t + interval
        if t > now:
            time.sleep(t - now)


_limiter = _Limiter()
_local = threading.local()


def session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        _local.session = s
    return s


def get(url: str, *, params=None, data=None, timeout: float = 20, retries: int = 3, accept: str = "application/json") -> requests.Response:
    host = urlparse(url).hostname or ""
    last: Exception | None = None
    for attempt in range(retries):
        _limiter.wait(host)
        try:
            if data is not None:
                r = session().post(url, data=data, params=params, timeout=timeout, headers={"Accept": accept})
            else:
                r = session().get(url, params=params, timeout=timeout, headers={"Accept": accept})
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 502, 503, 504):
            last = NetError(f"{host} returned {r.status_code}")
            time.sleep(2.0 * (attempt + 1))
            continue
        return r
    raise NetError(str(last) if last else f"Request to {host} failed")


def get_json(url: str, **kw):
    r = get(url, **kw)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise NetError(f"{urlparse(url).hostname} returned HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as e:
        raise NetError(f"Invalid JSON from {url}") from e


def get_bytes(url: str, **kw) -> bytes | None:
    r = get(url, accept="*/*", **kw)
    if r.status_code >= 400:
        return None
    return r.content


def download_file(url: str, dest, *, sha256: str = "", task=None, label: str = "Downloading", timeout: float = 60):
    """Stream url to dest (a Path), reporting progress; verify sha256 when given. Removes dest on failure."""
    import hashlib
    from pathlib import Path
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    done = 0
    try:
        with session().get(url, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                raise NetError(f"{label} failed (HTTP {r.status_code})")
            total = int(r.headers.get("Content-Length") or 0)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if task is not None:
                        task.progress(done // 1024, total // 1024, f"{label}… {done / 1e6:.0f} / {total / 1e6:.0f} MB")
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
    except NetError:
        dest.unlink(missing_ok=True)
        raise
    except requests.RequestException as e:
        dest.unlink(missing_ok=True)
        raise NetError(f"{label} failed: {e}") from e
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if sha256 and h.hexdigest() != sha256.lower():
        dest.unlink(missing_ok=True)
        raise NetError(f"{label}: the download failed its checksum check")
    return dest
