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


def _chunk_text(chunk: Any) -> str:
    choices = _field(chunk, "choices")
    if not isinstance(choices, list):
        return ""
    parts: list[str] = []
    for choice in choices:
        delta = _field(choice, "delta")
        if delta is None:
            continue
        content = _field(delta, "content")
        if content:
            parts.append(str(content))
    return "".join(parts)


def _chunk_tool_calls(chunk: Any) -> list[Any]:
    choices = _field(chunk, "choices")
    if not isinstance(choices, list):
        return []
    calls: list[Any] = []
    for choice in choices:
        delta = _field(choice, "delta")
        delta_calls = _field(delta, "tool_calls") if delta is not None else None
        if isinstance(delta_calls, list):
            calls.extend(delta_calls)
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


def _merge_tool_delta(accumulator: dict[int, dict[str, Any]], raw_call: Any, fallback_index: int) -> None:
    raw_index = _field(raw_call, "index")
    try:
        index = int(raw_index) if raw_index is not None else fallback_index
    except (TypeError, ValueError):
        index = fallback_index
    entry = accumulator.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    call_id = _field(raw_call, "id")
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


def summarize_stream_chunks(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    chunk_count = 0
    content_parts: list[str] = []
    finish_reasons: list[str] = []
    tool_deltas: dict[int, dict[str, Any]] = {}
    tool_delta_count = 0
    for chunk in chunks:
        chunk_count += 1
        content = _chunk_text(chunk)
        if content:
            content_parts.append(content)
        finish_reasons.extend(_chunk_finish_reasons(chunk))
        calls = _chunk_tool_calls(chunk)
        tool_delta_count += len(calls)
        for index, call in enumerate(calls):
            _merge_tool_delta(tool_deltas, call, index)

    tool_calls = [tool_deltas[index] for index in sorted(tool_deltas)]
    content = "".join(content_parts)
    return {
        "ok": chunk_count > 0 and (bool(content) or bool(tool_calls)),
        "chunk_count": chunk_count,
        "content_chars": len(content),
        "finish_reasons": finish_reasons,
        "tool_call_delta_count": tool_delta_count,
        "tool_call_count": len(tool_calls),
        "tool_calls": [
            {
                "id": str(call.get("id") or ""),
                "name": str((call.get("function") or {}).get("name") or ""),
                "argument_chars": len(str((call.get("function") or {}).get("arguments") or "")),
            }
            for call in tool_calls
        ],
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
    summary = summarize_stream_chunks(chunks if not isinstance(chunks, dict) else [])
    if require_tool_call and summary["tool_call_count"] == 0:
        raise RuntimeError("stream completed without a tool call")
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
    parser.add_argument(
        "--require-tool-call",
        action="store_true",
        help="Fail if the provider streams content but does not emit a tool call.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_stream_smoke(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            prompt=args.prompt,
            tool_call=args.tool_call or args.require_tool_call,
            require_tool_call=args.require_tool_call,
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
