"""Keep the in-memory stores across API restarts when no PostgreSQL is configured.

Without `DB_URL` every user, case, note and assignment lived only in the process, so a restart (or
the dev server reloading) turned every saved link and session into "case_not_found". A store wrapped
by `persist` loads its state from `STATE_DIR/<name>.pickle` on start and writes it back after each
change. The files are written and read only by this process (they live under the git-ignored `data/`).

- `STATE_DIR=<path>` picks the folder, `STATE_DIR=off` turns it off.
- By default it is on (`data/dev-state`) for a process without PostgreSQL, and off under pytest so
  tests always start clean.
"""

from __future__ import annotations

import functools
import inspect
import os
import pickle
import sys
from pathlib import Path
from typing import Any, TypeVar

import structlog

_log = structlog.get_logger("shared.snapshot")

DEFAULT_DIR = "data/dev-state"
READ_PREFIXES = ("get", "list", "find", "is_", "count", "read")
Store = TypeVar("Store")


def state_dir() -> Path | None:
    configured = os.environ.get("STATE_DIR", "").strip()
    if configured.lower() in {"off", "0", "false", "none"}:
        return None
    if configured:
        return Path(configured)
    if "pytest" in sys.modules or os.environ.get("DB_URL", "").startswith("postgresql"):
        return None
    return Path(DEFAULT_DIR)


def persist(store: Store, name: str, fields: tuple[str, ...], directory: Path | None = None) -> Store:
    """Restore `fields` of `store` from disk and save them after every call that changes the store."""
    folder = directory if directory is not None else state_dir()
    if folder is None:
        return store
    path = folder / f"{name}.pickle"
    _load(store, path, fields)

    def save() -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(pickle.dumps({field: getattr(store, field) for field in fields}, protocol=pickle.HIGHEST_PROTOCOL))
            temporary.replace(path)
        except Exception as error:  # a full disk must not break a request
            _log.warning("snapshot_save_failed", store=name, reason=str(error))

    for attribute, member in inspect.getmembers(type(store), inspect.iscoroutinefunction):
        if attribute.startswith("_") or attribute.startswith(READ_PREFIXES):
            continue
        setattr(store, attribute, _saving(getattr(store, attribute), save))
    return store


def _saving(method: Any, save: Any) -> Any:
    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await method(*args, **kwargs)
        save()
        return result

    return wrapper


def _load(store: Any, path: Path, fields: tuple[str, ...]) -> None:
    if not path.exists():
        return
    try:
        state = pickle.loads(path.read_bytes())  # noqa: S301 - our own file, written by `persist`
    except Exception as error:  # an old or broken snapshot: start clean rather than refuse to boot
        _log.warning("snapshot_load_failed", path=str(path), reason=str(error))
        return
    for field in fields:
        if field in state:
            setattr(store, field, state[field])
    _log.info("snapshot_loaded", path=str(path))
