"""Command line interface: ``musicmaid-cli <command>`` (also used for scripting/automation)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .config import load_settings, save_settings
from .library import VIEWS, Library
from .progress import Task


def _task(quiet: bool = False) -> Task:
    last = {"msg": ""}

    def prog(cur: int, total: int, msg: str) -> None:
        if quiet:
            return
        line = f"[{cur}/{total}] {msg}" if total else msg
        sys.stderr.write("\r" + line[:110].ljust(110))
        sys.stderr.flush()
        last["msg"] = line

    def log(msg: str) -> None:
        sys.stderr.write("\r" + " " * 110 + "\r" + msg + "\n")

    return Task(prog, log)


def _done() -> None:
    sys.stderr.write("\r" + " " * 110 + "\r")


def _ids(lib: Library, args) -> list[int]:
    return [t.id for t in lib.view(args.view, args.search or "")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="musicmaid-cli", description="MusicMaid music library cleaner")
    ap.add_argument("-q", "--quiet", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_sel(p):
        p.add_argument("--view", choices=list(VIEWS), default="all", help="which tracks to act on")
        p.add_argument("--search", help="only tracks matching these words")
        return p

    p = sub.add_parser("add", help="add a library folder")
    p.add_argument("folders", nargs="+")
    sub.add_parser("folders", help="list library folders")
    p = sub.add_parser("scan", help="scan library folders for changes")
    p.add_argument("--force", action="store_true", help="re-read every file")
    sub.add_parser("stats", help="library statistics")
    with_sel(sub.add_parser("list", help="list tracks"))
    with_sel(sub.add_parser("identify", help="look tracks up on MusicBrainz/AcoustID (creates proposals)"))
    with_sel(sub.add_parser("cleanup", help="propose offline tag fixes"))
    p = with_sel(sub.add_parser("artwork", help="find missing cover art (creates proposals)"))
    p.add_argument("--replace", action="store_true", help="also replace existing artwork")
    p = with_sel(sub.add_parser("autotag", help="cleanup + identify + artwork, write confident results"))
    p.add_argument("--no-apply", action="store_true", help="only create proposals")
    with_sel(sub.add_parser("review", help="show pending proposals"))
    p = with_sel(sub.add_parser("apply", help="write pending proposals to files"))
    p.add_argument("--min-score", type=float, default=0.0)
    with_sel(sub.add_parser("discard", help="drop pending proposals"))
    p = sub.add_parser("dupes", help="find duplicates")
    p.add_argument("--no-fingerprint", action="store_true")
    p.add_argument("--same-album", action="store_true")
    p.add_argument("--remove", action="store_true", help="quarantine all but the best copy")
    p = with_sel(sub.add_parser("pathtags", help="propose tags from folder/file names"))
    p.add_argument("--pattern", help="e.g. '%%artist%%/%%album%% (%%year%%)/%%track%% - %%title%%' (default: automatic)")
    p.add_argument("--overwrite", action="store_true", help="also replace tags that already have a value")
    p = sub.add_parser("cue", help="split CUE sheet albums into separate tracks")
    p.add_argument("--folder", help="only look in this folder (default: the whole library)")
    p.add_argument("--dest", help="put the tracks here (default: next to each CUE sheet)")
    p.add_argument("--keep-original", action="store_true", help="don't quarantine the big file and .cue")
    p.add_argument("--go", action="store_true", help="actually split (default: just list what was found)")
    p = with_sel(sub.add_parser("organize", help="rename/move files from tags"))
    p.add_argument("--pattern")
    p.add_argument("--dest")
    p.add_argument("--copy", action="store_true")
    p.add_argument("--go", action="store_true", help="actually move files (default is a dry run)")
    p = sub.add_parser("fpcalc", help="show fpcalc (Chromaprint) status, or download it")
    p.add_argument("--check", action="store_true", help="only report where fpcalc is; don't download")
    p = sub.add_parser("update", help="check for a new MusicMaid release and install it")
    p.add_argument("--check", action="store_true", help="only check; don't install")
    sub.add_parser("history", help="list undoable operations")
    sub.add_parser("snapshots", help="list the change snapshots saved in the library folders")
    p = sub.add_parser("revert", help="revert a snapshot (or everything since it) from the library's MusicMaid folder")
    p.add_argument("snapshot", help="number from 'snapshots' (1 = newest), or a snapshot id")
    p.add_argument("--since", action="store_true", help="also revert every newer snapshot")
    p = sub.add_parser("undo", help="undo an operation (default: the latest)")
    p.add_argument("batch", nargs="?")
    p = sub.add_parser("config", help="show or change settings")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")

    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # tags can contain any character; legacy consoles can't
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    lib = Library()
    task = _task(args.quiet)

    if args.cmd == "add":
        for f in args.folders:
            lib.add_folder(f)
        print("Library folders:", *lib.folders, sep="\n  ")
    elif args.cmd == "folders":
        print(*lib.folders, sep="\n")
    elif args.cmd == "scan":
        if not lib.folders:
            print("No library folders. Use: musicmaid-cli add <folder>")
            return 1
        stats = lib.scan(task, force=args.force)
        _done()
        print(", ".join(f"{k}: {v}" for k, v in stats.items()))
    elif args.cmd == "stats":
        for k, v in lib.counts().items():
            print(f"{VIEWS[k]:>16}: {v}")
    elif args.cmd == "list":
        for t in lib.view(args.view, args.search or ""):
            print(f"{t.id:>6}  {t.get('artist')[:25]:25}  {t.get('title')[:35]:35}  {t.get('album')[:25]:25}  {t.path}")
    elif args.cmd == "identify":
        r = lib.identify(_ids(lib, args), task)
        _done()
        print(r)
    elif args.cmd == "cleanup":
        n = lib.cleanup(_ids(lib, args), task)
        _done()
        print(f"{n} tracks have proposed fixes. Review with: musicmaid-cli review")
    elif args.cmd == "artwork":
        n = lib.fetch_artwork(_ids(lib, args), task, only_missing=not args.replace)
        _done()
        print(f"Artwork proposed for {n} tracks")
    elif args.cmd == "autotag":
        r = lib.auto_tag(_ids(lib, args), task, apply_confident=not args.no_apply)
        _done()
        print(r)
    elif args.cmd == "review":
        sel = set(_ids(lib, args))
        for t in lib.tracks(sorted(lib.db.proposal_ids() & sel)):
            p = lib.db.proposal(t.id)
            print(f"\n#{t.id} {t.path}\n   source: {p.source}  score: {p.score:.2f}  {p.note}")
            for k, v in p.tags.items():
                print(f"   {k:>24}: {t.get(k)!r} -> {v!r}")
            if p.art:
                print(f"   {'artwork':>24}: {'replace' if t.has_art else 'add'} ({p.art_source})")
    elif args.cmd == "apply":
        sel = set(_ids(lib, args))
        summary = lib.db.proposal_summary()
        ids = [i for i in sel if i in summary and summary[i][1] >= args.min_score]
        r = lib.apply(ids, task)
        _done()
        print(f"Wrote {r.written} files ({r.failed} failed). Undo with: musicmaid-cli undo {r.batch}")
    elif args.cmd == "discard":
        lib.discard(_ids(lib, args))
    elif args.cmd == "dupes":
        groups = lib.find_duplicates(task, use_fingerprints=not args.no_fingerprint, same_album_only=args.same_album)
        _done()
        for g in groups:
            print(f"\n{g.title}  [{', '.join(sorted(g.reasons))}; similarity {g.similarity:.2f}]")
            for i, t in enumerate(g.tracks):
                q = "lossless" if t.lossless else f"{t.bitrate}k"
                print(f"   {'KEEP ' if i == 0 else 'extra'} {t.codec:>7} {q:>8}  {t.path}")
        print(f"\n{len(groups)} duplicate groups, {sum(len(g.extras) for g in groups)} extra copies")
        if args.remove and groups:
            remove = {t.id: g.keep.id for g in groups for t in g.extras}
            n, batch = lib.remove_duplicates(list(remove), remove, task)
            _done()
            print(f"Moved {n} files to {lib.settings.quarantine_path / batch}. Undo with: musicmaid-cli undo {batch}")
    elif args.cmd == "pathtags":
        n = lib.tags_from_paths(_ids(lib, args), task, pattern=args.pattern, overwrite=args.overwrite)
        _done()
        print(f"{n} tracks have proposed changes. Review with: musicmaid-cli review")
    elif args.cmd == "cue":
        from . import cuesplit
        sheets = lib.cue_sheets(args.folder)
        ready = []
        for sh in sheets:
            status = sh.problems[0] if sh.problems else ("ready" if sh.splittable else "already one file per track")
            if status == "ready" and cuesplit.already_split(cuesplit.plan(sh, args.dest)):
                status = "already split"
            print(f"{status:>28}  {sh.path}{'  (embedded)' if sh.embedded else ''}")
            if status == "ready":
                ready.append(sh)
        print(f"\n{len(sheets)} CUE sheets, {len(ready)} ready to split.")
        if ready and not args.go:
            print("Add --go to split them.")
        if ready and args.go:
            if not cuesplit.find_ffmpeg():
                print("ffmpeg is needed. " + cuesplit.ffmpeg_help())
                return 1
            made, failed, batch = lib.split_cues(ready, task, dest=args.dest, remove_original=not args.keep_original)
            _done()
            print(f"Created {made} tracks ({failed} sheets failed). Undo with: musicmaid-cli undo {batch}")
    elif args.cmd == "organize":
        moves = [m for m in lib.organize_plan(_ids(lib, args), args.pattern, args.dest) if m.changed]
        for m in moves:
            print(f"{m.src}\n  -> {m.dst}")
        if args.go:
            n, batch = lib.organize(moves, copy=args.copy, task=task)
            _done()
            print(f"Moved {n} files. Undo with: musicmaid-cli undo {batch}")
        else:
            print(f"\n{len(moves)} files would move. Add --go to do it.")
    elif args.cmd == "fpcalc":
        from .fingerprint import FingerprintError, download_fpcalc, find_fpcalc
        current = find_fpcalc()
        if current or args.check:
            print(current or "fpcalc not found")
            return 0 if current else 1
        try:
            path = download_fpcalc(task)
        except FingerprintError as e:
            _done()
            print(e)
            return 1
        _done()
        print(f"fpcalc installed: {path}")
    elif args.cmd == "update":
        from . import __version__, updater
        try:
            upd = updater.check()
        except updater.UpdateError as e:
            print(e)
            return 1
        if not upd:
            print(f"MusicMaid {__version__} is the latest version.")
            return 0
        print(f"MusicMaid {upd.version} is available (you have {__version__}): {upd.page}")
        if args.check:
            return 0
        if not upd.can_install:
            print("This copy runs from Python. Update it with pip (pip install -U <path or git URL>) or git pull.")
            return 0
        try:
            msg = updater.install(upd, task, relaunch=False)
        except updater.UpdateError as e:
            _done()
            print(e)
            return 1
        _done()
        print(msg)
    elif args.cmd == "snapshots":
        import time
        for i, s in enumerate(lib.snapshots(), 1):
            state = "reverted" if s.reverted else ""
            print(f"{i:>3}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(s.created))}  {s.label:<28} "
                  f"{s.changes:>5} changes  {state:<9} {s.text_path}")
    elif args.cmd == "revert":
        snaps = lib.snapshots()
        pick = (snaps[int(args.snapshot) - 1] if args.snapshot.isdigit() and 0 < int(args.snapshot) <= len(snaps)
                else next((s for s in snaps if s.batch == args.snapshot), None))
        if not pick:
            print("No such snapshot; see: musicmaid-cli snapshots")
            return 1
        todo = [s for s in snaps if s.created >= pick.created] if args.since else [pick]
        n, problems = lib.revert_snapshots(todo, task)
        _done()
        for p in problems:
            print("  " + p)
        print(f"Reverted {n} changes")
    elif args.cmd == "history":
        import time
        for batch, label, ts, n in lib.history():
            print(f"{batch}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}  {label} ({n} operations)")
    elif args.cmd == "undo":
        batch = args.batch or (lib.history()[0][0] if lib.history() else None)
        if not batch:
            print("Nothing to undo")
            return 1
        n = lib.undo(batch, task)
        _done()
        print(f"Undid {n} operations")
    elif args.cmd == "config":
        s = load_settings()
        if not args.key:
            print(json.dumps(asdict(s), indent=2))
        else:
            cur = getattr(s, args.key)
            if args.value is None:
                print(cur)
            else:
                val = args.value
                if isinstance(cur, bool):
                    val = val.lower() in ("1", "true", "yes", "on")
                elif isinstance(cur, int):
                    val = int(val)
                elif isinstance(cur, float):
                    val = float(val)
                elif isinstance(cur, list):
                    val = [v.strip() for v in val.split(",") if v.strip()]
                if args.key == "acoustid_api_key" and val:
                    from .providers.acoustid import check_key
                    ok = check_key(val)
                    if ok is False:
                        print("AcoustID didn't accept this key; not saved. Get one at https://acoustid.org/new-application")
                        return 1
                    print("AcoustID key saved" + ("." if ok else " (couldn't verify it right now)."))
                setattr(s, args.key, val)
                save_settings(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
