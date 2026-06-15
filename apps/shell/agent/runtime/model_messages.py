"""Model message and stream chunk normalization helpers."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.agent.runtime.events import (
    model_output_completed_payload as _runtime_model_output_completed_payload,
)

_MODEL_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
)


class ModelOutputText(str):
    def __new__(
        cls,
        value: str,
        *,
        metadata: dict[str, Any] | None = None,
        truncated: bool = False,
    ) -> "ModelOutputText":
        obj = str.__new__(cls, value)
        obj.model_metadata = metadata or {}
        obj.output_truncated = truncated
        return obj


def message_field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return getattr(value, name, None)


def coerce_model_usage(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    usage: dict[str, Any] = {}
    for key in _MODEL_USAGE_KEYS:
        raw = message_field(value, key)
        if raw is None:
            continue
        try:
            usage[key] = int(raw)
        except (TypeError, ValueError):
            usage[key] = raw
    return usage or None


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def stream_chunk_usage(chunk: Any) -> dict[str, Any] | None:
    usage = coerce_model_usage(message_field(chunk, "usage"))
    if usage is not None:
        return usage
    response = message_field(chunk, "response")
    if response is not None:
        return coerce_model_usage(message_field(response, "usage"))
    return None


def stream_chunk_finish_reason(chunk: Any) -> str | None:
    direct = first_present(message_field(chunk, "finish_reason"), message_field(chunk, "stop_reason"))
    if direct:
        return str(direct)
    choices = message_field(chunk, "choices")
    if isinstance(choices, list):
        for choice in choices:
            reason = first_present(message_field(choice, "finish_reason"), message_field(choice, "stop_reason"))
            if reason:
                return str(reason)
    response = message_field(chunk, "response")
    response_reason = (
        first_present(message_field(response, "finish_reason"), message_field(response, "stop_reason"))
        if response is not None
        else None
    )
    if response_reason:
        return str(response_reason)
    output = message_field(response, "output") if response is not None else None
    if isinstance(output, list):
        for item in output:
            reason = first_present(message_field(item, "finish_reason"), message_field(item, "stop_reason"))
            if reason:
                return str(reason)
    return None


def model_message_metadata(message: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    finish_reason = first_present(message_field(message, "finish_reason"), message_field(message, "stop_reason"))
    if finish_reason:
        metadata["finish_reason"] = str(finish_reason)
    usage = coerce_model_usage(message_field(message, "usage"))
    if usage is not None:
        metadata["usage"] = usage
    return metadata


def model_output_metadata(value: Any) -> dict[str, Any]:
    metadata = getattr(value, "model_metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def model_output_completed_payload(
    content: str,
    *,
    truncated: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _runtime_model_output_completed_payload(
        content,
        truncated=truncated,
        metadata=metadata,
    )


def message_content_part_type(value: Any) -> str:
    return str(message_field(value, "type") or "").strip().lower()


def responses_stream_event_type(value: Any) -> str:
    return str(message_field(value, "type") or message_field(value, "event") or "").strip().lower()


RESPONSES_STREAM_REASONING_EVENTS = {
    "response.reasoning.delta",
    "response.reasoning.done",
    "response.reasoning_text.delta",
    "response.reasoning_text.done",
    "response.reasoning_summary_text.delta",
    "response.reasoning_summary_text.done",
    "reasoning.delta",
    "reasoning.done",
    "reasoning_text.delta",
    "reasoning_text.done",
    "reasoning_summary_text.delta",
    "reasoning_summary_text.done",
}


def responses_stream_is_reasoning_event(value: Any) -> bool:
    return responses_stream_event_type(value) in RESPONSES_STREAM_REASONING_EVENTS


def message_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(text for item in value if (text := message_text_value(item)))
    if isinstance(value, dict):
        for key in ("value", "content", "text"):
            nested = value.get(key)
            if nested is not None:
                text = message_text_value(nested)
                if text:
                    return text
        return ""
    nested = message_field(value, "value")
    if nested is not None:
        text = message_text_value(nested)
        if text:
            return text
    nested = message_field(value, "content")
    if nested is not None:
        text = message_text_value(nested)
        if text:
            return text
    nested = message_field(value, "text")
    if nested is not None:
        text = message_text_value(nested)
        if text:
            return text
    return str(value) if value is not None and not isinstance(value, set) else ""


def stream_index_value(value: Any, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def responses_stream_text_delta(chunk: Any) -> str | None:
    event_type = responses_stream_event_type(chunk)
    if event_type in {"response.output_text.delta", "output_text.delta"}:
        return message_text_value(message_field(chunk, "delta"))
    if event_type in {"response.refusal.delta", "refusal.delta"}:
        return message_text_value(message_field(chunk, "delta"))
    if event_type in {
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.added",
        "response.output_item.done",
        "function_call_arguments.delta",
        "function_call_arguments.done",
        "output_item.added",
        "output_item.done",
    }:
        return ""
    return None


def responses_stream_text_done(chunk: Any) -> str | None:
    event_type = responses_stream_event_type(chunk)
    if event_type in {
        "response.content_part.added",
        "response.content_part.done",
        "content_part.added",
        "content_part.done",
    }:
        part = message_field(chunk, "part")
        return message_visible_content_text(part)
    if event_type in {"response.output_item.added", "response.output_item.done", "output_item.added", "output_item.done"}:
        item = message_field(chunk, "item")
        item_type = message_content_part_type(item)
        if item_type == "message":
            return message_visible_content_text(item)
        return None
    if event_type not in {"response.output_text.done", "output_text.done", "response.refusal.done", "refusal.done"}:
        return None
    for field_name in ("text", "refusal", "content", "delta"):
        value = message_field(chunk, field_name)
        if value is not None:
            return message_text_value(value)
    return ""


def responses_stream_text_key(chunk: Any) -> tuple[int, int]:
    return (
        stream_index_value(message_field(chunk, "output_index"), 0),
        stream_index_value(message_field(chunk, "content_index"), 0),
    )


def responses_stream_tool_call(chunk: Any) -> dict[str, Any] | None:
    event_type = responses_stream_event_type(chunk)
    item = message_field(chunk, "item")
    snapshot = event_type in {"response.output_item.done", "output_item.done"}
    if event_type in {"response.output_item.added", "response.output_item.done", "output_item.added", "output_item.done"}:
        item_type = message_content_part_type(item)
        if item_type not in {"function_call", "tool_call"}:
            return None
        arguments = message_field(item, "arguments")
        item_id = message_field(item, "id")
        call_id = message_field(item, "call_id")
        return {
            "index": stream_index_value(first_present(message_field(chunk, "output_index"), message_field(item, "index")), 0),
            "id": str(item_id or call_id or ""),
            "item_id": str(item_id or "") if item_id else "",
            "call_id": str(call_id or "") if call_id else "",
            "type": "function",
            "function": {
                "name": str(message_field(item, "name") or ""),
                "arguments": arguments if arguments is not None else "",
            },
            "_snapshot": snapshot,
        }
    if event_type in {
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "function_call_arguments.delta",
        "function_call_arguments.done",
    }:
        arguments = message_field(chunk, "arguments")
        if arguments is None:
            arguments = message_field(chunk, "delta")
        item_id = message_field(chunk, "item_id")
        call_id = message_field(chunk, "call_id")
        return {
            "index": stream_index_value(first_present(message_field(chunk, "output_index"), message_field(chunk, "index")), 0),
            "id": str(item_id or call_id or ""),
            "item_id": str(item_id or "") if item_id else "",
            "call_id": str(call_id or "") if call_id else "",
            "type": "function",
            "function": {
                "name": str(message_field(chunk, "name") or ""),
                "arguments": arguments if arguments is not None else "",
            },
            "_snapshot": event_type.endswith(".done"),
        }
    return None


def is_reasoning_content_part(value: Any) -> bool:
    return message_content_part_type(value) in {"reasoning", "reasoning_content", "thinking", "thought"}


def tool_arguments_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def message_content_text(content: Any) -> str:
    if isinstance(content, dict):
        if is_reasoning_content_part(content):
            return ""
        nested = message_content_text(content.get("content"))
        if nested:
            return nested
        reasoning = content.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning
        text = content.get("text")
        return message_text_value(text)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if is_reasoning_content_part(item):
                continue
            text = message_content_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    nested = message_field(content, "content")
    if nested is not None:
        text = message_content_text(nested)
        if text:
            return text
    reasoning = message_field(content, "reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    text = message_field(content, "text")
    if text is not None:
        return message_text_value(text)
    return ""


def message_visible_content_text(content: Any) -> str:
    if isinstance(content, dict):
        if is_reasoning_content_part(content):
            return ""
        nested = message_visible_content_text(content.get("content"))
        if nested:
            return nested
        text = content.get("text")
        if text is not None:
            return message_text_value(text)
        return message_text_value(content.get("refusal"))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if is_reasoning_content_part(item):
                continue
            text = message_visible_content_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    nested = message_field(content, "content")
    if nested is not None:
        text = message_visible_content_text(nested)
        if text:
            return text
    text = message_field(content, "text")
    if text is not None:
        return message_text_value(text)
    refusal = message_field(content, "refusal")
    if refusal is not None:
        return message_text_value(refusal)
    return ""
