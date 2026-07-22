#!/usr/bin/env python3
"""Collect auditable packaged macOS background-provider acceptance evidence.

The collector never changes TCC settings.  Run it once for each user-controlled
permission state (``authorized``, ``denied``, then ``restored``), passing the
previous report with ``--merge``.  A final ``passed`` report is emitted only
when all three phases belong to the exact same installed app and every runtime
claim is backed by a concrete Bridge, Planner, Studio, or observer receipt.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import plistlib
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

SCHEMA_VERSION = "oha-yachiyo.daily-provider-acceptance.v2"
EVIDENCE_SOURCE = "local_packaged_tcc_acceptance"
COLLECTOR_VERSION = "3"
EXPECTED_BUNDLE_ID = "io.github.arisataki.oha-yachiyo"
EXPECTED_APP_PATH = Path("/Applications/Oha-Yachiyo.app")
EXPECTED_PROVIDER_ID = "cua-driver"
EXPECTED_PROVIDER_KIND = "background_desktop"
EXPECTED_PROVIDER_SOURCE = "cua_mcp_electron_bridge"
EXPECTED_PROVIDER_TRANSPORT = "electron_bridge"
TERMINAL_TASK_STATUSES = {
    "blocked",
    "cancelled",
    "completed",
    "denied",
    "expired",
    "failed",
    "rejected",
}
APPROVAL_TASK_STATUSES = {"approval_required", "waiting_approval"}
PERMISSION_BLOCKERS = {
    "desktop_permission_accessibility_required",
    "desktop_permission_screen_recording_required",
}
AUTHORIZED_CHECK_NAMES = (
    "packaged_bridge_ready",
    "background_launch_verified",
    "target_bound_observation_verified",
    "background_input_verified",
    "postcondition_verified",
    "foreground_app_unchanged",
    "pointer_not_taken_over",
    "keyboard_not_taken_over",
)
ALL_CHECK_NAMES = (*AUTHORIZED_CHECK_NAMES, "permission_denial_fails_closed")
ALLOWED_TOOLS = (
    "desktop.list_apps",
    "app.open",
    "desktop.ui_elements",
    "desktop.type_into_ui_element",
    "desktop.verify",
)
ACCEPTANCE_RUNTIME_TOOL_SEQUENCES = (
    ALLOWED_TOOLS,
    (
        "desktop.list_apps",
        "app.open",
        "desktop.inspect_app",
        "app.open_and_type_into_ui_element",
        "desktop.verify",
    ),
)
PRIVATE_RUNTIME_APPROVAL_FIELDS = {
    "approval_request_fingerprint",
    "decision_id",
    "plan_id",
    "planner_step_id",
    "planning_reason",
    "request_fingerprint",
    "request_id",
    "runtime_execution_envelope",
    "runtime_execution_metadata",
    "source",
    "step_id",
    "tool_plan_id",
}
ACCEPTANCE_TEXT_TARGET = "First Text View"
ACCEPTANCE_TEXT_ROLE = "text area"
OBSERVATION_TOOLS = {
    "desktop.active_window",
    "desktop.inspect_app",
    "desktop.read_ui",
    "desktop.ui_elements",
    "desktop.verify",
    "desktop.windows",
}
INPUT_TOOLS = {"desktop.safe_type_text", "desktop.type_into_ui_element"}
LAUNCH_TOOLS = {"app.open", "desktop.open_app"}
_FINGERPRINT_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
_SECRET_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|secret|session[_-]?token|api[_-]?key|bridge[_-]?token)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{16,}|bearer\s+[a-z0-9._~+/-]{12,})"
)
_LAUNCH_SERVICES_JXA = r"""
ObjC.import('AppKit');
ObjC.import('Foundation');

const source = $.NSProcessInfo.processInfo.environment;
const appPathValue = source.objectForKey('OHA_YACHIYO_ACCEPTANCE_APP_PATH');
const resultPathValue = source.objectForKey('OHA_YACHIYO_ACCEPTANCE_LAUNCH_RESULT_PATH');
if (!appPathValue) throw new Error('acceptance app path is missing');
if (!resultPathValue) throw new Error('acceptance launch result path is missing');

const applicationEnvironment = $.NSMutableDictionary.dictionary;
[
  'HOME',
  'TMPDIR',
  'LANG',
  'LC_ALL',
  'LC_CTYPE',
  'USER',
  'LOGNAME',
  'PATH',
  'OHA_YACHIYO_HOME',
  'OHA_YACHIYO_BRIDGE_URL',
  'OHA_YACHIYO_BRIDGE_TOKEN',
  'OHA_YACHIYO_DESKTOP_SMOKE_MODE',
  'OHA_YACHIYO_ELECTRON_SMOKE_ROOT',
].forEach(function (key) {
  const value = source.objectForKey(key);
  const unwrapped = ObjC.unwrap(value);
  if (typeof unwrapped === 'string' && unwrapped.length > 0) {
    applicationEnvironment.setObjectForKey(value, key);
  }
});

const appURL = $.NSURL.fileURLWithPath(ObjC.unwrap(appPathValue));
const appBundle = $.NSBundle.bundleWithURL(appURL);
const bundleIdentifier = ObjC.unwrap(appBundle.bundleIdentifier);
if (typeof bundleIdentifier !== 'string' || bundleIdentifier.length === 0) {
  throw new Error('acceptance app bundle identifier is missing');
}
function runningPidsForBundle() {
  const applications = $.NSWorkspace.sharedWorkspace.runningApplications;
  const pids = [];
  for (let index = 0; index < Number(applications.count); index += 1) {
    const candidate = applications.objectAtIndex(index);
    const candidateBundleIdentifier = ObjC.unwrap(candidate.bundleIdentifier);
    const candidatePid = Number(candidate.processIdentifier);
    if (candidateBundleIdentifier === bundleIdentifier && candidatePid > 0) {
      pids.push(candidatePid);
    }
  }
  return pids;
}
const preexistingPids = new Set(runningPidsForBundle());
const launchConfiguration = $.NSMutableDictionary.dictionary;
launchConfiguration.setObjectForKey(
  applicationEnvironment,
  $.NSWorkspaceLaunchConfigurationEnvironment,
);
const launchOptions = Number($.NSWorkspaceLaunchNewInstance)
  + Number($.NSWorkspaceLaunchWithoutActivation);
const launchError = Ref();
const application = $.NSWorkspace.sharedWorkspace.launchApplicationAtURLOptionsConfigurationError(
  appURL,
  launchOptions,
  launchConfiguration,
  launchError,
);
const unwrappedApplication = ObjC.unwrap(application);
if (typeof unwrappedApplication === 'undefined') {
  throw new Error('Launch Services returned no application');
}
let launchedPid = Number(application.processIdentifier);
const pidDeadline = Date.now() + 5000;
while (
  (launchedPid <= 0 || preexistingPids.has(launchedPid))
  && Date.now() < pidDeadline
) {
  const candidates = runningPidsForBundle().filter(function (pid) {
    return !preexistingPids.has(pid);
  });
  if (candidates.length > 0) {
    launchedPid = candidates[candidates.length - 1];
    break;
  }
  delay(0.05);
  launchedPid = Number(application.processIdentifier);
}
if (launchedPid <= 0) {
  throw new Error('Launch Services returned no application pid: ' + String(launchedPid));
}
const writeError = Ref();
const wroteResult = $.NSString.stringWithString(String(launchedPid))
  .writeToFileAtomicallyEncodingError(
    ObjC.unwrap(resultPathValue),
    true,
    $.NSUTF8StringEncoding,
    writeError,
  );
if (!wroteResult) throw new Error('failed to persist Launch Services application pid');
'ok';
"""
_LAUNCH_ENVIRONMENT_KEYS = (
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "USER",
    "LOGNAME",
)


class CollectorError(RuntimeError):
    """A fail-closed acceptance collection error."""


class ManagedProcess(Protocol):
    pid: int
    returncode: int | None

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class TrackedApplicationProcess:
    """Minimal process handle for an app launched by Launch Services."""

    def __init__(self, pid: int) -> None:
        if pid <= 0:
            raise ValueError("application pid must be positive")
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            self.returncode = 0
        except PermissionError:
            return None
        return self.returncode

    def _signal(self, selected: signal.Signals) -> None:
        if self.poll() is not None:
            return
        try:
            os.kill(self.pid, selected)
        except ProcessLookupError:
            self.returncode = -int(selected)

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.05)


@dataclass(frozen=True)
class HttpResult:
    method: str
    path: str
    status_code: int
    payload: Any
    raw: bytes
    received_at: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def evidence(self, *, summary: Any | None = None) -> dict[str, Any]:
        selected = sanitize_evidence(self.payload if summary is None else summary)
        return {
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "received_at": self.received_at,
            "raw_size_bytes": len(self.raw),
            "raw_sha256": sha256_bytes(self.raw),
            "summary": selected,
            "summary_sha256": sha256_json(selected),
        }


@dataclass
class OwnedPackagedApp:
    process: ManagedProcess
    bridge_url: str
    bridge_token: str
    smoke_root: Path
    started_at: str

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                except OSError:
                    pass
                self.process.wait(timeout=5)
        shutil.rmtree(self.smoke_root, ignore_errors=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_evidence(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY_RE.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_evidence(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_evidence(item, key=key) for item in value]
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        return _SECRET_VALUE_RE.sub("<redacted>", value)
    return value


def canonical_evidence_digest(report: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "evidence_digest"}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield path, value
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _nested_bool(value: Mapping[str, Any], key: str) -> bool | None:
    direct = value.get(key)
    if isinstance(direct, bool):
        return direct
    for container in (
        "data",
        "desktop_execution_provider_evidence",
        "desktop_execution_provider_transport",
        "observed_target",
        "verification_evidence",
    ):
        nested = value.get(container)
        if isinstance(nested, Mapping) and isinstance(nested.get(key), bool):
            return bool(nested[key])
    return None


def _nested_text(value: Mapping[str, Any], key: str) -> str:
    direct = value.get(key)
    if direct is not None and not isinstance(direct, (Mapping, list)):
        return str(direct).strip()
    for container in (
        "data",
        "desktop_execution_provider_evidence",
        "desktop_execution_provider_transport",
        "observed_target",
    ):
        nested = value.get(container)
        if isinstance(nested, Mapping) and nested.get(key) is not None:
            return str(nested[key]).strip()
    return ""


def _identity_pairs(value: Mapping[str, Any]) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for _path, record in _walk(value):
        pid = _positive_int(record.get("target_pid") or record.get("pid"))
        window_id = _positive_int(
            record.get("target_window_id")
            or record.get("window_id")
            or record.get("windowId")
        )
        if pid is not None and window_id is not None:
            pairs.add((pid, window_id))
    return pairs


def _only_identity(value: Mapping[str, Any]) -> tuple[int, int] | None:
    pairs = _identity_pairs(value)
    return next(iter(pairs)) if len(pairs) == 1 else None


def _bound_target_identity(value: Mapping[str, Any]) -> tuple[int, int] | None:
    """Prefer the provider's explicit bound target over diagnostic window lists."""

    candidates: list[Mapping[str, Any]] = [value]
    for key in ("data", "desktop_execution_provider_evidence"):
        candidate = value.get(key)
        if isinstance(candidate, Mapping):
            candidates.append(candidate)
    for candidate in candidates:
        pid = _positive_int(candidate.get("target_pid") or candidate.get("pid"))
        window_id = _positive_int(
            candidate.get("target_window_id")
            or candidate.get("window_id")
            or candidate.get("windowId")
        )
        if pid is not None and window_id is not None:
            return pid, window_id
    return _only_identity(value)


