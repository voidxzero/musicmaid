"""Run library operations on a background thread with Qt signals for progress."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..progress import Cancelled, Task


class _Signals(QObject):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class _Job(QRunnable):
    def __init__(self, fn, signals: _Signals, task: Task):
        super().__init__()
        self.fn, self.signals, self.task = fn, signals, task

    def run(self) -> None:
        try:
            result = self.fn(self.task)
        except Cancelled:
            self.signals.cancelled.emit()
        except Exception as e:  # report every failure to the UI
            traceback.print_exc()
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.signals.finished.emit(result)


class TaskRunner(QObject):
    """One long-running job at a time (keeps rate limits and the DB simple)."""

    progress = Signal(int, int, str)
    log = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self.task: Task | None = None
        self._signals: _Signals | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None

    def run(self, label: str, fn, on_done=None, on_error=None) -> bool:
        if self.busy:
            return False
        sig = _Signals()
        self._signals = sig  # keep a reference alive
        self.task = Task(on_progress=sig.progress.emit, on_log=sig.log.emit)
        sig.progress.connect(self.progress)
        sig.log.connect(self.log)

        def finish(result=None, *, error: str | None = None, cancelled: bool = False):
            self.task = None
            self.busy_changed.emit(False)
            if cancelled:
                self.progress.emit(0, 1, "Cancelled")
            elif error:
                self.progress.emit(0, 1, f"Error: {error}")
                if on_error:
                    on_error(error)
            else:
                self.progress.emit(0, 1, "")
                if on_done:
                    on_done(result)

        sig.finished.connect(lambda r: finish(r))
        sig.failed.connect(lambda e: finish(error=e))
        sig.cancelled.connect(lambda: finish(cancelled=True))
        self.busy_changed.emit(True)
        self.progress.emit(0, 0, label)
        self.pool.start(_Job(fn, sig, self.task))
        return True

    def cancel(self) -> None:
        if self.task:
            self.task.cancel()
