"""Tests for run timeline access split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_timeline import RuntimeRunTimelineService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _FakeRuns:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def list(self, limit: int) -> dict[str, Any]:
        self.calls.append(("list", limit))
        return {"runs": [{"run_id": "run-1"}], "limit": limit}

    def get(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get", run_id))
        return {"run_id": run_id, "status": "completed"}


class _FakeRunGroups:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.child_runs = [
            {"run_id": "child-run-1"},
            {"run_id": "child-run-2"},
        ]

    def list(self, limit: int) -> dict[str, Any]:
        self.calls.append(("list", limit))
        return {"run_groups": [{"run_group_id": "group-1"}], "limit": limit}

    def get(self, run_group_id: str) -> dict[str, Any]:
        self.calls.append(("get", run_group_id))
        return {
            "run_group_id": run_group_id,
            "child_run_ids": ["child-run-2", "child-run-1"],
        }

    def source(self, run_group_id: str) -> str:
        self.calls.append(("source", run_group_id))
        return "workflow"

    def runs(self, run_group_id: str) -> list[dict[str, Any]]:
        self.calls.append(("runs", run_group_id))
        return list(self.child_runs)


class _FakeRuntimeEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.events_by_run_id: dict[str, list[dict[str, Any]]] = {}

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "append",
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "payload": payload or {},
                    "actor": actor,
                    "visibility": visibility,
                    "sensitivity": sensitivity,
                },
            )
        )
        return {"event_id": "event-1", "event_type": event_type}

    def list(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "list",
                {
                    "run_id": run_id,
                    "after_sequence": after_sequence,
                    "limit": limit,
                    "include_internal": include_internal,
                },
            )
        )
        return {
            "events": self.events_by_run_id.get(run_id, [{"event_type": "run.completed"}]),
            "run_id": run_id,
        }


class _FakeArtifacts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def read(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append((run_id, artifact_path))
        return {"ok": True, "run_id": run_id, "path": artifact_path, "content": "# Done"}


def test_runtime_run_timeline_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunTimelineService is RuntimeRunTimelineService


def test_runtime_run_timeline_service_delegates_run_group_and_artifact_access() -> None:
    runs = _FakeRuns()
    run_groups = _FakeRunGroups()
    runtime_events = _FakeRuntimeEvents()
    artifacts = _FakeArtifacts()
    service = RuntimeRunTimelineService(
        runs=runs,
        run_groups=run_groups,
        runtime_events=runtime_events,
        run_artifacts=artifacts,
    )

    assert service.list_runs(10) == {"runs": [{"run_id": "run-1"}], "limit": 10}
    assert service.get_run("run-1") == {"run_id": "run-1", "status": "completed"}
    assert service.list_run_groups(5) == {
        "run_groups": [{"run_group_id": "group-1"}],
        "limit": 5,
    }
    assert service.get_run_group("group-1") == {
        "run_group_id": "group-1",
        "child_run_ids": ["child-run-2", "child-run-1"],
    }
    assert service.run_group_source("group-1") == "workflow"
    assert service.read_artifact("run-1", "report.md") == {
        "ok": True,
        "run_id": "run-1",
        "path": "report.md",
        "content": "# Done",
    }
    assert runs.calls == [("list", 10), ("get", "run-1")]
    assert run_groups.calls == [
        ("list", 5),
        ("get", "group-1"),
        ("source", "group-1"),
    ]
    assert artifacts.calls == [("run-1", "report.md")]


def test_runtime_run_timeline_service_delegates_event_append_and_replay() -> None:
    runtime_events = _FakeRuntimeEvents()
    service = RuntimeRunTimelineService(
        runs=_FakeRuns(),
        run_groups=_FakeRunGroups(),
        runtime_events=runtime_events,
        run_artifacts=_FakeArtifacts(),
    )

    appended = service.append_event(
        "run-1",
        "agent.tool.call",
        {"tool": "terminal.run"},
        actor="tester",
        visibility="internal",
        sensitivity="secret",
    )
    replay = service.list_events(
        "run-1",
        after_sequence=2,
        limit=3,
        include_internal=True,
    )

    assert appended == {"event_id": "event-1", "event_type": "agent.tool.call"}
    assert replay == {"events": [{"event_type": "run.completed"}], "run_id": "run-1"}
    assert runtime_events.calls == [
        (
            "append",
            {
                "run_id": "run-1",
                "event_type": "agent.tool.call",
                "payload": {"tool": "terminal.run"},
                "actor": "tester",
                "visibility": "internal",
                "sensitivity": "secret",
            },
        ),
        (
            "list",
            {
                "run_id": "run-1",
                "after_sequence": 2,
                "limit": 3,
                "include_internal": True,
            },
        ),
    ]


def test_runtime_run_timeline_service_normalizes_run_event_page_requests() -> None:
    runtime_events = _FakeRuntimeEvents()
    service = RuntimeRunTimelineService(
        runs=_FakeRuns(),
        run_groups=_FakeRunGroups(),
        runtime_events=runtime_events,
        run_artifacts=_FakeArtifacts(),
    )

    service.list_events("run-1", after_sequence=-5, limit=5000)

    assert runtime_events.calls == [
        (
            "list",
            {
                "run_id": "run-1",
                "after_sequence": 0,
                "limit": 1000,
                "include_internal": False,
            },
        )
    ]


def test_runtime_run_timeline_service_projects_group_event_page_from_child_runs() -> None:
    run_groups = _FakeRunGroups()
    runtime_events = _FakeRuntimeEvents()
    runtime_events.events_by_run_id = {
        "child-run-1": [
            {
                "event_id": "event-child-1-1",
                "run_id": "child-run-1",
                "sequence": 1,
                "event_type": "agent.tool.call",
                "payload": {"tool": "workspace.read"},
            },
            {
                "event_id": "event-child-1-2",
                "run_id": "child-run-1",
                "sequence": 2,
                "event_type": "group.member.completed",
                "payload": {"member_agent_id": "agent-1"},
            },
        ],
        "child-run-2": [
            {
                "event_id": "event-child-2-4",
                "run_id": "child-run-2",
                "sequence": 4,
                "event_type": "group.member.started",
                "payload": {"member_agent_id": "agent-2"},
            }
        ],
    }
    service = RuntimeRunTimelineService(
        runs=_FakeRuns(),
        run_groups=run_groups,
        runtime_events=runtime_events,
        run_artifacts=_FakeArtifacts(),
    )

    first_page = service.list_group_events("group-1", after_sequence=0, limit=1)
    second_page = service.list_group_events("group-1", after_sequence=1, limit=1)

    assert first_page["run_id"] == "group-1"
    assert first_page["events"][0]["sequence"] == 1
    assert first_page["events"][0]["run_id"] == "group-1"
    assert first_page["events"][0]["event_type"] == "group.member.started"
    assert first_page["events"][0]["payload"]["source_run_id"] == "child-run-2"
    assert first_page["events"][0]["payload"]["source_sequence"] == 4
    assert first_page["events"][0]["payload"]["source_event_id"] == "event-child-2-4"
    assert first_page["has_more"] is True
    assert second_page["events"][0]["sequence"] == 2
    assert second_page["events"][0]["event_type"] == "group.member.completed"
    assert second_page["events"][0]["payload"]["source_run_id"] == "child-run-1"
    assert second_page["has_more"] is False
    assert ("get", "group-1") in run_groups.calls
    assert ("runs", "group-1") in run_groups.calls


def test_native_runtime_installs_run_timeline_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.run_timeline, RuntimeRunTimelineService)
        assert service.run_timeline._runs is service.runs
        assert service.run_timeline._run_groups is service.run_groups
        assert service.run_timeline._runtime_events is service.runtime_events
        assert service.run_timeline._run_artifacts is service.run_artifacts
    finally:
        service.close()
