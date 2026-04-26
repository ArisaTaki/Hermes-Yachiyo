"""TTSService 测试。"""

from __future__ import annotations

import json

from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.config import AppConfig
from apps.shell.modes.live2d import Live2DWindowAPI
import apps.shell.tts as tts_mod
from apps.shell.config import TTSConfig
from apps.shell.tts import TTSService
from packages.protocol.enums import TaskStatus


class _ImmediateThread:
    def __init__(self, target, args=(), **_kwargs) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)


class _FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b"ok"


class _Live2DRuntimeStub:
    def __init__(self, store: ChatStore) -> None:
        self.state = AppState()
        self.chat_session = ChatSession(session_id="tts-live2d-test")
        self.chat_session.attach_store(store, load_existing=False)
        self.task_runner = None

    def is_hermes_ready(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"hermes": {"limited_tools": []}}


class _RecordingTTS:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def speak_async(self, text: str) -> dict:
        self.calls.append(text)
        return {"ok": True, "scheduled": True, "message": "scheduled"}

    def get_status(self) -> dict:
        return {"ok": True, "scheduled": False}


def test_tts_disabled_skips_without_side_effect(monkeypatch):
    started = []

    class _ThreadShouldNotStart:
        def __init__(self, *_args, **_kwargs) -> None:
            started.append(True)

        def start(self) -> None:
            started.append(True)

    monkeypatch.setattr(tts_mod.threading, "Thread", _ThreadShouldNotStart)
    service = TTSService(TTSConfig(enabled=False, provider="command", command="say"))

    result = service.speak_async("你好")

    assert result["skipped"] is True
    assert result["ok"] is False
    assert "未启用" in result["message"]
    assert started == []


def test_tts_missing_http_config_is_reported_without_call(monkeypatch):
    called = []
    monkeypatch.setattr(tts_mod, "urlopen", lambda *_args, **_kwargs: called.append(True))
    service = TTSService(TTSConfig(enabled=True, provider="http", endpoint=""))

    result = service.speak_async("你好")

    assert result["skipped"] is True
    assert result["ok"] is False
    assert "endpoint" in result["message"]
    assert called == []


def test_tts_missing_command_config_is_reported_without_call(monkeypatch):
    called = []
    monkeypatch.setattr(tts_mod.subprocess, "run", lambda *_args, **_kwargs: called.append(True))
    service = TTSService(TTSConfig(enabled=True, provider="command", command=""))

    result = service.speak_async("你好")

    assert result["skipped"] is True
    assert result["ok"] is False
    assert "命令" in result["message"]
    assert called == []


def test_tts_command_invocation_uses_text_voice_and_timeout(monkeypatch):
    calls = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Result()

    monkeypatch.setattr(tts_mod.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(tts_mod.subprocess, "run", fake_run)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="command",
            command="say --voice {voice} {text}",
            voice="Kyoko",
            timeout_seconds=7,
        )
    )

    result = service.speak_async("你好")

    assert result["ok"] is True
    assert result["message"] == "TTS 已完成"
    assert calls[0][0] == ["say", "--voice", "Kyoko", "你好"]
    assert calls[0][1]["timeout"] == 7
    assert calls[0][1]["env"]["HERMES_YACHIYO_TTS_TEXT"] == "你好"
    assert calls[0][1]["env"]["HERMES_YACHIYO_TTS_VOICE"] == "Kyoko"


def test_tts_http_posts_text_voice_and_timeout(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return _FakeHTTPResponse()

    monkeypatch.setattr(tts_mod.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="http",
            endpoint="http://127.0.0.1:9000/tts",
            voice="Kyoko",
            timeout_seconds=9,
        )
    )

    result = service.speak_async("你好")
    request, timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))

    assert result["ok"] is True
    assert result["message"] == "TTS 已完成"
    assert request.full_url == "http://127.0.0.1:9000/tts"
    assert request.get_method() == "POST"
    assert payload == {"text": "你好", "voice": "Kyoko"}
    assert timeout == 9


def test_live2d_tts_uses_full_latest_reply(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _Live2DRuntimeStub(store)
    config = AppConfig(display_mode="live2d")
    config.tts.enabled = True
    config.tts.provider = "command"
    config.tts.command = "say {text}"
    api = Live2DWindowAPI(runtime, config)
    recorder = _RecordingTTS()
    api._tts = recorder  # type: ignore[assignment]
    try:
        long_reply = "完整语音回复" + "A" * 200
        result = api.send_quick_message("请回答很长一段")
        runtime.state.update_task_status(result["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(result["task_id"], TaskStatus.COMPLETED, result=long_reply)

        view = api.get_live2d_view()

        assert view["chat"]["latest_reply"] != long_reply
        assert view["chat"]["latest_reply_full"] == long_reply
        assert recorder.calls == [long_reply]
    finally:
        store.close()
