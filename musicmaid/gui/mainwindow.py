"""MusicMaid desktop GUI (Qt / PySide6) for Linux and Windows."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDockWidget, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QStyle, QTableView, QToolBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from .. import tags as tagio
from ..cleanup import fixable, problems
from ..db import Track
from ..config import save_settings
from ..fingerprint import can_download_fpcalc, download_fpcalc, find_fpcalc
from ..library import VIEWS, Library
from .dialogs import AcoustIDDialog, ArtworkDialog, DuplicatesDialog, HistoryDialog, OrganizeDialog, SettingsDialog
from .. import foldertree, updater
from . import skins
from .workers import TaskRunner, background

COLUMNS = [
    ("state", "Status"), ("problems", "Problems"), ("artist", "Artist"), ("title", "Title"), ("album", "Album"), ("albumartist", "Album Artist"),
    ("tracknumber", "#"), ("date", "Year"), ("genre", "Genre"), ("format", "Format"), ("duration", "Length"),
    ("path", "File"),
]
# status colours: replaced by the skin's good/warn/bad colours when a skin is applied
GREEN = QColor(46, 160, 67)
AMBER = QColor(210, 153, 34)
RED = QColor(218, 54, 51)
DIM = QColor(140, 140, 140)


def _set_status_colors(name: str) -> None:
    c = skins.colors(name)
    GREEN.setRgb(QColor(c.get("good", "#2ea043")).rgb())
    AMBER.setRgb(QColor(c.get("warn", "#d29922")).rgb())
    RED.setRgb(QColor(c.get("bad", "#da3633")).rgb())
    DIM.setRgb(QColor(c.get("dim", "#8c8c8c")).rgb())


# ---------------------------------------------------------------- table model
class TrackModel(QAbstractTableModel):
    def __init__(self, lib: Library):
        super().__init__()
        self.lib = lib
        self.tracks: list[Track] = []
        self.pending: dict[int, tuple[str, float, bool]] = {}

    def set_tracks(self, tracks: list[Track]) -> None:
        self.beginResetModel()
        self.tracks = tracks
        self.pending = self.lib.db.proposal_summary()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.tracks)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][1]
        return None

    def _state(self, t: Track) -> tuple[str, QColor | None, str]:
        if t.error:
            return "Error", RED, f"Can't read this file: {t.error}"
        if t.id in self.pending:
            src, score, art = self.pending[t.id]
            return "New", GREEN, (f"New values from {src} ({score:.0%} sure) - select the track to compare "
                                  "Original and New, then Apply or Discard")
        probs = problems(t, self.lib.settings.artwork_min_size)
        if probs and probs[0].startswith("whole album"):
            return "CUE", AMBER, "This one file holds a whole album: select its folder and use Split CUE"
        if fixable(probs):
            return "Fix", RED, "Needs fixing: " + ", ".join(probs)
        if probs:
            return "OK", GREEN, "Tags look fine. Note: " + ", ".join(probs)
        return "OK", GREEN, "Tags look complete"

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        t = self.tracks[index.row()]
        key = COLUMNS[index.column()][0]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if key == "state":
                return self._state(t)[0]
            if key == "problems":
                return ", ".join(problems(t, self.lib.settings.artwork_min_size))
            if key in ("artist", "album") and not t.get(key) and not t.error:
                return "missing"
            if key == "format":
                return f"{t.codec} " + ("lossless" if t.lossless else f"{t.bitrate}k")
            if key == "duration":
                m, s = divmod(int(t.duration), 60)
                return f"{m}:{s:02d}"
            if key == "path":
                return t.path
            if key == "date":
                return t.get("date")[:4]
            if key == "title" and not t.get("title"):
                return t.filename
            return t.get(key)
        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "state":
                return QBrush(self._state(t)[1])
            if key == "problems":
                probs = problems(t, self.lib.settings.artwork_min_size)
                return QBrush(RED if fixable(probs) else AMBER)
            if key in ("artist", "album") and not t.get(key):
                return QBrush(RED)
            if key == "title" and not t.get("title"):
                return QBrush(RED)
        if role == Qt.ItemDataRole.FontRole and (key == "state" or (key in ("artist", "album", "title")
                                                                      and not t.get(key))):
            f = QFont()
            if key == "state":
                f.setBold(True)
            else:
                f.setItalic(True)
            return f
        if role == Qt.ItemDataRole.ToolTipRole and key in ("state", "problems"):
            return self._state(t)[2]
        if role == Qt.ItemDataRole.UserRole:  # sort key
            if key == "tracknumber":
                try:
                    return int(t.get("tracknumber") or 0)
                except ValueError:
                    return 0
            if key == "duration":
                return t.duration
            return str(self.data(index)).lower()
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("state", "tracknumber", "duration"):
            return Qt.AlignmentFlag.AlignCenter
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.terms: list[str] = []
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_search(self, text: str) -> None:
        self.terms = text.lower().split()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:
        if not self.terms:
            return True
        t = self.sourceModel().tracks[row]
        hay = (t.path + " " + " ".join(t.tags.values())).lower()
        return all(term in hay for term in self.terms)


# ---------------------------------------------------------------- details panel
# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, lib: Library | None = None):
        super().__init__()
        self.lib = lib or Library()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        self.view_name = "all"
        self.runner = TaskRunner(self)
        self.runner.progress.connect(self._progress)
        self.runner.log.connect(self._log)
        self.runner.busy_changed.connect(self._busy)

        # sidebar: the views (what to show) above the folder tree (where)
        self.views = QListWidget()
        for key, label in VIEWS.items():
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.views.addItem(it)
        self.views.setCurrentRow(0)
        self.views.currentItemChanged.connect(self._view_changed)
        self.views.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fit_views()
        self.folder = None                       # folder shown now (None = everything)
        self.folder_choice = None                # folder the user picked; kept while a view hides it
        self._view_tracks: list = []
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._folder_changed)
        sidebar = QWidget()
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(4)
        sl.addWidget(self.views)
        folders_lbl = QLabel("Folders")
        folders_lbl.setObjectName("dim")
        sl.addWidget(folders_lbl)
        sl.addWidget(self.tree, 1)
        sidebar.setMinimumWidth(180)

        # track table
        self.model = TrackModel(self.lib)
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setWordWrap(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        for i, w in enumerate([58, 170, 160, 210, 170, 130, 40, 50, 90, 100, 55]):
            self.table.setColumnWidth(i, w)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._sel_timer.start())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self._sel_timer = QTimer(self, singleShot=True, interval=120)
        self._sel_timer.timeout.connect(self._selection_changed)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search artist, title, album, path…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_search)

        # banner shown while proposed changes are waiting
        self.banner = QFrame()
        self.banner.setObjectName("panel")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(8, 4, 8, 4)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.b_review = QPushButton("Review Album by Album…")
        self.b_review.setObjectName("primary")
        self.b_review.clicked.connect(lambda: self.review())
        self.b_discard_all = QPushButton("Discard All…")
        self.b_discard_all.clicked.connect(self.discard_all)
        bl.addWidget(self.banner_text, 1)
        for b in (self.b_review, self.b_discard_all):
            bl.addWidget(b)
        self.banner.hide()

        # the real files of the chosen folder, under the track list
        from .filespanel import FilesPanel
        self.files = FilesPanel()
        self.files.file_clicked.connect(self._select_track_by_path)
        self.files.status.connect(lambda m: self.status.setText(m))
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.addWidget(self.table)
        self.vsplit.addWidget(self.files)
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 1)
        self.vsplit.setSizes([420, 200])

        table_page = QWidget()
        cl = QVBoxLayout(table_page)
        cl.setContentsMargins(0, 0, 0, 0)
        self.sel_bar = QToolBar("Selected tracks")
        self.sel_bar.setObjectName("selection-bar")
        cl.addWidget(self.search)
        cl.addWidget(self.sel_bar)
        cl.addWidget(self.banner)
        cl.addWidget(self.vsplit, 1)

        # first start: a welcome page instead of an empty table
        welcome = QWidget()
        wl = QVBoxLayout(welcome)
        wl.addStretch(1)
        title = QLabel(f"<h2>Welcome to {APP_NAME}</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        steps = QLabel(
            "<p>Two ways to tidy up your music:</p>"
            "<p><b>Fix everything at once:</b> add your music folder, click <b>Fix Whole Library</b>, then go "
            "through the suggested changes album by album and click <b>Apply</b> on the ones you like.</p>"
            "<p><b>Fix a few tracks by hand:</b> select them in the list, click <b>Look Up Tags</b> or "
            "<b>Find Artwork</b>, compare <i>Original</i> and <i>New</i> on the right (you can type in New "
            "too), then click <b>Apply</b>. Only the selected tracks change.</p>"
            "<p><b>Rename &amp; Organize</b> then names files and folders from their tags. Nothing on disk "
            "changes until you apply it, and every change can be undone.</p>")
        steps.setWordWrap(True)
        steps.setFixedWidth(560)
        steps.setMinimumHeight(steps.heightForWidth(560) + 40)
        add_btn = QPushButton("Add Music Folder…")
        add_btn.setObjectName("primary")
        add_btn.setMinimumHeight(36)
        add_btn.clicked.connect(self.add_folder)
        wl.addWidget(title)
        wl.addWidget(steps, 0, Qt.AlignmentFlag.AlignHCenter)
        wl.addSpacing(12)
        wl.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        wl.addStretch(2)

        from PySide6.QtWidgets import QStackedWidget
        center = QStackedWidget()
        center.addWidget(welcome)
        center.addWidget(table_page)
        self.center = center

        from .compare import ComparePanel
        self.detail = ComparePanel(self)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(self.detail)
        detail_scroll.setMinimumWidth(320)
        self.detail_scroll = detail_scroll

        split = QSplitter()
        split.addWidget(sidebar)
        split.addWidget(center)
        split.addWidget(detail_scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 900, 370])
        self.split = split
        self.setCentralWidget(split)

        # log dock
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_dock = QDockWidget("Log", self)
        self.log_dock.setWidget(self.log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

        # status bar
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setVisible(False)
        self.status = QLabel()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.runner.cancel)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)

        self._build_actions()
        self._restore_state()
        self._album_order()
        self.reload()
        QTimer.singleShot(200, self._first_run)

    # ------------------------------------------------------------ setup
    def _act(self, text, slot, shortcut=None, icon=None, tip=None) -> QAction:
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.triggered.connect(slot)
        return a

    def _build_actions(self) -> None:
        P = QStyle.StandardPixmap
        self.a_add = self._act("Add Folder…", self.add_folder, "Ctrl+O", P.SP_DirOpenIcon, "Add a music folder to the library")
        self.a_scan = self._act("Rescan", self.scan, "F5", P.SP_BrowserReload,
                                "Look for new, changed and deleted files in your library folders")
        # --- work on the selected tracks (the bar above the track list)
        self.a_ident = self._act("Look Up Tags", self.identify, "Ctrl+I", P.SP_FileDialogContentsView,
                                 "Look up the selected tracks on MusicBrainz (and AcoustID) - shows the result in "
                                 "the New column; nothing is written until you click Apply")
        self.a_art = self._act("Find Artwork", self.fetch_artwork, "Ctrl+K", P.SP_DesktopIcon,
                               "Find cover art for the selected tracks (Cover Art Archive, iTunes, Deezer)")
        self.a_choose_art = self._act("Pick Artwork…", self.choose_artwork, "Ctrl+Shift+K", P.SP_DesktopIcon,
                                      "Choose a cover yourself from several online results")
        self.a_clean = self._act("Clean Up", self.cleanup, "Ctrl+L", P.SP_DialogResetButton,
                                 "Fix capitals and junk text, fill empty tags from file names")
        self.a_paths = self._act("From Folders…", self.tags_from_paths, "Ctrl+Shift+F", P.SP_DirIcon,
                                 "Fill in tags from the folder structure, e.g. Artist/Album (Year)/01 - Title")
        self.a_apply = self._act("Apply", self.apply, "Ctrl+Return", P.SP_DialogApplyButton,
                                 "Write the New values of the selected tracks to their files (undoable)")
        self.a_discard = self._act("Discard", self.discard, "Ctrl+Backspace", P.SP_DialogDiscardButton,
                                   "Forget the New values of the selected tracks (files aren't touched)")
        # --- work on the whole library (the main toolbar)
        self.a_fix = self._act("Fix Whole Library…", self.fix_library, "Ctrl+T", P.SP_MediaPlay,
                               "Look up tags and artwork for all your music, then review the changes album by album")
        self.a_review = self._act("Review Changes", lambda: self.review(), "Ctrl+R", P.SP_FileDialogListView,
                                  "Go through all waiting changes one album (or folder) at a time")
        self.a_dupes = self._act("Duplicates", self.duplicates, "Ctrl+D", P.SP_FileDialogDetailedView,
                                 "Find duplicate songs (identical files, same audio, same tags)")
        self.a_cue = self._act("Split CUE", self.split_cue, None, P.SP_MediaSeekForward,
                               "Split albums stored as one big file + .cue sheet into separate tagged tracks")
        self.a_org = self._act("Rename && Organize", self.organize, "Ctrl+Shift+R", P.SP_DirIcon,
                               "Rename files and folders from their tags and sort them into a tidy folder structure")
        self.a_undo = self._act("Undo / History…", self.undo, "Ctrl+Z", P.SP_ArrowBack,
                                "See every change made and put things back (one change, or everything since a "
                                "point in time)")
        self.a_settings = self._act("Settings", self.settings_dialog, "Ctrl+,", P.SP_FileDialogInfoView)
        self.a_log = self._act("Show Log", lambda: self.log_dock.setVisible(not self.log_dock.isVisible()),
                               "Ctrl+Shift+L")
        self.a_select_all = self._act("Select All", self.table.selectAll, "Ctrl+A")
        self.a_files = self._act("Show Files Panel", lambda on: self.files.setVisible(on), "F6", None,
                                 "Show every file in the chosen folder (covers, .cue, .log, …) under the track list")
        self.a_files.setCheckable(True)
        self.a_files.setChecked(True)

        tb = QToolBar("Library")
        tb.setObjectName("main-toolbar")
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        for a in (self.a_add, self.a_scan, None, self.a_fix, self.a_review, None, self.a_dupes, self.a_cue,
                  self.a_org, None, self.a_undo, self.a_settings):
            tb.addSeparator() if a is None else tb.addAction(a)
        self.addToolBar(tb)

        sb = self.sel_bar
        sb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        lbl = QLabel(" Selected: ")
        lbl.setObjectName("dim")
        sb.addWidget(lbl)
        # Apply / Discard and the artwork picker live under the Original | New comparison on the right
        self.a_select_here = self._act("Select All", self.table.selectAll, None, None,
                                       "Select every track in the list (Ctrl+A)")
        for a in (self.a_select_here, None, self.a_ident, self.a_art, self.a_clean, self.a_paths):
            sb.addSeparator() if a is None else sb.addAction(a)
        from PySide6.QtWidgets import QToolButton
        for b in sb.findChildren(QToolButton):
            b.setAutoRaise(False)            # look like buttons, not plain text

        m = self.menuBar()
        f = m.addMenu("&File")
        for a in (self.a_add, self.a_scan, self.a_settings):
            f.addAction(a)
        f.addSeparator()
        f.addAction(self._act("Quit", self.close, "Ctrl+Q"))
        t = m.addMenu("&Selected Tracks")
        for a in (self.a_ident, self.a_art, self.a_choose_art, self.a_clean, self.a_paths, None,
                  self.a_apply, self.a_discard, None, self.a_select_all):
            t.addSeparator() if a is None else t.addAction(a)
        lib_menu = m.addMenu("&Library")
        for a in (self.a_fix, self.a_review, None, self.a_dupes, self.a_cue, self.a_org, None, self.a_undo):
            lib_menu.addSeparator() if a is None else lib_menu.addAction(a)
        v = m.addMenu("&View")
        v.addAction(self.a_files)
        v.addAction(self.a_log)
        v.addSeparator()
        self.skin_menu = v.addMenu("&Skin")
        self.fill_skin_menu()
        h = m.addMenu("&Help")
        h.addAction(self._act("Check for Updates…", lambda: self.check_updates(manual=True)))
        h.addAction(self._act("Identify by Sound (AcoustID Key)…", lambda: self.acoustid_key(first_run=False)))
        h.addAction(self._act("Download fpcalc (Chromaprint)…", self.get_fpcalc))
        h.addAction(self._act("About", self._about))

    def _restore_state(self) -> None:
        qs = QSettings(APP_NAME, APP_NAME)
        geo = qs.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        hdr = qs.value("header")
        if hdr is not None:
            self.table.horizontalHeader().restoreState(hdr)
        sp = qs.value("splitter")
        if sp is not None:
            self.split.restoreState(sp)
        vs = qs.value("files_split")
        if vs is not None:
            self.vsplit.restoreState(vs)
        show_files = str(qs.value("files_panel", "true")).lower() != "false"
        self.a_files.setChecked(show_files)
        self.files.setVisible(show_files)
        self.folder_choice = qs.value("folder") or None

    def closeEvent(self, e) -> None:
        if self.runner.busy:
            if QMessageBox.question(self, "Quit", "A task is still running. Cancel it and quit?") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.runner.cancel()
        qs = QSettings(APP_NAME, APP_NAME)
        qs.setValue("geometry", self.saveGeometry())
        qs.setValue("header", self.table.horizontalHeader().saveState())
        qs.setValue("splitter", self.split.saveState())
        qs.setValue("files_split", self.vsplit.saveState())
        qs.setValue("files_panel", "true" if self.a_files.isChecked() else "false")
        qs.setValue("folder", self.folder_choice or "")
        super().closeEvent(e)

    def _first_run(self) -> None:
        updater.cleanup_previous()
        if self.lib.settings.check_for_updates:
            self.check_updates(manual=False)
        # no pop-ups at start: the welcome page explains the first step, and the optional extras
        # (fpcalc, AcoustID key) are offered when they'd actually help (see _offer_sound_id)
        if not find_fpcalc():
            self._log("fpcalc (Chromaprint) isn't installed: recognising songs by sound and finding re-encoded "
                      "duplicates are off. Settings → Tools can download it.")
        if not self.lib.settings.acoustid_key:
            self._log("No AcoustID key: songs are recognised from their tags and file names only.")
        for err in self.lib.recorder.errors:
            self._log(err)

    def _offer_sound_id(self, unmatched: int) -> None:
        """Some tracks weren't found from their tags/names: offer recognising them by sound, once."""
        s = self.lib.settings
        if not unmatched or not s.offer_acoustid_key or (s.acoustid_key and find_fpcalc()):
            return
        if not find_fpcalc() and can_download_fpcalc() and s.offer_fpcalc_download:
            self._offer_fpcalc()
        if not s.acoustid_key:
            self.acoustid_key(first_run=True)

    def acoustid_key(self, first_run: bool) -> None:
        had = bool(self.lib.settings.acoustid_key)
        AcoustIDDialog(self.lib, self, first_run=first_run).exec()
        has = bool(self.lib.settings.acoustid_key)
        if has and not had:
            self._log("AcoustID key saved: songs will also be identified by their sound.")
            if not find_fpcalc():
                self._log("Note: identifying by sound also needs fpcalc (Help → Download fpcalc).")
        elif had and not has:
            self._log("AcoustID key removed: songs are identified from tags and file names only.")

    # ------------------------------------------------------------ skins
    def fill_skin_menu(self) -> None:
        """View ▸ Skin: System, the built-in skins, then skins from skin files (refilled after an import)."""
        from PySide6.QtGui import QActionGroup
        self.skin_menu.clear()
        self.skin_group = QActionGroup(self)
        separated = False
        current = self.lib.settings.skin or skins.DEFAULT_SKIN
        for name in skins.theme_names():
            if name not in skins.BUILTIN_SKINS and name != skins.SYSTEM and not separated:
                self.skin_menu.addSeparator()
                separated = True
            a = QAction(name, self, checkable=True)
            a.setChecked(name == current)
            a.triggered.connect(lambda _=False, n=name: self.set_skin(n))
            self.skin_group.addAction(a)
            self.skin_menu.addAction(a)
        self.skin_menu.addSeparator()
        self.skin_menu.addAction(self._act("Import Skin…", self.import_skin))

    def apply_skin(self, name: str) -> str:
        """Show a skin without saving it (also used for live preview in Settings)."""
        name = skins.apply(name)
        _set_status_colors(name)
        self.views.ensurePolished()
        QTimer.singleShot(0, self._fit_views)   # after Qt re-polishes with the new style sheet
        self.table.viewport().update()
        self.detail.show_tracks(self.detail.tracks)   # re-tint proposed-change fields
        for a in self.skin_group.actions():
            a.setChecked(a.text() == name)
        return name

    def _fit_views(self) -> None:
        """Size the views list to show every view without scrolling (row height depends on the skin)."""
        self.views.doItemsLayout()
        rows = sum(self.views.visualItemRect(self.views.item(i)).height() or self.views.sizeHintForRow(i)
                   for i in range(self.views.count()))
        self.views.setFixedHeight(rows + 2 * self.views.frameWidth() + 2)

    def set_skin(self, name: str) -> None:
        self.lib.settings.skin = self.apply_skin(name)
        save_settings(self.lib.settings)

    def import_skin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import skin", str(Path.home()), "Skins (*.json)")
        if not path:
            return
        try:
            name = skins.import_skin(path)
        except ValueError as e:
            QMessageBox.warning(self, "Import skin", f"That isn't a skin MusicMaid can use: {e}")
            return
        self.fill_skin_menu()
        self.set_skin(name)
        self._log(f"Imported the skin \"{name}\".")

    # ------------------------------------------------------------ updates
    def check_updates(self, manual: bool) -> None:
        def done(upd, error) -> None:
            if error:
                self._log(f"Update check failed: {error}")
                if manual:
                    QMessageBox.warning(self, APP_NAME, f"Couldn't check for updates:\n{error}")
            elif upd is None:
                if manual:
                    QMessageBox.information(self, APP_NAME, f"You're running the latest version ({__version__}).")
            elif manual or upd.version != self.lib.settings.skipped_update:
                self._offer_update(upd)
        if manual:
            self.status.setText("Checking for updates…")
        background(updater.check, done)

    def _offer_update(self, upd: "updater.Update") -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        box = QMessageBox(QMessageBox.Icon.Information, f"{APP_NAME} update",
                          f"<b>{APP_NAME} {upd.version}</b> is available. You have {__version__}.", parent=self)
        if upd.notes:
            box.setDetailedText(upd.notes)
        if upd.can_install:
            size = f" ({upd.size / 1e6:.0f} MB)" if upd.size else ""
            box.setInformativeText(f"Install it now{size}? {APP_NAME} will restart. Your library and settings are kept.")
            go = box.addButton("Install and Restart", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setInformativeText("This copy can't update itself (it runs from Python). Get the new version "
                                   "from the download page, or update with pip or git.")
            go = box.addButton("Open Download Page", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip This Version", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skip:
            self.lib.settings.skipped_update = upd.version
            save_settings(self.lib.settings)
        elif clicked is go and not upd.can_install:
            QDesktopServices.openUrl(QUrl(upd.page))
        elif clicked is go:
            if self.runner.busy:
                QMessageBox.information(self, APP_NAME, "Please wait for the current task to finish (or cancel "
                                        "it), then choose Help → Check for Updates.")
                return

            def installed(msg: str) -> None:
                self._log(msg)
                self.close()

            def failed(err: str) -> None:
                QMessageBox.warning(self, APP_NAME, f"The update wasn't installed:\n{err}\n\n"
                                    f"You can download it from {upd.page}")
            self.runner.run(f"Downloading {APP_NAME} {upd.version}…", lambda task: updater.install(upd, task),
                            installed, failed)

    def _offer_fpcalc(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Question, APP_NAME,
                          "MusicMaid needs Chromaprint's small fpcalc program (about 3 MB) to recognise songs by "
                          "their sound and to find duplicates that are encoded differently.\n\n"
                          "Download it now from the official Chromaprint release on GitHub?", parent=self)
        yes = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        never = box.addButton("Don't ask again", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is yes:
            self.get_fpcalc()
        elif box.clickedButton() is never:
            self.lib.settings.offer_fpcalc_download = False
            save_settings(self.lib.settings)

    def get_fpcalc(self) -> None:
        current = find_fpcalc()
        if current and QMessageBox.question(self, APP_NAME, f"fpcalc is already available:\n{current}\n\n"
                                            "Download a fresh copy anyway?") != QMessageBox.StandardButton.Yes:
            return
        if not can_download_fpcalc():
            QMessageBox.information(self, APP_NAME, "There's no prebuilt fpcalc for this system. Install "
                                    "Chromaprint with your package manager (e.g. chromaprint-tools).")
            return

        def done(path: str) -> None:
            self._log(f"fpcalc ready: {path}")
            self.status.setText("fpcalc installed: fingerprinting and AcoustID lookups are enabled")
        self.run("Downloading fpcalc…", download_fpcalc, done)

    # ------------------------------------------------------------ helpers
    def run(self, label: str, fn, on_done=None) -> None:
        if not self.runner.run(label, fn, on_done, lambda err: QMessageBox.warning(self, APP_NAME, err)):
            QMessageBox.information(self, APP_NAME, "Please wait for the current task to finish (or cancel it).")

    def _busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        for a in (self.a_scan, self.a_fix, self.a_review, self.a_ident, self.a_art, self.a_choose_art, self.a_clean,
                  self.a_paths, self.a_apply, self.a_discard, self.a_dupes, self.a_cue, self.a_org, self.a_undo):
            a.setEnabled(not busy)

    def _progress(self, cur: int, total: int, msg: str) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(cur)
        else:
            self.progress.setRange(0, 0)
        if msg:
            self.status.setText(msg)

    def _log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)

    def selected_ids(self) -> list[int]:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.tracks[r].id for r in rows]

    def visible_ids(self) -> list[int]:
        return [self.model.tracks[self.proxy.mapToSource(self.proxy.index(r, 0)).row()].id
                for r in range(self.proxy.rowCount())]

    def target_ids(self, verb: str) -> list[int] | None:
        """The selected tracks. Buttons only ever work on the selection (Fix Whole Library does everything)."""
        ids = self.selected_ids()
        if ids:
            return ids
        QMessageBox.information(self, verb, "Select the tracks you want first: click a track, Shift- or "
                                "Ctrl-click for several, or Ctrl+A for every track in the list.\n\n"
                                "To work on your whole library, use Fix Whole Library.")
        return None

    def refresh_tracks(self) -> None:
        """Pending changes changed: redraw the list and the comparison, keeping the selection."""
        self.reload()

    def reload(self) -> None:
        selected = set(self.selected_ids())
        counts = self.lib.counts()
        for i in range(self.views.count()):
            it = self.views.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            it.setText(f"{VIEWS[key]}  ({counts.get(key, 0)})")
        self._view_tracks = self.lib.view(self.view_name)
        self._fill_tree(self._view_tracks)
        self._show_folder(selected)
        self.status.setText(f"{counts['all']} tracks · {counts['review']} awaiting review · "
                            f"{counts['problems']} with problems")
        self.center.setCurrentIndex(1 if self.lib.folders else 0)
        self.detail_scroll.setVisible(bool(self.lib.folders))
        n = counts["review"]
        self.banner.setVisible(n > 0)
        if n:
            unit = "folder" if self.lib.settings.review_group == "folder" else "album"
            groups = len(self.lib.review_groups(self.lib.settings.review_group))
            self.banner_text.setText(f"<b>{n} track{'s have' if n != 1 else ' has'} new values waiting</b> "
                                     f"({groups} {unit}{'s' if groups != 1 else ''}).")
            self.b_review.setText(f"Review {unit.capitalize()} by {unit.capitalize()}…")
        self._selection_changed()

    def show_view(self, key: str) -> None:
        for i in range(self.views.count()):
            if self.views.item(i).data(Qt.ItemDataRole.UserRole) == key:
                self.views.setCurrentRow(i)
                return

    def discard_all(self) -> None:
        ids = sorted(self.lib.db.proposal_ids())
        if ids and QMessageBox.question(self, "Discard all", f"Drop the proposed changes of all {len(ids)} "
                                        "tracks? The files aren't touched.") == QMessageBox.StandardButton.Yes:
            self.lib.discard(ids)
            self.reload()

    def _show_folder(self, selected: set[int] | None = None) -> None:
        """Fill the table with the current view's tracks in the chosen folder (and below)."""
        tracks = sorted(foldertree.in_folder(self._view_tracks, self.folder), key=foldertree.album_order)
        self.model.set_tracks(tracks)
        roots = self.lib.folders
        self.files.set_folder(self.folder or (roots[0] if len(roots) == 1 else ""))
        if selected:
            sm = self.table.selectionModel()
            for r, t in enumerate(self.model.tracks):
                if t.id in selected:
                    idx = self.proxy.mapFromSource(self.model.index(r, 0))
                    if idx.isValid():
                        sm.select(idx, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)

    # ------------------------------------------------------------ folder tree
    def _fill_tree(self, tracks) -> None:
        """Rebuild the tree for the current view, keeping what was expanded and selected."""
        expanded = set()
        it = self.tree.invisibleRootItem()
        stack = [it.child(i) for i in range(it.childCount())]
        while stack:
            node = stack.pop()
            if node.isExpanded():
                expanded.add(node.data(0, Qt.ItemDataRole.UserRole))
            stack.extend(node.child(i) for i in range(node.childCount()))
        first_fill = not hasattr(self, "_tree_filled")
        self._tree_filled = True
        min_art = self.lib.settings.artwork_min_size
        nodes = foldertree.build(tracks, self.lib.folders, lambda t: fixable(problems(t, min_art)))
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self.tree.blockSignals(True)
        self.tree.clear()
        everything = QTreeWidgetItem([f"All folders  ({len(tracks)})"])
        everything.setData(0, Qt.ItemDataRole.UserRole, "")
        everything.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        self.tree.addTopLevelItem(everything)
        items: dict[str, QTreeWidgetItem] = {}

        def add(parent, node, depth):
            warn = f"  ⚠ {node.flagged}" if node.flagged else ""
            item = QTreeWidgetItem([f"{node.name}  ({node.count}){warn}"])
            item.setData(0, Qt.ItemDataRole.UserRole, node.path)
            item.setToolTip(0, f"{node.path}\n{node.count} track{'s' if node.count != 1 else ''}"
                            + (f", {node.flagged} need fixing" if node.flagged else ""))
            if node.flagged:
                item.setForeground(0, QBrush(RED))
            item.setIcon(0, icon)
            parent.addChild(item)
            items[node.path] = item
            for c in node.children:
                add(item, c, depth + 1)
            if node.path in expanded or (first_fill and depth == 0):
                item.setExpanded(True)
        for n in nodes:
            add(self.tree.invisibleRootItem(), n, 0)
        # the chosen folder may not be in this view: fall back to its nearest shown parent, else everything
        current = everything
        if self.folder_choice:
            for cand in (self.folder_choice, *map(str, Path(self.folder_choice).parents)):
                if cand in items:
                    current = items[cand]
                    break
        self.folder = current.data(0, Qt.ItemDataRole.UserRole) or None
        self.tree.setCurrentItem(current)
        p = current.parent()
        while p is not None:
            p.setExpanded(True)
            p = p.parent()
        self.tree.blockSignals(False)

    def _folder_changed(self, cur, _prev) -> None:
        if cur is None:
            return
        self.folder = self.folder_choice = cur.data(0, Qt.ItemDataRole.UserRole) or None
        self.table.clearSelection()
        self._album_order()
        self._show_folder()
        self._selection_changed()

    def _album_order(self) -> None:
        """Show tracks in folder / disc / track order (clicking a column header sorts by that column)."""
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.proxy.sort(-1)

    def _tree_menu(self, pos) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        item = self.tree.itemAt(pos)
        path = item.data(0, Qt.ItemDataRole.UserRole) if item else ""
        if not path:
            return
        menu = QMenu(self)
        menu.addAction(self._act("Copy Folder Name", lambda: self._copy(Path(path).name)))
        menu.addAction(self._act("Copy Folder Path", lambda: self._copy(path)))
        menu.addSeparator()
        menu.addAction(self._act("Select All Tracks in This Folder", lambda: (self.tree.setCurrentItem(item),
                                                                           self.table.selectAll())))
        menu.addAction(self._act("Tags from Folder Names…", lambda: (self.tree.setCurrentItem(item),
                                                                  self.tags_from_paths())))
        menu.addAction(self._act("Split CUE Sheets Here…", lambda: self.split_cue(path)))
        menu.addAction(self._act("Expand All Below", lambda: self._expand(item, True)))
        menu.addAction(self._act("Collapse All Below", lambda: self._expand(item, False)))
        menu.addSeparator()
        menu.addAction(self._act("Open Folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path))))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _expand(self, item, on: bool) -> None:
        item.setExpanded(on)
        for i in range(item.childCount()):
            self._expand(item.child(i), on)

    def _select_track_by_path(self, path: str) -> None:
        """A file was clicked in the Files panel: select its track in the list."""
        for r, t in enumerate(self.model.tracks):
            if t.path == path:
                idx = self.proxy.mapFromSource(self.model.index(r, 0))
                if idx.isValid():
                    self.table.selectRow(idx.row())
                    self.table.scrollTo(idx)
                    return
        self.status.setText("That file isn't in the track list right now (check the view or search, or Rescan)")

    def _selection_changed(self) -> None:
        ids = self.selected_ids()
        if len(ids) == 1:
            t = next((x for x in self.model.tracks if x.id == ids[0]), None)
            if t:
                self.files.show_track(t.path)
        self.detail.show_tracks(self.lib.tracks(ids[:500]) if ids else [])

    def _view_changed(self, cur, _prev) -> None:
        if cur:
            self.view_name = cur.data(Qt.ItemDataRole.UserRole)
            self.table.clearSelection()
            self.reload()

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy = menu.addMenu("Copy")
        tracks = self.lib.tracks(self.selected_ids())
        if tracks:
            def names(fn):
                return lambda: self._copy("\n".join(dict.fromkeys(fn(t) for t in tracks)))
            copy.addAction(self._act("File Name", names(lambda t: t.filename)))
            copy.addAction(self._act("Full Path", names(lambda t: t.path)))
            copy.addAction(self._act("Folder Name", names(lambda t: Path(t.folder).name)))
            copy.addAction(self._act("Folder Path", names(lambda t: t.folder)))
            copy.addAction(self._act("Artist - Title", names(lambda t: " - ".join(
                x for x in (t.get("artist"), t.get("title") or Path(t.path).stem) if x))))
        copy.setEnabled(bool(tracks))
        menu.addSeparator()
        for a in (self.a_ident, self.a_art, self.a_choose_art, self.a_clean, self.a_paths, None,
                  self.a_apply, self.a_discard, None, self.a_org):
            menu.addSeparator() if a is None else menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self._act("Open Containing Folder", self._open_folder))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        lines = text.count("\n") + 1
        self.status.setText(f"Copied {lines} line{'s' if lines != 1 else ''} to the clipboard" if lines > 1
                            else f"Copied: {text}")

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        ids = self.selected_ids()
        if ids:
            t = self.lib.db.track(ids[0])
            QDesktopServices.openUrl(QUrl.fromLocalFile(t.folder))

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME,
                          f"<h3>{APP_NAME} {__version__}</h3><p>Tag, clean up, de-duplicate and organize your music "
                          "library.</p><p>Metadata from <a href='https://musicbrainz.org'>MusicBrainz</a> and "
                          "<a href='https://acoustid.org'>AcoustID</a>; artwork from the Cover Art Archive, iTunes and "
                          "Deezer.</p>")

    # drag & drop folders onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        added = False
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                self.lib.add_folder(str(p))
                added = True
        if added:
            self.scan()

    # ------------------------------------------------------------ actions
    def add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Add music folder", str(Path.home() / "Music"))
        if d:
            self.lib.add_folder(d)
            self.scan()

    def scan(self) -> None:
        if not self.lib.folders:
            self.add_folder()
            return

        def done(r):
            parts = [f"{r.get('added', 0)} new", f"{r.get('updated', 0)} changed", f"{r.get('removed', 0)} gone"]
            msg = f"Scan finished: {self.lib.db.count()} tracks (" + ", ".join(parts) + ")"
            if r.get("errors"):
                msg += f"; {r['errors']} files couldn't be read (see Unreadable files)"
            self._log(msg)
            self.reload()
            self.status.setText(msg)
        self.run("Scanning library…", lambda task: self.lib.scan(task), done)

    def _after(self, fmt: str, view: str | None = "review"):
        def done(r):
            msg = fmt.format(r=r)
            self._log(msg)
            if view and self.view_name != view:
                for i in range(self.views.count()):
                    if self.views.item(i).data(Qt.ItemDataRole.UserRole) == view:
                        self.views.setCurrentRow(i)
                        break
            self.reload()
            self.status.setText(msg)
        return done

    def identify(self) -> None:
        ids = self.target_ids("Identify")
        if ids:
            after = self._after("Found tags for {r[matched]} of " + str(len(ids)) + " tracks ({r[unmatched]} not "
                                "found) - compare Original and New on the right, then Apply", None)

            def done(r) -> None:
                after(r)
                self._offer_sound_id(r.get("unmatched", 0))
            self.run("Looking up tags…", lambda task: self.lib.identify(ids, task), done)

    def cleanup(self) -> None:
        ids = self.target_ids("Clean up")
        if ids:
            self.run("Cleaning up tags…", lambda task: self.lib.cleanup(ids, task),
                     self._after("Clean up: fixes for {r} tracks - compare on the right, then Apply", None))

    def fetch_artwork(self) -> None:
        ids = self.target_ids("Find artwork for")
        if ids:
            self.run("Finding artwork…", lambda task: self.lib.fetch_artwork(ids, task, only_missing=False),
                     self._after("Found artwork for {r} tracks - compare on the right, then Apply", None))

    def tags_from_paths(self) -> None:
        from .dialogs import PathTagsDialog
        ids = self.target_ids("Tags from folder names")
        if not ids:
            return
        d = PathTagsDialog(self.lib, self.lib.tracks(ids), self)
        if d.exec():
            pattern, overwrite = d.result_options()
            self.run("Reading folder names…",
                     lambda task: self.lib.tags_from_paths(ids, task, pattern=pattern, overwrite=overwrite),
                     self._after("Folder names: new values for {r} tracks - compare on the right, then Apply",
                                 None))

    def split_cue(self, folder: str | None = None) -> None:
        from .dialogs import CueDialog
        if not self.lib.folders:
            self.add_folder()
            return
        d = CueDialog(self.lib, self, folder=folder if isinstance(folder, str) else self.folder)
        if not d.exec():
            return
        sheets = d.chosen
        dest, remove = d.options()

        def done(r) -> None:
            made, failed, batch = r
            msg = f"Split {len(sheets) - failed} CUE sheet(s) into {made} tracks"
            if failed:
                msg += f"; {failed} couldn't be split (see the log)"
                self.log_dock.show()
            self._log(msg + " - Ctrl+Z to undo")
            self.reload()
            self.status.setText(msg)
        self.run("Splitting CUE sheets…",
                 lambda task: self.lib.split_cues(sheets, task, dest=dest, remove_original=remove), done)

    def choose_artwork(self) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        dlg = ArtworkDialog(self.lib, self.lib.db.track(ids[0]), self)
        if dlg.exec() and dlg.result:
            self.propose_art(ids, *dlg.result)

    def propose_art(self, ids: list[int], data: bytes, label: str) -> None:
        if ids:
            self.lib.propose_artwork(ids, data, label)
            self.reload()

    def apply(self) -> None:
        """Write the new values of the selected tracks (and only those)."""
        pending = self.lib.db.proposal_ids()
        sel = self.selected_ids()
        if not sel:
            self.target_ids("Apply")
            return
        ids = [i for i in sel if i in pending]
        if not ids:
            self.status.setText("The selected tracks have no changes to apply")
            return
        if len(ids) == 1:          # what will be written is right there in the Original | New panel
            self.run("Writing tags…", lambda task: self.lib.apply(ids, task),
                     self._after("Saved - Ctrl+Z to undo", None))
            return
        self._preview_and_apply(ids)

    def _preview_and_apply(self, ids: list[int]) -> None:
        """Show every change first; write only what's still ticked."""
        from .dialogs import ApplyPreviewDialog
        d = ApplyPreviewDialog(self.lib, ids, self)
        if not d.tree.topLevelItemCount():
            self.status.setText("Nothing to apply: the proposed values are already in the files")
            return
        if not d.exec():
            return
        write, exclude = d.selection()
        self.run("Writing tags…", lambda task: self.lib.apply(write, task, exclude=exclude),
                 self._after("Wrote {r.written} files ({r.failed} failed) — Ctrl+Z to undo", None))

    def fix_library(self) -> None:
        from .compare import FixLibraryDialog
        if not self.lib.folders:
            self.add_folder()
            return
        d = FixLibraryDialog(self.lib, self.folder, self)
        if not d.exec():
            return
        o = d.options()
        if o["group"] != self.lib.settings.review_group:
            self.lib.settings.review_group = o["group"]
            save_settings(self.lib.settings)
        scope = [t.id for t in foldertree.in_folder(self.lib.view("all"), o["folder"])]

        def done(r) -> None:
            self.reload()
            self._log(f"Fix Whole Library: {r['waiting']} tracks have changes to review")
            if r["waiting"]:
                self.review(set(scope))
            else:
                QMessageBox.information(self, "Fix Whole Library", "Done - nothing needs changing.")
        self.run("Fixing library… (looking up tags and artwork)",
                 lambda task: self.lib.fix_library(scope, task, lookup=o["lookup"], artwork=o["artwork"],
                                                   clean=o["clean"], skip_identified=o["skip_identified"]), done)

    def review(self, ids: set[int] | None = None) -> None:
        from .compare import ReviewWizard
        if self.runner.busy:
            QMessageBox.information(self, APP_NAME, "Please wait for the current task to finish (or cancel it).")
            return
        ReviewWizard(self.lib, self, ids=ids).exec()
        self.reload()

    def discard(self) -> None:
        pending = self.lib.db.proposal_ids()
        ids = [i for i in self.selected_ids() if i in pending]
        if ids:
            self.lib.discard(ids)
            self.reload()

    def save_edits(self, ids: list[int], changes: dict[str, str]) -> None:
        self.run("Saving tags…", lambda task: self.lib.edit(ids, changes, task=task),
                 self._after("Saved {r.written} files", None))

    def duplicates(self) -> None:
        dlg = DuplicatesDialog(self.lib, self.runner, self)
        dlg.changed.connect(self.reload)
        dlg.exec()
        self.reload()

    def organize(self) -> None:
        all_ids = [t.id for t in self.lib.view("all")]
        if not all_ids:
            self.status.setText("Add a music folder first")
            return
        dlg = OrganizeDialog(self.lib, self.runner, self.selected_ids(), self, all_ids=all_ids)
        dlg.changed.connect(self.reload)
        dlg.exec()

    def undo(self) -> None:
        dlg = HistoryDialog(self.lib, self)
        if not dlg.exec() or not dlg.action:
            return
        kind, items = dlg.action
        if kind == "batch":
            self.run("Undoing…", lambda task: self.lib.undo(items[0], task), self._after("Undid {r} changes", None))
            return

        def done(r) -> None:
            n, problems = r
            for p in problems:
                self._log("Revert: " + p)
            if problems:
                self.log_dock.show()
                QMessageBox.warning(self, "Revert", f"Reverted {n} changes; {len(problems)} couldn't be reverted "
                                    "(see the log).")
            self.reload()
            self.status.setText(f"Reverted {n} changes")
        self.run("Reverting…", lambda task: self.lib.revert_snapshots(items, task), done)

    def settings_dialog(self) -> None:
        if SettingsDialog(self.lib, self).exec():
            self.reload()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if icon.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon)))
    if sys.platform == "win32":
        # own taskbar group/icon instead of python.exe's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MusicMaid.MusicMaid")
        except Exception:
            pass
    from . import winstyle
    winstyle.init(app)                    # Windows: title bars in the skin's colours, live dark/light
    win = MainWindow()
    win.apply_skin(win.lib.settings.skin or skins.DEFAULT_SKIN)
    for err in skins.skin_errors:
        win._log(err)
    winstyle.on_scheme_change(lambda: win.apply_skin(win.lib.settings.skin or skins.DEFAULT_SKIN))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
