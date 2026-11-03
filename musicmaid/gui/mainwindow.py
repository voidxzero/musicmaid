"""MusicMaid desktop GUI (Qt / PySide6) for Linux and Windows."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDockWidget, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QStyle, QTableView, QToolBar, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from .. import tags as tagio
from ..cleanup import problems
from ..db import Track
from ..config import save_settings
from ..fingerprint import can_download_fpcalc, download_fpcalc, find_fpcalc
from ..library import VIEWS, Library
from .dialogs import AcoustIDDialog, ArtworkDialog, DuplicatesDialog, HistoryDialog, OrganizeDialog, SettingsDialog
from .. import updater
from . import skins
from .workers import TaskRunner, background

COLUMNS = [
    ("state", ""), ("artist", "Artist"), ("title", "Title"), ("album", "Album"), ("albumartist", "Album Artist"),
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
            return "!", RED, t.error
        if t.id in self.pending:
            src, score, art = self.pending[t.id]
            ok = score >= self.lib.settings.auto_apply_threshold
            return "±", GREEN if ok else AMBER, f"Pending changes from {src} (confidence {score:.0%})"
        probs = problems(t, self.lib.settings.artwork_min_size)
        if probs:
            return "•", AMBER, ", ".join(probs)
        return "✓", GREEN, "OK"

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        t = self.tracks[index.row()]
        key = COLUMNS[index.column()][0]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if key == "state":
                return self._state(t)[0]
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
            if key == "title" and not t.get("title"):
                return QBrush(DIM)
        if role == Qt.ItemDataRole.ToolTipRole and key == "state":
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
class ArtLabel(QLabel):
    """Shows cover art; accepts dropped image files."""

    def __init__(self, on_drop):
        super().__init__()
        self.on_drop = on_drop
        self.setAcceptDrops(True)
        self.setFixedSize(260, 260)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setText("No artwork\n\n(drop an image here)")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                self.on_drop(p.read_bytes(), f"file {p.name}")
                return


class DetailPanel(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.tracks: list[Track] = []
        lay = QVBoxLayout(self)

        self.art = ArtLabel(self._dropped_art)
        self.art_info = QLabel()
        self.art_info.setWordWrap(True)
        self.art_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art_btns = QHBoxLayout()
        b_choose = QPushButton("Find artwork…")
        b_choose.clicked.connect(win.choose_artwork)
        b_file = QPushButton("From file…")
        b_file.clicked.connect(self._art_from_file)
        b_remove = QPushButton("Remove")
        b_remove.clicked.connect(self._remove_art)
        for b in (b_choose, b_file, b_remove):
            art_btns.addWidget(b)
        lay.addWidget(self.art, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.art_info)
        lay.addLayout(art_btns)

        self.proposal = QLabel()
        self.proposal.setWordWrap(True)
        self.proposal.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.proposal)
        prow = QHBoxLayout()
        self.b_apply = QPushButton("Apply proposed changes")
        self.b_apply.clicked.connect(win.apply)
        self.b_discard = QPushButton("Discard")
        self.b_discard.clicked.connect(win.discard)
        prow.addWidget(self.b_apply)
        prow.addWidget(self.b_discard)
        lay.addLayout(prow)

        form_w = QWidget()
        self.form = QFormLayout(form_w)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.edits: dict[str, QLineEdit] = {}
        for f in tagio.EDITABLE_FIELDS:
            e = QLineEdit()
            e.textEdited.connect(lambda _=None, f=f: self._edited(f))
            self.edits[f] = e
            self.form.addRow(tagio.FIELD_LABELS[f], e)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_w)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(scroll, 1)

        save_row = QHBoxLayout()
        self.b_save = QPushButton("Save tags")
        self.b_save.setEnabled(False)
        self.b_save.clicked.connect(self._save)
        self.b_revert = QPushButton("Revert")
        self.b_revert.clicked.connect(lambda: self.show_tracks(self.tracks))
        save_row.addStretch(1)
        save_row.addWidget(self.b_revert)
        save_row.addWidget(self.b_save)
        lay.addLayout(save_row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("dim")
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info)
        self.dirty: set[str] = set()
        self.show_tracks([])

    def show_tracks(self, tracks: list[Track]) -> None:
        self.tracks = tracks
        self.dirty.clear()
        self.b_save.setEnabled(False)
        lib = self.win.lib
        n = len(tracks)
        for e in self.edits.values():
            e.setEnabled(n > 0)
        if not tracks:
            for e in self.edits.values():
                e.clear()
                e.setPlaceholderText("")
            self.art.setPixmap(QPixmap())
            self.art.setText("No track selected")
            self.art_info.clear()
            self.proposal.clear()
            self.info.clear()
            self.b_apply.setVisible(False)
            self.b_discard.setVisible(False)
            return
        props = {t.id: lib.db.proposal(t.id) for t in tracks}
        for f, e in self.edits.items():
            values = {t.tags.get(f, "") for t in tracks}
            proposed = {(props[t.id].tags.get(f) if props[t.id] and f in props[t.id].tags else None) for t in tracks}
            e.setStyleSheet("")
            e.setToolTip("")
            if proposed != {None}:
                new_vals = {p for p in proposed if p is not None}
                old = ", ".join(sorted(v for v in values if v)) or "(empty)"
                e.setStyleSheet(f"QLineEdit {{ background: rgba({GREEN.red()},{GREEN.green()},{GREEN.blue()},0.22); }}")
                e.setToolTip(f"Proposed change (not saved yet). Current: {old}")
                e.setText(next(iter(new_vals)) if len(new_vals) == 1 else "")
                e.setPlaceholderText("<different proposals>" if len(new_vals) > 1 else "")
            elif len(values) == 1:
                e.setText(next(iter(values)))
                e.setPlaceholderText("")
            else:
                e.clear()
                e.setPlaceholderText("<multiple values — leave empty to keep>")
        # proposal summary
        with_p = [p for p in props.values() if p]
        self.b_apply.setVisible(bool(with_p))
        self.b_discard.setVisible(bool(with_p))
        if with_p:
            p = with_p[0]
            col = "#2ea043" if p.score >= lib.settings.auto_apply_threshold else "#d29922"
            txt = (f"<b style='color:{col}'>Proposed by {p.source} — confidence {p.score:.0%}</b>"
                   + (f"<br><i>{p.note}</i>" if p.note else ""))
            if n > 1:
                txt += f"<br>{len(with_p)} of {n} selected tracks have proposals."
            self.proposal.setText(txt)
        else:
            self.proposal.setText("")
        # artwork: proposed art first, else embedded art of the first track
        t = tracks[0]
        prop_art = props[t.id].art if props[t.id] and props[t.id].art else None
        data, label = None, ""
        if prop_art:
            data = prop_art
            _, w, h = tagio.image_info(prop_art)
            label = f"<b style='color:#2ea043'>New artwork {w}×{h}</b><br>{props[t.id].art_source or ''}"
        elif t.has_art:
            art = tagio.read_artwork(t.path)
            if art:
                data = art.data
                label = f"{art.width}×{art.height}"
        if data:
            pm = QPixmap()
            pm.loadFromData(data)
            self.art.setPixmap(pm.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
        else:
            self.art.setPixmap(QPixmap())
            self.art.setText("No artwork\n\n(drop an image here)")
        self.art_info.setText(label)
        if n == 1:
            m, s = divmod(int(t.duration), 60)
            probs = problems(t, lib.settings.artwork_min_size)
            self.info.setText(f"{t.path}\n{t.codec} · {'lossless' if t.lossless else f'{t.bitrate} kbps'} · "
                              f"{t.sample_rate / 1000:g} kHz · {m}:{s:02d}"
                              + (f"\nProblems: {', '.join(probs)}" if probs else ""))
        else:
            self.info.setText(f"{n} tracks selected")

    def _edited(self, f: str) -> None:
        self.dirty.add(f)
        self.b_save.setEnabled(True)

    def _save(self) -> None:
        changes = {f: self.edits[f].text().strip() for f in self.dirty}
        if len(self.tracks) > 1:
            # empty field in multi-edit means "keep" unless the user really typed something
            changes = {k: v for k, v in changes.items() if v}
        if changes:
            self.win.save_edits([t.id for t in self.tracks], changes)

    def _dropped_art(self, data: bytes, label: str) -> None:
        self.win.propose_art([t.id for t in self.tracks], data, label)

    def _art_from_file(self) -> None:
        if not self.tracks:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Choose image", str(Path.home()), "Images (*.jpg *.jpeg *.png *.webp)")
        if p:
            self._dropped_art(Path(p).read_bytes(), f"file {Path(p).name}")

    def _remove_art(self) -> None:
        if self.tracks and QMessageBox.question(self, "Remove artwork",
                                                f"Remove embedded artwork from {len(self.tracks)} file(s)?") \
                == QMessageBox.StandardButton.Yes:
            self.win.run("Removing artwork…", lambda task: self.win.lib.edit(
                [t.id for t in self.tracks], {}, None, task), lambda r: self.win.reload())


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

        # views sidebar
        self.views = QListWidget()
        self.views.setMaximumWidth(220)
        for key, label in VIEWS.items():
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.views.addItem(it)
        self.views.setCurrentRow(0)
        self.views.currentItemChanged.connect(self._view_changed)

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
        for i, w in enumerate([28, 170, 230, 190, 150, 40, 50, 100, 100, 55]):
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

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.search)
        cl.addWidget(self.table)

        self.detail = DetailPanel(self)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(self.detail)
        detail_scroll.setMinimumWidth(340)

        split = QSplitter()
        split.addWidget(self.views)
        split.addWidget(center)
        split.addWidget(detail_scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 900, 400])
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
        self.a_scan = self._act("Scan", self.scan, "F5", P.SP_BrowserReload, "Rescan library folders for changes")
        self.a_auto = self._act("Auto-Tag", self.auto_tag, "Ctrl+T", P.SP_MediaPlay,
                                "Clean up, identify online and fetch artwork; confident results are written automatically")
        self.a_ident = self._act("Identify", self.identify, "Ctrl+I", P.SP_FileDialogContentsView,
                                 "Look up selected tracks on MusicBrainz / AcoustID (proposes changes)")
        self.a_clean = self._act("Clean Up", self.cleanup, "Ctrl+L", P.SP_DialogResetButton,
                                 "Fix capitalisation, junk text, fill tags from file names (proposes changes)")
        self.a_art = self._act("Artwork", self.fetch_artwork, "Ctrl+K", P.SP_DesktopIcon,
                               "Find missing cover art (Cover Art Archive, iTunes, Deezer)")
        self.a_apply = self._act("Apply", self.apply, "Ctrl+Return", P.SP_DialogApplyButton,
                                 "Write proposed changes of the selected tracks to the files")
        self.a_discard = self._act("Discard", self.discard, "Ctrl+Backspace", P.SP_DialogDiscardButton,
                                   "Drop proposed changes of the selected tracks")
        self.a_dupes = self._act("Duplicates", self.duplicates, "Ctrl+D", P.SP_FileDialogDetailedView,
                                 "Find duplicate songs (identical files, same audio, same tags)")
        self.a_org = self._act("Organize", self.organize, "Ctrl+R", P.SP_DirIcon,
                               "Rename and move files into folders based on their tags")
        self.a_undo = self._act("Undo…", self.undo, "Ctrl+Z", P.SP_ArrowBack, "Undo tag writes, moves and removals")
        self.a_settings = self._act("Settings", self.settings_dialog, "Ctrl+,", P.SP_FileDialogInfoView)
        self.a_log = self._act("Show Log", lambda: self.log_dock.setVisible(not self.log_dock.isVisible()), "Ctrl+Shift+L")
        self.a_choose_art = self._act("Choose Artwork…", self.choose_artwork, "Ctrl+Shift+K")
        self.a_select_all = self._act("Select All", self.table.selectAll, "Ctrl+A")

        tb = QToolBar("Main")
        tb.setObjectName("main-toolbar")
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        for a in (self.a_add, self.a_scan, None, self.a_auto, self.a_ident, self.a_clean, self.a_art, None,
                  self.a_apply, self.a_discard, None, self.a_dupes, self.a_org, None, self.a_undo, self.a_settings):
            tb.addSeparator() if a is None else tb.addAction(a)
        self.addToolBar(tb)

        m = self.menuBar()
        f = m.addMenu("&File")
        for a in (self.a_add, self.a_scan, self.a_settings):
            f.addAction(a)
        f.addSeparator()
        f.addAction(self._act("Quit", self.close, "Ctrl+Q"))
        t = m.addMenu("&Tags")
        for a in (self.a_auto, self.a_ident, self.a_clean, self.a_art, self.a_choose_art, None, self.a_apply,
                  self.a_discard, self.a_undo):
            t.addSeparator() if a is None else t.addAction(a)
        lib_menu = m.addMenu("&Library")
        for a in (self.a_dupes, self.a_org, self.a_select_all, self.a_log):
            lib_menu.addAction(a)
        v = m.addMenu("&View")
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
        super().closeEvent(e)

    def _first_run(self) -> None:
        updater.cleanup_previous()
        if self.lib.settings.check_for_updates:
            self.check_updates(manual=False)
        if not find_fpcalc():
            self._log("fpcalc (Chromaprint) was not found: audio-based duplicate detection and AcoustID lookups are "
                      "disabled. Use Help → Download fpcalc, install Chromaprint, or set the fpcalc path in Settings.")
            self.log_dock.show()
            if can_download_fpcalc() and self.lib.settings.offer_fpcalc_download:
                self._offer_fpcalc()
        if not self.lib.settings.acoustid_key and self.lib.settings.offer_acoustid_key:
            self.acoustid_key(first_run=True)
        if not self.lib.settings.acoustid_key:
            self._log("No AcoustID key: songs are identified from tags and file names only. Add a free key with "
                      "Help → Identify by Sound to recognise untagged or wrongly tagged files.")
        if not self.lib.folders:
            QMessageBox.information(self, f"Welcome to {APP_NAME}",
                                    "Start by adding your music folder. Nothing is changed on disk until you apply "
                                    "changes, and every change can be undone.")
            self.add_folder()

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
        self.table.viewport().update()
        self.detail.show_tracks(self.detail.tracks)   # re-tint proposed-change fields
        for a in self.skin_group.actions():
            a.setChecked(a.text() == name)
        return name

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
        for a in (self.a_scan, self.a_auto, self.a_ident, self.a_clean, self.a_art, self.a_apply, self.a_dupes,
                  self.a_org, self.a_undo):
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
        """Selected tracks, or (after confirming) everything in the current view."""
        ids = self.selected_ids()
        if ids:
            return ids
        vis = self.visible_ids()
        if not vis:
            return None
        if QMessageBox.question(self, verb, f"No tracks selected. {verb} all {len(vis)} tracks in this view?") \
                == QMessageBox.StandardButton.Yes:
            return vis
        return None

    def reload(self) -> None:
        selected = set(self.selected_ids())
        counts = self.lib.counts()
        for i in range(self.views.count()):
            it = self.views.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            it.setText(f"{VIEWS[key]}  ({counts.get(key, 0)})")
        self.model.set_tracks(self.lib.view(self.view_name))
        if selected:
            sm = self.table.selectionModel()
            for r, t in enumerate(self.model.tracks):
                if t.id in selected:
                    idx = self.proxy.mapFromSource(self.model.index(r, 0))
                    if idx.isValid():
                        sm.select(idx, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
        self.status.setText(f"{counts['all']} tracks · {counts['review']} awaiting review · "
                            f"{counts['problems']} with problems")
        self._selection_changed()

    def _selection_changed(self) -> None:
        ids = self.selected_ids()
        self.detail.show_tracks(self.lib.tracks(ids[:500]) if ids else [])

    def _view_changed(self, cur, _prev) -> None:
        if cur:
            self.view_name = cur.data(Qt.ItemDataRole.UserRole)
            self.table.clearSelection()
            self.reload()

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        for a in (self.a_auto, self.a_ident, self.a_clean, self.a_art, self.a_choose_art, None, self.a_apply,
                  self.a_discard, None, self.a_org):
            menu.addSeparator() if a is None else menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self._act("Open Containing Folder", self._open_folder))
        menu.exec(self.table.viewport().mapToGlobal(pos))

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
            self._log(f"Scan: {r}")
            self.reload()
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

    def auto_tag(self) -> None:
        ids = self.target_ids("Auto-tag")
        if ids:
            self.run("Auto-tagging…", lambda task: self.lib.auto_tag(ids, task), self._after(
                "Auto-tag: {r[applied]} files written, {r[review]} need review, {r[unmatched]} not found online"))

    def identify(self) -> None:
        ids = self.target_ids("Identify")
        if ids:
            self.run("Identifying…", lambda task: self.lib.identify(ids, task), self._after(
                "Identified {r[matched]} tracks ({r[confident]} confident), {r[unmatched]} not found"))

    def cleanup(self) -> None:
        ids = self.target_ids("Clean up")
        if ids:
            self.run("Cleaning up tags…", lambda task: self.lib.cleanup(ids, task),
                     self._after("Clean-up proposed fixes for {r} tracks"))

    def fetch_artwork(self) -> None:
        ids = self.target_ids("Find artwork for")
        if ids:
            self.run("Finding artwork…", lambda task: self.lib.fetch_artwork(ids, task),
                     self._after("Found artwork for {r} tracks"))

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
        pending = self.lib.db.proposal_ids()
        ids = [i for i in self.selected_ids() if i in pending]
        if not ids:
            vis = [i for i in self.visible_ids() if i in pending]
            if not vis:
                self.status.setText("Nothing to apply")
                return
            if QMessageBox.question(self, "Apply", f"Write proposed changes for all {len(vis)} tracks in this view?") \
                    != QMessageBox.StandardButton.Yes:
                return
            ids = vis
        self.run("Writing tags…", lambda task: self.lib.apply(ids, task),
                 self._after("Wrote {r.written} files ({r.failed} failed) — Ctrl+Z to undo", None))

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
        ids = self.selected_ids() or self.visible_ids()
        if not ids:
            return
        dlg = OrganizeDialog(self.lib, self.runner, ids, self)
        dlg.changed.connect(self.reload)
        dlg.exec()

    def undo(self) -> None:
        dlg = HistoryDialog(self.lib, self)
        if dlg.exec() and dlg.batch:
            batch = dlg.batch
            self.run("Undoing…", lambda task: self.lib.undo(batch, task), self._after("Undid {r} changes", None))

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
