"""Detecting changes made while the application was not running (FR-035, FR-036).

`watchdog` only reports events that happen while its observer is alive. A user who enables
automatic re-indexing, quits, edits documents, and reopens would otherwise get stale
results from a UI reporting that watching is active — a silent correctness failure, and
the worst kind, because the interface asserts the opposite.

So at startup and on folder change we compare **metadata only**: names, sizes, and
modification times. No document contents are re-read, so this costs a directory walk
rather than a rebuild (research.md §11).

Known limitation: a change preserving both size and modification time is not detected.
Rare in practice, and the manual re-index path remains.
"""

from __future__ import annotations

from pathlib import Path

from . import store
from .indexer import scan_folder


def is_index_stale(folder: Path | None) -> bool:
    """True if the folder no longer matches what the index recorded."""
    if folder is None:
        return False

    meta = store.load_meta()
    if meta is None:
        # No index at all is not "stale" — it is simply absent, which the UI reports
        # differently and acts on differently.
        return False

    if meta.folder_path != str(folder):
        return True

    try:
        current = {
            (f.relative_path, f.size_bytes, f.modified_at) for f in scan_folder(folder)
        }
    except OSError:
        return False

    indexed = {
        (f.relative_path, f.size_bytes, f.modified_at) for f in store.load_fingerprints()
    }

    return current != indexed