def _contains_exact_marker(value: Any, marker: str) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_exact_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_marker(item, marker) for item in value)
    if isinstance(value, str):
        if value == marker:
            return True
        digits = re.sub(r"[^0-9]", "", value)
        return bool(digits and digits == marker)
    return False


def _collect_strings(value: Any, key: str) -> list[str]:
    found: list[str] = []
    for _path, record in _walk(value):
        item = record.get(key)
        if isinstance(item, str) and item.strip():
            found.append(item.strip())
        elif isinstance(item, list):
            found.extend(str(entry).strip() for entry in item if str(entry).strip())
    return list(dict.fromkeys(found))


def provider_health_observation(payload: Any) -> dict[str, Any]:
    candidates: list[tuple[int, str, Mapping[str, Any]]] = []
    for path, record in _walk(payload):
        if str(record.get("provider_id") or "").strip() != EXPECTED_PROVIDER_ID:
            continue
        health = record.get("health") if isinstance(record.get("health"), Mapping) else {}
        score = 0
        score += 8 if health.get("checked") is True else 0
        score += 4 if "available" in record else 0
        score += 2 if record.get("source") == EXPECTED_PROVIDER_SOURCE else 0
        score += 1 if record.get("provider_kind") == EXPECTED_PROVIDER_KIND else 0
        candidates.append((score, path, record))
    if not candidates:
        return {
            "checked": False,
            "ok": False,
            "status": "missing",
            "provider_id": EXPECTED_PROVIDER_ID,
            "provider_kind": EXPECTED_PROVIDER_KIND,
            "source": EXPECTED_PROVIDER_SOURCE,
            "transport": EXPECTED_PROVIDER_TRANSPORT,
            "blocking_conditions": ["cua_provider_health_evidence_missing"],
            "permission_blockers": [],
            "host_attribution_verified": False,
            "evidence_path": "",
            "snapshot": {},
        }
    _score, path, source = max(candidates, key=lambda item: item[0])
    health = source.get("health") if isinstance(source.get("health"), Mapping) else {}
    blockers = list(dict.fromkeys(
        _collect_strings(source, "blocking_conditions")
    ))
    transport = str(source.get("transport") or health.get("transport") or "").strip()
    snapshot = sanitize_evidence(
        {
            "available": source.get("available"),
            "adapter_ready": source.get("adapter_ready"),
            "provider_id": source.get("provider_id"),
            "provider_kind": source.get("provider_kind"),
            "source": source.get("source"),
            "transport": transport,
            "desktop_session_kind": source.get("desktop_session_kind"),
            "foreground_takeover_required": source.get("foreground_takeover_required"),
            "supported_tools": source.get("supported_tools") or health.get("supported_tools") or [],
            "health": {
                "ok": health.get("ok"),
                "checked": health.get("checked"),
                "status": health.get("status"),
                "blocking_conditions": health.get("blocking_conditions") or [],
                "transport": health.get("transport"),
            },
        }
    )
    host_attribution_verified = bool(
        source.get("source") == EXPECTED_PROVIDER_SOURCE
        and transport == EXPECTED_PROVIDER_TRANSPORT
        and health.get("checked") is True
        and "cua_embedded_host_attribution_failed" not in blockers
    )
    healthy = bool(
        source.get("provider_kind") == EXPECTED_PROVIDER_KIND
        and source.get("available") is True
        and source.get("adapter_ready") is True
        and source.get("foreground_takeover_required") is False
        and health.get("checked") is True
        and health.get("ok") is True
        and str(health.get("status") or "") == "healthy"
        and not blockers
        and host_attribution_verified
    )
    return {
        "checked": health.get("checked") is True,
        "ok": healthy,
        "status": str(health.get("status") or ""),
        "provider_id": str(source.get("provider_id") or ""),
        "provider_kind": str(source.get("provider_kind") or ""),
        "source": str(source.get("source") or ""),
        "transport": transport,
        "host_attribution_verified": host_attribution_verified,
        "permission_blockers": sorted(PERMISSION_BLOCKERS.intersection(blockers)),
        "blocking_conditions": blockers,
        "evidence_path": path,
        "snapshot": snapshot,
        "snapshot_sha256": sha256_json(snapshot),
    }


def _tool_receipts(timeline: Any, events: Any) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root_name, payload in (("timeline", timeline), ("events", events)):
        for path, record in _walk(payload):
            tool = str(record.get("tool_name") or record.get("tool") or "").strip()
            output = record.get("output_preview")
            if not isinstance(output, Mapping):
                output = record.get("result") if isinstance(record.get("result"), Mapping) else None
            if not tool or not isinstance(output, Mapping):
                continue
            tool_call_id = str(record.get("tool_call_id") or record.get("id") or "").strip()
            identity = tool_call_id or sha256_json([tool, output, record.get("input_preview")])
            if identity in seen:
                continue
            seen.add(identity)
            receipt = sanitize_evidence(
                {
                    "sequence": len(receipts),
                    "source": root_name,
                    "evidence_path": path,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool,
                    "status": str(record.get("status") or "").strip(),
                    "input_preview": record.get("input_preview") or record.get("input") or {},
                    "output_preview": dict(output),
                }
            )
            receipt["receipt_sha256"] = sha256_json(receipt)
            receipts.append(receipt)
    return receipts


