"""Model profile registry tests."""

from __future__ import annotations

import json
import sqlite3
import ssl

import pytest

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.model_profiles import (
    OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS,
    ModelProfileError,
    ModelProfileService,
    openai_compatible_chat,
    openai_compatible_chat_message,
    read_openai_compatible_chat_timeout,
)
from scripts.verify_secret_redaction import verify_secret_redaction


def make_profile_service(tmp_path) -> ModelProfileService:
    return ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )


def _vision_challenge():
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "left/right color test"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ], ("red", "blue")


def test_model_profile_crud_redacts_and_preserves_api_key(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Work Gateway",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )

        assert profile["api_key_configured"] is True
        assert "api_key" not in profile

        updated = service.update_profile(
            profile["profile_id"],
            {"base_url": "https://gateway.example.test/v1", "api_key": ""},
        )
        private = service.get_profile_private(profile["profile_id"])

        assert updated["base_url"] == "https://gateway.example.test/v1"
        assert updated["api_key_configured"] is True
        assert private["api_key"] == "sk-secret"

        conn = sqlite3.connect(tmp_path / "model-profiles.db")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
                (profile["profile_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["api_key"] == ""
        assert row["credential_ref"] == f"model_profile:{profile['profile_id']}:api_key"
    finally:
        service.close()


def test_model_profile_defaults_validate_capability(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile({"name": "Vision", "capability": "vision"})

        with pytest.raises(ModelProfileError):
            service.set_defaults({"chat": profile["profile_id"]})

        result = service.set_defaults({"vision": profile["profile_id"]})
        assert result["defaults"]["vision"] == profile["profile_id"]
    finally:
        service.close()


def test_model_profile_test_sets_default_when_missing(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Chat",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )

        result = service._record_test_result(profile["profile_id"], ok=True, message="OK")

        assert result["defaults"]["chat"] == profile["profile_id"]
        assert service.get_defaults()["chat"] == profile["profile_id"]
    finally:
        service.close()


def test_model_profile_defaults_repair_single_available_profile(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Chat",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='available', last_tested_at='now', updated_at='now' WHERE profile_id=?",
            (profile["profile_id"],),
        )
        service._conn.commit()

        assert service.get_defaults()["chat"] == profile["profile_id"]
    finally:
        service.close()


def test_model_profile_defaults_do_not_guess_between_multiple_available_profiles(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        first = service.create_profile(
            {
                "name": "Chat One",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model-a",
                "api_key": "sk-secret-a",
            }
        )
        second = service.create_profile(
            {
                "name": "Chat Two",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model-b",
                "api_key": "sk-secret-b",
            }
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='available', last_tested_at='now', updated_at='now' WHERE profile_id IN (?, ?)",
            (first["profile_id"], second["profile_id"]),
        )
        service._conn.commit()

        assert service.get_defaults()["chat"] == ""
    finally:
        service.close()


def test_model_source_owns_credentials_and_models_reference_it(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "MiniMax",
                "provider": "openai_compatible",
                "base_url": "https://api.minimax.chat/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "MiniMax Chat",
                "capability": "chat",
                "model": "MiniMax-M2.7",
                "api_key": "sk-ignored",
            }
        )
        public_profile = service.get_profile(profile["profile_id"])
        private_profile = service.get_profile_private(profile["profile_id"])
        updated = service.update_profile(profile["profile_id"], {"model": "MiniMax-M2.8"})

        assert public_profile["source_name"] == "MiniMax"
        assert public_profile["base_url"] == "https://api.minimax.chat/v1"
        assert public_profile["api_key_configured"] is True
        assert private_profile["api_key"] == "sk-source-secret"
        assert service.get_profile_private(profile["profile_id"])["api_key"] == "sk-source-secret"
        assert updated["model"] == "MiniMax-M2.8"

        conn = sqlite3.connect(tmp_path / "model-profiles.db")
        conn.row_factory = sqlite3.Row
        try:
            source_row = conn.execute(
                "SELECT api_key, credential_ref FROM model_sources WHERE source_id=?",
                (source["source_id"],),
            ).fetchone()
            profile_row = conn.execute(
                "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
                (profile["profile_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert source_row is not None
        assert profile_row is not None
        assert source_row["api_key"] == ""
        assert source_row["credential_ref"] == f"model_source:{source['source_id']}:api_key"
        assert profile_row["api_key"] == ""
        assert profile_row["credential_ref"] == ""
    finally:
        service.close()


def test_model_sources_are_scoped_by_capability(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        chat_source = service.create_source(
            {
                "name": "Gateway",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-chat",
            }
        )
        vision_source = service.create_source(
            {
                "name": "Gateway",
                "capability": "vision",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-vision",
            }
        )

        assert chat_source["capability"] == "chat"
        assert vision_source["capability"] == "vision"
        with pytest.raises(ModelProfileError, match="ID 在当前类型下必须唯一"):
            service.create_source(
                {
                    "name": "Gateway",
                    "capability": "vision",
                    "provider": "openai_compatible",
                    "base_url": "https://api.example.test/v1",
                }
            )
        with pytest.raises(ModelProfileError):
            service.create_profile(
                {
                    "source_id": chat_source["source_id"],
                    "name": "Wrong Vision",
                    "capability": "vision",
                    "model": "vision-model",
                }
            )
    finally:
        service.close()


def test_sync_tts_provider_registers_available_gsv_source_and_default(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        result = service.sync_tts_provider(
            {
                "enabled": True,
                "provider": "gpt-sovits",
                "base_url": "http://127.0.0.1:9880",
                "voice": "yachiyo",
                "options": {"gsv_text_language": "zh"},
            }
        )

        assert result["ok"] is True
        assert result["source"]["capability"] == "tts"
        assert result["source"]["provider"] == "gsv_tts_local"
        assert result["source"]["status"] == "available"
        assert result["profile"]["capability"] == "tts"
        assert result["profile"]["model"] == "yachiyo"
        assert result["profile"]["status"] == "available"
        assert result["defaults"]["tts"] == result["profile"]["profile_id"]

        second = service.sync_tts_provider(
            {
                "enabled": True,
                "provider": "gpt-sovits",
                "base_url": "http://127.0.0.1:9880",
                "voice": "yachiyo",
            }
        )

        assert second["source"]["source_id"] == result["source"]["source_id"]
        assert second["profile"]["profile_id"] == result["profile"]["profile_id"]
        assert len([source for source in service.list_sources()["sources"] if source["capability"] == "tts"]) == 1
    finally:
        service.close()


def test_legacy_shared_source_is_split_by_profile_capability(tmp_path):
    db_path = tmp_path / "model-profiles.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE model_sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE model_profiles (
            profile_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL UNIQUE,
            capability TEXT NOT NULL DEFAULT 'chat',
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE model_profile_defaults (
            capability TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO model_sources VALUES (
            'source_shared', 'Gateway', 'openai_compatible', 'https://api.example.test/v1',
            'sk-source-secret123456', '{}', 1, 'available', 'now', '', 'now', 'now'
        );
        INSERT INTO model_profiles VALUES (
            'profile_chat', 'source_shared', 'Gateway Chat', 'chat', 'openai_compatible',
            '', 'chat-model', '', '{}', 1, 'available', 'now', '', 'now', 'now'
        );
        INSERT INTO model_profiles VALUES (
            'profile_vision', 'source_shared', 'Gateway Vision', 'vision', 'openai_compatible',
            '', 'vision-model', '', '{}', 1, 'available', 'now', '', 'now', 'now'
        );
        """
    )
    conn.close()

    service = make_profile_service(tmp_path)
    try:
        sources = service.list_sources()["sources"]
        by_capability = {source["capability"]: source for source in sources}

        assert set(by_capability) == {"chat", "vision"}
        assert by_capability["chat"]["name"] == "Gateway"
        assert by_capability["vision"]["name"] == "Gateway"
        assert service.get_profile("profile_chat")["source_id"] == by_capability["chat"]["source_id"]
        assert service.get_profile("profile_vision")["source_id"] == by_capability["vision"]["source_id"]
        assert service.get_source_private(by_capability["chat"]["source_id"])["api_key"] == "sk-source-secret123456"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT api_key, credential_ref FROM model_sources ORDER BY capability").fetchall()
        finally:
            conn.close()
        assert [row["api_key"] for row in rows] == ["", ""]
        assert all(row["credential_ref"] for row in rows)
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_legacy_model_profile_api_key_migration_vacuums_plaintext_secret(tmp_path):
    db_path = tmp_path / "model-profiles.db"
    legacy_secret = "sk-legacy-profile-secret123456"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        f"""
        CREATE TABLE model_sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capability TEXT NOT NULL DEFAULT 'chat',
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{{}}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(capability, name)
        );
        CREATE TABLE model_profiles (
            profile_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL UNIQUE,
            capability TEXT NOT NULL DEFAULT 'chat',
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{{}}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE model_profile_defaults (
            capability TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO model_profiles VALUES (
            'profile_legacy_secret', '', 'Legacy Chat', 'chat', 'openai_compatible',
            'https://api.example.test/v1', 'demo-model', '{legacy_secret}', '{{}}',
            1, 'available', 'now', '', 'now', 'now'
        );
        """
    )
    conn.close()

    service = make_profile_service(tmp_path)
    try:
        profile = service.get_profile_private("profile_legacy_secret")
        assert profile["api_key"] == legacy_secret

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
                ("profile_legacy_secret",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["api_key"] == ""
        assert row["credential_ref"] == "model_profile:profile_legacy_secret:api_key"
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_model_source_reports_native_provider_adapter(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Xiaomi MiMo",
                "provider": "xiaomi_mimo",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "MiMo",
                "capability": "chat",
                "model": "mimo-v2-pro",
            }
        )
        public_source = service.get_source(source["source_id"])
        public_profile = service.get_profile(profile["profile_id"])

        assert public_source["native_provider"] == "xiaomi"
        assert public_source["api_key_name"] == "XIAOMI_API_KEY"
        assert public_source["can_use_as_native"] is True
        assert public_profile["native_provider"] == "xiaomi"
        assert public_profile["runtime_scope"] == "native"
    finally:
        service.close()


def test_openrouter_profile_keeps_openrouter_as_runtime_provider(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "OpenRouter",
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "DeepSeek via OpenRouter",
                "capability": "chat",
                "model": "deepseek/deepseek-chat",
            }
        )

        public_profile = service.get_profile(profile["profile_id"])

        assert public_profile["native_provider"] == "openrouter"
        assert public_profile["api_key_name"] == "OPENROUTER_API_KEY"
    finally:
        service.close()


def test_paused_source_marks_child_profiles_unavailable(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Gateway",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "Gateway Chat",
                "capability": "chat",
                "model": "demo-model",
            }
        )

        service.update_source(source["source_id"], {"enabled": False})
        paused_profile = service.get_profile(profile["profile_id"])

        assert paused_profile["enabled"] is False
        assert paused_profile["profile_enabled"] is True
        assert paused_profile["source_enabled"] is False

        service.update_source(source["source_id"], {"enabled": True})
        assert service.get_profile(profile["profile_id"])["enabled"] is True
    finally:
        service.close()


def test_model_profile_test_updates_status(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    profile = service.create_profile(
        {
            "name": "Runnable",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *_args, **_kwargs: "OK")
    try:
        result = service.test_profile(profile["profile_id"])
        tested = service.get_profile(profile["profile_id"])

        assert result["ok"] is True
        assert tested["status"] == "available"
        assert tested["last_tested_at"]
    finally:
        service.close()


def test_openai_compatible_chat_reads_reasoning_content_and_xiaomi_api_key_header(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "", "reasoning_content": "red, blue"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer sk-xiaomi"
        assert request.get_header("Api-key") == "sk-xiaomi"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    result = openai_compatible_chat(
        "https://token-plan-cn.xiaomimimo.com/v1",
        "mimo-v2-omni",
        "sk-xiaomi",
        [{"role": "user", "content": "hello"}],
    )

    assert result == "red, blue"


def test_openai_compatible_chat_skips_reasoning_content_parts(monkeypatch):
    private_reasoning = "private non-stream reasoning"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "reasoning", "text": {"value": private_reasoning}},
                                    {"type": "text", "text": {"value": "visible answer"}},
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = openai_compatible_chat(
        "https://api.example.test/v1",
        "demo-model",
        "sk-demo",
        [{"role": "user", "content": "hello"}],
    )

    assert result == "visible answer"
    assert private_reasoning not in result


def test_openai_compatible_chat_timeout_is_configurable(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", raising=False)
    assert OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS == 180
    assert read_openai_compatible_chat_timeout() == 180

    monkeypatch.setenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", "240.5")
    assert read_openai_compatible_chat_timeout() == 240.5

    monkeypatch.setenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", "invalid")
    assert read_openai_compatible_chat_timeout() == 180


def test_openai_compatible_chat_timeout_error_reports_limit(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr(
        "apps.shell.model_profiles.urlrequest.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("read operation timed out")),
    )

    with pytest.raises(ModelProfileError, match="等待响应超过 12 秒"):
        openai_compatible_chat(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
        )


def test_openai_compatible_chat_message_returns_tool_calls(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "workspace_read", "arguments": "{\"path\":\"README.md\"}"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert body["tools"][0]["function"]["name"] == "workspace_read"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    message = openai_compatible_chat_message(
        "https://api.example.test/v1",
        "demo-model",
        "sk-demo",
        [{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "workspace_read", "parameters": {"type": "object"}}}],
    )

    assert message["tool_calls"][0]["function"]["name"] == "workspace_read"


def test_openai_compatible_chat_message_streams_sse_chunks(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                b'"type":"function","function":{"name":"workspace_read","arguments":"{}"}}]}}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert body["stream"] is True
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert chunks[0]["choices"][0]["delta"]["content"] == "hello "
    assert chunks[1]["choices"][0]["delta"]["content"] == "world"
    assert chunks[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "workspace_read"


def test_openai_compatible_chat_message_streams_legacy_function_call_sse(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"checking "}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"function_call":'
                b'{"name":"workspace_","arguments":"{\\"path\\":\\"READ"}}}]}\n\n'
            )
            yield (
                b'data: {"choices":[{"delta":{"function_call":'
                b'{"name":"read","arguments":"ME.md\\"}"}},'
                b'"finish_reason":"function_call"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert chunks[0]["choices"][0]["delta"]["content"] == "checking "
    assert chunks[1]["choices"][0]["delta"]["function_call"]["name"] == "workspace_"
    assert chunks[1]["choices"][0]["delta"]["function_call"]["arguments"] == '{"path":"READ'
    assert chunks[2]["choices"][0]["delta"]["function_call"]["name"] == "read"
    assert chunks[2]["choices"][0]["delta"]["function_call"]["arguments"] == 'ME.md"}'
    assert chunks[2]["choices"][0]["finish_reason"] == "function_call"


def test_openai_compatible_chat_message_streams_coalesced_sse_frames(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = json.dumps({"choices": [{"delta": {"content": "hello "}}]})
            second = json.dumps({"choices": [{"delta": {"content": "world"}}]})
            yield f": keepalive\n\ndata: {first}\n\ndata: {second}\n\ndata: [DONE]\n\n".encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["hello ", "world"]


def test_openai_compatible_chat_message_stream_ignores_control_events(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = json.dumps({"choices": [{"delta": {"content": "control "}}]})
            second = json.dumps({"choices": [{"delta": {"content": "ignored"}}]})
            yield (
                b"event: ping\n"
                b'data: {"type":"ping"}\n\n'
                b'data: {"type":"heartbeat","created":123}\n\n'
                b'data: {"object":"keepalive"}\n\n'
                + f"data: {first}\n\n".encode("utf-8")
                + b'event: heartbeat\n'
                + f"data: {second}\n\n".encode("utf-8")
                + b"data: [DONE]\n\n"
            )

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["control ", "ignored"]


def test_openai_compatible_chat_message_streams_multiline_sse_data_event(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b"id: chunk-1\r\n"
                b"event: completion.chunk\r\n"
                b'data: {"choices":[{"delta":{"content":"multi line"}\r\n'
                b'data: ,"finish_reason":"stop"}]}\r\n\r\n'
                b"data: [DONE]\r\n\r\n"
            )

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert len(chunks) == 1
    assert chunks[0]["choices"][0]["delta"]["content"] == "multi line"
    assert chunks[0]["choices"][0]["finish_reason"] == "stop"


def test_openai_compatible_chat_message_streams_split_sse_frame_chunks(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            payload = json.dumps({"choices": [{"delta": {"content": "split frame"}}]})
            frame = f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
            yield frame[:9]
            yield frame[9:31]
            yield frame[31:52]
            yield frame[52:]

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["split frame"]


def test_openai_compatible_chat_message_streams_split_utf8_sse_frame_chunks(monkeypatch):
    expected = "跨块文本"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            payload = json.dumps({"choices": [{"delta": {"content": expected}}]}, ensure_ascii=False)
            frame = f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
            split_at = frame.index("跨".encode("utf-8")) + 1
            yield frame[:split_at]
            yield frame[split_at : split_at + 2]
            yield frame[split_at + 2 :]

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == [expected]
    assert "\ufffd" not in json.dumps(chunks, ensure_ascii=False)


def test_openai_compatible_chat_message_stream_raises_provider_error(monkeypatch):
    leaked_secret = "sk-stream-provider-error123456"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            yield (
                "data: "
                + json.dumps(
                    {
                        "error": {
                            "message": f"upstream rejected api_key={leaked_secret}",
                            "type": "invalid_request_error",
                            "code": "bad_api_key",
                        }
                    }
                )
                + "\n\n"
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    with pytest.raises(ModelProfileError) as excinfo:
        list(
            openai_compatible_chat_message(
                "https://api.example.test/v1",
                "demo-model",
                "sk-demo",
                [{"role": "user", "content": "hello"}],
                stream=True,
            )
        )

    error_text = str(excinfo.value)
    assert "OpenAI-compatible Profile 调用失败" in error_text
    assert "invalid_request_error" in error_text
    assert "bad_api_key" in error_text
    assert leaked_secret not in error_text
    assert "[redacted]" in error_text


@pytest.mark.parametrize(
    "error_frame",
    [
        "event: error\n"
        'data: {"message":"gateway rejected api_key=sk-stream-event-error123456","code":"bad_api_key"}\n\n',
        'data: {"type":"error","message":"gateway rejected api_key=sk-stream-event-error123456","code":"bad_api_key"}\n\n',
    ],
)
def test_openai_compatible_chat_message_stream_raises_provider_error_event(monkeypatch, error_frame):
    leaked_secret = "sk-stream-event-error123456"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            yield error_frame.encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    with pytest.raises(ModelProfileError) as excinfo:
        list(
            openai_compatible_chat_message(
                "https://api.example.test/v1",
                "demo-model",
                "sk-demo",
                [{"role": "user", "content": "hello"}],
                stream=True,
            )
        )

    error_text = str(excinfo.value)
    assert "OpenAI-compatible Profile 调用失败" in error_text
    assert "bad_api_key" in error_text
    assert leaked_secret not in error_text
    assert "[redacted]" in error_text


def test_test_and_save_profile_failure_does_not_persist(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Gateway",
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-secret",
        }
    )

    def fail_chat(*_args, **_kwargs):
        raise ModelProfileError("network failed")

    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fail_chat)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {"name": "Draft", "capability": "chat", "model": "demo-model"},
        )

        assert result["ok"] is False
        assert result["source"]["status"] == "failed"
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_vision_profile_rejects_model_that_fails_real_image_test(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "capability": "vision",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []
    monkeypatch.setattr("apps.shell.model_profiles._vision_test_challenge", _vision_challenge)
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *args, **kwargs: calls.append((args, kwargs)) or "OK")
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "Text Only",
                "capability": "vision",
                "model": "qwen/qwen3-coder",
                "options": {"remote_model": {"id": "qwen/qwen3-coder", "input_modalities": ["text"]}},
            },
        )

        assert result["ok"] is False
        assert "真实图片测试" in result["message"]
        assert calls
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_vision_profile_test_uses_image_payload_and_saves(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "capability": "vision",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []

    def fake_chat(base_url, model, api_key, messages):
        calls.append((base_url, model, api_key, messages))
        return "red, blue"

    monkeypatch.setattr("apps.shell.model_profiles._vision_test_challenge", _vision_challenge)
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fake_chat)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "Vision",
                "capability": "vision",
                "model": "openai/gpt-4.1-mini",
                "options": {
                    "remote_model": {
                        "id": "openai/gpt-4.1-mini",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    }
                },
            },
        )

        assert result["ok"] is True
        assert result["profile"]["status"] == "available"
        assert service.get_source(source["source_id"])["status"] == "available"
        assert result["profile"]["options"]["remote_model"]["input_modalities"] == ["text", "image"]
        assert calls[0][3][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        service.close()


def test_vision_profile_can_pass_without_remote_metadata(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "capability": "vision",
            "provider": "xiaomi",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []
    monkeypatch.setattr("apps.shell.model_profiles._vision_test_challenge", _vision_challenge)
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *args, **kwargs: calls.append((args, kwargs)) or "left red, right blue")
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "MiMo Vision",
                "capability": "vision",
                "model": "mimo-v2.5",
            },
        )

        assert result["ok"] is True
        assert result["profile"]["status"] == "available"
        assert result["profile"]["capability"] == "vision"
        assert calls[0][0][3][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        service.close()


def test_xiaomi_text_reasoning_model_is_not_saved_as_vision(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "capability": "vision",
            "provider": "xiaomi",
            "base_url": "https://api.mimo-v2.com/v1",
            "api_key": "sk-source-secret",
        }
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("known text-only Xiaomi model should be rejected before HTTP probing")

    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fail_if_called)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "MiMo Pro Vision",
                "capability": "vision",
                "model": "mimo-v2.5-pro",
            },
        )

        assert result["ok"] is False
        assert "文本/推理模型" in result["message"]
        assert result["vision_capability"]["recommended_vision_models"] == ["mimo-v2.5", "mimo-v2-omni"]
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_fetch_source_models_reads_openai_compatible_list(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "DeepSeek",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-source-secret",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                        {"id": "deepseek-reasoner"},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://api.deepseek.com/models"
        assert request.get_header("Authorization") == "Bearer sk-source-secret"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])

        assert result["ok"] is True
        assert result["count"] == 2
        assert result["models"] == [
            {"id": "deepseek-chat", "owned_by": "deepseek", "provider_key": "deepseek"},
            {"id": "deepseek-reasoner", "owned_by": "", "provider_key": "deepseek"},
        ]
        assert "api_key" not in result["source"]
    finally:
        service.close()


def test_fetch_xiaomi_models_marks_known_vision_capabilities(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "capability": "vision",
            "provider": "xiaomi",
            "base_url": "https://api.mimo-v2.com/v1",
            "api_key": "sk-source-secret",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "mimo-v2.5-pro"},
                        {"id": "mimo-v2.5"},
                        {"id": "mimo-v2-omni"},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://api.mimo-v2.com/v1/models"
        assert request.get_header("Authorization") == "Bearer sk-source-secret"
        assert request.get_header("Api-key") == "sk-source-secret"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])
        by_id = {model["id"]: model for model in result["models"]}

        assert by_id["mimo-v2.5-pro"]["known_capability"] == "text"
        assert by_id["mimo-v2.5-pro"]["not_recommended_for"] == ["vision"]
        assert by_id["mimo-v2.5"]["known_capability"] == "vision"
        assert by_id["mimo-v2.5"]["recommended_for"] == ["vision"]
        assert by_id["mimo-v2-omni"]["known_capability"] == "vision"
    finally:
        service.close()


def test_fetch_source_models_preserves_openrouter_metadata(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {
                            "id": "qwen/qwen3-coder",
                            "canonical_slug": "qwen/qwen3-coder",
                            "name": "Qwen: Qwen3 Coder",
                            "context_length": 262144,
                            "architecture": {
                                "modality": "text->text",
                                "input_modalities": ["text"],
                                "output_modalities": ["text"],
                            },
                            "pricing": {"prompt": "0", "completion": "0"},
                            "top_provider": {"max_completion_tokens": 65536, "is_moderated": False},
                            "supported_parameters": ["tools", "structured_outputs"],
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://openrouter.ai/api/v1/models"
        assert request.get_header("Authorization") is None
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])
        model = result["models"][0]

        assert model["provider_key"] == "qwen"
        assert model["name"] == "Qwen: Qwen3 Coder"
        assert model["context_length"] == 262144
        assert model["max_completion_tokens"] == 65536
        assert model["input_modalities"] == ["text"]
        assert model["supported_parameters"] == ["tools", "structured_outputs"]
        assert model["is_free"] is True
    finally:
        service.close()


def test_agent_runtime_uses_model_profile(monkeypatch, tmp_path):
    profile_service = make_profile_service(tmp_path)
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    profile = profile_service.create_profile(
        {
            "name": "Agent Profile",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Profile result"})
    try:
        agent = runtime.create_agent(
            {
                "name": "Profile Agent",
                "model_mode": "profile",
                "model_profile_id": profile["profile_id"],
            }
        )
        run = runtime.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Hello"})

        assert run["status"] == "completed"
        assert run["result"] == "Profile result"
    finally:
        runtime.close()
        profile_service.close()


def test_agent_runtime_uses_openai_compatible_provider_source_profile(monkeypatch, tmp_path):
    profile_service = make_profile_service(tmp_path)
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    source = profile_service.create_source(
        {
            "name": "Xiaomi MiMo",
            "provider": "xiaomi_mimo",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": "sk-secret",
        }
    )
    profile = profile_service.create_profile(
        {
            "source_id": source["source_id"],
            "name": "MiMo Agent",
            "capability": "chat",
            "model": "mimo-v2.5-pro",
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "MiMo result"})
    try:
        agent = runtime.create_agent(
            {
                "name": "MiMo Profile Agent",
                "model_mode": "profile",
                "model_profile_id": profile["profile_id"],
            }
        )
        run = runtime.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Hello"})

        assert run["status"] == "completed"
        assert run["result"] == "MiMo result"
    finally:
        runtime.close()
        profile_service.close()
