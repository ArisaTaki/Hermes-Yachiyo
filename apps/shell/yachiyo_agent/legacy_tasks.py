"""Legacy Chat-facing runtime port adapters."""

from __future__ import annotations

from typing import Any

from .legacy_runs import LegacyRunPayloadProjector

MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"


class LegacyRuntimePort:
    """RuntimePort adapter for existing NativeRunEngine-like services."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()

    def readiness(self) -> dict[str, Any]:
        try:
            payload = self._runtime.list_runnables()
        except Exception as exc:
            return {"ok": False, "status": "unavailable", "message": str(exc)}
        return {
            "ok": True,
            "status": "ready",
            "capabilities": {
                "tasks": True,
                "runnables": len(payload.get("runnables") or []),
            },
        }

    def list_runnable_catalog(self) -> dict[str, Any]:
        return {
            "agents": self._payload_items(self._runtime.list_agents(), "agents"),
            "workflows": self._payload_items(self._runtime.list_workflows(), "workflows"),
        }

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = str(request.get("prompt") or request.get("goal") or "").strip()
        runnable_id = str(
            request.get("agent_id") or request.get("runnable_id") or MAIN_CHAT_AGENT_ID
        )
        conversation_id = str(request.get("conversation_id") or "").strip()
        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        requested_task_id = str(
            request.get("task_id")
            or request.get("client_task_id")
            or metadata.get("task_id")
            or metadata.get("client_task_id")
            or ""
        ).strip()
        create_run = getattr(self._runtime, "create_run_for_runnable_async", None)
        if callable(create_run):
            run = create_run(
                runnable_id=runnable_id,
                user_goal=prompt,
            )
        else:
            run = self._runtime.create_run_for_runnable(
                runnable_id=runnable_id,
                user_goal=prompt,
            )
        run_id = str(run.get("run_id") or "").strip()
        task_id = requested_task_id or run_id
        if task_id and run_id:
            link_task_run = getattr(self._runtime, "link_task_run", None)
            if callable(link_task_run):
                link = link_task_run(task_id=task_id, run_id=run_id, session_id=conversation_id)
                try:
                    run = self._runtime.get_run(run_id)
                except KeyError:
                    pass
                run = self._run_with_task_link(task_id, run, link)
            else:
                run = {**run, "task_id": task_id, "session_id": conversation_id}
        return self._projector.chat_task_payload(run, conversation_id=conversation_id)

    def get_task_snapshot(self, task_id: str) -> dict[str, Any]:
        return self._projector.chat_task_payload(
            self._runtime.get_run(self._run_id_for_task(task_id))
        )

    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        payload = self._payload_with_task_link(task_id, self._runtime.get_run(run_id))
        if not payload.get("task_id"):
            payload = {**payload, "task_id": task_id}
        return payload

    def list_recent_tasks(self, conversation_id: str | None = None) -> list[dict[str, Any]]:
        payload = self._runtime.list_runs(30)
        runs = payload.get("runs") or []
        if conversation_id:
            runs = [run for run in runs if str(run.get("session_id") or "") == conversation_id]
        else:
            linked_runs = [
                run
                for run in runs
                if str(run.get("task_id") or "").strip() or str(run.get("session_id") or "").strip()
            ]
            if linked_runs:
                runs = linked_runs
        return [
            self._projector.chat_task_payload(
                run,
                conversation_id=conversation_id or "",
            )
            for run in runs
        ]

    def approve(self, approval_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = self._run_id_for_task(approval_id)
        return self._projector.chat_task_payload(
            self._payload_with_task_link(
                approval_id,
                self._runtime.approve_run_approval(run_id),
            )
        )

    def reject(self, approval_id: str, reason: str | None = None) -> dict[str, Any]:
        run_id = self._run_id_for_task(approval_id)
        return self._projector.chat_task_payload(
            self._payload_with_task_link(
                approval_id,
                self._runtime.reject_run_approval(run_id, reason or ""),
            )
        )

    def cancel(self, task_id: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        return self._projector.chat_task_payload(
            self._payload_with_task_link(task_id, self._runtime.cancel_run(run_id))
        )

    def _run_id_for_task(self, task_id: str) -> str:
        get_task_run_link = getattr(self._runtime, "get_task_run_link", None)
        if callable(get_task_run_link):
            try:
                link = get_task_run_link(task_id)
                run_id = str(link.get("run_id") or "").strip()
                if run_id:
                    return run_id
            except KeyError:
                pass
        return task_id

    def _payload_with_task_link(self, task_id: str, run: dict[str, Any]) -> dict[str, Any]:
        get_task_run_link = getattr(self._runtime, "get_task_run_link", None)
        if not callable(get_task_run_link):
            return run
        try:
            link = get_task_run_link(task_id)
        except KeyError:
            return run
        return self._run_with_task_link(task_id, run, link)

    def _run_with_task_link(
        self,
        task_id: str,
        run: dict[str, Any],
        link: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **run,
            "task_id": link.get("task_id") or task_id,
            "session_id": link.get("session_id") or run.get("session_id") or "",
            "task_run_link_created_at": link.get("created_at") or "",
            "task_run_link_updated_at": link.get("updated_at") or "",
            "task_run_link_run_status": link.get("run_status") or run.get("status") or "",
            "task_run_link_last_event_sequence": link.get("last_event_sequence") or 0,
        }

    def _payload_items(self, payload: Any, key: str) -> list[dict[str, Any]]:
        items = payload.get(key) if isinstance(payload, dict) else payload
        return [dict(item) for item in items or [] if isinstance(item, dict)]
