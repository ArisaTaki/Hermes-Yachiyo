#!/usr/bin/env python3
"""Local provider-contract smoke for Native Agent model/tool/workflow loops.

This smoke does not replace the real provider smoke. It patches the local
OpenAI-compatible HTTP transport with a deterministic SSE provider so source
verification can exercise the same stream parsing, tool-call, approval resume,
main Chat model loop, and Workflow orchestration paths without external
credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import apps.shell.model_profiles as model_profiles
from packages.security import contains_sensitive_text, sanitize_sensitive_value
from scripts.smoke_native_agent_full_chain import run_full_chain_smoke
from scripts.smoke_native_workflow_full_chain import run_workflow_full_chain_smoke

_FAKE_BASE_URL = "https://oha-yachiyo-provider-contract.local/v1"
_FAKE_MODEL = "oha-yachiyo-provider-contract-model"
_FAKE_API_KEY = "sk-oha-yachiyo-provider-contract-secret123456"


class _FakeProviderResponse:
    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        chunks: list[dict[str, Any]] | None = None,
    ) -> None:
        self._payload = payload or {}
        self._chunks = list(chunks or [])

    def __enter__(self) -> "_FakeProviderResponse":
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    return ""


def _combined_message_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(_message_text(message) for message in messages if isinstance(message, dict))


def _tool_names(payload: dict[str, Any]) -> list[str]:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict):
            name = str(function.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _last_tool_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "tool":
            return message
    return None


def _exact_output_from_prompt(text: str) -> str:
    match = re.search(
        r"Return exactly this text and nothing else:\s*(.+?)\.\s*Do not call tools",
        text,
        flags=re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    if "MAIN_CHAT_OK" in text:
        return "MAIN_CHAT_OK"
    if "APPROVED_CHAIN_OK" in text:
        return "APPROVED_CHAIN_OK"
    return "PROVIDER_CONTRACT_OK"


def _content_chunk(text: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {"content": text},
                "finish_reason": finish_reason,
            }
        ]
    }


def _tool_call_chunk(
    *,
    call_id: str,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                            },
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _non_stream_response(text: str = "PROVIDER_PROFILE_OK") -> _FakeProviderResponse:
    return _FakeProviderResponse(
        payload={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": text,
                    }
                }
            ]
        }
    )


def _tool_result_response(tool_message: dict[str, Any]) -> _FakeProviderResponse:
    tool_call_id = str(tool_message.get("tool_call_id") or "")
    if "workspace_pipeline" in tool_call_id:
        return _FakeProviderResponse(
            chunks=[
                _tool_call_chunk(
                    call_id="call_artifact_pipeline",
                    name="artifact_write",
                    arguments={
                        "path": "pipeline-report.md",
                        "content": "Oha-Yachiyo pipeline report: MIYABI-742",
                    },
                )
            ]
        )
    if "artifact_pipeline" in tool_call_id:
        return _FakeProviderResponse(chunks=[_content_chunk("PIPELINE_DONE MIYABI-742")])
    if "workspace" in tool_call_id:
        return _FakeProviderResponse(chunks=[_content_chunk("MIYABI-742 Oha-Yachiyo")])
    if "artifact_live" in tool_call_id:
        return _FakeProviderResponse(chunks=[_content_chunk("DONE")])
    if "terminal" in tool_call_id:
        return _FakeProviderResponse(chunks=[_content_chunk("APPROVED_CHAIN_OK")])
    return _FakeProviderResponse(chunks=[_content_chunk("TOOL_RESULT_OK")])


def _stream_response(payload: dict[str, Any]) -> _FakeProviderResponse:
    messages = payload.get("messages")
    clean_messages = [message for message in messages if isinstance(message, dict)] if isinstance(messages, list) else []
    tool_result = _last_tool_message(clean_messages)
    if tool_result is not None:
        return _tool_result_response(tool_result)

    names = set(_tool_names(payload))
    prompt_text = _combined_message_text(clean_messages)
    if "MAIN_CHAT_OK" in prompt_text:
        return _FakeProviderResponse(chunks=[_content_chunk("MAIN_CHAT_OK")])
    if "workspace_read" in names and "artifact_write" in names:
        return _FakeProviderResponse(
            chunks=[
                _tool_call_chunk(
                    call_id="call_workspace_pipeline",
                    name="workspace_read",
                    arguments={"path": "pipeline-facts.txt"},
                )
            ]
        )
    if "workspace_read" in names:
        return _FakeProviderResponse(
            chunks=[
                _tool_call_chunk(
                    call_id="call_workspace_facts",
                    name="workspace_read",
                    arguments={"path": "facts.txt"},
                )
            ]
        )
    if "artifact_write" in names:
        return _FakeProviderResponse(
            chunks=[
                _tool_call_chunk(
                    call_id="call_artifact_live",
                    name="artifact_write",
                    arguments={
                        "path": "live-chain-report.md",
                        "content": "Oha-Yachiyo report with MIYABI-742",
                    },
                )
            ]
        )
    if "terminal_run" in names:
        return _FakeProviderResponse(
            chunks=[
                _tool_call_chunk(
                    call_id="call_terminal_approval",
                    name="terminal_run",
                    arguments={"command": "printf APPROVED_CHAIN_OK"},
                )
            ]
        )
    return _FakeProviderResponse(chunks=[_content_chunk(_exact_output_from_prompt(prompt_text))])


def _fake_urlopen(request: Any, **_kwargs: Any) -> _FakeProviderResponse:
    try:
        payload = json.loads(request.data.decode("utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("stream"):
        return _stream_response(payload)
    return _non_stream_response()


@contextmanager
def _patched_provider_transport() -> Iterator[None]:
    original_urlopen = model_profiles.urlopen_with_bundled_ca
    model_profiles.urlopen_with_bundled_ca = _fake_urlopen
    try:
        yield
    finally:
        model_profiles.urlopen_with_bundled_ca = original_urlopen


def run_contract_smoke() -> dict[str, Any]:
    with _patched_provider_transport():
        native_agent = run_full_chain_smoke(
            base_url=_FAKE_BASE_URL,
            model=_FAKE_MODEL,
            api_key=_FAKE_API_KEY,
        )
        native_workflow = run_workflow_full_chain_smoke(
            base_url=_FAKE_BASE_URL,
            model=_FAKE_MODEL,
            api_key=_FAKE_API_KEY,
        )
    checks = [
        {
            "label": "native_agent_full_chain_contract",
            "summary": native_agent,
            "ok": bool(native_agent.get("ok")),
        },
        {
            "label": "native_workflow_full_chain_contract",
            "summary": native_workflow,
            "ok": bool(native_workflow.get("ok")),
        },
    ]
    return sanitize_sensitive_value(
        {
            "ok": all(bool(check["ok"]) for check in checks),
            "mode": "native_provider_contract_smoke",
            "provider": "local_fake_openai_compatible_sse",
            "checks": checks,
        },
        max_depth=8,
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    args = parser.parse_args(argv)
    payload = run_contract_smoke()
    if contains_sensitive_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)):
        payload = {"ok": False, "error": "contract smoke output still contains sensitive text"}
    if args.report_json is not None:
        _write_report(args.report_json, payload)
        print(f"native provider contract smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
