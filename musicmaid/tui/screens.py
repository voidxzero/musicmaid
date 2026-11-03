"""Modal dialogs and secondary screens for the terminal UI."""
from __future__ import annotations

import time
from dataclasses import fields
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button, Checkbox, DataTable, Footer, Header, Input, Label, OptionList, ProgressBar, Static,
)
from textual.widgets.option_list import Option

from .. import tags as tagio
from ..config import Settings, save_settings
from ..library import Library
from ..organizer import PATTERN_HELP
from ..progress import Cancelled, Task


# ---------------------------------------------------------------- small dialogs
class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "dismiss(False)", "Cancel"), ("y", "dismiss(True)", "Yes"), ("n", "dismiss(False)", "No")]

    def __init__(self, message: str, yes: str = "Yes"):
        super().__init__()
        self.message, self.yes = message, yes

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(self.message, classes="dialog-text")
            with Horizontal(classes="buttons"):
                yield Button(self.yes, variant="primary", id="yes")
                yield Button("Cancel", id="no")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class InputScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, value: str = "", placeholder: str = ""):
        super().__init__()
        self.title_text, self.value, self.placeholder = title, value, placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            yield Input(self.value, placeholder=self.placeholder, id="value")
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one("#value", Input).value if event.button.id == "ok" else None)


# ---------------------------------------------------------------- tag editor
KEEP = "<keep>"


