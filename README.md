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
* **Tags from folder names.** Fills in tags from your folder structure, either automatically (common layouts
  like `Artist/Album (Year)/01 - Title`) or with a pattern such as `%artist%/%album% (%year%)/%track% - %title%`,
  with a live preview. You choose whether to overwrite existing tags or only fill empty ones.
* **Split CUE albums.** Albums stored as one big file plus a `.cue` sheet (including CUE sheets embedded in FLAC
  files) are split into separate tagged tracks. Lossless images become FLAC tracks cut at exact sample positions,
  and lossy images are cut without re-encoding. The original goes to quarantine, so Undo can restore it. Needs
  ffmpeg: `install.sh` installs it on Linux, and on Windows MusicMaid offers to download it.
* **Duplicates.** It finds byte-identical files, files with the **same audio** (fingerprint comparison,
  even across formats and bitrates) and files with the same artist, title and length. The best copy is
  kept: lossless first, then bitrate and tag quality. The others are moved to a quarantine folder or the
  recycle bin, and their tags and artwork can be copied onto the kept copy.
* **Organize.** It renames and moves files using a pattern such as
  `{albumartist}/{album} ({year})/{disc_prefix}{tracknumber:02} - {title}`. File names are made safe for
  Windows and Linux, `.lrc`/`.cue` sidecars and folder art move along, empty folders are removed and
  folder-name casing is reused.
* **Skins.** It uses the same skins as [Spindle](https://github.com/voidxzero/spindle): Modern Night (the
  default on Linux), Amp Classic (the default on Windows), Luna Midnight, Olive Noir, Aqua Deck, Ice Blue,
  Chrome Deck, Emerald Core, Classic 98 and Vapor Dusk, plus *System* for your desktop's own look. Choose one
  under **View → Skin** or in **Settings**. Skins are small `.json` files with colours, not code, so they're safe
  to share, and skin files work in both apps.
* **Safe by default.** Automatic results become **proposals** that you review (see *Needs review*) before
  anything is written. **Apply** first shows a preview of every change (old → new), where you can untick whole
  tracks or single fields. Only matches above a confidence threshold (default 90%) are written automatically
  by *Auto-tag*. **Every** tag write, move and duplicate removal is journaled and can be **undone**.

Formats: MP3, FLAC, Ogg Vorbis, Opus, M4A/AAC/ALAC, WMA, WAV, AIFF, WavPack, APE, Musepack, TTA and DSF.
Tags use MusicBrainz Picard's field naming, so other taggers and players read them correctly.

## Install

### Linux

```sh
git clone https://github.com/voidxzero/musicmaid.git
cd musicmaid
./install.sh
```

The installer uses your package manager (apt, dnf, pacman or zypper) to install Chromaprint's `fpcalc`
and whatever Python libraries your distribution provides, sets up a private Python environment in
`~/.local/share/musicmaid`, and adds **MusicMaid** to your application menu. It also adds the commands
`musicmaid` (GUI), `musicmaid-tui` (terminal UI) and `musicmaid-cli`. No root is needed except for the
package step; `./install.sh --no-deps` skips it. Run `./install.sh` again at any time to reinstall, and
your library and settings are kept.

`./uninstall.sh` removes the program but keeps your library database, settings and undo history.

Prefer a single file? The [releases page](https://github.com/voidxzero/musicmaid/releases/latest) also
has an AppImage and a self-contained tarball.

### Windows

```powershell
py -m pip install "C:\path\to\musicmaid[gui]"
musicmaid
```

On first start MusicMaid offers to download Chromaprint's `fpcalc.exe` (about 3 MB) from the official
GitHub release. The download is checked against a pinned SHA-256 checksum and stored in the MusicMaid data
folder. You can also do it later with **Help → Download fpcalc** or `musicmaid-cli fpcalc`, or point
**Settings** at your own copy. The standalone apps below already include it.

### With or without AcoustID

MusicMaid works without any account or key. AcoustID is an optional extra that lets it recognise songs by
their **sound**. It's free for open-source apps like this one, but each user needs their own free key, so
MusicMaid asks on first start (you can skip it).

| | Without a key | With a free AcoustID key |
|---|---|---|
| Clean-up, artwork, duplicates, organize, undo | ✔ | ✔ |
| Files with decent tags (artist + title or album) | ✔ identified via MusicBrainz search | ✔ |
| Files with a MusicBrainz ID in their tags | ✔ | ✔ |
| Untagged files, wrong tags, names like `Track 01.mp3` | only if the file/folder name helps; otherwise **Needs review** | ✔ recognised by their audio |

**Getting a key (about a minute):** go to <https://acoustid.org/new-application>, sign in, enter any
application name (e.g. "MusicMaid"), and copy the **API key**. Paste it in the first-start prompt,
**Help → Identify by Sound**, **Settings**, or run `musicmaid-cli config acoustid_api_key YOURKEY`. The key
is checked with AcoustID before it's saved. Identifying by sound also needs `fpcalc`, which the standalone
apps include and MusicMaid offers to download otherwise.

Only each file's audio fingerprint and length are sent to AcoustID, never the audio itself.

## Typical workflow

1. **Add folder** → **Scan**. Your music appears as a folder tree on the left: pick a folder to see its
   tracks in album order, or *All folders* for everything. The views above the tree (*Needs review*,
   *Untagged*, …) narrow both the tree and the track list.
2. **Duplicates** → review the groups → *Remove checked copies*.
3. Select everything → **Auto-tag**. This runs clean-up, identification and artwork; confident results
   are written, and everything else lands in **Needs review**.
4. When changes are waiting, a bar above the track list says so. Click **Preview & Apply All**, untick
   anything you don't want, and write the rest; or open **Needs review** to go through them track by track.
   Fix leftovers by hand in the tag editor, or try **Tags from Folder Names** (in the Auto-Tag ▾ menu).
   Under the track list, the **Files** panel shows everything that's really in the chosen folder (covers,
   `.cue`, `.log`, …). Clicking an audio file selects its track, and double-clicking opens a file. Toggle the
   panel with **View → Show Files Panel** (F6).
