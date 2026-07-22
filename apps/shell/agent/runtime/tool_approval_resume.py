"""Agent and main-chat tool approval resume service."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.foreground_lock_scope import foreground_lock_broker_kwargs
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext
from apps.shell.agent.runtime.tool_brokers import latest_run_owned_browser_target_id
from apps.shell.agent.tools.policy import (
    DAILY_DESKTOP_TOOL_NAMES,
    HIGH_RISK_DESKTOP_TOOL_NAMES,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
)
from packages.security import redact_api_error_text

_DAILY_DESKTOP_APPROVAL_TOOLS = {
    *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    *HIGH_RISK_DESKTOP_TOOL_NAMES,
    *MEDIUM_RISK_BROWSER_TOOL_NAMES,
    "terminal.run",
}

_DAILY_DESKTOP_PLAN_SOURCES = {
    "daily_desktop_intent",
    "runtime_planner",
}


class RuntimeToolApprovalResumeService:
    """Builds approval resume contexts and dispatches approved tool resumes."""

    def __init__(
        self,
        *,
        pending_approval_private: Callable[[str], dict[str, Any] | None],
        get_agent_private: Callable[[str], dict[str, Any]],
        compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
        load_agent_skills: Callable[[list[str]], list[dict[str, Any]]],
        tool_brokers: Any,
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        resume_approved_tool_run: Callable[..., dict[str, Any]],
        main_chat_agent_config: Callable[..., dict[str, Any]],
        main_chat_pending_approval: Callable[..., dict[str, Any]],
        default_chat_profile_id: Callable[[], str],
        project_agent_running: Callable[[dict[str, Any]], dict[str, Any]],
        project_agent_completed: Callable[[ToolApprovalResumeContext, str], dict[str, Any]],
        project_main_chat_completed: Callable[[ToolApprovalResumeContext, str], dict[str, Any]],
        project_main_chat_failed: Callable[[ToolApprovalResumeContext, str], dict[str, Any]]
        | None = None,
        project_child_run_transition: Callable[[dict[str, Any]], dict[str, Any]],
        redact_agent_error: Callable[[Any], str],
        main_chat_agent_id: str,
        error_type: type[Exception],
        assert_approval_resume_active: Callable[[str, str], None] | None = None,
    ) -> None:
        self._pending_approval_private = pending_approval_private
        self._get_agent_private = get_agent_private
        self._compile_agent_runtime = compile_agent_runtime
        self._load_agent_skills = load_agent_skills
        self._tool_brokers = tool_brokers
        self._run_budget = run_budget
        self._resume_approved_tool_run = resume_approved_tool_run
        self._main_chat_agent_config = main_chat_agent_config
        self._main_chat_pending_approval = main_chat_pending_approval
        self._default_chat_profile_id = default_chat_profile_id
        self._project_agent_running = project_agent_running
        self._project_agent_completed = project_agent_completed
        self._project_main_chat_completed = project_main_chat_completed
        self._project_main_chat_failed = project_main_chat_failed
        self._project_child_run_transition = project_child_run_transition
        self._redact_agent_error = redact_agent_error
        self._main_chat_agent_id = main_chat_agent_id
        self._error_type = error_type
        self._assert_approval_resume_active = assert_approval_resume_active

    def context(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        *,
        runtime: dict[str, Any],
        skills: list[dict[str, Any]] | None = None,
    ) -> ToolApprovalResumeContext:
        run_id = str(run["run_id"])
        pending_context = pending if isinstance(pending, dict) else {}
        run_group_id = str(
            run.get("run_group_id")
            or pending_context.get("run_group_id")
            or pending_context.get("group_run_id")
            or ""
        ).strip()
        workflow_run_id = str(
            run.get("workflow_run_id")
            or pending_context.get("workflow_run_id")
            or ""
        ).strip()
        broker_kwargs: dict[str, Any] = foreground_lock_broker_kwargs(
            run_id=run_id,
            run_group_id=run_group_id,
            workflow_run_id=workflow_run_id,
        )
        approval_required = runtime["tool_policy"].get("approval_required") or {}
        if approval_required:
            broker_kwargs["approvals"] = approval_required
        broker = self._tool_brokers.for_run(
            run_id=run_id,
            workspace_policy=runtime["workspace_policy"],
            skills=skills,
            default_runnable_id=str((run.get("runnable_id") or self._main_chat_agent_id)),
            **broker_kwargs,
        )
        owned_browser_target_id = latest_run_owned_browser_target_id(run)
        restore_browser_target = getattr(
            broker,
            "restore_owned_browser_target",
            None,
        )
        if owned_browser_target_id and callable(restore_browser_target):
            restore_browser_target(owned_browser_target_id)
        return ToolApprovalResumeContext.from_run(
            run,
            pending,
            broker=broker,
            allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            budget_factory=lambda context_run_id, context_timeline: self._run_budget(
                context_run_id,
                context_timeline,
            ),
            assert_resume_active=self._assert_approval_resume_active,
        )
    def approve_agent_run(
        self,
        run: dict[str, Any],
        *,
        expected_approval_id: str = "",
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self._pending_approval_private(run_id)
        if not pending:
            raise self._error_type("Run 缺少待审批工具信息")
        expected_id = str(expected_approval_id or "").strip() or str(
            pending.get("approval_id") or ""
        ).strip()
        agent = self._get_agent_private(str(run["runnable_id"]))
        runtime = self._compile_agent_runtime(agent)
        skills = self._load_agent_skills(agent.get("skill_ids") or [])
        resume_context = self.context(
            run,
            pending,
            runtime=runtime,
            skills=skills,
        )
        resume_kwargs: dict[str, Any] = {
            "run_id": run_id,
            "pending": pending,
            "resume_context": resume_context,
            "agent": agent,
            "resumed_detail": "Agent resumed after approval",
            "running_result": "已批准，Agent 正在继续执行",
            "project_running": self._project_agent_running,
            "project_completed": self._project_agent_completed,
            "project_result": self._project_child_run_transition,
            "redact_error": self._redact_agent_error,
        }
        if supports_keyword(
            self._resume_approved_tool_run,
            "expected_approval_id",
        ):
            resume_kwargs["expected_approval_id"] = expected_id
        return self._resume_approved_tool_run(**resume_kwargs)

    def approve_main_chat_run(
        self,
        run: dict[str, Any],
        *,
        expected_approval_id: str = "",
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self._pending_approval_private(run_id)
        if not pending:
            raise self._error_type("Run 缺少待审批工具信息")
        expected_id = str(expected_approval_id or "").strip() or str(
            pending.get("approval_id") or ""
        ).strip()
        model_profile_id = str(pending.get("model_profile_id") or "").strip()
        profileless_daily_desktop = _is_daily_desktop_approval_resume(run, pending)
        if not model_profile_id and not profileless_daily_desktop:
            model_profile_id = str(self._default_chat_profile_id() or "").strip()
        if not model_profile_id and not profileless_daily_desktop:
            raise self._error_type("native_agent_not_ready:chat_model_profile_required")
        tool_policy = (
            pending.get("tool_policy")
            if isinstance(pending.get("tool_policy"), dict)
            else {"allowed_tools": []}
        )
        workspace_policy = (
            pending.get("workspace_policy")
            if isinstance(pending.get("workspace_policy"), dict)
            else None
        )
        agent = self._main_chat_agent_config(
            model_profile_id=model_profile_id,
            tool_policy=tool_policy,
            workspace_policy=workspace_policy,
        )
        runtime = self._compile_agent_runtime(agent)
        resume_context = self.context(run, pending, runtime=runtime)

        def prepare_main_chat_required(
            pending_approval: dict[str, Any],
        ) -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "model_profile_id": model_profile_id,
                "tool_policy": runtime["tool_policy"],
                "workspace_policy": runtime["workspace_policy"],
            }
            authority_values = (
                (
                    "runtime_execution_envelope",
                    resume_context.runtime_execution_envelope,
                ),
                (
                    "runtime_execution_metadata",
                    resume_context.runtime_execution_metadata,
                ),
            )
            authority_required = _resume_runtime_authority_required(resume_context)
            for key, value in authority_values:
                if value is None or (isinstance(value, dict) and not value):
                    continue
                if supports_keyword(self._main_chat_pending_approval, key):
                    kwargs[key] = value
                    continue
                if authority_required:
                    raise self._error_type(
                        "approval_resume_runtime_authority_unsupported"
                    )
            return self._main_chat_pending_approval(
                pending_approval,
                **kwargs,
            )

        resume_kwargs: dict[str, Any] = {
            "run_id": run_id,
            "pending": pending,
            "resume_context": resume_context,
            "agent": agent,
            "resumed_detail": "Main chat resumed after approval",
            "running_result": "已批准，Yachiyo 正在继续执行",
            "project_completed": self._project_main_chat_completed,
            "project_failed": self._project_main_chat_failed,
            "project_required": prepare_main_chat_required,
            "redact_error": redact_api_error_text,
        }
        if supports_keyword(
            self._resume_approved_tool_run,
            "expected_approval_id",
        ):
            resume_kwargs["expected_approval_id"] = expected_id
        return self._resume_approved_tool_run(**resume_kwargs)


def _is_daily_desktop_approval_resume(run: dict[str, Any], pending: dict[str, Any]) -> bool:
    tool_name = _pending_tool_name(pending)
    # Low-risk tools can still be dynamically approval-gated by the selected
    # foreground execution route (for example an open+type composite).  The
    # approval itself is already exact and generation-bound; model-profile
    # availability must not discard a persisted Native desktop plan here.
    if tool_name not in {
        *_DAILY_DESKTOP_APPROVAL_TOOLS,
        *DAILY_DESKTOP_TOOL_NAMES,
    }:
        return False
    if _pending_tool_in_uncompleted_daily_desktop_plan(run, tool_name):
        return True
    for event in reversed(run.get("timeline") or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("event") or "").strip() != "agent.desktop.intent_approval_required":
            continue
        if str(event.get("source") or "").strip() not in _DAILY_DESKTOP_PLAN_SOURCES:
            continue
        event_tool = str(event.get("tool") or event.get("detail") or "").strip()
        if event_tool == tool_name:
            return True
    return False


def _resume_runtime_authority_required(context: ToolApprovalResumeContext) -> bool:
    envelope = context.runtime_execution_envelope
    requests = envelope.get("requests") if isinstance(envelope, dict) else None
    return bool(
        (isinstance(requests, list) and requests)
        or (
            isinstance(context.runtime_execution_metadata, dict)
            and context.runtime_execution_metadata
        )
    )


def _pending_tool_in_uncompleted_daily_desktop_plan(run: dict[str, Any], tool_name: str) -> bool:
    planned_tools: list[str] = []
    for event in run.get("timeline") or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event") or "").strip()
        if event_type == "agent.desktop.intent_completed":
            planned_tools = []
            continue
        if event_type != "agent.desktop.intent_planned":
            continue
        if str(event.get("source") or "").strip() not in _DAILY_DESKTOP_PLAN_SOURCES:
            continue
        event_tool = str(event.get("tool") or event.get("detail") or "").strip()
        if event_tool:
            planned_tools.append(event_tool)
    return tool_name in planned_tools


def _pending_tool_name(pending: dict[str, Any]) -> str:
    tool_name = str(pending.get("tool") or "").strip()
    if tool_name:
        return tool_name
    tool_request = pending.get("tool_request")
    if isinstance(tool_request, dict):
        return str(tool_request.get("tool") or "").strip()
    return ""
