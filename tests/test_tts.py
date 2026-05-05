"""TTSService 测试。"""

from __future__ import annotations

import json
import plistlib
import zipfile
from http.client import RemoteDisconnected
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import apps.shell.tts as tts_mod
import apps.shell.gpt_sovits_service as gsv_service
import apps.shell.tts_resources as tts_resources
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


def test_tts_sync_test_returns_final_status(monkeypatch):
    calls = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Result()

    monkeypatch.setattr(tts_mod.subprocess, "run", fake_run)
    service = TTSService(TTSConfig(enabled=True, provider="command", command="say {text}"))

    result = service.speak_sync("测试语音调用成功。")

    assert result["ok"] is True
    assert result["success"] is True
    assert result["message"] == "TTS 测试已完成"
    assert result["spoken_text"] == "测试语音调用成功。"
    assert calls[0][0] == ["say", "测试语音调用成功。"]


def test_tts_sync_test_reports_validation_error(monkeypatch):
    called = []
    monkeypatch.setattr(tts_mod.subprocess, "run", lambda *_args, **_kwargs: called.append(True))
    service = TTSService(TTSConfig(enabled=False, provider="command", command="say {text}"))

    result = service.speak_sync("测试语音")

    assert result["ok"] is False
    assert result["success"] is False
    assert result["skipped"] is True
    assert "未启用" in result["message"]
    assert called == []


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


def test_prepare_tts_text_strips_leading_action_cues():
    text = "（轻轻歪了歪头，眨了眨眼）呀呀，八六——早上好呀。"

    prepared = prepare_tts_text(text, max_chars=80)

    assert prepared == "呀呀，八六——早上好呀。"


def test_prepare_tts_text_keeps_non_action_parentheses():
    text = "（周日）今天适合慢慢整理计划。"

    prepared = prepare_tts_text(text, max_chars=80)

    assert prepared == text


