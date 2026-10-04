"""Watching the documents folder for changes (FR-030 – FR-033).

**Cost warning**: every trigger here causes a *full rebuild* (FR-009). One saved file
re-processes the entire folder. The debounce below is not a nicety — it is what makes
automatic re-indexing usable at all. See research.md §10, which recommends revisiting
FR-009 if this proves annoying in practice.

The debounce is separated from the observer so it can be unit-tested without touching the
filesystem (T051).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .extract import SUPPORTED_EXTENSIONS

QUIET_PERIOD_SECONDS = 5.0
"""How long the folder must be still before a rebuild starts (FR-031).

Long enough to absorb an editor's save-rename-save dance and a multi-file paste; short
enough that the index is current by the time the user switches back to the browser.
"""


class Debouncer:
    """Collapses a burst of calls into one, after the folder has been quiet.

    Each call restarts the timer, so a stream of events produces exactly one action once
    it stops — not one action per event, and not one every quiet period.
    """

    def __init__(self, delay: float, action: Callable[[], None]) -> None:
        self._delay = delay
        self._action = action
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def trigger(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        self._action()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._timer is not None


class _ChangeHandler(FileSystemEventHandler):
    """Notifies the debouncer about changes to files we would actually index."""

    def __init__(self, debouncer: Debouncer) -> None:
        self._debouncer = debouncer

    def on_any_event(self, event) -> None:
        if event.is_directory:
            # A directory event is always accompanied by file events, except for pure
            # renames — which the next startup reconciliation would catch anyway.
            return
        for path in (getattr(event, "src_path", ""), getattr(event, "dest_path", "")):
            if path and Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
                self._debouncer.trigger()
                return


class FolderWatcher:
    """Starts and stops filesystem watching. Off unless the user turns it on (FR-033)."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self._observer: Observer | None = None
        self._debouncer: Debouncer | None = None
        self.folder: Path | None = None

    @property
    def enabled(self) -> bool:
        return self._observer is not None

    def start(self, folder: Path) -> None:
        self.stop()
        self._debouncer = Debouncer(QUIET_PERIOD_SECONDS, self._on_change)
        observer = Observer()
        observer.schedule(_ChangeHandler(self._debouncer), str(folder), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        self.folder = folder

    def stop(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
            self._debouncer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self.folder = None

    @property
    def pending_change(self) -> bool:
        return self._debouncer is not None and self._debouncer.pending
