"""Settings persistence and application paths.

Configuration lives in the user's application data directory, not beside their documents
and not in the index database. The index is destroyed and rebuilt on every run, so storing
settings there would lose them (research.md §8).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import InvalidPathError, PathNotFoundError, PathNotReadableError

APP_DIR_NAME = "localsearch"
DEFAULT_OLLAMA_MODEL = "llama3.2"


def app_data_dir() -> Path:
    """Where this application keeps its own state.

    Overridable via ``LOCALSEARCH_DATA_DIR`` so tests never touch the real directory.
    """
    override = os.environ.get("LOCALSEARCH_DATA_DIR")
    if override:
        base = Path(override)
    else:
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return app_data_dir() / "config.json"


def database_path() -> Path:
    return app_data_dir() / "index.db"


def embeddings_path() -> Path:
    return app_data_dir() / "embeddings.npy"


@dataclass
class Config:
    folder_path: str | None = None
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    auto_reindex: bool = False


def load_config() -> Config:
    """Read settings, falling back to defaults.

    A corrupt or hand-mangled file yields defaults rather than a crash on startup. Losing
    a folder path is recoverable in seconds; an application that will not start is not.
    """
    path = config_path()
    if not path.exists():
        return Config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Config()
    if not isinstance(data, dict):
        return Config()
    return Config(
        folder_path=data.get("folder_path"),
        ollama_model=data.get("ollama_model") or DEFAULT_OLLAMA_MODEL,
        auto_reindex=bool(data.get("auto_reindex", False)),
    )


def save_config(config: Config) -> None:
    """Write settings atomically, so an interrupted write cannot corrupt the file."""
    path = config_path()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    temporary.replace(path)


def validate_folder(raw: str | None) -> Path:
    """Check a user-supplied folder path, raising the contract's typed errors.

    Order matters: absent, then missing, then unreadable. Each produces a different
    status code and a different thing for the user to do about it.
    """
    if raw is None or not str(raw).strip():
        raise InvalidPathError(
            "No folder was provided. Enter the full path to your documents folder."
        )

    candidate = Path(str(raw).strip()).expanduser()

    if not candidate.is_absolute():
        raise InvalidPathError(
            f"'{raw}' is not a full path. Enter a path starting with '/', "
            "such as /Users/you/Documents."
        )
    if not candidate.exists():
        raise PathNotFoundError(
            f"No folder exists at '{candidate}'. Check the path for typos, or create the folder."
        )
    if not candidate.is_dir():
        raise InvalidPathError(
            f"'{candidate}' is a file, not a folder. "
            "Choose the folder that contains your documents."
        )
    if not os.access(candidate, os.R_OK | os.X_OK):
        raise PathNotReadableError(
            f"'{candidate}' cannot be read. Check its permissions, or grant access in "
            "System Settings → Privacy & Security → Files and Folders."
        )
    return candidate
