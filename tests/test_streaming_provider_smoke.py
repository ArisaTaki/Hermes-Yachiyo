"""OpenAI-compatible provider streaming smoke helper tests."""

from __future__ import annotations

import json
import ssl
from types import SimpleNamespace

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
        expect_tool_argument_json_fields=["path=README.md"],
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


def test_stream_smoke_validates_multiline_sse_tool_call_without_leaking_arguments(monkeypatch):
    leaked_secret = "sk-stream-multiline-secret123456"
    requests: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b"id: smoke-tool-1\r\n"
                b"event: completion.chunk\r\n"
                b'data: {"choices":[{"delta":{"content":"checking multiline "}}]}\r\n\r\n'
            )
            yield (
                b"id: smoke-tool-2\r\n"
                b"event: completion.chunk\r\n"
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_multiline",\r\n'
                b'data: "type":"function","function":{"name":"workspace_read","arguments":"{\\"path\\":\\"README.md\\"}"}}]},\r\n'
                b'data: "finish_reason":"tool_calls"}]}\r\n\r\n'
            )
            yield b"data: [DONE]\r\n\r\n"

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
        require_content=True,
        require_tool_call=True,
        expect_tool_name="workspace_read",
        expect_tool_argument_substrings=["README.md"],
        expect_finish_reasons=["tool_calls"],
    )

    summary_json = json.dumps(summary)
    assert requests[0]["stream"] is True
    assert requests[0]["tools"][0]["function"]["name"] == "workspace_read"
    assert summary["ok"] is True
    assert summary["chunk_count"] == 2
    assert summary["content_chars"] == len("checking multiline ")
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_call_delta_count"] == 1
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_multiline",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
        }
    ]
    assert leaked_secret not in summary_json
    assert "README.md" not in summary_json


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


def test_stream_smoke_summarizes_reasoning_without_leaking_text(monkeypatch):
    requests: list[dict] = []
    private_reasoning = "private chain of thought"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"reasoning_content":"private chain "}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"reasoning":"of thought"}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"final answer"},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-reasoning-model",
        api_key="sk-stream-smoke-secret123456",
        require_content=True,
        require_reasoning=True,
        expect_finish_reasons=["stop"],
    )

    assert requests[0]["stream"] is True
    assert summary["ok"] is True
    assert summary["content_chars"] == len("final answer")
    assert summary["reasoning_chars"] == len(private_reasoning)
    assert summary["finish_reasons"] == ["stop"]
    assert private_reasoning not in json.dumps(summary)

    class NoReasoningResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"final answer"},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(
        "apps.shell.model_profiles.urlrequest.urlopen",
        lambda *_args, **_kwargs: NoReasoningResponse(),
    )

    with pytest.raises(RuntimeError, match="without reasoning"):
        smoke.run_stream_smoke(
            base_url="https://api.example.test/v1",
            model="demo-reasoning-model",
            api_key="sk-stream-smoke-secret123456",
            require_reasoning=True,
        )


def test_stream_smoke_accepts_message_level_content_and_reasoning_frames(monkeypatch):
    requests: list[dict] = []
    private_reasoning = "message-level private thought"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b'data: {"choices":[{"message":{"role":"assistant",'
                b'"content":"final message","reasoning_content":"message-level private thought"},'
                b'"finish_reason":"stop"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-message-level-model",
        api_key="sk-stream-smoke-secret123456",
        require_content=True,
        require_reasoning=True,
        expect_finish_reasons=["stop"],
    )

    assert requests[0]["stream"] is True
    assert summary["ok"] is True
    assert summary["content_chars"] == len("final message")
    assert summary["reasoning_chars"] == len(private_reasoning)
    assert summary["finish_reasons"] == ["stop"]
    assert private_reasoning not in json.dumps(summary)


def test_stream_smoke_accepts_content_part_arrays(monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b'data: {"choices":[{"delta":{"content":'
                b'[{"type":"text","text":{"value":"content-part "}}]}}]}\n\n'
            )
            yield (
                b'data: {"choices":[{"message":{"role":"assistant","content":'
                b'[{"type":"text","text":{"value":"smoke output"}}]},"finish_reason":"stop"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-content-part-model",
        api_key="sk-stream-smoke-secret123456",
        require_content=True,
        expect_finish_reasons=["stop"],
    )

    assert requests[0]["stream"] is True
    assert summary["ok"] is True
    assert summary["content_chars"] == len("content-part smoke output")
    assert summary["finish_reasons"] == ["stop"]
    assert "content-part smoke output" not in json.dumps(summary)


