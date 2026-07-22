from __future__ import annotations

import copy
import json
import os
import plistlib
import signal
import sqlite3
import subprocess
from pathlib import Path

import pytest

from apps.shell.agent.runtime.approval_snapshots import public_pending_approval
from apps.shell.agent.tools.policy import ToolDescriptorRegistry
from apps.shell.yachiyo_agent.contracts import RuntimeExecutionEnvelopeSnapshot
from scripts import collect_packaged_daily_provider_acceptance as collector
from scripts import smoke_oha_desktop_agent_release as release_gate

TARGET = {"target_pid": 4312, "target_window_id": 9721}
TRANSPORT = {
    "provider_id": "cua-driver",
    "provider_kind": "background_desktop",
    "transport": "electron_bridge",
    "delivery_mode": "background",
    "foreground_takeover_required": False,
}


def _health_payload(*, authorized: bool = True) -> dict[str, object]:
    blockers = [] if authorized else ["desktop_permission_accessibility_required"]
    return {
        "providers": [
            {
                "provider_id": "cua-driver",
                "provider_kind": "background_desktop",
                "source": "cua_mcp_electron_bridge",
                "transport": "electron_bridge",
                "available": authorized,
                "adapter_ready": authorized,
                "foreground_takeover_required": False,
                "health": {
                    "checked": True,
                    "ok": authorized,
                    "status": "healthy" if authorized else "not_ready",
                    "blocking_conditions": blockers,
                },
            }
        ]
    }


def _observer() -> dict[str, object]:
    return collector.finalize_observer(
        [
            {
                "label": "before_task",
                "frontmost": {
                    "ok": True,
                    "source": "lsappinfo",
                    "pid": 101,
                    "bundle_id": "com.apple.finder",
                },
                "cursor": {"ok": True, "x": 10.0, "y": 20.0},
            },
            {
                "label": "after_task",
                "frontmost": {
                    "ok": True,
                    "source": "lsappinfo",
                    "pid": 101,
                    "bundle_id": "com.apple.finder",
                },
                "cursor": {"ok": True, "x": 10.5, "y": 20.0},
            },
        ]
    )


def _authorized_tool_calls(marker: str) -> list[dict[str, object]]:
    return [
        {
            "tool_call_id": "launch",
            "tool_name": "app.open",
            "status": "completed",
            "input_preview": {"app_name": "TextEdit"},
            "output_preview": {
                "ok": True,
                "app_name": "TextEdit",
                **TARGET,
                "agent_owned_target": True,
                "self_activation_suppressed": True,
                "desktop_execution_provider_transport": TRANSPORT,
            },
        },
        {
            "tool_call_id": "observe",
            "tool_name": "desktop.ui_elements",
            "status": "completed",
            "output_preview": {
                "ok": True,
                **TARGET,
                "target_bound": True,
                "agent_owned_target": True,
                "observation_verified": True,
                "frontmost": False,
                "desktop_scope": "agent_owned_background",
            },
        },
        {
            "tool_call_id": "input",
            "tool_name": "desktop.type_into_ui_element",
            "status": "completed",
            "input_preview": {"app_name": "TextEdit", "text": marker},
            "output_preview": {
                "ok": True,
                **TARGET,
                "target_bound": True,
                "action_dispatched": True,
                "grounded_element": {
                    "pid": TARGET["target_pid"],
                    "window_id": TARGET["target_window_id"],
                    "selector_type": "element_token",
                    "label": "Text Area",
                },
                "desktop_execution_provider_transport": TRANSPORT,
            },
        },
        {
            "tool_call_id": "verify",
            "tool_name": "desktop.verify",
            "status": "completed",
            "output_preview": {
                "ok": True,
                **TARGET,
                "target_bound": True,
                "postcondition_verified": True,
                "verification_context_trusted": True,
                "verification_method": "trusted_exact_typed_content_receipt",
                "source_tool": "desktop.type_into_ui_element",
                "source_tool_call_id": "input",
                "verification_predicate_kind": "exact_typed_content_present",
            },
        },
    ]


def _fixed_pending_approval(marker: str) -> dict[str, object]:
    envelope = collector._runtime_execution_envelope(marker)
    request = next(
        item
        for item in envelope["requests"]
        if item["step_id"] == "acceptance-type-nonce"
    )
    return {
        "approval_id": "approval-fixed-type",
        "status": "pending",
        "tool_name": request["tool_name"],
        "step_id": request["step_id"],
        "decision_id": envelope["decision_id"],
        "plan_id": envelope["plan_id"],
        "core_id": envelope["task_core"]["core_id"],
        "workspace_id": envelope["task_core"]["workspace"]["workspace_id"],
        "source": "runtime_planner",
        "planning_reason": "explicit_full_plan",
        "input_preview": dict(request["input"]),
    }


