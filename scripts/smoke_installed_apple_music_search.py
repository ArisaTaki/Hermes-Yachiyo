#!/usr/bin/env python3
"""Exercise installed Oha-Yachiyo -> packaged backend -> Electron -> Music search.

Quit any already-running Oha-Yachiyo instance before running this smoke.  The
script injects a one-run loopback Bridge URL/token, launches the installed app,
submits a deterministic daily-desktop request, and requires the public tool
receipt to prove the Music query, final foreground, and Electron native focus.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


DEFAULT_APP_PATH = Path("/Applications/Oha-Yachiyo.app")
DEFAULT_QUERY = "超时空辉夜姬"
APP_EXECUTABLE_NAME = "Oha-Yachiyo"
BRIDGE_TOKEN_HEADER = "X-Oha-Yachiyo-Bridge-Token"
PRIMER_VERIFICATION_DEADLINE_SECONDS = 20.0


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _app_executable(app_path: Path) -> Path:
    if app_path.suffix == ".app" or app_path.is_dir():
        return app_path / "Contents" / "MacOS" / APP_EXECUTABLE_NAME
    return app_path


def _request_json(
    bridge_url: str,
    route: str,
    *,
    token: str = "",
    payload: Mapping[str, Any] | None = None,
    timeout_seconds: float = 45,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
    headers = {
        "accept": "application/json",
        **({BRIDGE_TOKEN_HEADER: token} if token else {}),
        **({"content-type": "application/json"} if body is not None else {}),
    }
    request = urllib.request.Request(
        f"{bridge_url.rstrip('/')}{route}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    value = json.loads(raw) if raw.strip() else {}
    if not isinstance(value, dict):
        raise RuntimeError("bridge_response_not_object")
    return value


def _wait_for_status(
    process: subprocess.Popen[str],
    bridge_url: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(
                f"installed_app_exited_before_bridge_ready:returncode={returncode}"
            )
        try:
            status = _request_json(bridge_url, "/status", timeout_seconds=2)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(0.25)
            continue
        if status.get("service") == "oha-yachiyo":
            return status
        last_error = f"unexpected_service:{status.get('service')!r}"
        time.sleep(0.25)
    raise RuntimeError(f"installed_app_bridge_not_ready:{last_error}")


def _music_tool_call(response: Mapping[str, Any]) -> dict[str, Any]:
    agent_task = _mapping(response.get("agent_task"))
    tool_calls = agent_task.get("tool_calls")
    if not isinstance(tool_calls, list):
        return {}
    for call in reversed(tool_calls):
        if isinstance(call, Mapping) and call.get("tool_name") == "media.apple_music_play":
            return dict(call)
    return {}


def _normalized_query(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _music_search_evidence(
    query: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    from apps.shell.agent.tools import desktop as desktop_tools

    return desktop_tools._apple_music_search_result_evidence(
        query,
        timeout_seconds=timeout_seconds,
    )


def _prime_nonmatching_music_search(query: str) -> dict[str, Any]:
    """Give the backend a known nonmatching AX baseline for repeatable proof."""

    primer = (
        "The Beatles"
        if "thebeatles" not in query.casefold().replace(" ", "")
        else "Taylor Swift"
    )
    if _normalized_query(primer) == _normalized_query(query):
        raise RuntimeError("music_nonmatching_baseline_primer_matches_target")
    url = f"https://music.apple.com/search?term={quote_plus(primer)}"
    deadline = time.monotonic() + PRIMER_VERIFICATION_DEADLINE_SECONDS
    dispatch_timeout = min(8.0, max(0.0, deadline - time.monotonic()))
    if dispatch_timeout <= 0:
        raise RuntimeError("music_nonmatching_baseline_verification_timed_out")
    result = subprocess.run(
        ["/usr/bin/open", "-a", "Music", url],
        capture_output=True,
        text=True,
        timeout=dispatch_timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"music_nonmatching_baseline_dispatch_failed:returncode={result.returncode}"
        )
    last_evidence: dict[str, Any] = {}
    for attempt in range(8):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if attempt:
            time.sleep(min(0.25, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
        last_evidence = _music_search_evidence(
            primer,
            timeout_seconds=min(10.0, remaining),
        )
        if time.monotonic() >= deadline:
            break
        evidence_data = _mapping(last_evidence.get("data"))
        result_fingerprint = str(evidence_data.get("fingerprint") or "")
        if (
            last_evidence.get("ok") is True
            and evidence_data.get("result_marker") is True
            and evidence_data.get("query_match") is True
            and result_fingerprint
        ):
            return {
                "ok": True,
                "verified": True,
                "primer": primer,
                "query": query,
                "url": url,
                "result_marker": True,
                "search_query_identity_verified": (
                    evidence_data.get("search_query_identity_verified") is True
                ),
                "query_match": True,
                "result_fingerprint": result_fingerprint,
                "evidence": last_evidence,
            }
    last_error = str(last_evidence.get("error") or "search_ui_evidence_unverified")
    raise RuntimeError(f"music_nonmatching_baseline_unverified:{last_error}")


def _native_focus_receipt(tool_output: Mapping[str, Any]) -> dict[str, Any]:
    search_receipt = _mapping(tool_output.get("fallback_result"))
    search_details = _mapping(search_receipt.get("fallback_result"))
    return _mapping(search_details.get("focus"))


def assess_search_response(
    response: Mapping[str, Any],
    *,
    query: str,
    primer_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    call = _music_tool_call(response)
    output = _mapping(call.get("output_preview"))
    data = _mapping(output.get("data"))
    search_receipt = _mapping(output.get("fallback_result"))
    search_data = _mapping(search_receipt.get("data"))
    search_details = _mapping(search_receipt.get("fallback_result"))
    baseline_evidence = _mapping(search_details.get("baseline_evidence"))
    baseline_data = _mapping(baseline_evidence.get("data"))
    focus = _native_focus_receipt(output)
    focus_data = _mapping(focus.get("data"))
    primer = _mapping(primer_evidence)
    primer_query = str(primer.get("primer") or "")
    primer_fingerprint = str(primer.get("result_fingerprint") or "")
    primer_verified = bool(
        primer.get("ok") is True
        and primer.get("verified") is True
        and primer.get("result_marker") is True
        and primer.get("query_match") is True
        and primer_fingerprint
        and _normalized_query(primer_query) != _normalized_query(query)
    )
    baseline_fingerprint = str(
        data.get("search_baseline_fingerprint")
        or baseline_data.get("fingerprint")
        or ""
    )
    bounded_baseline_present = bool(
        "search_baseline_result_marker" in data
        and "search_baseline_query_match" in data
    )
    bounded_baseline_matches = bool(
        data.get("search_result_changed_from_nonmatching_baseline") is True
        and data.get("search_baseline_result_marker") is True
        and data.get("search_baseline_query_match") is False
        and baseline_fingerprint
    )
    nested_baseline_matches = bool(
        baseline_evidence.get("ok") is True
        and baseline_data.get("result_marker") is True
        and baseline_data.get("query_match") is False
        and baseline_fingerprint
    )
    runtime_baseline_matches_verified_primer = bool(
        primer_verified
        and (
            bounded_baseline_matches
            if bounded_baseline_present
            else nested_baseline_matches
        )
    )
    target_fingerprint = str(
        data.get("search_result_fingerprint")
        or search_data.get("result_fingerprint")
        or ""
    )
    focus_strategy = str(
        data.get("focus_strategy") or focus_data.get("focus_strategy") or ""
    )
    focus_verified = bool(
        data.get("electron_native_focus_verified") is True
        or (
            focus.get("ok") is True
            and focus_data.get("focus_verified") is True
        )
    )
    focus_frontmost_app = str(
        data.get("focus_frontmost_app") or focus_data.get("frontmost_app") or ""
    )
    causal_query_evidence = bool(
        runtime_baseline_matches_verified_primer
        and data.get("search_result_changed_from_nonmatching_baseline") is True
        and target_fingerprint
        and target_fingerprint != baseline_fingerprint
    )
    checks = {
        "message_committed": response.get("committed") is True or response.get("ok") is True,
        "music_tool_selected": bool(call),
        "music_tool_completed": call.get("status") == "completed",
        "search_fallback_verified": bool(
            output.get("ok") is True
            and data.get("search_opened") is True
            and data.get("search_query_verified") is True
        ),
        "nonmatching_primer_verified": primer_verified,
        "runtime_baseline_matches_verified_primer": (
            runtime_baseline_matches_verified_primer
        ),
        "causal_query_evidence_verified": causal_query_evidence,
        "final_foreground_verified": data.get("foreground_verified") is True,
        "electron_native_focus_verified": bool(
            focus_strategy == "electron_native_bridge"
            and focus_verified
            and focus_frontmost_app.strip() == "Music"
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not failed_checks,
        "mode": "installed_apple_music_search_smoke",
        **({} if not failed_checks else {"error": f"failed_checks:{','.join(failed_checks)}"}),
        "query": query,
        "task_id": str(response.get("task_id") or ""),
        "run_id": str(response.get("run_id") or ""),
        "checks": checks,
        "evidence": {
            "tool_name": str(call.get("tool_name") or ""),
            "tool_status": str(call.get("status") or ""),
            "search_opened": data.get("search_opened") is True,
            "search_query_verified": data.get("search_query_verified") is True,
            "search_query_identity_verified": (
                data.get("search_query_identity_verified") is True
            ),
            "search_result_changed_from_nonmatching_baseline": (
                data.get("search_result_changed_from_nonmatching_baseline") is True
            ),
            "primer_verified": primer_verified,
            "primer_fingerprint": primer_fingerprint,
            "runtime_baseline_fingerprint": baseline_fingerprint,
            "target_fingerprint": target_fingerprint,
            "foreground_verified": data.get("foreground_verified") is True,
            "focus_strategy": focus_strategy,
            "focus_verified": focus_verified,
            "frontmost_app": focus_frontmost_app,
        },
    }


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        process.wait(timeout=5)


def run_smoke(
    *,
    app_path: Path = DEFAULT_APP_PATH,
    query: str = DEFAULT_QUERY,
    startup_timeout_seconds: float = 30,
    request_timeout_seconds: float = 45,
) -> dict[str, Any]:
    executable = _app_executable(app_path.expanduser().resolve())
    if sys.platform != "darwin":
        return {
            "ok": False,
            "mode": "installed_apple_music_search_smoke",
            "error": "macos_required",
        }
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return {
            "ok": False,
            "mode": "installed_apple_music_search_smoke",
            "error": "installed_app_executable_not_found",
            "app_path": str(app_path),
            "executable_path": str(executable),
        }

    bridge_url = f"http://127.0.0.1:{_allocate_loopback_port()}"
    bridge_token = secrets.token_urlsafe(32)
    env = {
        **os.environ,
        "OHA_YACHIYO_BRIDGE_URL": bridge_url,
        "OHA_YACHIYO_BRIDGE_TOKEN": bridge_token,
    }
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        status = _wait_for_status(
            process,
            bridge_url,
            timeout_seconds=startup_timeout_seconds,
        )
        primer = _prime_nonmatching_music_search(query)
        client_message_id = f"installed-music-smoke-{secrets.token_hex(8)}"
        response = _request_json(
            bridge_url,
            "/ui/chat/messages",
            token=bridge_token,
            payload={
                "text": f"帮我在 Apple Music 搜一下{query}并播放",
                "attachments": [],
                "client_message_id": client_message_id,
            },
            timeout_seconds=request_timeout_seconds,
        )
        assessment = assess_search_response(
            response,
            query=query,
            primer_evidence=primer,
        )
        return {
            **assessment,
            "app_path": str(app_path),
            "executable_path": str(executable),
            "bridge_url": bridge_url,
            "packaged_service": status.get("service") == "oha-yachiyo",
            "build_metadata": _mapping(status.get("build_metadata")),
            "nonmatching_baseline_primer": primer,
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "installed_apple_music_search_smoke",
            "error": str(exc),
            "app_path": str(app_path),
            "executable_path": str(executable),
            "bridge_url": bridge_url,
        }
    finally:
        if process is not None:
            _terminate_process(process)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=DEFAULT_APP_PATH)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--startup-timeout-seconds", type=float, default=30)
    parser.add_argument("--request-timeout-seconds", type=float, default=45)
    parser.add_argument("--report-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_smoke(
        app_path=args.app,
        query=str(args.query or "").strip() or DEFAULT_QUERY,
        startup_timeout_seconds=args.startup_timeout_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
