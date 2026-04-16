"""Hermes streaming bridge.

Runs under Hermes Agent's own Python interpreter.  The parent process sends one
JSON payload on stdin and receives newline-delimited JSON events on stdout:

  {"type": "delta", "delta": "..."}
  {"type": "done", "response": "...", "session_id": "...", "title": "..."}
  {"type": "error", "message": "..."}

All Hermes CLI terminal output is redirected to stderr so the chat UI consumes
only agent text deltas, not Rich banners, tool lists, or startup messages.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from typing import Any, Optional


_EVENT_STDOUT = sys.stdout


def _emit(event_type: str, **payload: Any) -> None:
    payload["type"] = event_type
    _EVENT_STDOUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _EVENT_STDOUT.flush()


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _resolve_toolsets(cli_config: dict[str, Any]) -> list[str]:
    try:
        from hermes_cli.tools_config import _get_platform_tools

        return sorted(_get_platform_tools(cli_config, "cli"))
    except Exception:
        return []


def _get_session_title(cli: Any, session_id: str) -> Optional[str]:
    session_db = getattr(cli, "_session_db", None)
    if session_db is None:
        return None
    try:
        title = session_db.get_session_title(session_id)
    except Exception:
        return None
    return title if isinstance(title, str) and title else None


def _run(payload: dict[str, Any]) -> int:
    description = str(payload.get("description") or "")
    resume = payload.get("resume")
    resume = resume if isinstance(resume, str) and resume else None
    if not description.strip():
        _emit("error", message="消息内容不能为空")
        return 2

    os.environ["HERMES_INTERACTIVE"] = "1"

    # Import inside redirected stdout because Hermes imports/config loading may print.
    with contextlib.redirect_stdout(sys.stderr):
        from cli import CLI_CONFIG, HermesCLI

        cli = HermesCLI(
            toolsets=_resolve_toolsets(CLI_CONFIG),
            verbose=False,
            compact=True,
            resume=resume,
        )
        cli.tool_progress_mode = "off"
        cli.streaming_enabled = False

        if not cli._ensure_runtime_credentials():
            _emit("error", message="Hermes runtime credentials are not available")
            return 1

        route = cli._resolve_turn_agent_config(description)
        if route["signature"] != cli._active_agent_route_signature:
            cli.agent = None

        ok = cli._init_agent(
            model_override=route["model"],
            runtime_override=route["runtime"],
            route_label=route["label"],
            request_overrides=route.get("request_overrides"),
        )
        if not ok:
            _emit("error", message="Hermes agent 初始化失败")
            return 1

        cli.agent.quiet_mode = True
        cli.agent.suppress_status_output = True

        def on_delta(delta: Any) -> None:
            if delta is None:
                _emit("boundary")
                return
            if not isinstance(delta, str):
                delta = str(delta)
            if delta:
                _emit("delta", delta=delta)

        result = cli.agent.run_conversation(
            user_message=description,
            conversation_history=cli.conversation_history,
            stream_callback=on_delta,
            task_id=cli.session_id,
        )

    if isinstance(result, dict):
        response = result.get("final_response", "")
        failed = bool(result.get("failed"))
    else:
        response = str(result)
        failed = False

    _emit(
        "done",
        response=response if isinstance(response, str) else str(response),
        session_id=getattr(cli, "session_id", None),
        title=_get_session_title(cli, getattr(cli, "session_id", "")),
        failed=failed,
    )
    return 1 if failed else 0


def main() -> int:
    try:
        payload = _read_payload()
        return _run(payload)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit("error", message=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
