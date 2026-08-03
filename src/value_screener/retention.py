from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path


def iter_expired_dated_directories(root: Path, *, as_of: date, keep_days: int = 7) -> list[Path]:
    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    if not root.exists():
        return []

    cutoff = as_of - timedelta(days=keep_days - 1)
    expired: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            child_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if child_date < cutoff:
            expired.append(child)
    return expired


def cleanup_dated_directories(roots: list[Path], *, as_of: date, keep_days: int = 7) -> list[Path]:
    deleted: list[Path] = []
    for root in roots:
        for path in iter_expired_dated_directories(root, as_of=as_of, keep_days=keep_days):
            shutil.rmtree(path)
            deleted.append(path)
    return deleted
