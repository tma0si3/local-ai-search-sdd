"""Path containment checking.

**Security-critical.** `POST /api/open` hands a client-supplied path to the operating
system. Without the check below, any process able to reach the local port could open
arbitrary files — `~/.ssh/id_rsa`, anything.

The resolution order is the whole point: resolve symlinks *first*, then compare. Checking
a string prefix before resolution is defeated by a symlink inside the documents folder
pointing anywhere on disk (contracts/http-api.md, security note).
"""

from __future__ import annotations

from pathlib import Path

from .errors import FileNotFoundInIndexError, InvalidPathError, PathOutOfScopeError


def resolve_within(raw: str | None, folder: Path) -> Path:
    """Return the real path of ``raw``, or raise if it escapes ``folder``.

    Raises:
        InvalidPathError: missing, blank, or not absolute.
        PathOutOfScopeError: resolves outside ``folder``.
        FileNotFoundInIndexError: inside ``folder`` but no longer on disk.
    """
    if raw is None or not str(raw).strip():
        raise InvalidPathError("No document path was provided.")

    candidate = Path(str(raw).strip())
    if not candidate.is_absolute():
        raise InvalidPathError(f"'{raw}' is not a full path.")

    # strict=False so a deleted file still resolves; we want to report FILE_NOT_FOUND for
    # that case, not treat it as out of scope. Symlinks are still followed.
    resolved = candidate.resolve(strict=False)
    root = folder.resolve(strict=False)

    if not resolved.is_relative_to(root):
        raise PathOutOfScopeError(
            "That document is outside your configured documents folder, so it cannot be "
            "opened from here. Only files within the indexed folder can be opened."
        )

    if not resolved.exists():
        raise FileNotFoundInIndexError(
            f"'{resolved.name}' is no longer at the expected location. It may have been "
            "moved, renamed, or deleted since the index was built. Re-index to refresh."
        )

    return resolved
