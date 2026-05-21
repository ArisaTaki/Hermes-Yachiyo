"""Agent Runtime Service tests."""

from __future__ import annotations

import json
import sqlite3
import zipfile

import pytest

from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService, ToolBroker


def make_service(tmp_path, *, seed_templates: bool = False) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        seed_templates=seed_templates,
    )


def test_runtime_migrates_legacy_runs_before_index_creation(tmp_path):
    db_path = tmp_path / "agent-runtime.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            runnable_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_goal TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            timeline_json TEXT NOT NULL DEFAULT '[]',
            artifacts_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.close()

    service = make_service(tmp_path)
    try:
        columns = {row["name"] for row in service._conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "run_group_id" in columns
        indexes = {row["name"] for row in service._conn.execute("PRAGMA index_list(runs)").fetchall()}
        assert "idx_runs_group_updated" in indexes
    finally:
        service.close()


def test_runtime_restores_row_factory_before_listing_runnables(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service._conn.row_factory = None
        result = service.list_runnables()
        assert result["ok"] is True
        assert any(item["id"] == "agent_coding" for item in result["runnables"])
    finally:
        service.close()


def test_agent_crud_and_api_key_redaction(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Private Model",
                "nickname": "Private",
                "persona_prompt": "Keep a concise operator tone.",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-test-secret",
                },
            }
        )

        assert agent["model_config"]["api_key_configured"] is True
        assert "api_key" not in agent["model_config"]
        assert agent["nickname"] == "Private"
        assert agent["persona_prompt"] == "Keep a concise operator tone."

        updated = service.update_agent(
            agent["agent_id"],
            {
                "description": "updated",
                "nickname": "Private Ops",
                "model_config": {"base_url": "https://gateway.example.test/v1", "api_key": ""},
            },
        )
        assert updated["description"] == "updated"
        assert updated["nickname"] == "Private Ops"
        assert updated["model_config"]["base_url"] == "https://gateway.example.test/v1"
        assert updated["model_config"]["api_key_configured"] is True
    finally:
        service.close()


def test_agent_and_workflow_names_are_globally_unique(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_agent({"name": "Shared Name"})
        with pytest.raises(AgentRuntimeError):
            service.create_workflow(
                {
                    "name": "shared name",
                    "nodes": [{"id": "start", "type": "start", "data": {"label": "Start"}}],
                    "edges": [],
                }
            )
    finally:
        service.close()


def test_import_skill_directory_and_mount_to_agent(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    source = tmp_path / "demo-skill"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo Skill\n\nUseful instruction.", encoding="utf-8")
    (source / "assets" / "sample.txt").write_text("asset", encoding="utf-8")
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Demo Skill used"})
    try:
        skill = service.import_skill(str(source))
        agent = service.create_agent(
            {
                "name": "Skill Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        mounted = service.attach_skill(agent["agent_id"], skill["skill_id"])

        assert skill["name"] == "Demo Skill"
        assert skill["source_path"] == "local:demo-skill"
        assert skill["local_path"].endswith(skill["skill_id"])
        assert skill["enabled"] is True
        assert skill["asset_paths"] == ["assets/sample.txt"]
        assert mounted["skill_ids"] == [skill["skill_id"]]
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use the skill"})
        assert run["result"] == "Demo Skill used"
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")
        assert artifact["ok"] is True
        assert "Useful instruction" in artifact["content"]
        assert run["run_group_id"]
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "agent"
        assert group["child_run_ids"] == [run["run_id"]]
        disabled = service.update_skill(skill["skill_id"], {"enabled": False})
        assert disabled["enabled"] is False
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use disabled skill"})
        other_agent = service.create_agent({"name": "Other Skill Agent"})
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.attach_skill(other_agent["agent_id"], skill["skill_id"])
        with pytest.raises(AgentRuntimeError):
            service.read_run_artifact(run["run_id"], "../escape.md")
    finally:
        service.close()


def test_agent_context_includes_nickname_and_persona_prompt(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "ok"})
    try:
        agent = service.create_agent(
            {
                "name": "Context Agent",
                "nickname": "Ctx",
                "instructions": "Always inspect the local brief.",
                "persona_prompt": "Speak like a careful reviewer.",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Check context"})
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")

        assert "Nickname: Ctx" in artifact["content"]
        assert "# Functional Instructions" in artifact["content"]
        assert "Always inspect the local brief." in artifact["content"]
        assert "# Persona Prompt" in artifact["content"]
        assert "Speak like a careful reviewer." in artifact["content"]
    finally:
        service.close()


def test_import_skill_rejects_missing_skill_md(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "bad-skill"
    source.mkdir()
    try:
        with pytest.raises(AgentRuntimeError):
            service.import_skill(str(source))
    finally:
        service.close()


def test_import_skill_zip_rejects_path_traversal(tmp_path):
    service = make_service(tmp_path)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../SKILL.md", "# Bad")
    try:
        with pytest.raises(AgentRuntimeError):
            service.import_skill(str(archive))
    finally:
        service.close()


def test_workflow_validation_rejects_branch_and_cycle(tmp_path):
    service = make_service(tmp_path)
    try:
        nodes = [
            {"id": "start", "type": "start", "data": {"label": "Start"}},
            {"id": "a", "type": "agent", "data": {"label": "A"}},
            {"id": "b", "type": "agent", "data": {"label": "B"}},
        ]
        with pytest.raises(AgentRuntimeError):
            service.validate_workflow(
                nodes,
                [
                    {"source": "start", "target": "a"},
                    {"source": "start", "target": "b"},
                ],
            )
        with pytest.raises(AgentRuntimeError):
            service.validate_workflow(
                nodes,
                [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "a"},
                ],
            )
    finally:
        service.close()


def test_linear_workflow_executes_agent_nodes_in_order(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Profile result"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Agent A", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Agent B", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Linear Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Agent A", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Agent B", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "completed"
        assert run["run_group_id"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 2
        assert run["result"] == "Profile result"
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "workflow"
        assert len(group["child_run_ids"]) == 3
    finally:
        service.close()


def test_agent_execution_backend_legacy_values_normalize_to_yachiyo(tmp_path):
    service = make_service(tmp_path)
    try:
        hermes_agent = service.create_agent({"name": "Hermes Agent"})
        assert hermes_agent["execution_backend"] == "yachiyo_profile"
        run = service.create_agent_run({"agent_id": hermes_agent["agent_id"], "user_goal": "Plan"})
        assert run["status"] == "failed"
        assert "Chat Profile" in run["result"]

        external = service.create_agent({"name": "CLI Agent", "execution_backend": "external_cli"})
        assert external["execution_backend"] == "yachiyo_profile"
        external_run = service.create_agent_run({"agent_id": external["agent_id"], "user_goal": "Review"})
        assert external_run["status"] == "failed"
        assert "Chat Profile" in external_run["result"]
    finally:
        service.close()


def test_delegation_targets_and_delegate_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Delegated result"})
    try:
        agent = service.create_agent(
            {
                "name": "Delegated Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        targets = service.list_delegation_targets()
        assert any(item["name"] == "Delegated Agent" for item in targets["agents"])

        result = service.delegate_runnable(kind="agent", name="Delegated Agent", user_goal="Do the work")
        assert result["ok"] is True
        assert result["runnable"]["id"] == agent["agent_id"]
        assert result["result"] == "Delegated result"
        run = service.get_run(result["run_id"])
        assert run["status"] == "completed"
        assert run["run_group_id"]
    finally:
        service.close()


def test_agent_run_executes_native_tool_call_and_continues(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello native tools", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "workspace_read" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "README.md"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "hello native tools" in messages[-1]["content"]
        return {"content": "Read complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Read README"})

        assert run["status"] == "completed"
        assert run["result"] == "Read complete"
        assert any(event["event"] == "agent.tool.call" and event["detail"] == "workspace.read" for event in run["timeline"])
    finally:
        service.close()


def test_agent_run_json_fallback_writes_artifact(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "notes.md", "content": "hello"}})}
        assert "Tool result for artifact.write" in messages[-1]["content"]
        return {"content": "Artifact done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Artifact Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write artifact"})

        assert run["status"] == "completed"
        assert any(artifact.get("path") == "notes.md" for artifact in run["artifacts"])
        assert service.read_run_artifact(run["run_id"], "notes.md")["content"] == "hello"
    finally:
        service.close()


def test_agent_run_denies_unallowed_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "echo no"})},
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Denied Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})

        assert run["status"] == "failed"
        assert "未授权工具" in run["result"]
        assert any(event["event"] == "agent.tool.denied" for event in run["timeline"])
    finally:
        service.close()


