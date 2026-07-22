"""Atomicity regressions for partially-started native GroupRuns."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell.agent.runtime.clock import utc_now_iso
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.group_runs import start_agent_group_run
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore

FAILED_START_SUMMARY = "群组启动失败。"
CLEANUP_PENDING_SUMMARY = "群组启动失败，正在停止已启动成员。"


class _PartialStartRuntime:
    def __init__(
        self,
        service: AgentRuntimeService,
        *,
        second_member_failure_mode: str = "raise",
        cancel_fails: bool = False,
    ) -> None:
        self.service = service
        self.second_member_failure_mode = second_member_failure_mode
        self.cancel_fails = cancel_fails
        self.claimed_run_ids: dict[str, str] = {}
        self.run_group_id = ""

    @staticmethod
    def resolve_runnable(**payload: Any) -> dict[str, Any]:
        runnable_id = str(payload.get("runnable_id") or "")
        return {"kind": "agent", "id": runnable_id, "enabled": True}

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        runnable_id = str(payload.get("runnable_id") or "")
        if runnable_id == "agent-b":
            if self.second_member_failure_mode == "completed_winner":
                self.service._update_run_group(
                    self.run_group_id,
                    status="completed",
                    summary="A concurrent owner completed the group.",
                )
            elif self.second_member_failure_mode == "missing_group":
                self.service.run_groups.delete(self.run_group_id)
                self.service._conn.commit()
            raise RuntimeError("injected second member start failure")

        client_run_id = str(payload.get("client_run_id") or "")
        claimed_run_id = self.claimed_run_ids.get(client_run_id)
        if claimed_run_id:
            return self.service.get_run(claimed_run_id)

        run_group_id = str(payload.get("run_group_id") or "")
        if not run_group_id:
            group = self.service._insert_run_group(
                title="Partial-start group",
                source="agent",
            )
            run_group_id = str(group["run_group_id"])
            self.run_group_id = run_group_id
        run = self.service._insert_run(
            kind="agent_run",
            runnable_id=runnable_id,
            user_goal=str(payload.get("user_goal") or ""),
            run_group_id=run_group_id,
            client_request_id=client_run_id,
            project_root_group=bool(payload.get("project_root_group")),
        )
        self.claimed_run_ids[client_run_id] = str(run["run_id"])
        return run

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        if self.cancel_fails:
            raise RuntimeError("injected cancellation failure")
        return self.service.cancel_run(run_id)

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        return self.service.append_run_event(run_id, event_type, payload, **fence)

    def list_run_events(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.service.list_run_events(run_id, **kwargs)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.service.get_run(run_id)

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return self.service.get_run_group(run_group_id)

    def _update_run_group(
        self,
        run_group_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        return self.service._update_run_group(run_group_id, **fields)


def _service(tmp_path: Any) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )


def _start(runtime: _PartialStartRuntime) -> dict[str, Any]:
    return start_agent_group_run(
        runtime,
        {
            "group_id": "group-partial",
            "objective": "Prepare the report",
            "client_run_id": "partial-start-request",
        },
        group={
            "group_id": "group-partial",
            "name": "Partial-start team",
            "members": [
                {"agent_id": "agent-a"},
                {"agent_id": "agent-b"},
            ],
        },
    )


def _terminal_group_events(
    service: AgentRuntimeService,
    run_id: str,
) -> list[dict[str, Any]]:
    return [
        event
        for event in service.list_run_events(
            run_id,
            include_internal=True,
            limit=1000,
        )["events"]
        if event["event_type"] in {
            "group.run.completed",
            "group.run.failed",
            "group.run.cancelled",
        }
    ]


def _group_cleanup_events(
    service: AgentRuntimeService,
    run_id: str,
) -> list[dict[str, Any]]:
    return [
        event
        for event in service.list_run_events(
            run_id,
            include_internal=True,
            limit=1000,
        )["events"]
        if event["event_type"] == "group.cleanup.requested"
    ]


def _create_runtime_group_agents(service: AgentRuntimeService) -> list[str]:
    agent_ids: list[str] = []
    for name in ("Planner", "Reviewer"):
        agent = service.create_agent(
            {
                "name": name,
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-test-only",
                },
            }
        )
        agent_ids.append(str(agent["agent_id"]))
    return agent_ids


def test_group_publishes_all_start_facts_before_any_child_thread_starts(
    tmp_path: Any,
) -> None:
    service = _service(tmp_path)
    publication_snapshots: list[list[str]] = []

    class _PublicationSnapshotThread:
        def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self) -> None:
            publication_snapshots.append(
                [
                    str(row["event_type"])
                    for row in service._conn.execute(
                        "SELECT event_type FROM run_events ORDER BY rowid"
                    ).fetchall()
                ]
            )

    try:
        agent_ids = _create_runtime_group_agents(service)
        service.agent_run_async_coordinator._thread_factory = (
            _PublicationSnapshotThread
        )

        result = start_agent_group_run(
            service,
            {
                "group_id": "group-publication-order",
                "objective": "Prepare the report",
                "client_run_id": "publication-order-request",
            },
            group={
                "group_id": "group-publication-order",
                "name": "Publication order team",
                "members": [{"agent_id": agent_id} for agent_id in agent_ids],
            },
        )

        assert len(result["child_run_ids"]) == 2
        assert len(publication_snapshots) == 2
        for snapshot in publication_snapshots:
            assert "group.run.started" in snapshot
            assert "group.run.plan" in snapshot
            assert "group.run.plan.created" in snapshot
            assert snapshot.count("group.member.started") == 2
            assert "agent.plan.created" in snapshot
    finally:
        service.close()


@pytest.mark.parametrize(
    "failed_event_type",
    [
        "group.run.plan",
        "group.run.plan.created",
        "group.member.started",
        "agent.plan.created",
    ],
)
def test_group_publication_fault_records_cleanup_before_any_child_execution(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    failed_event_type: str,
) -> None:
    service = _service(tmp_path)
    thread_starts: list[str] = []
    original_append = service.append_run_event
    failed_once = False

    class _TrackingDeferredThread:
        def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self) -> None:
            thread_starts.append(self.name)

    def fail_publication_once(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        nonlocal failed_once
        if event_type == failed_event_type and not failed_once:
            failed_once = True
            raise RuntimeError(f"injected {failed_event_type} publication failure")
        return original_append(run_id, event_type, payload, **fence)

    monkeypatch.setattr(service, "append_run_event", fail_publication_once)
    try:
        agent_ids = _create_runtime_group_agents(service)
        service.agent_run_async_coordinator._thread_factory = _TrackingDeferredThread

        result = start_agent_group_run(
            service,
            {
                "group_id": "group-publication-fault",
                "objective": "Prepare the report",
                "client_run_id": f"publication-fault-{failed_event_type}",
            },
            group={
                "group_id": "group-publication-fault",
                "name": "Publication fault team",
                "members": [{"agent_id": agent_id} for agent_id in agent_ids],
            },
        )

        assert failed_once is True
        assert thread_starts == []
        assert result["status"] == "failed"
        assert result["cleanup"]["complete"] is True
        assert result["child_run_ids"]
        assert all(
            service.get_run(run_id)["status"] == "cancelled"
            for run_id in result["child_run_ids"]
        )
        assert len(
            _group_cleanup_events(service, str(result["child_run_ids"][0]))
        ) == 1
    finally:
        service.close()


def test_partial_group_start_commits_one_failed_group_fact(tmp_path: Any) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    try:
        result = _start(runtime)

        run_id = str(result["child_run_ids"][0])
        stored_group = service.get_run_group(runtime.run_group_id)
        terminal_events = _terminal_group_events(service, run_id)

        assert result["status"] == stored_group["status"] == "failed"
        assert result["summary"] == stored_group["summary"] == FAILED_START_SUMMARY
        assert service.get_run(run_id)["status"] == "cancelled"
        cleanup_events = _group_cleanup_events(service, run_id)
        assert len(cleanup_events) == 1
        assert cleanup_events[0]["payload"]["intended_terminal_status"] == "failed"
        assert [event["event_type"] for event in terminal_events] == [
            "group.run.failed"
        ]
        assert terminal_events[0]["payload"]["summary"] == stored_group["summary"]
        assert result["cleanup"] == {
            "attempted_run_ids": [run_id],
            "stopped_run_ids": [run_id],
            "unconfirmed_run_ids": [],
            "complete": True,
        }
    finally:
        service.close()


def test_partial_group_start_event_fault_rolls_back_group_and_is_visible(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    original_append = service.append_run_event
    failed_once = False

    def fail_first_group_failed_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        nonlocal failed_once
        if event_type == "group.run.failed" and not failed_once:
            failed_once = True
            raise RuntimeError("injected group terminal event failure")
        return original_append(run_id, event_type, payload, **fence)

    monkeypatch.setattr(service, "append_run_event", fail_first_group_failed_event)
    try:
        with pytest.raises(RuntimeError, match="group terminal event failure"):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        assert service.get_run(run_id)["status"] == "cancelled"
        assert service.get_run_group(runtime.run_group_id)["status"] == "running"
        assert _terminal_group_events(service, run_id) == []
        assert len(_group_cleanup_events(service, run_id)) == 1
    finally:
        service.close()


def test_partial_group_cleanup_intent_fault_prevents_child_cancellation(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    original_append = service.append_run_event

    def fail_cleanup_intent_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        if event_type == "group.cleanup.requested":
            raise RuntimeError("injected cleanup intent event failure")
        return original_append(run_id, event_type, payload, **fence)

    monkeypatch.setattr(service, "append_run_event", fail_cleanup_intent_event)
    try:
        with pytest.raises(RuntimeError, match="cleanup intent event failure"):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        assert service.get_run(run_id)["status"] == "running"
        assert service.get_run_group(runtime.run_group_id)["status"] == "running"
        assert _group_cleanup_events(service, run_id) == []
        assert _terminal_group_events(service, run_id) == []
    finally:
        service.close()


def test_partial_group_cleanup_intent_fence_mismatch_is_visible(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    original_append = service.append_run_event

    def lose_cleanup_intent_event_fence(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        if event_type == "group.cleanup.requested":
            return None
        return original_append(run_id, event_type, payload, **fence)

    monkeypatch.setattr(service, "append_run_event", lose_cleanup_intent_event_fence)
    try:
        with pytest.raises(
            AgentRuntimeError,
            match="group_run_partial_start_cleanup_event_fence_mismatch",
        ):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        assert service.get_run(run_id)["status"] == "running"
        assert service.get_run_group(runtime.run_group_id)["status"] == "running"
        assert _group_cleanup_events(service, run_id) == []
    finally:
        service.close()


def test_partial_group_start_cas_loser_never_returns_false_failed_payload(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    original_update = service.run_groups.update

    def lose_failed_cas(run_group_id: str, **fields: Any) -> dict[str, Any] | None:
        if fields.get("status") == "failed":
            return None
        return original_update(run_group_id, **fields)

    monkeypatch.setattr(service.run_groups, "update", lose_failed_cas)
    try:
        with pytest.raises(
            AgentRuntimeError,
            match="group_run_partial_start_terminal_cas_lost",
        ):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        assert service.get_run_group(runtime.run_group_id)["status"] == "running"
        assert _terminal_group_events(service, run_id) == []
    finally:
        service.close()


@pytest.mark.parametrize("failure_mode", ["completed_winner", "missing_group"])
def test_partial_group_start_terminal_conflict_or_missing_group_is_visible(
    tmp_path: Any,
    failure_mode: str,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(
        service,
        second_member_failure_mode=failure_mode,
    )
    try:
        expected_error = (
            AgentRuntimeError if failure_mode == "completed_winner" else KeyError
        )
        with pytest.raises(expected_error):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        event_types = [
            event["event_type"] for event in _terminal_group_events(service, run_id)
        ]
        assert service.get_run(run_id)["status"] == "running"
        assert "group.run.failed" not in event_types
        if failure_mode == "completed_winner":
            assert service.get_run_group(runtime.run_group_id)["status"] == "completed"
            assert event_types == ["group.run.completed"]
        else:
            with pytest.raises(KeyError):
                service.get_run_group(runtime.run_group_id)
    finally:
        service.close()


def test_partial_group_start_same_failed_winner_is_idempotent(tmp_path: Any) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    try:
        first = _start(runtime)
        second = _start(runtime)

        run_id = str(first["child_run_ids"][0])
        assert first["status"] == second["status"] == "failed"
        assert first["summary"] == second["summary"] == FAILED_START_SUMMARY
        assert [
            event["event_type"] for event in _terminal_group_events(service, run_id)
        ] == ["group.run.failed"]
        assert len(_group_cleanup_events(service, run_id)) == 1
    finally:
        service.close()


def test_partial_group_start_reports_unconfirmed_child_cancellation(
    tmp_path: Any,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service, cancel_fails=True)
    try:
        result = _start(runtime)

        run_id = str(result["child_run_ids"][0])
        assert service.get_run(run_id)["status"] == "running"
        assert service.get_run_group(runtime.run_group_id)["status"] == "running"
        assert result["status"] == "running"
        assert result["runs"][0]["status"] == "running"
        assert result["cleanup"] == {
            "attempted_run_ids": [run_id],
            "stopped_run_ids": [],
            "unconfirmed_run_ids": [run_id],
            "complete": False,
        }
        assert result["summary"] == CLEANUP_PENDING_SUMMARY
        assert _terminal_group_events(service, run_id) == []
        assert len(_group_cleanup_events(service, run_id)) == 1
    finally:
        service.close()


def test_partial_group_terminal_event_fault_converges_after_restart(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    original_append = service.append_run_event
    failed_once = False

    def fail_first_group_failed_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        nonlocal failed_once
        if event_type == "group.run.failed" and not failed_once:
            failed_once = True
            raise RuntimeError("injected group terminal event failure")
        return original_append(run_id, event_type, payload, **fence)

    monkeypatch.setattr(service, "append_run_event", fail_first_group_failed_event)
    recovered: AgentRuntimeService | None = None
    try:
        with pytest.raises(RuntimeError, match="group terminal event failure"):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        group_id = runtime.run_group_id
        assert service.get_run(run_id)["status"] == "cancelled"
        assert service.get_run_group(group_id)["status"] == "running"
        assert len(_group_cleanup_events(service, run_id)) == 1
        service.close()

        recovered = _service(tmp_path)
        observed_at = utc_now_iso()
        reconciliation = recovered.reconcile_startup_runs(
            observed_at,
            observed_at=observed_at,
        )

        assert group_id in reconciliation["reconciled_group_ids"]
        assert recovered.get_run_group(group_id)["status"] == "failed"
        assert [
            event["event_type"] for event in _terminal_group_events(recovered, run_id)
        ] == ["group.run.failed"]
    finally:
        if recovered is not None:
            recovered.close()
        else:
            service.close()


def test_ownerless_group_startup_event_fault_rolls_back_and_retries(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service)
    original_append = service.append_run_event
    failed_terminal_once = False

    def fail_initial_group_terminal_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        nonlocal failed_terminal_once
        if event_type == "group.run.failed" and not failed_terminal_once:
            failed_terminal_once = True
            raise RuntimeError("injected initial group terminal event failure")
        return original_append(run_id, event_type, payload, **fence)

    monkeypatch.setattr(service, "append_run_event", fail_initial_group_terminal_event)
    try:
        with pytest.raises(RuntimeError, match="initial group terminal event failure"):
            _start(runtime)

        run_id = next(iter(runtime.claimed_run_ids.values()))
        group_id = runtime.run_group_id
        reconciler = service.runtime_startup_reconciler
        original_recovery_append = reconciler._append_recovery_event_locked

        def fail_recovery_group_terminal_event(
            event_run_id: str,
            event_type: str,
            payload: dict[str, Any],
            **kwargs: Any,
        ) -> int:
            if event_type == "group.run.failed":
                raise RuntimeError("injected startup group event failure")
            return original_recovery_append(
                event_run_id,
                event_type,
                payload,
                **kwargs,
            )

        monkeypatch.setattr(
            reconciler,
            "_append_recovery_event_locked",
            fail_recovery_group_terminal_event,
        )
        observed_at = utc_now_iso()
        with pytest.raises(RuntimeError, match="startup group event failure"):
            service.reconcile_startup_runs(observed_at, observed_at=observed_at)

        assert service.get_run_group(group_id)["status"] == "running"
        assert _terminal_group_events(service, run_id) == []

        monkeypatch.setattr(
            reconciler,
            "_append_recovery_event_locked",
            original_recovery_append,
        )
        retried_at = utc_now_iso()
        reconciliation = service.reconcile_startup_runs(
            retried_at,
            observed_at=retried_at,
        )

        assert group_id in reconciliation["reconciled_group_ids"]
        assert service.get_run_group(group_id)["status"] == "failed"
        assert [
            event["event_type"] for event in _terminal_group_events(service, run_id)
        ] == ["group.run.failed"]
    finally:
        service.close()


def test_partial_group_running_child_cleanup_converges_in_watchdog(
    tmp_path: Any,
) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service, cancel_fails=True)
    try:
        result = _start(runtime)
        run_id = str(result["child_run_ids"][0])
        group_id = runtime.run_group_id
        service._conn.execute(
            """
            UPDATE runs
               SET async_lease_generation=7,
                   async_lease_owner_token='orphaned-group-worker',
                   async_lease_expires_at='2999-01-01T00:00:00+00:00',
                   async_lease_heartbeat_at='2999-01-01T00:00:00+00:00'
             WHERE run_id=?
            """,
            (run_id,),
        )
        service._conn.commit()

        reconciliation = service.reconcile_runtime_leases(utc_now_iso())

        stored_run = service.get_run(run_id)
        assert reconciliation["failed_run_ids"] == [run_id]
        assert group_id in reconciliation["reconciled_group_ids"]
        assert stored_run["status"] == "failed"
        lease_row = service._conn.execute(
            "SELECT async_lease_owner_token FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        assert str(lease_row["async_lease_owner_token"] or "") == ""
        assert service.get_run_group(group_id)["status"] == "failed"
        assert [
            event["event_type"] for event in _terminal_group_events(service, run_id)
        ] == ["group.run.failed"]
    finally:
        service.close()


def test_startup_cleanup_does_not_claim_run_newer_than_cutoff(tmp_path: Any) -> None:
    service = _service(tmp_path)
    runtime = _PartialStartRuntime(service, cancel_fails=True)
    try:
        result = _start(runtime)
        run_id = str(result["child_run_ids"][0])

        reconciliation = service.reconcile_startup_runs(
            "2000-01-01T00:00:00+00:00",
            observed_at=utc_now_iso(),
        )

        assert reconciliation["failed_run_ids"] == []
        assert service.get_run(run_id)["status"] == "running"
        assert service.get_run_group(runtime.run_group_id)["status"] == "running"
    finally:
        service.close()


def test_legacy_failed_ownerless_group_with_running_child_converges_on_restart(
    tmp_path: Any,
) -> None:
    service = _service(tmp_path)
    group = service._insert_run_group(
        title="Legacy partial-start group",
        source="agent",
    )
    run = service._insert_run(
        kind="agent_run",
        runnable_id="agent-legacy-partial",
        user_goal="Recover the legacy partial start",
        run_group_id=str(group["run_group_id"]),
        project_root_group=False,
    )
    service._update_run_group(
        str(group["run_group_id"]),
        status="failed",
        summary=FAILED_START_SUMMARY,
    )
    assert service.get_run(run["run_id"])["status"] == "running"
    assert _group_cleanup_events(service, run["run_id"]) == []
    # Simulate process loss: graceful shutdown would cancel the Run itself.
    service._conn.close()

    recovered = _service(tmp_path)
    try:
        observed_at = utc_now_iso()
        reconciliation = recovered.reconcile_startup_runs(
            observed_at,
            observed_at=observed_at,
        )

        assert reconciliation["failed_run_ids"] == [run["run_id"]]
        assert recovered.get_run(run["run_id"])["status"] == "failed"
        assert recovered.get_run_group(group["run_group_id"])["status"] == "failed"
        assert [
            event["event_type"]
            for event in _terminal_group_events(recovered, run["run_id"])
        ] == ["group.run.failed"]
    finally:
        recovered.close()