def test_stream_smoke_counts_reasoning_content_parts_without_visible_leak(monkeypatch):
    requests: list[dict] = []
    private_reasoning = "hidden planhidden thought"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b'data: {"choices":[{"delta":{"content":'
                b'[{"type":"reasoning","text":{"value":"hidden plan"}},'
                b'{"type":"text","text":{"value":"visible "}}]}}]}\n\n'
            )
            yield (
                b'data: {"choices":[{"message":{"role":"assistant","content":'
                b'[{"type":"thinking","text":{"value":"hidden thought"}},'
                b'{"type":"text","text":{"value":"answer"}}]},"finish_reason":"stop"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-reasoning-content-part-model",
        api_key="sk-stream-smoke-secret123456",
        require_content=True,
        require_reasoning=True,
        expect_finish_reasons=["stop"],
    )

    assert requests[0]["stream"] is True
    assert summary["ok"] is True
    assert summary["content_chars"] == len("visible answer")
    assert summary["reasoning_chars"] == len(private_reasoning)
    assert summary["finish_reasons"] == ["stop"]
    assert private_reasoning not in json.dumps(summary)
    assert "visible answer" not in json.dumps(summary)


def test_stream_smoke_keeps_multi_choice_tool_call_deltas_separate():
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_readme",
                                "type": "function",
                                "function": {
                                    "name": "workspace_",
                                    "arguments": '{"path":"READ',
                                },
                            }
                        ]
                    },
                },
                {
                    "index": 1,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_notes",
                                "type": "function",
                                "function": {
                                    "name": "workspace_",
                                    "arguments": '{"path":"NOT',
                                },
                            }
                        ]
                    },
                },
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "name": "read",
                                    "arguments": 'ME.md"}',
                                },
                            }
                        ]
                    },
                },
                {
                    "index": 1,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "name": "read",
                                    "arguments": 'ES.md"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                },
            ]
        },
    ]

    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["tool_call_delta_count"] == 4
    assert summary["tool_call_count"] == 2
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_calls"] == [
        {
            "id": "call_readme",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
            "arguments": '{"path":"README.md"}',
        },
        {
            "id": "call_notes",
            "name": "workspace_read",
            "argument_chars": len('{"path":"NOTES.md"}'),
            "arguments": '{"path":"NOTES.md"}',
        },
    ]


def test_stream_smoke_coalesces_indexless_tool_call_deltas():
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_indexless_read",
                                "type": "function",
                                "function": {
                                    "name": "workspace_",
                                    "arguments": '{"path":"READ',
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "read",
                                    "arguments": 'ME.md"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["tool_call_delta_count"] == 2
    assert summary["tool_call_count"] == 1
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_calls"] == [
        {
            "id": "call_indexless_read",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
            "arguments": '{"path":"README.md"}',
        }
    ]


def test_stream_smoke_coalesces_indexless_interleaved_tool_call_deltas_by_id():
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_indexless_readme",
                                "type": "function",
                                "function": {
                                    "name": "workspace_",
                                    "arguments": '{"path":"READ',
                                },
                            },
                            {
                                "id": "call_indexless_notes",
                                "type": "function",
                                "function": {
                                    "name": "workspace_",
                                    "arguments": '{"path":"NOT',
                                },
                            },
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_indexless_notes",
                                "function": {
                                    "name": "read",
                                    "arguments": 'ES.md"}',
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_indexless_readme",
                                "function": {
                                    "name": "read",
                                    "arguments": 'ME.md"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["tool_call_delta_count"] == 4
    assert summary["tool_call_count"] == 2
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_calls"] == [
        {
            "id": "call_indexless_readme",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
            "arguments": '{"path":"README.md"}',
        },
        {
            "id": "call_indexless_notes",
            "name": "workspace_read",
            "argument_chars": len('{"path":"NOTES.md"}'),
            "arguments": '{"path":"NOTES.md"}',
        },
    ]


def test_stream_smoke_summarizes_message_level_tool_calls():
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_message_read",
                                "type": "function",
                                "function": {
                                    "name": "workspace_read",
                                    "arguments": {"path": "README.md"},
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    ]

    public_summary = smoke.summarize_stream_chunks(chunks)
    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_call_delta_count"] == 1
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_message_read",
            "name": "workspace_read",
            "argument_chars": len('{"path": "README.md"}'),
            "arguments": '{"path": "README.md"}',
        }
    ]
    assert "README.md" not in json.dumps(public_summary)


