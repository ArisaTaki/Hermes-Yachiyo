"""Run and GroupRun compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from packages.security import contains_sensitive_text

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.run_requests import RuntimeRunRequestParser

RUNTIME_UNSET = object()


def _normalize_group_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return "cancelled" if status == "canceled" else status


def _is_terminal_group_status(value: Any) -> bool:
    return _normalize_group_status(value) in {
        "completed",
        "failed",
        "cancelled",
    }


def _run_group_projection_matches(
    group: dict[str, Any],
    *,
    status: str,
    summary: str,
) -> bool:
    return (
        _normalize_group_status(group.get("status"))
        == _normalize_group_status(status)
        and str(group.get("summary") or "") == str(summary or "")
    )


class RuntimeRunFacadeMixin:
    """Keeps legacy Run helper methods while delegating to split repositories."""

    def _insert_run_group(
        self,
        *,
        title: str,
        source: str,
        workspace_dir: str = "",
    ) -> dict[str, Any]:
        return self.run_groups.insert(title=title, source=source, workspace_dir=workspace_dir)

    def _append_run_to_group(self, run_group_id: str, run_id: str) -> None:
        self.run_groups.append_run(run_group_id, run_id)

    @staticmethod
    def _client_request_id_from_payload(payload: dict[str, Any]) -> str:
        return RuntimeRunRequestParser(
            contains_sensitive_text=contains_sensitive_text,
            error_type=AgentRuntimeError,
        ).client_request_id_from_payload(payload)

    def _run_by_client_request_id(self, client_request_id: str) -> dict[str, Any] | None:
        return self.runs.by_client_request_id(client_request_id)

    def _update_run_group(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        expected_status: str | None = None,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        transaction = getattr(getattr(self, "_conn", None), "transaction", None)
        scope = transaction() if callable(transaction) else nullcontext()
        with scope:
            current = self.get_run_group(run_group_id)
            target_status = str(status or current.get("status") or "")
            target_summary = (
                redact_secrets(summary)
                if summary is not None
                else str(current.get("summary") or "")
            )
            if _is_terminal_group_status(current.get("status")):
                if _run_group_projection_matches(
                    current,
                    status=target_status,
                    summary=target_summary,
                ):
                    self._record_run_group_terminal_event(
                        run_group_id,
                        status=target_status,
                    )
                    return current
                raise AgentRuntimeError("run_group_terminal_outcome_conflict")
            effective_expected_status = (
                expected_status
                if expected_status is not None
                else str(current.get("status") or "")
            )
            effective_expected_updated_at = (
                expected_updated_at
                if expected_updated_at is not None
                else str(current.get("updated_at") or "")
            )
            result = self.run_groups.update(
                run_group_id,
                status=status,
                summary=summary,
                expected_status=effective_expected_status,
                expected_updated_at=effective_expected_updated_at,
            )
            if result is None:
                winner = self.get_run_group(run_group_id)
                if _run_group_projection_matches(
                    winner,
                    status=target_status,
                    summary=target_summary,
                ):
                    self._record_run_group_terminal_event(
                        run_group_id,
                        status=target_status,
                    )
                    return winner
                if _is_terminal_group_status(winner.get("status")):
                    raise AgentRuntimeError("run_group_terminal_outcome_conflict")
                return None
            self._record_run_group_terminal_event(run_group_id, status=status)
        return result

    def _record_run_group_terminal_event(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
    ) -> None:
        event_type = self._run_group_terminal_event_type(status)
        if not event_type:
            return
        try:
            group = self.get_run_group(run_group_id)
        except KeyError:
            return
        child_run_ids = [
            str(item)
            for item in group.get("child_run_ids") or []
            if str(item)
        ]
        if not child_run_ids:
            return
        event_payload = self._run_group_event_payload(
            group,
            run_group_id,
            status,
            child_run_ids,
        )
        if self._run_group_event_recorded(
            child_run_ids,
            event_type=event_type,
            run_group_id=run_group_id,
            expected_payload=event_payload,
        ):
            return
        event = self.append_run_event(
            child_run_ids[0],
            event_type,
            event_payload,
        )
        if event is None:
            raise AgentRuntimeError("run_group_event_fence_mismatch")

    def _run_group_event_recorded(
        self,
        run_ids: list[str],
        *,
        event_type: str,
        run_group_id: str,
        expected_payload: dict[str, Any] | None = None,
    ) -> bool:
        for run_id in run_ids:
            try:
                events = self.list_run_events(
                    run_id,
                    include_internal=True,
                    limit=1000,
                )["events"]
            except KeyError:
                continue
            for event in events:
                payload = event.get("payload") if isinstance(event, dict) else {}
                if (
                    event.get("event_type") == event_type
                    and isinstance(payload, dict)
                    and self._run_group_event_payload_matches(
                        payload,
                        run_group_id=run_group_id,
                        expected_payload=expected_payload,
                    )
                ):
                    return True
        return False

    @staticmethod
    def _run_group_event_payload_matches(
        payload: dict[str, Any],
        *,
        run_group_id: str,
        expected_payload: dict[str, Any] | None,
    ) -> bool:
        if expected_payload is None:
            return str(
                payload.get("run_group_id")
                or payload.get("group_run_id")
                or ""
            ) == run_group_id
        if str(payload.get("run_group_id") or "") != run_group_id or str(
            payload.get("group_run_id") or ""
        ) != run_group_id:
            return False
        expected_child_run_ids = [
            str(item)
            for item in expected_payload.get("child_run_ids") or []
            if str(item)
        ]
        raw_child_run_ids = payload.get("child_run_ids")
        if not isinstance(raw_child_run_ids, list):
            return False
        child_run_ids = [str(item) for item in raw_child_run_ids]
        participant_count = payload.get("participant_count")
        return (
            _normalize_group_status(payload.get("status"))
            == _normalize_group_status(expected_payload.get("status"))
            and str(payload.get("summary") or "")
            == str(expected_payload.get("summary") or "")
            and child_run_ids == expected_child_run_ids
            and isinstance(participant_count, int)
            and not isinstance(participant_count, bool)
            and participant_count == len(expected_child_run_ids)
        )

    @staticmethod
    def _run_group_terminal_event_type(status: str | None) -> str:
        clean_status = str(status or "").strip()
        if clean_status == "completed":
            return "group.run.completed"
        if clean_status == "failed":
            return "group.run.failed"
        if clean_status == "cancelled":
            return "group.run.cancelled"
        return ""

    def _insert_run(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
        project_root_group: bool = False,
        async_lease_generation: int = 0,
        async_lease_owner_token: str = "",
        async_lease_expires_at: str = "",
        async_lease_heartbeat_at: str = "",
    ) -> dict[str, Any]:
        run = self.runs.insert(
            kind=kind,
            runnable_id=runnable_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            client_request_id=client_request_id,
            project_root_group=project_root_group,
            async_lease_generation=async_lease_generation,
            async_lease_owner_token=async_lease_owner_token,
            async_lease_expires_at=async_lease_expires_at,
            async_lease_heartbeat_at=async_lease_heartbeat_at,
        )
        self._record_run_group_started_event(run_group_id, run_id=run["run_id"])
        return run

    def _record_run_group_started_event(self, run_group_id: str, *, run_id: str) -> None:
        if not run_group_id or not run_id:
            return
        try:
            group = self.get_run_group(run_group_id)
        except KeyError:
            return
        if str(group.get("source") or "") != "workflow":
            return
        child_run_ids = [
            str(item)
            for item in group.get("child_run_ids") or []
            if str(item)
        ] or [run_id]
        event_payload = self._run_group_event_payload(
            group,
            run_group_id,
            "running",
            child_run_ids,
        )
        if self._run_group_event_recorded(
            child_run_ids,
            event_type="group.run.started",
            run_group_id=run_group_id,
        ):
            return
        self.append_run_event(
            child_run_ids[0],
            "group.run.started",
            event_payload,
        )

    def _update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: str | None = None,
        timeline: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        pending_approval: dict[str, Any] | None | object = RUNTIME_UNSET,
        expected_status: str | None = None,
        expected_approval_id: str = "",
        expected_updated_at: str | None = None,
        expected_pending_approval_absent: bool = False,
    ) -> dict[str, Any] | None:
        return self.runs.update(
            run_id,
            status=status,
            result=result,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=pending_approval,
            expected_status=expected_status,
            expected_approval_id=expected_approval_id,
            expected_updated_at=expected_updated_at,
            expected_pending_approval_absent=expected_pending_approval_absent,
        )

    def _terminal_run_or_none(self, run_id: str) -> dict[str, Any] | None:
        return self.terminal_run_resolver.terminal_run_or_none(run_id)

    @staticmethod
    def _run_group_event_payload(
        group: dict[str, Any],
        run_group_id: str,
        status: str | None,
        child_run_ids: list[str],
    ) -> dict[str, Any]:
        return {
            "child_run_ids": child_run_ids,
            "group_run_id": run_group_id,
            "objective": str(group.get("summary") or group.get("title") or ""),
            "participant_count": len(child_run_ids),
            "run_group_id": run_group_id,
            "source": str(group.get("source") or ""),
            "status": str(group.get("status") or status or ""),
            "summary": str(group.get("summary") or ""),
            "title": str(group.get("title") or ""),
        }
