"""Check GitHub releases for a newer MusicMaid and install it in place.

How an update is installed depends on how MusicMaid was installed:

* ``windows-installer``  Setup.exe install: run the new installer silently, and it relaunches the app.
* ``windows-portable``   unzipped folder: a helper script waits for the app to exit, copies the new files
                         over, then relaunches.
* ``appimage``           replace the AppImage file and relaunch.
* ``linux-tarball``      swap the app folder for the new one and relaunch.
* ``linux-install``      installed with ./install.sh: run the new release's install.sh --no-deps and relaunch.
* ``source``             pip/git install: only notify, because pip or git manages the files.

Every built download is checked against the SHA-256 digest GitHub publishes for the release file. The
install.sh route downloads the release's source archive from GitHub over HTTPS (GitHub publishes no
checksum for those).
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .progress import NULL_TASK, Task

REPO = "voidxzero/musicmaid"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"


class UpdateError(Exception):
    pass


@dataclass
class Update:
    version: str
    notes: str
    page: str
    kind: str
    asset_name: str = ""
    asset_url: str = ""
    sha256: str = ""
    size: int = 0

    @property
    def can_install(self) -> bool:
        if self.kind == "linux-install":
            return bool(self.asset_url)
        return bool(self.asset_url and self.sha256) and self.kind != "source"


def parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(remote: str, local: str = __version__) -> bool:
    r, l = parse_version(remote), parse_version(local)
    width = max(len(r), len(l))
    return bool(r) and r + (0,) * (width - len(r)) > l + (0,) * (width - len(l))


# ---------------------------------------------------------------- install detection
def app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def install_prefix() -> Path:
    """Where ./install.sh puts MusicMaid (lib/, venv/ next to the user's data)."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "musicmaid"


def launcher_dir() -> Path:
    return Path.home() / ".local" / "bin"


def install_kind() -> str:
    if not getattr(sys, "frozen", False):
        try:
            here = Path(__file__).resolve().parent.parent
            if sys.platform.startswith("linux") and here == (install_prefix() / "lib").resolve():
                return "linux-install"
        except OSError:
            pass
        return "source"
    if sys.platform == "win32":
        return "windows-installer" if any(app_dir().glob("unins*.exe")) else "windows-portable"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if sys.platform.startswith("linux"):
        return "linux-tarball"
    return "unsupported"


def _arch() -> str:
    m = platform.machine().lower()
    return "x86_64" if m in ("amd64", "x86_64", "x64") else m


def asset_pattern(kind: str) -> re.Pattern | None:
    arch = re.escape(_arch())
    prefix = "musicmaid-tui" if Path(sys.executable).stem.lower().startswith("musicmaid-tui") else "MusicMaid"
    return {
        "windows-installer": re.compile(r"^MusicMaid-[\d.]+-setup\.exe$"),
        "windows-portable": re.compile(r"^MusicMaid-[\d.]+-windows-x64\.zip$"),
        "appimage": re.compile(rf"^MusicMaid-[\d.]+-{arch}\.AppImage$"),
        "linux-tarball": re.compile(rf"^{re.escape(prefix)}-[\d.]+-linux-{arch}\.tar\.gz$"),
    }.get(kind)


# ---------------------------------------------------------------- check
def check(timeout: float = 10, kind: str | None = None) -> Update | None:
    """Return the latest release if it is newer than this version, else None."""
    from . import net

    try:
        r = net.session().get(LATEST_API, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    except Exception as e:
        raise UpdateError(f"Couldn't reach GitHub: {e}") from e
    if r.status_code == 404:
        return None  # no releases yet
    if r.status_code != 200:
        raise UpdateError(f"GitHub answered {r.status_code} when checking for updates")
    rel = r.json()
    version = rel.get("tag_name", "").lstrip("v")
    if rel.get("draft") or rel.get("prerelease") or not is_newer(version):
        return None
    kind = kind or install_kind()
    upd = Update(version=version, notes=(rel.get("body") or "").strip(), page=rel.get("html_url") or RELEASES_PAGE,
                 kind=kind)
    if kind == "linux-install":
        tag = rel.get("tag_name", "")
        upd.asset_name = f"musicmaid-{version}-source.tar.gz"
        upd.asset_url = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/{tag}" if tag else ""
        return upd
    pat = asset_pattern(kind)
    for a in rel.get("assets", []):
        if pat and pat.match(a.get("name", "")):
            digest = a.get("digest") or ""
            upd.asset_name, upd.asset_url, upd.size = a["name"], a["browser_download_url"], int(a.get("size") or 0)
            upd.sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""
            break
    return upd


# ---------------------------------------------------------------- download + install
def download(upd: Update, dest_dir: Path, task: Task = NULL_TASK) -> Path:
    from . import net

    if not upd.sha256 and upd.kind != "linux-install":
        raise UpdateError("This release has no checksum, so it can't be installed automatically.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / upd.asset_name
    h = hashlib.sha256()
    done = 0
    try:
        with net.session().get(upd.asset_url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                raise UpdateError(f"Download failed (HTTP {r.status_code})")
            total = int(r.headers.get("Content-Length") or upd.size or 0)
            with open(target, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    task.check()
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    task.progress(done // 1024, total // 1024, f"Downloading MusicMaid {upd.version}… "
                                                              f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    except Exception as e:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {e}") from e
    if upd.sha256 and h.hexdigest() != upd.sha256:
        target.unlink(missing_ok=True)
        raise UpdateError("The download failed its checksum check, so nothing was installed.")
    return target


def clean_env() -> dict[str, str]:
    """Environment for starting a fresh copy of the app, without this bundle's loader variables."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("_PYI_") or k in ("_MEIPASS2", "APPDIR", "APPIMAGE", "ARGV0", "OWD"):
            env.pop(k)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _spawn(cmd: list[str]) -> None:
    if sys.platform == "win32":
        flags = 0x00000200 | 0x08000000  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        try:
            subprocess.Popen(cmd, env=clean_env(), close_fds=True, creationflags=flags | 0x01000000)  # +BREAKAWAY
        except OSError:
            subprocess.Popen(cmd, env=clean_env(), close_fds=True, creationflags=flags)
    else:
        subprocess.Popen(cmd, env=clean_env(), close_fds=True, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _single_top_dir(root: Path) -> Path:
    entries = [p for p in root.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    raise UpdateError("The update archive doesn't have the expected layout.")


def install(upd: Update, task: Task = NULL_TASK, relaunch: bool = True) -> str:
    """Download, verify and install ``upd``.

    On Windows the files are replaced after this process exits, so the caller must quit right away.
    On Linux the files are replaced now. Returns a short message for the user.
    """
    if not upd.can_install:
        raise UpdateError("This copy of MusicMaid can't update itself. Download the new version from "
                          f"{upd.page}")
    kind = upd.kind
    if kind == "windows-installer":
        work = Path(tempfile.mkdtemp(prefix="musicmaid-update-"))
        setup = download(upd, work, task)
        args = [str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL", "/NORESTART", "/CLOSEAPPLICATIONS"]
        _spawn(args + (["/RELAUNCH"] if relaunch else []))
        return f"Installing MusicMaid {upd.version}…"

    if kind == "windows-portable":
        work = Path(tempfile.mkdtemp(prefix="musicmaid-update-"))
        archive = download(upd, work, task)
        task.progress(0, 0, "Unpacking update…")
        with zipfile.ZipFile(archive) as z:
            z.extractall(work / "new")
        archive.unlink()
        src = _single_top_dir(work / "new")
        script = work / "finish-update.bat"
        script.write_text(windows_script(os.getpid(), src, app_dir(), Path(sys.executable).name, work, relaunch),
                          encoding="ascii", errors="replace", newline="\r\n")
        _spawn(["cmd.exe", "/c", str(script)])
        return f"MusicMaid {upd.version} will be installed when MusicMaid closes."

    if kind == "appimage":
        target = Path(os.environ["APPIMAGE"])
        if not os.access(target.parent, os.W_OK):
            raise UpdateError(f"Can't write to {target.parent}; download the new AppImage from {upd.page}")
        work = Path(tempfile.mkdtemp(prefix=".musicmaid-update-", dir=target.parent))
        try:
            new = download(upd, work, task)
            new.chmod(0o755)
            os.replace(new, target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if relaunch:
            _spawn([str(target)])
        return f"Updated to MusicMaid {upd.version}."

    if kind == "linux-tarball":
        current = app_dir()
        parent = current.parent
        if not os.access(parent, os.W_OK):
            raise UpdateError(f"Can't write to {parent}; download the new version from {upd.page}")
        work = Path(tempfile.mkdtemp(prefix=f".{current.name}-update-", dir=parent))
        try:
            archive = download(upd, work, task)
            task.progress(0, 0, "Unpacking update…")
            with tarfile.open(archive) as t:
                t.extractall(work / "new", filter="data")
            archive.unlink()
            new = _single_top_dir(work / "new")
            if not (new / Path(sys.executable).name).is_file():
                raise UpdateError("The update archive doesn't contain the MusicMaid program.")
            old = parent / f".{current.name}.old"
            shutil.rmtree(old, ignore_errors=True)
            os.rename(current, old)  # the running program keeps working from the renamed folder
            try:
                os.rename(new, current)
            except OSError:
                os.rename(old, current)
                raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if relaunch:
            _spawn([str(current / Path(sys.executable).name)])
        return f"Updated to MusicMaid {upd.version}."

    if kind == "linux-install":
        work = Path(tempfile.mkdtemp(prefix="musicmaid-update-"))
        try:
            archive = download(upd, work, task)
            task.progress(0, 0, "Unpacking update…")
            with tarfile.open(archive) as t:
                t.extractall(work / "src", filter="data")
            top = _single_top_dir(work / "src")
            if not (top / "install.sh").is_file() or not (top / "musicmaid" / "__init__.py").is_file():
                raise UpdateError("The download doesn't contain MusicMaid's install.sh.")
            task.progress(0, 0, f"Installing MusicMaid {upd.version}…")
            proc = subprocess.run(["bash", str(top / "install.sh"), "--no-deps"], cwd=top, env=clean_env(),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=900)
            for line in proc.stdout.splitlines():
                line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
                if line:
                    task.log(line)
            if proc.returncode != 0:
                raise UpdateError(f"The installer stopped with an error (exit {proc.returncode}); see the log.")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if relaunch:
            _spawn([str(launcher_dir() / "musicmaid")])
        return f"Updated to MusicMaid {upd.version}."

    raise UpdateError(f"Automatic updates aren't supported for this install ({kind}).")


def windows_script(pid: int, src: Path, dst: Path, exe: str, work: Path, relaunch: bool) -> str:
    lines = [
        "@echo off",
        ":wait",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find " {pid} " >nul',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto wait",
        ")",
        f'robocopy "{src}" "{dst}" /E /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul',
        "if errorlevel 8 (",
        "  echo MusicMaid could not be updated. The new version is in:",
        f"  echo {src}",
        "  pause",
        "  exit /b 1",
        ")",
    ]
    if relaunch:
        lines.append(f'start "" "{dst / exe}"')
    lines.append(f'(goto) 2>nul & rmdir /s /q "{work}"')
    return "\n".join(lines) + "\n"


def cleanup_previous() -> None:
    """Remove the folder left behind by a Linux tarball update."""
    if install_kind() == "linux-tarball":
        shutil.rmtree(app_dir().parent / f".{app_dir().name}.old", ignore_errors=True)
