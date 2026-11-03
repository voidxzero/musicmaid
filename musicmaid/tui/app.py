"""MusicMaid terminal UI (Textual)."""
from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    DataTable, Footer, Header, Input, Label, ListItem, ListView, ProgressBar, RichLog, Static,
)

from .. import APP_NAME, __version__
from .. import tags as tagio
from ..cleanup import problems
from ..config import save_settings
from ..fingerprint import can_download_fpcalc, download_fpcalc, find_fpcalc
from .. import updater
from ..library import VIEWS, Library
from .screens import (
    ArtworkScreen, ConfirmScreen, DuplicatesScreen, EditScreen, FoldersScreen, HistoryScreen, OrganizeScreen,
    SettingsScreen, TaskMixin,
)

CSS = """
#sidebar { width: 26; border-right: solid $primary-darken-2; }
#sidebar ListView { height: auto; }
#sidebar .side-title { padding: 0 1; color: $text-muted; text-style: bold; margin-top: 1; }
#main { width: 1fr; }
#search { margin: 0 0; }
#tracks { height: 1fr; }
#details { width: 48; border-left: solid $primary-darken-2; padding: 0 1; }
#body { height: 1fr; }
#statusbar { height: 1; }
#statusbar ProgressBar { width: 34; }
#status { width: 1fr; padding: 0 1; }
#log { height: 10; border-top: solid $primary-darken-2; display: none; }
#log.visible { display: block; }
.dialog { width: 70; height: auto; max-height: 90%; background: $panel; border: thick $primary; padding: 1 2; }
.dialog.wide { width: 100; }
ModalScreen { align: center middle; }
.dialog-title { text-style: bold; margin-bottom: 1; }
.dialog-text { margin-bottom: 1; }
.buttons { height: auto; margin-top: 1; align-horizontal: right; }
.buttons Button { margin-left: 1; }
.form { height: auto; max-height: 30; }
.form-row { height: 3; }
.form-label { width: 18; padding-top: 1; }
.form-input { width: 1fr; }
.form-caption { color: $text-muted; margin-top: 1; }
.toolbar { height: 3; }
.toolbar Checkbox { margin-right: 1; }
.organize-form { height: auto; padding: 0 1; }
#folders { height: 8; }
#art-list { height: 14; }
.fill { height: 1fr; }
#dupe-help { color: $text-muted; padding: 0 1; }
"""


