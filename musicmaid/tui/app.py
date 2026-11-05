"""MusicMaid terminal UI (Textual)."""
from __future__ import annotations

import os

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    DataTable, Footer, Header, Input, Label, ListItem, ListView, ProgressBar, RichLog, Static, Tree,
)

from .. import APP_NAME, __version__
from .. import tags as tagio
from ..cleanup import fixable, problems
from ..config import save_settings
from ..fingerprint import can_download_fpcalc, download_fpcalc, find_fpcalc
from .. import foldertree, updater
from ..library import VIEWS, Library
from .screens import (
    ArtworkScreen, ConfirmScreen, DuplicatesScreen, EditScreen, FoldersScreen, HistoryScreen, InputScreen,
    OrganizeScreen, SettingsScreen, TaskMixin,
)

MAX_ROWS = 1500      # rows put in the track table at once (the folder tree and search narrow bigger lists)

KEYS_HELP = (
    "space  mark track     ctrl+a mark all\n/      search         enter  open folder\nt      auto-tag       "
    "i      identify\nc      clean up tags  w / W  artwork auto/pick\ne      edit tags      a / x  apply / discard\n"
    "p      tags from folder names       k  split CUE sheets\ny / Y  copy file / folder path\n"
    "d      duplicates     o      organize files\nu      undo           f      library folders\n,      settings  "
    "     l      show log\nctrl+x cancel task    ?      this help"
)

