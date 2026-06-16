"""Legacy-compatible model dependency providers for split runtime services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.config import DEFAULT_AGENT_IDS
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver


def _legacy_agent_runtime_module() -> Any:
    from apps.shell import agent_runtime

    return agent_runtime


@dataclass(frozen=True)
class RuntimeModelCompatibilityProvider:
    """Centralizes legacy model monkeypatch points behind explicit providers."""

    module_loader: Callable[[], Any] = _legacy_agent_runtime_module

    def _module(self) -> Any:
        return self.module_loader()

    def chat_message(self) -> Callable[..., Any]:
        return self._module().openai_compatible_chat_message

    def chat_timeout(self) -> float:
        return self._module().read_openai_compatible_chat_timeout()

    def urlopen(self, *args: Any, **kwargs: Any) -> Any:
        return self._module().urlopen_with_bundled_ca(*args, **kwargs)

    def redact_error(self, value: Any) -> str:
        return self._module().redact_secrets(value)

    def profile_service(self) -> Any:
        return self._module().get_model_profile_service()

    def supports_openai_compatible_api(self, provider: str) -> bool:
        return bool(self._module().supports_openai_compatible_api(provider))

    def workspace_status(self) -> dict[str, Any]:
        return dict(self._module().get_workspace_status())

    def default_profile_id(self, capability: str) -> str:
        return str(self.profile_service().get_defaults().get(capability) or "").strip()

    def chat_default_profile_id(self) -> str:
        return self.default_profile_id("chat")

    def chat_profile_model_config_private(self, profile_id: str) -> dict[str, Any]:
        return self._module().NativeRunEngine._model_profile_config_private(
            profile_id,
            capability="chat",
        )

    def openai_compatible_chat(
        self,
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
    ) -> str:
        return self._module()._legacy_openai_compatible_chat_adapter.call(
            base_url,
            model,
            api_key,
            messages,
        )

    def model_profile_resolver(self) -> RuntimeModelProfileResolver:
        return RuntimeModelProfileResolver(
            profile_service_factory=self.profile_service,
            supports_openai_compatible_api=self.supports_openai_compatible_api,
            default_agent_ids=DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        )


def runtime_model_compat_provider() -> RuntimeModelCompatibilityProvider:
    return RuntimeModelCompatibilityProvider()
