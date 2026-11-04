"""High-level library operations shared by the GUI, TUI and CLI.

Every destructive operation (writing tags, moving, quarantining) is journaled so it
can be undone, and all tag changes coming from automatic sources are first stored
as *proposals* that can be reviewed before they touch any file.
"""
from __future__ import annotations

import base64
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import cleanup, duplicates, organizer, scanner
from . import tags as tagio
from .config import Settings, load_settings, save_settings
from .db import Database, Proposal, Track
from .identify import identify_and_propose
from .net import NetError
from .progress import NULL_TASK, Cancelled, Task
from .providers import artwork as artprov

VIEWS = {
    "all": "All tracks",
    "review": "Needs review",
    "untagged": "Untagged",
    "noart": "Missing artwork",
    "problems": "Problems",
    "errors": "Unreadable",
}


@dataclass
class ApplyResult:
    written: int = 0
    failed: int = 0
    batch: str = ""


class Library:
    def __init__(self, db: Database | None = None, settings: Settings | None = None):
        self.db = db or Database()
        self.settings = settings or load_settings()

    # ------------------------------------------------------------ folders & scanning
    @property
    def folders(self) -> list[str]:
        return list(self.settings.library_folders)

    def add_folder(self, path: str) -> None:
        path = os.path.abspath(os.path.expanduser(path))
        if path not in self.settings.library_folders:
            self.settings.library_folders.append(path)
            save_settings(self.settings)

    def remove_folder(self, path: str) -> None:
        if path in self.settings.library_folders:
            self.settings.library_folders.remove(path)
            save_settings(self.settings)
            ids = [tid for tid, _, _ in self.db.known_files(path).values()]
            self.db.remove_tracks(ids)

    def scan(self, task: Task = NULL_TASK, force: bool = False) -> dict[str, int]:
        return scanner.scan(self.db, self.folders, task, force=force)

    # ------------------------------------------------------------ views
    def tracks(self, ids=None) -> list[Track]:
        return self.db.tracks(ids)

    def view(self, name: str = "all", search: str = "") -> list[Track]:
        tracks = self.db.tracks()
        if name == "review":
            pids = self.db.proposal_ids()
            tracks = [t for t in tracks if t.id in pids]
        elif name == "untagged":
            tracks = [t for t in tracks if not t.error and cleanup.is_untagged(t)]
        elif name == "noart":
            tracks = [t for t in tracks if not t.error and not t.has_art]
        elif name == "problems":
            tracks = [t for t in tracks if cleanup.problems(t, self.settings.artwork_min_size)]
        elif name == "errors":
            tracks = [t for t in tracks if t.error]
        if search:
            terms = search.lower().split()
            tracks = [t for t in tracks if all(
                term in (t.path.lower() + " " + " ".join(t.tags.values()).lower()) for term in terms)]
        return tracks

    def counts(self) -> dict[str, int]:
        tracks = self.db.tracks()
        pids = self.db.proposal_ids()
        return {
            "all": len(tracks),
            "review": len(pids),
            "untagged": sum(1 for t in tracks if not t.error and cleanup.is_untagged(t)),
            "noart": sum(1 for t in tracks if not t.error and not t.has_art),
            "problems": sum(1 for t in tracks if cleanup.problems(t, self.settings.artwork_min_size)),
            "errors": sum(1 for t in tracks if t.error),
        }

    def effective_tags(self, t: Track) -> dict[str, str]:
        p = self.db.proposal(t.id)
        tags = dict(t.tags)
        if p:
            for k, v in p.tags.items():
                if v:
                    tags[k] = v
                else:
                    tags.pop(k, None)
        return tags

    # ------------------------------------------------------------ identification / cleanup
    def identify(self, ids: list[int], task: Task = NULL_TASK) -> dict[str, int]:
        # search with pending (e.g. cleaned-up) values, not just what is on disk
        tracks = self.db.tracks(ids)
        for t in tracks:
            t.tags = self.effective_tags(t)
        matches, unmatched = identify_and_propose(self.db, tracks, task, self.settings)
        confident = sum(1 for m in matches if m.confidence >= self.settings.auto_apply_threshold)
        return {"matched": len(matches), "confident": confident, "unmatched": len(unmatched)}

    def cleanup(self, ids: list[int], task: Task = NULL_TASK, options: cleanup.CleanupOptions | None = None) -> int:
        return cleanup.propose_cleanup(self.db, self.db.tracks(ids), options, task, self.folders)

    def tags_from_paths(self, ids: list[int], task: Task = NULL_TASK, *, pattern: str | None = None,
                        overwrite: bool = False) -> int:
        """Propose tags read from folder/file names (automatic, or a %artist%/%album%/... pattern)."""
        from . import pathtags
        return pathtags.propose(self.db, self.db.tracks(ids), self.folders, pattern or None, overwrite, task)

    def auto_tag(self, ids: list[int], task: Task = NULL_TASK, *, apply_confident: bool = True) -> dict[str, int]:
        """Clean up → identify → fetch missing art → write confident results."""
        self.cleanup(ids, task)
        res = self.identify(ids, task)
        res["artwork"] = self.fetch_artwork(ids, task, only_missing=True)
        if apply_confident:
            summary = self.db.proposal_summary()
            good = [tid for tid in ids if tid in summary and
                    (summary[tid][1] >= self.settings.auto_apply_threshold or "MusicBrainz" not in summary[tid][0])]
            # cleanup-only / artwork-only proposals are safe to apply, MusicBrainz ones need confidence
            res["applied"] = self.apply(good, task, label="Auto-tag").written
        res["review"] = len(self.db.proposal_ids() & set(ids))
        return res

    # ------------------------------------------------------------ artwork
    def _album_groups(self, tracks: list[Track]) -> dict[tuple, list[Track]]:
        groups: dict[tuple, list[Track]] = defaultdict(list)
        for t in tracks:
            tags = self.effective_tags(t)
            key = (t.folder, tags.get("musicbrainz_albumid") or tags.get("album", "").lower())
            groups[key].append(t)
        return groups

    def artwork_candidates(self, t: Track) -> list[artprov.ArtCandidate]:
        tags = self.effective_tags(t)
        return artprov.search(
            tags.get("albumartist") or tags.get("artist", ""), tags.get("album", ""),
            tags.get("musicbrainz_albumid", ""), tags.get("musicbrainz_releasegroupid", ""),
            self.settings.artwork_sources,
        )

    def fetch_artwork(self, ids: list[int], task: Task = NULL_TASK, *, only_missing: bool = True) -> int:
        tracks = [t for t in self.db.tracks(ids) if not t.error]
        if only_missing:
            min_size = self.settings.artwork_min_size
            tracks = [t for t in tracks if not t.has_art or (t.art_w and min(t.art_w, t.art_h) < min_size)]
        groups = self._album_groups(tracks)
        found = 0
        for i, (key, gtracks) in enumerate(groups.items()):
            rep = gtracks[0]
            tags = self.effective_tags(rep)
            album = tags.get("album", "")
            task.progress(i, len(groups), f"Artwork: {album or rep.filename}")
            if not album and not tags.get("musicbrainz_albumid"):
                continue
            # reuse cover already embedded in another file of the same album
            donor = next((t for t in self.db.tracks(where="folder=? AND has_art=1", args=(rep.folder,))
                          if t.art_w >= self.settings.artwork_min_size
                          and self.effective_tags(t).get("album", "").lower() == album.lower()), None)
            data, label = None, ""
            if donor:
                art = tagio.read_artwork(donor.path)
                if art:
                    data, label = art.data, f"copied from {donor.filename}"
            if data is None:
                try:
                    res = artprov.best(tags.get("albumartist") or tags.get("artist", ""), album,
                                       tags.get("musicbrainz_albumid", ""), tags.get("musicbrainz_releasegroupid", ""),
                                       self.settings.artwork_sources)
                except NetError as e:
                    task.log(str(e))
                    res = None
                if res:
                    cand, data = res
                    label = cand.label
            if data is None:
                task.log(f"No artwork found for {album}")
                continue
            for t in gtracks:
                self.db.set_proposal(Proposal(track_id=t.id, tags={}, art=data, art_source=label, source="Artwork", score=1.0))
                found += 1
        return found

    def propose_artwork(self, ids: list[int], data: bytes, source: str = "manual") -> None:
        for tid in ids:
            self.db.set_proposal(Proposal(track_id=tid, tags={}, art=data, art_source=source, source="Artwork", score=1.0))

    # ------------------------------------------------------------ applying changes
    def _write_with_journal(self, batch: str, label: str, t: Track, changes: dict[str, str], art) -> None:
        old_tags = {k: t.tags.get(k, "") for k in changes}
        journal_art: str | None = "__keep__"
        if art is not tagio._KEEP:
            cur = tagio.read_artwork(t.path)
            journal_art = base64.b64encode(cur.data).decode() if cur else None
            if isinstance(art, (bytes, bytearray)):
                art = tagio.prepare_artwork(bytes(art), self.settings.artwork_max_size)
        tagio.write(t.path, changes, art)
        self.db.journal(batch, label, "tags", t.id, t.path, None, {"tags": old_tags, "art": journal_art})
        if self.settings.save_cover_jpg and isinstance(art, (bytes, bytearray)):
            cover = Path(t.folder) / "cover.jpg"
            if not cover.exists():
                cover.write_bytes(art)
                self.db.journal(batch, label, "create", None, None, str(cover))
        scanner.refresh_track(self.db, t.path)

    def apply(self, ids: list[int], task: Task = NULL_TASK, label: str = "Apply changes",
              exclude: dict[int, set[str]] | None = None) -> ApplyResult:
        """Write proposals to the files. exclude maps track id -> fields to leave out ("__art__" = artwork);
        left-out changes stay proposed, so they can still be applied or discarded later."""
        res = ApplyResult(batch=self.db.new_batch())
        exclude = exclude or {}
        ids = [i for i in ids if i in self.db.proposal_ids()]
        for i, t in enumerate(self.db.tracks(ids)):
            task.progress(i, len(ids), f"Writing {t.filename}")
            p = self.db.proposal(t.id)
            if not p:
                continue
            skip = exclude.get(t.id, set())
            tags = {k: v for k, v in p.tags.items() if k not in skip}
            art = p.art if p.art is not None and "__art__" not in skip else None
            if not tags and art is None:
                continue
            try:
                self._write_with_journal(res.batch, label, t, tags, art if art is not None else tagio._KEEP)
                left = {k: v for k, v in p.tags.items() if k in skip}
                left_art = p.art if "__art__" in skip else None
                if left or left_art is not None:
                    self.db.set_proposal(Proposal(t.id, left, left_art, p.art_source if left_art else None,
                                                  p.source, p.score, p.note), merge=False)
                else:
                    self.db.delete_proposals([t.id])
                res.written += 1
            except Cancelled:
                raise
            except Exception as e:
                res.failed += 1
                task.log(f"Failed to write {t.path}: {e}")
        return res

    def discard(self, ids: list[int]) -> None:
        self.db.delete_proposals(ids)

    def set_new_value(self, ids: list[int], field: str, value: str) -> None:
        """A manual edit in the "New" column: propose field=value for these tracks (nothing is written yet).
        Where value equals the file's current value, that field's pending change is dropped instead."""
        value = value.strip()
        for t in self.db.tracks(ids):
            p = self.db.proposal(t.id)
            tags = dict(p.tags) if p else {}
            if value == (t.tags.get(field) or "").strip():
                tags.pop(field, None)
            else:
                tags[field] = value
            if tags or (p and p.art is not None):
                src = p.source if p and p.source else "Manual edit"
                if "Manual edit" not in src:
                    src += ", Manual edit"
                self.db.set_proposal(Proposal(t.id, tags, p.art if p else None, p.art_source if p else None,
                                              src, p.score if p and p.tags else 1.0, p.note if p else ""),
                                     merge=False)
            elif p:
                self.db.delete_proposals([t.id])

    def fix_library(self, ids: list[int], task: Task = NULL_TASK, *, lookup: bool = True, artwork: bool = True,
                    clean: bool = True, skip_identified: bool = True) -> dict[str, int]:
        """Whole-library pass: clean up, look up tags and find missing artwork, proposing changes only.
        Nothing is written; the results are reviewed album by album (or folder by folder)."""
        res = {"cleaned": 0, "identified": 0, "artwork": 0}
        if clean:
            res["cleaned"] = self.cleanup(ids, task)
        if lookup:
            todo = ids
            if skip_identified:
                todo = [t.id for t in self.db.tracks(ids) if not t.tags.get("musicbrainz_recordingid")]
                task.log(f"Looking up {len(todo)} tracks ({len(ids) - len(todo)} already have MusicBrainz IDs)")
            if todo:
                r = self.identify(todo, task)
                res["identified"] = r.get("matched", 0) if isinstance(r, dict) else 0
        if artwork:
            res["artwork"] = self.fetch_artwork(ids, task, only_missing=True)
        res["waiting"] = len(self.db.proposal_ids() & set(ids))
        return res

    def review_groups(self, by: str = "album", ids: set[int] | None = None) -> list[tuple[str, list[Track]]]:
        """Tracks with pending changes, grouped per album (by the new tags) or per folder, in a stable order."""
        pending = self.db.proposal_ids()
        if ids is not None:
            pending &= ids
        groups: dict[str, list[Track]] = defaultdict(list)
        for t in self.db.tracks(sorted(pending)):
            if by == "folder":
                key = t.folder
            else:
                new = {**t.tags, **(self.db.proposal(t.id).tags if self.db.proposal(t.id) else {})}
                artist = new.get("albumartist") or new.get("artist") or ""
                key = f"{artist} \u2013 {new['album']}" if new.get("album") else t.folder
            groups[key].append(t)
        from .foldertree import album_order
        return [(k, sorted(v, key=album_order)) for k, v in sorted(groups.items(), key=lambda kv: kv[0].casefold())]

    def edit(self, ids: list[int], changes: dict[str, str], art=tagio._KEEP, task: Task = NULL_TASK) -> ApplyResult:
        """Write manual edits immediately (journaled)."""
        res = ApplyResult(batch=self.db.new_batch())
        tracks = self.db.tracks(ids)
        for i, t in enumerate(tracks):
            task.progress(i, len(tracks), f"Writing {t.filename}")
            try:
                self._write_with_journal(res.batch, "Edit tags", t, changes, art)
                res.written += 1
                p = self.db.proposal(t.id)
                if p:  # edited fields are no longer pending
                    rest = {k: v for k, v in p.tags.items() if k not in changes}
                    if rest or (p.art is not None and art is tagio._KEEP):
                        p.tags = rest
                        if art is not tagio._KEEP:
                            p.art = None
                        self.db.set_proposal(p, merge=False)
                    else:
                        self.db.delete_proposals([t.id])
            except Exception as e:
                res.failed += 1
                task.log(f"Failed to write {t.path}: {e}")
        return res

    # ------------------------------------------------------------ duplicates
    def find_duplicates(self, task: Task = NULL_TASK, *, use_fingerprints: bool = True, use_tags: bool = True,
                        same_album_only: bool = False, ids: list[int] | None = None) -> list[duplicates.DupeGroup]:
        tracks = self.db.tracks(ids) if ids else self.db.tracks()
        return duplicates.find_duplicates(
            self.db, tracks, use_fingerprints=use_fingerprints, use_tags=use_tags,
            same_album_only=same_album_only, threshold=self.settings.dupe_fingerprint_threshold, task=task)

    def _library_root(self, path: str) -> str | None:
        for f in self.folders:
            try:
                Path(path).relative_to(f)
                return f
            except ValueError:
                continue
        return None

    @staticmethod
    def _tag_richness(t: Track) -> int:
        return sum(1 for v in t.tags.values() if v) + (10 if t.tags.get("musicbrainz_recordingid") else 0)

    def _merge_duplicate_metadata(self, removed: list[Track], keep_map: dict[int, int]) -> None:
        """Give each kept copy the best tags/artwork found among its removed duplicates."""
        by_keep: dict[int, list[Track]] = defaultdict(list)
        for t in removed:
            if t.id in keep_map:
                by_keep[keep_map[t.id]].append(t)
        for keep_id, extras in by_keep.items():
            keep = self.db.track(keep_id)
            if not keep:
                continue
            donor = max(extras, key=self._tag_richness)
            tags: dict[str, str] = {}
            if self._tag_richness(donor) > self._tag_richness(keep):
                # the better-tagged copy wins completely (keeps album/track numbers consistent)
                tags = {k: v for k, v in donor.tags.items() if v and keep.tags.get(k) != v
                        and k not in ("comment",)}
            else:
                for e in extras:
                    for k, v in e.tags.items():
                        if v and not keep.tags.get(k) and k not in tags:
                            tags[k] = v
            art_donor = max((e for e in extras if e.has_art), key=lambda e: min(e.art_w, e.art_h), default=None)
            art = None
            if art_donor and (not keep.has_art or min(keep.art_w, keep.art_h) < min(art_donor.art_w, art_donor.art_h)):
                a = tagio.read_artwork(art_donor.path)
                art = a.data if a else None
            if tags or art:
                old = self.db.proposal(keep.id)
                if tags:
                    # a fuzzy online guess is worse than tags from an identical copy
                    self.db.delete_proposals([keep.id])
                    if old and old.art is not None and art is None:
                        art = old.art
                self.db.set_proposal(Proposal(
                    track_id=keep.id, tags=tags, art=art,
                    art_source=f"from duplicate {art_donor.filename}" if art and art_donor else None,
                    source="Duplicate merge", score=1.0, note=f"tags copied from duplicate {donor.filename}"))

    def remove_duplicates(self, remove_ids: list[int], keep_map: dict[int, int] | None = None,
                          task: Task = NULL_TASK, merge_metadata: bool = True) -> tuple[int, str]:
        """Quarantine (or recycle) the given tracks. keep_map maps removed id -> kept id for metadata merging."""
        batch = self.db.new_batch()
        tracks = self.db.tracks(remove_ids)
        if merge_metadata and keep_map:
            self._merge_duplicate_metadata(tracks, keep_map)
        removed = 0
        qroot = self.settings.quarantine_path / batch
        for i, t in enumerate(tracks):
            task.progress(i, len(tracks), f"Removing {t.filename}")
            try:
                if self.settings.use_recycle_bin:
                    from send2trash import send2trash
                    send2trash(t.path)
                    self.db.journal(batch, "Remove duplicates", "trash", t.id, t.path, None, t.tags)
                else:
                    root = self._library_root(t.path)
                    rel = Path(t.path).relative_to(root) if root else Path(*Path(t.path).parts[1:])
                    dst = qroot / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(t.path, dst)
                    self.db.journal(batch, "Remove duplicates", "quarantine", t.id, t.path, str(dst), t.tags)
                self.db.remove_tracks([t.id])
                removed += 1
                organizer.remove_empty_dirs(str(Path(t.path).parent), self.folders)
            except Exception as e:
                task.log(f"Could not remove {t.path}: {e}")
        return removed, batch

    # ------------------------------------------------------------ CUE sheets
    def cue_sheets(self, folder: str | None = None) -> list["cuesplit.CueSheet"]:
        """CUE sheets in the library (or one folder of it), including ones embedded in long FLAC files."""
        from . import cuesplit
        roots = [folder] if folder else self.folders
        long_tracks = [t.path for t in self.db.tracks() if t.duration >= 15 * 60
                       and (not folder or t.path.startswith(folder.rstrip(os.sep) + os.sep))]
        return cuesplit.find_sheets(roots, long_tracks)

    def split_cues(self, sheets: list["cuesplit.CueSheet"], task: Task = NULL_TASK, *, dest: str | None = None,
                   remove_original: bool = True) -> tuple[int, int, str]:
        """Split each sheet into track files (undoable). Returns (tracks created, sheets failed, batch).

        With remove_original, the big audio file and its .cue go to the quarantine folder afterwards (only
        when every track was created), so the album isn't in the library twice."""
        from . import cuesplit
        batch = self.db.new_batch()
        label = "Split CUE sheets"
        made = failed = 0
        for n, sheet in enumerate(sheets, 1):
            name = Path(sheet.path).name
            task.log(f"[{n}/{len(sheets)}] {name}")
            try:
                jobs = cuesplit.plan(sheet, dest)

                def created(path: str) -> None:
                    self.db.journal(batch, label, "create", None, None, path)
                    scanner.refresh_track(self.db, path)
                done, skipped = cuesplit.split(jobs, task, on_created=created)
                made += len(done)
                if skipped:
                    task.log(f"  {len(skipped)} track file(s) already existed and were left alone")
                if remove_original and len(done) + len(skipped) == len(jobs):
                    self._quarantine_cue_source(sheet, batch, label)
            except cuesplit.CueError as e:
                failed += 1
                task.log(f"  Couldn't split {name}: {e}")
        return made, failed, batch

    def _quarantine_cue_source(self, sheet, batch: str, label: str) -> None:
        qroot = self.settings.quarantine_path / batch
        extra = [] if sheet.embedded else [sheet.path]
        for path in [*sheet.files, *extra]:
            if not os.path.exists(path):
                continue
            root = self._library_root(path)
            rel = Path(path).relative_to(root) if root else Path(*Path(path).parts[1:])
            dst = qroot / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            t = self.db.track_by_path(path)
            shutil.move(path, dst)
            if t:
                self.db.journal(batch, label, "quarantine", t.id, path, str(dst), t.tags)
                self.db.remove_tracks([t.id])
            else:
                self.db.journal(batch, label, "move", None, path, str(dst))

    # ------------------------------------------------------------ organizing
    def organize_plan(self, ids: list[int], pattern: str | None = None, destination: str | None = None,
                      skip_untagged: bool = True) -> list[organizer.Move]:
        """Plan moves. Tracks without artist/title are skipped by default (they'd land in 'Unknown Artist')."""
        pattern = pattern or self.settings.organize_pattern
        destination = destination or self.settings.organize_destination or (self.folders[0] if self.folders else "")
        if not destination:
            raise ValueError("No destination folder set")
        tracks = self.db.tracks(ids)
        if skip_untagged:
            tracks = [t for t in tracks if not t.error and not cleanup.is_untagged(t)]
        if "{current_folder}" in pattern:
            # keep each track where it is: plan per library folder, relative to it
            by_root: dict[str, list[Track]] = defaultdict(list)
            for t in tracks:
                by_root[self._library_root(t.path) or t.folder].append(t)
            taken: set[str] = set()
            return [m for root, ts in by_root.items()
                    for m in organizer.plan(ts, pattern, root, self.settings.various_artists_name, taken)]
        return organizer.plan(tracks, pattern, destination, self.settings.various_artists_name)

    def organize(self, moves: list[organizer.Move], copy: bool = False, task: Task = NULL_TASK) -> tuple[int, str]:
        batch = self.db.new_batch()
        label = "Copy files" if copy else "Organize files"
        done = 0
        src_folders: dict[str, str] = {}
        moves = [m for m in moves if m.changed]
        for i, m in enumerate(moves):
            task.progress(i, len(moves), f"{'Copying' if copy else 'Moving'} {Path(m.src).name}")
            try:
                Path(m.dst).parent.mkdir(parents=True, exist_ok=True)
                if os.path.exists(m.dst) and os.path.normcase(m.dst) != os.path.normcase(m.src):
                    task.log(f"Skipped (target exists): {m.dst}")
                    continue
                if copy:
                    shutil.copy2(m.src, m.dst)
                    self.db.journal(batch, label, "copy", None, m.src, m.dst)
                else:
                    shutil.move(m.src, m.dst)
                    self.db.journal(batch, label, "move", m.track.id, m.src, m.dst)
                    self.db.update_path(m.track.id, m.dst)
                    for sc in organizer.sidecars(m.src):
                        sdst = str(Path(m.dst).with_suffix(Path(sc).suffix))
                        if not os.path.exists(sdst):
                            shutil.move(sc, sdst)
                            self.db.journal(batch, label, "move", None, sc, sdst)
                    src_folders[str(Path(m.src).parent)] = str(Path(m.dst).parent)
                done += 1
            except OSError as e:
                task.log(f"Could not move {m.src}: {e}")
        # carry folder artwork along and remove emptied folders
        for src_dir, dst_dir in src_folders.items():
            try:
                remaining_audio = any(tagio.is_audio_file(p) for p in os.listdir(src_dir))
            except OSError:
                continue
            if remaining_audio:
                continue
            for name in os.listdir(src_dir):
                if name.lower() in organizer.FOLDER_IMAGES:
                    s, d = os.path.join(src_dir, name), os.path.join(dst_dir, name)
                    if not os.path.exists(d):
                        shutil.move(s, d)
                        self.db.journal(batch, label, "move", None, s, d)
            organizer.remove_empty_dirs(src_dir, self.folders + [self.settings.organize_destination or ""])
        if not copy and moves:
            dest_root = self.settings.organize_destination
            if dest_root and not self._library_root(dest_root):
                self.add_folder(dest_root)
        return done, batch

    # ------------------------------------------------------------ undo
    def history(self) -> list[tuple[str, str, float, int]]:
        return self.db.batches()

    def undo(self, batch: str, task: Task = NULL_TASK) -> int:
        entries = self.db.batch_entries(batch)
        undone = []
        for i, (eid, op, track_id, src, dst, data) in enumerate(entries):
            task.progress(i, len(entries), f"Undoing {op}")
            try:
                import json
                payload = json.loads(data) if data else None
                if op in ("move", "quarantine"):
                    if dst and os.path.exists(dst) and not os.path.exists(src):
                        Path(src).parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(dst, src)
                        if op == "move" and track_id:
                            self.db.update_path(track_id, src)
                        elif op == "quarantine":
                            scanner.refresh_track(self.db, src)
                        organizer.remove_empty_dirs(str(Path(dst).parent), self.folders + [str(self.settings.quarantine_path)])
                elif op in ("copy", "create"):
                    if dst and os.path.exists(dst):
                        os.remove(dst)
                    gone = self.db.track_by_path(dst) if dst else None
                    if gone:
                        self.db.remove_tracks([gone.id])
                elif op == "tags":
                    t = self.db.track(track_id) if track_id else None
                    path = t.path if t else src
                    art = tagio._KEEP
                    if payload.get("art") != "__keep__":
                        art = base64.b64decode(payload["art"]) if payload.get("art") else None
                    tagio.write(path, payload.get("tags", {}), art)
                    scanner.refresh_track(self.db, path)
                elif op == "trash":
                    task.log(f"{src} was sent to the recycle bin - restore it from there.")
                undone.append(eid)
            except Exception as e:
                task.log(f"Undo failed for {src or dst}: {e}")
        self.db.mark_undone(undone)
        return len(undone)
