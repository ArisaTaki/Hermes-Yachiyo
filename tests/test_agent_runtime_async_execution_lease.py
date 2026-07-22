"""Cross-process recovery tests for asynchronous Agent Run execution leases."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _UtcClock:
    def __init__(self, value: datetime) -> None:
        self._value = value
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._value

    def advance(self, *, seconds: float) -> datetime:
        with self._lock:
            self._value += timedelta(seconds=seconds)
            return self._value


def _service(
    db_path: Path,
    workspace_dir: Path,
    credential_store: MemoryCredentialStore,
) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=db_path,
        workspace_dir=workspace_dir,
        credential_store=credential_store,
        seed_templates=False,
    )


def test_runtime_schema_migrates_existing_runs_with_async_lease_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy-runtime.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            run_group_id TEXT NOT NULL DEFAULT '',
            client_request_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            runnable_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_goal TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            timeline_json TEXT NOT NULL DEFAULT '[]',
            artifacts_json TEXT NOT NULL DEFAULT '[]',
            pending_approval_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    service = _service(db_path, tmp_path / "runtime", MemoryCredentialStore())
    try:
        columns = {
            str(row["name"])
            for row in service._conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        assert {
            "async_lease_generation",
            "async_lease_owner_token",
            "async_lease_expires_at",
            "async_lease_heartbeat_at",
        } <= columns
    finally:
        service.close()


def test_expired_async_agent_fails_closed_without_replaying_from_zero(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    credential_store = MemoryCredentialStore()
    services = [
        _service(db_path, workspace_dir, credential_store)
        for _ in range(3)
    ]
    clock = _UtcClock(datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc))
    dispatch_threads: list[threading.Thread] = []

    def dispatch_thread_factory(
        *,
        target: Any,
        name: str,
        daemon: bool,
    ) -> threading.Thread:
        thread = threading.Thread(target=target, name=name, daemon=daemon)
        dispatch_threads.append(thread)
        return thread

    try:
        agent = services[0].create_agent(
            {
                "name": "Lease Recovery Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        payload = {
            "agent_id": agent["agent_id"],
            "user_goal": "Recover exactly once",
            "client_run_id": "async-lease-client-1",
        }
        retry_payload = {
            "runnable_id": agent["agent_id"],
            "user_goal": "Recover exactly once",
            "client_run_id": "async-lease-client-1",
        }
        owner_tokens = ["owner-a", "owner-b", "owner-c"]

        for service, owner_token in zip(services, owner_tokens, strict=True):
            starter = service.agent_run_starter
            starter._now_utc = clock.now
            starter._async_lease_seconds = 60.0
            starter._owner_token_factory = lambda token=owner_token: token
            service.agent_run_async_coordinator._lock = threading.RLock()
            service.agent_run_async_coordinator._thread_factory = dispatch_thread_factory

        first_starter = services[0].agent_run_starter
        first_start = first_starter.start_async(
            payload,
            agent=services[0]._get_agent_private(agent["agent_id"]),
            lock=threading.RLock(),
        )
        run_id = first_start.run["run_id"]
        assert first_start.root_group is True
        assert first_start.lease_generation == 1
        assert first_start.lease_owner_token == "owner-a"
        assert not any(key.startswith("async_lease_") for key in first_start.run)
        assert dispatch_threads == []

        initial_lease = services[0]._conn.execute(
            """
            SELECT async_lease_generation, async_lease_owner_token,
                   async_lease_expires_at, async_lease_heartbeat_at
              FROM runs
             WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        assert initial_lease is not None
        assert initial_lease["async_lease_generation"] == 1
        assert initial_lease["async_lease_owner_token"] == "owner-a"
        assert initial_lease["async_lease_expires_at"].endswith("+00:00")
        assert initial_lease["async_lease_heartbeat_at"].endswith("+00:00")

        preserved_timeline = [
            {
                "event": "agent.tool.call",
                "detail": "communication.send",
                "result": {"ok": True},
            }
        ]
        preserved_artifacts = [
            {"artifact_id": "artifact-before-worker-loss", "kind": "report"}
        ]
        with services[0].runs.bind_async_execution_lease(
            run_id,
            generation=first_start.lease_generation,
            owner_token=first_start.lease_owner_token,
        ):
            services[0]._update_run(
                run_id,
                timeline=preserved_timeline,
                artifacts=preserved_artifacts,
            )

        clock.advance(seconds=30)
        unexpired = services[1].create_run_for_runnable_async(**retry_payload)
        assert unexpired["run_id"] == run_id
        assert unexpired["idempotent"] is True
        assert dispatch_threads == []

        clock.advance(seconds=31)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(service.create_run_for_runnable_async, **retry_payload)
                for service in services[1:]
            ]
            takeover_results = [future.result() for future in futures]

        assert {result["run_id"] for result in takeover_results} == {run_id}
        assert any(result["status"] == "failed" for result in takeover_results)
        assert all(result["status"] != "processing" for result in takeover_results)
        assert dispatch_threads == []

        active_lease = services[0]._conn.execute(
            """
            SELECT async_lease_generation, async_lease_owner_token
              FROM runs
             WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        assert active_lease is not None
        active_generation = int(active_lease["async_lease_generation"])
        active_owner = str(active_lease["async_lease_owner_token"])
        assert active_generation == 2
        assert active_owner == ""

        assert not services[0].runs.owns_async_execution_lease(
            run_id,
            generation=1,
            owner_token="owner-a",
        )
        assert not services[0].runs.renew_async_execution_lease(
            run_id,
            generation=1,
            owner_token="owner-a",
            heartbeat_at=clock.now().isoformat(),
            lease_expires_at=(clock.now() + timedelta(seconds=60)).isoformat(),
        )
        assert not services[0].runs.release_async_execution_lease(
            run_id,
            generation=1,
            owner_token="owner-a",
        )
        with services[0].runs.bind_async_execution_lease(
            run_id,
            generation=1,
            owner_token="owner-a",
        ):
            with pytest.raises(AgentRuntimeError, match="execution lease"):
                services[0].runs.update(run_id, status="failed", result="stale owner")

        final_run = services[0].get_run(run_id)
        assert final_run["status"] == "failed"
        assert "async_execution_resume_checkpoint_required" in final_run["result"]
        assert final_run["timeline"][:-1] == preserved_timeline
        assert final_run["timeline"][-1]["event"] == "agent.run.failed"
        assert final_run["artifacts"] == preserved_artifacts

        terminal_retry = services[0].create_run_for_runnable_async(**retry_payload)
        assert terminal_retry["run_id"] == run_id
        assert terminal_retry["status"] == "failed"
        assert terminal_retry["idempotent"] is True
        assert dispatch_threads == []
        final_lease = services[0]._conn.execute(
            """
            SELECT async_lease_generation, async_lease_owner_token,
                   async_lease_expires_at, async_lease_heartbeat_at
              FROM runs
             WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        assert final_lease is not None
        assert final_lease["async_lease_generation"] == 2
        assert final_lease["async_lease_owner_token"] == ""
        assert final_lease["async_lease_expires_at"] == ""
        assert final_lease["async_lease_heartbeat_at"] == ""
        assert services[0]._conn.execute(
            "SELECT COUNT(*) AS count FROM runs WHERE client_request_id=?",
            ("async-lease-client-1",),
        ).fetchone()["count"] == 1
        assert services[0]._conn.execute(
            "SELECT COUNT(*) AS count FROM run_groups",
        ).fetchone()["count"] == 1
    finally:
        for thread in dispatch_threads:
            thread.join(timeout=3)
        for service in reversed(services):
            service.close()


def test_async_agent_thread_start_failure_releases_execution_lease(tmp_path) -> None:
    service = _service(
        tmp_path / "agent-runtime.db",
        tmp_path / "runtime",
        MemoryCredentialStore(),
    )

    class _FailingThread:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("dispatch unavailable")

    try:
        agent = service.create_agent(
            {
                "name": "Lease Start Failure Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        service.agent_run_async_coordinator._thread_factory = _FailingThread

        with pytest.raises(AgentRuntimeError, match="dispatch unavailable"):
            service.create_run_for_runnable_async(
                runnable_id=agent["agent_id"],
                user_goal="Fail before dispatch",
                client_run_id="async-lease-thread-failure-1",
            )

        row = service._conn.execute(
            """
            SELECT status, async_lease_generation, async_lease_owner_token,
                   async_lease_expires_at, async_lease_heartbeat_at
              FROM runs
             WHERE client_request_id=?
            """,
            ("async-lease-thread-failure-1",),
        ).fetchone()
        assert row is not None
        assert row["status"] == "failed"
        assert row["async_lease_generation"] == 1
        assert row["async_lease_owner_token"] == ""
        assert row["async_lease_expires_at"] == ""
        assert row["async_lease_heartbeat_at"] == ""
    finally:
        service.close()


def test_external_cancel_is_terminal_against_late_async_owner_completion(
    tmp_path,
) -> None:
    service = _service(
        tmp_path / "agent-runtime.db",
        tmp_path / "runtime",
        MemoryCredentialStore(),
    )
    execution_started = threading.Event()
    release_execution = threading.Event()
    dispatch_threads: list[threading.Thread] = []

    def dispatch_thread_factory(
        *,
        target: Any,
        name: str,
        daemon: bool,
    ) -> threading.Thread:
        thread = threading.Thread(target=target, name=name, daemon=daemon)
        dispatch_threads.append(thread)
        return thread

    try:
        agent = service.create_agent(
            {
                "name": "Lease Cancel Fence Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        service.agent_run_async_coordinator._thread_factory = dispatch_thread_factory

        def execute_agent_run(run_id: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            execution_started.set()
            if not release_execution.wait(timeout=5):
                raise TimeoutError("test execution release timed out")
            return service._update_run(
                run_id,
                status="completed",
                result="late completion",
                pending_approval=None,
            )

        service.agent_run_async_coordinator._execute_agent_run = execute_agent_run
        started = service.create_run_for_runnable_async(
            runnable_id=agent["agent_id"],
            user_goal="Cancel before completion",
            client_run_id="async-lease-cancel-1",
        )
        assert execution_started.wait(timeout=2)

        cancelled = service.cancel_run(started["run_id"])
        assert cancelled["status"] == "cancelled"
        release_execution.set()
        for thread in dispatch_threads:
            thread.join(timeout=3)
            assert not thread.is_alive()

        final_run = service.get_run(started["run_id"])
        assert final_run["status"] == "cancelled"
        assert final_run["result"] != "late completion"
        lease_row = service._conn.execute(
            """
            SELECT async_lease_owner_token, async_lease_expires_at,
                   async_lease_heartbeat_at
              FROM runs
             WHERE run_id=?
            """,
            (started["run_id"],),
        ).fetchone()
        assert lease_row is not None
        assert lease_row["async_lease_owner_token"] == ""
        assert lease_row["async_lease_expires_at"] == ""
        assert lease_row["async_lease_heartbeat_at"] == ""
    finally:
        release_execution.set()
        for thread in dispatch_threads:
            thread.join(timeout=3)
        service.close()


def test_stale_async_owner_cannot_publish_terminal_events_after_takeover(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    credential_store = MemoryCredentialStore()
    first_service = _service(db_path, workspace_dir, credential_store)
    second_service = _service(db_path, workspace_dir, credential_store)
    initial_now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)

    try:
        agent = first_service.create_agent(
            {
                "name": "Lease Terminal Event Fence Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        payload = {
            "agent_id": agent["agent_id"],
            "user_goal": "Publish one terminal outcome",
            "client_run_id": "async-lease-terminal-event-1",
        }
        first_service.agent_run_starter._now_utc = lambda: initial_now
        first_service.agent_run_starter._owner_token_factory = lambda: "owner-a"
        first = first_service.agent_run_starter.start_async(
            payload,
            agent=first_service._get_agent_private(agent["agent_id"]),
        )
        second_service.agent_run_starter._now_utc = lambda: initial_now + timedelta(
            seconds=61
        )
        second_service.agent_run_starter._owner_token_factory = lambda: "owner-b"
        second = second_service.agent_run_starter.start_async(
            payload,
            agent=second_service._get_agent_private(agent["agent_id"]),
        )
        assert second.takeover is True

        with first_service.runs.bind_async_execution_lease(
            first.run["run_id"],
            generation=first.lease_generation,
            owner_token=first.lease_owner_token,
        ):
            with pytest.raises(AgentRuntimeError, match="execution lease"):
                first_service.agent_run_outcomes.completed(
                    first.run["run_id"],
                    "stale completion",
                    timeline=[],
                    artifacts=[],
                )

        event_types = [
            event["event_type"]
            for event in second_service.list_run_events(
                first.run["run_id"],
                limit=100,
            )["events"]
        ]
        assert "model.output.completed" not in event_types
        assert "agent.run.completed" not in event_types
        assert "run.completed" not in event_types
        assert second_service.get_run(first.run["run_id"])["status"] == "running"
    finally:
        second_service.close()
        first_service.close()


def test_stale_async_owner_cannot_append_run_event_after_takeover(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    credential_store = MemoryCredentialStore()
    first_service = _service(db_path, workspace_dir, credential_store)
    second_service = _service(db_path, workspace_dir, credential_store)
    initial_now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)

    try:
        agent = first_service.create_agent(
            {
                "name": "Lease Run Event Fence Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        payload = {
            "agent_id": agent["agent_id"],
            "user_goal": "Fence every stale durable event",
            "client_run_id": "async-lease-run-event-fence-1",
        }
        first_service.agent_run_starter._now_utc = lambda: initial_now
        first_service.agent_run_starter._owner_token_factory = lambda: "owner-old"
        first = first_service.agent_run_starter.start_async(
            payload,
            agent=first_service._get_agent_private(agent["agent_id"]),
        )
        second_service.agent_run_starter._now_utc = lambda: initial_now + timedelta(
            seconds=61
        )
        second_service.agent_run_starter._owner_token_factory = lambda: "owner-new"
        second = second_service.agent_run_starter.start_async(
            payload,
            agent=second_service._get_agent_private(agent["agent_id"]),
        )
        assert second.takeover is True
        assert second.lease_generation == first.lease_generation + 1

        callback_transaction_states: list[bool] = []
        assert_write_active = first_service.run_events._assert_write_active
        assert callable(assert_write_active)

        def observe_write_fence(run_id: str) -> None:
            callback_transaction_states.append(first_service._conn.in_transaction)
            assert_write_active(run_id)

        first_service.run_events._assert_write_active = observe_write_fence
        with first_service.runs.bind_async_execution_lease(
            first.run["run_id"],
            generation=first.lease_generation,
            owner_token=first.lease_owner_token,
        ):
            with pytest.raises(AgentRuntimeError, match="execution lease"):
                first_service.runs.update(
                    first.run["run_id"],
                    result="stale update",
                )
            with pytest.raises(AgentRuntimeError, match="execution lease"):
                first_service.append_run_event(
                    first.run["run_id"],
                    "agent.stale.event",
                    {"owner": "owner-old"},
                )

        assert callback_transaction_states == [True]
        stale_event_count = second_service._conn.execute(
            """
            SELECT COUNT(*) AS event_count
              FROM run_events
             WHERE run_id=? AND event_type='agent.stale.event'
            """,
            (first.run["run_id"],),
        ).fetchone()
        assert stale_event_count is not None
        assert stale_event_count["event_count"] == 0

        with second_service.runs.bind_async_execution_lease(
            second.run["run_id"],
            generation=second.lease_generation,
            owner_token=second.lease_owner_token,
        ):
            current_event = second_service.append_run_event(
                second.run["run_id"],
                "agent.current.event",
                {"owner": "owner-new"},
            )
        request_event = second_service.append_run_event(
            second.run["run_id"],
            "agent.request.event",
            {"source": "request-thread"},
        )
        assert current_event["event_type"] == "agent.current.event"
        assert request_event["event_type"] == "agent.request.event"
    finally:
        second_service.close()
        first_service.close()


def test_heartbeat_loss_stops_after_inflight_tool_and_fences_followup_tool(
    tmp_path,
) -> None:
    service = _service(
        tmp_path / "agent-runtime.db",
        tmp_path / "runtime",
        MemoryCredentialStore(),
    )
    first_tool_started = threading.Event()
    allow_first_tool_return = threading.Event()
    heartbeat_lost = threading.Event()
    dispatch_threads: list[threading.Thread] = []
    effects: list[str] = []

    def dispatch_thread_factory(
        *,
        target: Any,
        name: str,
        daemon: bool,
    ) -> threading.Thread:
        thread = threading.Thread(target=target, name=name, daemon=daemon)
        dispatch_threads.append(thread)
        return thread

    class _Broker:
        tool_policy = {"approval_required": {}}

        def call(
            self,
            tool_name: str,
            _payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            del approved
            effects.append(tool_name)
            if len(effects) == 1:
                first_tool_started.set()
                if not allow_first_tool_return.wait(timeout=5):
                    raise TimeoutError("test tool return timed out")
            return {"ok": True, "content": tool_name}

    try:
        agent = service.create_agent(
            {
                "name": "Lease Tool Fence Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        service.agent_run_async_coordinator._thread_factory = dispatch_thread_factory
        service.agent_run_async_coordinator._heartbeat_interval_seconds = 0.01
        original_heartbeat = service.agent_run_starter.heartbeat_async_lease
        heartbeat_calls = [0]

        def lose_heartbeat_after_dispatch(
            run_id: str,
            generation: int,
            owner_token: str,
        ) -> bool:
            heartbeat_calls[0] += 1
            if heartbeat_calls[0] == 1:
                return original_heartbeat(run_id, generation, owner_token)
            service._conn.execute(
                """
                UPDATE runs
                   SET async_lease_generation=?, async_lease_owner_token=?
                 WHERE run_id=?
                   AND async_lease_generation=?
                   AND async_lease_owner_token=?
                """,
                (generation + 1, "replacement-owner", run_id, generation, owner_token),
            )
            heartbeat_lost.set()
            return False

        service.agent_run_starter.heartbeat_async_lease = lose_heartbeat_after_dispatch
        broker = _Broker()

        def execute_agent_run(run_id: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            timeline: list[dict[str, Any]] = []
            for path in ("first.txt", "second.txt"):
                service.tool_call_executor.execute(
                    {"tool": "workspace.read", "input": {"path": path}},
                    ["workspace.read"],
                    broker,
                    timeline,
                    run_id=run_id,
                )
            return service._update_run(
                run_id,
                status="completed",
                result="both tools completed",
                pending_approval=None,
            )

        service.agent_run_async_coordinator._execute_agent_run = execute_agent_run
        started = service.create_run_for_runnable_async(
            runnable_id=agent["agent_id"],
            user_goal="Run two tools once",
            client_run_id="async-lease-tool-fence-1",
        )
        assert first_tool_started.wait(timeout=2)
        assert heartbeat_lost.wait(timeout=2)
        allow_first_tool_return.set()
        for thread in dispatch_threads:
            thread.join(timeout=3)
            assert not thread.is_alive()

        assert effects == ["workspace.read"]
        assert service.get_run(started["run_id"])["status"] == "running"
        event_types = [
            event["event_type"]
            for event in service.list_run_events(started["run_id"], limit=100)["events"]
        ]
        assert "agent.tool.call" not in event_types
        assert "agent.run.failed" not in event_types
    finally:
        allow_first_tool_return.set()
        for thread in dispatch_threads:
            thread.join(timeout=3)
        service.close()


def test_initial_heartbeat_exception_fails_closed_without_execution_or_failure_event(
    tmp_path,
) -> None:
    service = _service(
        tmp_path / "agent-runtime.db",
        tmp_path / "runtime",
        MemoryCredentialStore(),
    )
    dispatch_threads: list[threading.Thread] = []
    executions: list[str] = []

    def dispatch_thread_factory(
        *,
        target: Any,
        name: str,
        daemon: bool,
    ) -> threading.Thread:
        thread = threading.Thread(target=target, name=name, daemon=daemon)
        dispatch_threads.append(thread)
        return thread

    try:
        agent = service.create_agent(
            {
                "name": "Lease Initial Heartbeat Failure Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        service.agent_run_async_coordinator._thread_factory = dispatch_thread_factory
        service.agent_run_starter.heartbeat_async_lease = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("heartbeat database unavailable")
            )
        )
        service.agent_run_async_coordinator._execute_agent_run = (
            lambda run_id, *_args, **_kwargs: executions.append(run_id) or {}
        )

        started = service.create_run_for_runnable_async(
            runnable_id=agent["agent_id"],
            user_goal="Do not execute without a heartbeat",
            client_run_id="async-lease-initial-heartbeat-failure-1",
        )
        for thread in dispatch_threads:
            thread.join(timeout=3)
            assert not thread.is_alive()

        assert executions == []
        assert service.get_run(started["run_id"])["status"] == "running"
        event_types = [
            event["event_type"]
            for event in service.list_run_events(started["run_id"], limit=100)["events"]
        ]
        assert "agent.run.failed" not in event_types
        assert "run.failed" not in event_types
    finally:
        for thread in dispatch_threads:
            thread.join(timeout=3)
        service.close()
