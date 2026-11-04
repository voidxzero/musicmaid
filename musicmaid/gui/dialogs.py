"""Dialogs: settings, duplicates, organize, artwork chooser and undo history."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, net
from ..config import save_settings
from ..library import Library
from ..organizer import PATTERN_HELP
from .workers import TaskRunner


def _browse_row(edit: QLineEdit, parent, directory: bool = True, caption: str = "Choose folder") -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit, 1)
    btn = QPushButton("Browse…")

    def pick():
        if directory:
            p = QFileDialog.getExistingDirectory(parent, caption, edit.text() or str(Path.home()))
        else:
            p, _ = QFileDialog.getOpenFileName(parent, caption, edit.text() or str(Path.home()))
        if p:
            edit.setText(p)

    btn.clicked.connect(pick)
    lay.addWidget(btn)
    return w


# ---------------------------------------------------------------- settings
class SettingsDialog(QDialog):
    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(640)
        self.lib = lib
        s = lib.settings
        from PySide6.QtWidgets import QTabWidget
        tabs = QTabWidget()

        def page(title: str) -> QFormLayout:
            w = QWidget()
            f = QFormLayout(w)
            f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            tabs.addTab(w, title)
            return f

        def hint(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("dim")
            lbl.setWordWrap(True)
            lbl.setOpenExternalLinks(True)
            return lbl

        # --- Identifying
        form = page("Identifying")
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.5, 1.0)
        self.threshold.setSingleStep(0.01)
        self.threshold.setValue(s.auto_apply_threshold)
        form.addRow("Write automatically from", self.threshold)
        form.addRow("", hint("Auto-Tag writes matches at least this confident (0.90 = 90%) straight away; "
                             "anything less waits in Needs review."))
        self.country = QLineEdit(s.prefer_country)
        self.country.setPlaceholderText("e.g. US, GB, DE (empty = any)")
        form.addRow("Preferred release country", self.country)
        self.prefer_album = QCheckBox("Prefer albums over singles and compilations")
        self.prefer_album.setChecked(s.prefer_album_releases)
        form.addRow("", self.prefer_album)
        self.genre = QCheckBox("Take the genre from MusicBrainz")
        self.genre.setChecked(s.genre_from_musicbrainz)
        form.addRow("", self.genre)
        self.mbids = QCheckBox("Write MusicBrainz IDs to files (helps other taggers and players)")
        self.mbids.setChecked(s.write_musicbrainz_ids)
        form.addRow("", self.mbids)
        self.va = QLineEdit(s.various_artists_name)
        form.addRow("Name for various artists", self.va)
        self.acoustid = QLineEdit(s.acoustid_api_key)
        self.acoustid.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.acoustid.setPlaceholderText("optional")
        form.addRow("AcoustID API key", self.acoustid)
        form.addRow("", hint('Optional: <a href="https://acoustid.org/new-application">get a free key</a> to '
                             "recognise songs by their sound, even with no tags at all. Without one, MusicMaid "
                             "uses tags and file names."))

        # --- Artwork
        form = page("Artwork")
        self.art_checks = {}
        for key, label in (("coverartarchive", "Cover Art Archive (by MusicBrainz release)"),
                           ("itunes", "iTunes / Apple Music"), ("deezer", "Deezer")):
            cb = QCheckBox(label)
            cb.setChecked(key in s.artwork_sources)
            self.art_checks[key] = cb
            form.addRow("Search" if key == "coverartarchive" else "", cb)
        self.art_min = QSpinBox()
        self.art_min.setRange(0, 5000)
        self.art_min.setSuffix(" px")
        self.art_min.setValue(s.artwork_min_size)
        form.addRow("Replace artwork smaller than", self.art_min)
        self.art_max = QSpinBox()
        self.art_max.setRange(0, 5000)
        self.art_max.setSuffix(" px")
        self.art_max.setSpecialValueText("never")
        self.art_max.setValue(s.artwork_max_size)
        form.addRow("Shrink embedded artwork to", self.art_max)
        self.cover_jpg = QCheckBox("Also save cover.jpg into album folders")
        self.cover_jpg.setChecked(s.save_cover_jpg)
        form.addRow("", self.cover_jpg)

        # --- Duplicates
        form = page("Duplicates")
        self.dupe_thr = QDoubleSpinBox()
        self.dupe_thr.setRange(0.5, 1.0)
        self.dupe_thr.setSingleStep(0.01)
        self.dupe_thr.setValue(s.dupe_fingerprint_threshold)
        form.addRow("Same audio from similarity", self.dupe_thr)
        form.addRow("", hint("How alike two recordings must sound to count as duplicates (1.00 = identical)."))
        self.recycle = QCheckBox("Send removed files to the recycle bin instead of quarantine")
        self.recycle.setChecked(s.use_recycle_bin)
        form.addRow("", self.recycle)
        self.quarantine = QLineEdit(s.quarantine_folder)
        self.quarantine.setPlaceholderText(str(s.quarantine_path))
        form.addRow("Quarantine folder", _browse_row(self.quarantine, self))
        form.addRow("", hint("Removed duplicates and split CUE images are moved here, so Undo can bring them back."))

        # --- Appearance
        form = page("Appearance")
        from . import skins
        self._orig_skin = s.skin or skins.DEFAULT_SKIN
        self.skin = QComboBox()
        self.skin.addItems(skins.theme_names())
        self.skin.setCurrentText(self._orig_skin)
        self.skin.currentTextChanged.connect(self._preview_skin)   # selecting a skin previews it
        form.addRow("Skin", self.skin)
        skin_row = QHBoxLayout()
        for text, slot, tip in (("Import skin…", self._import_skin, "Add a skin file (.json), e.g. one from Spindle"),
                                ("Save a copy to edit…", self._export_skin,
                                 "Write the selected skin to a file you can edit and import as your own skin"),
                                ("Open skins folder", self._open_skins, "")):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if tip:
                b.setToolTip(tip)
            skin_row.addWidget(b)
        skin_row.addStretch(1)
        skin_w = QWidget()
        skin_row.setContentsMargins(0, 0, 0, 0)
        skin_w.setLayout(skin_row)
        form.addRow("", skin_w)
        form.addRow("", hint("Skins are small .json files with colours (no code), so they're safe to share. "
                             "Skins from Spindle work here too."))

        # --- Updates
        form = page("Updates")
        from .. import __version__
        form.addRow("Installed version", QLabel(f"MusicMaid {__version__}"))
        self.updates = QCheckBox("Check for updates when MusicMaid starts")
        self.updates.setChecked(s.check_for_updates)
        form.addRow("", self.updates)
        check_now = QPushButton("Check for Updates Now")
        check_now.clicked.connect(self._check_updates)
        form.addRow("", check_now)
        if s.skipped_update:
            form.addRow("", hint(f"You chose to skip version {s.skipped_update}; Check for Updates Now still "
                                 "offers it."))

        # --- Tools
        form = page("Tools")
        from ..cuesplit import can_download_ffmpeg
        from ..fingerprint import can_download_fpcalc
        self.fpcalc = QLineEdit(s.fpcalc_path)
        self.fpcalc.setPlaceholderText("found automatically")
        form.addRow("fpcalc (Chromaprint)", _browse_row(self.fpcalc, self, False, "Locate fpcalc"))
        form.addRow("", hint("Makes audio fingerprints, used to recognise songs by sound and find duplicates "
                             "that are encoded differently."))
        self.ffmpeg = QLineEdit(s.ffmpeg_path)
        self.ffmpeg.setPlaceholderText("found automatically")
        form.addRow("ffmpeg", _browse_row(self.ffmpeg, self, False, "Locate ffmpeg"))
        form.addRow("", hint("Used to split CUE sheets into separate tracks."))
        self.tool_status = QLabel()
        self.tool_status.setWordWrap(True)
        form.addRow("Status", self.tool_status)
        dl_row = QHBoxLayout()
        dl_row.setContentsMargins(0, 0, 0, 0)
        if can_download_fpcalc():
            b = QPushButton("Download fpcalc")
            b.clicked.connect(lambda: self._download_tool("fpcalc"))
            dl_row.addWidget(b)
        if can_download_ffmpeg():
            b = QPushButton("Download ffmpeg (115 MB)")
            b.clicked.connect(lambda: self._download_tool("ffmpeg"))
            dl_row.addWidget(b)
        dl_row.addStretch(1)
        dl_w = QWidget()
        dl_w.setLayout(dl_row)
        form.addRow("", dl_w)
        self._refresh_tools()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def _refresh_tools(self) -> None:
        from ..cuesplit import find_ffmpeg
        from ..fingerprint import find_fpcalc
        fp, ff = find_fpcalc(), find_ffmpeg()
        self.tool_status.setText(f"fpcalc: {fp or 'not found'}<br>ffmpeg: {ff or 'not found'}")

    def _download_tool(self, which: str) -> None:
        parent = self.parent()
        if parent is None or not hasattr(parent, "run"):
            return
        from ..cuesplit import download_ffmpeg
        from ..fingerprint import download_fpcalc
        fn = download_fpcalc if which == "fpcalc" else download_ffmpeg
        self.tool_status.setText(f"Downloading {which}… (progress is shown in the main window)")
        parent.run(f"Downloading {which}…", fn, lambda _p: self._refresh_tools())

    def _check_updates(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "check_updates"):
            parent.check_updates(manual=True)

    # skins: preview live, keep on Save, restore on Cancel
    def _preview_skin(self, name: str) -> None:
        parent = self.parent()
        if name and parent is not None and hasattr(parent, "apply_skin"):
            parent.apply_skin(name)

    def reject(self) -> None:
        if self.skin.currentText() != self._orig_skin:
            self._preview_skin(self._orig_skin)
        super().reject()

    def _refresh_skins(self, select: str = "") -> None:
        cur = select or self.skin.currentText()
        self.skin.blockSignals(True)
        self.skin.clear()
        from . import skins
        self.skin.addItems(skins.theme_names())
        self.skin.blockSignals(False)
        self.skin.setCurrentText(cur)
        self._preview_skin(cur)
        parent = self.parent()
        if parent is not None and hasattr(parent, "fill_skin_menu"):
            parent.fill_skin_menu()

    def _import_skin(self) -> None:
        from . import skins
        path, _ = QFileDialog.getOpenFileName(self, "Import skin", str(Path.home()), "Skins (*.json)")
        if not path:
            return
        try:
            name = skins.import_skin(path)
        except ValueError as e:
            QMessageBox.warning(self, "Import skin", f"That isn't a skin MusicMaid can use: {e}")
            return
        self._refresh_skins(select=name)
        QMessageBox.information(self, "Import skin", f"Added the skin \"{name}\". Press Save to keep using it.")

    def _export_skin(self) -> None:
        from . import skins
        name = self.skin.currentText()
        if name not in skins.THEMES:
            QMessageBox.information(self, "Save a copy", "Choose one of the skins first (System follows your "
                                    "desktop and can't be saved as a skin).")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save a copy to edit",
                                              str(Path.home() / f"my-{skins._slug(name)}.json"), "Skins (*.json)")
        if path:
            skins.export_skin(name, path)
            QMessageBox.information(self, "Save a copy", f"Saved. Edit the colours in {Path(path).name}, give it "
                                    "a new name, then use Import skin….")

    def _open_skins(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from . import skins
        d = skins.user_skin_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def save(self) -> None:
        s = self.lib.settings
        s.acoustid_api_key = self.acoustid.text().strip()
        s.fpcalc_path = self.fpcalc.text().strip()
        s.ffmpeg_path = self.ffmpeg.text().strip()
        if self.updates.isChecked() and not s.check_for_updates:
            s.skipped_update = ""
        s.check_for_updates = self.updates.isChecked()
        s.skin = self.skin.currentText()
        s.auto_apply_threshold = self.threshold.value()
        s.prefer_country = self.country.text().strip().upper()
        s.prefer_album_releases = self.prefer_album.isChecked()
        s.write_musicbrainz_ids = self.mbids.isChecked()
        s.genre_from_musicbrainz = self.genre.isChecked()
        s.artwork_sources = [k for k, cb in self.art_checks.items() if cb.isChecked()]
        s.artwork_min_size = self.art_min.value()
        s.artwork_max_size = self.art_max.value()
        s.save_cover_jpg = self.cover_jpg.isChecked()
        s.dupe_fingerprint_threshold = self.dupe_thr.value()
        s.quarantine_folder = self.quarantine.text().strip()
        s.use_recycle_bin = self.recycle.isChecked()
        s.various_artists_name = self.va.text().strip() or "Various Artists"
        save_settings(s)
        self.accept()


# ---------------------------------------------------------------- duplicates
class DuplicatesDialog(QDialog):
    changed = Signal()

    def __init__(self, lib: Library, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicates")
        self.resize(1100, 650)
        self.lib, self.runner = lib, runner
        self.groups = []

        self.use_fp = QCheckBox("Compare audio fingerprints")
        self.use_fp.setChecked(True)
        self.use_tags = QCheckBox("Compare artist/title/length")
        self.use_tags.setChecked(True)
        self.same_album = QCheckBox("Only within the same album")
        find = QPushButton("Find duplicates")
        find.setDefault(True)
        find.clicked.connect(self.find)
        top = QHBoxLayout()
        for w in (self.use_fp, self.use_tags, self.same_album):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(find)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Remove?", "Artist – Title", "Quality", "Length", "Path"])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 140)
        self.tree.setColumnWidth(1, 330)
        self.tree.setColumnWidth(2, 120)
        self.tree.itemChanged.connect(self._item_changed)

        self.summary = QLabel("Click “Find duplicates”. The best copy (lossless, highest bitrate, best tags) "
                              "is pre-selected to keep.")
        self.summary.setWordWrap(True)
        self.merge = QCheckBox("Copy missing tags/artwork from removed copies to the kept one")
        self.merge.setChecked(True)
        remove = QPushButton("Remove checked copies")
        remove.clicked.connect(self.remove)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addWidget(self.merge)
        bottom.addStretch(1)
        bottom.addWidget(remove)
        bottom.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.summary)
        lay.addLayout(bottom)

    def find(self) -> None:
        fp, tg, sa = self.use_fp.isChecked(), self.use_tags.isChecked(), self.same_album.isChecked()
        if not self.runner.run("Finding duplicates…", lambda task: self.lib.find_duplicates(
                task, use_fingerprints=fp, use_tags=tg, same_album_only=sa), self._show):
            QMessageBox.information(self, "Busy", "Another task is running.")

    def _show(self, groups) -> None:
        self.groups = groups
        self.tree.blockSignals(True)
        self.tree.clear()
        for gi, g in enumerate(groups):
            head = QTreeWidgetItem([f"{len(g.tracks)} copies", g.title, "", "",
                                    ", ".join(sorted(g.reasons)) + f"  (similarity {g.similarity:.0%})"])
            f = head.font(1)
            f.setBold(True)
            head.setFont(1, f)
            for i, t in enumerate(g.tracks):
                q = f"{t.codec} " + ("lossless" if t.lossless else f"{t.bitrate} kbps")
                m, s = divmod(int(t.duration), 60)
                it = QTreeWidgetItem([("keep" if i == 0 else "remove"),
                                      f"{t.get('artist', '?')} – {t.get('title', t.filename)}", q, f"{m}:{s:02d}", t.path])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Unchecked if i == 0 else Qt.CheckState.Checked)
                it.setData(0, Qt.ItemDataRole.UserRole, (gi, t.id))
                head.addChild(it)
            self.tree.addTopLevelItem(head)
            head.setExpanded(True)
        self.tree.blockSignals(False)
        self._update_summary()

    def _item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0 or item.parent() is None:
            return
        parent = item.parent()
        checked = [parent.child(i) for i in range(parent.childCount())
                   if parent.child(i).checkState(0) == Qt.CheckState.Checked]
        if len(checked) == parent.childCount():
            self.tree.blockSignals(True)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.blockSignals(False)
            QMessageBox.information(self, "Keep one", "At least one copy of each song must be kept.")
        self.tree.blockSignals(True)
        for i in range(parent.childCount()):
            c = parent.child(i)
            c.setText(0, "remove" if c.checkState(0) == Qt.CheckState.Checked else "keep")
        self.tree.blockSignals(False)
        self._update_summary()

    def _selection(self) -> dict[int, int]:
        remove: dict[int, int] = {}
        for gi in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(gi)
            kids = [head.child(i) for i in range(head.childCount())]
            keep = [k.data(0, Qt.ItemDataRole.UserRole)[1] for k in kids if k.checkState(0) != Qt.CheckState.Checked]
            for k in kids:
                if k.checkState(0) == Qt.CheckState.Checked and keep:
                    remove[k.data(0, Qt.ItemDataRole.UserRole)[1]] = keep[0]
        return remove

    def _update_summary(self) -> None:
        n = len(self._selection())
        self.summary.setText(f"{len(self.groups)} duplicate groups · {n} copies checked for removal. Removed files "
                             f"go to {'the recycle bin' if self.lib.settings.use_recycle_bin else self.lib.settings.quarantine_path} "
                             "and can be restored with Undo.")

    def remove(self) -> None:
        sel = self._selection()
        if not sel:
            return
        if QMessageBox.question(self, "Remove duplicates", f"Remove {len(sel)} duplicate files?") \
                != QMessageBox.StandardButton.Yes:
            return
        merge = self.merge.isChecked()
        self.runner.run("Removing duplicates…", lambda task: self.lib.remove_duplicates(list(sel), sel, task, merge),
                        self._removed)

    def _removed(self, result) -> None:
        n, _ = result
        self.tree.clear()
        self.groups = []
        self.summary.setText(f"Removed {n} files.")
        self.changed.emit()


# ---------------------------------------------------------------- organize
class OrganizeDialog(QDialog):
    changed = Signal()

    def __init__(self, lib: Library, runner: TaskRunner, ids: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Organize {len(ids)} files")
        self.resize(1100, 620)
        self.lib, self.runner, self.ids = lib, runner, ids
        self.moves = []
        s = lib.settings
        form = QFormLayout()
        self.pattern = QLineEdit(s.organize_pattern)
        form.addRow("Pattern", self.pattern)
        help_ = QLabel(PATTERN_HELP)
        help_.setWordWrap(True)
        help_.setObjectName("dim")
        form.addRow("", help_)
        self.dest = QLineEdit(s.organize_destination or (lib.folders[0] if lib.folders else ""))
        form.addRow("Destination", _browse_row(self.dest, self))
        self.copy = QCheckBox("Copy instead of move")
        self.copy.setChecked(s.organize_copy)
        self.skip = QCheckBox("Skip files without artist/title")
        self.skip.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self.copy)
        row.addWidget(self.skip)
        row.addStretch(1)
        preview = QPushButton("Preview")
        preview.clicked.connect(self.preview)
        row.addWidget(preview)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Current location", "New location"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.info = QLabel()
        go = QPushButton("Move files")
        go.clicked.connect(self.go)
        self.copy.toggled.connect(lambda c: go.setText("Copy files" if c else "Move files"))
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.info, 1)
        bottom.addWidget(go)
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(self.table, 1)
        lay.addLayout(bottom)
        self.pattern.textChanged.connect(self.preview)
        self.preview()

    def preview(self) -> None:
        try:
            self.moves = [m for m in self.lib.organize_plan(self.ids, self.pattern.text(), self.dest.text().strip(),
                                                            self.skip.isChecked()) if m.changed]
        except (ValueError, KeyError, IndexError) as e:
            self.info.setText(f"⚠ {e}")
            return
        shown = self.moves[:3000]
        self.table.setRowCount(len(shown))
        for i, m in enumerate(shown):
            self.table.setItem(i, 0, QTableWidgetItem(m.src))
            self.table.setItem(i, 1, QTableWidgetItem(m.dst))
        pending = len(self.lib.db.proposal_ids() & set(self.ids))
        msg = f"{len(self.moves)} files will be {'copied' if self.copy.isChecked() else 'moved'}."
        if pending:
            msg += f"  ⚠ {pending} tracks have unapplied changes — apply them first for best results."
        self.info.setText(msg)

    def go(self) -> None:
        self.preview()
        if not self.moves:
            return
        s = self.lib.settings
        s.organize_pattern = self.pattern.text()
        s.organize_destination = self.dest.text().strip()
        s.organize_copy = self.copy.isChecked()
        save_settings(s)
        moves, copy = list(self.moves), self.copy.isChecked()
        self.runner.run("Organizing files…", lambda task: self.lib.organize(moves, copy, task), self._done)

    def _done(self, result) -> None:
        self.changed.emit()
        self.accept()


# ---------------------------------------------------------------- history
class HistoryDialog(QDialog):
    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo history")
        self.resize(600, 400)
        self.batch: str | None = None
        self.list = QListWidget()
        for batch, label, ts, n in lib.history():
            it = QListWidgetItem(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}   {label}   ({n} changes)")
            it.setData(Qt.ItemDataRole.UserRole, batch)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _: self._undo())
        buttons = QDialogButtonBox()
        undo = buttons.addButton("Undo selected", QDialogButtonBox.ButtonRole.AcceptRole)
        undo.setEnabled(self.list.count() > 0)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self._undo)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Undo operations newest-first for best results:"))
        lay.addWidget(self.list)
        lay.addWidget(buttons)

    def _undo(self) -> None:
        it = self.list.currentItem()
        if it:
            self.batch = it.data(Qt.ItemDataRole.UserRole)
            self.accept()


# ---------------------------------------------------------------- artwork chooser
class _ThumbSignals(QObject):
    loaded = Signal(int, bytes)


class _ThumbJob(QRunnable):
    def __init__(self, idx: int, url: str, sig: _ThumbSignals):
        super().__init__()
        self.idx, self.url, self.sig = idx, url, sig

    def run(self) -> None:
        try:
            data = net.get_bytes(self.url, timeout=30)
        except Exception:
            data = None
        if data:
            self.sig.loaded.emit(self.idx, data)


class _SearchSignals(QObject):
    done = Signal(list)


class _SearchJob(QRunnable):
    def __init__(self, fn, sig):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self) -> None:
        try:
            res = self.fn()
        except Exception:
            res = []
        self.sig.done.emit(res)


class ArtworkDialog(QDialog):
    """Show cover candidates from all sources as a thumbnail grid."""

    def __init__(self, lib: Library, track, parent=None):
        super().__init__(parent)
        tags = lib.effective_tags(track)
        self.setWindowTitle(f"Artwork — {tags.get('albumartist') or tags.get('artist', '?')} – {tags.get('album', '?')}")
        self.resize(900, 600)
        self.cands = []
        self.result: tuple[bytes, str] | None = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(200, 200))
        self.grid.setGridSize(QSize(230, 270))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.itemDoubleClicked.connect(lambda _: self._use())
        self.status = QLabel("Searching Cover Art Archive, iTunes and Deezer…")

        q = QHBoxLayout()
        self.artist = QLineEdit(tags.get("albumartist") or tags.get("artist", ""))
        self.album = QLineEdit(tags.get("album", ""))
        search = QPushButton("Search again")
        search.clicked.connect(lambda: self._search(lib, None))
        q.addWidget(QLabel("Artist"))
        q.addWidget(self.artist)
        q.addWidget(QLabel("Album"))
        q.addWidget(self.album)
        q.addWidget(search)

        file_btn = QPushButton("From file…")
        file_btn.clicked.connect(self._from_file)
        use = QPushButton("Use selected")
        use.setDefault(True)
        use.clicked.connect(self._use)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(file_btn)
        bottom.addWidget(use)
        bottom.addWidget(cancel)
        lay = QVBoxLayout(self)
        lay.addLayout(q)
        lay.addWidget(self.grid, 1)
        lay.addLayout(bottom)

        self._thumb_sig = _ThumbSignals()
        self._thumb_sig.loaded.connect(self._thumb_loaded)
        self._search_sig = _SearchSignals()
        self._search_sig.done.connect(self._show)
        self._search(lib, track)

    def _search(self, lib: Library, track) -> None:
        from ..providers import artwork as artprov
        self.grid.clear()
        self.status.setText("Searching…")
        if track is not None:
            fn = lambda: lib.artwork_candidates(track)  # noqa: E731
        else:
            artist, album = self.artist.text(), self.album.text()
            fn = lambda: artprov.search(artist, album, sources=lib.settings.artwork_sources)  # noqa: E731
        self.pool.start(_SearchJob(fn, self._search_sig))

    def _show(self, cands) -> None:
        self.cands = cands
        self.status.setText(f"{len(cands)} candidates — double-click to use one")
        for i, c in enumerate(cands):
            it = QListWidgetItem(f"{c.source}\n{c.artist} – {c.title}\n"
                                 + (f"{c.width}×{c.height}" if c.width else "original size"))
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.grid.addItem(it)
            self.pool.start(_ThumbJob(i, c.thumb_url, self._thumb_sig))

    def _thumb_loaded(self, idx: int, data: bytes) -> None:
        pm = QPixmap()
        if pm.loadFromData(data) and idx < self.grid.count():
            self.grid.item(idx).setIcon(QIcon(pm))

    def _use(self) -> None:
        it = self.grid.currentItem()
        if not it:
            return
        c = self.cands[it.data(Qt.ItemDataRole.UserRole)]
        self.status.setText("Downloading full-size image…")
        self.repaint()
        data = net.get_bytes(c.url, timeout=60)
        if not data:
            QMessageBox.warning(self, "Artwork", "Download failed.")
            return
        self.result = (data, c.label)
        self.accept()

    def _from_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Choose image", str(Path.home()), "Images (*.jpg *.jpeg *.png *.webp)")
        if p:
            self.result = (Path(p).read_bytes(), f"file {Path(p).name}")
            self.accept()


# ---------------------------------------------------------------- AcoustID key
class AcoustIDDialog(QDialog):
    """Explains MusicMaid with and without AcoustID, and takes (and checks) the user's own key."""

    def __init__(self, lib: Library, parent=None, first_run: bool = False):
        from ..guidance import (ACOUSTID_INTRO, ACOUSTID_PRIVACY, ACOUSTID_SIGNUP, ACOUSTID_WITH,
                                ACOUSTID_WITHOUT)
        super().__init__(parent)
        self.lib = lib
        self.never = False
        self.setWindowTitle("Identify songs by their sound (optional)")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = QLabel(ACOUSTID_INTRO.replace(ACOUSTID_SIGNUP, f'<a href="{ACOUSTID_SIGNUP}">acoustid.org</a>'))
        for text in (intro, QLabel(f"<b>{ACOUSTID_WITH.split(':', 1)[0]}:</b>{ACOUSTID_WITH.split(':', 1)[1]}"),
                     QLabel(f"<b>{ACOUSTID_WITHOUT.split(':', 1)[0]}:</b>{ACOUSTID_WITHOUT.split(':', 1)[1]}"),
                     QLabel(f"<small>{ACOUSTID_PRIVACY}</small>")):
            text.setWordWrap(True)
            text.setOpenExternalLinks(True)
            lay.addWidget(text)
        row = QHBoxLayout()
        self.key = QLineEdit(lib.settings.acoustid_api_key)
        self.key.setPlaceholderText("Paste your AcoustID API key here")
        row.addWidget(QLabel("API key"))
        row.addWidget(self.key, 1)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton("Check and Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Continue without a key" if first_run else "Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        if first_run:
            never = buttons.addButton("Don't ask again", QDialogButtonBox.ButtonRole.DestructiveRole)
            never.clicked.connect(self._never)
        elif lib.settings.acoustid_api_key:
            remove = buttons.addButton("Remove Key", QDialogButtonBox.ButtonRole.DestructiveRole)
            remove.clicked.connect(self._remove)
        self.save_btn.clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def save(self) -> None:
        from ..providers.acoustid import check_key
        key = self.key.text().strip()
        if not key:
            self.result.setText("Paste a key first, or continue without one.")
            return
        self.result.setText("Checking the key with AcoustID…")
        self.setEnabled(False)
        QApplication.processEvents()
        ok = check_key(key)
        self.setEnabled(True)
        if ok is False:
            self.result.setText("<span style='color:#da3633'>AcoustID didn't accept this key. Check that you "
                                "copied the <b>API key</b> of your application.</span>")
            return
        s = self.lib.settings
        s.acoustid_api_key = key
        s.offer_acoustid_key = False
        save_settings(s)
        if ok is None:
            QMessageBox.information(self, APP_NAME, "Saved. The key couldn't be checked right now (no connection?), "
                                    "it will be used once AcoustID is reachable.")
        self.accept()

    def _never(self) -> None:
        self.lib.settings.offer_acoustid_key = False
        save_settings(self.lib.settings)
        self.never = True
        self.reject()

    def _remove(self) -> None:
        self.lib.settings.acoustid_api_key = ""
        save_settings(self.lib.settings)
        self.accept()


# ---------------------------------------------------------------- tags from folder names
class PathTagsDialog(QDialog):
    """Choose automatic or a %artist%/%album%/... pattern, with a live preview of what each track gets."""

    COLS = [("artist", "Artist"), ("album", "Album"), ("date", "Year"), ("discnumber", "Disc"),
            ("tracknumber", "#"), ("title", "Title")]

    def __init__(self, lib: Library, tracks, parent=None):
        from .. import pathtags
        super().__init__(parent)
        self.setWindowTitle("Tags from Folder Names")
        self.resize(980, 600)
        self.lib, self.tracks = lib, tracks
        from PySide6.QtWidgets import QButtonGroup, QRadioButton
        lay = QVBoxLayout(self)
        intro = QLabel(f"Fill in tags for <b>{len(tracks)} track{'s' if len(tracks) != 1 else ''}</b> from "
                       "their folder and file names. You'll review the changes before anything is written.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.auto = QRadioButton("Automatic: recognise common layouts (Artist/Album (Year)/01 - Title, "
                                 "Artist - Album/Title, …)")
        self.use_pattern = QRadioButton("Use a pattern:")
        grp = QButtonGroup(self)
        grp.addButton(self.auto)
        grp.addButton(self.use_pattern)
        self.auto.setChecked(True)
        lay.addWidget(self.auto)
        row = QHBoxLayout()
        row.addWidget(self.use_pattern)
        self.pattern = QComboBox()
        self.pattern.setEditable(True)
        self.pattern.addItems(pathtags.EXAMPLES)
        self.pattern.setCurrentText(pathtags.EXAMPLES[1])
        row.addWidget(self.pattern, 1)
        lay.addLayout(row)
        help_ = QLabel(pathtags.PATTERN_HELP)
        help_.setObjectName("dim")
        help_.setWordWrap(True)
        lay.addWidget(help_)
        self.overwrite = QCheckBox("Overwrite existing tags (otherwise only empty fields are filled)")
        lay.addWidget(self.overwrite)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.COLS) + 1)
        self.table.setHorizontalHeaderLabels(["File", *[c[1] for c in self.COLS]])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        self.ok = buttons.addButton("Propose Changes", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._preview)
        for sig in (self.auto.toggled, self.overwrite.toggled, self.pattern.currentTextChanged):
            sig.connect(lambda *_: self._timer.start())
        self.pattern.lineEdit().textEdited.connect(lambda *_: self.use_pattern.setChecked(True))
        self.pattern.activated.connect(lambda *_: self.use_pattern.setChecked(True))
        self._preview()

    def result_options(self) -> tuple[str | None, bool]:
        return (self.pattern.currentText().strip() if self.use_pattern.isChecked() else None,
                self.overwrite.isChecked())

    def _preview(self) -> None:
        from PySide6.QtGui import QFont
        from .. import pathtags
        pattern, overwrite = self.result_options()
        try:
            compiled = pathtags.compile_pattern(pattern) if pattern else None
        except ValueError as e:
            self.summary.setText(f"<span style='color:#da3633'>Pattern problem: {e}</span>")
            self.ok.setEnabled(False)
            self.table.setRowCount(0)
            return
        shown = self.tracks[:300]
        changing = 0
        self.table.setRowCount(len(shown))
        bold = QFont()
        bold.setBold(True)
        for r, t in enumerate(shown):
            guessed = pathtags.guess(t, self.lib.folders, pattern, compiled)
            ch = pathtags.changes(t, guessed, overwrite)
            changing += bool(ch)
            self.table.setItem(r, 0, QTableWidgetItem(t.filename))
            self.table.item(r, 0).setToolTip(t.path)
            for c, (field, _) in enumerate(self.COLS, 1):
                val = ch.get(field, t.tags.get(field, ""))
                it = QTableWidgetItem(val)
                if field in ch:
                    it.setFont(bold)
                    it.setToolTip(f"was: {t.tags.get(field) or '(empty)'}")
                self.table.setItem(r, c, it)
        if len(self.tracks) > len(shown):
            changing_txt = f"{changing} of the first {len(shown)} tracks shown would change"
        else:
            changing_txt = f"{changing} of {len(self.tracks)} tracks would change"
        self.summary.setText(f"<b>{changing_txt}</b> (new values in bold; hover to see the old value).")
        self.ok.setEnabled(changing > 0 or len(self.tracks) > len(shown))


