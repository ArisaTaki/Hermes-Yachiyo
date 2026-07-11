"""Tool-capable main chat model loop orchestration."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.model_messages import (
    message_visible_content_text,
    messages_require_model_first,
    model_output_metadata,
)
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    planner_first_direct_tool_selection,
)
from apps.shell.yachiyo_agent.discovered_app_followups import (
    planner_discovered_app_followup_can_direct_execute,
)
from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_requests_can_complete_without_model,
)
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_requests_from_envelope_payload,
    runtime_execution_requests_from_metadata,
)
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    with_daily_entrypoint_desktop_execution_policy,
)


def build_runtime_main_chat_model_loop_runner(
    *,
    get_run: Callable[[str], dict[str, Any]],
    profile_service_factory: Callable[[], Any],
    model_profile_config_private: Callable[[str], dict[str, Any]],
    main_chat_agent_config: Callable[..., dict[str, Any]],
    compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
    run_budget: Callable[[str, list[dict[str, Any]]], Any],
    check_context_budget: Callable[[Any, list[dict[str, Any]]], None],
    runtime_agent_timeline: Any,
    timeline_factory: Callable[..., dict[str, Any]],
    update_run: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], dict[str, Any]],
    task_model_events: Any,
    tool_brokers: Any,
    continue_custom_api_agent: Callable[..., str],
    main_chat_pending_approval: Callable[..., dict[str, Any]],
    approval_pause: Any,
    terminal_run_or_none: Callable[[str], dict[str, Any] | None],
) -> "MainChatModelLoopRunner":
    return MainChatModelLoopRunner(
        get_run=get_run,
        default_profile_id=lambda: str(
            profile_service_factory().get_defaults().get("chat") or ""
        ).strip(),
        model_profile_config_private=model_profile_config_private,
        main_chat_agent_config=main_chat_agent_config,
        compile_agent_runtime=compile_agent_runtime,
        run_budget=run_budget,
        check_context_budget=check_context_budget,
        runtime_agent_timeline=runtime_agent_timeline,
        timeline_factory=timeline_factory,
        update_run=update_run,
        append_run_event=append_run_event,
        task_model_events=task_model_events,
        tool_brokers=tool_brokers,
        continue_custom_api_agent=continue_custom_api_agent,
        main_chat_pending_approval=main_chat_pending_approval,
        approval_pause=approval_pause,
        terminal_run_or_none=terminal_run_or_none,
        redact_secrets=redact_secrets,
        model_output_metadata=model_output_metadata,
        error_type=AgentRuntimeError,
    )


class MainChatModelLoopRunner:
    """Orchestrates the daily Chat model loop while preserving approval gates."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        default_profile_id: Callable[[], str],
        model_profile_config_private: Callable[[str], dict[str, Any]],
        main_chat_agent_config: Callable[..., dict[str, Any]],
        compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        check_context_budget: Callable[[Any, list[dict[str, Any]]], None],
        runtime_agent_timeline: Any,
        timeline_factory: Callable[..., dict[str, Any]],
        update_run: Callable[..., dict[str, Any]],
        append_run_event: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        task_model_events: Any,
        tool_brokers: Any,
        continue_custom_api_agent: Callable[..., str],
        main_chat_pending_approval: Callable[..., dict[str, Any]],
        approval_pause: Any,
        terminal_run_or_none: Callable[[str], dict[str, Any] | None],
        redact_secrets: Callable[[Any], str],
        model_output_metadata: Callable[[Any], dict[str, Any]],
        error_type: type[Exception],
    ) -> None:
        self._get_run = get_run
        self._default_profile_id = default_profile_id
        self._model_profile_config_private = model_profile_config_private
        self._main_chat_agent_config = main_chat_agent_config
        self._compile_agent_runtime = compile_agent_runtime
        self._run_budget = run_budget
        self._check_context_budget = check_context_budget
        self._runtime_agent_timeline = runtime_agent_timeline
        self._timeline = timeline_factory
        self._update_run = update_run
        self._append_run_event = append_run_event
        self._task_model_events = task_model_events
        self._tool_brokers = tool_brokers
        self._continue_custom_api_agent = continue_custom_api_agent
        self._main_chat_pending_approval = main_chat_pending_approval
        self._approval_pause = approval_pause
        self._terminal_run_or_none = terminal_run_or_none
        self._redact_secrets = redact_secrets
        self._model_output_metadata = model_output_metadata
        self._error_type = error_type

    def execute(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        profile_id: str = "",
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        runtime_execution_envelope: dict[str, Any] | None = None,
        runtime_execution_metadata: dict[str, Any] | None = None,
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._get_run(run_id)
        if str(run.get("kind") or "") != "main_chat_run":
            raise self._error_type("Run 不是主聊天 Native Run")
        runtime_execution_metadata = with_daily_entrypoint_desktop_execution_policy(
            runtime_execution_metadata,
            surface="chat",
        )
        default_profile_id = str(profile_id or self._default_profile_id() or "").strip()
        agent = self._main_chat_agent_config(
            model_profile_id=default_profile_id,
            tool_policy=tool_policy,
            workspace_policy=workspace_policy,
        )
        runtime = self._compile_agent_runtime(agent)
        timeline = [event for event in run.get("timeline") or [] if isinstance(event, dict)]
        budget = self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        timeline.append(
            self._runtime_agent_timeline.compiled(
                detail="Main chat NativeRunEngine compiled tools and workspace policy",
                allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            )
        )
        direct_daily_desktop_intent = self._will_handle_daily_desktop_intent(
            messages,
            runtime["tool_policy"].get("allowed_tools") or [],
            direct_tool_request=direct_tool_request,
            direct_tool_requests=direct_tool_requests,
            runtime_execution_envelope=runtime_execution_envelope,
            runtime_execution_metadata=runtime_execution_metadata,
        )
        if not default_profile_id and not direct_daily_desktop_intent:
            raise self._error_type("native_agent_not_ready:chat_model_profile_required")
        model_config = (
            self._model_profile_config_private(default_profile_id)
            if default_profile_id and not direct_daily_desktop_intent
            else {}
        )
        if not direct_daily_desktop_intent:
            timeline.append(
                self._timeline(
                    "model.request.started",
                    str(model_config.get("model") or ""),
                    profile_id=default_profile_id,
                    capability="chat",
                )
            )
        self._update_run(run_id, status="running", timeline=timeline)
        if not direct_daily_desktop_intent:
            self._append_run_event(
                run_id,
                "model.request.started",
                self._task_model_events.model_request_started_payload(
                    profile_id=default_profile_id,
                    model=str(model_config.get("model") or ""),
                    capability="chat",
                    message_count=len(messages),
                ),
            )
        broker_kwargs: dict[str, Any] = {}
        approval_required = runtime["tool_policy"].get("approval_required") or {}
        if approval_required:
            broker_kwargs["approvals"] = approval_required
        broker = self._tool_brokers.for_main_chat(
            run_id=run_id,
            workspace_policy=runtime["workspace_policy"],
            **broker_kwargs,
        )
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        try:
            result_text = self._continue_custom_api_agent(
                agent,
                "",
                broker,
                timeline,
                artifacts,
                messages=messages,
                direct_tool_request=direct_tool_request,
                direct_tool_requests=direct_tool_requests,
                runtime_execution_envelope=runtime_execution_envelope,
                runtime_execution_metadata=runtime_execution_metadata,
                run_id=run_id,
                budget=budget,
            )
        except AgentApprovalRequired as exc:
            pending = self._main_chat_pending_approval(
                exc.pending_approval,
                model_profile_id=default_profile_id,
                tool_policy=runtime["tool_policy"],
                workspace_policy=runtime["workspace_policy"],
                runtime_execution_envelope=runtime_execution_envelope,
                runtime_execution_metadata=runtime_execution_metadata,
            )
            return self._approval_pause.project_tool_required(
                run_id,
                pending_approval=pending,
                timeline=timeline,
                artifacts=artifacts,
            )
        except Exception as exc:
            terminal = self._terminal_run_or_none(run_id)
            if terminal is not None:
                return terminal
            provider_blocker = (
                _desktop_provider_required_failure(timeline)
                if (
                    direct_daily_desktop_intent
                    and not default_profile_id
                    and _is_missing_chat_profile_error(exc)
                )
                else {}
            )
            safe_error = str(
                provider_blocker.get("summary") or self._redact_secrets(exc)
            )
            failure_event = (
                "agent.desktop.permission_recovery"
                if provider_blocker
                else "model.request.failed"
            )
            timeline.append(
                self._timeline(
                    failure_event,
                    safe_error,
                    **(
                        {
                            "status": "blocked",
                            "recovery_actions": provider_blocker["recovery_actions"],
                            "blocking_conditions": provider_blocker[
                                "blocking_conditions"
                            ],
                        }
                        if provider_blocker
                        else {}
                    ),
                )
            )
            self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=None,
            )
            event_payload = (
                {
                    "error": safe_error,
                    "status": "blocked",
                    "recovery_actions": provider_blocker["recovery_actions"],
                    "blocking_conditions": provider_blocker["blocking_conditions"],
                }
                if provider_blocker
                else self._task_model_events.model_request_failed_payload(safe_error)
            )
            self._append_run_event(run_id, failure_event, event_payload)
            if provider_blocker:
                raise self._error_type(safe_error) from exc
            raise
        terminal = self._terminal_run_or_none(run_id)
        if terminal is not None:
            return terminal

        timeline.append(
            self._timeline(
                "model.output.ready",
                result_text[:500],
                output_chars=len(result_text),
                truncated=bool(getattr(result_text, "output_truncated", False)),
            )
        )
        self._append_run_event(
            run_id,
            "model.output.completed",
            self._task_model_events.model_output_completed_payload(
                str(result_text),
                truncated=bool(getattr(result_text, "output_truncated", False)),
                metadata=self._model_output_metadata(result_text),
            ),
        )
        return self._update_run(
            run_id,
            status="running",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

    @staticmethod
    def _will_handle_daily_desktop_intent(
        messages: list[dict[str, Any]],
        allowed_tools: list[str],
        *,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        runtime_execution_envelope: dict[str, Any] | None = None,
        runtime_execution_metadata: dict[str, Any] | None = None,
    ) -> bool:
        explicit_requests = [
            request
            for request in direct_tool_requests or []
            if isinstance(request, dict) and str(request.get("tool") or "").strip()
        ]
        if (
            isinstance(direct_tool_request, dict)
            and str(direct_tool_request.get("tool") or "").strip()
        ):
            explicit_requests.append(direct_tool_request)
        if explicit_requests:
            return daily_desktop_requests_can_complete_without_model(explicit_requests)
        for requests in (
            runtime_execution_requests_from_envelope_payload(
                runtime_execution_envelope,
                allowed_tools=allowed_tools,
            ),
            runtime_execution_requests_from_metadata(
                runtime_execution_metadata,
                allowed_tools=allowed_tools,
            ),
        ):
            if requests and not any(
                bool(request.get("continue_to_model"))
                for request in requests
                if isinstance(request, dict)
            ):
                return True
            if daily_desktop_requests_can_complete_without_model(requests):
                return True
        if messages_require_model_first(messages):
            return False
        intent_text = _latest_user_intent_text(messages)
        if not intent_text:
            return False
        try:
            selection = planner_first_direct_tool_selection(
                intent_text,
                allowed_tools,
            )
            planned_requests = selection.requests
            if planned_requests:
                if not any(
                    bool(request.get("continue_to_model"))
                    for request in planned_requests
                    if isinstance(request, dict)
                ):
                    return True
                if daily_desktop_requests_can_complete_without_model(planned_requests):
                    return True
                return planner_discovered_app_followup_can_direct_execute(
                    selection.event_payload,
                    planned_requests,
                    allowed_tools,
                    allow_open_path=True,
                )
        except Exception:
            pass
        return False


def _latest_user_intent_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") != "user":
            continue
        content = message_visible_content_text(message).strip()
        if content:
            return content
    return ""


_DESKTOP_PROVIDER_BLOCKING_CONDITIONS = {
    "desktop_backend_not_release_ready",
    "desktop_execution_provider_adapter_unavailable",
    "desktop_execution_provider_unavailable",
    "desktop_provider_authentication_required",
    "desktop_provider_missing_required_tools",
    "loopback_desktop_backend",
    "real_virtual_desktop_backend_required",
    "sandbox_desktop_provider_required",
    "sandbox_keyboard_mouse_provider_required",
}


def _desktop_provider_required_failure(
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.skipped":
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if str(result.get("error") or "").strip() != "desktop_execution_policy_blocked":
            continue
        blockers = sorted(
            {
                str(value or "").strip()
                for value in result.get("blocking_conditions") or []
                if str(value or "").strip() in _DESKTOP_PROVIDER_BLOCKING_CONDITIONS
            }
        )
        if not blockers:
            continue
        recovery_actions = [
            dict(action)
            for action in result.get("recovery_actions") or []
            if isinstance(action, dict)
        ]
        if not recovery_actions:
            recovery_actions = [
                {
                    "tool": "desktop.provider_session.start",
                    "label": "Start isolated desktop provider",
                    "input": {"diagnostic_route": "/yachiyo/studio/tools"},
                    "planning_reason": "desktop_provider_session_recovery",
                    "permission_target": "isolated_desktop_provider",
                    "risk_level": "medium",
                    "approval_required": True,
                    "approval_status": "pending",
                }
            ]
        real_provider_required = bool(
            {"loopback_desktop_backend", "real_virtual_desktop_backend_required"}
            .intersection(blockers)
        )
        return {
            "blocking_conditions": blockers,
            "recovery_actions": recovery_actions,
            "summary": (
                "桌面任务需要真实的隔离桌面 Provider；当前开发 Provider 不能执行此前台操作。"
                "请在 Agent Studio 配置 Provider 后重试，或选择受监督执行。"
                if real_provider_required
                else "桌面任务需要隔离桌面 Provider，当前环境尚未就绪。"
                "请在 Agent Studio 配置 Provider 后重试，或选择受监督执行。"
            ),
        }
    return {}


def _is_missing_chat_profile_error(error: Exception) -> bool:
    detail = str(error or "").strip()
    return bool(
        "缺少可运行的 Chat Profile" in detail
        or detail == "native_agent_not_ready:chat_model_profile_required"
    )
