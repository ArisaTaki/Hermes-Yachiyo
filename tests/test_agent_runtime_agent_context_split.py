"""Tests for Agent context helpers split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_context import (
    AgentContextBuilder,
    agent_goal_disallows_tool,
    agent_output_contract_rules,
    user_goal_from_agent_messages,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _compile_agent_runtime(_agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime": "oha_agent",
        "tool_policy": {
            "allowed_tools": ["workspace.read", "artifact.write"],
            "approval_required": {"terminal.run": True},
        },
        "workspace_policy": {
            "default_workdir": "/tmp/project",
            "readable_scopes": ["."],
            "writable_scopes": [],
        },
    }


def _load_agent_skills(skill_ids: list[str]) -> list[dict[str, Any]]:
    assert skill_ids == ["skill-1"]
    return [
        {
            "skill_id": "skill-1",
            "name": "Brief Reader",
            "description": "Read local briefs.",
            "content_summary": "Inspect the project brief before acting.",
            "asset_paths": ["templates/brief.md"],
        }
    ]


def test_agent_context_builder_projects_model_visible_runtime_context() -> None:
    builder = AgentContextBuilder(
        compile_agent_runtime=_compile_agent_runtime,
        load_agent_skills=_load_agent_skills,
        long_term_memory_context=lambda: "Remember compact updates.",
        operating_doctrine="Follow approval gates.",
    )

    context = builder.build(
        {
            "name": "Context Agent",
            "nickname": "Ctx",
            "category": "review",
            "instructions": "Inspect first.",
            "persona_prompt": "Be precise.",
            "skill_ids": ["skill-1"],
            "output_contract": "report",
        },
        "Review the current plan.",
        "Parent run summary.",
    )

    assert "# Agent\nName: Context Agent\nNickname: Ctx\nCategory: review" in context
    assert "# Functional Instructions\nInspect first." in context
    assert "# Persona Prompt\nBe precise." in context
    assert "# Operating Doctrine\nFollow approval gates." in context
    assert "skill_id: skill-1" in context
    assert "assets/templates: templates/brief.md" in context
    assert "# Long-term Memory\nRemember compact updates." in context
    assert "Allowed tools: workspace.read, artifact.write" in context
    assert 'Approval required: {"terminal.run": true}' in context
    assert '"default_workdir": "/tmp/project"' in context
    assert "# Upstream Context\nParent run summary." in context
    assert "# User Goal\nReview the current plan." in context
    assert "Contract: report" in context


def test_agent_goal_helpers_remain_behaviorally_compatible() -> None:
    messages = [
        {"role": "assistant", "content": "ignored"},
        {"role": "user", "content": "# User Goal\nShow code inline only.\n# Runtime\nx"},
    ]

    assert agent_runtime._user_goal_from_agent_messages is user_goal_from_agent_messages
    assert agent_runtime._agent_output_contract_rules is agent_output_contract_rules
    assert agent_runtime._agent_goal_disallows_tool is agent_goal_disallows_tool
    assert user_goal_from_agent_messages(messages) == "Show code inline only."
    assert agent_runtime._user_goal_from_agent_messages(messages) == "Show code inline only."
    assert agent_output_contract_rules("diff") == agent_runtime._agent_output_contract_rules("diff")
    assert "Contract: diff" in agent_output_contract_rules("diff")

    no_file_reason = agent_goal_disallows_tool(
        "只需要展示代码，不要修改文件",
        "workspace.write_patch",
    )
    assert no_file_reason
    assert no_file_reason == agent_runtime._agent_goal_disallows_tool(
        "只需要展示代码，不要修改文件",
        "workspace.write_patch",
    )

    assert agent_goal_disallows_tool("不要运行命令", "terminal.run")
    assert not agent_goal_disallows_tool(
        "必须调用 terminal.run 来完成检查，不要运行其他命令",
        "terminal.run",
    )


def test_native_runtime_uses_split_agent_context_builder(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.AgentContextBuilder is AgentContextBuilder
        assert isinstance(service.agent_context_builder, AgentContextBuilder)
    finally:
        service.close()