def _receipt_output(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    value = receipt.get("output_preview")
    return value if isinstance(value, Mapping) else {}


def _background_transport_ok(output: Mapping[str, Any]) -> bool:
    transport = output.get("desktop_execution_provider_transport")
    if not isinstance(transport, Mapping):
        return False
    return bool(
        transport.get("provider_id") == EXPECTED_PROVIDER_ID
        and transport.get("provider_kind") == EXPECTED_PROVIDER_KIND
        and transport.get("transport") == EXPECTED_PROVIDER_TRANSPORT
        and transport.get("delivery_mode") == "background"
        and transport.get("foreground_takeover_required") is False
    )


def _grounded_input_matches_target(
    output: Mapping[str, Any], target: tuple[int, int] | None
) -> bool:
    grounded = output.get("grounded_element")
    if not isinstance(grounded, Mapping) or target is None:
        return False
    return bool(
        _only_identity(grounded) == target
        and str(grounded.get("selector_type") or "")
        in {"element_index", "element_token"}
        and "x" not in grounded
        and "y" not in grounded
    )


def _has_foreground_violation(value: Any) -> bool:
    # Provider status payloads intentionally advertise every available route,
    # including supervised foreground fallbacks that were not selected.  Only
    # execution evidence may prove a takeover; diagnostic alternatives must
    # not turn a background receipt into a false positive.
    def execution_records(item: Any) -> Iterable[Mapping[str, Any]]:
        if isinstance(item, Mapping):
            yield item
            for key, nested in item.items():
                if str(key) in {
                    "health",
                    "launch_hint",
                    "provider_contract",
                    "sandbox_provider",
                    "supported_tools",
                }:
                    continue
                yield from execution_records(nested)
        elif isinstance(item, list):
            for nested in item:
                yield from execution_records(nested)

    for record in execution_records(value):
        if any(
            record.get(key) is True
            for key in (
                "fallback_used",
                "foreground_takeover_detected",
                "foreground_takeover_required",
            )
        ):
            return True
        if str(record.get("delivery_mode") or "").strip() in {
            "foreground",
            "user_foreground",
        }:
            return True
        if str(record.get("desktop_scope") or "").strip() == "user_foreground":
            return True
    return False


def observer_checks(observer: Mapping[str, Any], *, target_pid: int | None) -> dict[str, bool]:
    samples = observer.get("samples") if isinstance(observer.get("samples"), list) else []
    frontmost = [
        sample.get("frontmost")
        for sample in samples
        if isinstance(sample, Mapping) and isinstance(sample.get("frontmost"), Mapping)
    ]
    cursors = [
        sample.get("cursor")
        for sample in samples
        if isinstance(sample, Mapping) and isinstance(sample.get("cursor"), Mapping)
    ]
    identities = {
        _frontmost_app_identity(item)
        for item in frontmost
        if _frontmost_app_identity(item) is not None
    }
    foreground_unchanged = bool(
        len(samples) >= 2
        and len(frontmost) == len(samples)
        and len(identities) == 1
        and observer.get("frontmost_unchanged") is True
    )
    pointer_unchanged = bool(
        len(samples) >= 2
        and len(cursors) == len(samples)
        and isinstance(observer.get("pointer_max_delta"), (int, float))
        and float(observer["pointer_max_delta"]) <= 1.0
    )
    target_never_frontmost = bool(
        target_pid is not None
        and frontmost
        and all(_positive_int(item.get("pid")) != target_pid for item in frontmost)
    )
    return {
        "foreground_app_unchanged": foreground_unchanged and target_never_frontmost,
        "pointer_not_taken_over": pointer_unchanged,
        "keyboard_not_taken_over": foreground_unchanged and target_never_frontmost,
    }


def authorized_task_observation(
    timeline: Any,
    events: Any,
    *,
    marker: str,
    observer: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, bool], list[str]]:
    receipts = _tool_receipts(timeline, events)
    launch: dict[str, Any] = {}
    observation: dict[str, Any] = {}
    input_receipt: dict[str, Any] = {}
    verify: dict[str, Any] = {}
    target: tuple[int, int] | None = None

    for receipt in receipts:
        if receipt.get("tool_name") not in LAUNCH_TOOLS:
            continue
        output = _receipt_output(receipt)
        identity = _bound_target_identity(output)
        if (
            output.get("ok") is True
            and _nested_bool(output, "agent_owned_target") is True
            and _nested_bool(output, "self_activation_suppressed") is True
            and identity is not None
            and _background_transport_ok(output)
        ):
            launch = dict(receipt)
            target = identity
            break

    for receipt in receipts:
        if receipt.get("tool_name") not in OBSERVATION_TOOLS - {"desktop.verify"}:
            continue
        output = _receipt_output(receipt)
        if (
            output.get("ok") is True
            and _bound_target_identity(output) == target
            and _nested_bool(output, "target_bound") is True
            and _nested_bool(output, "agent_owned_target") is True
            and _nested_bool(output, "observation_verified") is True
            and _nested_bool(output, "frontmost") is False
            and _nested_text(output, "desktop_scope") == "agent_owned_background"
        ):
            observation = dict(receipt)
            break

    for receipt in receipts:
        if receipt.get("tool_name") not in INPUT_TOOLS:
            continue
        output = _receipt_output(receipt)
        input_preview = receipt.get("input_preview") if isinstance(receipt.get("input_preview"), Mapping) else {}
        if (
            output.get("ok") is True
            and _bound_target_identity(output) == target
            and _nested_bool(output, "target_bound") is True
            and _background_transport_ok(output)
            and _nested_bool(output, "action_dispatched") is True
            and _grounded_input_matches_target(output, target)
            and str(input_preview.get("text") or "") == marker
        ):
            input_receipt = dict(receipt)
            break

    input_tool_call_id = str(input_receipt.get("tool_call_id") or "").strip()
    for receipt in receipts:
        if receipt.get("tool_name") != "desktop.verify":
            continue
        output = _receipt_output(receipt)
        method = _nested_text(output, "verification_method")
        if (
            output.get("ok") is True
            and _bound_target_identity(output) == target
            and _nested_bool(output, "target_bound") is True
            and _nested_bool(output, "postcondition_verified") is True
            and _nested_bool(output, "verification_context_trusted") is True
            and method == "trusted_exact_typed_content_receipt"
            and _nested_text(output, "source_tool") == "desktop.type_into_ui_element"
            and bool(input_tool_call_id)
            and _nested_text(output, "source_tool_call_id") == input_tool_call_id
            and _nested_text(output, "verification_predicate_kind") == "exact_typed_content_present"
        ):
            verify = dict(receipt)
            break

    receipt_bundle = {
        "receipts": {
            "launch": launch,
            "observation": observation,
            "input": input_receipt,
            "verify": verify,
        }
    }
    no_foreground_violation = not _has_foreground_violation(receipts)
    monitor = observer_checks(observer, target_pid=target[0] if target else None)
    checks = {
        "background_launch_verified": bool(launch),
        "target_bound_observation_verified": bool(observation),
        "background_input_verified": bool(input_receipt),
        "postcondition_verified": bool(verify),
        "foreground_app_unchanged": monitor["foreground_app_unchanged"] and no_foreground_violation,
        "pointer_not_taken_over": monitor["pointer_not_taken_over"] and no_foreground_violation,
        "keyboard_not_taken_over": monitor["keyboard_not_taken_over"] and no_foreground_violation,
    }
    blockers = [f"authorized_{name}_failed" for name, passed in checks.items() if not passed]
    if _has_foreground_violation(receipts):
        blockers.append("authorized_foreground_fallback_detected")
    return receipt_bundle, checks, list(dict.fromkeys(blockers))


def cleanup_agent_owned_textedit(
    authorized_task: Mapping[str, Any],
    *,
    protected_pid: int,
    kill: Callable[[int, int], None] = os.kill,
) -> dict[str, Any]:
    receipts = authorized_task.get("receipts") if isinstance(authorized_task.get("receipts"), Mapping) else {}
    launch = receipts.get("launch") if isinstance(receipts.get("launch"), Mapping) else {}
    output = _receipt_output(launch)
    identity = _bound_target_identity(output)
    app_name = _nested_text(output, "app_name") or _nested_text(output, "name")
    safe = bool(
        identity is not None
        and identity[0] != protected_pid
        and _nested_bool(output, "agent_owned_target") is True
        and _nested_bool(output, "self_activation_suppressed") is True
        and app_name.casefold() == "textedit"
    )
    evidence = {
        "attempted": False,
        "terminated": False,
        "target_pid": identity[0] if identity else None,
        "target_window_id": identity[1] if identity else None,
        "identity_revalidated": safe,
    }
    if not safe or identity is None:
        return evidence
    evidence["attempted"] = True
    try:
        kill(identity[0], signal.SIGTERM)
    except OSError as exc:
        evidence["error"] = type(exc).__name__
    else:
        evidence["terminated"] = True
    return evidence


def permission_denial_observation(
    health: Mapping[str, Any],
    timeline: Any,
    events: Any,
    *,
    task_status: str,
    start_status_code: int,
) -> tuple[dict[str, Any], bool, list[str]]:
    receipts = _tool_receipts(timeline, events)
    effectful: list[dict[str, Any]] = []
    ambiguous_effect_receipts: list[dict[str, Any]] = []
    for receipt in receipts:
        output = _receipt_output(receipt)
        if receipt.get("tool_name") in LAUNCH_TOOLS | INPUT_TOOLS:
            dispatched = bool(
                output.get("ok") is True
                or _nested_bool(output, "action_dispatched") is True
                or _nested_bool(output, "agent_owned_target") is True
                or bool(_identity_pairs(output))
                or _nested_text(output, "mcp_tool") in {"launch_app", "type_text"}
            )
            if dispatched:
                effectful.append(receipt)
                continue
            explicitly_blocked = bool(
                output.get("ok") is False
                and (
                    _nested_bool(output, "blocked_by_desktop_execution_policy") is True
                    or bool(_nested_text(output, "error"))
                    or bool(_nested_text(output, "blocking_condition"))
                    or bool(output.get("blocking_conditions"))
                    or str(receipt.get("status") or "").strip().casefold()
                    in {"blocked", "denied", "failed", "rejected"}
                )
            )
            if not explicitly_blocked:
                ambiguous_effect_receipts.append(receipt)
    permission_blockers = [
        item for item in health.get("permission_blockers") or [] if item in PERMISSION_BLOCKERS
    ]
    terminal_fail_closed = bool(
        start_status_code >= 400
        or task_status in {"blocked", "denied", "failed", "rejected"}
    )
    health_snapshot = health.get("snapshot") if isinstance(health.get("snapshot"), Mapping) else {}
    raw_health = health_snapshot.get("health") if isinstance(health_snapshot.get("health"), Mapping) else {}
    passed = bool(
        permission_blockers
        and raw_health.get("checked") is True
        and raw_health.get("ok") is False
        and raw_health.get("status") == "not_ready"
        and not effectful
        and not ambiguous_effect_receipts
        and not _has_foreground_violation(receipts)
        and terminal_fail_closed
    )
    effectful_launch_receipts = [
        item for item in effectful if item.get("tool_name") in LAUNCH_TOOLS
    ]
    effectful_input_receipts = [
        item for item in effectful if item.get("tool_name") in INPUT_TOOLS
    ]
    evidence = {
        "checked": raw_health.get("checked") is True,
        "ok": False,
        "status": str(raw_health.get("status") or ""),
        "blocking_conditions": permission_blockers,
        "actual_permission_blockers": permission_blockers,
        "health_snapshot_sha256": health.get("snapshot_sha256"),
        "task_status": task_status,
        "task_start_status_code": start_status_code,
        "action_dispatched": bool(effectful),
        "tool_call_count": len(receipts),
        "tool_calls": receipts,
        "launch_receipt_present": any(
            item.get("tool_name") in LAUNCH_TOOLS for item in receipts
        ),
        "input_receipt_present": any(
            item.get("tool_name") in INPUT_TOOLS for item in receipts
        ),
        "launch_attempted": bool(effectful_launch_receipts),
        "input_attempted": bool(effectful_input_receipts),
        "foreground_fallback_used": _has_foreground_violation(receipts),
        "effectful_receipts": effectful,
        "ambiguous_effect_receipts": ambiguous_effect_receipts,
        "all_receipts_sha256": sha256_json(receipts),
        "receipt_count": len(receipts),
        "no_launch_or_input_dispatched": not effectful,
        "no_foreground_fallback": not _has_foreground_violation(receipts),
    }
    blockers = [] if passed else ["permission_denial_fail_closed_evidence_missing"]
    return evidence, passed, blockers


