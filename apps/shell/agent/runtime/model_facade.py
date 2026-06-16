"""Model profile compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.model_compat import runtime_model_compat_provider
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver


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
        return runtime_model_compat_provider().chat_profile_model_config_private(profile_id)

    def _agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.model_profile_resolver.agent_model_config_private(agent)

    @staticmethod
    def _openai_compatible_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
    ) -> str:
        return runtime_model_compat_provider().openai_compatible_chat(
            base_url,
            model,
            api_key,
            messages,
        )

    @staticmethod
    def _model_profile_resolver() -> RuntimeModelProfileResolver:
        return runtime_model_compat_provider().model_profile_resolver()
