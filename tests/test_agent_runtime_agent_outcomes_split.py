"""Tests for Agent Run outcome projection split out of the legacy runtime."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_outcomes import RuntimeAgentRunOutcomeProjector
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.group_runs import start_agent_group_run
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeTimeline:
    def completed(self) -> dict[str, Any]:
        return {"event": "agent.completed"}

    def failed(self, error: str) -> dict[str, Any]:
        return {"event": "agent.failed", "error": error}


class FakeTaskModelEvents:
    def model_output_completed_payload(
        self,
        content: str,
        *,
        truncated: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "content": content,
            "truncated": truncated,
            "metadata": metadata or {},
        }


class FakeRunEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def completed(self, run_id: str, result: str) -> None:
        self.calls.append(("completed", run_id, result))

    def failed(self, run_id: str, error: str) -> None:
        self.calls.append(("failed", run_id, error))


class FakeOutput(str):
    output_truncated = True
    model_metadata = {"finish_reason": "stop"}


def _projector(
    *,
    run_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] | None = None,
    run_updates: list[tuple[str, dict[str, Any]]] | None = None,
    recorder: FakeRunEvents | None = None,
    run_state: dict[str, Any] | None = None,
    cas_lost_to: dict[str, Any] | None = None,
    transaction_scope: Any | None = None,
    event_failure_index: int = 0,
    group_projections: list[dict[str, Any]] | None = None,
) -> RuntimeAgentRunOutcomeProjector:
    run_events = run_events if run_events is not None else []
    run_updates = run_updates if run_updates is not None else []
    current = run_state if run_state is not None else {
        "run_id": "run-1",
        "status": "running",
        "updated_at": "version-1",
        "pending_approval": None,
    }

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        run_updates.append((run_id, kwargs))
        if cas_lost_to is not None:
            current.clear()
            current.update(cas_lost_to)
            return None
        current.update(kwargs)
        current["updated_at"] = "version-2"
        return dict(current)

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        run_events.append((run_id, event_type, payload, fence))
        if event_failure_index and len(run_events) == event_failure_index:
            return None
        return {"event_type": event_type}

    return RuntimeAgentRunOutcomeProjector(
        append_run_event=append_run_event,
        runtime_task_model_events=FakeTaskModelEvents(),
        runtime_agent_timeline=FakeTimeline(),
        runtime_agent_run_events=recorder or FakeRunEvents(),
        get_run=lambda _run_id: dict(current),
        update_run=update_run,
        project_agent_run_group_if_root=(
            (lambda run: group_projections.append(dict(run)))
            if group_projections is not None
            else None
        ),
        model_output_metadata=lambda value: getattr(value, "model_metadata", {}),
        redact_secrets=lambda value: str(value).replace("sk-secret", "[REDACTED]"),
        transaction_scope=transaction_scope,
    )


def test_agent_run_outcome_projector_projects_completed_run() -> None:
    run_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    run_updates: list[tuple[str, dict[str, Any]]] = []
    recorder = FakeRunEvents()
    timeline = [{"event": "agent.started"}]
    artifacts = [{"kind": "context", "path": "agent-context.md"}]

    result = _projector(
        run_events=run_events,
        run_updates=run_updates,
        recorder=recorder,
    ).completed(
        "run-1",
        FakeOutput("Done"),
        timeline=timeline,
        artifacts=artifacts,
    )

    assert run_events == [
        (
            "run-1",
            "model.output.completed",
            {
                "content": "Done",
                "truncated": True,
                "metadata": {"finish_reason": "stop"},
            },
            {
                "expected_status": "completed",
                "expected_updated_at": "version-2",
            },
        ),
        (
            "run-1",
            "agent.run.completed",
            {"result": "Done"},
            {
                "expected_status": "completed",
                "expected_updated_at": "version-2",
            },
        ),
    ]
    assert timeline == [{"event": "agent.started"}, {"event": "agent.completed"}]
    assert recorder.calls == []
    assert run_updates == [
        (
            "run-1",
            {
                "status": "completed",
                "result": "Done",
                "timeline": timeline,
                "artifacts": artifacts,
                "pending_approval": None,
                "expected_status": "running",
                "expected_updated_at": "version-1",
                "expected_pending_approval_absent": True,
            },
        )
    ]
    assert result["status"] == "completed"
    assert result["result"] == "Done"


def test_agent_run_outcome_projector_projects_failed_run_with_redaction() -> None:
    run_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    run_updates: list[tuple[str, dict[str, Any]]] = []
    recorder = FakeRunEvents()
    timeline = [{"event": "agent.started"}]

    result = _projector(
        run_events=run_events,
        run_updates=run_updates,
        recorder=recorder,
    ).failed(
        "run-1",
        RuntimeError("provider leaked sk-secret"),
        timeline=timeline,
        artifacts=[],
    )

    assert timeline == [
        {"event": "agent.started"},
        {"event": "agent.failed", "error": "provider leaked [REDACTED]"},
    ]
    assert recorder.calls == []
    assert run_events == [
        (
            "run-1",
            "agent.run.failed",
            {"error": "provider leaked [REDACTED]"},
            {
                "expected_status": "failed",
                "expected_updated_at": "version-2",
            },
        ),
    ]
    assert run_updates == [
        (
            "run-1",
            {
                "status": "failed",
                "result": "provider leaked [REDACTED]",
                "timeline": timeline,
                "artifacts": [],
                "pending_approval": None,
                "expected_status": "running",
                "expected_updated_at": "version-1",
                "expected_pending_approval_absent": True,
            },
        )
    ]
    assert result["status"] == "failed"
    assert result["result"] == "provider leaked [REDACTED]"


def test_agent_run_completion_lost_cas_returns_fresh_terminal_without_events() -> None:
    run_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    timeline = [{"event": "agent.started"}]
    cancelled = {
        "run_id": "run-1",
        "status": "cancelled",
        "updated_at": "version-cancelled",
        "result": "Run cancelled",
        "pending_approval": None,
    }
    group_projections: list[dict[str, Any]] = []

    result = _projector(
        run_events=run_events,
        cas_lost_to=cancelled,
        group_projections=group_projections,
    ).completed("run-1", "late completion", timeline=timeline, artifacts=[])

    assert result == cancelled
    assert timeline == [{"event": "agent.started"}]
    assert run_events == []
    assert group_projections == []


def test_agent_run_failure_lost_cas_returns_fresh_terminal_without_events() -> None:
    run_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    timeline = [{"event": "agent.started"}]
    completed = {
        "run_id": "run-1",
        "status": "completed",
        "updated_at": "version-completed",
        "result": "Done",
        "pending_approval": None,
    }
    group_projections: list[dict[str, Any]] = []

    result = _projector(
        run_events=run_events,
        cas_lost_to=completed,
        group_projections=group_projections,
    ).failed("run-1", RuntimeError("late failure"), timeline=timeline, artifacts=[])

    assert result == completed
    assert timeline == [{"event": "agent.started"}]
    assert run_events == []
    assert group_projections == []


def test_agent_run_completion_rolls_back_row_and_events_when_second_event_fails() -> None:
    run = {
        "run_id": "run-1",
        "status": "running",
        "updated_at": "version-1",
        "pending_approval": None,
    }
    run_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    timeline = [{"event": "agent.started"}]

    @contextmanager
    def transaction_scope() -> Any:
        run_snapshot = deepcopy(run)
        events_snapshot = list(run_events)
        try:
            yield
        except BaseException:
            run.clear()
            run.update(run_snapshot)
            run_events[:] = events_snapshot
            raise

    projector = _projector(
        run_events=run_events,
        run_state=run,
        transaction_scope=transaction_scope,
        event_failure_index=2,
    )

    with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
        projector.completed("run-1", "done", timeline=timeline, artifacts=[])

    assert run == {
        "run_id": "run-1",
        "status": "running",
        "updated_at": "version-1",
        "pending_approval": None,
    }
    assert run_events == []
    assert timeline == [{"event": "agent.started"}]


def test_native_agent_outcome_transaction_rolls_back_sqlite_row_and_events(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        created = service._insert_run(
            kind="agent_run",
            runnable_id="agent-atomic",
            user_goal="prove terminal atomicity",
        )
        running = service._update_run(created["run_id"], status="running")
        before_events = service.list_run_events(created["run_id"])["events"]
        original_append = service.agent_run_outcomes._append_run_event
        append_calls = 0

        def fail_second_terminal_event(
            run_id: str,
            event_type: str,
            payload: dict[str, Any],
            **fence: Any,
        ) -> dict[str, Any] | None:
            nonlocal append_calls
            append_calls += 1
            if append_calls == 2:
                return None
            return original_append(run_id, event_type, payload, **fence)

        service.agent_run_outcomes._append_run_event = fail_second_terminal_event
        timeline = list(running.get("timeline") or [])

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            service.agent_run_outcomes.completed(
                created["run_id"],
                "done",
                timeline=timeline,
                artifacts=[],
            )

        restored = service.get_run(created["run_id"])
        assert restored["status"] == "running"
        assert restored.get("result") in {None, ""}
        assert service.list_run_events(created["run_id"])["events"] == before_events
        assert timeline == list(running.get("timeline") or [])
    finally:
        service.close()


def test_native_root_agent_completion_commits_run_group_and_terminal_facts_together(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Atomic agent", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-atomic",
            user_goal="commit root outcome",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        timeline = list(run.get("timeline") or [])

        result = service.agent_run_outcomes.completed(
            run["run_id"],
            "done",
            timeline=timeline,
            artifacts=[],
        )

        stored_group = service.get_run_group(group["run_group_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(
                run["run_id"],
                include_internal=True,
            )["events"]
        ]
        assert result["status"] == "completed"
        assert stored_group["status"] == "completed"
        assert stored_group["summary"] == "done"
        assert "agent.run.completed" in event_types
        assert "run.completed" in event_types
        assert "group.run.completed" in event_types
        assert event_types.index("agent.run.completed") < event_types.index(
            "run.completed"
        ) < event_types.index("group.run.completed")

        # The sync/async entrypoint compatibility callback may project again.
        # An identical committed winner is a strict idempotent no-op.
        before_group = dict(stored_group)
        before_events = list(event_types)
        service._project_agent_run_group_if_root(result)
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert [
            event["event_type"]
            for event in service.list_run_events(
                run["run_id"],
                include_internal=True,
            )["events"]
        ] == before_events
    finally:
        service.close()


def test_native_root_agent_alias_failure_rolls_back_run_group_and_all_events(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Atomic agent", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-atomic",
            user_goal="rollback alias failure",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        original_append = service.runtime_events._repository.append

        def fail_agent_alias(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == "run.completed":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        service.runtime_events._repository.append = fail_agent_alias
        timeline = list(before_run.get("timeline") or [])

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            service.agent_run_outcomes.completed(
                run["run_id"],
                "done",
                timeline=timeline,
                artifacts=[],
            )

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == list(before_run.get("timeline") or [])
    finally:
        service.close()


def test_native_root_agent_group_event_failure_rolls_back_agent_and_group(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Atomic agent", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-atomic",
            user_goal="rollback group event failure",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        original_append = service.runtime_events._repository.append

        def fail_group_event(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == "group.run.failed":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        service.runtime_events._repository.append = fail_group_event
        timeline = list(before_run.get("timeline") or [])

        with pytest.raises(AgentRuntimeError, match="run_group_event_fence_mismatch"):
            service.agent_run_outcomes.failed(
                run["run_id"],
                RuntimeError("boom"),
                timeline=timeline,
                artifacts=[],
            )

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == list(before_run.get("timeline") or [])
    finally:
        service.close()


def test_native_root_agent_group_cas_failure_rolls_back_agent_and_events(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Atomic agent", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-atomic",
            user_goal="rollback group CAS failure",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        service.agent_run_group_projection._update_run_group = (
            lambda _run_group_id, **_kwargs: None
        )
        timeline = list(before_run.get("timeline") or [])

        with pytest.raises(AgentRuntimeError, match="run_group_projection_cas_lost"):
            service.agent_run_outcomes.completed(
                run["run_id"],
                "done",
                timeline=timeline,
                artifacts=[],
            )

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == list(before_run.get("timeline") or [])
    finally:
        service.close()


def test_two_member_async_group_uses_aggregator_as_only_terminal_authority(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    callbacks: dict[str, Any] = {}

    class DeferredGroupRuntime:
        @staticmethod
        def resolve_runnable(**kwargs: Any) -> dict[str, Any]:
            runnable_id = str(kwargs.get("runnable_id") or "")
            return {"kind": "agent", "id": runnable_id, "enabled": True}

        @staticmethod
        def create_run_for_runnable_async(**payload: Any) -> dict[str, Any]:
            run_group_id = str(payload.get("run_group_id") or "")
            if not run_group_id:
                group = service._insert_run_group(
                    title="Two-member group",
                    source="agent",
                )
                run_group_id = group["run_group_id"]
            run = service._insert_run(
                kind="agent_run",
                runnable_id=str(payload.get("runnable_id") or ""),
                user_goal=str(payload.get("user_goal") or ""),
                run_group_id=run_group_id,
                project_root_group=bool(payload.get("project_root_group")),
            )
            callbacks[run["run_id"]] = payload.get("on_complete")
            return {**run, "status": "processing"}

        get_run_group = staticmethod(service.get_run_group)
        get_run = staticmethod(service.get_run)
        append_run_event = staticmethod(service.append_run_event)
        list_run_events = staticmethod(service.list_run_events)
        _update_run_group = staticmethod(service._update_run_group)

    runtime = DeferredGroupRuntime()
    try:
        started = start_agent_group_run(
            runtime,
            {"group_id": "group-two", "objective": "Compare findings"},
            group={
                "group_id": "group-two",
                "name": "Two members",
                "members": [
                    {"agent_id": "agent-one", "sort_order": 1},
                    {"agent_id": "agent-two", "sort_order": 2},
                ],
            },
        )
        child_run_ids = list(started["child_run_ids"])
        assert len(child_run_ids) == 2
        assert service.get_run_group(started["run_group_id"])["status"] == "running"
        assert all(
            service.get_run(run_id)["project_root_group"] is False
            for run_id in child_run_ids
        )

        first = service.get_run(child_run_ids[0])
        first_timeline = list(first.get("timeline") or [])
        first_completed = service.agent_run_outcomes.completed(
            first["run_id"],
            "first done",
            timeline=first_timeline,
            artifacts=[],
        )
        callbacks[first["run_id"]](first_completed)

        assert service.get_run(first["run_id"])["status"] == "completed"
        assert service.get_run(child_run_ids[1])["status"] == "running"
        assert service.get_run_group(started["run_group_id"])["status"] == "running"

        second = service.get_run(child_run_ids[1])
        second_timeline = list(second.get("timeline") or [])
        second_completed = service.agent_run_outcomes.completed(
            second["run_id"],
            "second done",
            timeline=second_timeline,
            artifacts=[],
        )
        assert service.get_run_group(started["run_group_id"])["status"] == "running"
        callbacks[second["run_id"]](second_completed)

        stored_group = service.get_run_group(started["run_group_id"])
        assert service.get_run(first["run_id"])["status"] == "completed"
        assert service.get_run(second["run_id"])["status"] == "completed"
        assert stored_group["status"] == "completed"
        assert "first done" in stored_group["summary"]
        assert "second done" in stored_group["summary"]
        group_terminal_events = [
            event
            for run_id in child_run_ids
            for event in service.list_run_events(
                run_id,
                include_internal=True,
            )["events"]
            if event["event_type"] == "group.run.completed"
        ]
        assert len(group_terminal_events) == 1
    finally:
        service.close()


def test_native_runtime_uses_split_agent_run_outcome_projector(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeAgentRunOutcomeProjector is RuntimeAgentRunOutcomeProjector
        assert isinstance(service.agent_run_outcomes, RuntimeAgentRunOutcomeProjector)
    finally:
        service.close()
