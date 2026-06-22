"""Model-visible Agent Desk context helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

DESK_NOTES_PATH = "desk-notes.md"
DESK_METADATA_PATH = ".yachiyo-desk.json"


def build_agent_desk_context(
    agent: Mapping[str, Any],
    *,
    max_items: int = 80,
    note_preview_limit: int = 4000,
) -> str:
    """Return a compact, read-only Agent Desk summary for the model context."""

    root = _agent_desk_root(agent)
    if root is None or not root.exists() or not root.is_dir():
        return ""

    sections = [f"Root: {root}"]
    note_text = _read_text_preview(root / DESK_NOTES_PATH, limit=note_preview_limit)
    if note_text:
        sections.append(f"Desk notes:\n{note_text}")

    item_lines, truncated = _desk_item_lines(root, max_items=max_items)
    if item_lines:
        if truncated:
            item_lines.append(f"- ... truncated after {max_items} items")
        sections.append("Desk files:\n" + "\n".join(item_lines))
    return "\n".join(sections)


def _agent_desk_root(agent: Mapping[str, Any]) -> Path | None:
    workspace_policy = agent.get("workspace_policy")
    if not isinstance(workspace_policy, Mapping):
        return None
    raw = str(workspace_policy.get("default_workdir") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _desk_item_lines(root: Path, *, max_items: int) -> tuple[list[str], bool]:
    lines: list[str] = []
    truncated = False
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for item in paths:
        rel = item.relative_to(root).as_posix()
        if rel == DESK_METADATA_PATH:
            continue
        if len(lines) >= max_items:
            truncated = True
            break
        kind = "directory" if item.is_dir() else "note" if rel == DESK_NOTES_PATH else "file"
        size = _file_size(item)
        size_label = f", {size} bytes" if size is not None else ""
        lines.append(f"- {rel} ({kind}{size_label})")
    return lines, truncated


def _file_size(path: Path) -> int | None:
    if path.is_dir():
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _read_text_preview(path: Path, *, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit].strip()
    except (OSError, UnicodeDecodeError):
        return ""
