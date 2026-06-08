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
    runtime.config.assistant.agent_name = "月見八千代"
    runtime.config.assistant.agent_nickname = "月夜"
    runtime.config.assistant.persona_prompt = "你是八千代。"
    runtime.config.assistant.user_address = "老师"
    runtime.config.assistant.user_name = "测试用户"
    runtime.config.assistant.user_profile = "喜欢简洁说明"
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)

    result = assistant_route.get_assistant_profile()

    assert result.ok is True
    assert result.agent_name == "月見八千代"
    assert result.agent_nickname == "月夜"
    assert result.agent_avatar_url.startswith("data:image/")
    assert result.persona_prompt == "你是八千代。"
    assert result.user_address == "老师"
    assert result.user_name == "测试用户"
    assert result.user_profile == "喜欢简洁说明"
    assert result.memory_enabled is True
    assert result.memory_scope == "local_chat_history"
    assert result.prompt_order == [
        "agent_profile",
        "persona",
        "user_address",
        "user_profile",
        "relevant_memory",
        "current_session",
        "request",
    ]


def test_patch_assistant_profile_updates_config_and_saves(monkeypatch):
    runtime = _RuntimeStub()
    saved: list[AppConfig] = []
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)
    monkeypatch.setattr("apps.shell.config.save_config", lambda config: saved.append(config))

    result = assistant_route.patch_assistant_profile(
        AssistantProfilePatchRequest(
            agent_name="八千代",
            agent_nickname="月夜",
            persona_prompt="共享人设",
            user_address="老师",
            user_name="用户",
            user_profile="基本信息",
            user_preferences="偏好",
        )
    )

    assert result.ok is True
    assert result.agent_name == "八千代"
    assert result.agent_nickname == "月夜"
    assert result.persona_prompt == "共享人设"
    assert result.user_address == "老师"
    assert result.user_name == "用户"
    assert result.user_profile == "基本信息"
    assert result.user_preferences == "偏好"
    assert runtime.config.assistant.agent_name == "八千代"
    assert runtime.config.assistant.agent_nickname == "月夜"
    assert runtime.config.assistant.persona_prompt == "共享人设"
    assert runtime.config.assistant.user_address == "老师"
    assert runtime.config.assistant.user_name == "用户"
    assert runtime.config.assistant.user_profile == "基本信息"
    assert runtime.config.assistant.user_preferences == "偏好"
    assert saved == [runtime.config]


def test_import_assistant_avatar_from_data_url(tmp_path, monkeypatch):
    runtime = _RuntimeStub()
    saved: list[AppConfig] = []
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)
    monkeypatch.setattr(assistant_route, "get_user_avatar_assets_dir", lambda: tmp_path / "avatars")
    monkeypatch.setattr("apps.shell.config.save_config", lambda config: saved.append(config))

    result = assistant_route.import_assistant_avatar(
        assistant_route.AssistantAvatarImportRequest(
            target="user",
            file_name="me.png",
            data_url="data:image/png;base64,iVBORw0KGgo=",
        )
    )

    assert result.ok is True
    assert result.user_avatar_path.endswith(".png")
    assert result.user_avatar_url.startswith("data:image/png;base64,")
    assert (tmp_path / "avatars").exists()
    assert runtime.config.assistant.user_avatar_path == result.user_avatar_path
    assert saved == [runtime.config]


def test_import_assistant_avatar_from_local_path(tmp_path, monkeypatch):
    runtime = _RuntimeStub()
    saved: list[AppConfig] = []
    source = tmp_path / "agent.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)
    monkeypatch.setattr(assistant_route, "get_user_avatar_assets_dir", lambda: tmp_path / "avatars")
    monkeypatch.setattr("apps.shell.config.save_config", lambda config: saved.append(config))

    result = assistant_route.import_assistant_avatar(
        assistant_route.AssistantAvatarImportRequest(
            target="agent",
            path=str(source),
        )
    )

    assert result.ok is True
    assert result.agent_avatar_path.endswith(".png")
    assert result.agent_avatar_url.startswith("data:image/png;base64,")
    assert runtime.config.assistant.agent_avatar_path == result.agent_avatar_path
    assert saved == [runtime.config]
