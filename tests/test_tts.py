"""TTSService 测试。"""

from __future__ import annotations

import json

import apps.shell.tts as tts_mod
from apps.shell.config import TTSConfig
from apps.shell.tts import TTSService, prepare_tts_text


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


class _FakeAudioResponse(_FakeHTTPResponse):
    def __init__(self, body: bytes = b"RIFFaudio", content_type: str = "audio/wav") -> None:
        self._body = body
        self._content_type = content_type

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str = "") -> str:
        return self._content_type if name.lower() == "content-type" else default


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


def test_tts_command_invocation_uses_shortened_notification_text(monkeypatch):
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
            command="say {text}",
            max_chars=24,
        )
    )

    result = service.speak_async("这是第一句提醒。后面是很长很长的分析内容，不应该全部朗读。")

    assert result["ok"] is True
    assert calls[0][0] == ["say", "这是第一句提醒。"]
    assert result["spoken_text"] == "这是第一句提醒。"


def test_prepare_tts_text_strips_code_and_limits_length():
    text = "```python\nprint('hello')\n```\n请看这个链接：https://example.com/path 后面还有很多内容需要截断"

    prepared = prepare_tts_text(text, max_chars=30)

    assert "print" not in prepared
    assert "https://" not in prepared
    assert len(prepared) <= 30


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


def test_tts_gpt_sovits_posts_payload_sets_weights_and_plays_audio(monkeypatch):
    calls = []
    played = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if request.full_url.endswith("/tts"):
            return _FakeAudioResponse()
        return _FakeHTTPResponse()

    def fake_run(argv, **kwargs):
        played.append((argv, kwargs))
        return _Result()

    monkeypatch.setattr(tts_mod.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(tts_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(tts_mod.subprocess, "run", fake_run)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_base_url="http://127.0.0.1:9880",
            gsv_gpt_weights_path="/models/yachiyo.ckpt",
            gsv_sovits_weights_path="/models/yachiyo.pth",
            gsv_ref_audio_path="/voices/ref.wav",
            gsv_ref_audio_text="なんだか孤独になっちゃった夜は",
            gsv_ref_audio_language="ja",
            gsv_text_language="zh",
            gsv_top_k=12,
            gsv_media_type="wav",
            timeout_seconds=11,
        )
    )

    result = service.speak_async("彩叶，休息一下吧。")
    tts_request = calls[-1][0]
    payload = json.loads(tts_request.data.decode("utf-8"))

    assert result["ok"] is True
    assert result["message"] == "TTS 已完成"
    assert "set_gpt_weights" in calls[0][0].full_url
    assert "set_sovits_weights" in calls[1][0].full_url
    assert tts_request.full_url == "http://127.0.0.1:9880/tts"
    assert payload["text"] == "彩叶，休息一下吧。"
    assert payload["ref_audio_path"] == "/voices/ref.wav"
    assert payload["prompt_lang"] == "ja"
    assert payload["text_lang"] == "zh"
    assert payload["top_k"] == 12
    assert played[0][0][0] == "afplay"
    assert played[0][1]["timeout"] == 11
