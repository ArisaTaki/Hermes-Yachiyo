"""External integration smoke script tests."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import pytest

from scripts import smoke_external_integrations as smoke


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object]]] = []

    def get(self, path: str) -> _FakeResponse:
        if path == "/status":
            return _FakeResponse(
                {
                    "service": "oha-yachiyo",
                    "version": "0.4.0",
                    "native_agent_ready": True,
                }
            )
        if path == "/ui/settings":
            return _FakeResponse({"display": {"current_mode": "live2d"}})
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, json: dict[str, object]) -> _FakeResponse:
        self.posts.append((path, json))
        if path == "/ui/live2d/archive/import":
            return _FakeResponse(
                {
                    "ok": True,
                    "imported_path": "/tmp/live2d/yachiyo",
                    "draft_changes": {
                        "live2d_mode.model_path": "/tmp/live2d/yachiyo",
                    },
                }
            )
        if path == "/ui/tts/voice-resource/import":
            return _FakeResponse(
                {
                    "ok": True,
                    "imported_path": "/tmp/tts/yachiyo",
                    "draft_changes": {
                        "tts.enabled": True,
                        "tts.provider": "gpt-sovits",
                        "tts.gsv_base_url": "http://127.0.0.1:9880",
                    },
                }
            )
        if path == "/ui/settings":
            return _FakeResponse({"ok": True})
        if path == "/ui/tts/test":
            return _FakeResponse(
                {
                    "ok": True,
                    "success": True,
                    "provider": "gpt-sovits",
                    "spoken_text": json["text"],
                }
            )
        raise AssertionError(f"unexpected POST {path}")


class _LegacyBridgeClient(_FakeClient):
    def get(self, path: str) -> _FakeResponse:
        if path == "/status":
            return _FakeResponse(
                {
                    "service": "hermes-yachiyo",
                    "version": "0.1.0",
                    "hermes_ready": True,
                }
            )
        return super().get(path)


def _zip_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("placeholder.txt", "ok")
    return path


def test_live2d_and_tts_external_checks_use_bridge_routes(tmp_path):
    client = _FakeClient()
    live2d = _zip_file(tmp_path / "yachiyo-live2d.zip")
    voice = _zip_file(tmp_path / "yachiyo-voice.zip")

    live2d_evidence = smoke.run_live2d_resource_check(client, archive_path=live2d)
    tts_evidence = smoke.run_gpt_sovits_tts_check(
        client,
        archive_path=voice,
        base_url="http://127.0.0.1:9881",
        text="外部验收",
    )

    assert live2d_evidence["display_mode_saved"] is True
    assert tts_evidence["tts_test_success"] is True
    assert tts_evidence["base_url"] == "http://127.0.0.1:9881"
    assert (
        "/ui/settings",
        {"changes": {"live2d_mode.model_path": "/tmp/live2d/yachiyo", "display_mode": "live2d"}},
    ) in client.posts
    assert any(
        path == "/ui/settings"
        and isinstance(body.get("changes"), dict)
        and body["changes"].get("tts.provider") == "gpt-sovits"
        and body["changes"].get("tts.gsv_base_url") == "http://127.0.0.1:9881"
        for path, body in client.posts
    )
    assert ("/ui/tts/test", {"text": "外部验收"}) in client.posts


def test_external_smoke_requires_at_least_one_selected_check():
    args = argparse.Namespace(
        live2d_archive=None,
        tts_voice_archive=None,
        astrbot=False,
    )

    with pytest.raises(smoke.SmokeError, match="select at least one check"):
        smoke.run_smoke(args)


def test_external_smoke_bridge_only_checks_oha_identity(monkeypatch):
    client = _FakeClient()

    class ClientFactory:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return client

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(smoke.httpx, "Client", ClientFactory)

    report = smoke.run_smoke(
        argparse.Namespace(
            bridge_url="http://127.0.0.1:18420",
            timeout=1.0,
            bridge_only=True,
            live2d_archive=None,
            tts_voice_archive=None,
            gpt_sovits_base_url="",
            tts_text="外部验收",
            skip_tts_test=False,
            astrbot=False,
            astrbot_sender="external-smoke",
            astrbot_skip_screen=False,
            astrbot_skip_window=False,
        )
    )

    assert report == {
        "ok": True,
        "complete": False,
        "mode": "bridge_only",
        "bridge_url": "http://127.0.0.1:18420",
        "required_check_ids": [
            "live2d_resource",
            "gpt_sovits_tts",
            "astrbot_plugin_bridge",
        ],
        "selected_required_check_ids": [],
        "missing_required_check_ids": [
            "live2d_resource",
            "gpt_sovits_tts",
            "astrbot_plugin_bridge",
        ],
        "resource_inputs": {
            "live2d_archive": {"provided": False},
            "tts_voice_archive": {"provided": False},
            "gpt_sovits_base_url_configured": False,
            "tts_test_skipped": False,
            "astrbot_enabled": False,
            "astrbot_screen_enabled": False,
            "astrbot_window_enabled": False,
            "astrbot_task_mode": "auto",
            "bridge_token_configured": False,
        },
        "readiness": {
            "status": "bridge_only",
            "signoff_ready": False,
            "passed_check_ids": ["bridge_status"],
            "failed_check_ids": [],
            "passed_required_check_ids": [],
            "failed_required_check_ids": [],
            "missing_required_check_ids": [
                "live2d_resource",
                "gpt_sovits_tts",
                "astrbot_plugin_bridge",
            ],
            "completion_blockers": ["missing_required_checks"],
            "next_actions": [
                smoke.REQUIRED_CHECK_NEXT_ACTIONS["live2d_resource"],
                smoke.REQUIRED_CHECK_NEXT_ACTIONS["gpt_sovits_tts"],
                smoke.REQUIRED_CHECK_NEXT_ACTIONS["astrbot_plugin_bridge"],
            ],
            "recommended_full_command": smoke.FULL_EXTERNAL_SMOKE_COMMAND,
        },
        "checks": [
            {
                "id": "bridge_status",
                "status": "passed",
                "evidence": {
                    "service": "oha-yachiyo",
                    "version": "0.4.0",
                    "native_agent_ready": True,
                },
            }
        ],
    }
    assert client.posts == []


def test_external_smoke_rejects_legacy_hermes_bridge(monkeypatch, tmp_path):
    client = _LegacyBridgeClient()

    class ClientFactory:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return client

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(smoke.httpx, "Client", ClientFactory)

    report = smoke.run_smoke(
        argparse.Namespace(
            bridge_url="http://127.0.0.1:18420",
            timeout=1.0,
            bridge_only=False,
            live2d_archive=_zip_file(tmp_path / "yachiyo-live2d.zip"),
            tts_voice_archive=None,
            gpt_sovits_base_url="",
            tts_text="外部验收",
            skip_tts_test=False,
            astrbot=False,
            astrbot_sender="external-smoke",
            astrbot_skip_screen=False,
            astrbot_skip_window=False,
        )
    )

    assert report["ok"] is False
    assert report["complete"] is False
    assert report["mode"] == "external_integrations"
    assert report["selected_required_check_ids"] == ["live2d_resource"]
    assert report["missing_required_check_ids"] == [
        "gpt_sovits_tts",
        "astrbot_plugin_bridge",
    ]
    assert report["checks"] == [
        {
            "id": "bridge_status",
            "status": "failed",
            "error": "/status returned service=hermes-yachiyo; expected oha-yachiyo",
        }
    ]
    assert client.posts == []


def test_external_smoke_reports_selected_and_missing_required_checks(monkeypatch, tmp_path):
    client = _FakeClient()
    live2d = _zip_file(tmp_path / "yachiyo-live2d.zip")

    class ClientFactory:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return client

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(smoke.httpx, "Client", ClientFactory)

    report = smoke.run_smoke(
        argparse.Namespace(
            bridge_url="http://127.0.0.1:18420",
            timeout=1.0,
            bridge_only=False,
            live2d_archive=live2d,
            tts_voice_archive=None,
            gpt_sovits_base_url="",
            tts_text="外部验收",
            skip_tts_test=False,
            astrbot=False,
            astrbot_sender="external-smoke",
            astrbot_skip_screen=False,
            astrbot_skip_window=False,
        )
    )

    assert report["ok"] is True
    assert report["complete"] is False
    assert report["required_check_ids"] == [
        "live2d_resource",
        "gpt_sovits_tts",
        "astrbot_plugin_bridge",
    ]
    assert report["selected_required_check_ids"] == ["live2d_resource"]
    assert report["missing_required_check_ids"] == [
        "gpt_sovits_tts",
        "astrbot_plugin_bridge",
    ]
    assert report["resource_inputs"]["live2d_archive"] == {
        "provided": True,
        "path": str(live2d),
        "exists": True,
    }
    assert report["resource_inputs"]["tts_voice_archive"] == {"provided": False}
    assert report["resource_inputs"]["astrbot_task_mode"] == "auto"
    assert report["resource_inputs"]["bridge_token_configured"] is False
    assert report["readiness"]["status"] == "partial"
    assert report["readiness"]["signoff_ready"] is False
    assert report["readiness"]["passed_required_check_ids"] == ["live2d_resource"]
    assert report["readiness"]["missing_required_check_ids"] == [
        "gpt_sovits_tts",
        "astrbot_plugin_bridge",
    ]
    assert report["readiness"]["completion_blockers"] == ["missing_required_checks"]
    assert report["readiness"]["next_actions"] == [
        smoke.REQUIRED_CHECK_NEXT_ACTIONS["gpt_sovits_tts"],
        smoke.REQUIRED_CHECK_NEXT_ACTIONS["astrbot_plugin_bridge"],
    ]
    assert [check["id"] for check in report["checks"]] == [
        "bridge_status",
        "live2d_resource",
    ]


def test_external_smoke_requires_real_tts_test_for_complete_signoff(
    monkeypatch,
    tmp_path,
):
    client = _FakeClient()
    live2d = _zip_file(tmp_path / "yachiyo-live2d.zip")
    voice = _zip_file(tmp_path / "yachiyo-voice.zip")

    class ClientFactory:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return client

        def __exit__(self, *_args):
            return False

    async def fake_astrbot(**_kwargs):
        return {
            "bridge_url": "http://127.0.0.1:18420",
            "native_agent_ready": True,
            "task_command_mode": "full",
            "commands": ["status", "do", "tasks", "check", "ask", "screen", "window", "cancel"],
            "response_lengths": {},
        }

    monkeypatch.setattr(smoke.httpx, "Client", ClientFactory)
    monkeypatch.setattr(smoke, "run_astrbot_plugin_bridge_check", fake_astrbot)

    report = smoke.run_smoke(
        argparse.Namespace(
            bridge_url="http://127.0.0.1:18420",
            timeout=1.0,
            bridge_only=False,
            live2d_archive=live2d,
            tts_voice_archive=voice,
            gpt_sovits_base_url="http://127.0.0.1:9880",
            tts_text="外部验收",
            skip_tts_test=True,
            astrbot=True,
            astrbot_sender="external-smoke",
            astrbot_skip_screen=False,
            astrbot_skip_window=False,
            astrbot_task_mode="require",
        )
    )

    assert report["ok"] is True
    assert report["complete"] is False
    assert report["selected_required_check_ids"] == [
        "live2d_resource",
        "gpt_sovits_tts",
        "astrbot_plugin_bridge",
    ]
    assert report["missing_required_check_ids"] == []
    assert report["readiness"]["status"] == "partial"
    assert report["readiness"]["signoff_ready"] is False
    assert report["readiness"]["passed_required_check_ids"] == [
        "live2d_resource",
        "gpt_sovits_tts",
        "astrbot_plugin_bridge",
    ]
    assert report["readiness"]["completion_blockers"] == [
        "gpt_sovits_tts_test_skipped"
    ]
    assert "Rerun without --skip-tts-test" in report["readiness"]["next_actions"][0]
    assert any(
        check["id"] == "gpt_sovits_tts"
        and check["evidence"]["tts_test_skipped"] is True
        for check in report["checks"]
    )


def test_external_smoke_sends_bridge_token_without_archiving_secret(monkeypatch):
    client = _FakeClient()
    factories: list[object] = []

    class ClientFactory:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs
            factories.append(self)

        def __enter__(self):
            return client

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(smoke.httpx, "Client", ClientFactory)

    report = smoke.run_smoke(
        argparse.Namespace(
            bridge_url="http://127.0.0.1:18420",
            bridge_token="secret-token-123",
            timeout=1.0,
            bridge_only=True,
            live2d_archive=None,
            tts_voice_archive=None,
            gpt_sovits_base_url="",
            tts_text="外部验收",
            skip_tts_test=False,
            astrbot=False,
            astrbot_sender="external-smoke",
            astrbot_skip_screen=False,
            astrbot_skip_window=False,
        )
    )

    assert factories
    assert factories[0].kwargs["headers"] == {
        "X-Oha-Yachiyo-Bridge-Token": "secret-token-123"
    }
    assert report["resource_inputs"]["bridge_token_configured"] is True
    assert "secret-token-123" not in json.dumps(report, ensure_ascii=False)


@pytest.mark.asyncio
async def test_astrbot_plugin_bridge_check(monkeypatch):
    async def fake_on_y_command(text: str, sender_id: str = "", config=None) -> str:
        if text == "/y status":
            return "📊 Oha-Yachiyo 状态\nNative Agent: ✅ 已就绪"
        if text.startswith("/y do "):
            return "✅ 任务已提交\nID: abcdef123456\n状态: ⏳ 等待中"
        if text == "/y tasks":
            return "📋 任务列表\n[abcdef12] 外部 AstrBot 集成验收任务"
        if text.startswith("/y check "):
            return "🔍 任务详情\nID: abcdef123456"
        if text.startswith("/y ask "):
            return "💬 Yachiyo\n动作: create_low_risk_task"
        if text == "/y screen":
            return "📸 截图已获取\n分辨率: 2×1"
        if text == "/y window":
            return "🪟 当前活动窗口\n应用: Codex"
        if text.startswith("/y cancel "):
            return "🚫 任务已取消\nID: abcdef123456"
        raise AssertionError(text)

    monkeypatch.setattr(
        "integrations.astrbot_plugin.main.on_y_command",
        fake_on_y_command,
    )

    evidence = await smoke.run_astrbot_plugin_bridge_check(
        bridge_url="http://127.0.0.1:18420",
        sender_id="qq-smoke",
    )

    assert evidence["task_id"] == "abcdef123456"
    assert evidence["sender_id"] == "qq-smoke"
    assert evidence["native_agent_ready"] is True
    assert evidence["task_command_mode"] == "full"
    assert evidence["commands"] == [
        "ask",
        "cancel",
        "check",
        "do",
        "screen",
        "status",
        "tasks",
        "window",
    ]


@pytest.mark.asyncio
async def test_astrbot_plugin_bridge_check_auto_skips_task_commands_when_native_agent_not_ready(
    monkeypatch,
):
    seen: list[str] = []

    async def fake_on_y_command(text: str, sender_id: str = "", config=None) -> str:
        seen.append(text)
        if text == "/y status":
            return "📊 Oha-Yachiyo 状态\nNative Agent: ⚠️ 未就绪"
        if text == "/y tasks":
            return "📋 当前没有任务"
        if text == "/y ask 状态":
            return "💬 Yachiyo\n动作: status\n请在桌面应用中完成 Native Agent 模型配置"
        raise AssertionError(text)

    monkeypatch.setattr(
        "integrations.astrbot_plugin.main.on_y_command",
        fake_on_y_command,
    )

    evidence = await smoke.run_astrbot_plugin_bridge_check(
        bridge_url="http://127.0.0.1:18420",
        sender_id="qq-smoke",
        include_screen=False,
        include_window=False,
    )

    assert evidence["native_agent_ready"] is False
    assert evidence["task_command_mode"] == "skipped_native_agent_not_ready"
    assert evidence["skipped_task_commands"] == [
        "do",
        "check",
        "cancel",
        "ask_create_low_risk_task",
    ]
    assert evidence["commands"] == ["ask", "status", "tasks"]
    assert not any(command.startswith("/y do ") for command in seen)
