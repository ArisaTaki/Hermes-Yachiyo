from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def row_to_agent(
    row: Any,
    *,
    json_load: Callable[[str | None, Any], Any],
    default_tool_policy: Callable[[str], dict[str, Any]],
    default_workspace_policy: Callable[[], dict[str, Any]],
    compile_tool_policy: Callable[[str, Any], dict[str, Any]],
    compile_workspace_policy: Callable[[Any], dict[str, Any]],
    normalize_execution_backend: Callable[..., str],
) -> dict[str, Any]:
    category = str(row["category"] or "custom")
    model_mode = str(row["model_mode"] or "")
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "nickname": row["nickname"] or row["name"],
        "description": row["description"],
        "avatar_url": row["avatar_url"],
        "category": row["category"],
        "instructions": row["instructions"],
        "persona_prompt": row["persona_prompt"],
        "model_mode": row["model_mode"],
        "execution_backend": normalize_execution_backend(row["execution_backend"], model_mode=model_mode),
        "model_profile_id": row["model_profile_id"],
        "vision_model_profile_id": row["vision_model_profile_id"],
        "model_config": {
            "provider": row["model_provider"],
            "base_url": row["model_base_url"],
            "model": row["model_name"],
            "api_key_configured": bool(
                str(row["model_credential_ref"] or "").strip()
                or str(row["model_api_key"] or "").strip()
            ),
        },
        "tool_policy": compile_tool_policy(
            category,
            json_load(row["tool_policy_json"], default_tool_policy(category)),
        ),
        "workspace_policy": compile_workspace_policy(
            json_load(row["workspace_policy_json"], default_workspace_policy()),
        ),
        "skill_ids": json_load(row["skill_ids_json"], []),
        "output_contract": row["output_contract"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_agent_private(
    row: Any,
    *,
    row_to_agent: Callable[[Any], dict[str, Any]],
    read_credential: Callable[[str], str],
) -> dict[str, Any]:
    agent = row_to_agent(row)
    credential_ref = str(row["model_credential_ref"] or "")
    agent["model_config"]["credential_ref"] = row["model_credential_ref"]
    agent["model_config"]["api_key"] = read_credential(credential_ref) or str(row["model_api_key"] or "")
    return agent


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


def row_to_run(
    row: Any,
    *,
    json_load: Callable[[str | None, Any], Any],
    public_pending_approval: Callable[[Any], dict[str, Any]],
    task_run_link_for_run: Callable[[str], dict[str, Any] | None],
    run_group_source: Callable[[str], str],
    runnable_name: Callable[[str, str], str],
) -> dict[str, Any]:
    row_keys = set(row.keys()) if hasattr(row, "keys") else set()
    run_group_id = row["run_group_id"]
    run_id = str(row["run_id"] or "")
    task_link = task_run_link_for_run(run_id)
    kind = str(row["kind"])
    runnable_id = str(row["runnable_id"])
    return {
        "run_id": row["run_id"],
        "task_id": str(task_link["task_id"] or "") if task_link is not None else "",
        "session_id": str(task_link["session_id"] or "") if task_link is not None else "",
        "task_run_link_created_at": str(task_link["created_at"] or "") if task_link is not None else "",
        "task_run_link_updated_at": str(task_link["updated_at"] or "") if task_link is not None else "",
        "task_run_link_run_status": str(task_link["run_status"] or "") if task_link is not None else "",
        "task_run_link_last_event_sequence": (
            int(task_link["last_event_sequence"] or 0) if task_link is not None else 0
        ),
        "run_group_id": run_group_id,
        "run_group_source": (
            str(row["run_group_source"] or "")
            if "run_group_source" in row_keys
            else run_group_source(str(run_group_id or ""))
        ),
        "client_request_id": str(row["client_request_id"] or "") if "client_request_id" in row_keys else "",
        "kind": row["kind"],
        "runnable_id": row["runnable_id"],
        "runnable_name": runnable_name(kind, runnable_id),
        "status": row["status"],
        "user_goal": row["user_goal"],
        "result": row["result"],
        "timeline": json_load(row["timeline_json"], []),
        "artifacts": json_load(row["artifacts_json"], []),
        "pending_approval": public_pending_approval(json_load(row["pending_approval_json"], {})),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