class EditScreen(ModalScreen[dict | None]):
    """Edit tags of one or many tracks. Returns {field: value} of changed fields."""

    BINDINGS = [("escape", "dismiss(None)", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, tracks):
        super().__init__()
        self.tracks = tracks

    def compose(self) -> ComposeResult:
        n = len(self.tracks)
        with Vertical(classes="dialog wide"):
            yield Label(f"Edit tags — {n} track{'s' if n != 1 else ''}"
                        + ("  (fields showing <keep> differ between tracks)" if n > 1 else ""), classes="dialog-title")
            with VerticalScroll(classes="form"):
                for f in tagio.EDITABLE_FIELDS:
                    values = {t.tags.get(f, "") for t in self.tracks}
                    val = next(iter(values)) if len(values) == 1 else KEEP
                    with Horizontal(classes="form-row"):
                        yield Label(tagio.FIELD_LABELS[f], classes="form-label")
                        yield Input(val, id=f"f_{f}", classes="form-input")
            with Horizontal(classes="buttons"):
                yield Button("Save (Ctrl+S)", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def action_save(self) -> None:
        changes = {}
        for f in tagio.EDITABLE_FIELDS:
            v = self.query_one(f"#f_{f}", Input).value
            if v == KEEP:
                continue
            values = {t.tags.get(f, "") for t in self.tracks}
            if values != {v}:
                changes[f] = v
        self.dismiss(changes)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)


# ---------------------------------------------------------------- settings
_SETTINGS_FORM = [
    ("acoustid_api_key", "AcoustID API key (free: acoustid.org/new-application)"),
    ("fpcalc_path", "fpcalc path (empty = auto)"),
    ("auto_apply_threshold", "Auto-apply matches scoring at least (0-1)"),
    ("prefer_country", "Preferred release country (e.g. US, GB)"),
    ("artwork_sources", "Artwork sources (comma separated: coverartarchive, itunes, deezer)"),
    ("artwork_min_size", "Replace artwork smaller than (px)"),
    ("artwork_max_size", "Downscale embedded artwork to (px, 0 = never)"),
    ("dupe_fingerprint_threshold", "Duplicate fingerprint similarity (0-1)"),
    ("quarantine_folder", "Quarantine folder for removed duplicates (empty = default)"),
    ("organize_pattern", "Organize pattern"),
    ("organize_destination", "Organize destination folder"),
    ("various_artists_name", "Various artists name"),
]
_SETTINGS_BOOLS = [
    ("prefer_album_releases", "Prefer album releases over singles/compilations"),
    ("write_musicbrainz_ids", "Write MusicBrainz IDs"),
    ("genre_from_musicbrainz", "Take genre from MusicBrainz"),
    ("save_cover_jpg", "Also save cover.jpg in album folders"),
    ("use_recycle_bin", "Send removed duplicates to the recycle bin instead of quarantine"),
    ("organize_copy", "Organize copies instead of moving"),
    ("check_for_updates", "Check for updates at startup"),
]


class SettingsScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "dismiss(False)", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("Settings", classes="dialog-title")
            with VerticalScroll(classes="form"):
                for key, label in _SETTINGS_FORM:
                    v = getattr(self.settings, key)
                    if isinstance(v, list):
                        v = ", ".join(v)
                    yield Label(label, classes="form-caption")
                    yield Input(str(v), id=f"s_{key}", password=(key == "acoustid_api_key"))
                for key, label in _SETTINGS_BOOLS:
                    yield Checkbox(label, getattr(self.settings, key), id=f"s_{key}")
            with Horizontal(classes="buttons"):
                yield Button("Save (Ctrl+S)", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def action_save(self) -> None:
        types = {f.name: f.type for f in fields(Settings)}
        try:
            for key, _ in _SETTINGS_FORM:
                raw = self.query_one(f"#s_{key}", Input).value.strip()
                cur = getattr(self.settings, key)
                if isinstance(cur, list) or "list" in str(types.get(key)):
                    val = [x.strip() for x in raw.split(",") if x.strip()]
                elif isinstance(cur, float):
                    val = float(raw)
                elif isinstance(cur, int):
                    val = int(raw or 0)
                else:
                    val = raw
                setattr(self.settings, key, val)
            for key, _ in _SETTINGS_BOOLS:
                setattr(self.settings, key, self.query_one(f"#s_{key}", Checkbox).value)
        except ValueError as e:
            self.notify(f"Invalid value: {e}", severity="error")
            return
        save_settings(self.settings)
        self.dismiss(True)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(False)


# ---------------------------------------------------------------- folders
class FoldersScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "close", "Close"), ("delete", "remove", "Remove folder")]

    def __init__(self, lib: Library):
        super().__init__()
        self.lib = lib
        self.changed = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("Library folders", classes="dialog-title")
            yield OptionList(*[Option(f, id=f) for f in self.lib.folders], id="folders")
            yield Label("Add folder (path, ~ allowed):", classes="form-caption")
            yield Input(placeholder=str(Path.home() / "Music"), id="newfolder")
            with Horizontal(classes="buttons"):
                yield Button("Add", variant="primary", id="add")
                yield Button("Remove selected", variant="error", id="remove")
                yield Button("Close", id="close")

    def _refresh(self) -> None:
        ol = self.query_one("#folders", OptionList)
        ol.clear_options()
        ol.add_options([Option(f, id=f) for f in self.lib.folders])

    def _add(self) -> None:
        inp = self.query_one("#newfolder", Input)
        path = Path(inp.value.strip()).expanduser()
        if not inp.value.strip():
            return
        if not path.is_dir():
            self.notify(f"Not a folder: {path}", severity="error")
            return
        self.lib.add_folder(str(path))
        inp.value = ""
        self.changed = True
        self._refresh()

    def action_remove(self) -> None:
        ol = self.query_one("#folders", OptionList)
        if ol.highlighted is None:
            return
        folder = ol.get_option_at_index(ol.highlighted).id
        self.lib.remove_folder(folder)
        self.changed = True
        self._refresh()

    def action_close(self) -> None:
        self.dismiss(self.changed)

    @on(Input.Submitted, "#newfolder")
    def _submitted(self) -> None:
        self._add()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        {"add": self._add, "remove": self.action_remove, "close": self.action_close}[event.button.id]()