class MusicMaidTUI(TaskMixin, App):
    TITLE = APP_NAME
    SUB_TITLE = f"music library cleaner {__version__}"
    CSS = CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "mark", "Mark", show=False),
        Binding("ctrl+a", "mark_all", "Mark all", show=False),
        Binding("escape", "clear_marks", "Clear marks", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("s", "scan", "Scan"),
        Binding("t", "autotag", "Auto-tag"),
        Binding("i", "identify", "Identify"),
        Binding("c", "cleanup", "Clean up"),
        Binding("w", "artwork", "Artwork"),
        Binding("W", "choose_artwork", "Pick art", show=False),
        Binding("e", "edit", "Edit"),
        Binding("a", "apply", "Apply"),
        Binding("x", "discard", "Discard"),
        Binding("d", "dupes", "Duplicates"),
        Binding("o", "organize", "Organize"),
        Binding("u", "undo", "Undo"),
        Binding("f", "folders", "Folders"),
        Binding("comma", "settings", "Settings"),
        Binding("l", "toggle_log", "Log", show=False),
        Binding("ctrl+x", "cancel", "Cancel task", show=False),
    ]

    def __init__(self, lib: Library | None = None):
        super().__init__()
        self.lib = lib or Library()
        self.view_name = "all"
        self.marked: set[int] = set()
        self.shown = []
        self.by_id = {}
        self.pending: dict[int, tuple[str, float, bool]] = {}

    def check_action(self, action: str, parameters) -> bool | None:
        # library shortcuts only make sense on the main screen (not in dialogs/sub-screens)
        main_only = {b.action for b in self.BINDINGS} - {"quit", "cancel"}
        if len(self.screen_stack) > 1 and action in main_only:
            return False
        return True

    # ------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Label("LIBRARY", classes="side-title")
                yield ListView(*[ListItem(Label(label, id=f"lbl_{key}"), id=f"view_{key}")
                                 for key, label in VIEWS.items()], id="views")
                yield Label("KEYS", classes="side-title")
                yield Static(
                    "space  mark track\nctrl+a mark all\n/      search\nt      auto-tag\ni      identify\n"
                    "c      clean up tags\nw / W  artwork auto/pick\ne      edit tags\na / x  apply / discard\n"
                    "d      duplicates\no      organize files\nu      undo\nf      folders\n,      settings\n"
                    "l      show log\nctrl+x cancel task",
                    classes="keys",
                )
            with Vertical(id="main"):
                yield Input(placeholder="Search artist, title, album, path…  (/)", id="search")
                yield DataTable(cursor_type="row", zebra_stripes=True, id="tracks")
                yield RichLog(id="log", wrap=True, markup=False)
            with VerticalScroll(id="details"):
                yield Static("", id="detail")
        with Horizontal(id="statusbar"):
            yield ProgressBar(total=100, show_eta=False, id="progress")
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#tracks", DataTable)
        for key, label, width in [("mark", "", 1), ("state", "", 1), ("artist", "Artist", 20), ("title", "Title", 26),
                                  ("album", "Album", 20), ("track", "#", 3), ("year", "Year", 4),
                                  ("format", "Format", 11), ("file", "File", 40)]:
            t.add_column(label, key=key, width=width)
        self.refresh_library()
        t.focus()
        if not self.lib.folders:
            self.call_after_refresh(self.action_folders)
        if not find_fpcalc():
            self.log_message("fpcalc (Chromaprint) not found: duplicate detection by audio and AcoustID are disabled. "
                             "Install it with your package manager (e.g. 'dnf install chromaprint-tools') "
                             "or run 'musicmaid-cli fpcalc' to download it.")
            if can_download_fpcalc() and self.lib.settings.offer_fpcalc_download:
                self.call_after_refresh(self._offer_fpcalc)
        if self.lib.settings.check_for_updates:
            self._check_updates()
        if not self.lib.settings.acoustid_api_key:
            self.log_message("Tip: add a free AcoustID API key in Settings (,) to identify tracks by their audio.")

    # ------------------------------------------------------------ data
    def refresh_library(self) -> None:
        counts = self.lib.counts()
        for key, label in VIEWS.items():
            self.query_one(f"#lbl_{key}", Label).update(f"{label} ({counts.get(key, 0)})")
        self.pending = self.lib.db.proposal_summary()
        search = self.query_one("#search", Input).value
        self.shown = self.lib.view(self.view_name, search)
        self.by_id = {t.id: t for t in self.shown}
        self.marked &= set(self.by_id)
        table = self.query_one("#tracks", DataTable)
        row = table.cursor_row
        table.clear()
        for t in self.shown:
            table.add_row(*self._cells(t), key=str(t.id))
        if self.shown:
            table.move_cursor(row=min(row, len(self.shown) - 1))
        self.query_one("#status", Static).update(
            f"{len(self.shown)} tracks shown · {len(self.marked)} marked · {counts['review']} awaiting review")
        self._update_detail()

    def _cells(self, t):
        mark = Text("●", style="bold yellow") if t.id in self.marked else ""
        if t.error:
            state = Text("!", style="bold red")
        elif t.id in self.pending:
            src, score, _ = self.pending[t.id]
            style = "bold green" if score >= self.lib.settings.auto_apply_threshold else "bold yellow"
            state = Text("±", style=style)
        elif problems(t, self.lib.settings.artwork_min_size):
            state = Text("·", style="red")
        else:
            state = Text("✓", style="green")
        fmt = f"{t.codec} " + ("lossless" if t.lossless else f"{t.bitrate}k")
        return (mark, state, t.get("artist"), t.get("title") or Text(t.filename, style="italic dim"),
                t.get("album"), t.get("tracknumber"), t.get("date")[:4], fmt, t.filename)

    def _cursor_track(self):
        table = self.query_one("#tracks", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self.by_id.get(int(key))

    def selection(self) -> list[int]:
        if self.marked:
            return [t.id for t in self.shown if t.id in self.marked]
        t = self._cursor_track()
        return [t.id] if t else []

    def _update_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        t = self._cursor_track()
        if t is None:
            detail.update("No track selected.\n\nAdd a library folder with F, then scan with S.")
            return
        p = self.lib.db.proposal(t.id)
        tbl = Table.grid(padding=(0, 1))
        tbl.add_column(style="dim", no_wrap=True)
        tbl.add_column()
        for f in tagio.FIELD_NAMES:
            old = t.tags.get(f, "")
            if p and f in p.tags and p.tags[f] != old:
                new = p.tags[f]
                val = Text()
                if old:
                    val.append(old, style="red strike")
                    val.append(" → ")
                val.append(new or "(remove)", style="bold green")
                tbl.add_row(tagio.FIELD_LABELS[f], val)
            elif old:
                tbl.add_row(tagio.FIELD_LABELS[f], old)
        info = Text()
        info.append(f"{t.filename}\n", style="bold")
        info.append(f"{t.folder}\n", style="dim")
        mins, secs = divmod(int(t.duration), 60)
        info.append(f"{t.codec} · {'lossless' if t.lossless else f'{t.bitrate} kbps'} · "
                    f"{t.sample_rate / 1000:g} kHz · {mins}:{secs:02d}\n")
        art = f"artwork {t.art_w}×{t.art_h}" if t.has_art else "no artwork"
        info.append(art)
        if p and p.art:
            _, w, h = tagio.image_info(p.art)
            info.append(f"  → new {w}×{h} ({p.art_source})", style="bold green")
        info.append("\n")
        if t.error:
            info.append(f"\n{t.error}\n", style="bold red")
        probs = problems(t, self.lib.settings.artwork_min_size)
        if probs:
            info.append("Problems: " + ", ".join(probs) + "\n", style="yellow")
        if p:
            col = "green" if p.score >= self.lib.settings.auto_apply_threshold else "yellow"
            info.append(f"\nProposed by {p.source} · confidence {p.score:.0%}\n", style=f"bold {col}")
            if p.note:
                info.append(p.note + "\n", style="italic")
            info.append("a = apply, x = discard\n", style="dim")
        from rich.console import Group
        detail.update(Group(info, Text(""), tbl))

    # ------------------------------------------------------------ events
    @on(ListView.Selected, "#views")
    @on(ListView.Highlighted, "#views")
    def _view_changed(self, event) -> None:
        if event.item is None:
            return
        name = event.item.id.removeprefix("view_")
        if name != self.view_name:
            self.view_name = name
            self.refresh_library()

    @on(Input.Changed, "#search")
    def _search_changed(self) -> None:
        self.refresh_library()

    @on(Input.Submitted, "#search")
    def _search_done(self) -> None:
        self.query_one("#tracks", DataTable).focus()

    @on(DataTable.RowHighlighted, "#tracks")
    def _row(self) -> None:
        self._update_detail()

    @on(DataTable.HeaderSelected, "#tracks")
    def _sort(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key
        rev = getattr(self, "_sort_key", None) == key and not getattr(self, "_sort_rev", False)
        self._sort_key, self._sort_rev = key, rev
        event.data_table.sort(key, key=lambda v: str(v).lower(), reverse=rev)

    # ------------------------------------------------------------ marks
    def action_mark(self) -> None:
        t = self._cursor_track()
        if not t:
            return
        self.marked ^= {t.id}
        table = self.query_one("#tracks", DataTable)
        table.update_cell(str(t.id), "mark", Text("●", style="bold yellow") if t.id in self.marked else "")
        table.action_cursor_down()
        self.query_one("#status", Static).update(f"{len(self.marked)} marked")

    def action_mark_all(self) -> None:
        self.marked = {t.id for t in self.shown}
        self.refresh_library()

    def action_clear_marks(self) -> None:
        self.marked.clear()
        self.refresh_library()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_toggle_log(self) -> None:
        self.query_one("#log", RichLog).toggle_class("visible")

    def log_message(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    def action_cancel(self) -> None:
        self.cancel_task()

    # ------------------------------------------------------------ actions
    def _need_selection(self) -> list[int] | None:
        ids = self.selection()
        if not ids:
            self.notify("No tracks selected", severity="warning")
            return None
        return ids

    def _finish(self, msg: str):
        def done(result) -> None:
            self.notify(msg.format(r=result) if "{" in msg else msg)
            self.query_one("#status", Static).update(msg.format(r=result) if "{" in msg else msg)
            self.refresh_library()
        return done

    @work(thread=True, exclusive=True, group="updates")
    def _check_updates(self) -> None:
        updater.cleanup_previous()
        try:
            upd = updater.check()
        except updater.UpdateError as e:
            self.call_from_thread(self.log_message, f"Update check failed: {e}")
            return
        if upd and upd.version != self.lib.settings.skipped_update:
            self.call_from_thread(self._offer_update, upd)

    def _offer_update(self, upd) -> None:
        if not upd.can_install:
            self.log_message(f"MusicMaid {upd.version} is available (you have {__version__}): {upd.page}")
            self.notify(f"MusicMaid {upd.version} is available. See the log (l) for details.", timeout=8)
            return

        def go(ok: bool | None) -> None:
            if not ok:
                self.lib.settings.skipped_update = upd.version
                save_settings(self.lib.settings)
                self.log_message(f"Skipping {upd.version}. Run 'musicmaid-cli update' to install it later.")
                return

            def done(msg: str) -> None:
                self.exit(message=f"{msg} Start MusicMaid again to use it.")
            self.start_task(f"Downloading MusicMaid {upd.version}…",
                            lambda task: updater.install(upd, task, relaunch=False), done)
        self.push_screen(ConfirmScreen(f"MusicMaid {upd.version} is available (you have {__version__}).\n\n"
                                       f"{upd.notes[:600]}\n\nInstall it now? Cancel skips this version.",
                                       "Install"), go)

    def _offer_fpcalc(self) -> None:
        def go(ok: bool | None) -> None:
            if ok:
                self.start_task("Downloading fpcalc…", download_fpcalc,
                                lambda path: self.notify(f"fpcalc installed: {path}"))
            else:
                self.lib.settings.offer_fpcalc_download = False
                save_settings(self.lib.settings)
                self.log_message("OK, not asking again. Run 'musicmaid-cli fpcalc' any time to download it.")
        self.push_screen(ConfirmScreen(
            "fpcalc (Chromaprint, ~3 MB) is needed to recognise songs by their sound and to find duplicates "
            "that are encoded differently.\n\nDownload it now from the official Chromaprint release on GitHub?",
            "Download"), go)

    def action_scan(self) -> None:
        if not self.lib.folders:
            self.action_folders()
            return
        self.start_task("Scanning…", lambda task: self.lib.scan(task),
                        lambda r: self._finish("Scan: {r[added]} added, {r[updated]} updated, {r[removed]} removed, "
                                               "{r[errors]} errors")(r))

    def _scope(self, verb: str, fn, msg: str) -> None:
        """Run fn on marked tracks, or ask to run it on the whole current view."""
        ids = [t.id for t in self.shown if t.id in self.marked]
        if ids:
            self.start_task(f"{verb}…", lambda task: fn(ids, task), self._finish(msg))
            return
        all_ids = [t.id for t in self.shown]
        if not all_ids:
            return

        def go(ok: bool | None) -> None:
            if ok:
                self.start_task(f"{verb}…", lambda task: fn(all_ids, task), self._finish(msg))
        self.push_screen(ConfirmScreen(f"{verb} all {len(all_ids)} tracks in this view?\n"
                                       "(Mark tracks with space to work on a subset.)", verb), go)

    def action_autotag(self) -> None:
        self._scope("Auto-tag", lambda ids, task: self.lib.auto_tag(ids, task),
                    "Auto-tag: {r[applied]} written, {r[review]} need review, {r[unmatched]} not found")

    def action_identify(self) -> None:
        self._scope("Identify", lambda ids, task: self.lib.identify(ids, task),
                    "Identified {r[matched]} ({r[confident]} confident), {r[unmatched]} not found — see Needs review")

    def action_cleanup(self) -> None:
        self._scope("Clean up", lambda ids, task: self.lib.cleanup(ids, task),
                    "{r} tracks have proposed fixes — see Needs review")

    def action_artwork(self) -> None:
        self._scope("Find artwork", lambda ids, task: self.lib.fetch_artwork(ids, task),
                    "Artwork found for {r} tracks — see Needs review")

    def action_choose_artwork(self) -> None:
        t = self._cursor_track()
        if not t:
            return
        ids = self.selection()

        def chosen(res) -> None:
            if res:
                data, label = res
                self.lib.propose_artwork(ids, data, label)
                self.notify(f"Artwork proposed for {len(ids)} tracks — press a to apply")
                self.refresh_library()
        self.push_screen(ArtworkScreen(self.lib, t), chosen)

    def action_apply(self) -> None:
        ids = [i for i in self.selection() if i in self.pending]
        if not ids and self.view_name == "review" and not self.marked:
            ids = []
        if not ids:
            self.notify("Selected tracks have no pending changes", severity="warning")
            return
        self.start_task("Writing tags…", lambda task: self.lib.apply(ids, task),
                        lambda r: self._finish(f"Wrote {r.written} files ({r.failed} failed). Undo with U.")(r))

    def action_discard(self) -> None:
        ids = [i for i in self.selection() if i in self.pending]
        if ids:
            self.lib.discard(ids)
            self.notify(f"Discarded proposals for {len(ids)} tracks")
            self.refresh_library()

    def action_edit(self) -> None:
        ids = self._need_selection()
        if not ids:
            return
        tracks = self.lib.tracks(ids)

        def save(changes: dict | None) -> None:
            if changes:
                self.start_task("Writing tags…", lambda task: self.lib.edit(ids, changes, task=task),
                                lambda r: self._finish(f"Saved {r.written} files")(r))
        self.push_screen(EditScreen(tracks), save)

    def action_dupes(self) -> None:
        self.push_screen(DuplicatesScreen(self.lib))

    def action_organize(self) -> None:
        ids = [t.id for t in self.shown if t.id in self.marked] or [t.id for t in self.shown]
        if not ids:
            return
        self.push_screen(OrganizeScreen(self.lib, ids))

    def action_undo(self) -> None:
        def chosen(batch: str | None) -> None:
            if batch:
                self.start_task("Undoing…", lambda task: self.lib.undo(batch, task),
                                lambda r: self._finish(f"Undid {r} operations")(r))
        self.push_screen(HistoryScreen(self.lib), chosen)

    def action_folders(self) -> None:
        def closed(changed: bool | None) -> None:
            if changed:
                self.action_scan()
        self.push_screen(FoldersScreen(self.lib), closed)

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self.lib.settings), lambda ok: ok and self.notify("Settings saved"))


def main() -> None:
    MusicMaidTUI().run()


if __name__ == "__main__":
    main()