def test_stream_smoke_summarizes_top_level_delta_and_message_tool_calls():
    chunks = [
        {
            "delta": {
                "content": "checking ",
                "tool_calls": [
                    {
                        "id": "call_top_delta",
                        "type": "function",
                        "function": {
                            "name": "workspace_",
                            "arguments": {"path": "READ"},
                        },
                    }
                ],
            }
        },
        {
            "message": {
                "tool_calls": [
                    {
                        "id": "call_top_delta",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": "ME.md",
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        },
        {"message": {"content": "done"}, "stop_reason": "stop"},
    ]

    public_summary = smoke.summarize_stream_chunks(chunks)
    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["content_chars"] == len("checking done")
    assert summary["finish_reasons"] == ["tool_calls", "stop"]
    assert summary["tool_call_delta_count"] == 2
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_top_delta",
            "name": "workspace_read",
            "argument_chars": len('{"path": "READ"}ME.md'),
            "arguments": '{"path": "READ"}ME.md',
        }
    ]
    assert "README.md" not in json.dumps(public_summary)


def test_stream_smoke_summarizes_singular_tool_call_frames():
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_call": {
                            "index": 0,
                            "id": "call_singular_delta",
                            "type": "function",
                            "function": {
                                "name": "workspace_",
                                "arguments": '{"path":"READ',
                            },
                        }
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "tool_call": {
                            "index": 0,
                            "function": {
                                "name": "read",
                                "arguments": 'ME.md"}',
                            },
                        }
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    public_summary = smoke.summarize_stream_chunks(chunks)
    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_call_delta_count"] == 2
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_singular_delta",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
            "arguments": '{"path":"README.md"}',
        }
    ]
    assert "README.md" not in json.dumps(public_summary)


def test_stream_smoke_summarizes_responses_style_tool_call_chunks():
    chunks = [
        {"type": "response.output_text.delta", "delta": "checking responses "},
        {
            "type": "response.output_item.added",
            "item": {
                "id": "fc_response_read",
                "type": "function_call",
                "call_id": "call_response_read",
                "name": "workspace_read",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_response_read",
            "delta": '{"path": "READ',
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_response_read",
            "delta": 'ME.md"}',
        },
        {
            "type": "response.output_item.done",
            "item": {
                "id": "fc_response_read",
                "type": "function_call",
                "call_id": "call_response_read",
                "name": "workspace_read",
                "arguments": {"path": "README.md"},
            },
        },
        {"type": "response.completed", "response": {"status": "completed"}},
    ]

    public_summary = smoke.summarize_stream_chunks(chunks)
    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["content_chars"] == len("checking responses ")
    assert summary["finish_reasons"] == ["completed"]
    assert summary["tool_call_delta_count"] == 4
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_response_read",
            "name": "workspace_read",
            "argument_chars": len('{"path": "README.md"}'),
            "arguments": '{"path": "README.md"}',
        }
    ]
    assert "README.md" not in json.dumps(public_summary)


def test_stream_smoke_parses_responses_style_sse_transport_without_leaking_arguments(monkeypatch):
    requests: list[dict] = []
    leaked_secret = "sk-stream-responses-secret123456"

    def event(payload: dict) -> bytes:
        event_type = str(payload.get("type") or "")
        return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n".encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield event({"type": "response.output_text.delta", "delta": "checking responses "})
            yield event(
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "id": "fc_response_read",
                        "type": "function_call",
                        "call_id": "call_response_read",
                        "name": "workspace_read",
                        "arguments": "",
                    },
                }
            )
            yield event(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_response_read",
                    "delta": '{"path": "READ',
                }
            )
            yield event(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_response_read",
                    "delta": 'ME.md"}',
                }
            )
            yield event(
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_response_read",
                    "arguments": {"path": "README.md"},
                }
            )
            yield event(
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": "fc_response_read",
                        "type": "function_call",
                        "call_id": "call_response_read",
                        "name": "workspace_read",
                        "arguments": {"path": "README.md"},
                    },
                }
            )
            yield event({"type": "response.completed", "response": {"status": "completed"}})

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-responses-model",
        api_key=leaked_secret,
        require_content=True,
        require_tool_call=True,
        expect_tool_name="workspace_read",
        expect_tool_argument_substrings=["README.md"],
        expect_tool_argument_json_fields=["path=README.md"],
        expect_finish_reasons=["completed"],
    )

    summary_json = json.dumps(summary)
    assert requests[0]["stream"] is True
    assert requests[0]["tools"][0]["function"]["name"] == "workspace_read"
    assert summary["ok"] is True
    assert summary["content_chars"] == len("checking responses ")
    assert summary["finish_reasons"] == ["completed"]
    assert summary["tool_call_delta_count"] == 5
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_response_read",
            "name": "workspace_read",
            "argument_chars": len('{"path": "README.md"}'),
        }
    ]
    assert leaked_secret not in summary_json
    assert "README.md" not in summary_json


