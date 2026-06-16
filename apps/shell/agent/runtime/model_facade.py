"""Model profile compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.config import DEFAULT_AGENT_IDS as _DEFAULT_AGENT_IDS
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver


def _legacy_agent_runtime_module() -> Any:
    from apps.shell import agent_runtime

    return agent_runtime


class RuntimeModelFacadeMixin:
    """Keeps legacy model helper methods while delegating to split services."""

    @staticmethod
    def _validate_available_profile(profile_id: str, capability: str) -> dict[str, Any]:
        return RuntimeModelFacadeMixin._model_profile_resolver().validate_available_profile(
            profile_id,
            capability,
        )

    @staticmethod
    def _model_profile_config_private(profile_id: str, *, capability: str) -> dict[str, Any]:
        return RuntimeModelFacadeMixin._model_profile_resolver().model_profile_config_private(
            profile_id,
            capability=capability,
        )

    @staticmethod
    def _chat_profile_model_config_private(profile_id: str) -> dict[str, Any]:
        return _legacy_agent_runtime_module().NativeRunEngine._model_profile_config_private(
            profile_id,
            capability="chat",
        )

    def _agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.model_profile_resolver.agent_model_config_private(agent)

    @staticmethod
    def _openai_compatible_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
    ) -> str:
        return _legacy_agent_runtime_module()._legacy_openai_compatible_chat_adapter.call(
            base_url,
            model,
            api_key,
            messages,
        )

    @staticmethod
    def _model_profile_resolver() -> RuntimeModelProfileResolver:
        legacy = _legacy_agent_runtime_module()
        return RuntimeModelProfileResolver(
            profile_service_factory=lambda: legacy.get_model_profile_service(),
            supports_openai_compatible_api=legacy.supports_openai_compatible_api,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        )
