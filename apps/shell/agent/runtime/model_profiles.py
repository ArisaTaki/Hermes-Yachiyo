"""Runtime model profile resolution helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class RuntimeModelProfileResolver:
    """Resolves Agent model configuration without owning execution state."""

    def __init__(
        self,
        *,
        profile_service_factory: Callable[[], Any],
        supports_openai_compatible_api: Callable[[str], bool],
        default_agent_ids: set[str] | frozenset[str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._profile_service_factory = profile_service_factory
        self._supports_openai_compatible_api = supports_openai_compatible_api
        self._default_agent_ids = set(default_agent_ids)
        self._error_type = error_type

    def model_profile_config_private(
        self,
        profile_id: str,
        *,
        capability: str,
    ) -> dict[str, Any]:
        try:
            profile = self._profile_service_factory().get_profile_private(profile_id)
        except KeyError as exc:
            raise self._error_type("Agent 引用的模型 Profile 不存在") from exc
        if not profile.get("enabled", True):
            raise self._error_type("Agent 引用的模型 Profile 已停用")
        if str(profile.get("status") or "") != "available":
            raise self._error_type("Agent 引用的模型 Profile 尚未通过连接测试")
        if not self._supports_openai_compatible_api(
            str(profile.get("provider") or "openai_compatible")
        ):
            raise self._error_type("Agent Runtime 首版仅支持 OpenAI-compatible 模型 Profile")
        if str(profile.get("capability") or "chat") != capability:
            raise self._error_type(f"Agent 推理需要 {capability} 模型 Profile")
        return {
            "provider": profile.get("provider") or "openai_compatible",
            "base_url": profile.get("base_url") or "",
            "model": profile.get("model") or "",
            "api_key": profile.get("api_key") or "",
        }

    def chat_profile_model_config_private(self, profile_id: str) -> dict[str, Any]:
        return self.model_profile_config_private(profile_id, capability="chat")

    def agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(agent.get("model_profile_id") or "").strip()
        if profile_id:
            return self.chat_profile_model_config_private(profile_id)
        model_mode = str(agent.get("model_mode") or "profile")
        agent_id = str(agent.get("agent_id") or "")
        if model_mode == "follow_main" or agent_id in self._default_agent_ids:
            default_profile_id = str(
                self._profile_service_factory().get_defaults().get("chat") or ""
            ).strip()
            if default_profile_id:
                return self.chat_profile_model_config_private(default_profile_id)
        model_config = agent.get("model_config") or {}
        if any(
            str(model_config.get(key) or "").strip()
            for key in ("base_url", "model", "api_key")
        ):
            return model_config
        raise self._error_type(
            "Agent 缺少可运行的 Chat Profile；请在 Agent Studio 为该岗位选择已测试的文本模型。"
        )
