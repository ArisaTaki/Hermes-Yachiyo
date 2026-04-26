"""Bridge /assistant/profile 路由测试。"""

from __future__ import annotations

from apps.bridge.routes import assistant as assistant_route
from apps.shell.config import AppConfig
from packages.protocol.schemas import AssistantProfilePatchRequest


class _RuntimeStub:
    def __init__(self) -> None:
        self.config = AppConfig()


def test_get_assistant_profile_returns_shared_persona(monkeypatch):
    runtime = _RuntimeStub()
    runtime.config.assistant.persona_prompt = "你是八千代。"
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)

    result = assistant_route.get_assistant_profile()

    assert result.ok is True
    assert result.persona_prompt == "你是八千代。"
    assert result.memory_enabled is False
    assert result.memory_scope == "local_only"
    assert result.prompt_order == ["persona", "relevant_memory", "current_session", "request"]


def test_patch_assistant_profile_updates_config_and_saves(monkeypatch):
    runtime = _RuntimeStub()
    saved: list[AppConfig] = []
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)
    monkeypatch.setattr("apps.shell.config.save_config", lambda config: saved.append(config))

    result = assistant_route.patch_assistant_profile(
        AssistantProfilePatchRequest(persona_prompt="共享人设")
    )

    assert result.ok is True
    assert result.persona_prompt == "共享人设"
    assert runtime.config.assistant.persona_prompt == "共享人设"
    assert saved == [runtime.config]