5. **Split CUE** turns one-file albums into tracks; **Organize** renames and moves files into a clean folder
   structure. Right-click a track or folder to copy its name or path.
6. Changed your mind? Use **Undo**.

### Terminal UI keys

The left side shows the views (All tracks, Needs review, …) above a **folder tree** of your library; pick a
folder with `enter` to see its tracks (including subfolders) in album order.
`space` mark · `ctrl+a` mark all · `/` search · `t` auto-tag · `i` identify · `c` clean up ·
`w` find artwork · `W` pick artwork · `e` edit tags · `a` apply · `x` discard · `d` duplicates ·
`p` tags from folder names · `k` split CUE sheets · `y` / `Y` copy file / folder path ·
`o` organize · `u` undo · `f` library folders · `,` settings · `l` log · `ctrl+x` cancel task · `?` keys · `q` quit.
Actions work on marked tracks; with nothing marked, they offer to work on the current view.

### CLI examples

```bash
musicmaid-cli add ~/Music && musicmaid-cli scan
musicmaid-cli dupes                     # list duplicates;  --remove to quarantine extra copies
musicmaid-cli autotag --view untagged   # identify + write confident matches
musicmaid-cli review                    # show pending proposals
musicmaid-cli apply --min-score 0.8
musicmaid-cli pathtags --pattern '%artist%/%album%/%track% - %title%'   # tags from folders
musicmaid-cli cue                       # list CUE sheets;  --go to split them
musicmaid-cli organize                  # dry run;  --go to move files
musicmaid-cli history && musicmaid-cli undo
musicmaid-cli update                    # install a newer release  (--check: only check)
musicmaid-cli fpcalc                    # download fpcalc if it's missing  (--check: just show where it is)
```

## Standalone apps (no Python needed)

| Platform | Build on | Command | Output in `release/` |
|----------|----------|---------|----------------------|
| Windows | a Windows PC | double-click **`build-windows.bat`** | `MusicMaid-<ver>-windows-x64.zip`, plus `MusicMaid-<ver>-setup.exe` if [Inno Setup](https://jrsoftware.org/isdl.php) is installed |
| Linux | Linux | `./build-linux.sh` (add `--appimage` for a single-file AppImage) | `MusicMaid-<ver>-linux-x86_64.tar.gz` (+ `.AppImage`) |

Both bundle Python, Qt and Chromaprint's `fpcalc`, and finish with a self-test of the built app
(`MusicMaid --self-test`). On Linux, unpack the tarball and run `./MusicMaid`; run `./install.sh` once to
add it to your application menu.

**Without a Windows PC:** push the project to GitHub and use GitHub Actions:

| Workflow | Runs when | What it does |
|----------|-----------|--------------|
| `Tests` | every push to `main` and every pull request | runs the test suite |
| `Build Windows` | manual run, or a `v*` tag | tests, then builds the zip and installer and self-tests the `.exe` |
| `Build Linux` | manual run, or a `v*` tag | tests, then builds the tarball and AppImage and self-tests the binary |

Start a build from the *Actions* tab (pick the workflow, then *Run workflow*) and download the result
under *Artifacts*. Pushing a tag such as `v0.2.0` runs both builds and attaches all files to that GitHub
release.

Issues use the labels `windows`, `linux`, `gui`, `tui` and `packaging`, defined in `.github/labels.json`.

## Updates

MusicMaid checks [GitHub releases](https://github.com/voidxzero/musicmaid/releases) at startup; turn this off in
**Settings**, or use **Help → Check for Updates** (`musicmaid-cli update` from a terminal). When a new version
is available you can install it from the app, or skip that version:

| Installed from | How the update is installed |
|----------------|-----------------------------|
| Windows `setup.exe` | the new installer runs silently, then MusicMaid restarts |
| Windows portable zip | the new files are copied over the folder after MusicMaid closes, then it restarts |
| AppImage | the AppImage file is replaced and MusicMaid restarts |
| Linux tarball | the app folder is swapped for the new one and MusicMaid restarts |
| Linux `./install.sh` | the new release's `install.sh --no-deps` runs (your data is kept) and MusicMaid restarts |
| pip / git (source) | you're notified; update with `pip install -U` or `git pull` |

The built apps are checked against the SHA-256 checksum GitHub publishes for each release file before anything
is installed. An `./install.sh` install downloads the release's source from GitHub over HTTPS, since GitHub
publishes no checksum for source archives. Your library, settings and undo history live in the data folder
and aren't touched.

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
