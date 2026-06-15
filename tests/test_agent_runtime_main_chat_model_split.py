"""Tests for main chat model caller split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.main_chat_model import MainChatModelCaller
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBudget:
    def __init__(self) -> None:
        self.claims = 0

    def claim_model_call(self) -> None:
        self.claims += 1


class FakeTaskModelEvents:
    @staticmethod
    def model_request_started_payload(**payload: Any) -> dict[str, Any]:
        return {"started": payload}

    @staticmethod
    def model_request_failed_payload(error: str) -> dict[str, Any]:
        return {"error": error}

    @staticmethod
    def model_output_completed_payload(
        content: str,
        *,
        truncated: bool,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {"content": content, "truncated": truncated, **metadata}


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def test_main_chat_model_caller_records_replayable_model_events() -> None:
    budget = FakeBudget()
    run = {"run_id": "run-1", "kind": "main_chat_run", "timeline": []}
    updates: list[dict[str, Any]] = []
    events: list[tuple[str, dict[str, Any]]] = []
    checked_messages: list[list[dict[str, Any]]] = []
    profile_calls: list[tuple[str, str]] = []

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any]:
        snapshot = {
            key: list(value) if key == "timeline" and isinstance(value, list) else value
            for key, value in payload.items()
        }
        updates.append(snapshot)
        return {**run, **snapshot}

    caller = MainChatModelCaller(
        get_run=lambda run_id: run,
        default_profile_id=lambda capability: f"profile-{capability}",
        model_profile_config_private=lambda profile_id, *, capability: profile_calls.append(
            (profile_id, capability)
        )
        or {"base_url": "https://model.local", "model": "test-model", "api_key": "key"},
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, messages: checked_messages.append(messages),
        limit_model_output=lambda value: (str(value), False),
        timeline_factory=_timeline,
        update_run=update_run,
        append_run_event=lambda _run_id, event_type, payload: events.append((event_type, payload))
        or {"event_type": event_type, "payload": payload},
        task_model_events=FakeTaskModelEvents(),
        call_model=lambda *_args, **_kwargs: {"role": "assistant", "content": "hello"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {"finish_reason": "stop"},
        terminal_run_or_none=lambda _run_id: None,
        redact_secrets=lambda value: str(value).replace("secret", "[redacted]"),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = caller.call("run-1", [{"role": "user", "content": "hi"}], capability="vision")

    assert result == "hello"
    assert budget.claims == 1
    assert checked_messages == [[{"role": "user", "content": "hi"}]]
    assert profile_calls == [("profile-vision", "vision")]
    assert updates[0]["timeline"][-1]["event"] == "model.request.started"
    assert updates[1]["timeline"][-1]["event"] == "model.output.completed"
    assert events == [
        (
            "model.request.started",
            {
                "started": {
                    "profile_id": "profile-vision",
                    "model": "test-model",
                    "capability": "vision",
                    "message_count": 1,
                }
            },
        ),
        (
            "model.output.completed",
            {"content": "hello", "truncated": False, "finish_reason": "stop"},
        ),
    ]


def test_main_chat_model_caller_keeps_terminal_run_idempotent_after_model_returns() -> None:
    budget = FakeBudget()
    caller = MainChatModelCaller(
        get_run=lambda _run_id: {"run_id": "run-1", "kind": "main_chat_run", "timeline": []},
        default_profile_id=lambda _capability: "profile-chat",
        model_profile_config_private=lambda _profile_id, *, capability: {
            "base_url": "",
            "model": capability,
            "api_key": "",
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        limit_model_output=lambda value: (str(value), False),
        timeline_factory=_timeline,
        update_run=lambda _run_id, **payload: {"run_id": "run-1", **payload},
        append_run_event=lambda _run_id, event_type, payload: {"event_type": event_type, "payload": payload},
        task_model_events=FakeTaskModelEvents(),
        call_model=lambda *_args, **_kwargs: {"role": "assistant", "content": "late output"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        terminal_run_or_none=lambda _run_id: {"status": "cancelled", "result": "cancelled result"},
        redact_secrets=str,
        error_type=agent_runtime.AgentRuntimeError,
    )

    assert caller.call("run-1", [{"role": "user", "content": "hi"}]) == "cancelled result"


def test_native_runtime_installs_main_chat_model_caller_and_preserves_monkeypatch(tmp_path, monkeypatch) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {"role": "assistant", "content": "patched"},
    )
    try:
        assert agent_runtime.MainChatModelCaller is MainChatModelCaller
        assert isinstance(service.main_chat_model, MainChatModelCaller)
        assert getattr(service.main_chat_model._run_budget, "__self__", None) is not service
        assert getattr(service.main_chat_model._check_context_budget, "__self__", None) is not service
        assert getattr(service.main_chat_model._limit_model_output, "__self__", None) is not service

        service.runtime_limits = RunBudgetLimits(max_model_output_chars=5)
        limited, truncated = service.main_chat_model._limit_model_output("abcdefghi")
        assert truncated is True
        assert limited == "abcde"
        service.runtime_limits = RunBudgetLimits()

        run = service.start_main_chat_run(
            task_id="task-main-model",
            session_id="session-main-model",
            user_goal="hello",
        )
        result = service.call_main_chat_model(run["run_id"], [{"role": "user", "content": "hello"}])

        assert result == "patched"
    finally:
        service.close()


class _FakeDefaultProfileService:
    def get_defaults(self) -> dict[str, str]:
        return {"chat": "profile-chat"}

    def get_profile_private(self, profile_id: str) -> dict[str, Any]:
        return {
            "profile_id": profile_id,
            "provider": "openai_compatible",
            "base_url": "https://model.local",
            "model": "test-model",
            "api_key": "key",
            "credential_ref": "",
            "capability": "chat",
            "status": "available",
            "enabled": True,
        }
