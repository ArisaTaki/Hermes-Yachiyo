#!/usr/bin/env python3
"""Run opt-in external integration smoke checks against a live Oha bridge."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.security import redact_api_error_text

EXPECTED_BRIDGE_SERVICE = "oha-yachiyo"
REQUIRED_CHECK_IDS: tuple[str, ...] = (
    "live2d_resource",
    "gpt_sovits_tts",
    "astrbot_plugin_bridge",
)
FULL_EXTERNAL_SMOKE_COMMAND = (
    "python scripts/smoke_external_integrations.py "
    "--bridge-url http://127.0.0.1:18420 "
    "--live2d-archive /path/to/yachiyo-live2d.zip "
    "--tts-voice-archive /path/to/yachiyo-gpt-sovits.zip "
    "--gpt-sovits-base-url http://127.0.0.1:9880 "
    "--astrbot "
    "--report-json tmp/external-integrations-smoke.json"
)
REQUIRED_CHECK_NEXT_ACTIONS: dict[str, str] = {
    "live2d_resource": (
        "Prepare the real Yachiyo Live2D ZIP and rerun with "
        "--live2d-archive /path/to/yachiyo-live2d.zip."
    ),
    "gpt_sovits_tts": (
        "Prepare the real GPT-SoVITS voice ZIP, start the GPT-SoVITS API, "
        "and rerun with --tts-voice-archive plus --gpt-sovits-base-url "
        "without --skip-tts-test."
    ),
    "astrbot_plugin_bridge": (
        "Run the AstrBot plugin bridge check with --astrbot; use "
        "--astrbot-task-mode require when final signoff must prove Native "
        "Agent task commands."
    ),
}


class SmokeError(RuntimeError):
    """External smoke check failed."""


def _redacted_error(exc: BaseException) -> str:
    return redact_api_error_text(exc, fallback="external integration smoke failed")


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_existing_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SmokeError(f"{label} does not exist or is not a file: {path}")
    return resolved


def _json_response(response: httpx.Response, *, path: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:1000] if exc.response is not None else ""
        detail = redact_api_error_text(body or str(exc))
        raise SmokeError(f"{path} returned HTTP {response.status_code}: {detail}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise SmokeError(f"{path} did not return JSON") from exc
    if not isinstance(data, dict):
        raise SmokeError(f"{path} returned non-object JSON")
    return data


def _get(client: httpx.Client, path: str) -> dict[str, Any]:
    try:
        return _json_response(client.get(path), path=path)
    except httpx.HTTPError as exc:
        raise SmokeError(f"{path} request failed: {_redacted_error(exc)}") from exc


def _post(client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return _json_response(client.post(path, json=body), path=path)
    except httpx.HTTPError as exc:
        raise SmokeError(f"{path} request failed: {_redacted_error(exc)}") from exc


def _require_ok(payload: dict[str, Any], *, label: str) -> None:
    if payload.get("ok") is True or payload.get("success") is True:
        return
    message = payload.get("message") or payload.get("error") or f"{label} did not return ok=true"
    raise SmokeError(str(message))


def _append_check(
    checks: list[dict[str, Any]],
    check_id: str,
    *,
    ok: bool,
    evidence: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    item: dict[str, Any] = {
        "id": check_id,
        "status": "passed" if ok else "failed",
    }
    if evidence:
        item["evidence"] = evidence
    if error:
        item["error"] = redact_api_error_text(error)
    checks.append(item)


def _selected_required_check_ids(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    if args.live2d_archive:
        selected.append("live2d_resource")
    if args.tts_voice_archive:
        selected.append("gpt_sovits_tts")
    if args.astrbot:
        selected.append("astrbot_plugin_bridge")
    return selected


def _resource_input_summary(args: argparse.Namespace) -> dict[str, Any]:
    def file_input(path: Path | None) -> dict[str, Any]:
        if path is None:
            return {"provided": False}
        expanded = path.expanduser()
        return {
            "provided": True,
            "path": str(path),
            "exists": expanded.is_file(),
        }

    return {
        "live2d_archive": file_input(args.live2d_archive),
        "tts_voice_archive": file_input(args.tts_voice_archive),
        "gpt_sovits_base_url_configured": bool(args.gpt_sovits_base_url.strip()),
        "tts_test_skipped": bool(args.skip_tts_test),
        "astrbot_enabled": bool(args.astrbot),
        "astrbot_screen_enabled": bool(args.astrbot and not args.astrbot_skip_screen),
        "astrbot_window_enabled": bool(args.astrbot and not args.astrbot_skip_window),
        "astrbot_task_mode": str(getattr(args, "astrbot_task_mode", "auto") or "auto"),
        "bridge_token_configured": bool(str(getattr(args, "bridge_token", "")).strip()),
    }


def _report_metadata(
    args: argparse.Namespace,
    *,
    selected_required_check_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    selected = list(selected_required_check_ids or _selected_required_check_ids(args))
    missing = [check_id for check_id in REQUIRED_CHECK_IDS if check_id not in selected]
    return {
        "required_check_ids": list(REQUIRED_CHECK_IDS),
        "selected_required_check_ids": selected,
        "missing_required_check_ids": missing,
        "resource_inputs": _resource_input_summary(args),
    }


def _external_report(
    args: argparse.Namespace,
    *,
    checks: list[dict[str, Any]],
    mode: str,
    ok: bool,
    selected_required_check_ids: Sequence[str] | None = None,
    error: str = "",
) -> dict[str, Any]:
    metadata = _report_metadata(
        args,
        selected_required_check_ids=selected_required_check_ids,
    )
    readiness = _readiness_summary(
        args,
        checks=checks,
        mode=mode,
        ok=ok,
        missing_required_check_ids=metadata["missing_required_check_ids"],
    )
    report: dict[str, Any] = {
        "ok": ok,
        "complete": readiness["signoff_ready"],
        "mode": mode,
        "bridge_url": args.bridge_url.rstrip("/"),
        **metadata,
        "readiness": readiness,
        "checks": checks,
    }
    if error:
        report["error"] = redact_api_error_text(error)
    return report


def _check_ids_by_status(checks: Sequence[dict[str, Any]], status: str) -> list[str]:
    return [
        str(check.get("id") or "").strip()
        for check in checks
        if str(check.get("id") or "").strip()
        and str(check.get("status") or "").strip() == status
    ]


def _readiness_summary(
    args: argparse.Namespace,
    *,
    checks: Sequence[dict[str, Any]],
    mode: str,
    ok: bool,
    missing_required_check_ids: Sequence[str],
) -> dict[str, Any]:
    passed_check_ids = _check_ids_by_status(checks, "passed")
    failed_check_ids = [
        str(check.get("id") or "").strip()
        for check in checks
        if str(check.get("id") or "").strip()
        and str(check.get("status") or "").strip() != "passed"
    ]
    passed_required_check_ids = [
        check_id for check_id in REQUIRED_CHECK_IDS if check_id in passed_check_ids
    ]
    failed_required_check_ids = [
        check_id for check_id in REQUIRED_CHECK_IDS if check_id in failed_check_ids
    ]
    missing_required = [
        check_id for check_id in missing_required_check_ids if check_id in REQUIRED_CHECK_IDS
    ]
    completion_blockers: list[str] = []
    if missing_required:
        completion_blockers.append("missing_required_checks")
    if failed_check_ids or not ok:
        completion_blockers.append("failed_checks")
    if args.tts_voice_archive and args.skip_tts_test:
        completion_blockers.append("gpt_sovits_tts_test_skipped")

    signoff_ready = (
        ok
        and mode == "external_integrations"
        and not completion_blockers
        and passed_required_check_ids == list(REQUIRED_CHECK_IDS)
    )
    if signoff_ready:
        status = "complete"
    elif failed_check_ids or not ok:
        status = "failed"
    elif mode == "bridge_only":
        status = "bridge_only"
    elif passed_required_check_ids:
        status = "partial"
    else:
        status = "incomplete"

    next_actions: list[str] = []
    if failed_check_ids:
        next_actions.append(
            "Fix failed checks before using this report as release signoff evidence: "
            + ", ".join(failed_check_ids)
            + "."
        )
    for check_id in missing_required:
        action = REQUIRED_CHECK_NEXT_ACTIONS.get(check_id)
        if action:
            next_actions.append(action)
    if "gpt_sovits_tts_test_skipped" in completion_blockers:
        next_actions.append(
            "Rerun without --skip-tts-test so the report proves a real GPT-SoVITS /ui/tts/test request."
        )
    if not next_actions and not signoff_ready:
        next_actions.append(
            "Rerun the full external integration smoke with real Live2D, GPT-SoVITS, and AstrBot resources."
        )

    return {
        "status": status,
        "signoff_ready": signoff_ready,
        "passed_check_ids": passed_check_ids,
        "failed_check_ids": failed_check_ids,
        "passed_required_check_ids": passed_required_check_ids,
        "failed_required_check_ids": failed_required_check_ids,
        "missing_required_check_ids": missing_required,
        "completion_blockers": completion_blockers,
        "next_actions": next_actions,
        "recommended_full_command": FULL_EXTERNAL_SMOKE_COMMAND,
    }


def _require_oha_bridge(status: dict[str, Any]) -> None:
    service = str(status.get("service") or "").strip()
    if service != EXPECTED_BRIDGE_SERVICE:
        raise SmokeError(
            f"/status returned service={service or '<missing>'}; "
            f"expected {EXPECTED_BRIDGE_SERVICE}"
        )


def run_live2d_resource_check(
    client: httpx.Client,
    *,
    archive_path: Path,
) -> dict[str, Any]:
    archive = _resolve_existing_file(archive_path, "Live2D archive")
    imported = _post(client, "/ui/live2d/archive/import", {"path": str(archive)})
    _require_ok(imported, label="Live2D archive import")
    draft_changes = imported.get("draft_changes")
    if not isinstance(draft_changes, dict) or not draft_changes:
        raise SmokeError("Live2D archive import did not return draft_changes")
    changes = {**draft_changes, "display_mode": "live2d"}
    saved = _post(client, "/ui/settings", {"changes": changes})
    _require_ok(saved, label="Live2D settings save")
    settings = _get(client, "/ui/settings")
    return {
        "archive": str(archive),
        "imported_path": imported.get("imported_path"),
        "draft_change_keys": sorted(str(key) for key in draft_changes),
        "display_mode_saved": True,
        "settings_mode": (
            settings.get("display", {}).get("current_mode")
            if isinstance(settings.get("display"), dict)
            else None
        ),
    }


def run_gpt_sovits_tts_check(
    client: httpx.Client,
    *,
    archive_path: Path,
    base_url: str = "",
    text: str,
    skip_tts_test: bool = False,
) -> dict[str, Any]:
    archive = _resolve_existing_file(archive_path, "GPT-SoVITS voice archive")
    imported = _post(client, "/ui/tts/voice-resource/import", {"path": str(archive)})
    _require_ok(imported, label="GPT-SoVITS voice archive import")
    draft_changes = imported.get("draft_changes")
    if not isinstance(draft_changes, dict) or not draft_changes:
        raise SmokeError("GPT-SoVITS voice import did not return draft_changes")
    changes = dict(draft_changes)
    if base_url.strip():
        changes["tts.gsv_base_url"] = base_url.strip().rstrip("/")
    saved = _post(client, "/ui/settings", {"changes": changes})
    _require_ok(saved, label="GPT-SoVITS settings save")

    evidence: dict[str, Any] = {
        "archive": str(archive),
        "imported_path": imported.get("imported_path"),
        "draft_change_keys": sorted(str(key) for key in draft_changes),
        "base_url": changes.get("tts.gsv_base_url"),
        "settings_saved": True,
        "tts_test_skipped": skip_tts_test,
    }
    if skip_tts_test:
        return evidence

    result = _post(client, "/ui/tts/test", {"text": text})
    if not (result.get("ok") is True and result.get("success") is True):
        detail = str(result.get("error") or "").strip()
        message = str(result.get("message") or "").strip()
        if detail and message and detail != message:
            raise SmokeError(f"{message}: {detail}")
        raise SmokeError(detail or message or "GPT-SoVITS TTS test failed")
    evidence.update(
        {
            "tts_test_success": True,
            "provider": result.get("provider"),
            "spoken_text": result.get("spoken_text"),
        }
    )
    return evidence


async def run_astrbot_plugin_bridge_check(
    *,
    bridge_url: str,
    bridge_token: str = "",
    sender_id: str,
    include_screen: bool = True,
    include_window: bool = True,
    task_mode: str = "auto",
) -> dict[str, Any]:
    from integrations.astrbot_plugin.config import PluginConfig
    from integrations.astrbot_plugin.main import on_y_command

    task_mode = (task_mode or "auto").strip().lower()
    if task_mode not in {"auto", "require", "skip"}:
        raise SmokeError("AstrBot task mode must be auto, require, or skip")

    config = PluginConfig(oha_url=bridge_url, bridge_token=bridge_token)
    responses: dict[str, str] = {}

    def response_has_error(response: str) -> bool:
        failure_markers = (
            "命令执行失败",
            "执行失败",
            "无法连接到 Oha-Yachiyo",
            "Bridge 响应超时",
            "Traceback",
            "RuntimeError",
            "处理失败",
            "未知错误",
            "Native Agent 未就绪",
            "资源不存在",
            "请求参数有误",
            "Bridge 内部错误",
            "请求错误",
            "请求失败",
        )
        return any(marker in response for marker in failure_markers)

    def require_success_response(label: str, response: str) -> None:
        if response_has_error(response):
            raise SmokeError(f"/y {label} returned an error response: {response[:160]}")

    async def command(label: str, text: str, *, allow_error_response: bool = False) -> str:
        response = await on_y_command(text, sender_id=sender_id, config=config)
        responses[label] = response
        if not allow_error_response:
            require_success_response(label, response)
        return response

    status = await command("status", "/y status")
    if "Oha-Yachiyo 状态" not in status:
        raise SmokeError("/y status did not return Oha-Yachiyo status")

    native_agent_ready = (
        "Native Agent" in status
        and "未就绪" not in status
        and ("已就绪" in status or "✅" in status)
    )
    run_task_commands = task_mode == "require" or (task_mode == "auto" and native_agent_ready)
    if task_mode == "require" and not native_agent_ready:
        raise SmokeError("/y status reported Native Agent is not ready")

    task_id = ""
    task_command_mode = "full"
    cancel_result = ""
    tasks_list_contains_created_task: bool | None = None
    skipped_task_commands: list[str] = []
    if run_task_commands:
        created = await command("do", "/y do 外部 AstrBot 集成验收任务")
        match = re.search(r"ID: ([0-9a-f]{8,64})", created)
        if match is None:
            raise SmokeError("/y do did not return a task id")
        task_id = match.group(1)

        tasks = await command("tasks", "/y tasks")
        if "任务" not in tasks:
            raise SmokeError("/y tasks did not return task-list text")
        tasks_list_contains_created_task = task_id[:8] in tasks

        checked = await command("check", f"/y check {task_id}")
        if task_id not in checked:
            raise SmokeError("/y check did not include the created task id")

        cancelled = await command(
            "cancel",
            f"/y cancel {task_id}",
            allow_error_response=True,
        )
        terminal_conflict = re.search(
            r"状态为\s+(failed|completed|cancelled)，无法取消",
            cancelled,
        )
        if response_has_error(cancelled):
            if terminal_conflict is None:
                raise SmokeError(f"/y cancel returned an error response: {cancelled[:160]}")
            cancel_result = f"already_terminal:{terminal_conflict.group(1)}"
        elif "任务已取消" in cancelled or "已取消" in cancelled:
            cancel_result = "cancelled"
        else:
            raise SmokeError("/y cancel did not return cancellation text")

        asked = await command("ask", "/y ask 做一次外部 AstrBot 自然语言入口验收")
        if "Yachiyo" not in asked:
            raise SmokeError("/y ask did not return a Yachiyo response")
    else:
        task_command_mode = (
            "skipped_by_request"
            if task_mode == "skip"
            else "skipped_native_agent_not_ready"
        )
        skipped_task_commands = ["do", "check", "cancel", "ask_create_low_risk_task"]

        tasks = await command("tasks", "/y tasks")
        if "任务" not in tasks:
            raise SmokeError("/y tasks did not return task-list text")

        asked = await command("ask", "/y ask 状态")
        if "Yachiyo" not in asked or "status" not in asked:
            raise SmokeError("/y ask status did not return a Yachiyo status response")

    if include_screen:
        screen = await command("screen", "/y screen")
        if "截图" not in screen:
            raise SmokeError("/y screen did not return screenshot text")

    if include_window:
        window = await command("window", "/y window")
        if "当前活动窗口" not in window:
            raise SmokeError("/y window did not return active-window text")

    evidence: dict[str, Any] = {
        "bridge_url": bridge_url,
        "bridge_token_configured": bool(bridge_token),
        "sender_id": sender_id,
        "native_agent_ready": native_agent_ready,
        "task_command_mode": task_command_mode,
        "commands": sorted(responses),
        "response_lengths": {key: len(value) for key, value in responses.items()},
    }
    if task_id:
        evidence["task_id"] = task_id
    if tasks_list_contains_created_task is not None:
        evidence["tasks_list_contains_created_task"] = tasks_list_contains_created_task
    if cancel_result:
        evidence["cancel_result"] = cancel_result
    if skipped_task_commands:
        evidence["skipped_task_commands"] = skipped_task_commands
    return evidence


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    bridge_only = bool(getattr(args, "bridge_only", False))
    selected_required_check_ids = _selected_required_check_ids(args)
    selected = bool(selected_required_check_ids or bridge_only)
    if not selected:
        raise SmokeError("select at least one check: --bridge-only, --live2d-archive, --tts-voice-archive, or --astrbot")

    bridge_token = str(getattr(args, "bridge_token", "") or "").strip()
    headers = {"X-Oha-Yachiyo-Bridge-Token": bridge_token} if bridge_token else None
    with httpx.Client(
        base_url=args.bridge_url.rstrip("/"),
        timeout=args.timeout,
        headers=headers,
    ) as client:
        try:
            status = _get(client, "/status")
            _require_oha_bridge(status)
            _append_check(
                checks,
                "bridge_status",
                ok=True,
                evidence={
                    "service": status.get("service"),
                    "version": status.get("version"),
                    "native_agent_ready": status.get("native_agent_ready"),
                },
            )
        except Exception as exc:
            _append_check(checks, "bridge_status", ok=False, error=_redacted_error(exc))
            return _external_report(
                args,
                checks=checks,
                mode="bridge_only" if bridge_only else "external_integrations",
                ok=False,
                selected_required_check_ids=selected_required_check_ids,
            )

        if bridge_only:
            return _external_report(
                args,
                checks=checks,
                mode="bridge_only",
                ok=True,
                selected_required_check_ids=selected_required_check_ids,
            )

        if args.live2d_archive:
            try:
                evidence = run_live2d_resource_check(
                    client,
                    archive_path=args.live2d_archive,
                )
                _append_check(checks, "live2d_resource", ok=True, evidence=evidence)
            except Exception as exc:
                _append_check(checks, "live2d_resource", ok=False, error=_redacted_error(exc))

        if args.tts_voice_archive:
            try:
                evidence = run_gpt_sovits_tts_check(
                    client,
                    archive_path=args.tts_voice_archive,
                    base_url=args.gpt_sovits_base_url,
                    text=args.tts_text,
                    skip_tts_test=args.skip_tts_test,
                )
                _append_check(checks, "gpt_sovits_tts", ok=True, evidence=evidence)
            except Exception as exc:
                _append_check(checks, "gpt_sovits_tts", ok=False, error=_redacted_error(exc))

    if args.astrbot:
        try:
            evidence = asyncio.run(
                run_astrbot_plugin_bridge_check(
                    bridge_url=args.bridge_url.rstrip("/"),
                    bridge_token=bridge_token,
                    sender_id=args.astrbot_sender,
                    include_screen=not args.astrbot_skip_screen,
                    include_window=not args.astrbot_skip_window,
                    task_mode=str(getattr(args, "astrbot_task_mode", "auto") or "auto"),
                )
            )
            _append_check(checks, "astrbot_plugin_bridge", ok=True, evidence=evidence)
        except Exception as exc:
            _append_check(checks, "astrbot_plugin_bridge", ok=False, error=_redacted_error(exc))

    selected_ok = all(check.get("status") == "passed" for check in checks)
    return _external_report(
        args,
        checks=checks,
        mode="external_integrations",
        ok=selected_ok,
        selected_required_check_ids=selected_required_check_ids,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run opt-in external Oha-Yachiyo integration checks against a live Bridge."
    )
    parser.add_argument("--bridge-url", default="http://127.0.0.1:18420")
    parser.add_argument(
        "--bridge-token",
        default=os.getenv("OHA_YACHIYO_BRIDGE_TOKEN", ""),
        help="Bridge session token for packaged mutating routes; defaults to OHA_YACHIYO_BRIDGE_TOKEN.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--bridge-only",
        action="store_true",
        help="Only verify that --bridge-url points at an Oha-Yachiyo Bridge.",
    )
    parser.add_argument("--live2d-archive", type=Path)
    parser.add_argument("--tts-voice-archive", type=Path)
    parser.add_argument("--gpt-sovits-base-url", default="")
    parser.add_argument("--tts-text", default="Oha-Yachiyo GPT-SoVITS 外部集成验收。")
    parser.add_argument("--skip-tts-test", action="store_true")
    parser.add_argument("--astrbot", action="store_true")
    parser.add_argument("--astrbot-sender", default="external-smoke")
    parser.add_argument("--astrbot-skip-screen", action="store_true")
    parser.add_argument("--astrbot-skip-window", action="store_true")
    parser.add_argument(
        "--astrbot-task-mode",
        choices=("auto", "require", "skip"),
        default="auto",
        help=(
            "AstrBot task command coverage: auto runs /y do when Native Agent is "
            "ready, require fails if it is not ready, skip records bridge-only "
            "command coverage."
        ),
    )
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)

    try:
        report = run_smoke(args)
    except Exception as exc:
        report = {
            "ok": False,
            "complete": False,
            "bridge_url": args.bridge_url.rstrip("/"),
            **_report_metadata(args),
            "checks": [],
            "error": _redacted_error(exc),
        }

    if args.report_json is not None:
        _write_report(args.report_json, report)
        print(f"external integration smoke report: {args.report_json}")

    for check in report.get("checks", []):
        print(f"{check.get('id')}: {check.get('status')}")
        if check.get("error"):
            print(f"- {check['error']}")
    missing_required = report.get("missing_required_check_ids")
    if isinstance(missing_required, list) and missing_required:
        print(
            "external integration smoke missing required checks: "
            + ", ".join(str(check_id) for check_id in missing_required)
        )
    readiness = report.get("readiness")
    if isinstance(readiness, dict):
        print(f"external integration smoke readiness: {readiness.get('status')}")
        completion_blockers = readiness.get("completion_blockers")
        if isinstance(completion_blockers, list) and completion_blockers:
            print(
                "external integration smoke completion blockers: "
                + ", ".join(str(item) for item in completion_blockers)
            )
        next_actions = readiness.get("next_actions")
        if isinstance(next_actions, list) and next_actions:
            print("external integration smoke next actions:")
            for action in next_actions:
                print(f"- {action}")
        recommended = str(readiness.get("recommended_full_command") or "").strip()
        if recommended and readiness.get("signoff_ready") is not True:
            print("external integration smoke recommended full command:")
            print(recommended)
    if not report.get("checks") and report.get("error"):
        print(f"external integration smoke: failed\n- {report['error']}")
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
