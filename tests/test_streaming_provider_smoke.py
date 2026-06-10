"""OpenAI-compatible provider streaming smoke helper tests."""

from __future__ import annotations

import json
import ssl

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