def test_import_tts_voice_archive_returns_gpt_sovits_settings(monkeypatch, tmp_path):
    assets_root = tmp_path / "assets" / "tts"
    package_root = tmp_path / "package" / "voice"
    (package_root / "GPT_weights_v4").mkdir(parents=True)
    (package_root / "SoVITS_weights_v4").mkdir(parents=True)
    (package_root / "refs").mkdir(parents=True)
    (package_root / "GPT_weights_v4" / "voice.ckpt").write_bytes(b"gpt")
    (package_root / "SoVITS_weights_v4" / "voice.pth").write_bytes(b"sovits")
    (package_root / "refs" / "ref.wav").write_bytes(b"ref")
    (package_root / "yachiyo-tts-preset.json").write_text(
        json.dumps(
            {
                "kind": tts_resources.TTS_PRESET_KIND,
                "schema_version": 1,
                "slug": "voice",
                "files": {
                    "gpt_weights": "GPT_weights_v4/voice.ckpt",
                    "sovits_weights": "SoVITS_weights_v4/voice.pth",
                    "ref_audio": "refs/ref.wav",
                },
                "gpt_sovits": {
                    "ref_audio_text": "参考音频",
                    "ref_audio_language": "ja",
                    "text_language": "zh",
                    "top_k": 12,
                },
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "voice.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in package_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(package_root))

    monkeypatch.setattr(tts_resources, "get_user_tts_assets_dir", lambda: assets_root)

    result = tts_resources.import_tts_voice_archive_draft(archive)

    assert result["ok"] is True
    settings = result["tts_settings"]
    assert settings["enabled"] is True
    assert settings["provider"] == "gpt-sovits"
    assert settings["gsv_base_url"] == "http://127.0.0.1:9880"
    assert settings["gsv_service_workdir"].endswith("AI/GPT-SoVITS")
    assert settings["gsv_service_command"] == "python api_v2.py -a 127.0.0.1 -p 9880"
    assert settings["gsv_top_k"] == 12
    assert Path(settings["gsv_gpt_weights_path"]).is_file()
    assert Path(settings["gsv_sovits_weights_path"]).is_file()
    assert Path(settings["gsv_ref_audio_path"]).is_file()
    assert result["draft_changes"]["tts.provider"] == "gpt-sovits"


def test_gpt_sovits_service_status_reports_local_requirements(monkeypatch, tmp_path):
    workdir = tmp_path / "GPT-SoVITS"
    workdir.mkdir()
    monkeypatch.setattr(gsv_service, "_launch_agent_path", lambda: tmp_path / "agent.plist")
    monkeypatch.setattr(gsv_service, "_launch_agent_running", lambda: False)
    monkeypatch.setattr(gsv_service, "_service_reachable", lambda _url: {"ok": False, "error": "connection refused"})

    status = gsv_service.get_gpt_sovits_service_status(
        TTSConfig(gsv_service_workdir=str(workdir), gsv_service_command="python api_v2.py")
    )

    assert status["workdir_exists"] is True
    assert status["command_configured"] is True
    assert status["reachable"] is False
    assert status["launch_agent_installed"] is False


def test_gpt_sovits_service_status_uses_unsaved_draft_and_expands_env(monkeypatch, tmp_path):
    workdir = tmp_path / "GPT-SoVITS"
    workdir.mkdir()
    monkeypatch.setenv("GSV_TEST_ROOT", str(tmp_path))
    monkeypatch.setattr(gsv_service, "_launch_agent_path", lambda: tmp_path / "agent.plist")
    monkeypatch.setattr(gsv_service, "_launch_agent_running", lambda: False)
    monkeypatch.setattr(gsv_service, "_service_reachable", lambda _url: {"ok": True})

    status = gsv_service.get_gpt_sovits_service_status_for_values(
        base_url="http://127.0.0.1:9880",
        workdir="$GSV_TEST_ROOT/GPT-SoVITS",
        command="python api_v2.py",
    )

    assert status["reachable"] is True
    assert status["workdir_exists"] is True
    assert status["workdir"] == str(workdir)
    assert status["command_configured"] is True


def test_gpt_sovits_launch_agent_install_validates_workdir(monkeypatch):
    monkeypatch.setattr(gsv_service.platform, "system", lambda: "Darwin")

    result = gsv_service.install_gpt_sovits_launch_agent(
        TTSConfig(gsv_service_workdir="/definitely/missing", gsv_service_command="python api_v2.py")
    )

    assert result["ok"] is False
    assert "服务目录" in result["error"]


def test_gpt_sovits_launch_agent_install_writes_plist(monkeypatch, tmp_path):
    workdir = tmp_path / "GPT-SoVITS"
    workdir.mkdir()
    plist_path = tmp_path / "LaunchAgents" / "com.hermes-yachiyo.gpt-sovits.plist"
    launchctl_calls = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(gsv_service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(gsv_service, "_launch_agent_path", lambda: plist_path)
    monkeypatch.setattr(gsv_service, "_launchctl_domain", lambda: "gui/501")
    monkeypatch.setattr(gsv_service, "_log_path", lambda kind: tmp_path / f"gsv-{kind}.log")
    monkeypatch.setattr(gsv_service, "_service_reachable", lambda _url: {"ok": True})
    monkeypatch.setattr(gsv_service, "_launch_agent_running", lambda: True)
    monkeypatch.setattr(gsv_service, "_launchctl", lambda args, *, check: launchctl_calls.append(args) or _Result())

    result = gsv_service.install_gpt_sovits_launch_agent(
        TTSConfig(gsv_service_workdir=str(workdir), gsv_service_command="python api_v2.py -p 9880")
    )

    assert result["ok"] is True
    assert plist_path.exists()
    plist = plistlib.loads(plist_path.read_bytes())
    shell_command = plist["ProgramArguments"][-1]
    assert "brew shellenv" in shell_command
    assert "source .venv/bin/activate" in shell_command
    assert any(call[0] == "bootstrap" for call in launchctl_calls)


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


def test_tts_gpt_sovits_can_cache_audio_without_playback(tmp_path, monkeypatch):
    calls = []
    played = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if request.full_url.endswith("/tts"):
            return _FakeAudioResponse(body=b"RIFFcached")
        return _FakeHTTPResponse()

    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(tts_mod.subprocess, "run", lambda *args, **kwargs: played.append((args, kwargs)))
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_media_type="wav",
            gsv_ref_audio_path="/voices/ref.wav",
            gsv_ref_audio_text="ref text",
        )
    )
    output_path = tmp_path / "cached.wav"

    result = service.speak_sync("缓存这句语音。", play=False, output_path=str(output_path))

    assert result["ok"] is True
    assert result["audio_path"] == str(output_path)
    assert result["mime_type"] == "audio/wav"
    assert output_path.read_bytes() == b"RIFFcached"
    assert played == []


def test_tts_gpt_sovits_remote_disconnect_reports_endpoint(monkeypatch):
    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/tts"):
            raise RemoteDisconnected("Remote end closed connection without response")
        return _FakeHTTPResponse()

    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_base_url="http://127.0.0.1:9880",
            gsv_ref_audio_path="/voices/ref.wav",
            gsv_ref_audio_text="ref text",
        )
    )

    result = service.speak_sync("测试语音调用。")

    assert result["ok"] is False
    assert result["success"] is False
    assert "GPT-SoVITS /tts 请求失败" in result["error"]
    assert "http://127.0.0.1:9880/tts" in result["error"]
    assert "远端提前关闭连接" in result["error"]


