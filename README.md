# MusicMaid

Tag, clean up, de-duplicate and organize a music library, mostly on autopilot.
It comes with three front-ends that share one engine:

| Front-end | Platforms | Start with |
|-----------|-----------|------------|
| Desktop GUI (Qt) | Linux, Windows | `musicmaid` |
| Terminal UI (Textual) | Linux (any terminal, works over SSH) | `musicmaid-tui` |
| CLI (scriptable) | Linux, Windows | `musicmaid-cli --help` |

## What it does

* **Identifies songs online.** It fingerprints each file's audio (Chromaprint → AcoustID), so it can recognise
  files with **wrong or missing tags**. It then pulls complete metadata from **MusicBrainz**: title, artists,
  album, album artist, track/disc numbers and totals, dates, genre, label, catalog #, ISRC and MusicBrainz IDs.
  Files without a fingerprint match fall back to an album lookup and then a per-track search, using the
  existing tags or the file/folder name.
* **Keeps whole albums together.** Tracks in a folder vote on the release, so an album isn't split across
  random compilations. Official studio releases are preferred over live versions, bootlegs, compilations
  and later reissues, and you can set a preferred release country.
* **Artwork.** Cover art comes from the **Cover Art Archive** (by MusicBrainz release), **iTunes/Apple Music**
  and **Deezer**. If another file in the same album already has good art, it is reused. The GUI has a
  thumbnail picker and drag-and-drop; large images are downscaled before embedding, and saving
  `cover.jpg` is optional.
* **Offline clean-up.** It fixes ALL CAPS and lowercase text, strips junk like URLs or "(www.site.com)",
  and splits "Artist - Title" crammed into the title field. It fills missing tags from file and folder
  names, normalises track numbers and makes album fields consistent within a folder.
* **Duplicates.** It finds byte-identical files, files with the **same audio** (fingerprint comparison,
  even across formats and bitrates) and files with the same artist, title and length. The best copy is
  kept: lossless first, then bitrate and tag quality. The others are moved to a quarantine folder or the
  recycle bin, and their tags and artwork can be copied onto the kept copy.
* **Organize.** It renames and moves files using a pattern such as
  `{albumartist}/{album} ({year})/{disc_prefix}{tracknumber:02} - {title}`. File names are made safe for
  Windows and Linux, `.lrc`/`.cue` sidecars and folder art move along, empty folders are removed and
  folder-name casing is reused.
* **Safe by default.** Automatic results become **proposals** that you review (see *Needs review*) before
  anything is written. Only matches above a confidence threshold (default 90%) are written automatically
  by *Auto-tag*. **Every** tag write, move and duplicate removal is journaled and can be **undone**.

Formats: MP3, FLAC, Ogg Vorbis, Opus, M4A/AAC/ALAC, WMA, WAV, AIFF, WavPack, APE, Musepack, TTA and DSF.
Tags use MusicBrainz Picard's field naming, so other taggers and players read them correctly.

## Install

### Linux

```bash
sudo dnf install chromaprint-tools      # Fedora   (Debian/Ubuntu: sudo apt install libchromaprint-tools)
python3 -m venv ~/.local/share/musicmaid-venv
~/.local/share/musicmaid-venv/bin/pip install "/path/to/musicmaid[all]"
~/.local/share/musicmaid-venv/bin/musicmaid-tui      # or: musicmaid (GUI)
```

Optional menu entry: copy `packaging/musicmaid.desktop` to `~/.local/share/applications/`.

### Windows

```powershell
py -m pip install "C:\path\to\musicmaid[gui]"
musicmaid
```

Download `fpcalc.exe` from <https://acoustid.org/chromaprint> and either put it on your `PATH` or set its
location in **Settings**. Alternatively, build a self-contained app that bundles it (see below).

### AcoustID key (recommended)

Fingerprint identification needs a free AcoustID application key:
<https://acoustid.org/new-application>. Enter it in **Settings** (GUI/TUI) or run
`musicmaid-cli config acoustid_api_key YOURKEY`. Without a key, MusicMaid still identifies files from
their tags and file names, but untagged and wrongly tagged files will mostly go to manual review.

## Typical workflow

1. **Add folder** → **Scan**.
2. **Duplicates** → review the groups → *Remove checked copies*.
3. Select everything → **Auto-tag**. This runs clean-up, identification and artwork; confident results
   are written, and everything else lands in **Needs review**.
4. Open **Needs review**, check the proposed changes (shown in green), and **Apply** or **Discard** them.
   Fix leftovers by hand in the tag editor.
5. **Organize** to rename and move files into a clean folder structure.
6. Changed your mind? Use **Undo**.

### Terminal UI keys

`space` mark · `ctrl+a` mark all · `/` search · `t` auto-tag · `i` identify · `c` clean up ·
`w` find artwork · `W` pick artwork · `e` edit tags · `a` apply · `x` discard · `d` duplicates ·
`o` organize · `u` undo · `f` folders · `,` settings · `l` log · `ctrl+x` cancel task · `q` quit.
Actions work on marked tracks; with nothing marked, they offer to work on the current view.

### CLI examples

```bash
musicmaid-cli add ~/Music && musicmaid-cli scan
musicmaid-cli dupes                     # list duplicates;  --remove to quarantine extra copies
musicmaid-cli autotag --view untagged   # identify + write confident matches
musicmaid-cli review                    # show pending proposals
musicmaid-cli apply --min-score 0.8
musicmaid-cli organize                  # dry run;  --go to move files
musicmaid-cli history && musicmaid-cli undo
```

## Standalone apps (no Python needed)

| Platform | Build on | Command | Output in `release/` |
|----------|----------|---------|----------------------|
| Windows | a Windows PC | double-click **`build-windows.bat`** | `MusicMaid-<ver>-windows-x64.zip`, plus `MusicMaid-<ver>-setup.exe` if [Inno Setup](https://jrsoftware.org/isdl.php) is installed |
| Linux | Linux | `./build-linux.sh` (add `--appimage` for a single-file AppImage) | `MusicMaid-<ver>-linux-x86_64.tar.gz` (+ `.AppImage`) |

Both bundle Python, Qt and Chromaprint's `fpcalc`, and finish with a self-test of the built app
(`MusicMaid --self-test`). On Linux, unpack the tarball and run `./MusicMaid`; run `./install.sh` once to
add it to your application menu.

**Without a Windows PC:** push the project to GitHub. `.github/workflows/build.yml` runs the tests and
builds the Windows zip and installer, plus the Linux tarball and AppImage. Start it manually from the
*Actions* tab, or push a tag such as `v0.1.0` to publish everything as a GitHub release.

## Data locations

Settings, the library database, the undo journal and quarantined duplicates are stored in
`~/.local/share/musicmaid/` on Linux and `%APPDATA%\MusicMaid\` on Windows. Set `MUSICMAID_HOME` to use
another location. MusicBrainz asks clients to identify themselves; set `MUSICMAID_CONTACT` (for example to
an email address) to add contact information to the User-Agent.

## Development

```bash
python -m venv --system-site-packages .venv && .venv/bin/pip install -e ".[all,dev]"
.venv/bin/pytest            # needs ffmpeg + fpcalc for the audio-based tests
```

Layout: `musicmaid/` holds the engine (`tags`, `scanner`, `fingerprint`, `identify`, `cleanup`,
`duplicates`, `organizer`, `library`, `providers/`), plus `gui/` (PySide6), `tui/` (Textual) and `cli.py`.
