"""Runtime-owned projection helpers for native GroupRun results."""

from __future__ import annotations

from typing import Any, Protocol


class GroupRunProjector(Protocol):
    def child_run_payload(self, run: dict[str, Any], runtime: Any) -> dict[str, Any]: ...

    def group_artifacts(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def group_events_from_child_runs(
        self,
        runs: list[dict[str, Any]],
        runtime: Any,
    ) -> list[dict[str, Any]]: ...


class RuntimeGroupRunProjector:
    """Adds runtime events and task links without public-UI fields."""

    def child_run_payload(self, run: dict[str, Any], runtime: Any) -> dict[str, Any]:
        linked = self.run_with_task_link(run, runtime)
        events = self.all_events_for_run(linked, runtime)
        if not events:
            return linked
        return {**linked, "events": events, "recent_events": events}

    def group_artifacts(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            for artifact in run.get("artifacts") or []:
                if isinstance(artifact, dict):
                    artifacts.append({**artifact, "source_run_id": run_id})
        return artifacts

    def group_events_from_child_runs(
        self,
        runs: list[dict[str, Any]],
        runtime: Any,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for run in runs:
            run_id = str(run.get("run_id") or "").strip()
            for event in self.events_for_run(run, runtime):
                event_type = _event_type(event)
                if not event_type.startswith("group."):
                    continue
                item = dict(event)
                if not item.get("event_type") and item.get("event"):
                    item["event_type"] = event_type
                if run_id and not item.get("run_id"):
                    item["run_id"] = run_id
                events.append(item)
        return events

    def run_with_task_link(self, run: dict[str, Any], runtime: Any) -> dict[str, Any]:
        link = self.task_link_for_run(run, runtime)
        if not link:
            return run
        return {
            **run,
            "task_id": link.get("task_id") or run.get("task_id") or "",
            "session_id": link.get("session_id") or run.get("session_id") or "",
            "task_run_link_created_at": link.get("created_at") or "",
            "task_run_link_updated_at": link.get("updated_at") or "",
            "task_run_link_run_status": link.get("run_status") or run.get("status") or "",
            "task_run_link_last_event_sequence": link.get("last_event_sequence") or 0,
        }

    @staticmethod
    def task_link_for_run(run: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            return None
        for_run = getattr(getattr(runtime, "task_run_links", None), "for_run", None)
        if callable(for_run):
            link = for_run(run_id)
            if isinstance(link, dict):
                return link
        task_id = str(run.get("task_id") or "").strip()
        get_task_run_link = getattr(runtime, "get_task_run_link", None)
        if task_id and callable(get_task_run_link):
            try:
                link = get_task_run_link(task_id)
            except KeyError:
                return None
            if isinstance(link, dict):
                return link
        return None

    @staticmethod
    def all_events_for_run(run: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
        events = _event_list_from_payload(
            run,
            ("events", "run_events", "recent_events", "timeline"),
        )
        run_id = str(run.get("run_id") or "").strip()
        list_run_events = getattr(runtime, "list_run_events", None)
        if run_id and callable(list_run_events):
            try:
                payload = list_run_events(run_id)
            except Exception:
                payload = {}
            events.extend(_event_list_from_payload(payload, ("events",)))
        return _dedupe_events(events)

    @staticmethod
    def events_for_run(run: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
        existing = _event_list_from_payload(
            run,
            ("events", "run_events", "recent_events", "timeline"),
        )
        explicit_group_events = [
            event
            for event in existing
            if _event_type(event).startswith("group.") and event.get("event_type")
        ]
        if explicit_group_events:
            return explicit_group_events
        existing_group_events = [
            event for event in existing if _event_type(event).startswith("group.")
        ]
        if existing_group_events:
            return existing_group_events
        run_id = str(run.get("run_id") or "").strip()
        list_run_events = getattr(runtime, "list_run_events", None)
        if run_id and callable(list_run_events):
            try:
                payload = list_run_events(run_id)
            except Exception:
                payload = {}
            events = _event_list_from_payload(payload, ("events",))
            if events:
                return events
        return existing

    def child_runs_for_run_group(
        self,
        run_group: dict[str, Any],
        runtime: Any,
    ) -> list[dict[str, Any]]:
        child_runs = []
        for run_id in run_group.get("child_run_ids") or []:
            try:
                child_runs.append(
                    self.child_run_payload(runtime.get_run(str(run_id)), runtime)
                )
            except KeyError:
                continue
        return child_runs


def _event_list_from_payload(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value and isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("event") or "").strip()


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        key = (
            _event_type(event),
            str(event.get("sequence") or "").strip(),
            str(
                event.get("detail")
                or payload.get("detail")
                or payload.get("tool")
                or ""
            ).strip(),
            str(event.get("step_id") or payload.get("step_id") or "").strip(),
            str(event.get("request_id") or payload.get("request_id") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(event))
    return result
