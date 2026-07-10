"""Legacy runtime run payload projection helpers."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.group_projection import RuntimeGroupRunProjector

from .links import studio_run_url


class LegacyRunPayloadProjector(RuntimeGroupRunProjector):
    """Normalizes legacy runtime run payloads before public snapshot projection."""

    def chat_task_payload(
        self,
        run: dict[str, Any],
        *,
        conversation_id: str = "",
        runtime: Any | None = None,
    ) -> dict[str, Any]:
        return {
            **run,
            "task_id": str(run.get("task_id") or run.get("run_id") or ""),
            "conversation_id": conversation_id or str(run.get("session_id") or ""),
            "title": str(run.get("user_goal") or run.get("runnable_name") or "Yachiyo task"),
            "summary": run.get("summary") or run.get("result") or "",
            "recent_events": self.chat_events_for_run(run, runtime),
            "open_in_studio_url": studio_run_url(
                str(run.get("run_id") or ""),
                group_run_id=str(run.get("group_run_id") or run.get("run_group_id") or ""),
            ),
        }

    def chat_events_for_run(
        self,
        run: dict[str, Any],
        runtime: Any | None = None,
    ) -> list[dict[str, Any]]:
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

    def run_with_runtime_events(
        self,
        run: dict[str, Any],
        runtime: Any | None = None,
    ) -> dict[str, Any]:
        events = self.chat_events_for_run(run, runtime)
        if not events:
            return run
        return {
            **run,
            "events": events,
            "recent_events": events,
        }

    def group_run_from_legacy_run_group(
        self,
        run_group: dict[str, Any],
        runtime: Any,
    ) -> dict[str, Any]:
        child_runs = self.child_runs_for_run_group(run_group, runtime)
        run_group_id = str(run_group.get("run_group_id") or run_group.get("group_run_id") or "")
        events = [
            *self.run_group_events(run_group),
            *self.group_events_from_child_runs(child_runs, runtime),
        ]
        event_group_id = _first_event_payload_text(events, "group_id")
        event_objective = _first_event_payload_text(events, "objective")
        return {
            "run_group_id": run_group_id,
            "group_run_id": run_group_id,
            "group_id": str(run_group.get("group_id") or event_group_id or ""),
            "source": str(run_group.get("source") or ""),
            "title": run_group.get("title") or "Run group",
            "status": run_group.get("status") or "unknown",
            "objective": event_objective or run_group.get("summary") or run_group.get("title") or "",
            "events": events,
            "runs": child_runs,
            "child_run_ids": run_group.get("child_run_ids") or [],
            "shared_artifacts": self.group_artifacts(child_runs),
            "pending_approvals": [
                run.get("pending_approval")
                for run in child_runs
                if run.get("pending_approval")
            ],
            "final_answer": run_group.get("summary") or "",
            "created_at": run_group.get("created_at") or "",
            "updated_at": run_group.get("updated_at") or "",
        }

    def run_group_events(self, run_group: dict[str, Any]) -> list[dict[str, Any]]:
        return _event_list_from_payload(run_group, ("events", "run_events", "timeline"))

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


def _first_event_payload_text(events: list[dict[str, Any]], key: str) -> str:
    for event in events:
        payload = event.get("payload") if isinstance(event, dict) else {}
        if not isinstance(payload, dict):
            continue
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""
