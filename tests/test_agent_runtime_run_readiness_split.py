"""Tests for run readiness validation split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_readiness import RuntimeRunReadinessValidator, native_agent_readiness
from apps.shell.agent.tools.policy import RuntimePolicyCompiler
from apps.shell.model_profiles import ModelProfileError


def test_run_readiness_validator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunReadinessValidator is RuntimeRunReadinessValidator


def test_native_agent_readiness_projects_model_profile_state() -> None:
    service = FakeProfileService()

    assert native_agent_readiness(
        profile_service_factory=lambda: service,
        supports_openai_compatible_api=lambda _provider: True,
        redact_error=str,
    ) == {
        "ready": False,
        "code": "native_agent_not_ready",
        "reason": "model_profile_required",
        "message": "请先配置并选择默认对话模型。",
        "capabilities": {
            "model": False,
            "image_input": False,
            "tools": False,
            "approval": False,
        },
    }

    service.defaults["chat"] = "chat-1"
    service.profiles["chat-1"] = {
        "enabled": True,
        "status": "available",
        "capability": "chat",
        "provider": "openai_compatible",
        "base_url": "https://api.example.test/v1",
        "model": "demo-model",
        "api_key": "sk-demo",
    }

    readiness = native_agent_readiness(
        profile_service_factory=lambda: service,
        supports_openai_compatible_api=lambda provider: provider == "openai_compatible",
        redact_error=str,
    )

    assert readiness == {
        "ready": True,
        "code": "",
        "reason": "",
        "message": "",
        "profile_id": "chat-1",
        "model": "demo-model",
        "provider": "openai_compatible",
        "capabilities": {
            "model": True,
            "image_input": True,
            "tools": False,
            "approval": False,
        },
    }

    service.profiles["chat-1"]["provider"] = "native_only"
    unsupported = native_agent_readiness(
        profile_service_factory=lambda: service,
        supports_openai_compatible_api=lambda _provider: False,
        redact_error=str,
    )
    assert unsupported["ready"] is False
    assert unsupported["code"] == "native_agent_not_ready"
    assert unsupported["reason"] == "model_profile_unavailable"
    assert unsupported["message"] == "Native Agent 当前仅支持 OpenAI-compatible 对话模型。"
    assert unsupported["capabilities"]["model"] is False


def test_native_agent_readiness_probes_model_credential_without_exposing_it() -> None:
    class StartupProfileService:
        private_reads = 0

        def get_defaults(self) -> dict[str, str]:
            return {"chat": "chat-1"}

        def get_profile(self, profile_id: str) -> dict[str, object]:
            assert profile_id == "chat-1"
            return {
                "enabled": True,
                "status": "available",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key_configured": True,
            }

        def get_profile_private(self, profile_id: str) -> dict[str, object]:
            assert profile_id == "chat-1"
            self.private_reads += 1
            return {
                **self.get_profile(profile_id),
                "api_key": "sk-readiness-probe-secret",
            }

    service = StartupProfileService()
    readiness = native_agent_readiness(
        profile_service_factory=lambda: service,
        supports_openai_compatible_api=lambda provider: provider == "openai_compatible",
        redact_error=str,
    )

    assert readiness["ready"] is True
    assert readiness["profile_id"] == "chat-1"
    assert service.private_reads == 1
    assert "sk-readiness-probe-secret" not in str(readiness)


def test_native_agent_readiness_reports_inaccessible_keychain_credential() -> None:
    class InaccessibleCredentialProfileService:
        def get_defaults(self) -> dict[str, str]:
            return {"chat": "chat-1"}

        def get_profile(self, profile_id: str) -> dict[str, object]:
            assert profile_id == "chat-1"
            return {
                "enabled": True,
                "status": "available",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key_configured": True,
            }

        def get_profile_private(self, profile_id: str) -> dict[str, object]:
            assert profile_id == "chat-1"
            raise ModelProfileError(
                "应用更新后无法读取原有钥匙串中的 API Key。"
                "请在「模型配置」中重新保存 API Key，然后重新测试连接。",
                code="credential_reentry_required",
            )

    readiness = native_agent_readiness(
        profile_service_factory=InaccessibleCredentialProfileService,
        supports_openai_compatible_api=lambda provider: provider == "openai_compatible",
        redact_error=str,
    )

    assert readiness["ready"] is False
    assert readiness["code"] == "native_agent_not_ready"
    assert readiness["reason"] == "model_profile_unavailable"
    assert "重新保存 API Key" in readiness["message"]
    assert "重新测试连接" in readiness["message"]
    assert readiness["capabilities"]["model"] is False


def test_run_readiness_validator_projects_workflow_agent_node() -> None:
    validator = _validator(
        agents={
            "agent-1": {
                "agent_id": "agent-1",
                "name": "Research",
                "enabled": True,
            }
        },
    )

    agent = validator.workflow_agent_for_node(
        {"id": "research", "type": "agent", "data": {"agent_id": "agent-1"}}
    )

    assert agent["name"] == "Research"
    with pytest.raises(AgentRuntimeError, match="没有选择 Agent"):
        validator.workflow_agent_for_node({"id": "empty", "type": "agent", "data": {}})


def test_workflow_agent_node_can_override_tool_policy_without_mutating_agent() -> None:
    stored_agent = {
        "agent_id": "agent-1",
        "name": "Research",
        "enabled": True,
        "tool_policy": {"allowed_tools": ["workspace.read"]},
    }
    validator = _validator(agents={"agent-1": stored_agent})

    agent = validator.workflow_agent_for_node(
        {
            "id": "screen-review",
            "type": "agent",
            "data": {
                "agent_id": "agent-1",
                "tool_policy": {
                    "allowed_tools": ["screen.capture", "terminal.run"],
                    "approval_required": {},
                },
            },
        }
    )
    compiled = RuntimePolicyCompiler().compile_tool_policy(
        str(agent.get("category") or "custom"),
        agent.get("tool_policy"),
    )

    assert agent["tool_policy"]["allowed_tools"] == ["screen.capture", "terminal.run"]
    assert stored_agent["tool_policy"]["allowed_tools"] == ["workspace.read"]
    assert compiled["allowed_tools"] == ["screen.capture", "terminal.run"]
    assert compiled["approval_required"] == {"terminal.run": True}


def test_run_readiness_validator_rejects_self_referencing_subworkflow() -> None:
    validator = _validator(
        workflows={
            "workflow-1": {
                "workflow_id": "workflow-1",
                "name": "Parent",
                "enabled": True,
            }
        },
    )

    with pytest.raises(AgentRuntimeError, match="不能引用当前 Workflow"):
        validator.validate_workflow_subworkflow_nodes(
            [
                {
                    "id": "child",
                    "type": "workflow",
                    "data": {"workflow_id": "workflow-1", "label": "Child Flow"},
                }
            ],
            parent_workflow_id="workflow-1",
        )


def test_run_readiness_validator_checks_agent_model_configuration() -> None:
    validator = _validator()

    with pytest.raises(AgentRuntimeError, match="缺少可运行的 Chat Profile"):
        validator.validate_agent_run_readiness(
            {
                "agent_id": "custom-agent",
                "name": "Custom Agent",
                "enabled": True,
                "model_mode": "profile",
                "skill_ids": [],
            },
            require_model_config=True,
        )
    with pytest.raises(AgentRuntimeError, match="缺少 API Key"):
        validator.validate_agent_run_readiness(
            {
                "agent_id": "api-agent",
                "name": "API Agent",
                "enabled": True,
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                },
                "skill_ids": [],
            },
            require_model_config=True,
        )


def _validator(
    *,
    agents: dict[str, dict[str, object]] | None = None,
    workflows: dict[str, dict[str, object]] | None = None,
) -> RuntimeRunReadinessValidator:
    agents = agents or {}
    workflows = workflows or {}

    def get_agent_private(agent_id: str) -> dict[str, object]:
        if agent_id not in agents:
            raise KeyError(agent_id)
        return agents[agent_id]

    def get_workflow(workflow_id: str) -> dict[str, object]:
        if workflow_id not in workflows:
            raise KeyError(workflow_id)
        return workflows[workflow_id]

    def load_agent_skills(_skill_ids: list[str]) -> list[dict[str, object]]:
        return []

    def agent_model_config_private(agent: dict[str, object]) -> dict[str, object]:
        if str(agent.get("model_mode") or "") == "custom_api":
            return dict(agent.get("model_config") or {})
        profile_id = str(agent.get("model_profile_id") or "")
        if not profile_id:
            raise AgentRuntimeError("Chat Profile 不存在")
        return {"profile_id": profile_id}

    return RuntimeRunReadinessValidator(
        node_kind=_node_kind,
        get_agent_private=get_agent_private,
        get_workflow=get_workflow,
        load_agent_skills=load_agent_skills,
        agent_model_config_private=agent_model_config_private,
        default_agent_ids={"builtin"},
    )


def _node_kind(node: dict[str, object]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
    node_type = str(node.get("type") or "").strip()
    if data_kind and node_type in {"", "input", "default", "output"}:
        return data_kind
    return node_type or data_kind


class FakeProfileService:
    def __init__(self) -> None:
        self.defaults: dict[str, str] = {}
        self.profiles: dict[str, dict[str, object]] = {}

    def get_defaults(self) -> dict[str, str]:
        return dict(self.defaults)

    def get_profile_private(self, profile_id: str) -> dict[str, object]:
        if profile_id not in self.profiles:
            raise KeyError(profile_id)
        return self.profiles[profile_id]
