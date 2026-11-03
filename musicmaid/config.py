"""Application paths and persistent settings."""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    override = os.environ.get("MUSICMAID_HOME")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "musicmaid"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULT_PATTERN = "{albumartist}/{album} ({year})/{disc_prefix}{tracknumber:02} - {title}"


@dataclass
class Settings:
    library_folders: list[str] = field(default_factory=list)
    acoustid_api_key: str = ""
    fpcalc_path: str = ""  # empty = auto-detect
    offer_fpcalc_download: bool = True  # ask at startup when fpcalc is missing
    check_for_updates: bool = True  # look for a new release on GitHub at startup
    skipped_update: str = ""  # version the user chose to skip
    # identification
    auto_apply_threshold: float = 0.90  # matches scoring at/above this are auto-accepted
    prefer_album_releases: bool = True
    prefer_country: str = ""  # e.g. "US", "GB", "" = any
    write_musicbrainz_ids: bool = True
    genre_from_musicbrainz: bool = True
    # artwork
    artwork_sources: list[str] = field(default_factory=lambda: ["coverartarchive", "itunes", "deezer"])
    artwork_min_size: int = 500
    artwork_max_size: int = 1200  # downscale bigger art before embedding (0 = never)
    save_cover_jpg: bool = False  # also write cover.jpg in album folder
    # duplicates
    dupe_fingerprint_threshold: float = 0.80  # 1 - bit error rate
    quarantine_folder: str = ""  # empty = <data_dir>/quarantine
    use_recycle_bin: bool = False
    # organize
    organize_pattern: str = DEFAULT_PATTERN
    organize_destination: str = ""
    organize_copy: bool = False
    various_artists_name: str = "Various Artists"

    @property
    def quarantine_path(self) -> Path:
        return Path(self.quarantine_folder) if self.quarantine_folder else data_dir() / "quarantine"


_lock = threading.Lock()
_settings: Settings | None = None


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> Settings:
    global _settings
    with _lock:
        if _settings is None:
            s = Settings()
            try:
                raw = json.loads(settings_path().read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except (OSError, ValueError):
                pass
            _settings = s
        return _settings


def save_settings(s: Settings | None = None) -> None:
    s = s or load_settings()
    tmp = settings_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    os.replace(tmp, settings_path())
