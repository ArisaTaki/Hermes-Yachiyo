"""Legacy runtime run payload projection helpers."""

from __future__ import annotations

from typing import Any


class LegacyRunPayloadProjector:
    """Normalizes legacy runtime run payloads before public snapshot projection."""

    def chat_task_payload(
        self,
        run: dict[str, Any],
        *,
        conversation_id: str = "",
    ) -> dict[str, Any]:
        return {
            **run,
            "task_id": str(run.get("task_id") or run.get("run_id") or ""),
            "conversation_id": conversation_id or str(run.get("session_id") or ""),
            "title": str(run.get("user_goal") or run.get("runnable_name") or "Yachiyo task"),
            "summary": run.get("summary") or run.get("result") or "",
            "recent_events": run.get("timeline") or [],
            "open_in_studio_url": (
                f"#/agents?run_id={run.get('run_id')}" if run.get("run_id") else None
            ),
        }

    def group_artifacts(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            for artifact in run.get("artifacts") or []:
                if isinstance(artifact, dict):
                    artifacts.append({**artifact, "source_run_id": run_id})
        return artifacts

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

    def task_link_for_run(self, run: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            return None

        task_links = getattr(runtime, "task_run_links", None)
        for_run = getattr(task_links, "for_run", None)
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

    def group_run_from_legacy_run_group(
        self,
        run_group: dict[str, Any],
        runtime: Any,
    ) -> dict[str, Any]:
        child_runs = self.child_runs_for_run_group(run_group, runtime)
        run_group_id = str(run_group.get("run_group_id") or run_group.get("group_run_id") or "")
        return {
            "run_group_id": run_group_id,
            "group_run_id": run_group_id,
            "group_id": str(run_group.get("group_id") or ""),
            "title": run_group.get("title") or "Run group",
            "status": run_group.get("status") or "unknown",
            "objective": run_group.get("summary") or run_group.get("title") or "",
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

    def child_runs_for_run_group(
        self,
        run_group: dict[str, Any],
        runtime: Any,
    ) -> list[dict[str, Any]]:
        child_runs = []
        for run_id in run_group.get("child_run_ids") or []:
            try:
                child_runs.append(self.run_with_task_link(runtime.get_run(str(run_id)), runtime))
            except KeyError:
                continue
        return child_runs
