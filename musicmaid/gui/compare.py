"""Side-by-side "Original | New" comparison (manual work on the selected tracks) and the album-by-album review
that follows Fix Whole Library."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import tags as tagio
from ..db import Track
from ..library import Library

# the fields shown in the comparison, in order (the rest of the editable fields follow)
MAIN_FIELDS = ["title", "artist", "album", "albumartist", "tracknumber", "totaltracks", "discnumber", "date",
               "genre", "composer"]
SHOW_FIELDS = MAIN_FIELDS + [f for f in tagio.EDITABLE_FIELDS if f not in MAIN_FIELDS]
DIFFERENT = "(different values)"
PER_TRACK = "(changes per track)"
MISSING = "(missing)"
REQUIRED = {"title", "artist", "album", "tracknumber"}     # empty ones are problems
ART_SIZE = 120


def _pixmap(data: bytes | None, size: int = ART_SIZE) -> QPixmap:
    pm = QPixmap()
    if data:
        pm.loadFromData(data)
        pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return pm


def _shrinkable(label: QLabel) -> None:
    """Let a text label wrap (even inside long words) and be narrower than its text, instead of forcing the
    panel it sits in to grow wider than the window."""
    from PySide6.QtWidgets import QSizePolicy
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


class SquareLabel(QLabel):
    """A square label that grows with the width it is given and rescales its picture to fill itself."""

    def __init__(self, min_size: int, max_size: int):
        super().__init__()
        from PySide6.QtWidgets import QSizePolicy
        self.src = QPixmap()
        self.setMinimumSize(min_size, min_size)
        self.setMaximumSize(max_size, max_size)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.maximumWidth(), self.maximumWidth())

    def set_source(self, pm: QPixmap) -> None:
        self.src = pm
        self._rescale()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.height() != self.width():
            self.setFixedHeight(self.width())      # stay square (the frame is drawn on the label itself)
        self._rescale()

    def _rescale(self) -> None:
        if self.src.isNull():
            self.setPixmap(QPixmap())
            return
        side = max(8, min(self.width(), self.height()) - 8)
        self.setPixmap(self.src.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))


class ArtBox(QWidget):
    """A titled cover-art box; the "New" one accepts dropped images."""
    dropped = Signal(bytes, str)

    def __init__(self, title: str, accept_drops: bool = False, size: int = ART_SIZE, flexible: bool = False):
        """flexible: the picture grows to fill the width it's given (up to `size`) instead of a fixed square."""
        super().__init__()
        self.size = size
        self.flexible = flexible
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QLabel(f"<b>{title}</b>")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image = SquareLabel(ART_SIZE + 8, size + 8) if flexible else QLabel()
        self.image.setObjectName("artbox")
        # an even frame on all sides (the skins' sunken "cover" style hides two edges on dark themes)
        self.image.setStyleSheet("QLabel#artbox { border: 1px solid palette(mid); border-radius: 3px; "
                                 "background: palette(base); padding: 0px; }")
        if not flexible:
            self.image.setFixedSize(size + 8, size + 8)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setWordWrap(True)
        self.caption = QLabel()
        self.caption.setObjectName("dim")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _shrinkable(self.caption)          # a long cover title must wrap, not widen the whole panel
        lay.addWidget(head)
        lay.addWidget(self.image, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.caption)
        self.setAcceptDrops(accept_drops)

    def show_art(self, data: bytes | None, caption: str, empty: str = "No artwork") -> None:
        if data:
            self.image.setText("")
            if self.flexible:
                pm = QPixmap()
                pm.loadFromData(data)
                self.image.set_source(pm)
            else:
                self.image.setPixmap(_pixmap(data, self.size))
        else:
            if self.flexible:
                self.image.set_source(QPixmap())
            self.image.setPixmap(QPixmap())
            self.image.setText(empty)
        self.caption.setText(caption)

    def dragEnterEvent(self, e):
        if e.mimeData().hasImage() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for url in md.urls():
                p = Path(url.toLocalFile())
                if p.is_file():
                    self.dropped.emit(p.read_bytes(), f"file {p.name}")
                    return
        if md.hasImage():
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            md.imageData().save(buf, "PNG")
            self.dropped.emit(bytes(buf.data()), "dropped image")


def folder_art_button(parent, on_pick) -> QPushButton:
    """A button offering the image files already in the album folder (hidden when there are none)."""
    b = QPushButton()
    b.setToolTip("This folder already has a cover image: use it instead")
    b.setVisible(False)
    b._images = []

    def clicked():
        if len(b._images) == 1:
            on_pick(b._images[0][0])
    b.clicked.connect(clicked)
    return b


