"""Tests for AgentDefinitionRepository split out of the legacy runtime."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _connect_agents_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            avatar_url TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'custom',
            instructions TEXT NOT NULL DEFAULT '',
            persona_prompt TEXT NOT NULL DEFAULT '',
            model_mode TEXT NOT NULL DEFAULT 'profile',
            execution_backend TEXT NOT NULL DEFAULT 'native_profile',
            model_profile_id TEXT NOT NULL DEFAULT '',
            vision_model_profile_id TEXT NOT NULL DEFAULT '',
            model_provider TEXT NOT NULL DEFAULT '',
            model_base_url TEXT NOT NULL DEFAULT '',
            model_name TEXT NOT NULL DEFAULT '',
            model_api_key TEXT NOT NULL DEFAULT '',
            model_credential_ref TEXT NOT NULL DEFAULT '',
            tool_policy_json TEXT NOT NULL DEFAULT '{}',
            workspace_policy_json TEXT NOT NULL DEFAULT '{}',
            skill_ids_json TEXT NOT NULL DEFAULT '[]',
            output_contract TEXT NOT NULL DEFAULT 'chat',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def _row_to_agent(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "agent_id": str(row["agent_id"]),
        "name": str(row["name"]),
        "nickname": str(row["nickname"] or row["name"]),
        "description": str(row["description"]),
        "avatar_url": str(row["avatar_url"]),
        "category": str(row["category"]),
        "instructions": str(row["instructions"]),
        "persona_prompt": str(row["persona_prompt"]),
        "model_mode": str(row["model_mode"]),
        "execution_backend": str(row["execution_backend"]),
        "model_profile_id": str(row["model_profile_id"]),
        "vision_model_profile_id": str(row["vision_model_profile_id"]),
        "model_config": {
            "provider": str(row["model_provider"]),
            "base_url": str(row["model_base_url"]),
            "model": str(row["model_name"]),
            "api_key_configured": bool(str(row["model_credential_ref"] or "").strip() or str(row["model_api_key"] or "").strip()),
        },
        "tool_policy": _json_load(row["tool_policy_json"], {}),
        "workspace_policy": _json_load(row["workspace_policy_json"], {}),
        "skill_ids": _json_load(row["skill_ids_json"], []),
        "output_contract": str(row["output_contract"]),
        "enabled": bool(row["enabled"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def test_agent_definition_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.AgentDefinitionRepository is AgentDefinitionRepository


def test_agent_definition_repository_lifecycle_and_policy_callbacks() -> None:
    conn = _connect_agents_db()
    now_values = iter(["2026-06-15T10:00:00Z", "2026-06-15T10:01:00Z"])
    credentials: dict[str, str] = {}
    deleted_credentials: list[str] = []
    name_checks: list[tuple[str, str]] = []
    trusted_workspaces: list[tuple[dict[str, Any], str, bool]] = []
    deletion_events: list[tuple[str, str, str]] = []

    def row_to_agent_private(row: sqlite3.Row) -> dict[str, Any]:
        agent = _row_to_agent(row)
        credential_ref = str(row["model_credential_ref"] or "")
        agent["model_config"]["credential_ref"] = credential_ref
        agent["model_config"]["api_key"] = credentials.get(credential_ref, str(row["model_api_key"] or ""))
        return agent

    def ensure_name(name: str, *, ignore_agent_id: str = "", **_: Any) -> None:
        name_checks.append((name, ignore_agent_id))
        if name.strip().lower() == "duplicate":
            raise AgentRuntimeError("Agent/Workflow 名称必须全局唯一")

    repo = AgentDefinitionRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_agent=_row_to_agent,
        row_to_agent_private=row_to_agent_private,
        coerce_named_row=lambda row, _description: row,
        main_chat_virtual_agent=lambda: {"agent_id": "builtin:yachiyo-main", "name": "Yachiyo", "model_config": {}},
        now=lambda: next(now_values),
        json_dump=_json_dump,
        agent_id_factory=lambda name: f"agent_{name.lower().replace(' ', '_')}",
        normalize_execution_backend=lambda value, *, model_mode: f"backend:{value or model_mode}",
        ensure_global_name_available=ensure_name,
        validate_agent_profile_refs=lambda payload: payload.setdefault("_profiles_validated", True),
        compile_tool_policy=lambda category, policy: {"allowed_tools": [category], "approval_required": policy or {}},
        compile_workspace_policy=lambda policy: {"default_workdir": str((policy or {}).get("default_workdir") or "")},
        assign_default_agent_workdir=lambda agent_id, workspace_policy, _tool_policy: {
            **workspace_policy,
            "default_workdir": workspace_policy.get("default_workdir") or f"/workspaces/{agent_id}",
        },
        trust_workspace_from_policy=lambda policy, *, source, commit: trusted_workspaces.append((policy, source, commit)),
        agent_model_credential_ref=lambda agent_id: f"agent:{agent_id}:model_api_key",
        store_credential=lambda ref, secret: credentials.__setitem__(ref, secret),
        delete_credential=lambda ref: deleted_credentials.append(ref),
        record_studio_deletion=lambda kind, key: deletion_events.append(("record", kind, key)),
        clear_studio_deletion=lambda kind, key: deletion_events.append(("clear", kind, key)),
        system_agent_ids={"builtin:yachiyo-main"},
        main_chat_agent_id="builtin:yachiyo-main",
        error_type=AgentRuntimeError,
    )

    assert repo.list()["agents"][0]["agent_id"] == "builtin:yachiyo-main"
    created = repo.create(
        {
            "name": "Design Agent",
            "category": "design",
            "model_mode": "custom_api",
            "execution_backend": "external_cli",
            "model_config": {
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-create",
            },
            "skill_ids": ["skill-1"],
        }
    )

    assert created["agent_id"] == "agent_design_agent"
    assert created["execution_backend"] == "backend:external_cli"
    assert created["model_config"]["api_key_configured"] is True
    assert created["skill_ids"] == ["skill-1"]
    assert credentials == {"agent:agent_design_agent:model_api_key": "sk-create"}
    assert trusted_workspaces == [
        ({"default_workdir": "/workspaces/agent_design_agent"}, "agent:agent_design_agent", False)
    ]
    assert deletion_events == [("clear", "agent", "agent_design_agent")]
    assert repo.get_private("agent_design_agent")["model_config"]["api_key"] == "sk-create"

    updated = repo.update(
        "agent_design_agent",
        {
            "name": "Design Agent v2",
            "enabled": False,
            "model_config": {"model": "demo-model-v2"},
        },
    )
    assert updated["name"] == "Design Agent v2"
    assert updated["enabled"] is False
    assert updated["model_config"]["model"] == "demo-model-v2"
    assert name_checks[-1] == ("Design Agent v2", "agent_design_agent")
    assert credentials == {"agent:agent_design_agent:model_api_key": "sk-create"}

    assert repo.delete("agent_design_agent") == {"ok": True}
    assert deletion_events[-1] == ("record", "agent", "agent_design_agent")
    assert deleted_credentials == ["agent:agent_design_agent:model_api_key"]
    with pytest.raises(AgentRuntimeError, match="系统 Agent"):
        repo.delete("builtin:yachiyo-main")


def test_native_runtime_uses_split_agent_definition_repository(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        agent = service.create_agent({"name": "Runtime Agent"})

        assert isinstance(service.agent_definitions, AgentDefinitionRepository)
        assert service.get_agent(agent["agent_id"])["name"] == "Runtime Agent"
        assert service.update_agent(agent["agent_id"], {"enabled": False})["enabled"] is False
        assert service.delete_agent(agent["agent_id"]) == {"ok": True}
    finally:
        service.close()
