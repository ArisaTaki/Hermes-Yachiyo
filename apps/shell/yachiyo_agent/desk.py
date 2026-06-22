"""Agent Desk snapshots and local workspace-backed storage."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError

from .contracts import AgentDeskItemSnapshot, AgentDeskSnapshot

DESK_NOTES_PATH = "desk-notes.md"
DESK_METADATA_PATH = ".yachiyo-desk.json"


def agent_desk_snapshot_from_payload(payload: Mapping[str, Any]) -> AgentDeskSnapshot:
    return AgentDeskSnapshot(
        agent_id=str(payload.get("agent_id") or ""),
        root_path=str(payload.get("root_path") or ""),
        notes_path=str(payload.get("notes_path") or DESK_NOTES_PATH),
        metadata_path=str(payload.get("metadata_path") or DESK_METADATA_PATH),
        items=[
            agent_desk_item_snapshot_from_payload(item)
            for item in payload.get("items") or []
            if isinstance(item, Mapping)
        ],
        updated_at=str(payload.get("updated_at") or ""),
    )


def agent_desk_item_snapshot_from_payload(payload: Mapping[str, Any]) -> AgentDeskItemSnapshot:
    return AgentDeskItemSnapshot(
        path=str(payload.get("path") or ""),
        name=str(payload.get("name") or ""),
        kind=_item_kind(payload.get("kind")),
        size_bytes=_optional_int(payload.get("size_bytes")),
        mime_type=_optional_text(payload.get("mime_type")),
        preview_text=_optional_text(payload.get("preview_text")),
        updated_at=str(payload.get("updated_at") or ""),
    )


class LocalAgentDeskStore:
    """Workspace-backed Agent Desk storage with no schema migration."""

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    def get_agent_desk(self, agent_id: str) -> dict[str, Any]:
        agent, root = self._agent_and_root(agent_id)
        self._ensure_metadata(agent, root)
        return self._snapshot(agent_id, root)

    def write_agent_desk_note(self, agent_id: str, content: str) -> dict[str, Any]:
        agent, root = self._agent_and_root(agent_id)
        root.mkdir(parents=True, exist_ok=True)
        note_path = root / DESK_NOTES_PATH
        note_path.write_text(str(content or ""), encoding="utf-8")
        self._write_metadata(agent, root)
        return self._snapshot(agent_id, root)

    def write_agent_desk_file(self, agent_id: str, path: str, content: str) -> dict[str, Any]:
        agent, root = self._agent_and_root(agent_id)
        rel = _safe_rel_path(path)
        target = (root / rel).resolve()
        if not _is_within(target, root.resolve()):
            raise AgentRuntimeError("Agent Desk 文件路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content or ""), encoding="utf-8")
        self._write_metadata(agent, root)
        return self._snapshot(agent_id, root)

    def trigger_agent_desk_file_event(
        self,
        agent_id: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        clean_agent_id = str(agent_id or "").strip()
        if not clean_agent_id:
            raise AgentRuntimeError("Agent Desk 文件事件需要 agent_id")
        self._runtime.get_agent(clean_agent_id)
        rel = _safe_rel_path(str(request.get("path") or "")).as_posix()
        event_type = _desk_event_type(request.get("event_type"))
        schedule_future_task = getattr(self._runtime, "schedule_future_task", None)
        if not callable(schedule_future_task):
            raise AgentRuntimeError("Agent Desk 文件事件需要 FutureTask runtime")

        delay_seconds = request.get("delay_seconds")
        payload = {
            "title": f"Review Agent Desk file: {rel}",
            "prompt": _desk_file_event_prompt(clean_agent_id, rel, event_type),
            "runnable_id": clean_agent_id,
            "delay_seconds": delay_seconds if delay_seconds is not None else 0,
        }
        return schedule_future_task(payload, source_run_id="agent_desk_file_event")

    def _agent_and_root(self, agent_id: str) -> tuple[dict[str, Any], Path]:
        clean_agent_id = str(agent_id or "").strip()
        if not clean_agent_id:
            raise AgentRuntimeError("Agent Desk 需要 agent_id")
        agent = self._runtime.get_agent(clean_agent_id)
        workspace_policy = agent.get("workspace_policy") if isinstance(agent, Mapping) else {}
        configured = (
            str(workspace_policy.get("default_workdir") or "").strip()
            if isinstance(workspace_policy, Mapping)
            else ""
        )
        root = Path(configured).expanduser() if configured else self._default_agent_workdir(clean_agent_id)
        root.mkdir(parents=True, exist_ok=True)
        return dict(agent), root

    def _default_agent_workdir(self, agent_id: str) -> Path:
        callback = getattr(self._runtime, "_default_agent_workdir", None)
        if callable(callback):
            return Path(callback(agent_id)).expanduser()
        base = Path(getattr(self._runtime, "agent_workspaces_dir", Path.cwd() / "agent-workspaces"))
        raw_id = str(agent_id or "")
        clean_id = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_id).strip(".-")[:80] or "agent"
        if clean_id != raw_id:
            clean_id = f"{clean_id}-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:8]}"
        return base / clean_id

    def _snapshot(self, agent_id: str, root: Path) -> dict[str, Any]:
        root.mkdir(parents=True, exist_ok=True)
        items = [
            _item_payload(root, child)
            for child in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
        ]
        return {
            "agent_id": agent_id,
            "root_path": str(root),
            "notes_path": DESK_NOTES_PATH,
            "metadata_path": DESK_METADATA_PATH,
            "items": [item for item in items if item is not None],
            "updated_at": _mtime_iso(root),
        }

    def _ensure_metadata(self, agent: Mapping[str, Any], root: Path) -> None:
        metadata_path = root / DESK_METADATA_PATH
        if metadata_path.exists():
            return
        self._write_metadata(agent, root)

    def _write_metadata(self, agent: Mapping[str, Any], root: Path) -> None:
        metadata = {
            "schema_version": 1,
            "agent_id": str(agent.get("agent_id") or ""),
            "agent_name": str(agent.get("name") or ""),
            "updated_at": _now_iso(),
        }
        (root / DESK_METADATA_PATH).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _item_payload(root: Path, path: Path) -> dict[str, Any] | None:
    rel = path.relative_to(root).as_posix()
    if rel == DESK_METADATA_PATH:
        return None
    is_note = rel == DESK_NOTES_PATH
    if path.is_dir():
        kind = "directory"
        size = None
        mime_type = None
        preview = None
    else:
        kind = "note" if is_note else "file"
        size = path.stat().st_size
        mime_type = mimetypes.guess_type(path.name)[0] or "text/plain"
        preview = _preview_text(path) if _looks_textual(mime_type) else None
    return {
        "path": rel,
        "name": path.name,
        "kind": kind,
        "size_bytes": size,
        "mime_type": mime_type,
        "preview_text": preview,
        "updated_at": _mtime_iso(path),
    }


def _safe_rel_path(value: str) -> Path:
    raw = str(value or "").replace("\\", "/").strip()
    pure = PurePosixPath(raw)
    if (
        not raw
        or not pure.parts
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise AgentRuntimeError("Agent Desk 文件路径必须是安全的相对路径")
    return Path(*pure.parts)


def _desk_event_type(value: Any) -> str:
    raw = str(value or "changed").strip().lower()
    return raw if raw in {"created", "modified", "deleted", "changed"} else "changed"


def _desk_file_event_prompt(agent_id: str, path: str, event_type: str) -> str:
    return (
        f"Agent Desk file event for {agent_id}: {event_type} {path}\n\n"
        "Review the Agent Desk notes and file list, then decide whether a short "
        "follow-up is useful. Use read-only tools first. Do not modify files, "
        "send messages, or run terminal commands unless the user explicitly asks "
        "and approval policy allows it."
    )


def _preview_text(path: Path, limit: int = 4000) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None
    return text[:limit]


def _looks_textual(mime_type: str | None) -> bool:
    value = str(mime_type or "")
    return value.startswith("text/") or value in {"application/json", "application/xml"}


def _item_kind(value: Any) -> str:
    raw = str(value or "file")
    return raw if raw in {"file", "directory", "note"} else "file"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mtime_iso(path: Path) -> str:
    try:
        timestamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
