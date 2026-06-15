"""Skill public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import SkillSnapshot


def skill_snapshot_from_payload(payload: Mapping[str, Any] | SkillSnapshot) -> SkillSnapshot:
    if isinstance(payload, SkillSnapshot):
        return payload

    return SkillSnapshot(
        skill_id=_text(payload.get("skill_id")),
        name=_text(payload.get("name") or payload.get("skill_id") or "Skill"),
        description=_optional_text(payload.get("description")),
        source_path=_optional_text(payload.get("source_path")),
        local_path=_optional_text(payload.get("local_path")),
        folder_id=_optional_text(payload.get("folder_id")),
        folder_name=_optional_text(payload.get("folder_name")),
        source_type=_optional_text(payload.get("source_type")),
        origin_path=_optional_text(payload.get("origin_path")),
        source_ref=_optional_text(payload.get("source_ref")),
        content_hash=_optional_text(payload.get("content_hash")),
        last_synced_at=_optional_text(payload.get("last_synced_at")),
        sync_status=_optional_text(payload.get("sync_status")),
        content_summary=_optional_text(payload.get("content_summary")),
        skill_markdown=_optional_text(payload.get("skill_markdown")),
        asset_paths=[str(item) for item in payload.get("asset_paths") or [] if str(item)],
        enabled=bool(payload.get("enabled", True)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
