"""Run readiness validation for Agent and Workflow runtime entries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_path import WorkflowPathPlanner


def native_agent_readiness(
    *,
    profile_service_factory: Callable[[], Any],
    supports_openai_compatible_api: Callable[[str], bool],
    redact_error: Callable[[Any], str],
) -> dict[str, Any]:
    """Project native main-agent readiness from the model profile service."""
    private_profile: dict[str, Any] | None = None
    try:
        profile_service = profile_service_factory()
        profile_id = str(profile_service.get_defaults().get("chat") or "").strip()
        if not profile_id:
            return native_agent_not_ready(
                reason="model_profile_required",
                message="请先配置并选择默认对话模型。",
            )
        get_profile = getattr(profile_service, "get_profile", None)
        if callable(get_profile):
            profile = get_profile(profile_id)
        else:
            private_profile = profile_service.get_profile_private(profile_id)
            profile = private_profile
    except KeyError:
        return native_agent_not_ready(
            reason="model_profile_required",
            message="默认对话模型不存在，请重新选择。",
        )
    except Exception as exc:
        return native_agent_not_ready(
            reason="model_profile_unavailable",
            message=redact_error(exc),
        )

    reason = ""
    if not profile.get("enabled", True):
        reason = "默认对话模型已停用。"
    elif str(profile.get("status") or "") != "available":
        reason = "默认对话模型尚未通过连接测试。"
    elif str(profile.get("capability") or "") != "chat":
        reason = "默认模型不是对话模型。"
    elif not supports_openai_compatible_api(str(profile.get("provider") or "openai_compatible")):
        reason = "Native Agent 当前仅支持 OpenAI-compatible 对话模型。"
    elif not (
        all(str(profile.get(key) or "").strip() for key in ("base_url", "model"))
        and bool(
            profile.get("api_key_configured")
            if "api_key_configured" in profile
            else str(profile.get("api_key") or "").strip()
        )
    ):
        reason = "默认对话模型配置不完整。"

    if not reason:
        try:
            if private_profile is None:
                private_profile = profile_service.get_profile_private(profile_id)
            credential_accessible = bool(
                str(private_profile.get("api_key") or "").strip()
            )
        except KeyError:
            return native_agent_not_ready(
                reason="model_profile_required",
                message="默认对话模型不存在，请重新选择。",
            )
        except Exception as exc:
            return native_agent_not_ready(
                reason="model_profile_unavailable",
                message=redact_error(exc),
            )
        if not credential_accessible:
            reason = "默认对话模型配置不完整。"

    ready = not reason
    return {
        "ready": ready,
        "code": "" if ready else "native_agent_not_ready",
        "reason": "" if ready else "model_profile_unavailable",
        "message": reason,
        "profile_id": profile_id,
        "model": str(profile.get("model") or ""),
        "provider": str(profile.get("provider") or ""),
        "capabilities": native_agent_capabilities(ready),
    }


def native_agent_not_ready(reason: str, message: str) -> dict[str, Any]:
    return {
        "ready": False,
        "code": "native_agent_not_ready",
        "reason": reason,
        "message": message,
        "capabilities": native_agent_capabilities(False),
    }


def native_agent_capabilities(model_ready: bool) -> dict[str, bool]:
    return {
        "model": bool(model_ready),
        "image_input": bool(model_ready),
        "tools": False,
        "approval": False,
    }


class RuntimeRunReadinessValidator:
    """Validates Agent and Workflow runnable dependencies before execution."""

    def __init__(
        self,
        *,
        node_kind: Callable[[dict[str, Any]], str],
        get_agent_private: Callable[[str], dict[str, Any]],
        get_workflow: Callable[[str], dict[str, Any]],
        load_agent_skills: Callable[[list[str]], list[dict[str, Any]]],
        agent_model_config_private: Callable[[dict[str, Any]], dict[str, Any]],
        default_agent_ids: set[str],
    ) -> None:
        self._node_kind = node_kind
        self._get_agent_private = get_agent_private
        self._get_workflow = get_workflow
        self._load_agent_skills = load_agent_skills
        self._agent_model_config_private = agent_model_config_private
        self._default_agent_ids = set(default_agent_ids)

    def workflow_agent_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") or {}
        label = str(data.get("label") or node.get("id") or "Agent").strip() or "Agent"
        agent_id = str(data.get("agent_id") or data.get("agentId") or "").strip()
        if not agent_id:
            raise AgentRuntimeError(f"Agent 节点 {label} 没有选择 Agent")
        try:
            agent = self._get_agent_private(agent_id)
        except KeyError as exc:
            raise AgentRuntimeError(f"Agent 节点 {label} 引用了不存在的 Agent") from exc
        if not agent.get("enabled", True):
            raise AgentRuntimeError(f"Agent 节点 {label} 选择的 Agent 已停用")
        tool_policy = data.get("tool_policy")
        if isinstance(tool_policy, dict):
            return {**agent, "tool_policy": dict(tool_policy)}
        return agent

    @staticmethod
    def workflow_id_for_node(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.workflow_id(node)

    def workflow_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") or {}
        label = str(data.get("label") or node.get("id") or "Workflow").strip() or "Workflow"
        workflow_id = self.workflow_id_for_node(node)
        if not workflow_id:
            raise AgentRuntimeError(f"Workflow 节点 {label} 没有选择子 Workflow")
        try:
            workflow = self._get_workflow(workflow_id)
        except KeyError as exc:
            raise AgentRuntimeError(f"Workflow 节点 {label} 引用了不存在的子 Workflow") from exc
        if not workflow.get("enabled", True):
            raise AgentRuntimeError(f"Workflow 节点 {label} 选择的子 Workflow 已停用")
        return workflow

    def validate_workflow_agent_nodes(self, nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if self._node_kind(node) == "agent":
                self.workflow_agent_for_node(node)

    def validate_workflow_subworkflow_nodes(
        self,
        nodes: list[dict[str, Any]],
        *,
        parent_workflow_id: str = "",
    ) -> None:
        for node in nodes:
            if self._node_kind(node) != "workflow":
                continue
            data = node.get("data") or {}
            label = str(data.get("label") or node.get("id") or "Workflow").strip() or "Workflow"
            workflow_id = self.workflow_id_for_node(node)
            if not workflow_id:
                raise AgentRuntimeError(f"Workflow 节点 {label} 没有选择子 Workflow")
            if parent_workflow_id and workflow_id == parent_workflow_id:
                raise AgentRuntimeError(f"Workflow 节点 {label} 不能引用当前 Workflow")
            self.workflow_for_node(node)

    def validate_agent_run_readiness(
        self,
        agent: dict[str, Any],
        *,
        label: str = "Agent",
        require_model_config: bool = False,
    ) -> None:
        display = str(label or agent.get("name") or "Agent").strip() or "Agent"
        if not agent.get("enabled", True):
            raise AgentRuntimeError(f"{display} 已停用")
        self._load_agent_skills(agent.get("skill_ids") or [])
        model_mode = str(agent.get("model_mode") or "profile")
        model_config = agent.get("model_config") or {}
        if model_mode == "custom_api":
            missing = [
                label
                for key, label in (
                    ("base_url", "Base URL"),
                    ("model", "Model"),
                    ("api_key", "API Key"),
                )
                if not str(model_config.get(key) or "").strip()
            ]
            if missing:
                raise AgentRuntimeError(f"{display} Custom API 配置不完整：缺少 {', '.join(missing)}")
        elif (
            require_model_config
            and model_mode != "follow_main"
            and str(agent.get("agent_id") or "") not in self._default_agent_ids
        ):
            if not str(agent.get("model_profile_id") or "").strip():
                raise AgentRuntimeError(f"{display} 缺少可运行的 Chat Profile")
        if require_model_config:
            try:
                self._agent_model_config_private(agent)
            except AgentRuntimeError as exc:
                raise AgentRuntimeError(f"{display} 无法运行：{exc}") from exc

    def validate_workflow_agent_run_readiness(self, nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if self._node_kind(node) != "agent":
                continue
            data = node.get("data") or {}
            label = str(data.get("label") or node.get("id") or "Agent").strip() or "Agent"
            agent = self.workflow_agent_for_node(node)
            self.validate_agent_run_readiness(
                agent,
                label=f"Agent 节点 {label}",
                require_model_config=True,
            )

    def validate_workflow_runnable_steps(self, nodes: list[dict[str, Any]]) -> None:
        if not any(self._node_kind(node) != "start" for node in nodes):
            raise AgentRuntimeError(
                "Workflow 至少需要一个可执行节点（Agent、Approval、Artifact、Condition、Parallel、Workflow 或 Loop）"
            )