def test_agent_run_pauses_for_terminal_approval_and_resumes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf approved"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "approved" in messages[-1]["content"]
        return {"content": "Command complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert "messages" not in run["pending_approval"]
        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Command complete"
        assert service.get_run_group(resumed["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_agent_run_rejects_pending_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": json.dumps({"action": "tool", "tool": "terminal.run", "input": {"command": "echo blocked"}})
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Reject Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})
        rejected = service.reject_run_approval(run["run_id"], "not now")

        assert rejected["status"] == "cancelled"
        assert rejected["pending_approval"] == {}
        assert "not now" in rejected["result"]
    finally:
        service.close()


def test_model_payload_approved_flag_does_not_bypass_write_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "workspace_write_patch",
                        "arguments": json.dumps({"path": "src/out.txt", "content": "bad", "approved": True}),
                    },
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."], "writable_scopes": ["src"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write file"})

        assert run["status"] == "approval_required"
        assert not (workdir / "src" / "out.txt").exists()
    finally:
        service.close()


def test_tool_broker_blocks_out_of_scope_and_unapproved_terminal(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["src"],
        },
        tmp_path / "artifacts",
    )

    assert broker.workspace_read("README.md")["content"] == "hello"
    with pytest.raises(AgentRuntimeError):
        broker.workspace_write_patch("../escape.txt", "bad", approved=True)
    assert broker.terminal_run("echo should-not-run")["approval_required"] is True
    assert broker.call("terminal.run", {"command": "echo should-not-run", "approved": True})["approval_required"] is True


@pytest.mark.asyncio
async def test_run_approval_routes_return_404_and_400(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Done"})
    try:
        with pytest.raises(HTTPException) as missing:
            await agent_routes.approve_run_approval("run_missing")
        assert missing.value.status_code == 404

        agent = service.create_agent(
            {
                "name": "Done Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Finish"})
        with pytest.raises(HTTPException) as invalid:
            await agent_routes.approve_run_approval(run["run_id"])
        assert invalid.value.status_code == 400
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_update_route_toggles_enabled_and_returns_404(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    source = tmp_path / "route-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Route Skill\n\nRoute import.", encoding="utf-8")
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        skill = service.import_skill(str(source))
        updated = await agent_routes.update_skill(
            skill["skill_id"],
            agent_routes.SkillUpdateRequest(enabled=False),
        )
        assert updated["enabled"] is False

        with pytest.raises(HTTPException) as missing:
            await agent_routes.update_skill("missing", agent_routes.SkillUpdateRequest(enabled=True))
        assert missing.value.status_code == 404
    finally:
        service.close()