def show_folder_art(b: QPushButton, images: list[tuple[str, int, int]], current_source: str | None, on_pick) -> None:
    from PySide6.QtWidgets import QMenu
    images = [i for i in images if f"folder: {Path(i[0]).name}" != (current_source or "")]
    b._images = images
    b.setVisible(bool(images))
    b.setMenu(None)
    if not images:
        return
    from html import escape
    if len(images) == 1:
        path, w, h = images[0]
        b.setText(f"Use {Path(path).name}\nfrom this folder ({w}×{h})")
        b.setToolTip(f"This folder already has a cover image:<br><img src='{escape(path)}' width='220'>"
                     f"<br>{escape(Path(path).name)} · {w}×{h}")
    else:
        b.setText(f"Use an image\nfrom this folder ({len(images)})…")
        b.setToolTip("This folder has several images: " + ", ".join(Path(p).name for p, _, _ in images))
        m = QMenu(b)
        for path, w, h in images:
            m.addAction(f"{Path(path).name}  ({w}×{h})", lambda p=path: on_pick(p))
        b.setMenu(m)


def _common(values: list[str]) -> str:
    vals = set(values)
    return next(iter(vals)) if len(vals) == 1 else DIFFERENT


# ---------------------------------------------------------------- manual: the selected tracks
class ComparePanel(QWidget):
    """Original tags and art on the left, the new (proposed) ones on the right. The New column can be typed in;
    nothing is written until Apply."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.lib: Library = win.lib
        self.tracks: list[Track] = []
        self._filling = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 0, 0)

        self.heading = QLabel()
        self.heading.setWordWrap(True)
        self.heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.heading)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setObjectName("problems")
        lay.addWidget(self.problems)

        arts = QHBoxLayout()
        self.art_old = ArtBox("Original", size=420, flexible=True)
        self.art_new = ArtBox("New", accept_drops=True, size=420, flexible=True)
        self.art_new.dropped.connect(self._set_art)
        arts.addWidget(self.art_old)
        arts.addWidget(self.art_new)
        lay.addLayout(arts)
        art_btns = QHBoxLayout()
        art_btns.addStretch(1)
        b = QPushButton("Find Artwork Online…")
        b.setToolTip("Pick a cover from the Cover Art Archive, iTunes or Deezer for the selected tracks")
        b.clicked.connect(win.choose_artwork)
        art_btns.addWidget(b)
        b = QPushButton("From File…")
        b.setToolTip("Use an image file as the new cover (you can also drop an image on the New box)")
        b.clicked.connect(self._art_from_file)
        art_btns.addWidget(b)
        lay.addLayout(art_btns)
        self.b_folder_art = folder_art_button(self, self._use_folder_image)
        lay.addWidget(self.b_folder_art)

        self.table = QTableWidget(len(SHOW_FIELDS), 3)
        self.table.setHorizontalHeaderLabels(["", "Original", "New"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.SelectedClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(22)
        for r, f in enumerate(SHOW_FIELDS):
            lbl = QTableWidgetItem(tagio.FIELD_LABELS[f])
            lbl.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, lbl)
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table, 1)

        self.source = QLabel()
        _shrinkable(self.source)
        lay.addWidget(self.source)
        hint = QLabel("Double-click a value in the New column to change it yourself.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        btns = QHBoxLayout()
        self.b_discard = QPushButton("Discard Changes")
        self.b_discard.setToolTip("Forget the new values of the selected tracks (the files aren't touched)")
        self.b_discard.clicked.connect(win.discard)
        self.b_apply = QPushButton("Apply")
        self.b_apply.setObjectName("primary")
        self.b_apply.setMinimumHeight(30)
        self.b_apply.clicked.connect(win.apply)
        btns.addWidget(self.b_discard)
        btns.addWidget(self.b_apply, 1)
        lay.addLayout(btns)
        self.info = QLabel()
        self.info.setObjectName("dim")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        _shrinkable(self.info)
        lay.addWidget(self.info)
        self.show_tracks([])

    # ------------------------------------------------------------ filling
    def show_tracks(self, tracks: list[Track]) -> None:
        self.tracks = tracks
        n = len(tracks)
        self._filling = True
        try:
            self._fill(tracks)
        finally:
            self._filling = False

    def _fill(self, tracks: list[Track]) -> None:
        from .mainwindow import GREEN, RED
        from ..cleanup import problems as find_problems
        n = len(tracks)
        self.table.setEnabled(n > 0)
        if not tracks:
            self.heading.setText("<b>Select one or more tracks</b> in the list to see and change their tags.")
            for r in range(len(SHOW_FIELDS)):
                for c in (1, 2):
                    self.table.setItem(r, c, QTableWidgetItem(""))
            self.art_old.show_art(None, "")
            self.art_new.show_art(None, "")
            self.b_folder_art.setVisible(False)
            self.problems.hide()
            self.source.clear()
            self.info.clear()
            self.b_apply.setEnabled(False)
            self.b_discard.setEnabled(False)
            self.b_apply.setText("Apply")
            return
        found = self.lib.db.proposals([t.id for t in tracks])      # one query, not one per track
        props = {t.id: found.get(t.id) for t in tracks}
        changed_tracks = sum(1 for p in props.values() if p and (p.tags or p.art is not None))
        t0 = tracks[0]
        title = t0.get("title") or t0.filename
        self.heading.setText(f"<b>{title}</b>" if n == 1 else f"<b>{n} tracks selected</b>")
        tint = QColor(GREEN)
        tint.setAlpha(60)
        red_tint = QColor(RED)
        red_tint.setAlpha(55)
        italic = QFont()
        italic.setItalic(True)
        # what needs fixing, in red, before anything else
        from ..cleanup import fixable
        counts: dict[str, int] = {}
        notes: dict[str, int] = {}
        for t in tracks:
            probs = self.lib.problems_of(t)
            fix = fixable(probs)
            for pr in probs:
                key = pr.split(" (")[0]
                bucket = counts if pr in fix else notes
                bucket[key] = bucket.get(key, 0) + 1
        if counts or notes:
            def items(d):
                return ", ".join(k if n == 1 else f"{k} ({c} of {n})" for k, c in d.items())
            html = ""
            if counts:
                html += f"<span style='color:{QColor(RED).name()}'><b>⚠ Needs fixing:</b> {items(counts)}</span>"
            if notes:
                from .mainwindow import AMBER
                html += ("<br>" if html else "") + f"<span style='color:{QColor(AMBER).name()}'>Note: {items(notes)}</span>"
            self.problems.setText(html)
            edge = QColor(RED if counts else GREEN).name()
            self.problems.setStyleSheet(f"QLabel#problems {{ border: 1px solid {edge}; "
                                        "border-radius: 3px; padding: 4px; }")
            self.problems.show()
        else:
            self.problems.hide()
        bold = QFont()
        bold.setBold(True)
        changes = 0
        for r, f in enumerate(SHOW_FIELDS):
            olds = [t.tags.get(f, "") for t in tracks]
            news = [(props[t.id].tags[f] if props[t.id] and f in props[t.id].tags else t.tags.get(f, ""))
                    for t in tracks]
            old, new = _common(olds), _common(news)
            if new == DIFFERENT and olds != news:
                new = PER_TRACK
            o = QTableWidgetItem(old)
            o.setFlags(Qt.ItemFlag.ItemIsEnabled)          # the Original column is read-only
            o.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
            label = self.table.item(r, 0)
            label.setForeground(self.palette().color(self.palette().ColorRole.WindowText))
            if f in REQUIRED and any(not v for v in olds):
                o.setText(MISSING if all(not v for v in olds) else old)
                o.setForeground(QColor(RED))
                o.setFont(italic)
                label.setForeground(QColor(RED))
            nw = QTableWidgetItem(new)
            nw.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)
            nw.setData(Qt.ItemDataRole.UserRole, f)
            differs = olds != news
            if differs:
                changes += 1
                nw.setBackground(tint)
                nw.setFont(bold)
                nw.setToolTip("Changed. Apply writes this to the file" + ("s" if n > 1 else ""))
            if f in REQUIRED and any(not v for v in news):
                nw.setBackground(red_tint)
                nw.setToolTip("Still missing: double-click to type it, or use Look Up Tags")
            self.table.setItem(r, 1, o)
            self.table.setItem(r, 2, nw)
        # artwork
        old_art = tagio.read_artwork(t0.path) if t0.has_art else None
        small = old_art is not None and min(old_art.width, old_art.height) < self.lib.settings.artwork_min_size
        red = QColor(RED).name()
        self.art_old.show_art(old_art.data if old_art else None,
                              f"<span style='color:{red}'>{old_art.width}×{old_art.height} - too small</span>"
                              if small else (f"{old_art.width}×{old_art.height}" if old_art else
                                             f"<span style='color:{red}'><b>No artwork</b></span>"),
                              "No artwork")
        p0 = props[t0.id]
        if p0 and p0.art is not None:
            _, w, h = tagio.image_info(p0.art)
            self.art_new.show_art(p0.art, f"{w}×{h} · {p0.art_source or 'new'}")
            changes += 1
        else:
            self.art_new.show_art(old_art.data if old_art else None,
                                  "unchanged" if old_art else "", "Drop an image here")
        # an image file already in the album folder? offer it
        folders = {t.folder for t in tracks}
        imgs = self.lib.folder_images(next(iter(folders))) if len(folders) == 1 else []
        show_folder_art(self.b_folder_art, imgs, p0.art_source if p0 and p0.art is not None else None,
                        self._use_folder_image)
        # source and buttons
        with_p = [p for p in props.values() if p]
        if with_p:
            p = with_p[0]
            note = f" · {p.note}" if p.note else ""
            conf = f" · {p.score:.0%} sure" if p.tags else ""
            self.source.setText(f"New values from <b>{p.source}</b>{conf}{note}")
        else:
            self.source.setText("No changes yet. Use <b>Look Up Tags</b>, <b>Find Artwork</b> or "
                                "<b>Clean Up</b> above, or type a new value.")
        self.b_apply.setEnabled(changed_tracks > 0)
        self.b_discard.setEnabled(changed_tracks > 0)
        self.b_apply.setText("Apply" if n == 1 else f"Apply to {changed_tracks} Track"
                             + ("s" if changed_tracks != 1 else ""))
        if n == 1:
            m, s = divmod(int(t0.duration), 60)
            self.info.setText(f"{t0.path}\n{t0.codec} · {'lossless' if t0.lossless else f'{t0.bitrate} kbps'}"
                              f" · {t0.sample_rate / 1000:g} kHz · {m}:{s:02d}")
        else:
            self.info.setText(f"{changed_tracks} of {n} selected tracks have changes")

    # ------------------------------------------------------------ editing
    def _edited(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 2 or not self.tracks:
            return
        field = item.data(Qt.ItemDataRole.UserRole)
        value = item.text()
        if value in (DIFFERENT, PER_TRACK):
            return
        self.lib.set_new_value([t.id for t in self.tracks], field, value)
        self.win.refresh_tracks()

    def _set_art(self, data: bytes, label: str) -> None:
        if self.tracks:
            self.win.propose_art([t.id for t in self.tracks], data, label)

    def _use_folder_image(self, path: str) -> None:
        if self.tracks:
            self.lib.use_folder_image([t.id for t in self.tracks], path)
            self.win.refresh_tracks()

    def _art_from_file(self) -> None:
        if not self.tracks:
            return
        start = self.tracks[0].folder if Path(self.tracks[0].folder).is_dir() else str(Path.home())
        p, _ = QFileDialog.getOpenFileName(self, "Choose image", start, "Images (*.jpg *.jpeg *.png *.webp)")
        if p:
            self._set_art(Path(p).read_bytes(), f"file {Path(p).name}")


# ---------------------------------------------------------------- whole library: options
class FixLibraryDialog(QDialog):
    def __init__(self, lib: Library, folder: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fix Whole Library")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = QLabel("MusicMaid goes through your music, looks up tags and finds missing artwork. "
                       "<b>Nothing is changed yet</b>: when it's done, you review the changes "
                       f"{'album' if lib.settings.review_group != 'folder' else 'folder'} by "
                       f"{'album' if lib.settings.review_group != 'folder' else 'folder'} and apply the ones "
                       "you want. Looking up a large library can take a while (MusicBrainz allows about one "
                       "lookup per second); you can stop and continue the review later.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("The whole library", "")
        if folder:
            self.scope.addItem(f"Only {Path(folder).name}", folder)
        form.addRow("Work on", self.scope)
        self.lookup = QCheckBox("Look up tags online (MusicBrainz / AcoustID)")
        self.lookup.setChecked(True)
        self.artwork = QCheckBox("Find missing artwork")
        self.artwork.setChecked(True)
        self.clean = QCheckBox("Clean up text (capitals, junk like URLs, empty fields from file names)")
        self.clean.setChecked(True)
        self.skip = QCheckBox("Skip tracks that were already looked up (have MusicBrainz IDs) - much faster")
        self.skip.setChecked(True)
        for cb in (self.lookup, self.artwork, self.clean, self.skip):
            form.addRow("", cb)
        self.group = QComboBox()
        self.group.addItem("Album by album", "album")
        self.group.addItem("Folder by folder", "folder")
        self.group.setCurrentIndex(1 if lib.settings.review_group == "folder" else 0)
        form.addRow("Review the changes", self.group)
        lay.addLayout(form)
        buttons = QDialogButtonBox()
        go = buttons.addButton("Start", QDialogButtonBox.ButtonRole.AcceptRole)
        go.setObjectName("primary")
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def options(self) -> dict:
        return {"folder": self.scope.currentData() or None, "lookup": self.lookup.isChecked(),
                "artwork": self.artwork.isChecked(), "clean": self.clean.isChecked(),
                "skip_identified": self.skip.isChecked(), "group": self.group.currentData()}


# ---------------------------------------------------------------- whole library: review one group at a time
class ReviewWizard(QDialog):
    """Steps through the pending changes one album (or folder) at a time: Apply & Next, Skip, Discard & Next."""

    def __init__(self, lib: Library, parent=None, by: str | None = None, ids: set[int] | None = None):
        super().__init__(parent)
        self.lib = lib
        self.by = by or lib.settings.review_group
        self.setWindowTitle("Review Changes")
        self.resize(1050, 720)
        self.groups = lib.review_groups(self.by, ids)
        self.pos = 0
        self.stats = {"applied": 0, "skipped": 0, "discarded": 0, "tracks": 0}
        self.batches: list[str] = []

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setObjectName("dim")
        self.title = QLabel()
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        top.addWidget(self.counter)
        lay.addLayout(top)

        mid = QHBoxLayout()
        arts = QVBoxLayout()
        self.art_old = ArtBox("Original", size=210)
        self.art_new = ArtBox("New", size=210)
        arts.addWidget(self.art_old)
        arts.addSpacing(8)
        arts.addWidget(self.art_new)
        self.b_folder_art = folder_art_button(self, self._use_folder_image)
        self.b_folder_art.setFixedWidth(218)
        arts.addWidget(self.b_folder_art)
        arts.addStretch(1)
        mid.addLayout(arts)
        from PySide6.QtWidgets import QSplitter
        right = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["", "Original", "New"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 230)
        right.addWidget(self.tree)
        # every track/file of this album, with what will change for each
        files = QWidget()
        fl = QVBoxLayout(files)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(2)
        self.files_label = QLabel()
        self.files_label.setObjectName("dim")
        fl.addWidget(self.files_label)
        self.files = QTableWidget(0, 5)
        self.files.setHorizontalHeaderLabels(["#", "Title", "Artist", "File", "What changes"])
        self.files.verticalHeader().setVisible(False)
        self.files.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files.setAlternatingRowColors(True)
        self.files.setWordWrap(False)
        self.files.verticalHeader().setDefaultSectionSize(22)
        fh = self.files.horizontalHeader()
        fh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for c in (1, 2, 3, 4):
            fh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.files.cellDoubleClicked.connect(self._jump_to_track)
        fl.addWidget(self.files, 1)
        right.addWidget(files)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        mid.addWidget(right, 1)
        lay.addLayout(mid, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("dim")
        lay.addWidget(self.note)

        btns = QHBoxLayout()
        self.b_back = QPushButton("◀ Back")
        self.b_back.clicked.connect(lambda: self._go(-1))
        self.b_stop = QPushButton("Stop for Now")
        self.b_stop.setToolTip("Close; the remaining changes stay in Changes to review for later")
        self.b_stop.clicked.connect(self.accept)
        self.b_discard = QPushButton("Discard && Next")
        self.b_discard.setToolTip("Throw away this album's changes (the files aren't touched)")
        self.b_discard.clicked.connect(self._discard)
        self.b_skip = QPushButton("Skip")
        self.b_skip.setToolTip("Decide later: the changes stay in Changes to review")
        self.b_skip.clicked.connect(self._skip)
        self.b_apply = QPushButton("Apply && Next ▶")
        self.b_apply.setObjectName("primary")
        self.b_apply.setMinimumHeight(30)
        self.b_apply.clicked.connect(self._apply)
        btns.addWidget(self.b_back)
        btns.addWidget(self.b_stop)
        btns.addStretch(1)
        btns.addWidget(self.b_discard)
        btns.addWidget(self.b_skip)
        btns.addWidget(self.b_apply)
        lay.addLayout(btns)
        self.tree.itemChanged.connect(lambda *_: self._count())
        self._show()

    # ------------------------------------------------------------ one group
    def _show(self) -> None:
        if not self.groups:
            self.title.setText("<h3>Nothing to review</h3>No tracks have changes waiting.")
            for b in (self.b_back, self.b_discard, self.b_skip, self.b_apply):
                b.setEnabled(False)
            self.counter.clear()
            return
        if self.pos >= len(self.groups):
            self._finish()
            return
        name, tracks = self.groups[self.pos]
        # tracks may have been handled meanwhile (applied/discarded elsewhere)
        pending = self.lib.db.proposal_ids()
        tracks = [t for t in self.lib.tracks([t.id for t in tracks]) if t.id in pending]
        if not tracks:
            self.pos += 1
            self._show()
            return
        self.cur = tracks
        unit = "folder" if self.by == "folder" else "album"
        self.counter.setText(f"{self.pos + 1} of {len(self.groups)}")
        shown = f"Folder: {Path(name).name}" if Path(name).is_absolute() else name
        where = tracks[0].folder
        root = next((r for r in sorted(self.lib.folders, key=len, reverse=True)
                     if where == r or where.startswith(r.rstrip("/\\") + os.sep)), None)
        if root:
            where = os.path.relpath(where, root)
        self.title.setText(f"<h3 style='margin:0'>{shown}</h3>{len(tracks)} track{'s' if len(tracks) != 1 else ''}"
                           f" with changes · in {where}")
        self.b_back.setEnabled(self.pos > 0)
        props = {t.id: self.lib.db.proposal(t.id) for t in tracks}
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)

        scores = [p.score for p in props.values() if p and p.tags]
        low = bool(scores) and min(scores) < 0.5
        tick = Qt.CheckState.Unchecked if low else Qt.CheckState.Checked

        def check(item: QTreeWidgetItem, data) -> None:
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, tick)
            item.setFont(2, bold)

        def technical(f: str) -> bool:
            return f.startswith("musicbrainz_") or f == "acoustid_id"

        def add_rows(parent: QTreeWidgetItem, rows: list[QTreeWidgetItem]) -> None:
            """Normal rows first; MusicBrainz IDs folded into one collapsed row (they're applied too)."""
            ids = [r for r in rows if technical(r.data(0, Qt.ItemDataRole.UserRole)[1])]
            for r in rows:
                if r not in ids:
                    parent.addChild(r)
            if ids:
                grp = QTreeWidgetItem([f"MusicBrainz IDs ({len(ids)})", "", "help other apps recognise it"])
                grp.setFlags(grp.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                for r in ids:
                    grp.addChild(r)
                parent.addChild(grp)
                folded.append(grp)
        folded: list[QTreeWidgetItem] = []

        # changes that are the same for every track (album, album artist, year, …) are shown once
        fields = [f for f in tagio.FIELD_NAMES if any(props[t.id] and f in props[t.id].tags for t in tracks)]
        shared, per_track = [], []
        for f in fields:
            pairs = {((t.tags.get(f) or ""), (props[t.id].tags.get(f, t.tags.get(f) or "") if props[t.id] else
                                              t.tags.get(f) or "")) for t in tracks}
            changed_all = all(props[t.id] and f in props[t.id].tags and
                              (props[t.id].tags[f] or "") != (t.tags.get(f) or "") for t in tracks)
            (shared if len(pairs) == 1 and changed_all and len(tracks) > 1 else per_track).append(f)
        if shared:
            head = QTreeWidgetItem([f"Whole {unit}", "", ""])
            head.setFlags(head.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            rows = []
            for f in shared:
                old = tracks[0].tags.get(f) or "(empty)"
                new = props[tracks[0].id].tags[f] or "(remove)"
                it = QTreeWidgetItem([tagio.FIELD_LABELS.get(f, f), old, new])
                check(it, ("*", f))
                rows.append(it)
            add_rows(head, rows)
            self.tree.addTopLevelItem(head)
        same_art = self._same_art_everywhere(props)

        def new_num(t):
            p = props[t.id]
            v = (p.tags.get("tracknumber") if p and p.tags.get("tracknumber") else t.tags.get("tracknumber")) or ""
            d = (p.tags.get("discnumber") if p and p.tags.get("discnumber") else t.tags.get("discnumber")) or ""
            from ..textutil import first_int
            return (first_int(d) or 0, first_int(v) or 0, t.filename.lower())
        for t in sorted(tracks, key=new_num):
            p = props[t.id]
            rows = []
            for f in per_track:
                if p and f in p.tags and (p.tags[f] or "") != (t.tags.get(f) or ""):
                    rows.append(QTreeWidgetItem([tagio.FIELD_LABELS.get(f, f), t.tags.get(f) or "(empty)",
                                                 p.tags[f] or "(remove)"]))
                    check(rows[-1], (t.id, f))
            if p and p.art is not None and not same_art:
                _, w, h = tagio.image_info(p.art)
                rows.append(QTreeWidgetItem(["Cover art", f"{t.art_w}×{t.art_h}" if t.has_art else "(none)",
                                             f"{w}×{h}"]))
                check(rows[-1], (t.id, "__art__"))
            if not rows:
                continue
            num = new_num(t)[1]
            label = f"{str(num) + '. ' if num else ''}" \
                    f"{p.tags.get('title') if p and p.tags.get('title') else t.get('title') or t.filename}"
            top = QTreeWidgetItem([label, t.filename, ""])
            top.setToolTip(0, t.path)
            top.setToolTip(1, t.path)
            top.setForeground(1, self.palette().color(self.palette().ColorRole.PlaceholderText))
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            add_rows(top, rows)
            self.tree.addTopLevelItem(top)
        # artwork, shown once when the whole group gets the same new cover
        old_art = next((tagio.read_artwork(t.path) for t in tracks if t.has_art), None)
        self.art_old.show_art(old_art.data if old_art else None,
                              f"{old_art.width}×{old_art.height}" if old_art else "", "No artwork")
        new_art = next((props[t.id].art for t in tracks if props[t.id] and props[t.id].art is not None), None)
        self.art_new_check = None
        if new_art and same_art:
            _, w, h = tagio.image_info(new_art)
            self.art_new.show_art(new_art, f"{w}×{h}")
            item = QTreeWidgetItem(["Cover art (all tracks)", f"{old_art.width}×{old_art.height}" if old_art
                                    else "(none)", f"{w}×{h} · {props[tracks[0].id].art_source or ''}"])
            check(item, ("*", "__art__"))
            self.tree.insertTopLevelItem(0, item)
        elif new_art:
            self.art_new.show_art(new_art, "differs per track")
        else:
            self.art_new.show_art(old_art.data if old_art else None, "unchanged" if old_art else "", "No artwork")
        self.tree.expandAll()
        for g in folded:
            g.setExpanded(False)
        self._fill_files(tracks, props, new_num, shared, same_art)
        folders = {t.folder for t in tracks}
        cur_src = next((props[t.id].art_source for t in tracks if props[t.id] and props[t.id].art is not None), None)
        show_folder_art(self.b_folder_art, self.lib.folder_images(next(iter(folders))) if len(folders) == 1 else [],
                        cur_src, self._use_folder_image)
        self.tree.blockSignals(False)
        srcs = sorted({s for p in props.values() if p for s in p.source.split(", ") if s})
        conf = ""
        if scores:
            lo, hi = min(scores), max(scores)
            conf = f" · {lo:.0%} sure" if lo == hi else f" · {lo:.0%}–{hi:.0%} sure"
        text = f"Changes from {', '.join(srcs)}{conf}. Untick anything you don't want; unticked changes stay in " \
               "Changes to review."
        nums = [new_num(t)[:2] for t in tracks if new_num(t)[1]]
        if len(nums) != len(set(nums)):
            from .mainwindow import AMBER
            text = (f"<span style='color:{QColor(AMBER).name()}'><b>Two files would be the same track</b> - one "
                    "is probably a duplicate (Duplicates can remove it).</span> ") + text
        if scores and min(scores) < 0.6:
            from .mainwindow import RED
            text = (f"<span style='color:{QColor(RED).name()}'><b>⚠ Unsure match ({min(scores):.0%}).</b> "
                    + ("Nothing is ticked: tick what's right, or use Discard &amp; Next. " if low else
                       "Check it carefully before applying. ") + "</span>" + text)
        self.note.setText(text)
        self._count()

    def _fill_files(self, tracks, props, new_num, shared, same_art) -> None:
        from .mainwindow import GREEN
        bold = QFont()
        bold.setBold(True)
        # the other tracks in the same folder(s) too, so you see the whole album
        folders = sorted({t.folder for t in tracks})
        ids = {t.id for t in tracks}
        marks = ",".join("?" * len(folders))
        others = [t for t in self.lib.db.tracks(where=f"folder IN ({marks})", args=tuple(folders))
                  if t.id not in ids]
        for t in others:
            props.setdefault(t.id, None)
        def order(t):
            d, n, name = new_num(t)
            return (t.id not in ids, d, n or 9999, name)     # changed tracks first, unnumbered last
        ordered = sorted([*tracks, *others], key=order)
        self.files.setRowCount(len(ordered))
        for r, t in enumerate(ordered):
            p = props[t.id]
            new = dict(t.tags, **(p.tags if p else {}))
            changed = [f for f in (p.tags if p else {}) if (p.tags[f] or "") != (t.tags.get(f) or "")]
            what = [tagio.FIELD_LABELS.get(f, f).lower() for f in changed
                    if not f.startswith("musicbrainz_") and f != "acoustid_id"]
            if any(f.startswith("musicbrainz_") for f in changed):
                what.append("IDs")
            if p and p.art is not None:
                what.insert(0, "cover art")
            num = new_num(t)[1]
            cells = [str(num) if num else "", new.get("title") or t.filename, new.get("artist", ""), t.filename,
                     ", ".join(what) or "no changes"]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, t.id)
                if c in (1, 2) and ("title" if c == 1 else "artist") in changed:
                    it.setFont(bold)
                    it.setForeground(QColor(GREEN))
                if c == 3 or t.id not in ids:
                    it.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
                if c == 3:
                    it.setToolTip(t.path)
                self.files.setItem(r, c, it)
        self.files_label.setText(f"Tracks in this {'folder' if self.by == 'folder' else 'album'}: {len(ordered)}"
                                 f" ({len(tracks)} with changes) - double-click one to see its changes")

    def _use_folder_image(self, path: str) -> None:
        """Use the cover image that's already in the folder for every track of this album."""
        self.lib.use_folder_image([t.id for t in self.cur], path)
        self._show()

    def _jump_to_track(self, row: int, _col: int) -> None:
        tid = self.files.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.toolTip(0) and any(t.id == tid and t.path == top.toolTip(0) for t in self.cur):
                self.tree.setCurrentItem(top)
                top.setExpanded(True)
                self.tree.scrollToItem(top)
                return

    @staticmethod
    def _same_art_everywhere(props) -> bool:
        arts = [p.art for p in props.values() if p and p.art is not None]
        return bool(arts) and len(arts) == len(props) and all(a == arts[0] for a in arts)

    def _leaves(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop(0)
            if it.childCount():
                stack[:0] = [it.child(j) for j in range(it.childCount())]
            else:
                yield it

    def _count(self) -> None:
        tids = set()
        for it in self._leaves():
            if it.checkState(0) == Qt.CheckState.Checked:
                tid = it.data(0, Qt.ItemDataRole.UserRole)[0]
                tids.update(t.id for t in self.cur) if tid == "*" else tids.add(tid)
        n = len(tids)
        self.b_apply.setText(f"Apply to {n} Track{'s' if n != 1 else ''} && Next ▶" if n else "Next ▶")

    # ------------------------------------------------------------ actions
    def _selection(self) -> tuple[list[int], dict[int, set[str]]]:
        ids = [t.id for t in self.cur]
        exclude: dict[int, set[str]] = {}
        for it in self._leaves():
            tid, field = it.data(0, Qt.ItemDataRole.UserRole)
            if it.checkState(0) != Qt.CheckState.Checked:
                for t in (ids if tid == "*" else [tid]):
                    exclude.setdefault(t, set()).add(field)
        # fields not shown at all (e.g. unchanged values) don't matter; tracks with nothing ticked are skipped
        return ids, exclude

    def _apply(self) -> None:
        ids, exclude = self._selection()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = self.lib.apply(ids, exclude=exclude, label=f"Review: {self.groups[self.pos][0]}")
        finally:
            QApplication.restoreOverrideCursor()
        if res.failed:
            QMessageBox.warning(self, "Review", f"{res.failed} file(s) couldn't be written (see the log). "
                                "Their changes stay in Changes to review.")
        self.batches.append(res.batch)
        self.stats["applied"] += 1
        self.stats["tracks"] += res.written
        self._go(1)

    def _skip(self) -> None:
        self.stats["skipped"] += 1
        self._go(1)

    def _discard(self) -> None:
        self.lib.discard([t.id for t in self.cur])
        self.stats["discarded"] += 1
        self._go(1)

    def _go(self, step: int) -> None:
        self.pos = max(0, self.pos + step)
        self._show()

    def _finish(self) -> None:
        s = self.stats
        self.tree.clear()
        self.files.setRowCount(0)
        self.files_label.clear()
        self.art_old.show_art(None, "")
        self.art_new.show_art(None, "")
        self.counter.clear()
        self.title.setText(f"<h3>All done</h3>Applied changes to {s['tracks']} tracks in {s['applied']} "
                           f"{'folders' if self.by == 'folder' else 'albums'}; skipped {s['skipped']}, discarded "
                           f"{s['discarded']}. Skipped changes are still in <i>Changes to review</i>. "
                           "Everything applied can be undone with Undo.")
        self.note.clear()
        for b in (self.b_discard, self.b_skip, self.b_back):
            b.setEnabled(False)
        self.b_apply.setText("Close")
        self.b_apply.clicked.disconnect()
        self.b_apply.clicked.connect(self.accept)
