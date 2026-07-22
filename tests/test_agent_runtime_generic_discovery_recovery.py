"""Focused vertical-slice tests for generic read-only discovery recovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

import pytest

from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.errors import (
    AgentApprovalRequired,
    AgentDirectOutcomeUnverified,
    AgentRuntimeError,
)
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionContext,
    RecoveryActionDisposition,
    RecoveryActionRegistry,
    RecoveryActionScope,
    RecoveryToolBatch,
    RecoveryToolResult,
)
from apps.shell.agent.runtime.recovery_adapters import (
    AppleMusicAliasRecoveryAdapter,
    BackgroundWindowRecoveryAdapter,
    DesktopAppResolutionAdapter,
    EntityAliasRecoveryAdapter,
    WorkspaceFileResolutionAdapter,
)
from apps.shell.agent.runtime.recovery_policies import assess_latest_tool_recovery
from apps.shell.agent.runtime.tooling import build_runtime_tooling_stack


def _event(tool: str, result: Mapping[str, Any], call_id: str = "source-call") -> dict[str, Any]:
    return {
        "event": "agent.tool.call",
        "tool": tool,
        "tool_call_id": call_id,
        "result": dict(result),
    }


def _file_result(path: str, *, directory: bool = False) -> dict[str, Any]:
    if directory:
        return {
            "ok": False,
            "path": path,
            "error": "workspace.read 只能读取文件",
            "hint": (
                "这是一个目录；请改用 workspace.list 查看目录内容，"
                "或选择目录中的具体文件再读取。"
            ),
            "suggested_tool": "workspace.list",
        }
    return {
        "ok": False,
        "path": path,
        "error": "路径不存在",
        "hint": "请先用 workspace.list 查看父目录，确认要读取的文件相对路径。",
    }


def _app_not_found(action: str, query: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "error": f"No application matched {query}",
        "error_code": "app_not_found",
        "data": {"app_name": query},
        "permission_error": False,
        "fallback_used": False,
    }


def _app_result(tool: str, query: str) -> dict[str, Any]:
    if tool in {"app.open", "desktop.open_app"}:
        result = _app_not_found(tool, query)
    else:
        result = {
            "ok": False,
            "action": tool,
            "error": "focus failed before launch fallback",
            "data": {},
            "permission_error": False,
            "fallback_used": False,
            "fallback_result": _app_not_found("app.open", query),
        }
    result[RUNTIME_EXECUTION_PROVENANCE_KEY] = {
        "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
        "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
    }
    return result


def _assessment(
    tool: str,
    result: Mapping[str, Any],
    *,
    allowed_tools: Iterable[str],
    call_id: str = "source-call",
    lineage: tuple[Any, ...] = (),
):
    return assess_latest_tool_recovery(
        [_event(tool, result, call_id)],
        start_index=0,
        allowed_tools=allowed_tools,
        attempt_lineage=lineage,
    )


class _RecordingRuntime:
    def __init__(
        self,
        error: Exception | None = None,
        result: Mapping[str, Any] | None = None,
        event_type: str = "agent.tool.call",
    ) -> None:
        self.error = error
        self.result = dict(result or {"ok": True, "data": {"items": []}})
        self.event_type = event_type
        self.calls: list[dict[str, Any]] = []
        self.release_count = 0

    def execute_tools(
        self,
        tool_requests: Sequence[Mapping[str, Any]],
        *,
        allowed_tools: Iterable[str],
        next_iteration: int,
    ) -> RecoveryToolBatch:
        self.calls.append(
            {
                "requests": tuple(dict(request) for request in tool_requests),
                "allowed_tools": tuple(allowed_tools),
                "next_iteration": next_iteration,
            }
        )
        if self.error is not None:
            raise self.error
        request = dict(tool_requests[0])
        return RecoveryToolBatch(
            requests=tuple(tool_requests),
            results=(
                RecoveryToolResult(
                    tool_call_id=str(request.get("tool_call_id") or ""),
                    result=self.result,
                    event_type=self.event_type,
                ),
            ),
        )

    def select_tool(self, **_kwargs: Any) -> Any:
        raise AssertionError("discovery recovery must not invoke the model directly")

    def commit_model_turn(self, **_kwargs: Any) -> None:
        raise AssertionError("discovery recovery must not commit a synthetic model turn")

    def project_completion(self, _batch: RecoveryToolBatch) -> str:
        raise AssertionError("discovery recovery must return control to the model")

    def release_owned_resources(self) -> None:
        self.release_count += 1


def _context(assessment: Any, runtime: Any, allowed_tools: Iterable[str]) -> RecoveryActionContext:
    assert assessment is not None and assessment.plan is not None
    return RecoveryActionContext(
        plan=assessment.plan,
        source_outcome=assessment.outcome,
        source_tool_call_id=assessment.tool_call_id,
        scope=RecoveryActionScope(allowed_tools=frozenset(allowed_tools), iteration=4),
        runtime=runtime,
    )


@pytest.mark.parametrize("tool", ["workspace.read", "fs.read_file", "file.read"])
@pytest.mark.parametrize("directory", [False, True])
def test_file_read_miss_normalizes_to_one_capability_plan(tool: str, directory: bool) -> None:
    assessment = _assessment(
        tool,
        _file_result(
            "reports/2026" if directory else "reports/2026/missing.md",
            directory=directory,
        ),
        allowed_tools=(tool, "workspace.list"),
    )

    assert assessment is not None and assessment.plan is not None
    assert assessment.outcome.retryable is True
    assert "file_resolution_failed" in assessment.outcome.recovery_hints
    assert assessment.plan.strategy_id == "resolve-file-location"
    assert assessment.plan.action == "resolve_file_location"
    assert assessment.plan.required_capabilities == ("file.workspace_read",)


@pytest.mark.parametrize(
    "tool",
    ["app.open", "desktop.open_app", "app.focus", "desktop.focus_app"],
)
def test_explicit_app_miss_normalizes_to_discovery_only_plan(tool: str) -> None:
    assessment = _assessment(
        tool,
        _app_result(tool, "Example Writer"),
        allowed_tools=(tool, "desktop.list_apps"),
    )

    assert assessment is not None and assessment.plan is not None
    assert assessment.outcome.retryable is True
    assert "app_resolution_failed" in assessment.outcome.recovery_hints
    assert assessment.plan.strategy_id == "resolve-app-identity"
    assert assessment.plan.action == "resolve_app_identity"
    assert assessment.plan.required_capabilities == ("desktop.app_discovery",)


@pytest.mark.parametrize(
    ("tool", "result"),
    [
        ("workspace.read", {**_file_result("missing.md"), "hint": "untrusted"}),
        ("workspace.read", {**_file_result("missing.md"), "path": ""}),
        ("workspace.list", _file_result("missing.md")),
        ("app.open", {**_app_not_found("app.open", "Missing"), "error_code": "other"}),
        ("app.open", {**_app_not_found("app.open", "Missing"), "action": "app.focus"}),
        ("app.open", {**_app_not_found("app.open", "Missing"), "permission_error": True}),
    ],
)
def test_untrusted_or_malformed_source_shapes_do_not_plan(
    tool: str,
    result: Mapping[str, Any],
) -> None:
    discovery = (
        "workspace.list"
        if tool.startswith(("workspace", "fs", "file"))
        else "desktop.list_apps"
    )
    assessment = _assessment(tool, result, allowed_tools=(tool, discovery))

    assert assessment is not None
    assert assessment.plan is None


def test_nonempty_source_call_id_is_required_for_generic_plan() -> None:
    assessment = _assessment(
        "workspace.read",
        _file_result("missing.md"),
        allowed_tools=("workspace.read", "workspace.list"),
        call_id="",
    )

    assert assessment is not None
    assert assessment.plan is None


@pytest.mark.parametrize(
    ("tool", "result", "allowed_tools"),
    [
        (
            "workspace.read",
            _file_result("missing.md"),
            ("workspace.read", "file.search"),
        ),
        (
            "app.open",
            _app_result("app.open", "Missing"),
            ("app.open", "desktop.running_apps"),
        ),
    ],
)
def test_broad_capability_without_exact_discovery_tool_does_not_plan(
    tool: str,
    result: Mapping[str, Any],
    allowed_tools: tuple[str, ...],
) -> None:
    assessment = _assessment(tool, result, allowed_tools=allowed_tools)

    assert assessment is not None
    assert assessment.plan is None


@pytest.mark.parametrize("provider_routed", [False, True], ids=("missing", "provider"))
def test_app_recovery_requires_local_broker_provenance(provider_routed: bool) -> None:
    result = _app_result("app.open", "Remote Writer")
    result.pop(RUNTIME_EXECUTION_PROVENANCE_KEY)
    if provider_routed:
        result["desktop_execution_provider_routed"] = True
        result["desktop_execution_route"] = {
            "provider_kind": "sandbox_desktop",
            "provider_id": "sandbox-1",
        }

    assessment = _assessment(
        "app.open",
        result,
        allowed_tools=("app.open", "desktop.list_apps"),
    )

    assert assessment is not None
    assert assessment.plan is None


@pytest.mark.parametrize(
    ("directory", "expected_path"),
    [(False, "reports/2026"), (True, "reports/2026")],
)
def test_file_adapter_lists_parent_for_miss_or_self_for_directory_once(
    directory: bool,
    expected_path: str,
) -> None:
    assessment = _assessment(
        "workspace.read",
        _file_result(
            "reports/2026" if directory else "reports/2026/missing.md",
            directory=directory,
        ),
        allowed_tools=("workspace.read", "workspace.list"),
    )
    runtime = _RecordingRuntime()
    registry = RecoveryActionRegistry((WorkspaceFileResolutionAdapter(),))
    resolved = registry.resolve(
        _context(assessment, runtime, ("workspace.read", "workspace.list"))
    )
    assert resolved is not None

    result = resolved.execute()
    repeated = resolved.execute()

    assert result.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert result.reason == "discovery_completed"
    assert len(result.attempts) == 1
    assert repeated.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert repeated.reason == "already_executed"
    assert len(runtime.calls) == 1
    request = runtime.calls[0]["requests"][0]
    assert request["tool"] == "workspace.list"
    assert request["input"] == {"path": expected_path}
    assert request["tool_call_id"].startswith("file-resolution-list-4-")
    assert runtime.calls[0]["allowed_tools"] == ("workspace.list",)
    assert runtime.calls[0]["next_iteration"] == 5
    assert runtime.release_count == 0


def test_app_adapter_hands_off_when_discovery_finds_no_candidates() -> None:
    assessment = _assessment(
        "app.open",
        _app_result("app.open", "Example Writer"),
        allowed_tools=("app.open", "desktop.list_apps"),
    )
    runtime = _RecordingRuntime()
    context = _context(assessment, runtime, ("app.open", "desktop.list_apps"))

    result = RecoveryActionRegistry((DesktopAppResolutionAdapter(),)).execute(context)

    assert result.disposition is RecoveryActionDisposition.AWAIT_USER
    assert result.reason == "app_discovery_no_match"
    assert len(result.attempts) == 1
    assert len(runtime.calls) == 1
    request = runtime.calls[0]["requests"][0]
    assert request["tool"] == "desktop.list_apps"
    assert request["input"] == {"query": "Example Writer", "limit": 20}
    assert request["tool_call_id"].startswith("app-resolution-list-4-")
    assert runtime.calls[0]["allowed_tools"] == ("desktop.list_apps",)
    assert runtime.release_count == 0


def test_app_adapter_reconciles_completed_legacy_discovery_without_replaying() -> None:
    assessment = _assessment(
        "app.open",
        _app_result("app.open", "Example Writer"),
        allowed_tools=("app.open", "desktop.list_apps"),
    )
    runtime = _RecordingRuntime()
    registry = RecoveryActionRegistry((DesktopAppResolutionAdapter(),))
    resolved = registry.resolve(
        _context(assessment, runtime, ("app.open", "desktop.list_apps"))
    )
    assert resolved is not None
    completed_batch = RecoveryToolBatch(
        requests=(
            {
                "tool": "desktop.list_apps",
                "tool_call_id": "legacy-discovery",
                "input": {"query": "Example Writer", "limit": 20},
            },
        ),
        results=(
            RecoveryToolResult(
                tool_call_id="legacy-discovery",
                result={"ok": True, "data": {"apps": []}},
                event_type="agent.tool.call",
            ),
        ),
    )

    result = resolved.reconcile_completed_attempt(completed_batch)

    assert result.disposition is RecoveryActionDisposition.AWAIT_USER
    assert result.reason == "app_discovery_no_match"
    assert result.attempts == (completed_batch,)
    assert runtime.calls == []


@pytest.mark.parametrize("kind", ["file", "app"])
def test_discovery_adapter_reports_failed_tool_result_as_execution_failure(
    kind: str,
) -> None:
    if kind == "file":
        assessment = _assessment(
            "workspace.read",
            _file_result("missing.md"),
            allowed_tools=("workspace.read", "workspace.list"),
        )
        adapter: Any = WorkspaceFileResolutionAdapter()
        allowed = ("workspace.read", "workspace.list")
    else:
        assessment = _assessment(
            "app.open",
            _app_result("app.open", "Missing"),
            allowed_tools=("app.open", "desktop.list_apps"),
        )
        adapter = DesktopAppResolutionAdapter()
        allowed = ("app.open", "desktop.list_apps")
    runtime = _RecordingRuntime(result={"ok": False, "error": "unavailable"})

    result = RecoveryActionRegistry((adapter,)).execute(
        _context(assessment, runtime, allowed)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "discovery_tool_failed"
    assert len(result.attempts) == 1


@pytest.mark.parametrize("kind", ["file", "app"])
def test_discovery_adapter_treats_fatal_tool_event_as_execution_failure(
    kind: str,
) -> None:
    if kind == "file":
        assessment = _assessment(
            "workspace.read",
            _file_result("missing.md"),
            allowed_tools=("workspace.read", "workspace.list"),
        )
        adapter: Any = WorkspaceFileResolutionAdapter()
        allowed = ("workspace.read", "workspace.list")
    else:
        assessment = _assessment(
            "app.open",
            _app_result("app.open", "Missing"),
            allowed_tools=("app.open", "desktop.list_apps"),
        )
        adapter = DesktopAppResolutionAdapter()
        allowed = ("app.open", "desktop.list_apps")
    runtime = _RecordingRuntime(
        result={"ok": True, "data": {"items": []}},
        event_type="agent.tool.failed",
    )

    result = RecoveryActionRegistry((adapter,)).execute(
        _context(assessment, runtime, allowed)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "discovery_tool_failed"


@pytest.mark.parametrize("kind", ["file", "app"])
def test_adapter_allowlist_and_exact_plan_shape_fail_closed(kind: str) -> None:
    if kind == "file":
        assessment = _assessment(
            "workspace.read",
            _file_result("missing.md"),
            allowed_tools=("workspace.read", "workspace.list"),
        )
        adapter: Any = WorkspaceFileResolutionAdapter()
        full_allowlist = ("workspace.read", "workspace.list")
        narrow_allowlist = ("workspace.read",)
        wrong_capabilities = ("file.organization",)
    else:
        assessment = _assessment(
            "app.open",
            _app_result("app.open", "Missing"),
            allowed_tools=("app.open", "desktop.list_apps"),
        )
        adapter = DesktopAppResolutionAdapter()
        full_allowlist = ("app.open", "desktop.list_apps")
        narrow_allowlist = ("app.open",)
        wrong_capabilities = ("desktop.app_control",)
    runtime = _RecordingRuntime()
    context = _context(assessment, runtime, full_allowlist)

    assert adapter.supports(context) is True
    assert adapter.supports(
        replace(context, scope=RecoveryActionScope(narrow_allowlist, 4))
    ) is False
    assert adapter.supports(
        replace(context, plan=replace(context.plan, strategy_id="wrong-strategy"))
    ) is False
    assert adapter.supports(
        replace(context, plan=replace(context.plan, action="wrong_action"))
    ) is False
    assert adapter.supports(
        replace(context, plan=replace(context.plan, recovery_hint="wrong_hint"))
    ) is False
    assert adapter.supports(
        replace(
            context,
            plan=replace(context.plan, required_capabilities=wrong_capabilities),
        )
    ) is False
    assert adapter.supports(replace(context, source_tool_call_id="")) is False
    assert adapter.supports(
        replace(context, plan=replace(context.plan, scope_id=""))
    ) is False
    assert runtime.calls == []


@pytest.mark.parametrize("kind", ["file", "app"])
@pytest.mark.parametrize(
    "error",
    [
        AgentApprovalRequired({"tool": "test"}),
        AgentDirectOutcomeUnverified("unverified"),
        AgentRuntimeError("budget or lease stopped"),
    ],
)
def test_discovery_adapter_control_exceptions_propagate(kind: str, error: Exception) -> None:
    if kind == "file":
        assessment = _assessment(
            "workspace.read",
            _file_result("missing.md"),
            allowed_tools=("workspace.read", "workspace.list"),
        )
        adapter: Any = WorkspaceFileResolutionAdapter()
        allowed = ("workspace.read", "workspace.list")
    else:
        assessment = _assessment(
            "app.open",
            _app_result("app.open", "Missing"),
            allowed_tools=("app.open", "desktop.list_apps"),
        )
        adapter = DesktopAppResolutionAdapter()
        allowed = ("app.open", "desktop.list_apps")
    runtime = _RecordingRuntime(error)

    with pytest.raises(type(error)) as exc_info:
        RecoveryActionRegistry((adapter,)).execute(_context(assessment, runtime, allowed))

    assert exc_info.value is error
    assert len(runtime.calls) == 1
    assert runtime.release_count == 0


@pytest.mark.parametrize("kind", ["file", "app"])
def test_strategy_budget_blocks_same_source_scope(kind: str) -> None:
    if kind == "file":
        tool, result, allowed = (
            "workspace.read",
            _file_result("missing.md"),
            ("workspace.read", "workspace.list"),
        )
    else:
        tool, result, allowed = (
            "app.open",
            _app_result("app.open", "Missing"),
            ("app.open", "desktop.list_apps"),
        )
    first = _assessment(tool, result, allowed_tools=allowed)
    assert first is not None and first.plan is not None

    repeated = _assessment(tool, result, allowed_tools=allowed, lineage=(first.plan,))

    assert repeated is not None
    assert repeated.plan is None


def test_production_registry_contains_media_and_generic_discovery_adapters() -> None:
    stack = build_runtime_tooling_stack(
        runtime_limits=lambda: RunBudgetLimits(),
        runtime_run_budget=lambda _run_id, _timeline: object(),
        runtime_timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        runtime_context_budget_checker=lambda _budget, _messages: None,
        runtime_model_output_limiter=lambda value: (str(value), False),
        tool_call_events=object(),
        trace_events=object(),
        append_run_event=lambda _run_id, _event_type, _payload: None,
        pending_approval_builder=object(),
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True},
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": []},
            "workspace_policy": {},
        },
        call_model=lambda *_args, **_kwargs: {"role": "assistant", "content": "ok"},
        tool_requests_from_message=lambda _message, _content: [],
        run_tool_requests=lambda *_args, **_kwargs: None,
    )

    assert tuple(
        type(adapter)
        for adapter in stack.custom_api_agent_loop._recovery_action_registry.adapters
    ) == (
        EntityAliasRecoveryAdapter,
        WorkspaceFileResolutionAdapter,
        DesktopAppResolutionAdapter,
        BackgroundWindowRecoveryAdapter,
    )
    assert AppleMusicAliasRecoveryAdapter is EntityAliasRecoveryAdapter