CSS = """
#sidebar { width: 32; border-right: solid $primary-darken-2; }
#sidebar ListView { height: auto; }
#tree { height: 1fr; padding: 0 0; }
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
.dialog-scroll { height: auto; max-height: 28; }
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
        Binding("f", "folders", "Library folders"),
        Binding("comma", "settings", "Settings"),
        Binding("l", "toggle_log", "Log", show=False),
        Binding("ctrl+x", "cancel", "Cancel task", show=False),
        Binding("question_mark", "keys", "Keys"),
        Binding("p", "pathtags", "Tags from folders", show=False),
        Binding("k", "split_cue", "Split CUE", show=False),
        Binding("y", "copy_path", "Copy path", show=False),
        Binding("Y", "copy_folder", "Copy folder", show=False),
    ]

    def __init__(self, lib: Library | None = None):
        super().__init__()
        self.lib = lib or Library()
        self.view_name = "all"
        self.marked: set[int] = set()
        self.shown = []
        self.by_id = {}
        self.pending: dict[int, tuple[str, float, bool]] = {}
        self.folder: str | None = None          # folder shown now (None = all folders)
        self.folder_choice: str | None = None   # folder the user picked; kept while a view hides it
        self._tree_filled = False

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
                yield Label("FOLDERS  (enter to open)", classes="side-title")
                yield Tree("All folders", data="", id="tree")
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
        if not self.lib.settings.acoustid_key:
            self.log_message("No AcoustID key: songs are identified from tags and file names only. Add a free key "
                             "in Settings (,) to also recognise untagged or wrongly tagged files by their sound.")
            if self.lib.settings.offer_acoustid_key:
                self.call_after_refresh(self._offer_acoustid)

    # ------------------------------------------------------------ data
    def refresh_library(self) -> None:
        counts = self.lib.counts()
        for key, label in VIEWS.items():
            self.query_one(f"#lbl_{key}", Label).update(f"{label} ({counts.get(key, 0)})")
        self.pending = self.lib.db.proposal_summary()
        search = self.query_one("#search", Input).value
        in_view = self.lib.view(self.view_name, search)
        self._fill_tree(in_view)
        self._show_tracks(in_view, counts)

    def _show_tracks(self, in_view, counts=None) -> None:
        counts = counts or self.lib.counts()
        self._in_view = in_view
        order = self.lib.sort_keys()
        self.shown = foldertree.in_folder(in_view, self.folder)
        self.shown.sort(key=lambda t: order.get(t.id) or foldertree.album_order(t))
        self.by_id = {t.id: t for t in self.shown}
        self.marked &= set(self.by_id)
        table = self.query_one("#tracks", DataTable)
        row = table.cursor_row
        table.clear()
        # a terminal table can't show tens of thousands of rows quickly; folders and search narrow it down
        listed = self.shown[:MAX_ROWS]
        for t in listed:
            table.add_row(*self._cells(t), key=str(t.id))
        if listed:
            table.move_cursor(row=min(row, len(listed) - 1))
        more = (f"showing the first {len(listed):,} of {len(self.shown):,} - open a folder or search (/) to narrow"
                if len(self.shown) > len(listed) else f"{len(self.shown):,} tracks")
        self.query_one("#status", Static).update(
            f"{more} · {len(self.marked)} marked · {counts['review']} with changes to review")
        self._update_detail()

    def _cells(self, t):
        mark = Text("●", style="bold yellow") if t.id in self.marked else ""
        if t.error:
            state = Text("!", style="bold red")
        elif t.id in self.pending:
            src, score, _ = self.pending[t.id]
            style = "bold green" if score >= self.lib.settings.auto_apply_threshold else "bold yellow"
            state = Text("±", style=style)
        elif self.lib.problems_of(t):
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
            detail.update("No track selected.\n\nAdd a library folder with F, then scan with S.\n\n" + KEYS_HELP)
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
        probs = self.lib.problems_of(t)
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

    # ------------------------------------------------------------ folder tree
    def _fill_tree(self, tracks) -> None:
        """Rebuild the folder tree for this view (and search), keeping what was expanded and chosen."""
        tree = self.query_one("#tree", Tree)
        expanded = set()
        stack = list(tree.root.children)
        while stack:
            n = stack.pop()
            if n.is_expanded:
                expanded.add(n.data)
            stack.extend(n.children)
        first = not self._tree_filled
        self._tree_filled = True
        min_art = self.lib.settings.artwork_min_size
        nodes = foldertree.build(tracks, self.lib.folders, self.lib.needs_fixing)
        tree.clear()
        tree.root.set_label(f"All folders ({len(tracks)})")
        tree.root.data = ""
        by_path = {}

        def add(parent, node, depth):
            label = Text(f"{node.name} ({node.count})")
            if node.flagged:
                label.append(f" ⚠{node.flagged}", style="bold red")
                label.stylize("red", 0, len(node.name))
            item = parent.add(label, data=node.path,
                              expand=node.path in expanded or (first and depth == 0),
                              allow_expand=bool(node.children))
            by_path[node.path] = item
            for c in node.children:
                add(item, c, depth + 1)
        for n in nodes:
            add(tree.root, n, 0)
        tree.root.expand()
        current = tree.root
        if self.folder_choice:
            from pathlib import Path
            for cand in (self.folder_choice, *map(str, Path(self.folder_choice).parents)):
                if cand in by_path:
                    current = by_path[cand]
                    break
        self.folder = current.data or None
        p = current.parent
        while p is not None:
            p.expand()
            p = p.parent
        self.call_after_refresh(tree.move_cursor, current)

    @on(Tree.NodeSelected, "#tree")
    def _folder_selected(self, event: Tree.NodeSelected) -> None:
        self.folder = self.folder_choice = event.node.data or None
        self._show_tracks(getattr(self, "_in_view", []))

    def action_keys(self) -> None:
        self.notify(KEYS_HELP, title="Keys", timeout=20)

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

    def _offer_acoustid(self) -> None:
        from ..guidance import ACOUSTID_INTRO, ACOUSTID_PRIVACY, ACOUSTID_WITH, ACOUSTID_WITHOUT

        def got_key(key: str | None) -> None:
            if key and key.strip():
                self._check_acoustid_key(key.strip())

        def go(ok: bool | None) -> None:
            if ok:
                self.push_screen(InputScreen("AcoustID API key", "", "paste the API key of your application"),
                                 got_key)
            else:
                self.lib.settings.offer_acoustid_key = False
                save_settings(self.lib.settings)
                self.log_message("Continuing without AcoustID. You can add a key any time in Settings (,).")
        self.push_screen(ConfirmScreen("\n\n".join([ACOUSTID_INTRO, ACOUSTID_WITH, ACOUSTID_WITHOUT,
                                                     ACOUSTID_PRIVACY + " Cancel continues without a key."]),
                                       "Add a key"), go)

    @work(thread=True, exclusive=True, group="acoustid")
    def _check_acoustid_key(self, key: str) -> None:
        from ..providers.acoustid import check_key
        ok = check_key(key)
        self.call_from_thread(self._acoustid_checked, key, ok)

    def _acoustid_checked(self, key: str, ok: bool | None) -> None:
        if ok is False:
            self.notify("AcoustID didn't accept that key. Check you copied the API key.", severity="error")
            self._offer_acoustid()
            return
        s = self.lib.settings
        s.acoustid_api_key, s.offer_acoustid_key = key, False
        save_settings(s)
        self.notify("AcoustID key saved: songs will also be identified by their sound."
                    + ("" if ok else " (Couldn't verify it right now.)"))

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
        where = f"in {os.path.basename(self.folder)}" if self.folder else "in this view"
        self.push_screen(ConfirmScreen(f"{verb} all {len(all_ids)} tracks {where}?\n"
                                       "(Mark tracks with space to work on a subset.)", verb), go)

    def action_autotag(self) -> None:
        self._scope("Auto-tag", lambda ids, task: self.lib.auto_tag(ids, task),
                    "Auto-tag: {r[applied]} written, {r[review]} need review, {r[unmatched]} not found")

    def action_identify(self) -> None:
        self._scope("Identify", lambda ids, task: self.lib.identify(ids, task),
                    "Identified {r[matched]} ({r[confident]} confident), {r[unmatched]} not found — see Changes to review")

    def action_cleanup(self) -> None:
        self._scope("Clean up", lambda ids, task: self.lib.cleanup(ids, task),
                    "{r} tracks have proposed fixes — see Changes to review")

    def action_artwork(self) -> None:
        self._scope("Find artwork", lambda ids, task: self.lib.fetch_artwork(ids, task),
                    "Artwork found for {r} tracks — see Changes to review")

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
        from .. import tags as tagio
        lines, n = [], 0
        for t in self.lib.tracks(ids):
            p = self.lib.db.proposal(t.id)
            if not p:
                continue
            ch = [(f, t.tags.get(f, ""), v) for f, v in p.tags.items() if (v or "") != (t.tags.get(f) or "")]
            n += len(ch) + (p.art is not None)
            if len(lines) < 40:
                lines.append(f"{t.filename}")
                lines += [f"   {tagio.FIELD_LABELS.get(f, f)}: {old or '(empty)'} → {new or '(remove)'}"
                          for f, old, new in ch[:8]]
                if p.art is not None:
                    lines.append("   Cover art: " + ("replace" if t.has_art else "add"))
        if len(lines) >= 40:
            lines.append("   …")

        def go(ok: bool | None) -> None:
            if ok:
                self.start_task("Writing tags…", lambda task: self.lib.apply(ids, task),
                                lambda r: self._finish(f"Wrote {r.written} files ({r.failed} failed). Undo with U.")(r))
        self.push_screen(ConfirmScreen(f"Write {n} change(s) to {len(ids)} file(s)?\n\n" + "\n".join(lines)
                                       + "\n\nEverything written can be undone with U.", "Write changes"), go)

    def action_pathtags(self) -> None:
        from .. import pathtags

        def got(pattern: str | None) -> None:
            if pattern is None:
                return
            pattern = pattern.strip()
            if pattern:
                try:
                    pathtags.compile_pattern(pattern)
                except ValueError as e:
                    self.notify(f"Pattern problem: {e}", severity="error")
                    return
            self._scope("Tags from folder names",
                        lambda ids, task: self.lib.tags_from_paths(ids, task, pattern=pattern or None),
                        "Folder names: changes proposed for {r} tracks. Review, then apply with A.")
        self.push_screen(InputScreen("Tags from folder names: pattern, or leave empty for automatic",
                                     "", pathtags.EXAMPLES[1]), got)

    def action_split_cue(self) -> None:
        from .. import cuesplit
        sheets = [s for s in self.lib.cue_sheets(self.folder) if s.splittable]
        ready = []
        for s in sheets:
            try:
                if not cuesplit.already_split(cuesplit.plan(s)):
                    ready.append(s)
            except cuesplit.CueError:
                pass
        where = os.path.basename(self.folder) if self.folder else "the library"
        if not ready:
            self.notify(f"No CUE sheets to split in {where}.")
            return
        if not cuesplit.find_ffmpeg():
            self.notify("ffmpeg is needed to split CUE sheets. " + cuesplit.ffmpeg_help(), severity="error",
                        timeout=12)
            return

        def go(ok: bool | None) -> None:
            if ok:
                self.start_task("Splitting CUE sheets…", lambda task: self.lib.split_cues(ready, task),
                                lambda r: self._finish(f"Split into {r[0]} tracks ({r[1]} failed). Undo with U.")(r))
        names = "\n".join(f"  {os.path.relpath(s.path, self.folder or os.path.dirname(s.path))}" for s in ready[:15])
        self.push_screen(ConfirmScreen(f"Split {len(ready)} CUE sheet(s) in {where} into separate tracks?\n\n"
                                       f"{names}\n\nThe big files and .cue sheets go to the quarantine folder "
                                       "(undo with U).", "Split"), go)

    def action_copy_path(self) -> None:
        t = self._cursor_track()
        if t:
            self.copy_to_clipboard(t.path)
            self.notify(f"Copied: {t.path}")

    def action_copy_folder(self) -> None:
        t = self._cursor_track()
        path = t.folder if t else self.folder
        if path:
            self.copy_to_clipboard(path)
            self.notify(f"Copied: {path}")

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
    import sys
    sys.setswitchinterval(0.0003)     # keep the screen responsive while a background task is busy
    MusicMaidTUI().run()


if __name__ == "__main__":
    main()
