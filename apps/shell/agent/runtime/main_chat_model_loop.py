"""Tool-capable main chat model loop orchestration."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_request,
    daily_desktop_intent_tool_requests,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.model_messages import message_visible_content_text, model_output_metadata
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    planner_first_direct_decision_and_tool_requests,
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
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._get_run(run_id)
        if str(run.get("kind") or "") != "main_chat_run":
            raise self._error_type("Run 不是主聊天 Native Run")
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
        )
        if not default_profile_id and not direct_daily_desktop_intent:
            raise self._error_type("native_agent_not_ready:chat_model_profile_required")
        model_config = (
            self._model_profile_config_private(default_profile_id)
            if default_profile_id
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
                run_id=run_id,
                budget=budget,
            )
        except AgentApprovalRequired as exc:
            pending = self._main_chat_pending_approval(
                exc.pending_approval,
                model_profile_id=default_profile_id,
                tool_policy=runtime["tool_policy"],
                workspace_policy=runtime["workspace_policy"],
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
            safe_error = self._redact_secrets(exc)
            timeline.append(self._timeline("model.request.failed", safe_error))
            self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=None,
            )
            self._append_run_event(
                run_id,
                "model.request.failed",
                self._task_model_events.model_request_failed_payload(safe_error),
            )
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
    ) -> bool:
        if any(
            isinstance(request, dict) and str(request.get("tool") or "").strip()
            for request in direct_tool_requests or []
        ):
            return True
        if isinstance(direct_tool_request, dict) and str(direct_tool_request.get("tool") or "").strip():
            return True
        intent_text = _latest_user_intent_text(messages)
        if not intent_text:
            return False
        try:
            _decision, planned_requests = planner_first_direct_decision_and_tool_requests(
                intent_text,
                allowed_tools,
                legacy_tool_requests=daily_desktop_intent_tool_requests,
            )
            if planned_requests:
                return not any(
                    bool(request.get("continue_to_model"))
                    for request in planned_requests
                    if isinstance(request, dict)
                )
        except Exception:
            pass
        if daily_desktop_intent_tool_request(intent_text, allowed_tools):
            return True
        return bool(daily_desktop_intent_candidates(intent_text))


def _latest_user_intent_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") != "user":
            continue
        content = message_visible_content_text(message).strip()
        if content:
            return content
    return ""
