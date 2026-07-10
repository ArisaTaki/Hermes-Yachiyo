"""Small deterministic primitives shared by planner modules."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any


def stable_planner_id(prefix: str, kind: Any, text: str) -> str:
    digest = hashlib.sha1(f"{kind}\n{text}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def unique_planner_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean_value = str(value or "").strip()
        if clean_value and clean_value not in result:
            result.append(clean_value)
    return result