def test_tts_gpt_sovits_retries_localhost_when_docker_host_disconnects(monkeypatch):
    calls = []
    played = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if "host.docker.internal" in request.full_url:
            raise RemoteDisconnected("Remote end closed connection without response")
        if request.full_url.endswith("/tts"):
            return _FakeAudioResponse()
        return _FakeHTTPResponse()

    def fake_run(argv, **kwargs):
        played.append((argv, kwargs))
        return _Result()

    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(tts_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(tts_mod.subprocess, "run", fake_run)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_base_url="http://host.docker.internal:9880",
            gsv_gpt_weights_path="/models/yachiyo.ckpt",
            gsv_ref_audio_path="/voices/ref.wav",
            gsv_ref_audio_text="ref text",
        )
    )

    result = service.speak_sync("测试语音调用。")

    assert result["ok"] is True
    assert calls[0].startswith("http://host.docker.internal:9880/set_gpt_weights")
    assert any(call.startswith("http://127.0.0.1:9880/set_gpt_weights") for call in calls)
    assert any(call == "http://127.0.0.1:9880/tts" for call in calls)
    assert played[0][0][0] == "afplay"


def test_tts_gpt_sovits_weight_error_reports_step(monkeypatch):
    def fake_urlopen(request, timeout):
        if "set_gpt_weights" in request.full_url:
            raise ConnectionRefusedError("connection refused")
        return _FakeHTTPResponse()

    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_base_url="http://127.0.0.1:9880",
            gsv_gpt_weights_path="/models/yachiyo.ckpt",
            gsv_ref_audio_path="/voices/ref.wav",
            gsv_ref_audio_text="ref text",
        )
    )

    result = service.speak_sync("测试语音调用。")

    assert result["ok"] is False
    assert "set_gpt_weights" in result["error"]
    assert "连接被拒绝" in result["error"]


def test_tts_gpt_sovits_validates_reference_audio_before_request(monkeypatch):
    called = []
    monkeypatch.setattr(tts_mod, "urlopen", lambda *_args, **_kwargs: called.append(True))
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_base_url="http://127.0.0.1:9880",
        )
    )

    result = service.speak_sync("测试语音调用。")

    assert result["ok"] is False
    assert result["skipped"] is True
    assert "参考音频路径" in result["message"]
    assert called == []


def test_tts_gpt_sovits_http_error_reports_json_body(monkeypatch):
    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/tts"):
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=BytesIO(b'{"message":"ref_audio_path is required"}'),
            )
        return _FakeHTTPResponse()

    monkeypatch.setattr(tts_mod, "urlopen", fake_urlopen)
    service = TTSService(
        TTSConfig(
            enabled=True,
            provider="gpt-sovits",
            gsv_base_url="http://127.0.0.1:9880",
            gsv_ref_audio_path="/voices/ref.wav",
            gsv_ref_audio_text="ref text",
        )
    )

    result = service.speak_sync("测试语音调用。")

    assert result["ok"] is False
    assert "HTTP 400" in result["error"]
    assert "ref_audio_path is required" in result["error"]
