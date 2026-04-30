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
import inspect
import json
import os
import sys
import traceback
from typing import Any, Optional


_EVENT_STDOUT = sys.stdout
_DEBUG_ROUTE_ENV = "HERMES_YACHIYO_DEBUG_ROUTE"
_DEBUG_ROUTE_TRUE_VALUES = {"1", "true", "yes", "on", "debug"}
_EMPTY_DETAIL_VALUES = {"", "none", "null"}
_FAILURE_DETAIL_KEYS = (
    "error",
    "error_message",
    "message",
    "exception",
    "detail",
    "details",
)


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


def _detail_text(value: Any, *, drop_empty_literals: bool = True) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value).strip()
    else:
        text = str(value).strip()
    if drop_empty_literals and text.lower() in _EMPTY_DETAIL_VALUES:
        return ""
    return text


def _failure_message_from_result(result: dict[str, Any]) -> str:
    for key in _FAILURE_DETAIL_KEYS:
        text = _detail_text(result.get(key))
        if text:
            return text
    errors = result.get("errors")
    if isinstance(errors, list):
        for item in errors:
            text = _detail_text(item)
            if text:
                return text
    return ""


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


def _is_debug_route_enabled() -> bool:
    value = os.environ.get(_DEBUG_ROUTE_ENV, "")
    return value.strip().lower() in _DEBUG_ROUTE_TRUE_VALUES


def _debug_route(route: Any) -> None:
    """按显式开关输出 route 结构，供开发者对比不同 provider 路径。

    只输出结构信息，不输出 value，避免泄漏 token、endpoint 或 request 配置。
    """
    if not _is_debug_route_enabled():
        return
    try:
        if route is None:
            print("[yachiyo-debug] route=None", file=sys.stderr, flush=True)
            return
        if isinstance(route, dict):
            print(
                f"[yachiyo-debug] route keys={list(route.keys())}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"[yachiyo-debug] route type={type(route).__name__}",
                file=sys.stderr,
                flush=True,
            )
    except Exception:
        pass


def _build_init_agent_kwargs(
    init_agent_fn: Any,
    *,
    model_override: Any,
    runtime_override: Any,
    route_label: Any,
    request_overrides: Any,
) -> dict[str, Any]:
    """运行时检查 _init_agent() 的签名，只传入函数实际接受的参数。

    Hermes 不同版本 / provider 路径下 _init_agent() 的签名并不稳定：
    - 某些版本支持 route_label 参数
    - 另一些版本不支持，直接传会引发 TypeError: unexpected keyword argument

    通过 inspect.signature 动态构建 kwargs，避免硬编码参数名与 Hermes 内部 API 绑定。
    """
    candidates: dict[str, Any] = {
        "model_override": model_override,
        "runtime_override": runtime_override,
        "route_label": route_label,
        "request_overrides": request_overrides,
    }

    try:
        sig = inspect.signature(init_agent_fn)
    except (ValueError, TypeError):
        # 获取签名失败时保守处理：只传最基础的两个参数
        return {
            "model_override": model_override,
            "runtime_override": runtime_override,
        }

    # 部分 Hermes 版本使用 **kwargs，此时所有候选均可传
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )
    if has_var_keyword:
        return {k: v for k, v in candidates.items() if v is not None}

    accepted = set(sig.parameters.keys())
    return {k: v for k, v in candidates.items() if k in accepted}


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

        # 诊断日志：记录 route 的完整结构，帮助对比 provider 路径差异
        _debug_route(route)

        # 防御式解析：_resolve_turn_agent_config 在不同 provider/api_mode（如
        # Nous Portal、MiMo 等）下返回的 dict 可能缺少 "label"、"model"、
        # "runtime"、"signature" 等字段，不能假定全部存在。
        if not isinstance(route, dict):
            _emit(
                "error",
                message=(
                    f"Hermes agent 路由配置类型不符（期望 dict，实际 {type(route).__name__}）"
                ),
            )
            return 1

        route_sig = route.get("signature")
        if route_sig != cli._active_agent_route_signature:
            cli.agent = None

        # label 字段在部分 provider 路径下可能不存在，此处安全降级为 None。
        route_label = route.get("label")

        # 使用签名检查构建 kwargs，避免向旧版 Hermes _init_agent 传入它不认识的参数
        init_kwargs = _build_init_agent_kwargs(
            cli._init_agent,
            model_override=route.get("model"),
            runtime_override=route.get("runtime"),
            route_label=route_label,
            request_overrides=route.get("request_overrides"),
        )
        if _is_debug_route_enabled():
            print(
                "[yachiyo-debug] _init_agent kwargs="
                f"{list(init_kwargs.keys())}, route_label_present={route_label is not None}",
                file=sys.stderr,
                flush=True,
            )
        try:
            ok = cli._init_agent(**init_kwargs)
        except TypeError as exc:
            # 签名检测失败兜底：去掉 route_label 后再试一次
            fallback_kwargs = {
                k: v for k, v in init_kwargs.items() if k != "route_label"
            }
            try:
                ok = cli._init_agent(**fallback_kwargs)
                if _is_debug_route_enabled():
                    print(
                        "[yachiyo-debug] _init_agent fallback succeeded "
                        "(removed route_label)",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc2:
                _emit(
                    "error",
                    message=f"Hermes agent 初始化参数不兼容（{exc2}）",
                )
                return 1
        except Exception as exc:
            _emit(
                "error",
                message=f"Hermes agent 初始化失败（{type(exc).__name__}）",
            )
            return 1

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
        response = _detail_text(result.get("final_response"), drop_empty_literals=False)
        failed = bool(result.get("failed"))
        error = _failure_message_from_result(result) if failed else ""
    else:
        response = _detail_text(result)
        failed = False
        error = ""

    done_payload: dict[str, Any] = {
        "response": response,
        "session_id": getattr(cli, "session_id", None),
        "title": _get_session_title(cli, getattr(cli, "session_id", "")),
        "failed": failed,
    }
    if error:
        done_payload["error"] = error
    _emit("done", **done_payload)
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
