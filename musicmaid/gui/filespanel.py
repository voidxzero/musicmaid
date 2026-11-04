"""The Files panel: everything that's really in the chosen folder (covers, .cue, .log, …), next to the tracks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileSystemModel, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton,
    QTreeView, QVBoxLayout, QWidget,
)

from ..tags import AUDIO_EXTENSIONS


class FilesPanel(QWidget):
    file_clicked = Signal(str)          # an audio file was clicked: select its track
    status = Signal(str)                # a short message for the status bar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = ""
        self._syncing = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("dim")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = QPushButton("Open in File Manager")
        open_btn.clicked.connect(lambda: self.root and QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)))
        head.addWidget(self.title, 1)
        head.addWidget(open_btn)
        lay.addLayout(head)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.model.setReadOnly(True)
        self.view = QTreeView()
        self.view.setModel(self.model)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.view.setAlternatingRowColors(True)
        self.view.setUniformRowHeights(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.view.header().setStretchLastSection(False)
        for col, w in ((1, 80), (2, 110), (3, 140)):
            self.view.setColumnWidth(col, w)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.clicked.connect(self._clicked)
        self.view.doubleClicked.connect(self._open)
        self.empty = QLabel("Pick a folder in the tree to see its files.")
        self.empty.setObjectName("dim")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.empty, 1)
        self.set_folder("")

    # ------------------------------------------------------------ folder
    def set_folder(self, folder: str) -> None:
        folder = folder or ""
        if folder == self.root:
            return
        self.root = folder
        has = bool(folder) and Path(folder).is_dir()
        self.view.setVisible(has)
        self.empty.setVisible(not has)
        if has:
            self.view.setRootIndex(self.model.setRootPath(folder))
            self.title.setText(f"Files in <b>{Path(folder).name or folder}</b>")
            self.title.setToolTip(folder)
        else:
            self.title.setText("Files")
            self.title.setToolTip("")

    def _path(self, index: QModelIndex) -> str:
        return self.model.filePath(index) if index.isValid() else ""

    def selected_paths(self) -> list[str]:
        return [self._path(i) for i in self.view.selectionModel().selectedRows(0)]

    # ------------------------------------------------------------ sync with the track list
    def show_track(self, path: str) -> None:
        """Highlight a track's file (if it's under the shown folder) without clicking it."""
        if not path or not self.root or self._syncing:
            return
        root = self.root.rstrip("/\\")
        if not (path.startswith(root + "/") or path.startswith(root + "\\")):
            return
        idx = self.model.index(path)
        if idx.isValid():
            self._syncing = True
            try:
                parent = idx.parent()
                while parent.isValid() and parent != self.view.rootIndex():
                    self.view.expand(parent)
                    parent = parent.parent()
                self.view.setCurrentIndex(idx)
                self.view.scrollTo(idx)
            finally:
                self._syncing = False

    def _clicked(self, index: QModelIndex) -> None:
        path = self._path(index)
        if path and Path(path).suffix.lower() in AUDIO_EXTENSIONS and not self._syncing:
            self._syncing = True
            try:
                self.file_clicked.emit(path)
            finally:
                self._syncing = False

    def _open(self, index: QModelIndex) -> None:
        path = self._path(index)
        if path and not self.model.isDir(index):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------ context menu
    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        n = text.count("\n") + 1
        self.status.emit(f"Copied {n} lines to the clipboard" if n > 1 else f"Copied: {text}")

    def _menu(self, pos) -> None:
        idx = self.view.indexAt(pos)
        paths = self.selected_paths() or ([self._path(idx)] if idx.isValid() else [])
        menu = QMenu(self)
        if paths:
            first = paths[0]
            menu.addAction("Open", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(first)))
            menu.addAction("Show in File Manager",
                           lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(first).parent))))
            menu.addSeparator()
            menu.addAction("Copy Name", lambda: self._copy("\n".join(Path(p).name for p in paths)))
            menu.addAction("Copy Path", lambda: self._copy("\n".join(paths)))
        if self.root:
            menu.addSeparator()
            menu.addAction("Copy This Folder's Path", lambda: self._copy(self.root))
        if not menu.isEmpty():
            menu.exec(self.view.viewport().mapToGlobal(pos))
