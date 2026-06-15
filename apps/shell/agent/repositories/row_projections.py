from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def row_to_skill(
    row: Any,
    *,
    skills_dir: Path,
    json_load: Callable[[str | None, Any], Any],
) -> dict[str, Any]:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    folder_id = str(row["folder_id"] if "folder_id" in keys else "")
    folder_name = str(row["folder_name"] if "folder_name" in keys and row["folder_name"] else "")
    return {
        "skill_id": row["skill_id"],
        "name": row["name"],
        "description": row["description"],
        "source_path": row["source_path"],
        "local_path": row["local_path"] or str(skills_dir / row["skill_id"]),
        "folder_id": folder_id,
        "folder_name": folder_name,
        "source_type": row["source_type"],
        "origin_path": row["origin_path"],
        "source_ref": row["source_ref"],
        "content_hash": row["content_hash"],
        "last_synced_at": row["last_synced_at"],
        "sync_status": row["sync_status"],
        "content_summary": row["content_summary"],
        "skill_markdown": row["skill_markdown"],
        "asset_paths": json_load(row["asset_paths_json"], []),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_skill_folder(row: Any) -> dict[str, Any]:
    return {
        "folder_id": row["folder_id"],
        "name": row["name"],
        "description": row["description"],
        "source_scope": row["source_scope"],
        "sort_order": int(row["sort_order"]),
        "skill_count": int(row["skill_count"] or 0),
        "installed_count": int(row["installed_count"] or 0),
        "native_count": int(row["native_count"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_workflow(
    row: Any,
    *,
    json_load: Callable[[str | None, Any], Any],
) -> dict[str, Any]:
    return {
        "workflow_id": row["workflow_id"],
        "name": row["name"],
        "description": row["description"],
        "nodes": json_load(row["nodes_json"], []),
        "edges": json_load(row["edges_json"], []),
        "default_input_schema": json_load(row["default_input_schema_json"], {}),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_run_group(
    row: Any,
    *,
    json_load: Callable[[str | None, Any], Any],
) -> dict[str, Any]:
    child_run_ids = json_load(row["child_run_ids_json"], [])
    return {
        "run_group_id": row["run_group_id"],
        "title": row["title"],
        "source": row["source"],
        "workspace_dir": row["workspace_dir"],
        "status": row["status"],
        "summary": row["summary"],
        "child_run_ids": child_run_ids if isinstance(child_run_ids, list) else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
