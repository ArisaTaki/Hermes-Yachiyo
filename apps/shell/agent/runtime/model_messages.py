"""Model message and stream chunk normalization helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable as IterableABC
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


def stream_chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    if responses_stream_is_reasoning_event(chunk):
        return ""
    responses_text = responses_stream_text_delta(chunk)
    if responses_text is not None:
        return responses_text
    choices = message_field(chunk, "choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            delta = message_field(choice, "delta")
            if delta is not None:
                parts.append(message_visible_content_text(delta))
            message = message_field(choice, "message")
            if message is not None:
                parts.append(message_visible_content_text(message))
            text = message_field(choice, "text")
            if text is not None:
                parts.append(str(text))
        if parts:
            return "".join(parts)
    delta = message_field(chunk, "delta")
    if delta is not None:
        return message_visible_content_text(delta)
    return message_visible_content_text(chunk)


def stream_choice_index(choice: Any, fallback: int) -> int:
    try:
        value = message_field(choice, "index")
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def stream_chunk_tool_calls(chunk: Any) -> list[tuple[int, int, Any]]:
    responses_call = responses_stream_tool_call(chunk)
    if responses_call is not None:
        return [(0, stream_choice_index(responses_call, 0), responses_call)]
    direct = message_field(chunk, "tool_calls")
    if isinstance(direct, list):
        return [(0, index, call) for index, call in enumerate(direct)]
    direct_single = message_field(chunk, "tool_call")
    if direct_single is not None:
        return [(0, 0, direct_single)]
    direct_function = message_field(chunk, "function_call")
    if direct_function is not None:
        return [(0, 0, {"index": 0, "type": "function", "function": direct_function})]
    for field_name in ("delta", "message"):
        value = message_field(chunk, field_name)
        if value is None:
            continue
        calls = message_field(value, "tool_calls")
        if isinstance(calls, list):
            return [(0, index, call) for index, call in enumerate(calls)]
        single_call = message_field(value, "tool_call")
        if single_call is not None:
            return [(0, 0, single_call)]
        function_call = message_field(value, "function_call")
        if function_call is not None:
            return [(0, 0, {"index": 0, "type": "function", "function": function_call})]
    choices = message_field(chunk, "choices")
    if not isinstance(choices, list):
        return []
    calls: list[tuple[int, int, Any]] = []
    for choice_position, choice in enumerate(choices):
        choice_index = stream_choice_index(choice, choice_position)
        delta = message_field(choice, "delta")
        if delta is not None:
            delta_calls = message_field(delta, "tool_calls")
            if isinstance(delta_calls, list):
                calls.extend((choice_index, index, call) for index, call in enumerate(delta_calls))
            delta_single_call = message_field(delta, "tool_call")
            if delta_single_call is not None:
                calls.append((choice_index, 0, delta_single_call))
            delta_function = message_field(delta, "function_call")
            if delta_function is not None:
                calls.append((choice_index, 0, {"index": 0, "type": "function", "function": delta_function}))
        message = message_field(choice, "message")
        if message is not None:
            message_calls = message_field(message, "tool_calls")
            if isinstance(message_calls, list):
                calls.extend((choice_index, index, call) for index, call in enumerate(message_calls))
            message_single_call = message_field(message, "tool_call")
            if message_single_call is not None:
                calls.append((choice_index, 0, message_single_call))
            message_function = message_field(message, "function_call")
            if message_function is not None:
                calls.append((choice_index, 0, {"index": 0, "type": "function", "function": message_function}))
    return calls


def merge_stream_tool_call_delta(
    accumulator: dict[tuple[int, int], dict[str, Any]],
    raw_call: Any,
    choice_index: int,
    fallback_index: int,
) -> None:
    if raw_call is None:
        return
    raw_index = message_field(raw_call, "index")
    try:
        index = int(raw_index) if raw_index is not None else fallback_index
    except (TypeError, ValueError):
        index = fallback_index
    call_id = message_field(raw_call, "id")
    item_id = message_field(raw_call, "item_id")
    response_call_id = message_field(raw_call, "call_id")
    match_ids = {str(value) for value in (call_id, item_id, response_call_id) if value}
    key = (choice_index, index)
    if match_ids:
        for existing_key, existing in accumulator.items():
            existing_ids = {
                str(value)
                for value in (existing.get("id"), existing.get("item_id"), existing.get("call_id"))
                if value
            }
            if existing_key[0] == choice_index and match_ids.intersection(existing_ids):
                key = existing_key
                break
        else:
            existing = accumulator.get(key)
            has_distinct_id = False
            if raw_index is None and existing:
                existing_ids = {
                    str(value)
                    for value in (existing.get("id"), existing.get("item_id"), existing.get("call_id"))
                    if value
                }
                has_distinct_id = bool(existing_ids and not match_ids.intersection(existing_ids))
            if raw_index is None and existing and has_distinct_id:
                occupied = {tool_index for existing_choice, tool_index in accumulator if existing_choice == choice_index}
                while index in occupied:
                    index += 1
                key = (choice_index, index)
    entry = accumulator.setdefault(key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    if item_id:
        entry["item_id"] = str(item_id)
    if response_call_id:
        entry["call_id"] = str(response_call_id)
    preferred_id = response_call_id or call_id or item_id
    if preferred_id:
        entry["id"] = str(preferred_id)
    call_type = message_field(raw_call, "type")
    if call_type:
        entry["type"] = str(call_type)
    raw_function = message_field(raw_call, "function")
    if raw_function is None:
        return
    function = entry.setdefault("function", {"name": "", "arguments": ""})
    snapshot = bool(message_field(raw_call, "_snapshot"))
    name = message_field(raw_function, "name")
    if name:
        function["name"] = str(name) if snapshot else f"{function.get('name') or ''}{name}"
    arguments = message_field(raw_function, "arguments")
    if arguments or snapshot:
        arguments_text = tool_arguments_text(arguments)
        function["arguments"] = arguments_text if snapshot else f"{function.get('arguments') or ''}{arguments_text}"


def coalesced_stream_tool_calls(accumulator: dict[tuple[int, int], dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for choice_index, tool_index in sorted(accumulator):
        call = accumulator[(choice_index, tool_index)]
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        calls.append(
            {
                "id": str(call.get("id") or f"call_{choice_index}_{tool_index}"),
                "type": str(call.get("type") or "function"),
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or ""),
                },
            }
        )
    return calls


def coerce_tool_call(value: Any, index: int) -> dict[str, Any] | None:
    if value is None:
        return None
    raw_function = message_field(value, "function")
    function_name = message_field(raw_function, "name") if raw_function is not None else ""
    if not function_name:
        return None
    arguments = message_field(raw_function, "arguments")
    return {
        "id": str(message_field(value, "id") or f"call_{index}"),
        "type": str(message_field(value, "type") or "function"),
        "function": {
            "name": str(function_name),
            "arguments": tool_arguments_text(arguments) if arguments is not None else "{}",
        },
    }


def coerce_tool_calls(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    calls: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        call = coerce_tool_call(item, index)
        if call is not None:
            calls.append(call)
    return calls


def coerce_function_call(value: Any, index: int = 0) -> dict[str, Any] | None:
    if value is None:
        return None
    name = message_field(value, "name")
    if not name:
        return None
    arguments = message_field(value, "arguments")
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {
            "name": str(name),
            "arguments": tool_arguments_text(arguments) if arguments is not None else "{}",
        },
    }


def coalesce_model_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        tool_calls = coerce_tool_calls(message.get("tool_calls"))
        if tool_calls is not None:
            return {**message, "tool_calls": tool_calls}
        tool_call = coerce_tool_call(message.get("tool_call"), 0)
        if tool_call is not None:
            return {**message, "tool_calls": [tool_call]}
        function_call = coerce_function_call(message.get("function_call"))
        return {**message, "tool_calls": [function_call]} if function_call is not None else message
    if isinstance(message, str):
        return {"role": "assistant", "content": message}
    if not isinstance(message, IterableABC):
        result = {"role": "assistant", "content": message_visible_content_text(message)}
        tool_calls = coerce_tool_calls(message_field(message, "tool_calls"))
        if tool_calls is not None:
            result["tool_calls"] = tool_calls
        else:
            tool_call = coerce_tool_call(message_field(message, "tool_call"), 0)
            if tool_call is not None:
                result["tool_calls"] = [tool_call]
            else:
                function_call = coerce_function_call(message_field(message, "function_call"))
                if function_call is not None:
                    result["tool_calls"] = [function_call]
        return result

    content_parts: list[str] = []
    responses_text_order: list[tuple[int, int]] = []
    responses_text_deltas: dict[tuple[int, int], list[str]] = {}
    responses_text_done: dict[tuple[int, int], str] = {}
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_deltas: dict[tuple[int, int], dict[str, Any]] = {}
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    for chunk in message:
        if responses_stream_is_reasoning_event(chunk):
            continue
        chunk_finish_reason = stream_chunk_finish_reason(chunk)
        if chunk_finish_reason:
            finish_reason = chunk_finish_reason
        chunk_usage = stream_chunk_usage(chunk)
        if chunk_usage is not None:
            usage = chunk_usage
        responses_delta = responses_stream_text_delta(chunk)
        responses_done = responses_stream_text_done(chunk)
        if responses_delta is not None or responses_done is not None:
            key = responses_stream_text_key(chunk)
            if key not in responses_text_order:
                responses_text_order.append(key)
            if responses_delta:
                responses_text_deltas.setdefault(key, []).append(responses_delta)
            if responses_done is not None:
                responses_text_done[key] = responses_done
        else:
            content = stream_chunk_text(chunk)
            if content:
                content_parts.append(content)
        chunk_tool_calls = stream_chunk_tool_calls(chunk)
        if isinstance(chunk_tool_calls, list):
            for choice_index, fallback_index, call in chunk_tool_calls:
                merge_stream_tool_call_delta(tool_call_deltas, call, choice_index, fallback_index)

    for key in responses_text_order:
        content_parts.append(responses_text_done.get(key) or "".join(responses_text_deltas.get(key, [])))

    result: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_call_deltas:
        tool_calls = coalesced_stream_tool_calls(tool_call_deltas)
    if tool_calls is not None:
        result["tool_calls"] = tool_calls
    if finish_reason:
        result["finish_reason"] = finish_reason
    if usage is not None:
        result["usage"] = usage
    return result
