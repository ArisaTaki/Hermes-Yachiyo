"""Tests for model message parsing split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime import model_messages


def test_model_message_helpers_remain_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime._ModelOutputText is model_messages.ModelOutputText
    assert agent_runtime._message_field is model_messages.message_field
    assert agent_runtime._model_message_metadata is model_messages.model_message_metadata
    assert agent_runtime._model_output_metadata is model_messages.model_output_metadata
    assert agent_runtime._message_visible_content_text is model_messages.message_visible_content_text
    assert agent_runtime._responses_stream_text_delta is model_messages.responses_stream_text_delta
    assert agent_runtime._responses_stream_tool_call is model_messages.responses_stream_tool_call
    assert agent_runtime._stream_chunk_tool_calls is model_messages.stream_chunk_tool_calls
    assert agent_runtime._merge_stream_tool_call_delta is model_messages.merge_stream_tool_call_delta
    assert agent_runtime._coalesced_stream_tool_calls is model_messages.coalesced_stream_tool_calls
    assert agent_runtime._coerce_tool_call is model_messages.coerce_tool_call
    assert agent_runtime._coalesce_model_message is model_messages.coalesce_model_message


def test_model_message_helpers_parse_responses_stream_text_and_tool_calls() -> None:
    text_delta = {
        "type": "response.output_text.delta",
        "delta": {"text": "hello"},
    }
    text_done = {
        "type": "response.output_text.done",
        "text": {"value": "hello world"},
    }
    tool_item = {
        "type": "response.output_item.done",
        "output_index": 2,
        "item": {
            "type": "function_call",
            "id": "item-1",
            "call_id": "call-1",
            "name": "workspace.read",
            "arguments": "{\"path\":\"README.md\"}",
        },
    }

    assert model_messages.responses_stream_text_delta(text_delta) == "hello"
    assert model_messages.responses_stream_text_done(text_done) == "hello world"
    assert model_messages.responses_stream_tool_call(tool_item) == {
        "index": 2,
        "id": "item-1",
        "item_id": "item-1",
        "call_id": "call-1",
        "type": "function",
        "function": {
            "name": "workspace.read",
            "arguments": "{\"path\":\"README.md\"}",
        },
        "_snapshot": True,
    }


def test_model_output_text_carries_metadata_for_runtime_events() -> None:
    output = model_messages.ModelOutputText(
        "truncated",
        metadata={"usage": {"total_tokens": 12}},
        truncated=True,
    )

    assert output == "truncated"
    assert model_messages.model_output_metadata(output) == {"usage": {"total_tokens": 12}}
    assert output.output_truncated is True
    assert model_messages.model_output_completed_payload(
        str(output),
        truncated=output.output_truncated,
        metadata=model_messages.model_output_metadata(output),
    ) == {
        "content": "truncated",
        "output_chars": 9,
        "truncated": True,
        "usage": {"total_tokens": 12},
    }


def test_model_message_helpers_coalesce_streaming_text_and_tool_calls() -> None:
    message = model_messages.coalesce_model_message([
        {"type": "response.output_text.delta", "delta": "Read "},
        {"type": "response.output_text.delta", "delta": "the file"},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "id": "item-1",
                "call_id": "call-1",
                "name": "workspace.read",
                "arguments": "{\"path\":\"README.md\"}",
            },
        },
        {"usage": {"total_tokens": "21"}, "finish_reason": "tool_calls"},
    ])

    assert message == {
        "role": "assistant",
        "content": "Read the file",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "workspace.read",
                    "arguments": "{\"path\":\"README.md\"}",
                },
            }
        ],
        "finish_reason": "tool_calls",
        "usage": {"total_tokens": 21},
    }
