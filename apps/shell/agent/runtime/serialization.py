from __future__ import annotations

import json
import re
from typing import Any


def json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def json_dump_sorted(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_dump_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def slug(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized[:48] or fallback
