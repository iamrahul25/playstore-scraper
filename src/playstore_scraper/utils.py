"""Shared helpers."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any


def dig(obj: Any, *path: int | str, default: Any = None) -> Any:
    """Safely walk nested lists/dicts by index or key."""
    cur = obj
    for key in path:
        try:
            cur = cur[key]
        except (IndexError, KeyError, TypeError):
            return default
    return cur if cur is not None else default


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def run_folder_stamp() -> str:
    return utc_now().strftime("%Y-%m-%dT%H-%M-%SZ")


def unix_to_iso(ts: int | float | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return None


def jitter_sleep(base_seconds: float, jitter_ratio: float = 0.3) -> None:
    """Sleep base ± jitter_ratio."""
    if base_seconds <= 0:
        return
    delta = base_seconds * jitter_ratio
    time.sleep(max(0.0, base_seconds + random.uniform(-delta, delta)))


def format_count(n: int | None) -> str:
    if n is None:
        return "all"
    return f"{n:,}"
