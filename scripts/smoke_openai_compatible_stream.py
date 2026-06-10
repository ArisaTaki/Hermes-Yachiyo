"""Opt-in smoke test for OpenAI-compatible streaming providers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.shell.model_profiles import openai_compatible_chat_message
from packages.security import redact_api_error_text

BASE_URL_ENV = "OHA_YACHIYO_SMOKE_BASE_URL"
MODEL_ENV = "OHA_YACHIYO_SMOKE_MODEL"
API_KEY_ENV = "OHA_YACHIYO_SMOKE_API_KEY"


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return getattr(value, name, None)


def _content_part_type(value: Any) -> str:
    return str(_field(value, "type") or "").strip().lower()


def _is_reasoning_content_part(value: Any) -> bool:
    return _content_part_type(value) in {"reasoning", "reasoning_content", "thinking", "thought"}


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := _text_value(item)))
    if isinstance(value, dict):
        for key in ("value", "content", "text"):
            nested = value.get(key)
            if nested is not None:
                text = _text_value(nested)
                if text:
                    return text
        return ""
    for field_name in ("value", "content", "text"):
        nested = _field(value, field_name)
        if nested is not None:
            text = _text_value(nested)
            if text:
                return text
    return str(value) if value is not None else ""


def _raw_part_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := _raw_part_text(item)))
    nested = _field(value, "content")
    if nested is not None:
        text = _raw_part_text(nested)
        if text:
            return text
    text = _field(value, "text")
    return _text_value(text)


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if _is_reasoning_content_part(item):
                continue
            text = _content_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if _is_reasoning_content_part(value):
        return ""
    nested = _field(value, "content")
    if nested is not None:
        text = _content_text(nested)
        if text:
            return text
    text = _field(value, "text")
    return _text_value(text)


def _reasoning_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(_reasoning_text(item) for item in value)
    if _is_reasoning_content_part(value):
        return _raw_part_text(value)
    reasoning = _field(value, "reasoning_content")
    if reasoning is None:
        reasoning = _field(value, "reasoning")
    if reasoning is None:
        content = _field(value, "content")
        if content is not None:
            return _reasoning_text(content)
    return str(reasoning) if reasoning else ""


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    choices = _field(chunk, "choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            for field_name in ("delta", "message"):
                value = _field(choice, field_name)
                if value is not None:
                    text = _content_text(value)
                    if text:
                        parts.append(text)
            text = _field(choice, "text")
            if text is not None:
                parts.append(str(text))
        if parts:
            return "".join(parts)
    for field_name in ("delta", "message"):
        value = _field(chunk, field_name)
        if value is not None:
            text = _content_text(value)
            if text:
                return text
    return _content_text(chunk)


def _chunk_reasoning_text(chunk: Any) -> str:
    choices = _field(chunk, "choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            for field_name in ("delta", "message"):
                value = _field(choice, field_name)
                if value is not None:
                    reasoning = _reasoning_text(value)
                    if reasoning:
                        parts.append(reasoning)
            reasoning = _reasoning_text(choice)
            if reasoning:
                parts.append(reasoning)
        return "".join(parts)
    for field_name in ("delta", "message"):
        value = _field(chunk, field_name)
        if value is not None:
            reasoning = _reasoning_text(value)
            if reasoning:
                return reasoning
    return _reasoning_text(chunk)


def _normalized_index(value: Any, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _chunk_tool_calls(chunk: Any) -> list[tuple[int, int, Any]]:
    choices = _field(chunk, "choices")
    direct = _field(chunk, "tool_calls")
    if isinstance(direct, list):
        return [(0, index, call) for index, call in enumerate(direct)]
    direct_function = _field(chunk, "function_call")
    if direct_function is not None:
        return [(0, 0, {"index": 0, "type": "function", "function": direct_function})]
    if not isinstance(choices, list):
        return []
    calls: list[tuple[int, int, Any]] = []
    for choice_position, choice in enumerate(choices):
        choice_index = _normalized_index(_field(choice, "index"), choice_position)
        delta = _field(choice, "delta")
        delta_calls = _field(delta, "tool_calls") if delta is not None else None
        if isinstance(delta_calls, list):
            calls.extend((choice_index, index, call) for index, call in enumerate(delta_calls))
        delta_function = _field(delta, "function_call") if delta is not None else None
        if delta_function is not None:
            calls.append((choice_index, 0, {"index": 0, "type": "function", "function": delta_function}))
        message = _field(choice, "message")
        message_calls = _field(message, "tool_calls") if message is not None else None
        if isinstance(message_calls, list):
            calls.extend((choice_index, index, call) for index, call in enumerate(message_calls))
        message_function = _field(message, "function_call") if message is not None else None
        if message_function is not None:
            calls.append((choice_index, 0, {"index": 0, "type": "function", "function": message_function}))
    return calls


def _chunk_finish_reasons(chunk: Any) -> list[str]:
    choices = _field(chunk, "choices")
    if not isinstance(choices, list):
        return []
    reasons: list[str] = []
    for choice in choices:
        reason = _field(choice, "finish_reason")
        if reason:
            reasons.append(str(reason))
    return reasons


def _merge_tool_delta(
    accumulator: dict[tuple[int, int], dict[str, Any]],
    raw_call: Any,
    choice_index: int,
    fallback_index: int,
) -> None:
    raw_index = _field(raw_call, "index")
    index = _normalized_index(raw_index, fallback_index)
    call_id = _field(raw_call, "id")
    key = (choice_index, index)
    if call_id:
        call_id_text = str(call_id)
        for existing_key, existing in accumulator.items():
            if existing_key[0] == choice_index and str(existing.get("id") or "") == call_id_text:
                key = existing_key
                break
        else:
            existing = accumulator.get(key)
            if raw_index is None and existing and str(existing.get("id") or "") not in {"", call_id_text}:
                occupied = {tool_index for existing_choice, tool_index in accumulator if existing_choice == choice_index}
                while index in occupied:
                    index += 1
                key = (choice_index, index)
    entry = accumulator.setdefault(key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    if call_id:
        entry["id"] = str(call_id)
    call_type = _field(raw_call, "type")
    if call_type:
        entry["type"] = str(call_type)
    function_delta = _field(raw_call, "function")
    if function_delta is None:
        return
    function = entry.setdefault("function", {"name": "", "arguments": ""})
    name = _field(function_delta, "name")
    if name:
        function["name"] = f"{function.get('name') or ''}{name}"
    arguments = _field(function_delta, "arguments")
    if arguments:
        function["arguments"] = f"{function.get('arguments') or ''}{arguments}"


def summarize_stream_chunks(
    chunks: Iterable[dict[str, Any]],
    *,
    include_tool_arguments: bool = False,
) -> dict[str, Any]:
    chunk_count = 0
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reasons: list[str] = []
    tool_deltas: dict[tuple[int, int], dict[str, Any]] = {}
    tool_delta_count = 0
    for chunk in chunks:
        chunk_count += 1
        content = _chunk_text(chunk)
        if content:
            content_parts.append(content)
        reasoning = _chunk_reasoning_text(chunk)
        if reasoning:
            reasoning_parts.append(reasoning)
        finish_reasons.extend(_chunk_finish_reasons(chunk))
        calls = _chunk_tool_calls(chunk)
        tool_delta_count += len(calls)
        for choice_index, fallback_index, call in calls:
            _merge_tool_delta(tool_deltas, call, choice_index, fallback_index)

    tool_calls = [tool_deltas[index] for index in sorted(tool_deltas)]
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    tool_call_summaries: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") or {}
        item = {
            "id": str(call.get("id") or ""),
            "name": str(function.get("name") or ""),
            "argument_chars": len(str(function.get("arguments") or "")),
        }
        if include_tool_arguments:
            item["arguments"] = str(function.get("arguments") or "")
        tool_call_summaries.append(item)

    return {
        "ok": chunk_count > 0 and (bool(content) or bool(reasoning) or bool(tool_calls)),
        "chunk_count": chunk_count,
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
        "finish_reasons": finish_reasons,
        "tool_call_delta_count": tool_delta_count,
        "tool_call_count": len(tool_calls),
        "tool_calls": tool_call_summaries,
    }


def _workspace_read_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "workspace_read",
            "description": "Read a workspace file for provider streaming smoke validation.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }


def run_stream_smoke(
    *,
    base_url: str,
    model: str,
    api_key: str,
    prompt: str = "",
    tool_call: bool = False,
    require_tool_call: bool = False,
    require_content: bool = False,
    require_reasoning: bool = False,
    expect_tool_name: str = "",
    expect_tool_argument_substrings: Iterable[str] | None = None,
    expect_finish_reasons: Iterable[str] | None = None,
) -> dict[str, Any]:
    base_url = str(base_url or "").strip()
    model = str(model or "").strip()
    api_key = str(api_key or "").strip()
    missing = [
        name
        for name, value in (
            ("base URL", base_url),
            ("model", model),
            ("API key", api_key),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing {', '.join(missing)}")

    expected_name = str(expect_tool_name or "").strip()
    expected_argument_substrings = [
        str(value).strip()
        for value in (expect_tool_argument_substrings or [])
        if str(value or "").strip()
    ]
    expected_finish_reasons = [
        str(value).strip()
        for value in (expect_finish_reasons or [])
        if str(value or "").strip()
    ]
    tool_call = tool_call or require_tool_call or bool(expected_name) or bool(expected_argument_substrings)
    if not prompt:
        prompt = (
            "Call workspace_read with path README.md, then stream a short answer."
            if tool_call
            else "Stream a short one-sentence reply."
        )
    chunks = openai_compatible_chat_message(
        base_url,
        model,
        api_key,
        [{"role": "user", "content": prompt}],
        tools=[_workspace_read_tool()] if tool_call else None,
        stream=True,
    )
    summary = summarize_stream_chunks(
        chunks if not isinstance(chunks, dict) else [],
        include_tool_arguments=bool(expected_argument_substrings),
    )
    if require_content and int(summary["content_chars"]) == 0:
        raise RuntimeError("stream completed without content")
    if require_reasoning and int(summary["reasoning_chars"]) == 0:
        raise RuntimeError("stream completed without reasoning")
    if require_tool_call and summary["tool_call_count"] == 0:
        raise RuntimeError("stream completed without a tool call")
    if expected_name:
        names = {str(call.get("name") or "") for call in summary["tool_calls"]}
        if expected_name not in names:
            raise RuntimeError(f"stream completed without expected tool call {expected_name!r}")
    if expected_argument_substrings:
        arguments = [str(call.get("arguments") or "") for call in summary["tool_calls"]]
        for expected_argument in expected_argument_substrings:
            if not any(expected_argument in argument for argument in arguments):
                raise RuntimeError("stream completed without expected tool call argument substring")
        for call in summary["tool_calls"]:
            call.pop("arguments", None)
    if expected_finish_reasons:
        finish_reasons = {str(reason) for reason in summary["finish_reasons"]}
        for expected_reason in expected_finish_reasons:
            if expected_reason not in finish_reasons:
                raise RuntimeError(f"stream completed without expected finish_reason {expected_reason!r}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an opt-in OpenAI-compatible streaming smoke test without printing secrets."
    )
    parser.add_argument("--base-url", default=os.getenv(BASE_URL_ENV, ""), help=f"Provider base URL, or {BASE_URL_ENV}.")
    parser.add_argument("--model", default=os.getenv(MODEL_ENV, ""), help=f"Model name, or {MODEL_ENV}.")
    parser.add_argument("--api-key", default=os.getenv(API_KEY_ENV, ""), help=f"API key, or {API_KEY_ENV}.")
    parser.add_argument("--prompt", default="", help="Optional user prompt for the smoke call.")
    parser.add_argument("--tool-call", action="store_true", help="Ask the provider to stream a workspace_read tool call.")
    parser.add_argument("--require-content", action="store_true", help="Fail if the provider streams no text content.")
    parser.add_argument("--require-reasoning", action="store_true", help="Fail if the provider streams no reasoning_content.")
    parser.add_argument(
        "--require-tool-call",
        action="store_true",
        help="Fail if the provider streams content but does not emit a tool call.",
    )
    parser.add_argument(
        "--expect-tool-name",
        default="",
        help="Fail unless the stream emits a tool call with this function name.",
    )
    parser.add_argument(
        "--expect-tool-argument-substring",
        action="append",
        default=[],
        help="Fail unless at least one streamed tool call argument contains this substring. May be repeated.",
    )
    parser.add_argument(
        "--expect-finish-reason",
        action="append",
        default=[],
        help="Fail unless the stream emits this finish_reason. May be repeated.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_stream_smoke(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            prompt=args.prompt,
            tool_call=(
                args.tool_call
                or args.require_tool_call
                or bool(args.expect_tool_name)
                or bool(args.expect_tool_argument_substring)
            ),
            require_tool_call=args.require_tool_call,
            require_content=args.require_content,
            require_reasoning=args.require_reasoning,
            expect_tool_name=args.expect_tool_name,
            expect_tool_argument_substrings=args.expect_tool_argument_substring,
            expect_finish_reasons=args.expect_finish_reason,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(redact_api_error_text(str(exc), fallback="stream smoke failed"), file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