def _parse_lsappinfo(text: str) -> dict[str, Any]:
    def match(patterns: Sequence[str]) -> str:
        for pattern in patterns:
            found = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if found:
                return found.group(1).strip().strip('"')
        return ""

    return {
        "pid": _positive_int(match((r"\bpid\s*[:=]\s*([0-9]+)", r"\"pid\"\s*=\s*([0-9]+)"))),
        "bundle_id": match(
            (
                r'"?(?:bundleid|CFBundleIdentifier)"?\s*[:=]\s*"([^"\n]+)"',
                r"\bbundleid\s*[:=]\s*\"?([^\"\n,}]+)",
            )
        ),
        "app_name": match(
            (
                r'"?(?:name|LSDisplayName)"?\s*[:=]\s*"([^"\n]+)"',
            )
        ),
    }


def _frontmost_app_identity(value: Mapping[str, Any]) -> tuple[str, str] | None:
    bundle_id = str(value.get("bundle_id") or "").strip().casefold()
    if bundle_id:
        return ("bundle_id", bundle_id)
    app_name = str(value.get("app_name") or "").strip().casefold()
    if app_name:
        return ("app_name", app_name)
    pid = _positive_int(value.get("pid"))
    return ("pid", str(pid)) if pid is not None else None


def lsappinfo_frontmost(
    *, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    front = run(
        ["/usr/bin/lsappinfo", "front"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    asn = front.stdout.strip()
    if front.returncode != 0 or not asn or "NULL" in asn.upper():
        return {"ok": False, "source": "lsappinfo", "error": "frontmost_unavailable"}
    info = run(
        ["/usr/bin/lsappinfo", "info", "-only", "name,bundleid,pid", asn],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    parsed = _parse_lsappinfo(info.stdout)
    parsed.update({"ok": info.returncode == 0 and parsed["pid"] is not None, "source": "lsappinfo"})
    return parsed


def cursor_position() -> dict[str, Any]:
    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    try:
        core_graphics = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        core_graphics.CGEventCreate.argtypes = [ctypes.c_void_p]
        core_graphics.CGEventCreate.restype = ctypes.c_void_p
        core_graphics.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        core_graphics.CGEventGetLocation.restype = CGPoint
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        event = core_graphics.CGEventCreate(None)
        if not event:
            raise RuntimeError("CGEventCreate returned null")
        point = core_graphics.CGEventGetLocation(event)
        core_foundation.CFRelease(event)
        return {"ok": True, "source": "CoreGraphics", "x": point.x, "y": point.y}
    except Exception as exc:
        return {"ok": False, "source": "CoreGraphics", "error": type(exc).__name__}


def observer_sample(
    *,
    label: str,
    frontmost_reader: Callable[[], Mapping[str, Any]] = lsappinfo_frontmost,
    cursor_reader: Callable[[], Mapping[str, Any]] = cursor_position,
) -> dict[str, Any]:
    return sanitize_evidence(
        {
            "label": label,
            "recorded_at": utc_now(),
            "frontmost": dict(frontmost_reader()),
            "cursor": dict(cursor_reader()),
        }
    )


def finalize_observer(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    clean_samples = [sanitize_evidence(dict(sample)) for sample in samples]
    raw_frontmost = [
        sample.get("frontmost")
        for sample in clean_samples
        if isinstance(sample.get("frontmost"), Mapping)
    ]
    frontmost: list[dict[str, Any]] = []
    for item in raw_frontmost:
        pid = _positive_int(item.get("pid"))
        bundle_id = str(item.get("bundle_id") or "").strip()
        app_name = str(item.get("app_name") or "").strip()
        identity: dict[str, Any] = {}
        if pid is not None:
            identity["pid"] = pid
        if bundle_id:
            identity["bundle_id"] = bundle_id
        elif app_name:
            identity["app_name"] = app_name
        frontmost.append(identity)
    cursor_points = [
        (float(cursor["x"]), float(cursor["y"]))
        for sample in clean_samples
        for cursor in [sample.get("cursor")]
        if isinstance(cursor, Mapping)
        and isinstance(cursor.get("x"), (int, float))
        and isinstance(cursor.get("y"), (int, float))
    ]
    pointer_max_delta: float | None = None
    if len(cursor_points) == len(clean_samples) and cursor_points:
        origin_x, origin_y = cursor_points[0]
        pointer_max_delta = max(
            ((x - origin_x) ** 2 + (y - origin_y) ** 2) ** 0.5
            for x, y in cursor_points
        )
    return {
        "source": "lsappinfo+CoreGraphics",
        "frontmost_before": frontmost[0] if frontmost else {},
        "frontmost_after": frontmost[-1] if frontmost else {},
        "frontmost_samples": frontmost,
        "samples": clean_samples,
        "sample_count": len(clean_samples),
        "frontmost_unchanged": bool(
            len(clean_samples) >= 2
            and len(frontmost) == len(clean_samples)
            and all(frontmost)
            and _frontmost_app_identity(frontmost[0]) is not None
            and all(
                _frontmost_app_identity(item)
                == _frontmost_app_identity(frontmost[0])
                for item in frontmost
            )
        ),
        "pointer_max_delta": pointer_max_delta,
    }


def app_identity(app_path: Path, bridge_status: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    resolved = app_path.expanduser().resolve()
    info_path = resolved / "Contents" / "Info.plist"
    asar_path = resolved / "Contents" / "Resources" / "app.asar"
    blockers: list[str] = []
    if resolved != EXPECTED_APP_PATH:
        blockers.append("packaged_app_install_path_mismatch")
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise CollectorError(f"installed app Info.plist unreadable: {type(exc).__name__}") from exc
    executable_name = str(info.get("CFBundleExecutable") or "Oha-Yachiyo").strip()
    executable = resolved / "Contents" / "MacOS" / executable_name
    if not executable.is_file():
        blockers.append("packaged_app_executable_missing")
    if not asar_path.is_file():
        blockers.append("packaged_app_asar_missing")
    metadata = bridge_status.get("build_metadata") if isinstance(bridge_status.get("build_metadata"), Mapping) else {}
    build_revision = str(metadata.get("commit") or "").strip().lower()
    fingerprint = str(metadata.get("source_tree_fingerprint") or "").strip().lower()
    bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
    short_version = str(info.get("CFBundleShortVersionString") or "").strip()
    bundle_version = str(info.get("CFBundleVersion") or "").strip()
    if bundle_id != EXPECTED_BUNDLE_ID:
        blockers.append("packaged_app_bundle_id_mismatch")
    if not _REVISION_RE.fullmatch(build_revision):
        blockers.append("packaged_app_build_revision_invalid")
    if not _FINGERPRINT_RE.fullmatch(fingerprint):
        blockers.append("packaged_app_source_fingerprint_invalid")
    if str(metadata.get("version") or "").strip() != short_version:
        blockers.append("packaged_app_version_mismatch")
    identity = {
        "packaged_app": True,
        "path": str(resolved),
        "bundle_id": bundle_id,
        "version": short_version or bundle_version,
        "short_version": short_version,
        "bundle_version": bundle_version,
        "executable_path": str(executable),
        "executable_sha256": file_sha256(executable) if executable.is_file() else "",
        "app_asar_path": str(asar_path),
        "app_asar_sha256": file_sha256(asar_path) if asar_path.is_file() else "",
        "build_revision": build_revision,
        "source_tree_fingerprint": fingerprint,
        "build_metadata": sanitize_evidence(dict(metadata)),
        "build_metadata_sha256": sha256_json(sanitize_evidence(dict(metadata))),
    }
    identity["identity_sha256"] = sha256_json(identity)
    return identity, blockers


def allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def snapshot_model_profiles_database(
    source_runtime_home: Path,
    isolated_runtime_home: Path,
) -> bool:
    """Snapshot model configuration without sharing mutable runtime state."""

    source = source_runtime_home.expanduser() / "model-profiles.db"
    if not source.is_file():
        return False
    target = isolated_runtime_home / "model-profiles.db"
    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=5) as source_conn:
            with sqlite3.connect(target, timeout=5) as target_conn:
                source_conn.backup(target_conn)
                for table in ("model_sources", "model_profiles"):
                    columns = {
                        str(row[1])
                        for row in target_conn.execute(
                            f"PRAGMA table_info({table})"
                        ).fetchall()
                    }
                    if "api_key" in columns:
                        target_conn.execute(f"UPDATE {table} SET api_key=''")
                target_conn.commit()
        target.chmod(0o600)
    except (OSError, sqlite3.Error) as exc:
        raise CollectorError(
            f"model profile snapshot failed: {type(exc).__name__}"
        ) from exc
    return True


def launch_owned_packaged_app(
    app_path: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    process_factory: Callable[[int], ManagedProcess] = TrackedApplicationProcess,
) -> OwnedPackagedApp:
    resolved = app_path.expanduser().resolve()
    info_path = resolved / "Contents" / "Info.plist"
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    executable = resolved / "Contents" / "MacOS" / str(
        info.get("CFBundleExecutable") or "Oha-Yachiyo"
    )
    if not executable.is_file():
        raise CollectorError("installed app executable is missing")
    port = allocate_loopback_port()
    bridge_url = f"http://127.0.0.1:{port}"
    token = secrets.token_hex(32)
    smoke_root = Path(tempfile.mkdtemp(prefix="oha-daily-provider-acceptance-"))
    runtime_home = smoke_root / "oha-home"
    launch_result_path = smoke_root / "launch-result.pid"
    runtime_home.mkdir(mode=0o700)
    source_environment = dict(os.environ)
    source_runtime_home = Path(
        source_environment.get("OHA_YACHIYO_HOME") or Path.home() / ".oha-yachiyo"
    )
    snapshot_model_profiles_database(source_runtime_home, runtime_home)
    env = {
        key: value
        for key in _LAUNCH_ENVIRONMENT_KEYS
        if (value := source_environment.get(key))
    }
    env.update(
        {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "OHA_YACHIYO_ACCEPTANCE_APP_PATH": str(resolved),
            "OHA_YACHIYO_ACCEPTANCE_LAUNCH_RESULT_PATH": str(launch_result_path),
            "OHA_YACHIYO_HOME": str(runtime_home),
            "OHA_YACHIYO_BRIDGE_URL": bridge_url,
            "OHA_YACHIYO_BRIDGE_TOKEN": token,
            "OHA_YACHIYO_DESKTOP_SMOKE_MODE": "1",
            "OHA_YACHIYO_ELECTRON_SMOKE_ROOT": str(smoke_root),
        }
    )
    command = [
        "/usr/bin/osascript",
        "-l",
        "JavaScript",
        "-e",
        _LAUNCH_SERVICES_JXA,
    ]
    try:
        launch_result = run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(smoke_root, ignore_errors=True)
        raise CollectorError(
            f"Launch Services invocation failed: {type(exc).__name__}"
        ) from exc
    if launch_result.returncode != 0:
        shutil.rmtree(smoke_root, ignore_errors=True)
        raise CollectorError(
            f"Launch Services rejected the packaged app ({launch_result.returncode})"
        )
    try:
        pid_text = launch_result_path.read_text(encoding="utf-8").strip()
        launch_result_path.chmod(0o600)
    except OSError as exc:
        shutil.rmtree(smoke_root, ignore_errors=True)
        raise CollectorError("Launch Services returned no packaged app pid") from exc
    if not re.fullmatch(r"[1-9][0-9]*", pid_text):
        shutil.rmtree(smoke_root, ignore_errors=True)
        raise CollectorError("Launch Services returned an invalid packaged app pid")
    process = process_factory(int(pid_text))
    return OwnedPackagedApp(
        process=process,
        bridge_url=bridge_url,
        bridge_token=token,
        smoke_root=smoke_root,
        started_at=utc_now(),
    )


class BridgeClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 12.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise CollectorError("Bridge URL must be loopback HTTP")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> HttpResult:
        raw_body = canonical_json_bytes(body) if body is not None else b""
        headers = {"accept": "application/json"}
        if raw_body:
            headers["content-type"] = "application/json"
        if self.token:
            headers["x-oha-yachiyo-bridge-token"] = self.token
        request = Request(
            f"{self.base_url}{path}",
            data=raw_body if raw_body else None,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except (OSError, URLError) as exc:
            raise CollectorError(f"Bridge request failed for {path}: {type(exc).__name__}") from exc
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"invalid_json": True}
        return HttpResult(method.upper(), path, status, payload, raw, utc_now())


def wait_for_status(client: BridgeClient, process: subprocess.Popen[bytes], timeout: float) -> HttpResult:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CollectorError(f"packaged app exited before Bridge readiness ({process.returncode})")
        try:
            result = client.request("GET", "/status")
        except CollectorError as exc:
            last_error = str(exc)
        else:
            if result.ok and isinstance(result.payload, Mapping):
                return result
            last_error = f"HTTP {result.status_code}"
        time.sleep(0.25)
    raise CollectorError(f"packaged Bridge did not become ready: {last_error or 'timeout'}")


def wait_for_native_agent_ready(
    client: BridgeClient,
    process: subprocess.Popen[bytes],
    *,
    initial_status: HttpResult,
    timeout: float,
) -> HttpResult:
    if (
        initial_status.ok
        and isinstance(initial_status.payload, Mapping)
        and initial_status.payload.get("service") == "oha-yachiyo"
        and initial_status.payload.get("native_agent_ready") is True
    ):
        return initial_status
    deadline = time.monotonic() + timeout
    last_result = initial_status
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CollectorError(
                f"packaged app exited before Native Agent readiness ({process.returncode})"
            )
        try:
            candidate = client.request("GET", "/status")
        except CollectorError as exc:
            last_error = str(exc)
            time.sleep(0.5)
            continue
        if candidate.ok and isinstance(candidate.payload, Mapping):
            last_result = candidate
            if (
                candidate.payload.get("service") == "oha-yachiyo"
                and candidate.payload.get("native_agent_ready") is True
            ):
                return candidate
        time.sleep(0.5)
    if last_error:
        raise CollectorError(last_error)
    return last_result


def _prompt(marker: str) -> str:
    return (
        "仅使用后台 CUA provider：打开一个由 Agent 单独拥有的新 TextEdit 实例，"
        f"在文本框输入 {marker}，随后验证同一 PID/window 中存在该精确文本。"
        "禁止切换前台、禁止 foreground/local fallback、禁止移动鼠标或抢占键盘焦点。"
    )


def _direct_tool_requests(marker: str) -> list[dict[str, Any]]:
    return [
        {
            "tool": "desktop.list_apps",
            "input": {"query": "TextEdit", "limit": 40},
            "step_id": "acceptance-discover-textedit",
        },
        {
            "tool": "app.open",
            "input": {"app_name": "TextEdit", "bring_to_front": False},
            "step_id": "acceptance-open-textedit",
            "depends_on": ["acceptance-discover-textedit"],
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.ui_elements",
            "input": {"app_name": "TextEdit", "role_filter": "text", "limit": 120},
            "step_id": "acceptance-observe-textedit",
            "depends_on": ["acceptance-open-textedit"],
        },
        {
            "tool": "desktop.type_into_ui_element",
            "input": {
                "target": ACCEPTANCE_TEXT_TARGET,
                "role_filter": ACCEPTANCE_TEXT_ROLE,
                "text": marker,
            },
            "step_id": "acceptance-type-nonce",
            "depends_on": ["acceptance-observe-textedit"],
            "requires_observation": True,
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.verify",
            "input": {"app_name": "TextEdit"},
            "step_id": "acceptance-verify-nonce",
            "depends_on": ["acceptance-type-nonce"],
        },
    ]


def _runtime_execution_envelope(marker: str) -> dict[str, Any]:
    """Build the fixed, auditable provider-acceptance execution contract."""

    marker_digest = sha256_bytes(marker.encode("utf-8"))[:16]
    decision_id = f"acceptance-decision-{marker_digest}"
    plan_id = f"acceptance-plan-{marker_digest}"
    core_id = f"acceptance-core-{marker_digest}"
    workspace_id = f"acceptance-workspace-{marker_digest}"
    requests: list[dict[str, Any]] = []
    capabilities = {
        "desktop.list_apps": "desktop.app_discovery",
        "app.open": "desktop.app_control",
        "desktop.ui_elements": "desktop.app_discovery",
        "desktop.type_into_ui_element": "desktop.ui_operation",
        "desktop.verify": "desktop.app_discovery",
    }
    stages = {
        "desktop.list_apps": ("discover", "find_target_app"),
        "app.open": ("operate", "prepare_target_app"),
        "desktop.ui_elements": ("discover", "inspect_ui"),
        "desktop.type_into_ui_element": ("operate", "type_ui"),
        "desktop.verify": ("verify", "verify_result"),
    }
    for request in _direct_tool_requests(marker):
        item = dict(request)
        tool_name = str(item.pop("tool"))
        step_id = str(item.get("step_id") or "")
        runtime_stage, runtime_role = stages[tool_name]
        requests.append(
            {
                **item,
                "request_id": f"acceptance-request-{step_id}",
                "tool_name": tool_name,
                "protocol": "json_fallback",
                "decision_id": decision_id,
                "plan_id": plan_id,
                "core_id": core_id,
                "workspace_id": workspace_id,
                "intent_kind": "desktop_operation",
                "capability_id": capabilities[tool_name],
                "status": "planned",
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
                "approval_required": tool_name == "desktop.type_into_ui_element",
                "risk_level": (
                    "medium"
                    if tool_name == "desktop.type_into_ui_element"
                    else "low"
                ),
                "runtime_doctrine": "discover_operate_verify",
                "runtime_stage": runtime_stage,
                "runtime_role": runtime_role,
            }
        )
    task_core = {
        "core_id": core_id,
        "workspace": {
            "workspace_id": workspace_id,
            "title": "Packaged background TextEdit acceptance",
            "summary": "Fixed provider acceptance workspace",
            "items": [],
            "context": {},
            "source": "runtime_planner",
        },
        "todos": [
            {
                "todo_id": f"acceptance-todo-{request['step_id']}",
                "title": str(request["runtime_role"]).replace("_", " "),
                "status": "pending",
                "capability_id": request["capability_id"],
                "step_id": request["step_id"],
                "tool_name": request["tool_name"],
                "approval_required": request["approval_required"],
                "depends_on": list(request.get("depends_on") or []),
                "reason": "Packaged provider acceptance step",
                "metadata": {
                    "runtime_doctrine": request["runtime_doctrine"],
                    "runtime_stage": request["runtime_stage"],
                    "runtime_role": request["runtime_role"],
                },
            }
            for request in requests
        ],
        "checkpoints": [],
        "replan_signals": [],
        "goal_contract": {
            "contract_id": f"acceptance-goal-contract-{marker_digest}",
            "original_goal": _prompt(marker),
            "intent_kind": "desktop_operation",
            "criteria": [
                {
                    "criterion_id": f"acceptance-input-criterion-{marker_digest}",
                    "description": (
                        "Type the exact marker into the Agent-owned background "
                        "TextEdit target and verify the result"
                    ),
                    "effectful": True,
                    "required": True,
                    "response_satisfiable": False,
                    "required_capabilities": ["desktop.ui_operation"],
                    "required_effects": [],
                    "expected": {},
                    "source_step_ids": ["acceptance-type-nonce"],
                    "verifier_step_ids": ["acceptance-verify-nonce"],
                }
            ],
            "max_total_attempts": 12,
            "max_subgoal_attempts": 2,
            "source": "runtime_planner",
        },
        "source": "runtime_planner",
    }
    return {
        "envelope_id": f"acceptance-envelope-{marker_digest}",
        "decision_id": decision_id,
        "plan_id": plan_id,
        "intent_kind": "desktop_operation",
        "requests": requests,
        "task_core": task_core,
        "approvals_required": ["desktop.ui_operation"],
        "artifacts_expected": [],
        "open_questions": [],
        "route_to_studio": True,
        "runtime_doctrine": "discover_operate_verify",
        "runtime_stage_counts": {"discover": 2, "operate": 2, "verify": 1},
        "replan_signal_count": 0,
        "source": "runtime_planner",
    }


def _planner_metadata() -> dict[str, Any]:
    return {
        "source": "packaged_daily_provider_acceptance_v2",
        "launcher_mode": "acceptance",
        "prefer_background_desktop": True,
        "desktop_provider_health_probe": True,
        "desktop_provider_route_readonly": True,
        "desktop_provider_route_foreground": True,
        "runtime_planner_preflight_ui_before_action": True,
        "yachiyo_entrypoint_allowed_tools": list(ALLOWED_TOOLS),
        "desktop_execution_policy": {
            "mode": "preview_input",
            "prefer_background_desktop": True,
            "prefer_isolated_desktop": False,
            "avoid_user_foreground_takeover": True,
            "require_sandbox_for_keyboard_mouse": False,
            "allow_live_foreground": False,
        },
    }


def plan_health_probe(client: BridgeClient, marker: str) -> tuple[HttpResult, dict[str, Any]]:
    result = client.request(
        "POST",
        "/yachiyo/chat/tasks/plan",
        {
            "prompt": _prompt(marker),
            "allowed_tools": list(ALLOWED_TOOLS),
            "metadata": _planner_metadata(),
            "direct": True,
            "direct_tool_requests": _direct_tool_requests(marker),
        },
    )
    if not result.ok:
        raise CollectorError(f"Planner health probe failed with HTTP {result.status_code}")
    health = provider_health_observation(result.payload)
    return result, health


def screen_probe(client: BridgeClient) -> tuple[HttpResult, dict[str, Any]]:
    result = client.request("GET", "/screen/current")
    summary: dict[str, Any] = {"authorized": False, "status_code": result.status_code}
    if result.ok and isinstance(result.payload, Mapping):
        encoded = str(result.payload.get("image_base64") or "")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            image = b""
        summary.update(
            {
                "authorized": bool(
                    image.startswith(b"\x89PNG\r\n\x1a\n")
                    and _positive_int(result.payload.get("width"))
                    and _positive_int(result.payload.get("height"))
                ),
                "width": result.payload.get("width"),
                "height": result.payload.get("height"),
                "format": result.payload.get("format"),
                "image_size_bytes": len(image),
                "image_sha256": sha256_bytes(image) if image else "",
            }
        )
    else:
        summary["error"] = sanitize_evidence(result.payload)
    return result, summary


def _task_request(marker: str) -> dict[str, Any]:
    client_id = f"acceptance-{int(time.time())}-{secrets.token_hex(4)}"
    return {
        "prompt": _prompt(marker),
        "title": "Packaged background TextEdit acceptance",
        "metadata": {
            "source": "packaged_daily_provider_acceptance_v2",
            "launcher_mode": "acceptance",
            "client_message_id": client_id,
            "client_task_id": client_id,
            "chat_delivery_requires_task": True,
            "acceptance_marker_sha256": sha256_bytes(marker.encode("utf-8")),
        },
    }


def _task_run_id(task: Mapping[str, Any]) -> str:
    debug = task.get("runtime_debug") if isinstance(task.get("runtime_debug"), Mapping) else {}
    metadata = task.get("metadata") if isinstance(task.get("metadata"), Mapping) else {}
    for value in (
        debug.get("run_id"),
        metadata.get("run_id"),
        metadata.get("main_run_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    for call in task.get("tool_calls") or []:
        if isinstance(call, Mapping) and str(call.get("run_id") or "").strip():
            return str(call["run_id"]).strip()
    return ""


def task_evidence_summary(task: Mapping[str, Any]) -> dict[str, Any]:
    """Keep compact public failure evidence instead of only a terminal status.

    The public task snapshot is already redacted by the Bridge, but acceptance
    reports still sanitize every retained field.  Keeping the runtime request
    overlay and recent event tail makes a failed packaged run diagnosable
    without persisting the full (often hundreds-of-kilobytes) response body.
    """

    runtime_debug = (
        dict(task.get("runtime_debug"))
        if isinstance(task.get("runtime_debug"), Mapping)
        else {}
    )
    envelope = (
        task.get("runtime_execution_envelope")
        if isinstance(task.get("runtime_execution_envelope"), Mapping)
        else {}
    )
    requests: list[dict[str, Any]] = []
    for request in envelope.get("requests") or []:
        if not isinstance(request, Mapping):
            continue
        requests.append(
            {
                key: request.get(key)
                for key in (
                    "request_id",
                    "step_id",
                    "tool_name",
                    "status",
                    "blocking_conditions",
                    "desktop_execution_route",
                )
                if request.get(key) not in (None, "", [], {})
            }
        )
    recent_events: list[dict[str, Any]] = []
    raw_events = task.get("recent_events")
    if isinstance(raw_events, list):
        for event in raw_events[-20:]:
            if not isinstance(event, Mapping):
                continue
            recent_events.append(
                {
                    key: event.get(key)
                    for key in (
                        "event_type",
                        "status",
                        "title",
                        "detail",
                        "payload_preview",
                    )
                    if event.get(key) not in (None, "", [], {})
                }
            )
    payload = {
        "task_id": str(task.get("task_id") or "").strip(),
        "run_id": _task_run_id(task),
        "status": str(task.get("status") or "").strip(),
        "summary": task.get("summary") or task.get("result") or "",
        "current_step": task.get("current_step") or "",
        "progress_text": task.get("progress_text") or "",
        "needs_user_action": task.get("needs_user_action") is True,
        "pending_approval_count": len(task.get("pending_approvals") or []),
        "runtime_debug": runtime_debug,
        "runtime_requests": requests,
        "recent_events": recent_events,
        "tool_calls": _tool_receipts(task, {}),
    }
    return dict(sanitize_evidence(payload))


def _declares_foreground_execution_authority(value: Any) -> bool:
    if isinstance(value, Mapping):
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip().casefold().replace("-", "_")
            if key in {
                "allow_live_foreground",
                "allow_user_foreground_takeover",
                "desktop_allow_user_foreground_takeover",
                "foreground_takeover_required",
                "requires_foreground_takeover",
            } and raw_value is True:
                return True
            if key in {
                "desktop_execution_route",
                "delivery_mode",
                "execution_mode",
                "mode",
                "route",
            } and str(raw_value or "").strip().casefold().replace("-", "_") in {
                "foreground",
                "foreground_live",
                "live",
                "local_foreground",
                "user_foreground",
            }:
                return True
            if key == "provider_kind" and "foreground" in str(
                raw_value or ""
            ).casefold():
                return True
            if _declares_foreground_execution_authority(raw_value):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_declares_foreground_execution_authority(item) for item in value)
    return False


def _runtime_bound_pending_approval(
    task: Mapping[str, Any],
    marker: str,
    *,
    expected_task_id: str,
    expected_run_id: str,
) -> dict[str, str]:
    """Return the one approval bound to the Runtime-generated fixture plan.

    Public chat requests cannot provide Runtime execution authority.  The
    collector therefore validates the immutable envelope produced by the
    packaged Runtime itself and approves only the exact marker-input step when
    the whole discover -> open -> observe -> input -> verify plan remains in
    the narrow TextEdit acceptance scope.
    """

    task_id = str(task.get("task_id") or "").strip()
    runtime_debug = (
        task.get("runtime_debug")
        if isinstance(task.get("runtime_debug"), Mapping)
        else {}
    )
    run_id = str(runtime_debug.get("run_id") or "").strip()
    if not (
        task_id
        and run_id
        and task_id == str(expected_task_id or "").strip()
        and run_id == str(expected_run_id or "").strip()
    ):
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )

    raw_approvals = task.get("pending_approvals")
    if not (
        isinstance(raw_approvals, list)
        and len(raw_approvals) == 1
        and isinstance(raw_approvals[0], Mapping)
    ):
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )
    approval = dict(raw_approvals[0])
    envelope = (
        dict(task.get("runtime_execution_envelope"))
        if isinstance(task.get("runtime_execution_envelope"), Mapping)
        else {}
    )
    raw_requests = envelope.get("requests")
    if not (
        isinstance(raw_requests, list)
        and raw_requests
        and all(isinstance(item, Mapping) for item in raw_requests)
    ):
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )
    requests = [dict(item) for item in raw_requests]
    tool_names = tuple(
        str(item.get("tool_name") or item.get("tool") or "").strip()
        for item in requests
    )
    if tool_names not in ACCEPTANCE_RUNTIME_TOOL_SEQUENCES:
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )
    if not all(isinstance(item.get("input"), Mapping) for item in requests):
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )
    inputs = [dict(item["input"]) for item in requests]
    if tool_names == ALLOWED_TOOLS:
        expected_inputs = [
            dict(item["input"])
            for item in _direct_tool_requests(marker)
        ]
    else:
        expected_inputs = [
            {"query": "TextEdit", "limit": 20},
            {"app_name": "TextEdit"},
            {
                "app_name": "TextEdit",
                "open_if_needed": False,
                "focus": False,
                "role_filter": "text",
                "limit": 80,
            },
            {
                "app_name": "TextEdit",
                "target": "文本框",
                "role_filter": "text",
                "text": marker,
                "limit": 80,
            },
            {"app_name": "TextEdit"},
        ]
    exact_input_contract_matches = inputs == expected_inputs
    observation_input_matches = bool(
        str(inputs[2].get("app_name") or "").strip() == "TextEdit"
        and str(inputs[2].get("role_filter") or "").strip() == "text"
        and inputs[2].get("focus") is not True
        and inputs[2].get("open_if_needed") is not True
    )
    input_target = str(inputs[3].get("target") or "").strip()
    input_role = str(inputs[3].get("role_filter") or "").strip()
    input_target_matches = (input_target, input_role) in {
        (ACCEPTANCE_TEXT_TARGET, ACCEPTANCE_TEXT_ROLE),
        ("文本框", "text"),
    }
    compound_input_matches = bool(
        tool_names[3] != "app.open_and_type_into_ui_element"
        or str(inputs[3].get("app_name") or "").strip() == "TextEdit"
    )
    no_foreground_authority = not any(
        _declares_foreground_execution_authority(request)
        or request_input.get("bring_to_front") is True
        for request, request_input in zip(requests, inputs, strict=True)
    )
    semantic_plan_matches = bool(
        exact_input_contract_matches
        and str(inputs[0].get("query") or "").strip() == "TextEdit"
        and str(inputs[1].get("app_name") or "").strip() == "TextEdit"
        and inputs[1].get("bring_to_front") is not True
        and observation_input_matches
        and input_target_matches
        and compound_input_matches
        and str(inputs[3].get("text") or "") == marker
        and str(inputs[4].get("app_name") or "").strip() == "TextEdit"
        and no_foreground_authority
    )
    decision_id = str(envelope.get("decision_id") or "").strip()
    plan_id = str(envelope.get("plan_id") or "").strip()
    task_core = (
        envelope.get("task_core")
        if isinstance(envelope.get("task_core"), Mapping)
        else {}
    )
    workspace = (
        task_core.get("workspace")
        if isinstance(task_core.get("workspace"), Mapping)
        else {}
    )
    core_id = str(task_core.get("core_id") or "").strip()
    workspace_id = str(workspace.get("workspace_id") or "").strip()
    step_ids = [str(request.get("step_id") or "").strip() for request in requests]
    dependency_ids: list[tuple[str, ...]] = []
    dependencies_well_formed = True
    for request in requests:
        raw_dependencies = request.get("depends_on")
        if raw_dependencies is None:
            dependency_ids.append(())
            continue
        if not isinstance(raw_dependencies, list):
            dependencies_well_formed = False
            break
        normalized = tuple(str(item or "").strip() for item in raw_dependencies)
        if any(not item for item in normalized):
            dependencies_well_formed = False
            break
        dependency_ids.append(normalized)
    expected_dependencies = [
        () if index == 0 else (step_ids[index - 1],)
        for index in range(len(requests))
    ]
    dependencies_match = bool(
        dependencies_well_formed
        and len(set(step_ids)) == len(requests)
        and all(step_ids)
        and dependency_ids == expected_dependencies
    )
    expected = requests[3]
    expected_step_id = str(expected.get("step_id") or "").strip()
    expected_source = str(expected.get("source") or "").strip()
    expected_planning_reason = str(expected.get("planning_reason") or "").strip()
    lineage_matches = bool(
        semantic_plan_matches
        and dependencies_match
        and decision_id
        and plan_id
        and core_id
        and workspace_id
        and expected_step_id
        and expected.get("approval_required") is True
        and sum(
            request.get("approval_required") is True for request in requests
        )
        == 1
        and expected_source == "runtime_planner"
        and expected_planning_reason.startswith("planner_")
        and all(
            str(request.get("decision_id") or "").strip() == decision_id
            and str(request.get("plan_id") or "").strip() == plan_id
            and str(request.get("core_id") or "").strip() == core_id
            and str(request.get("workspace_id") or "").strip() == workspace_id
            for request in requests
        )
    )
    if not lineage_matches:
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )
    approval_id = str(approval.get("approval_id") or "").strip()
    input_preview = (
        dict(approval.get("input_preview"))
        if isinstance(approval.get("input_preview"), Mapping)
        else None
    )
    approval_task_id = str(approval.get("task_id") or "").strip()
    approval_run_id = str(approval.get("source_run_id") or "").strip()
    approval_core_id = str(approval.get("core_id") or "").strip()
    approval_workspace_id = str(approval.get("workspace_id") or "").strip()
    expected_input_preview = sanitize_evidence(inputs[3])
    leaked_private_lineage = any(
        str(key) in PRIVATE_RUNTIME_APPROVAL_FIELDS
        or "fingerprint" in str(key).casefold()
        for key in approval
    )
    public_card_matches = bool(
        approval_id
        and str(approval.get("tool") or "").strip()
        == str(expected.get("tool_name") or "").strip()
        and input_preview == expected_input_preview
        and approval_task_id == task_id
        and approval_run_id == run_id
        and approval_core_id == core_id
        and approval_workspace_id == workspace_id
        and not leaked_private_lineage
        and not _declares_foreground_execution_authority(approval)
        and input_preview is not None
        and input_preview.get("bring_to_front") is not True
    )
    if not public_card_matches:
        raise CollectorError(
            "TextEdit acceptance received an unexpected or unbound approval"
        )
    return {"approval_id": approval_id}


