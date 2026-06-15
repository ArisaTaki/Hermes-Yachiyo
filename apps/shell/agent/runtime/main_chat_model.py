"""Main chat model-call helper for the legacy runtime entrypoint."""

from __future__ import annotations

from typing import Any, Callable


class MainChatModelCaller:
    """Runs a single daily Chat model request and records replayable events."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        default_profile_id: Callable[[str], str],
        model_profile_config_private: Callable[..., dict[str, Any]],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        check_context_budget: Callable[[Any, list[dict[str, Any]]], None],
        limit_model_output: Callable[[Any], tuple[str, bool]],
        timeline_factory: Callable[..., dict[str, Any]],
        update_run: Callable[..., dict[str, Any]],
        append_run_event: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        task_model_events: Any,
        call_model: Callable[..., Any],
        coalesce_model_message: Callable[[Any], dict[str, Any]],
        message_visible_content_text: Callable[[dict[str, Any]], str],
        model_message_metadata: Callable[[dict[str, Any]], dict[str, Any]],
        terminal_run_or_none: Callable[[str], dict[str, Any] | None],
        redact_secrets: Callable[[Any], str],
        error_type: type[Exception],
    ) -> None:
        self._get_run = get_run
        self._default_profile_id = default_profile_id
        self._model_profile_config_private = model_profile_config_private
        self._run_budget = run_budget
        self._check_context_budget = check_context_budget
        self._limit_model_output = limit_model_output
        self._timeline = timeline_factory
        self._update_run = update_run
        self._append_run_event = append_run_event
        self._task_model_events = task_model_events
        self._call_model = call_model
        self._coalesce_model_message = coalesce_model_message
        self._message_visible_content_text = message_visible_content_text
        self._model_message_metadata = model_message_metadata
        self._terminal_run_or_none = terminal_run_or_none
        self._redact_secrets = redact_secrets
        self._error_type = error_type

    def call(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        profile_id: str = "",
        capability: str = "chat",
    ) -> str:
        run = self._get_run(run_id)
        if str(run.get("kind") or "") != "main_chat_run":
            raise self._error_type("Run 不是主聊天 Native Run")
        default_profile_id = str(profile_id or self._default_profile_id(capability) or "").strip()
        if not default_profile_id:
            raise self._error_type(f"native_agent_not_ready:{capability}_model_profile_required")
        model_config = self._model_profile_config_private(default_profile_id, capability=capability)
        timeline = list(run.get("timeline") or [])
        budget = self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        budget.claim_model_call()
        timeline.append(
            self._timeline(
                "model.request.started",
                str(model_config.get("model") or ""),
                profile_id=default_profile_id,
                capability=capability,
            )
        )
        self._update_run(run_id, timeline=timeline)
        self._append_run_event(
            run_id,
            "model.request.started",
            self._task_model_events.model_request_started_payload(
                profile_id=default_profile_id,
                model=str(model_config.get("model") or ""),
                capability=capability,
                message_count=len(messages),
            ),
        )
        try:
            message = self._coalesce_model_message(
                self._call_model(
                    str(model_config.get("base_url") or ""),
                    str(model_config.get("model") or ""),
                    str(model_config.get("api_key") or ""),
                    messages,
                    stream=True,
                )
            )
            content, output_truncated = self._limit_model_output(
                self._message_visible_content_text(message)
            )
            content = content.strip()
            if not content:
                raise self._error_type("Native Agent 模型返回了空回复")
            output_metadata = self._model_message_metadata(message)
        except Exception as exc:
            terminal = self._terminal_run_or_none(run_id)
            if terminal is not None:
                return str(terminal.get("result") or "")
            safe_error = self._redact_secrets(exc)
            timeline.append(self._timeline("model.request.failed", safe_error))
            self._update_run(run_id, timeline=timeline)
            self._append_run_event(
                run_id,
                "model.request.failed",
                self._task_model_events.model_request_failed_payload(safe_error),
            )
            raise
        terminal = self._terminal_run_or_none(run_id)
        if terminal is not None:
            return str(terminal.get("result") or "")
        timeline.append(
            self._timeline(
                "model.output.completed",
                content[:500],
                output_chars=len(content),
                truncated=output_truncated,
            )
        )
        self._update_run(run_id, timeline=timeline)
        self._append_run_event(
            run_id,
            "model.output.completed",
            self._task_model_events.model_output_completed_payload(
                content,
                truncated=output_truncated,
                metadata=output_metadata,
            ),
        )
        return content
