"""Run and GroupRun compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from packages.security import contains_sensitive_text

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_requests import RuntimeRunRequestParser

RUNTIME_UNSET = object()


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
    ) -> None:
        self.run_groups.update(run_group_id, status=status, summary=summary)
        self._record_run_group_terminal_event(run_group_id, status=status)

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
        if not child_run_ids or self._run_group_event_recorded(
            child_run_ids,
            event_type=event_type,
            run_group_id=run_group_id,
        ):
            return
        self.append_run_event(
            child_run_ids[0],
            event_type,
            self._run_group_event_payload(group, run_group_id, status, child_run_ids),
        )

    def _run_group_event_recorded(
        self,
        run_ids: list[str],
        *,
        event_type: str,
        run_group_id: str,
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
                    and str(
                        payload.get("run_group_id")
                        or payload.get("group_run_id")
                        or ""
                    ) == run_group_id
                ):
                    return True
        return False

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
    ) -> dict[str, Any]:
        run = self.runs.insert(
            kind=kind,
            runnable_id=runnable_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            client_request_id=client_request_id,
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
        if self._run_group_event_recorded(
            child_run_ids,
            event_type="group.run.started",
            run_group_id=run_group_id,
        ):
            return
        self.append_run_event(
            child_run_ids[0],
            "group.run.started",
            self._run_group_event_payload(group, run_group_id, "running", child_run_ids),
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
    ) -> dict[str, Any]:
        return self.runs.update(
            run_id,
            status=status,
            result=result,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=pending_approval,
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