# ---------------------------------------------------------------- CUE sheets
class CueDialog(QDialog):
    """Pick CUE sheets to split; the main window runs the split."""

    def __init__(self, lib: Library, parent=None, folder: str | None = None):
        from .. import cuesplit
        super().__init__(parent)
        self.setWindowTitle("Split CUE Sheets")
        self.resize(1000, 560)
        self.lib = lib
        self.chosen: list = []
        lay = QVBoxLayout(self)
        intro = QLabel("Albums stored as <b>one big audio file plus a .cue sheet</b> are split into separate, "
                       "tagged track files. Lossless images become FLAC tracks cut at exact sample positions; "
                       "MP3 and other lossy images are cut without re-encoding.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        where = folder or ""
        self.where = QLabel(f"Looking in: <b>{where or 'the whole library'}</b>")
        lay.addWidget(self.where)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.sheets = lib.cue_sheets(where or None)
        finally:
            QApplication.restoreOverrideCursor()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "CUE sheet", "Album", "Tracks", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 28)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 230)
        self.table.setRowCount(len(self.sheets))
        ready = 0
        for r, sh in enumerate(self.sheets):
            status, ok = "Ready to split", True
            if sh.problems:
                status, ok = sh.problems[0], False
            elif not sh.splittable:
                status, ok = "Already one file per track", False
            else:
                try:
                    if cuesplit.already_split(cuesplit.plan(sh)):
                        status, ok = "Already split", False
                except cuesplit.CueError as e:
                    status, ok = str(e), False
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if ok else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, chk)
            name = QTableWidgetItem(sh.path + ("  (embedded)" if sh.embedded else ""))
            name.setToolTip(sh.path)
            self.table.setItem(r, 1, name)
            self.table.setItem(r, 2, QTableWidgetItem(" - ".join(x for x in (sh.performer, sh.title) if x)))
            self.table.setItem(r, 3, QTableWidgetItem(str(len(sh.tracks))))
            st = QTableWidgetItem(status)
            if not ok:
                st.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
            self.table.setItem(r, 4, st)
            ready += ok
        lay.addWidget(self.table, 1)
        found = QLabel(f"Found {len(self.sheets)} CUE sheet{'s' if len(self.sheets) != 1 else ''}, "
                       f"{ready} ready to split." if self.sheets else
                       "No CUE sheets found here. They're .cue files next to a large audio file, or embedded "
                       "in a FLAC file.")
        found.setWordWrap(True)
        lay.addWidget(found)

        opts = QFormLayout()
        self.dest = QLineEdit()
        self.dest.setPlaceholderText("next to each CUE sheet")
        opts.addRow("Put the tracks in", _browse_row(self.dest, self))
        self.remove = QCheckBox("Afterwards, move the big file and its .cue to the quarantine folder (Undo puts "
                                "them back)")
        self.remove.setChecked(True)
        opts.addRow("", self.remove)
        lay.addLayout(opts)

        self.ffmpeg_note = QLabel()
        self.ffmpeg_note.setWordWrap(True)
        lay.addWidget(self.ffmpeg_note)
        buttons = QDialogButtonBox()
        self.go = buttons.addButton("Split Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        self.go.setObjectName("primary")
        self.get_ffmpeg = None
        if cuesplit.can_download_ffmpeg():
            self.get_ffmpeg = buttons.addButton("Download ffmpeg…", QDialogButtonBox.ButtonRole.ActionRole)
            self.get_ffmpeg.clicked.connect(self._download)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._check_ffmpeg()

    def _check_ffmpeg(self) -> None:
        from .. import cuesplit
        have = cuesplit.find_ffmpeg()
        self.go.setEnabled(bool(have) and bool(self.sheets))
        if self.get_ffmpeg:
            self.get_ffmpeg.setVisible(not have)
        self.ffmpeg_note.setVisible(not have)
        self.ffmpeg_note.setText("" if have else "<b>ffmpeg is needed to split audio.</b> " + cuesplit.ffmpeg_help())

    def _download(self) -> None:
        parent = self.parent()
        from .. import cuesplit
        self.ffmpeg_note.setText("Downloading ffmpeg… (progress is shown in the main window's status bar)")
        if parent is not None and hasattr(parent, "run"):
            parent.run("Downloading ffmpeg…", cuesplit.download_ffmpeg, lambda _p: self._check_ffmpeg())

    def _accept(self) -> None:
        self.chosen = [sh for r, sh in enumerate(self.sheets)
                       if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]
        if not self.chosen:
            QMessageBox.information(self, "Split CUE sheets", "Tick at least one CUE sheet to split.")
            return
        self.accept()

    def options(self) -> tuple[str | None, bool]:
        return self.dest.text().strip() or None, self.remove.isChecked()


# ---------------------------------------------------------------- preview before applying
class ApplyPreviewDialog(QDialog):
    """Every proposed change (old -> new) with checkboxes; only ticked changes are written."""

    def __init__(self, lib: Library, ids: list[int], parent=None):
        from .. import tags as tagio
        super().__init__(parent)
        self.setWindowTitle("Preview Changes")
        self.resize(1000, 640)
        self.lib = lib
        lay = QVBoxLayout(self)
        intro = QLabel("These changes will be written to your files. Untick anything you don't want: unticked "
                       "changes stay in <i>Needs review</i>. Everything written can be undone.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Change", "Now", "Will become"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 280)
        lay.addWidget(self.tree, 1)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        for text, state in (("Tick All", Qt.CheckState.Checked), ("Untick All", Qt.CheckState.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, st=state: self._set_all(st))
            row.addWidget(b)
        exp = QPushButton("Expand All")
        exp.clicked.connect(self.tree.expandAll)
        col = QPushButton("Collapse All")
        col.clicked.connect(self.tree.collapseAll)
        row.addWidget(exp)
        row.addWidget(col)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QDialogButtonBox()
        self.go = buttons.addButton("Write Changes", QDialogButtonBox.ButtonRole.AcceptRole)
        self.go.setObjectName("primary")
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        pending = lib.db.proposal_ids()
        self.ids = [i for i in ids if i in pending]
        self.tree.blockSignals(True)
        for t in lib.tracks(self.ids):
            p = lib.db.proposal(t.id)
            if not p:
                continue
            who = " - ".join(x for x in (t.get("artist"), t.get("title")) if x) or t.filename
            top = QTreeWidgetItem([who, "", f"from {p.source}" + (f" ({p.score:.0%})" if p.tags else "")])
            top.setToolTip(0, t.path)
            top.setData(0, Qt.ItemDataRole.UserRole, (t.id, None))
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            for field in tagio.FIELD_NAMES + [k for k in p.tags if k not in tagio.FIELD_LABELS]:
                if field not in p.tags or (p.tags[field] or "") == (t.tags.get(field) or ""):
                    continue
                child = QTreeWidgetItem([tagio.FIELD_LABELS.get(field, field), t.tags.get(field) or "(empty)",
                                         p.tags[field] or "(remove)"])
                child.setData(0, Qt.ItemDataRole.UserRole, (t.id, field))
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                top.addChild(child)
            if p.art is not None:
                _, w, h = tagio.image_info(p.art)
                now = f"{t.art_w}×{t.art_h}" if t.has_art else "(none)"
                child = QTreeWidgetItem(["Cover art", now, f"{w}×{h} from {p.art_source or 'artwork search'}"])
                child.setData(0, Qt.ItemDataRole.UserRole, (t.id, "__art__"))
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                top.addChild(child)
            if top.childCount():
                top.setCheckState(0, Qt.CheckState.Checked)
                self.tree.addTopLevelItem(top)
        self.tree.blockSignals(False)
        if self.tree.topLevelItemCount() <= 30:
            self.tree.expandAll()
        self.tree.itemChanged.connect(lambda *_: self._update())
        self._update()

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _set_all(self, state) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)

    def _update(self) -> None:
        on = [it for it in self._items() if it.checkState(0) == Qt.CheckState.Checked]
        tracks = {it.data(0, Qt.ItemDataRole.UserRole)[0] for it in on}
        self.summary.setText(f"<b>{len(on)} change{'s' if len(on) != 1 else ''} in {len(tracks)} "
                             f"file{'s' if len(tracks) != 1 else ''}</b> will be written.")
        self.go.setText(f"Write {len(on)} Change{'s' if len(on) != 1 else ''}")
        self.go.setEnabled(bool(on))

    def selection(self) -> tuple[list[int], dict[int, set[str]]]:
        """(track ids to write, fields to leave out per track)."""
        write, exclude = set(), {}
        for it in self._items():
            tid, field = it.data(0, Qt.ItemDataRole.UserRole)
            if it.checkState(0) == Qt.CheckState.Checked:
                write.add(tid)
            else:
                exclude.setdefault(tid, set()).add(field)
        return sorted(write), exclude