def test_stream_smoke_accepts_sse_delta_tool_call_object_arguments_without_leaking(monkeypatch):
    requests: list[dict] = []
    leaked_secret = "sk-stream-object-args-secret123456"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_object_args",'
                b'"type":"function","function":{"name":"workspace_read","arguments":{"path":"README.md"}}}]},'
                b'"finish_reason":"tool_calls"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key=leaked_secret,
        require_tool_call=True,
        expect_tool_name="workspace_read",
        expect_tool_argument_substrings=["README.md"],
        expect_tool_argument_json_fields=["path=README.md"],
        expect_finish_reasons=["tool_calls"],
    )

    summary_json = json.dumps(summary)
    assert requests[0]["stream"] is True
    assert summary["ok"] is True
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_call_delta_count"] == 1
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_object_args",
            "name": "workspace_read",
            "argument_chars": len('{"path": "README.md"}'),
        }
    ]
    assert leaked_secret not in summary_json
    assert "README.md" not in summary_json


def test_stream_smoke_summarizes_legacy_function_call_deltas():
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "function_call": {
                            "name": "workspace_",
                            "arguments": '{"path":"READ',
                        }
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "function_call": {
                            "name": "read",
                            "arguments": 'ME.md"}',
                        }
                    },
                    "finish_reason": "function_call",
                }
            ]
        },
    ]

    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["finish_reasons"] == ["function_call"]
    assert summary["tool_call_delta_count"] == 2
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
            "arguments": '{"path":"README.md"}',
        }
    ]


def test_stream_smoke_summarizes_openai_sdk_object_tool_call_deltas():
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    index=0,
                    delta=SimpleNamespace(
                        content="checking ",
                        reasoning_content="private plan ",
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_sdk_read",
                                type="function",
                                function=SimpleNamespace(
                                    name="workspace_",
                                    arguments='{"path":"READ',
                                ),
                            )
                        ],
                    ),
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    index=0,
                    delta=SimpleNamespace(
                        reasoning="kept private",
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                function=SimpleNamespace(
                                    name="read",
                                    arguments='ME.md"}',
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ]
        ),
    ]

    summary = smoke.summarize_stream_chunks(chunks, include_tool_arguments=True)

    assert summary["ok"] is True
    assert summary["content_chars"] == len("checking ")
    assert summary["reasoning_chars"] == len("private plan kept private")
    assert summary["finish_reasons"] == ["tool_calls"]
    assert summary["tool_call_delta_count"] == 2
    assert summary["tool_call_count"] == 1
    assert summary["tool_calls"] == [
        {
            "id": "call_sdk_read",
            "name": "workspace_read",
            "argument_chars": len('{"path":"README.md"}'),
            "arguments": '{"path":"README.md"}',
        }
    ]


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

    with pytest.raises(RuntimeError, match="expected tool call JSON argument field"):
        smoke.run_stream_smoke(
            base_url="https://api.example.test/v1",
            model="demo-model",
            api_key="sk-stream-smoke-secret123456",
            tool_call=True,
            expect_tool_argument_json_fields=["path=README.md"],
        )


def test_stream_smoke_requires_expected_finish_reason(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(
        "apps.shell.model_profiles.urlrequest.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    summary = smoke.run_stream_smoke(
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key="sk-stream-smoke-secret123456",
        require_content=True,
        expect_finish_reasons=["stop"],
    )

    assert summary["ok"] is True
    assert summary["finish_reasons"] == ["stop"]

    with pytest.raises(RuntimeError, match="expected finish_reason 'tool_calls'"):
        smoke.run_stream_smoke(
            base_url="https://api.example.test/v1",
            model="demo-model",
            api_key="sk-stream-smoke-secret123456",
            expect_finish_reasons=["tool_calls"],
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
            "--require-reasoning",
            "--expect-tool-name",
            "workspace_read",
            "--expect-tool-argument-substring",
            "README.md",
            "--expect-tool-argument-json-field",
            "path=README.md",
            "--expect-finish-reason",
            "tool_calls",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls[0]["tool_call"] is True
    assert calls[0]["require_content"] is True
    assert calls[0]["require_reasoning"] is True
    assert calls[0]["expect_tool_name"] == "workspace_read"
    assert calls[0]["expect_tool_argument_substrings"] == ["README.md"]
    assert calls[0]["expect_tool_argument_json_fields"] == ["path=README.md"]
    assert calls[0]["expect_finish_reasons"] == ["tool_calls"]
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
