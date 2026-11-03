"""A tiny progress/cancellation channel shared by the core and both UIs."""
from __future__ import annotations

import threading
from typing import Callable


class Cancelled(Exception):
    pass


class Task:
    def __init__(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ):
        self._on_progress = on_progress
        self._on_log = on_log
        self._cancel = threading.Event()

    def progress(self, current: int, total: int, message: str = "") -> None:
        if self._cancel.is_set():
            raise Cancelled()
        if self._on_progress:
            self._on_progress(current, total, message)

    def log(self, message: str) -> None:
        if self._on_log:
            self._on_log(message)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()


NULL_TASK = Task()