# ---------------------------------------------------------------- history / undo
class HistoryScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "Close")]

    def __init__(self, lib: Library):
        super().__init__()
        self.lib = lib

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("Undo history — pick an operation to undo (newest first)", classes="dialog-title")
            opts = [Option(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}  {label}  ({n} changes)", id=batch)
                    for batch, label, ts, n in self.lib.history()]
            yield OptionList(*opts) if opts else Static("Nothing to undo.")
            with Horizontal(classes="buttons"):
                yield Button("Close", id="close")

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    @on(Button.Pressed)
    def _pressed(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- artwork chooser
class ArtworkScreen(ModalScreen[tuple[bytes, str] | None]):
    """List artwork candidates from all sources; returns (image bytes, label)."""

    BINDINGS = [("escape", "dismiss(None)", "Close")]

    def __init__(self, lib: Library, track):
        super().__init__()
        self.lib, self.track = lib, track
        self.cands = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            tags = self.lib.effective_tags(self.track)
            yield Label(f"Artwork for {tags.get('albumartist') or tags.get('artist', '?')} – {tags.get('album', '?')}",
                        classes="dialog-title")
            yield Static("Searching Cover Art Archive, iTunes and Deezer…", id="art-status")
            yield OptionList(id="art-list")
            yield Label("…or path / URL of an image:", classes="form-caption")
            yield Input(id="art-path")
            with Horizontal(classes="buttons"):
                yield Button("Use file/URL", id="use-path")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self._search()

    @work(thread=True, exclusive=True)
    def _search(self) -> None:
        try:
            cands = self.lib.artwork_candidates(self.track)
        except Exception as e:  # network trouble
            self.app.call_from_thread(self.query_one("#art-status", Static).update, f"Search failed: {e}")
            return
        self.app.call_from_thread(self._show, cands)

    def _show(self, cands) -> None:
        self.cands = cands
        self.query_one("#art-status", Static).update(f"{len(cands)} candidates — Enter to use one")
        ol = self.query_one("#art-list", OptionList)
        ol.add_options([Option(f"{c.score:4.0%}  {c.label}", id=str(i)) for i, c in enumerate(cands)])
        ol.focus()

    @on(OptionList.OptionSelected, "#art-list")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        self._download(self.cands[int(event.option.id)])

    @work(thread=True, exclusive=True)
    def _download(self, cand) -> None:
        from .. import net
        self.app.call_from_thread(self.query_one("#art-status", Static).update, "Downloading…")
        data = net.get_bytes(cand.url, timeout=60)
        if not data:
            self.app.call_from_thread(self.notify, "Download failed", severity="error")
            return
        self.app.call_from_thread(self.dismiss, (data, cand.label))

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "use-path":
            self.dismiss(None)
            return
        src = self.query_one("#art-path", Input).value.strip()
        if src.startswith(("http://", "https://")):
            from ..providers.artwork import ArtCandidate
            self._download(ArtCandidate(url=src, thumb_url=src, source="URL"))
        elif Path(src).expanduser().is_file():
            self.dismiss((Path(src).expanduser().read_bytes(), f"file {Path(src).name}"))
        else:
            self.notify("Not a file or URL", severity="error")


# ---------------------------------------------------------------- task progress helper
class TaskMixin:
    """Run a library call in a thread with a progress bar + status label."""

    def start_task(self, label: str, fn, done=None) -> None:
        self._mm_task = Task(
            on_progress=lambda c, t, m: self.app.call_from_thread(self._mm_progress, c, t, m),
            on_log=lambda m: self.app.call_from_thread(self._mm_log, m),
        )
        self._mm_progress(0, 0, label)
        self._mm_run(fn, done)

    @work(thread=True, exclusive=True, group="task")
    def _mm_run(self, fn, done) -> None:
        try:
            result = fn(self._mm_task)
        except Cancelled:
            self.app.call_from_thread(self._mm_finished, None, "Cancelled", done)
            return
        except Exception as e:
            self.app.call_from_thread(self._mm_finished, None, f"Error: {e}", done)
            return
        self.app.call_from_thread(self._mm_finished, result, None, done)

    def cancel_task(self) -> None:
        if getattr(self, "_task", None):
            self._mm_task.cancel()

    def _mm_progress(self, cur: int, total: int, msg: str) -> None:
        bar = self.query_one("#progress", ProgressBar)
        bar.update(total=total or None, progress=cur)
        self.query_one("#status", Static).update(msg)

    def _mm_log(self, msg: str) -> None:
        self.app.log_message(msg)

    def _mm_finished(self, result, error, done) -> None:
        self._mm_task = None
        bar = self.query_one("#progress", ProgressBar)
        bar.update(total=100, progress=0)
        if error:
            self.query_one("#status", Static).update(error)
            self.notify(error, severity="error" if error.startswith("Error") else "warning")
        elif done:
            done(result)


# ---------------------------------------------------------------- duplicates
class DuplicatesScreen(TaskMixin, Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("f", "find", "Find"),
        Binding("space", "toggle", "Toggle remove"),
        Binding("k", "keep", "Keep this one"),
        Binding("r", "remove", "Remove marked"),
        Binding("ctrl+x", "cancel", "Cancel task"),
    ]

    def __init__(self, lib: Library):
        super().__init__()
        self.lib = lib
        self.groups = []
        self.to_remove: dict[int, int] = {}  # track id -> kept id of its group
        self.row_info: dict[str, tuple[int, int]] = {}  # row key -> (group idx, track id)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(classes="toolbar"):
            yield Checkbox("Use audio fingerprints", True, id="use-fp")
            yield Checkbox("Use artist/title", True, id="use-tags")
            yield Checkbox("Same album only", False, id="same-album")
            yield Button("Find duplicates (F)", variant="primary", id="find")
        yield Static("Press F to search. Best copy of each group is kept; marked (✗) copies are moved to quarantine.",
                     id="dupe-help")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="dupes", classes="fill")
        with Horizontal(id="statusbar"):
            yield ProgressBar(total=100, show_eta=False, id="progress")
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#dupes", DataTable)
        t.add_column("", key="mark", width=3)
        t.add_column("Group", key="group", width=6)
        t.add_column("Artist – Title", key="title", width=40)
        t.add_column("Quality", key="quality", width=14)
        t.add_column("Why", key="why", width=26)
        t.add_column("Path", key="path")

    @on(Button.Pressed, "#find")
    def action_find(self) -> None:
        fp = self.query_one("#use-fp", Checkbox).value
        tg = self.query_one("#use-tags", Checkbox).value
        sa = self.query_one("#same-album", Checkbox).value
        self.start_task("Finding duplicates…", lambda task: self.lib.find_duplicates(
            task, use_fingerprints=fp, use_tags=tg, same_album_only=sa), self._show)

    def _show(self, groups) -> None:
        self.groups = groups
        self.to_remove = {t.id: g.keep.id for g in groups for t in g.extras}
        self._render_groups()
        n = sum(len(g.extras) for g in groups)
        self.query_one("#status", Static).update(f"{len(groups)} groups, {n} extra copies marked for removal")

    def _render_groups(self) -> None:
        table = self.query_one("#dupes", DataTable)
        table.clear()
        self.row_info.clear()
        for gi, g in enumerate(self.groups):
            for t in g.tracks:
                key = f"{gi}:{t.id}"
                self.row_info[key] = (gi, t.id)
                q = f"{t.codec} " + ("lossless" if t.lossless else f"{t.bitrate}k")
                mark = Text("✗", style="bold red") if t.id in self.to_remove else Text("✓", style="bold green")
                table.add_row(mark, str(gi + 1), f"{t.get('artist', '?')} – {t.get('title', t.filename)}",
                              q, ", ".join(sorted(g.reasons)), t.path, key=key)

    def _current(self):
        table = self.query_one("#dupes", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self.row_info.get(key)

    def _refresh_marks(self, gi: int) -> None:
        table = self.query_one("#dupes", DataTable)
        for t in self.groups[gi].tracks:
            mark = Text("✗", style="bold red") if t.id in self.to_remove else Text("✓", style="bold green")
            table.update_cell(f"{gi}:{t.id}", "mark", mark)

    def action_toggle(self) -> None:
        cur = self._current()
        if not cur:
            return
        gi, tid = cur
        g = self.groups[gi]
        if tid in self.to_remove:
            del self.to_remove[tid]
        else:
            keepers = [t.id for t in g.tracks if t.id not in self.to_remove and t.id != tid]
            if not keepers:
                self.notify("At least one copy must be kept", severity="warning")
                return
            self.to_remove[tid] = keepers[0]
        # point removed copies at a kept copy for metadata merging
        keepers = [t.id for t in g.tracks if t.id not in self.to_remove]
        for t in g.tracks:
            if t.id in self.to_remove:
                self.to_remove[t.id] = keepers[0]
        self._refresh_marks(gi)

    def action_keep(self) -> None:
        cur = self._current()
        if not cur:
            return
        gi, tid = cur
        for t in self.groups[gi].tracks:
            if t.id == tid:
                self.to_remove.pop(t.id, None)
            else:
                self.to_remove[t.id] = tid
        self._refresh_marks(gi)

    def action_remove(self) -> None:
        if not self.to_remove:
            self.notify("Nothing marked")
            return
        where = "the recycle bin" if self.lib.settings.use_recycle_bin else f"quarantine ({self.lib.settings.quarantine_path})"
        msg = (f"Move {len(self.to_remove)} duplicate files to {where}?\n\n"
               "Missing tags/artwork are copied to the kept file as proposals. This can be undone (U on main screen).")

        def go(ok: bool | None) -> None:
            if ok:
                remove = dict(self.to_remove)
                self.start_task("Removing duplicates…", lambda task: self.lib.remove_duplicates(
                    list(remove), remove, task), self._removed)

        self.app.push_screen(ConfirmScreen(msg, "Remove"), go)

    def _removed(self, result) -> None:
        n, batch = result
        self.notify(f"Removed {n} duplicates")
        self.groups, self.to_remove = [], {}
        self._render_groups()
        self.app.refresh_library()

    def action_cancel(self) -> None:
        self.cancel_task()


# ---------------------------------------------------------------- organize
class OrganizeScreen(TaskMixin, Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("p", "preview", "Preview"),
        Binding("ctrl+g", "go", "Move files"),
    ]

    def __init__(self, lib: Library, ids: list[int]):
        super().__init__()
        self.lib, self.ids = lib, ids
        self.moves = []

    def compose(self) -> ComposeResult:
        s = self.lib.settings
        yield Header()
        with Vertical(classes="organize-form"):
            yield Label(f"Organize {len(self.ids)} tracks.  {PATTERN_HELP}", classes="form-caption")
            with Horizontal(classes="form-row"):
                yield Label("Pattern", classes="form-label")
                yield Input(s.organize_pattern, id="pattern", classes="form-input")
            with Horizontal(classes="form-row"):
                yield Label("Destination", classes="form-label")
                yield Input(s.organize_destination or (self.lib.folders[0] if self.lib.folders else ""),
                            id="dest", classes="form-input")
            with Horizontal(classes="toolbar"):
                yield Checkbox("Copy instead of move", s.organize_copy, id="copy")
                yield Checkbox("Skip untagged files", True, id="skip")
                yield Button("Preview (P)", id="preview")
                yield Button("Move files (Ctrl+G)", variant="warning", id="go")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="plan", classes="fill")
        with Horizontal(id="statusbar"):
            yield ProgressBar(total=100, show_eta=False, id="progress")
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#plan", DataTable)
        t.add_column("From", key="from")
        t.add_column("To", key="to")
        self.action_preview()

    def action_preview(self) -> None:
        pattern = self.query_one("#pattern", Input).value
        dest = self.query_one("#dest", Input).value.strip()
        try:
            self.moves = [m for m in self.lib.organize_plan(self.ids, pattern, dest,
                                                            self.query_one("#skip", Checkbox).value) if m.changed]
        except (ValueError, KeyError, IndexError) as e:
            self.notify(f"Bad pattern/destination: {e}", severity="error")
            return
        table = self.query_one("#plan", DataTable)
        table.clear()
        for i, m in enumerate(self.moves[:5000]):
            table.add_row(m.src, Text(m.dst, style="green"), key=str(i))
        pending = len(self.lib.db.proposal_ids() & set(self.ids))
        msg = f"{len(self.moves)} files will move."
        if pending:
            msg += f"  ⚠ {pending} tracks have unapplied proposals - apply them first for best results."
        self.query_one("#status", Static).update(msg)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preview":
            self.action_preview()
        elif event.button.id == "go":
            self.action_go()

    def action_go(self) -> None:
        self.action_preview()
        if not self.moves:
            return
        copy = self.query_one("#copy", Checkbox).value
        s = self.lib.settings
        s.organize_pattern = self.query_one("#pattern", Input).value
        s.organize_destination = self.query_one("#dest", Input).value.strip()
        s.organize_copy = copy
        save_settings(s)

        def go(ok: bool | None) -> None:
            if ok:
                moves = list(self.moves)
                self.start_task("Organizing…", lambda task: self.lib.organize(moves, copy, task), self._done)

        self.app.push_screen(ConfirmScreen(f"{'Copy' if copy else 'Move'} {len(self.moves)} files? (undoable)",
                                           "Copy" if copy else "Move"), go)

    def _done(self, result) -> None:
        n, batch = result
        self.notify(f"Organized {n} files")
        self.app.refresh_library()
        self.app.pop_screen()
