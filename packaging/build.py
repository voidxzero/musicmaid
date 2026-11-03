"""Build standalone MusicMaid apps with PyInstaller. Run it on the OS you are building for.

    python packaging/build.py               # GUI app for this OS (bundles fpcalc)
    python packaging/build.py --tui         # Linux terminal app
    python packaging/build.py --appimage    # Linux: also make a single-file AppImage
    python packaging/build.py --installer   # Windows: also make Setup.exe (needs Inno Setup's iscc)

Output goes to ./release/:
    Windows: MusicMaid-<ver>-windows-x64.zip  (+ MusicMaid-<ver>-setup.exe)
    Linux:   MusicMaid-<ver>-linux-x86_64.tar.gz  (+ MusicMaid-<ver>-x86_64.AppImage)
"""
from __future__ import annotations

import argparse
import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
VENDOR = ROOT / "vendor"
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
CHROMAPRINT = "1.5.1"
WIN = sys.platform == "win32"
FPCALC = "fpcalc.exe" if WIN else "fpcalc"

sys.path.insert(0, str(ROOT))
from musicmaid import __version__  # noqa: E402

# Other Qt bindings / heavy libraries that may be installed but are never used.
EXCLUDES = ["PyQt5", "PyQt6", "tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest"]


def log(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def download(url: str) -> bytes:
    log(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def ensure_fpcalc() -> Path | None:
    target = VENDOR / FPCALC
    if target.exists():
        return target
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}[platform.system()]
    arch = "x86_64" if platform.machine().lower() in ("amd64", "x86_64") else platform.machine().lower()
    name = f"chromaprint-fpcalc-{CHROMAPRINT}-{system}-{arch}"
    ext = "zip" if WIN else "tar.gz"
    try:
        data = download(f"https://github.com/acoustid/chromaprint/releases/download/v{CHROMAPRINT}/{name}.{ext}")
    except OSError as e:
        print(f"WARNING: could not download fpcalc ({e}); the app will need a system-wide fpcalc.")
        return None
    VENDOR.mkdir(exist_ok=True)
    if WIN:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            target.write_bytes(z.read(next(m for m in z.namelist() if m.endswith(FPCALC))))
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            member = next(m for m in t.getmembers() if m.name.endswith("/" + FPCALC))
            target.write_bytes(t.extractfile(member).read())
        target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return target


def write_version_file() -> Path:
    """Windows file properties (shown in Explorer → Properties → Details)."""
    nums = tuple(int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4])
    path = DIST.parent / "build" / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'MusicMaid'),
    StringStruct('FileDescription', 'MusicMaid music library cleaner'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', 'MusicMaid'),
    StringStruct('ProductVersion', '{__version__}'),
    StringStruct('OriginalFilename', 'MusicMaid.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")
    return path


def pyinstaller(tui: bool, fpcalc: Path | None) -> Path:
    import PyInstaller.__main__

    name = "musicmaid-tui" if tui else "MusicMaid"
    sep = os.pathsep
    opts = [
        "--noconfirm", "--clean", "--name", name,
        "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        "--collect-submodules", "musicmaid",
        "--add-data", f"{ROOT / 'musicmaid' / 'assets'}{sep}musicmaid/assets",
        "--icon", str(PKG / ("icon.ico" if WIN else "icon-512.png")),
    ]
    for mod in EXCLUDES + (["PySide6"] if tui else ["textual"]):
        opts += ["--exclude-module", mod]
    if fpcalc:
        opts += ["--add-binary", f"{fpcalc}{sep}."]
    if WIN:
        opts += ["--version-file", str(write_version_file())]
    if tui:
        opts += ["--console", "--collect-all", "textual", str(PKG / "tui_entry.py")]
    else:
        opts += ["--windowed", str(PKG / "gui_entry.py")]
    log(f"PyInstaller → dist/{name}")
    PyInstaller.__main__.run(opts)
    return DIST / name


# Qt plugins that drag in large unused Qt modules (QML/Quick, PDF, virtual keyboard)
PRUNE_PLUGINS = ["imageformats/*qpdf*", "platforminputcontexts/*virtualkeyboard*"]
PRUNE_LIBS = ["*Qt6Pdf*", "*Qt6Quick*", "*Qt6Qml*", "*Qt6VirtualKeyboard*"]


def prune(app_dir: Path) -> None:
    removed = 0
    for qt in app_dir.rglob("PySide6"):
        for pattern in PRUNE_PLUGINS:
            for f in list((qt / ("plugins" if WIN else "Qt/plugins")).glob(pattern)):
                removed += f.stat().st_size
                f.unlink()
        lib_dir = qt if WIN else qt / "Qt" / "lib"
        for pattern in PRUNE_LIBS:
            for f in list(lib_dir.glob(pattern)):
                removed += f.stat().st_size
                f.unlink()
    log(f"Pruned {removed / 1e6:.0f} MB of unused Qt modules")


def package_windows(app_dir: Path, installer: bool) -> list[Path]:
    RELEASE.mkdir(exist_ok=True)
    out = [Path(shutil.make_archive(str(RELEASE / f"MusicMaid-{__version__}-windows-x64"), "zip",
                                    app_dir.parent, app_dir.name))]
    if installer:
        iscc = shutil.which("iscc") or next((p for p in (
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe")
            if Path(p).exists()), None)
        if not iscc:
            print("WARNING: Inno Setup (iscc) not found - skipping Setup.exe. Get it from https://jrsoftware.org/isdl.php")
        else:
            log("Inno Setup → Setup.exe")
            subprocess.run([iscc, f"/DAppVersion={__version__}", f"/DSourceDir={app_dir}",
                            f"/DOutputDir={RELEASE}", f"/DIconFile={PKG / 'icon.ico'}",
                            str(PKG / "musicmaid.iss")], check=True)
            out.append(RELEASE / f"MusicMaid-{__version__}-setup.exe")
    return out


def package_linux(app_dir: Path, appimage: bool, tui: bool) -> list[Path]:
    RELEASE.mkdir(exist_ok=True)
    arch = platform.machine()
    base = f"{'musicmaid-tui' if tui else 'MusicMaid'}-{__version__}-linux-{arch}"
    # a .desktop file + icon so `install.sh` can add a menu entry
    if not tui:
        shutil.copy(PKG / "icon-512.png", app_dir / "musicmaid.png")
        (app_dir / "install.sh").write_text(INSTALL_SH)
        (app_dir / "install.sh").chmod(0o755)
    out = [Path(shutil.make_archive(str(RELEASE / base), "gztar", app_dir.parent, app_dir.name))]
    if appimage and not tui:
        out.append(make_appimage(app_dir, arch))
    return out


INSTALL_SH = """#!/bin/sh
# Adds MusicMaid to your application menu (no root needed).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/512x512/apps
cp "$HERE/musicmaid.png" ~/.local/share/icons/hicolor/512x512/apps/musicmaid.png
cat > ~/.local/share/applications/musicmaid.desktop <<EOF
[Desktop Entry]
Type=Application
Name=MusicMaid
GenericName=Music Tagger
Comment=Tag, clean up, de-duplicate and organize your music library
Exec="$HERE/MusicMaid" %F
Icon=musicmaid
Terminal=false
Categories=AudioVideo;Audio;Utility;
EOF
update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "MusicMaid added to your application menu."
"""


def make_appimage(app_dir: Path, arch: str) -> Path:
    tool = ROOT / "build" / f"appimagetool-{arch}.AppImage"
    if not tool.exists():
        tool.parent.mkdir(exist_ok=True)
        tool.write_bytes(download(
            f"https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-{arch}.AppImage"))
        tool.chmod(0o755)
    appdir = ROOT / "build" / "MusicMaid.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(app_dir, appdir / "usr" / "lib" / "musicmaid", symlinks=True)
    (appdir / "AppRun").write_text('#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
                                   'exec "$HERE/usr/lib/musicmaid/MusicMaid" "$@"\n')
    (appdir / "AppRun").chmod(0o755)
    shutil.copy(PKG / "icon-512.png", appdir / "musicmaid.png")
    desktop = (PKG / "musicmaid.desktop").read_text().replace("Icon=audio-x-generic", "Icon=musicmaid")
    (appdir / "musicmaid.desktop").write_text(desktop)
    out = RELEASE / f"MusicMaid-{__version__}-{arch}.AppImage"
    log("appimagetool → AppImage")
    env = dict(os.environ, ARCH=arch, APPIMAGE_EXTRACT_AND_RUN="1")  # works without FUSE (e.g. in CI)
    subprocess.run([str(tool), "--no-appstream", str(appdir), str(out)], check=True, env=env)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tui", action="store_true", help="build the terminal UI instead of the GUI")
    ap.add_argument("--appimage", action="store_true", help="Linux: also build an AppImage")
    ap.add_argument("--installer", action="store_true", help="Windows: also build Setup.exe with Inno Setup")
    ap.add_argument("--no-fpcalc", action="store_true", help="don't bundle fpcalc")
    args = ap.parse_args()

    fpcalc = None if args.no_fpcalc else ensure_fpcalc()
    app_dir = pyinstaller(args.tui, fpcalc)
    if not args.tui:
        prune(app_dir)
    files = package_windows(app_dir, args.installer) if WIN else package_linux(app_dir, args.appimage, args.tui)
    log("Done:")
    for f in files:
        print(f"   {f}  ({f.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