def _runtime_planned_pending_approval(
    marker: str,
    *,
    task_id: str = "task-1",
    run_id: str = "run-1",
) -> tuple[dict[str, object], dict[str, object]]:
    envelope = copy.deepcopy(collector._runtime_execution_envelope(marker))
    envelope["decision_id"] = "runtime-decision"
    envelope["plan_id"] = "runtime-plan"
    envelope["task_core"]["core_id"] = "runtime-core"
    envelope["task_core"]["workspace"]["workspace_id"] = "runtime-workspace"
    step_ids = {
        "acceptance-discover-textedit": "discover-desktop-state",
        "acceptance-open-textedit": "open-or-focus-app",
        "acceptance-observe-textedit": "read-foreground-ui",
        "acceptance-type-nonce": "operate-foreground-ui",
        "acceptance-verify-nonce": "verify-desktop-result",
    }
    for request in envelope["requests"]:
        request["step_id"] = step_ids[request["step_id"]]
        request["request_id"] = f"runtime-request-{request['step_id']}"
        request["decision_id"] = envelope["decision_id"]
        request["plan_id"] = envelope["plan_id"]
        request["core_id"] = envelope["task_core"]["core_id"]
        request["workspace_id"] = envelope["task_core"]["workspace"]["workspace_id"]
        request["planning_reason"] = "planner_desktop_operation"
        request["depends_on"] = [step_ids.get(item, item) for item in request.get("depends_on", [])]
    envelope["requests"][0]["input"] = {"query": "TextEdit", "limit": 20}
    envelope["requests"][1]["input"] = {"app_name": "TextEdit"}
    envelope["requests"][2]["tool_name"] = "desktop.inspect_app"
    envelope["requests"][2]["input"] = {
        "app_name": "TextEdit",
        "open_if_needed": False,
        "focus": False,
        "role_filter": "text",
        "limit": 80,
    }
    envelope["requests"][3]["tool_name"] = "app.open_and_type_into_ui_element"
    envelope["requests"][3]["input"] = {
        "app_name": "TextEdit",
        "target": "文本框",
        "role_filter": "text",
        "text": marker,
        "limit": 80,
    }
    envelope["requests"][4]["input"] = {"app_name": "TextEdit"}
    request = envelope["requests"][3]
    private_approval = {
        "approval_id": "approval-runtime-type",
        "tool": request["tool_name"],
        "input": dict(request["input"]),
        "requested_at": "2026-07-17T00:00:00+00:00",
        "tool_request": {
            **copy.deepcopy(request),
            "task_id": task_id,
            "source_run_id": run_id,
        },
    }
    return envelope, public_pending_approval(private_approval)


def _runtime_approval_task(
    envelope: dict[str, object],
    approval: dict[str, object],
    *,
    task_id: str = "task-1",
    run_id: str = "run-1",
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "status": "approval_required",
        "runtime_debug": {"run_id": run_id},
        "runtime_execution_envelope": envelope,
        "pending_approvals": [approval],
    }


def test_owned_packaged_app_isolates_runtime_home_from_installed_app(
    tmp_path,
    monkeypatch,
) -> None:
    installed_runtime_home = tmp_path / "installed-runtime-home"
    installed_runtime_home.mkdir()
    with sqlite3.connect(installed_runtime_home / "model-profiles.db") as conn:
        conn.execute("CREATE TABLE snapshot_marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO snapshot_marker VALUES ('configured-profile')")
        conn.execute(
            "CREATE TABLE model_profiles (profile_id TEXT PRIMARY KEY, api_key TEXT)"
        )
        conn.execute("INSERT INTO model_profiles VALUES ('profile-1', 'legacy-secret')")
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(installed_runtime_home))
    monkeypatch.setenv("UNRELATED_PARENT_SECRET", "must-not-reach-packaged-app")

    app_path = tmp_path / "Oha-Yachiyo.app"
    macos_dir = app_path / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    executable = macos_dir / "Oha-Yachiyo"
    executable.write_bytes(b"")
    info_path = app_path / "Contents" / "Info.plist"
    with info_path.open("wb") as handle:
        plistlib.dump({"CFBundleExecutable": executable.name}, handle)

    captured: dict[str, object] = {}

    class FinishedProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        @staticmethod
        def poll() -> int:
            return 0

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        Path(kwargs["env"]["OHA_YACHIYO_ACCEPTANCE_LAUNCH_RESULT_PATH"]).write_text(
            "4312\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
        )

    owned = collector.launch_owned_packaged_app(
        app_path,
        run=fake_run,
        process_factory=FinishedProcess,
    )
    try:
        env = captured["env"]
        assert isinstance(env, dict)
        runtime_home = Path(str(env["OHA_YACHIYO_HOME"]))
        assert runtime_home == owned.smoke_root / "oha-home"
        assert runtime_home.parent == owned.smoke_root
        assert env["OHA_YACHIYO_ELECTRON_SMOKE_ROOT"] == str(owned.smoke_root)
        assert env["OHA_YACHIYO_ACCEPTANCE_APP_PATH"] == str(app_path.resolve())
        assert "UNRELATED_PARENT_SECRET" not in env
        assert captured["args"][:4] == [
            "/usr/bin/osascript",
            "-l",
            "JavaScript",
            "-e",
        ]
        assert env["OHA_YACHIYO_BRIDGE_TOKEN"] not in " ".join(captured["args"])
        with sqlite3.connect(runtime_home / "model-profiles.db") as conn:
            assert conn.execute("SELECT value FROM snapshot_marker").fetchone() == (
                "configured-profile",
            )
            assert conn.execute(
                "SELECT api_key FROM model_profiles WHERE profile_id='profile-1'"
            ).fetchone() == ("",)
    finally:
        owned.close()


