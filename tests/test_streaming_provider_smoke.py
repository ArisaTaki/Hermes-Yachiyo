"""OpenAI-compatible provider streaming smoke helper tests."""

from __future__ import annotations

import json
import ssl

import pytest

from scripts import smoke_openai_compatible_stream as smoke


def test_stream_smoke_summarizes_split_tool_call_without_secrets(monkeypatch):
    leaked_secret = "sk-stream-smoke-secret123456"
    requests: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"checking "}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                b'"type":"function","function":{"name":"workspace_","arguments":"{\\"path\\":\\"READ"}}]}}]}\n\n'
            )
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                b'"function":{"name":"read","arguments":"ME.md\\"}"}}]},'
                b'"finish_reason":"tool_calls"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout, context):
        requests.append(json.loads(request.data.decode("utf-8")))
        assert timeout == 180
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key=leaked_secret,
        tool_call=True,
        require_tool_call=True,
        expect_tool_argument_substrings=["README.md"],
    )

    assert requests[0]["stream"] is True
    assert requests[0]["tools"][0]["function"]["name"] == "workspace_read"
    assert summary["ok"] is True
    assert summary["chunk_count"] == 3
    assert summary["content_chars"] == len("checking ")
    assert summary["tool_call_delta_count"] == 2
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_1",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
        }
    ]
    assert leaked_secret not in json.dumps(summary)
    assert "README.md" not in json.dumps(summary)


def test_stream_smoke_requires_content_and_expected_tool_name(monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"ok "}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                b'"type":"function","function":{"name":"workspace_read","arguments":"{}"}}]},'
                b'"finish_reason":"tool_calls"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout, context):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key="sk-stream-smoke-secret123456",
        require_content=True,
        expect_tool_name="workspace_read",
    )

    assert requests[0]["tools"][0]["function"]["name"] == "workspace_read"
    assert summary["ok"] is True
    assert summary["content_chars"] == len("ok ")
    assert summary["tool_call_count"] == 1


def test_stream_smoke_tolerates_role_and_usage_only_provider_chunks(monkeypatch):
    requests: list[dict] = []
    leaked_secret = "sk-stream-usage-secret123456"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            yield b": provider heartbeat\n\n"
            yield b'data: {"choices":[{"delta":{"content":"checking usage "}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_usage",'
                b'"type":"function","function":{"name":"workspace_read","arguments":"{\\"path\\":\\"README.md\\"}"}}]},'
                b'"finish_reason":"tool_calls"}]}\n\n'
            )
            yield b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n\n'
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key=leaked_secret,
        require_content=True,
        expect_tool_name="workspace_read",
        expect_tool_argument_substrings=["README.md"],
    )

    assert requests[0]["stream"] is True
    assert summary["ok"] is True
    assert summary["chunk_count"] == 4
    assert summary["content_chars"] == len("checking usage ")
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {"id": "call_usage", "name": "workspace_read", "argument_chars": len('{"path":"README.md"}')}
    ]
    assert leaked_secret not in json.dumps(summary)
    assert "README.md" not in json.dumps(summary)


def test_stream_smoke_fails_when_expected_content_or_tool_is_missing(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                b'"function":{"name":"other_tool","arguments":"{}"}}]}}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(
        "apps.shell.model_profiles.urlrequest.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    with pytest.raises(RuntimeError, match="without content"):
        smoke.run_stream_smoke(
            base_url="https://api.example.test/v1",
            model="demo-model",
            api_key="sk-stream-smoke-secret123456",
            tool_call=True,
            require_content=True,
        )

    with pytest.raises(RuntimeError, match="expected tool call 'workspace_read'"):
        smoke.run_stream_smoke(
            base_url="https://api.example.test/v1",
            model="demo-model",
            api_key="sk-stream-smoke-secret123456",
            tool_call=True,
            expect_tool_name="workspace_read",
        )

    with pytest.raises(RuntimeError, match="expected tool call argument substring"):
        smoke.run_stream_smoke(
            base_url="https://api.example.test/v1",
            model="demo-model",
            api_key="sk-stream-smoke-secret123456",
            tool_call=True,
            expect_tool_argument_substrings=["README.md"],
        )


def test_stream_smoke_main_expect_tool_name_requests_tool_call(monkeypatch, capsys):
    calls: list[dict] = []

    def fake_run_stream_smoke(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "chunk_count": 1, "content_chars": 1, "tool_call_count": 1, "tool_calls": []}

    monkeypatch.setattr(smoke, "run_stream_smoke", fake_run_stream_smoke)

    exit_code = smoke.main(
        [
            "--base-url",
            "https://api.example.test/v1",
            "--model",
            "demo-model",
            "--api-key",
            "sk-stream-smoke-secret123456",
            "--require-content",
            "--expect-tool-name",
            "workspace_read",
            "--expect-tool-argument-substring",
            "README.md",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[0]["tool_call"] is True
    assert calls[0]["require_content"] is True
    assert calls[0]["expect_tool_name"] == "workspace_read"
    assert calls[0]["expect_tool_argument_substrings"] == ["README.md"]
    assert "sk-stream" not in captured.out


def test_stream_smoke_main_redacts_provider_errors(monkeypatch, capsys):
    leaked_secret = "sk-provider-error-smoke123456"

    def fake_run_stream_smoke(**_kwargs):
        raise RuntimeError(f"provider rejected api_key={leaked_secret}")

    monkeypatch.setattr(smoke, "run_stream_smoke", fake_run_stream_smoke)

    exit_code = smoke.main(
        [
            "--base-url",
            "https://api.example.test/v1",
            "--model",
            "demo-model",
            "--api-key",
            leaked_secret,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert leaked_secret not in captured.err
    assert "[redacted]" in captured.err