def run_task(
    client: BridgeClient,
    marker: str,
    *,
    timeout: float,
    sample: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    samples = [dict(sample("before_task"))]
    start = client.request("POST", "/yachiyo/chat/tasks", _task_request(marker))
    task: Mapping[str, Any] = start.payload if isinstance(start.payload, Mapping) else {}
    task_id = str(task.get("task_id") or "").strip()
    start_runtime_debug = (
        task.get("runtime_debug")
        if isinstance(task.get("runtime_debug"), Mapping)
        else {}
    )
    expected_run_id = str(start_runtime_debug.get("run_id") or "").strip()
    final_result = start
    approval_count = 0
    if start.ok and task_id:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            samples.append(dict(sample("during_task")))
            final_result = client.request("GET", f"/yachiyo/chat/tasks/{quote(task_id, safe='')}")
            task = final_result.payload if isinstance(final_result.payload, Mapping) else {}
            task_status = str(task.get("status") or "").strip().lower()
            if task_status in APPROVAL_TASK_STATUSES:
                approval_count += 1
                if approval_count > 1:
                    raise CollectorError("TextEdit acceptance requested too many approvals")
                runtime_debug = (
                    task.get("runtime_debug")
                    if isinstance(task.get("runtime_debug"), Mapping)
                    else {}
                )
                polled_run_id = str(runtime_debug.get("run_id") or "").strip()
                if not expected_run_id:
                    expected_run_id = polled_run_id
                approval = _runtime_bound_pending_approval(
                    task,
                    marker,
                    expected_task_id=task_id,
                    expected_run_id=expected_run_id,
                )
                approval_id = str(approval["approval_id"])
                final_result = client.request(
                    "POST",
                    f"/yachiyo/chat/tasks/{quote(task_id, safe='')}/approve",
                    {
                        "approval_id": approval_id,
                        "approved": True,
                        "reason": (
                            "Automated approval for the Runtime-bound packaged "
                            "acceptance plan on an Agent-owned background target."
                        ),
                        "metadata": {
                            "source": "packaged_daily_provider_acceptance_v2",
                            "runtime_bound_plan": True,
                            "approval_id": approval_id,
                        },
                    },
                )
                if not final_result.ok:
                    raise CollectorError(
                        "TextEdit acceptance approval failed with HTTP "
                        f"{final_result.status_code}"
                    )
                task = (
                    final_result.payload
                    if isinstance(final_result.payload, Mapping)
                    else {}
                )
                continue
            if task_status in TERMINAL_TASK_STATUSES:
                break
            time.sleep(0.5)
        else:
            raise CollectorError("TextEdit acceptance task timed out")
    samples.append(dict(sample("after_task")))
    run_id = _task_run_id(task)
    timeline = client.request("GET", f"/yachiyo/studio/runs/{quote(run_id, safe='')}") if run_id else None
    events = client.request("GET", f"/yachiyo/studio/runs/{quote(run_id, safe='')}/events?limit=200") if run_id else None
    return {
        "start": start,
        "final": final_result,
        "task": dict(task),
        "task_id": task_id,
        "run_id": run_id,
        "timeline": timeline,
        "events": events,
        "observer": finalize_observer(samples),
        "approval_count": approval_count,
    }


def _empty_observations() -> dict[str, Any]:
    return {
        "provider_health": {},
        "provider_health_phases": {},
        "authorized_task": {
            "receipts": {"launch": {}, "observation": {}, "input": {}, "verify": {}}
        },
        "observer": {},
        "permission_denial": {},
    }


def _phase_evidence(
    *,
    phase: str,
    status_result: HttpResult,
    screen_result: HttpResult,
    screen: Mapping[str, Any],
    plan_result: HttpResult,
    health: Mapping[str, Any],
    task_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "phase": phase,
        "status": status_result.evidence(
            summary={
                "service": status_result.payload.get("service") if isinstance(status_result.payload, Mapping) else None,
                "version": status_result.payload.get("version") if isinstance(status_result.payload, Mapping) else None,
                "native_agent_ready": status_result.payload.get("native_agent_ready") if isinstance(status_result.payload, Mapping) else None,
                "build_metadata": status_result.payload.get("build_metadata") if isinstance(status_result.payload, Mapping) else {},
            }
        ),
        "screen": screen_result.evidence(summary=screen),
        "planner_health": plan_result.evidence(summary=health),
    }
    if task_result is not None:
        start = task_result["start"]
        final = task_result["final"]
        timeline = task_result.get("timeline")
        events = task_result.get("events")
        evidence["task_start"] = start.evidence(
            summary={"task_id": task_result.get("task_id"), "run_id": task_result.get("run_id"), "status": task_result.get("task", {}).get("status")}
        )
        evidence["task_final"] = final.evidence(
            summary=task_evidence_summary(task_result.get("task", {}))
        )
        if isinstance(timeline, HttpResult):
            evidence["studio_timeline"] = timeline.evidence(
                summary={"run_id": task_result.get("run_id"), "tool_calls": _tool_receipts(timeline.payload, {})}
            )
        if isinstance(events, HttpResult):
            evidence["studio_events"] = events.evidence(
                summary={"run_id": task_result.get("run_id"), "event_receipts": _tool_receipts({}, events.payload)}
            )
    evidence["evidence_sha256"] = sha256_json(evidence)
    return evidence


def merge_phase_report(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if previous is not None and previous.get("schema_version") != SCHEMA_VERSION:
        raise CollectorError("merge report schema mismatch")
    if previous is not None:
        old_identity = previous.get("app_identity") if isinstance(previous.get("app_identity"), Mapping) else {}
        new_identity = current.get("app_identity") if isinstance(current.get("app_identity"), Mapping) else {}
        if old_identity.get("identity_sha256") != new_identity.get("identity_sha256"):
            raise CollectorError("merge report app identity mismatch")

    phases = dict(previous.get("phases") or {}) if previous else {}
    phase = str(current.get("collector", {}).get("phase") or "")
    phases[phase] = current.get("phase_evidence") or {}
    observations = _empty_observations()
    if previous and isinstance(previous.get("observations"), Mapping):
        observations.update(dict(previous["observations"]))
    current_observations = current.get("observations") if isinstance(current.get("observations"), Mapping) else {}
    if current_observations.get("provider_health"):
        provider_by_phase = dict(observations.get("provider_health_phases") or {})
        provider_by_phase[phase] = current_observations["provider_health"]
        observations["provider_health_phases"] = provider_by_phase
        if phase == "authorized" or not observations.get("provider_health"):
            observations["provider_health"] = current_observations["provider_health"]
    if phase == "authorized":
        observations["authorized_task"] = current_observations.get("authorized_task") or observations["authorized_task"]
        observations["observer"] = current_observations.get("observer") or observations["observer"]
    if phase == "denied":
        observations["permission_denial"] = current_observations.get("permission_denial") or {}

    phase_checks = dict(previous.get("phase_checks") or {}) if previous else {}
    phase_checks[phase] = dict(current.get("checks") or {})
    authorized_checks = phase_checks.get("authorized", {})
    denied_checks = phase_checks.get("denied", {})
    restored_checks = phase_checks.get("restored", {})
    checks = {
        name: bool(authorized_checks.get(name)) for name in AUTHORIZED_CHECK_NAMES
    }
    checks["permission_denial_fails_closed"] = bool(
        denied_checks.get("permission_denial_fails_closed")
    )
    restored = bool(
        restored_checks.get("packaged_bridge_ready")
        and restored_checks.get("permissions_restored")
    )
    complete = all(checks.values()) and restored
    blockers = [f"acceptance_{name}_failed" for name, passed in checks.items() if not passed]
    if not restored:
        blockers.append("acceptance_permissions_restored_evidence_missing")
    bridge_status = dict(current.get("bridge_status") or {})
    bridge_status["phases"] = {
        key: value.get("bridge_status", {})
        for key, value in phases.items()
        if isinstance(value, Mapping)
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if complete else "partial",
        "evidence_source": EVIDENCE_SOURCE,
        "recorded_at": utc_now(),
        "collector": current["collector"],
        "app_identity": current["app_identity"],
        "bridge_status": bridge_status,
        "observations": observations,
        "phases": phases,
        "phase_checks": phase_checks,
        "checks": checks,
        "blocking_conditions": list(dict.fromkeys(blockers)),
        "provider_kind": EXPECTED_PROVIDER_KIND,
        "provider_id": EXPECTED_PROVIDER_ID,
        "desktop_session_kind": EXPECTED_PROVIDER_KIND,
        "transport": "cua_mcp_electron_bridge",
        "packaged_app": True,
        "packaged_app_path": current["app_identity"]["path"],
        "build_revision": current["app_identity"]["build_revision"],
        "host_bundle_id": current["app_identity"]["bundle_id"],
        "host_attribution_verified": bool(
            (observations.get("provider_health") or {}).get("host_attribution_verified")
        ),
        "foreground_takeover_required": False,
        "tcc": {
            "accessibility": "authorized" if authorized_checks.get("provider_health_authorized") else "unknown",
            "screen_recording": "authorized" if authorized_checks.get("screen_recording_authorized") else "unknown",
            "restored": restored,
        },
    }
    report["evidence_digest"] = canonical_evidence_digest(report)
    return report


def collect_phase(
    phase: str,
    *,
    app_path: Path,
    timeout: float,
    previous: Mapping[str, Any] | None = None,
    marker: str | None = None,
) -> dict[str, Any]:
    if phase not in {"authorized", "denied", "restored"}:
        raise CollectorError("phase must be authorized, denied, or restored")
    marker = marker or f"{secrets.randbelow(90_000_000) + 10_000_000}"
    owned = launch_owned_packaged_app(app_path)
    try:
        client = BridgeClient(owned.bridge_url, owned.bridge_token)
        status_result = wait_for_status(client, owned.process, timeout=min(timeout, 45.0))
        status_result = wait_for_native_agent_ready(
            client,
            owned.process,
            initial_status=status_result,
            timeout=min(timeout, 20.0),
        )
        status_payload = status_result.payload if isinstance(status_result.payload, Mapping) else {}
        identity, identity_blockers = app_identity(app_path, status_payload)
        bridge_ready = bool(
            status_result.ok
            and status_payload.get("service") == "oha-yachiyo"
            and status_payload.get("native_agent_ready") is True
            and not identity_blockers
        )
        bridge_status = {
            "ready": bridge_ready,
            "version": status_payload.get("version"),
            "build_metadata": sanitize_evidence(
                dict(status_payload.get("build_metadata") or {})
            ),
            "bridge_url": owned.bridge_url,
            "owned_process_pid": owned.process.pid,
            "owned_process_alive": owned.process.poll() is None,
            "started_at": owned.started_at,
            "token_recorded": False,
            "status_evidence_sha256": sha256_bytes(status_result.raw),
        }
        screen_result, screen = screen_probe(client)
        plan_result, health = plan_health_probe(client, marker)
        observations = _empty_observations()
        observations["provider_health"] = health
        checks: dict[str, bool] = {
            "packaged_bridge_ready": bridge_ready,
            "provider_health_authorized": health.get("ok") is True,
            "screen_recording_authorized": screen.get("authorized") is True,
        }
        blockers = list(identity_blockers)
        task_result: dict[str, Any] | None = None

        if phase == "authorized":
            if health.get("ok") is not True or screen.get("authorized") is not True:
                blockers.append("authorized_tcc_precondition_failed")
            else:
                task_result = run_task(
                    client,
                    marker,
                    timeout=timeout,
                    sample=lambda label: observer_sample(label=label),
                )
                timeline_payload = task_result["timeline"].payload if isinstance(task_result.get("timeline"), HttpResult) else {}
                events_payload = task_result["events"].payload if isinstance(task_result.get("events"), HttpResult) else {}
                task_observation, task_checks, task_blockers = authorized_task_observation(
                    timeline_payload,
                    events_payload,
                    marker=marker,
                    observer=task_result["observer"],
                )
                cleanup = cleanup_agent_owned_textedit(
                    task_observation,
                    protected_pid=owned.process.pid,
                )
                task_observation["cleanup"] = cleanup
                if task_observation.get("receipts", {}).get("launch") and not cleanup.get(
                    "terminated"
                ):
                    task_blockers.append("authorized_agent_owned_target_cleanup_failed")
                observations["authorized_task"] = task_observation
                observations["observer"] = task_result["observer"]
                checks.update(task_checks)
                blockers.extend(task_blockers)
        elif phase == "denied":
            if health.get("permission_blockers"):
                task_result = run_task(
                    client,
                    marker,
                    timeout=timeout,
                    sample=lambda label: observer_sample(label=label),
                )
                timeline_payload = task_result["timeline"].payload if isinstance(task_result.get("timeline"), HttpResult) else {}
                events_payload = task_result["events"].payload if isinstance(task_result.get("events"), HttpResult) else {}
                denial, passed, denial_blockers = permission_denial_observation(
                    health,
                    timeline_payload,
                    events_payload,
                    task_status=str(task_result.get("task", {}).get("status") or ""),
                    start_status_code=task_result["start"].status_code,
                )
                observations["permission_denial"] = denial
                checks["permission_denial_fails_closed"] = passed
                blockers.extend(denial_blockers)
            else:
                checks["permission_denial_fails_closed"] = False
                blockers.append("actual_permission_denial_blocker_missing")
        else:
            checks["permissions_restored"] = bool(
                health.get("ok") is True and screen.get("authorized") is True
            )
            if not checks["permissions_restored"]:
                blockers.append("restored_tcc_precondition_failed")

        phase_evidence = _phase_evidence(
            phase=phase,
            status_result=status_result,
            screen_result=screen_result,
            screen=screen,
            plan_result=plan_result,
            health=health,
            task_result=task_result,
        )
        phase_evidence.update(
            {
                "bridge_status": bridge_status,
                "checks": checks,
                "blocking_conditions": list(dict.fromkeys(blockers)),
                "observations_sha256": sha256_json(observations),
            }
        )
        current = {
            "collector": {
                "name": Path(__file__).name,
                "version": COLLECTOR_VERSION,
                "phase": phase,
                "source_sha256": file_sha256(Path(__file__)),
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "changes_tcc_settings": False,
            },
            "app_identity": identity,
            "bridge_status": bridge_status,
            "observations": observations,
            "checks": checks,
            "phase_evidence": phase_evidence,
        }
        return merge_phase_report(current, previous)
    finally:
        owned.close()


def _read_merge(path: Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError(f"merge report unreadable: {type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise CollectorError("merge report must be a JSON object")
    if payload.get("evidence_digest") != canonical_evidence_digest(payload):
        raise CollectorError("merge report evidence digest mismatch")
    return payload


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("authorized", "denied", "restored"))
    parser.add_argument("--app", type=Path, default=Path("/Applications/Oha-Yachiyo.app"))
    parser.add_argument("--merge", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--marker", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = collect_phase(
            args.phase,
            app_path=args.app,
            timeout=max(10.0, min(float(args.timeout), 600.0)),
            previous=_read_merge(args.merge),
            marker=args.marker,
        )
    except CollectorError as exc:
        print(f"Acceptance collection failed: {exc}", file=sys.stderr)
        return 1
    _write_report(args.output, report)
    print(
        f"Collected {args.phase} evidence: status={report['status']} output={args.output}"
    )
    return 0 if report["status"] in {"partial", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