@pytest.mark.skipif(collector.sys.platform != "darwin", reason="macOS Launch Services only")
def test_launch_services_script_skips_unset_optional_environment_values(tmp_path) -> None:
    result_path = tmp_path / "launch-result.pid"
    result = subprocess.run(
        [
            "/usr/bin/osascript",
            "-l",
            "JavaScript",
            "-e",
            collector._LAUNCH_SERVICES_JXA,
        ],
        env={
            "HOME": str(Path.home()),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "OHA_YACHIYO_ACCEPTANCE_APP_PATH": str(tmp_path / "missing.app"),
            "OHA_YACHIYO_ACCEPTANCE_LAUNCH_RESULT_PATH": str(result_path),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "object cannot be nil" not in result.stderr


@pytest.mark.skipif(collector.sys.platform != "darwin", reason="macOS Launch Services only")
def test_launch_services_script_returns_pid_for_valid_background_app(tmp_path) -> None:
    app_path = tmp_path / "AcceptanceFixture.app"
    executable = app_path / "Contents" / "MacOS" / "acceptance-fixture"
    executable.parent.mkdir(parents=True)
    source = tmp_path / "AcceptanceFixture.swift"
    source.write_text(
        """
import AppKit
import Foundation

let pid = String(ProcessInfo.processInfo.processIdentifier)
try? pid.write(
    toFile: FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("launched.pid").path,
    atomically: true,
    encoding: .utf8
)
let application = NSApplication.shared
application.setActivationPolicy(.prohibited)
application.run()
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "swiftc",
            str(source),
            "-o",
            str(executable),
            "-framework",
            "AppKit",
        ],
        check=True,
        capture_output=True,
    )
    info_path = app_path / "Contents" / "Info.plist"
    with info_path.open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleExecutable": executable.name,
                "CFBundleIdentifier": "io.github.arisataki.oha-yachiyo.acceptance-fixture",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "LSBackgroundOnly": True,
            },
            handle,
        )
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app_path)],
        check=True,
        capture_output=True,
    )

    launched_pid = 0
    launch_result_path = tmp_path / "launch-result.pid"
    try:
        result = subprocess.run(
            [
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                collector._LAUNCH_SERVICES_JXA,
            ],
            env={
                "HOME": str(tmp_path),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "OHA_YACHIYO_ACCEPTANCE_APP_PATH": str(app_path),
                "OHA_YACHIYO_ACCEPTANCE_LAUNCH_RESULT_PATH": str(
                    launch_result_path
                ),
            },
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if launch_result_path.is_file():
            launched_pid = int(launch_result_path.read_text(encoding="utf-8").strip())

        assert result.returncode == 0, result.stderr
        assert launched_pid > 0
    finally:
        if launched_pid <= 0:
            matches = subprocess.run(
                ["/usr/bin/pgrep", "-f", str(executable)],
                text=True,
                capture_output=True,
                check=False,
            )
            candidate_pids = [
                int(line)
                for line in matches.stdout.splitlines()
                if line.strip().isdigit()
            ]
        else:
            candidate_pids = [launched_pid]
        for candidate_pid in candidate_pids:
            try:
                os.kill(candidate_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_fixed_execution_envelope_remains_valid_for_plan_health_probe() -> None:
    marker = "7070802"
    envelope = collector._runtime_execution_envelope(marker)
    snapshot = RuntimeExecutionEnvelopeSnapshot.model_validate(envelope)

    assert snapshot.task_core is not None
    assert snapshot.task_core.goal_contract is not None
    assert snapshot.task_core.goal_contract.original_goal == collector._prompt(marker)
    assert [item.tool_name for item in snapshot.requests] == list(
        collector.ALLOWED_TOOLS
    )
    assert [item.step_id for item in snapshot.requests] == [
        "acceptance-discover-textedit",
        "acceptance-open-textedit",
        "acceptance-observe-textedit",
        "acceptance-type-nonce",
        "acceptance-verify-nonce",
    ]
    assert all(
        item.planning_reason == "explicit_full_plan" for item in snapshot.requests
    )
    assert snapshot.requests[3].approval_required is True
    assert snapshot.requests[3].input["target"] == collector.ACCEPTANCE_TEXT_TARGET
    assert snapshot.requests[3].input["role_filter"] == collector.ACCEPTANCE_TEXT_ROLE
    for item in envelope["requests"]:
        ToolDescriptorRegistry.validate_payload(
            str(item["tool_name"]),
            dict(item["input"]),
        )


def test_task_request_uses_public_prompt_contract_without_runtime_authority() -> None:
    marker = "7070802"
    request = collector._task_request(marker)

    assert request["prompt"] == collector._prompt(marker)
    assert request["metadata"]["source"] == "packaged_daily_provider_acceptance_v2"
    assert "yachiyo_entrypoint_allowed_tools" not in request["metadata"]
    assert "allowed_tools" not in request
    assert "direct_tool_requests" not in request
    assert "runtime_execution_envelope" not in request
    assert "client_run_id" not in request
    assert "client_task_id" not in request


def test_wait_for_native_agent_ready_polls_until_status_reports_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)

    class AliveProcess:
        returncode = None

        @staticmethod
        def poll() -> None:
            return None

    initial = collector.HttpResult(
        method="GET",
        path="/status",
        status_code=200,
        payload={"service": "oha-yachiyo", "native_agent_ready": False},
        raw=b"{}",
        received_at="2026-07-17T00:00:00+00:00",
    )
    ready = collector.HttpResult(
        method="GET",
        path="/status",
        status_code=200,
        payload={"service": "oha-yachiyo", "native_agent_ready": True},
        raw=b'{"native_agent_ready":true}',
        received_at="2026-07-17T00:00:02+00:00",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, method: str, path: str) -> collector.HttpResult:
            assert method == "GET"
            assert path == "/status"
            self.calls += 1
            return ready if self.calls >= 2 else initial

    client = FakeClient()
    result = collector.wait_for_native_agent_ready(
        client,
        AliveProcess(),
        initial_status=initial,
        timeout=1.0,
    )

    assert result is ready
    assert client.calls >= 2


def test_wait_for_native_agent_ready_returns_last_status_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)

    class AliveProcess:
        returncode = None

        @staticmethod
        def poll() -> None:
            return None

    not_ready = collector.HttpResult(
        method="GET",
        path="/status",
        status_code=200,
        payload={"service": "oha-yachiyo", "native_agent_ready": False},
        raw=b'{"native_agent_ready":false}',
        received_at="2026-07-17T00:00:00+00:00",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, method: str, path: str) -> collector.HttpResult:
            assert method == "GET"
            assert path == "/status"
            self.calls += 1
            return not_ready

    client = FakeClient()
    result = collector.wait_for_native_agent_ready(
        client,
        AliveProcess(),
        initial_status=not_ready,
        timeout=0.01,
    )

    assert result is not_ready
    assert client.calls >= 1


def test_run_task_resumes_runtime_selected_background_plan_after_approval() -> None:
    calls: list[tuple[str, str, object]] = []

    def result(method: str, path: str, payload: object) -> collector.HttpResult:
        raw = json.dumps(payload).encode("utf-8")
        return collector.HttpResult(
            method=method,
            path=path,
            status_code=200,
            payload=payload,
            raw=raw,
            received_at="2026-07-17T00:00:00+00:00",
        )

    class FakeClient:
        task_gets = 0

        def request(
            self,
            method: str,
            path: str,
            payload: object = None,
        ) -> collector.HttpResult:
            calls.append((method, path, payload))
            if method == "POST" and path == "/yachiyo/chat/tasks":
                return result(method, path, {"task_id": "task-1", "status": "running"})
            if method == "GET" and path == "/yachiyo/chat/tasks/task-1":
                self.task_gets += 1
                status = "approval_required" if self.task_gets == 1 else "completed"
                envelope, approval = _runtime_planned_pending_approval("7070802")
                return result(
                    method,
                    path,
                    {
                        "task_id": "task-1",
                        "status": status,
                        "runtime_debug": {"run_id": "run-1"},
                        "runtime_execution_envelope": envelope,
                        "pending_approvals": (
                            [approval]
                            if status == "approval_required"
                            else []
                        ),
                    },
                )
            if method == "POST" and path == "/yachiyo/chat/tasks/task-1/approve":
                return result(method, path, {"task_id": "task-1", "status": "running"})
            if method == "GET" and path.startswith("/yachiyo/studio/runs/run-1"):
                return result(method, path, {"run_id": "run-1", "events": []})
            raise AssertionError((method, path, payload))

    task = collector.run_task(
        FakeClient(),
        "7070802",
        timeout=2,
        sample=lambda label: {
            "label": label,
            "frontmost": {"ok": True, "pid": 101, "bundle_id": "com.apple.finder"},
            "cursor": {"ok": True, "x": 10.0, "y": 20.0},
        },
    )

    approvals = [
        payload
        for method, path, payload in calls
        if method == "POST" and path.endswith("/approve")
    ]
    assert task["task"]["status"] == "completed"
    assert task["approval_count"] == 1
    assert len(approvals) == 1
    assert approvals[0]["approval_id"] == "approval-runtime-type"
    assert approvals[0]["metadata"]["runtime_bound_plan"] is True
    assert approvals[0]["metadata"]["approval_id"] == "approval-runtime-type"
    assert set(approvals[0]["metadata"]).isdisjoint(
        {
            "approval_request_fingerprint",
            "decision_id",
            "plan_id",
            "request_fingerprint",
            "request_id",
            "runtime_execution_envelope",
            "step_id",
        }
    )


def test_run_task_refuses_unexpected_runtime_approval() -> None:
    calls: list[tuple[str, str, object]] = []

    def result(method: str, path: str, payload: object) -> collector.HttpResult:
        raw = json.dumps(payload).encode("utf-8")
        return collector.HttpResult(
            method=method,
            path=path,
            status_code=200,
            payload=payload,
            raw=raw,
            received_at="2026-07-17T00:00:00+00:00",
        )

    class FakeClient:
        def request(
            self,
            method: str,
            path: str,
            payload: object = None,
        ) -> collector.HttpResult:
            calls.append((method, path, payload))
            if method == "POST" and path == "/yachiyo/chat/tasks":
                return result(method, path, {"task_id": "task-1", "status": "running"})
            if method == "GET" and path == "/yachiyo/chat/tasks/task-1":
                unexpected = _fixed_pending_approval("7070802")
                unexpected["tool_name"] = "desktop.hotkey"
                unexpected["step_id"] = "unexpected-replan-step"
                return result(
                    method,
                    path,
                    {
                        "task_id": "task-1",
                        "status": "approval_required",
                        "pending_approvals": [unexpected],
                    },
                )
            raise AssertionError((method, path, payload))

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector.run_task(
            FakeClient(),
            "7070802",
            timeout=2,
            sample=lambda label: {
                "label": label,
                "frontmost": {
                    "ok": True,
                    "pid": 101,
                    "bundle_id": "com.apple.finder",
                },
                "cursor": {"ok": True, "x": 10.0, "y": 20.0},
            },
        )

    assert not any(path.endswith("/approve") for _method, path, _payload in calls)


def test_runtime_bound_approval_rejects_request_level_foreground_authority() -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    envelope["requests"][3]["desktop_execution_policy"] = {
        "mode": "live",
        "allow_live_foreground": True,
    }

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


def test_runtime_bound_approval_accepts_real_public_card_shape() -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")

    assert set(approval).isdisjoint(
        {
            "decision_id",
            "plan_id",
            "planning_reason",
            "request_id",
            "source",
            "status",
            "step_id",
            "tool_name",
        }
    )
    assert collector._runtime_bound_pending_approval(
        _runtime_approval_task(envelope, approval),
        "7070802",
        expected_task_id="task-1",
        expected_run_id="run-1",
    ) == {"approval_id": "approval-runtime-type"}


@pytest.mark.parametrize(
    "field",
    ("task_id", "source_run_id", "core_id", "workspace_id"),
)
def test_runtime_bound_approval_rejects_missing_public_identity(field: str) -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    approval.pop(field)

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


@pytest.mark.parametrize(
    ("field", "foreign_value"),
    (
        ("task_id", "task-foreign"),
        ("source_run_id", "run-foreign"),
        ("core_id", "core-foreign"),
        ("workspace_id", "workspace-foreign"),
    ),
)
def test_runtime_bound_approval_rejects_foreign_public_identity(
    field: str,
    foreign_value: str,
) -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    approval[field] = foreign_value

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


@pytest.mark.parametrize(
    ("task_id", "run_id"),
    (("task-foreign", "run-1"), ("task-1", "run-foreign")),
)
def test_runtime_bound_approval_rejects_foreign_polled_task_identity(
    task_id: str,
    run_id: str,
) -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(
                envelope,
                approval,
                task_id=task_id,
                run_id=run_id,
            ),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


@pytest.mark.parametrize("mutation", ("tool", "input"))
def test_runtime_bound_approval_rejects_wrong_public_action(mutation: str) -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    if mutation == "tool":
        approval["tool"] = "desktop.hotkey"
    else:
        approval["input_preview"] = {
            **dict(approval["input_preview"]),
            "text": "foreign text",
        }

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


@pytest.mark.parametrize("mutation", ("approval_input", "earlier_input"))
def test_runtime_bound_approval_rejects_runtime_input_outside_fixed_contract(
    mutation: str,
) -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    if mutation == "approval_input":
        envelope["requests"][3]["input"]["limit"] = 81
        approval["input_preview"] = {
            **dict(approval["input_preview"]),
            "limit": 81,
        }
    else:
        envelope["requests"][0]["input"]["limit"] = 999

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


def test_runtime_bound_approval_rejects_leaked_private_lineage() -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    approval["plan_id"] = "runtime-plan"

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


def test_runtime_bound_approval_rejects_multiple_public_cards() -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    task = _runtime_approval_task(envelope, approval)
    task["pending_approvals"] = [
        approval,
        {**approval, "approval_id": "approval-runtime-type-duplicate"},
    ]

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            task,
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


@pytest.mark.parametrize("mutation", ("missing_request", "broken_dependency"))
def test_runtime_bound_approval_rejects_malformed_runtime_envelope(
    mutation: str,
) -> None:
    envelope, approval = _runtime_planned_pending_approval("7070802")
    if mutation == "missing_request":
        envelope["requests"] = list(envelope["requests"])[:-1]
    else:
        envelope["requests"][3]["depends_on"] = ["foreign-step"]

    with pytest.raises(
        collector.CollectorError,
        match="unexpected or unbound approval",
    ):
        collector._runtime_bound_pending_approval(
            _runtime_approval_task(envelope, approval),
            "7070802",
            expected_task_id="task-1",
            expected_run_id="run-1",
        )


def test_task_evidence_summary_preserves_sanitized_terminal_failure() -> None:
    summary = collector.task_evidence_summary(
        {
            "task_id": "task-failed",
            "status": "failed",
            "summary": "Background launch failed with sk-secretsecretsecretsecret",
            "current_step": "Open TextEdit",
            "progress_text": "Stopped",
            "needs_user_action": True,
            "runtime_debug": {
                "run_id": "run-failed",
                "failed_tool_call_count": 1,
                "latest_request_tool_name": "app.open",
                "latest_request_status": "failed",
            },
            "tool_calls": [
                {
                    "tool_call_id": "call-open",
                    "tool_name": "app.open",
                    "status": "failed",
                    "input_preview": {"app_name": "TextEdit"},
                    "output_preview": {
                        "ok": False,
                        "error": "cua_background_target_not_agent_owned",
                    },
                }
            ],
        }
    )

    assert summary["task_id"] == "task-failed"
    assert summary["run_id"] == "run-failed"
    assert summary["status"] == "failed"
    assert summary["summary"] == "Background launch failed with <redacted>"
    assert summary["runtime_debug"]["latest_request_tool_name"] == "app.open"
    assert summary["tool_calls"][0]["tool_name"] == "app.open"
    assert summary["tool_calls"][0]["output_preview"]["error"] == (
        "cua_background_target_not_agent_owned"
    )


def test_provider_health_is_gate_ready_and_preserves_real_denial() -> None:
    authorized = collector.provider_health_observation(_health_payload())
    assert {
        key: authorized[key]
        for key in (
            "checked",
            "ok",
            "status",
            "provider_id",
            "provider_kind",
            "source",
            "transport",
            "blocking_conditions",
        )
    } == {
        "checked": True,
        "ok": True,
        "status": "healthy",
        "provider_id": "cua-driver",
        "provider_kind": "background_desktop",
        "source": "cua_mcp_electron_bridge",
        "transport": "electron_bridge",
        "blocking_conditions": [],
    }

    denied = collector.provider_health_observation(_health_payload(authorized=False))
    assert denied["checked"] is True
    assert denied["ok"] is False
    assert denied["status"] == "not_ready"
    assert denied["permission_blockers"] == [
        "desktop_permission_accessibility_required"
    ]


def test_authorized_receipts_require_one_grounded_background_target() -> None:
    marker = "7070802"
    timeline = {"tool_calls": _authorized_tool_calls(marker)}
    observation, checks, blockers = collector.authorized_task_observation(
        timeline,
        {},
        marker=marker,
        observer=_observer(),
    )
    assert all(checks.values())
    assert blockers == []
    assert set(observation["receipts"]) == {
        "launch",
        "observation",
        "input",
        "verify",
    }

    forged = copy.deepcopy(timeline)
    forged["tool_calls"][2]["output_preview"]["grounded_element"][
        "window_id"
    ] = 9999
    _observation, forged_checks, forged_blockers = (
        collector.authorized_task_observation(
            forged,
            {},
            marker=marker,
            observer=_observer(),
        )
    )
    assert forged_checks["background_input_verified"] is False
    assert "authorized_background_input_verified_failed" in forged_blockers


def test_authorized_receipts_follow_tool_call_lineage_not_json_walk_order() -> None:
    marker = "26076885"
    calls = _authorized_tool_calls(marker)
    input_call = copy.deepcopy(calls[2])
    verify_call = copy.deepcopy(calls[3])
    verify_call["output_preview"]["source_tool_call_id"] = input_call["tool_call_id"]
    timeline = {
        # Persisted run events can precede the canonical tool_calls projection
        # in object traversal even though the launch happened first in time.
        "events": [{"payload": input_call}],
        "tool_calls": [calls[0], calls[1], verify_call],
    }

    observation, checks, blockers = collector.authorized_task_observation(
        timeline,
        {},
        marker=marker,
        observer=_observer(),
    )

    assert blockers == []
    assert all(checks.values())
    assert observation["receipts"]["input"]["tool_call_id"] == "input"
    assert observation["receipts"]["verify"]["tool_call_id"] == "verify"


def test_permission_denial_rejects_effectful_tool_receipts() -> None:
    denied_health = collector.provider_health_observation(
        _health_payload(authorized=False)
    )
    evidence, passed, blockers = collector.permission_denial_observation(
        denied_health,
        {},
        {},
        task_status="failed",
        start_status_code=202,
    )
    assert passed is True
    assert blockers == []
    assert evidence["blocking_conditions"] == [
        "desktop_permission_accessibility_required"
    ]
    assert evidence["ok"] is False
    assert evidence["tool_call_count"] == 0
    assert evidence["action_dispatched"] is False

    _evidence, passed, blockers = collector.permission_denial_observation(
        denied_health,
        {"tool_calls": _authorized_tool_calls("7070802")[:1]},
        {},
        task_status="failed",
        start_status_code=202,
    )
    assert passed is False
    assert blockers == ["permission_denial_fail_closed_evidence_missing"]


def test_permission_denial_allows_read_only_and_policy_blocked_receipts() -> None:
    denied_health = collector.provider_health_observation(
        _health_payload(authorized=False)
    )
    timeline = {
        "tool_calls": [
            {
                "tool_call_id": "discover",
                "tool_name": "desktop.list_apps",
                "status": "completed",
                "output_preview": {"ok": True, "action": "desktop.list_apps"},
            },
            {
                "tool_call_id": "blocked-launch",
                "tool_name": "app.open",
                "status": "failed",
                "output_preview": {
                    "ok": False,
                    "error": "desktop_execution_policy_blocked",
                    "blocked_by_desktop_execution_policy": True,
                    "blocking_conditions": [
                        "desktop_permission_accessibility_required"
                    ],
                },
            },
        ]
    }

    evidence, passed, blockers = collector.permission_denial_observation(
        denied_health,
        timeline,
        {},
        task_status="failed",
        start_status_code=200,
    )

    assert passed is True
    assert blockers == []
    assert evidence["tool_call_count"] == 2
    assert evidence["action_dispatched"] is False
    assert evidence["launch_receipt_present"] is True
    assert evidence["launch_attempted"] is False
    assert evidence["input_attempted"] is False


def test_observer_exports_identity_only_frontmost_samples() -> None:
    observer = _observer()
    expected = {"pid": 101, "bundle_id": "com.apple.finder"}
    assert observer["frontmost_before"] == expected
    assert observer["frontmost_after"] == expected
    assert observer["frontmost_samples"] == [expected, expected]
    assert observer["frontmost_unchanged"] is True
    assert observer["pointer_max_delta"] == 0.5


def test_observer_treats_same_bundle_process_handoff_as_same_frontmost_app() -> None:
    observer = collector.finalize_observer(
        [
            {
                "frontmost": {
                    "ok": True,
                    "pid": 101,
                    "bundle_id": "io.github.arisataki.oha-yachiyo",
                },
                "cursor": {"ok": True, "x": 10.0, "y": 20.0},
            },
            {
                "frontmost": {
                    "ok": True,
                    "pid": 202,
                    "bundle_id": "io.github.arisataki.oha-yachiyo",
                },
                "cursor": {"ok": True, "x": 10.0, "y": 20.0},
            },
        ]
    )

    assert observer["frontmost_unchanged"] is True
    checks = collector.observer_checks(observer, target_pid=4312)
    assert all(checks.values())


def test_lsappinfo_parser_accepts_quoted_only_keys() -> None:
    parsed = collector._parse_lsappinfo(
        '\n'.join(
            (
                '"LSDisplayName"="ChatGPT"',
                '"CFBundleIdentifier"="com.openai.codex"',
                '"pid"=33753',
            )
        )
    )

    assert parsed == {
        "pid": 33753,
        "bundle_id": "com.openai.codex",
        "app_name": "ChatGPT",
    }


def test_unused_foreground_provider_diagnostic_is_not_execution_violation() -> None:
    marker = "7070802"
    tool_calls = _authorized_tool_calls(marker)
    tool_calls[0]["output_preview"]["sandbox_provider"] = {
        "launch_hint": {
            "controlled_provider": {
                "foreground_takeover_required": True,
                "desktop_session_kind": "user_foreground",
            }
        }
    }

    _observation, checks, blockers = collector.authorized_task_observation(
        {"tool_calls": tool_calls},
        {},
        marker=marker,
        observer=_observer(),
    )

    assert blockers == []
    assert all(checks.values())


def test_selected_foreground_transport_is_execution_violation() -> None:
    marker = "7070802"
    tool_calls = _authorized_tool_calls(marker)
    tool_calls[2]["output_preview"]["desktop_execution_provider_transport"] = {
        **TRANSPORT,
        "delivery_mode": "foreground",
        "foreground_takeover_required": True,
    }

    _observation, checks, blockers = collector.authorized_task_observation(
        {"tool_calls": tool_calls},
        {},
        marker=marker,
        observer=_observer(),
    )

    assert checks["background_input_verified"] is False
    assert checks["foreground_app_unchanged"] is False
    assert "authorized_foreground_fallback_detected" in blockers


def test_authorized_observation_prefers_bound_target_over_extra_app_windows() -> None:
    tool_calls = _authorized_tool_calls("7070802")
    launch_output = tool_calls[0]["output_preview"]
    launch_output["windows"] = [
        {"pid": TARGET["target_pid"], "window_id": TARGET["target_window_id"]},
        {"pid": TARGET["target_pid"], "window_id": 9999},
    ]

    observation, checks, blockers = collector.authorized_task_observation(
        {"tool_calls": tool_calls},
        {},
        marker="7070802",
        observer=_observer(),
    )

    assert blockers == []
    assert all(checks.values())
    assert observation["receipts"]["launch"]["tool_name"] == "app.open"

    cleanup = collector.cleanup_agent_owned_textedit(
        observation,
        protected_pid=999,
        kill=lambda _pid, _signal: None,
    )
    assert cleanup["identity_revalidated"] is True
    assert cleanup["target_pid"] == TARGET["target_pid"]
    assert cleanup["target_window_id"] == TARGET["target_window_id"]
    assert cleanup["terminated"] is True


def test_app_identity_uses_bare_asar_digest_and_binds_build_metadata(
    tmp_path: Path,
) -> None:
    app = tmp_path / "Oha-Yachiyo.app"
    executable = app / "Contents" / "MacOS" / "Oha-Yachiyo"
    asar = app / "Contents" / "Resources" / "app.asar"
    executable.parent.mkdir(parents=True)
    asar.parent.mkdir(parents=True)
    executable.write_bytes(b"executable")
    asar.write_bytes(b"asar")
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": collector.EXPECTED_BUNDLE_ID,
                "CFBundleExecutable": "Oha-Yachiyo",
                "CFBundleShortVersionString": "0.4.0",
                "CFBundleVersion": "40",
            },
            handle,
        )
    metadata = {
        "version": "0.4.0",
        "commit": "1" * 40,
        "source_tree_fingerprint": f"sha256:{'2' * 64}",
    }
    identity, blockers = collector.app_identity(
        app, {"build_metadata": metadata}
    )
    assert identity["version"] == "0.4.0"
    assert identity["app_asar_sha256"] == collector.hashlib.sha256(b"asar").hexdigest()
    assert len(identity["app_asar_sha256"]) == 64
    assert identity["build_metadata"] == metadata
    assert blockers == ["packaged_app_install_path_mismatch"]


def _current_phase(
    phase: str,
    *,
    identity: dict[str, object],
    bridge_status: dict[str, object],
    observations: dict[str, object],
    checks: dict[str, bool],
) -> dict[str, object]:
    return {
        "collector": {"name": "collector", "version": "2", "phase": phase},
        "app_identity": identity,
        "bridge_status": bridge_status,
        "observations": observations,
        "checks": checks,
        "phase_evidence": {"bridge_status": bridge_status, "phase": phase},
    }


def test_three_phase_merge_is_accepted_by_release_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = "1" * 40
    fingerprint = f"sha256:{'2' * 64}"
    asar_sha256 = "3" * 64
    identity: dict[str, object] = {
        "packaged_app": True,
        "path": "/Applications/Oha-Yachiyo.app",
        "bundle_id": collector.EXPECTED_BUNDLE_ID,
        "version": "0.4.0",
        "short_version": "0.4.0",
        "app_asar_sha256": asar_sha256,
        "build_revision": revision,
        "source_tree_fingerprint": fingerprint,
    }
    identity["identity_sha256"] = collector.sha256_json(identity)
    bridge_status = {
        "ready": True,
        "build_metadata": {
            "version": "0.4.0",
            "commit": revision,
            "source_tree_fingerprint": fingerprint,
        },
    }
    health = collector.provider_health_observation(_health_payload())
    authorized_task, authorized_checks, blockers = (
        collector.authorized_task_observation(
            {"tool_calls": _authorized_tool_calls("7070802")},
            {},
            marker="7070802",
            observer=_observer(),
        )
    )
    assert blockers == []
    authorized = collector.merge_phase_report(
        _current_phase(
            "authorized",
            identity=identity,
            bridge_status=bridge_status,
            observations={
                "provider_health": health,
                "authorized_task": authorized_task,
                "observer": _observer(),
            },
            checks={
                "packaged_bridge_ready": True,
                "provider_health_authorized": True,
                "screen_recording_authorized": True,
                **authorized_checks,
            },
        ),
        None,
    )
    denial, denial_passed, _ = collector.permission_denial_observation(
        collector.provider_health_observation(_health_payload(authorized=False)),
        {},
        {},
        task_status="failed",
        start_status_code=202,
    )
    denied = collector.merge_phase_report(
        _current_phase(
            "denied",
            identity=identity,
            bridge_status=bridge_status,
            observations={
                "provider_health": collector.provider_health_observation(
                    _health_payload(authorized=False)
                ),
                "permission_denial": denial,
            },
            checks={"permission_denial_fails_closed": denial_passed},
        ),
        authorized,
    )
    restored = collector.merge_phase_report(
        _current_phase(
            "restored",
            identity=identity,
            bridge_status=bridge_status,
            observations={"provider_health": health},
            checks={"packaged_bridge_ready": True, "permissions_restored": True},
        ),
        denied,
    )
    assert restored["status"] == "passed"
    assert restored["evidence_digest"] == collector.canonical_evidence_digest(restored)
    assert len(restored["evidence_digest"]) == 64
    assert restored["observations"]["provider_health"]["status"] == "healthy"
    assert restored["bridge_status"]["build_metadata"]["commit"] == revision

    report_path = tmp_path / "daily-provider.json"
    report_path.write_text(json.dumps(restored), encoding="utf-8")
    monkeypatch.setattr(
        release_gate,
        "_packaged_app_identity_from_disk",
        lambda _path: {
            "ok": True,
            "location_valid": True,
            "bundle_id": collector.EXPECTED_BUNDLE_ID,
            "version": "0.4.0",
            "app_asar_sha256": asar_sha256,
        },
    )
    gate = release_gate._daily_provider_acceptance_evidence(report_path)
    assert gate["ok"] is True, gate["blocking_conditions"]


def test_cleanup_only_terminates_revalidated_agent_owned_textedit() -> None:
    launch = {
        "receipts": {"launch": _authorized_tool_calls("7070802")[0]}
    }
    calls: list[tuple[int, int]] = []
    result = collector.cleanup_agent_owned_textedit(
        launch,
        protected_pid=999,
        kill=lambda pid, sig: calls.append((pid, sig)),
    )
    assert result["terminated"] is True
    assert calls == [(TARGET["target_pid"], collector.signal.SIGTERM)]

    protected = collector.cleanup_agent_owned_textedit(
        launch,
        protected_pid=TARGET["target_pid"],
        kill=lambda pid, sig: calls.append((pid, sig)),
    )
    assert protected["attempted"] is False
    assert len(calls) == 1
