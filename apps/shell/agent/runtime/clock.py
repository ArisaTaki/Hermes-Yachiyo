"""Clock helpers shared by runtime services."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_utc(value: Any) -> datetime | None:
    """Parse an ISO timestamp and normalize it to an aware UTC datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return time.time()
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()
