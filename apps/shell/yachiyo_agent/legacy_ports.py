"""Ports backed by the existing Agent runtime surface."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.chat_api import ChatAPI

from .legacy_groups import (
    append_group_run_event,
    append_group_member_event,
    chat_group_snapshot,
    chat_group_snapshots,
    create_runnable_run,
    group_definition_from_run_group,
    save_chat_group_snapshot,
)
from .legacy_runs import LegacyRunPayloadProjector
from .legacy_tasks import LegacyRuntimePort
from .groups import group_run_snapshot_from_payload


_LEGACY_RUN_PROJECTOR = LegacyRunPayloadProjector()


class LegacyChatTaskStarter:
    """Starts agent tasks through the existing Chat session path when available."""

    def __init__(self, app_runtime: Any, runtime: Any) -> None:
        self._app_runtime = app_runtime
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any] | None:
        agent_id = str(request.get("agent_id") or "").strip()
        if not agent_id:
            return None
        if getattr(self._app_runtime, "chat_session", None) is None:
            return None

        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        client_message_id = str(
            metadata.get("client_message_id")
            or metadata.get("idempotency_key")
            or metadata.get("client_task_id")
            or ""
        ).strip()
        result = ChatAPI(self._app_runtime).send_runnable_message_in_session(
            str(request.get("conversation_id") or ""),
            str(request.get("prompt") or ""),
            runnable_id=agent_id,
            client_message_id=client_message_id,
        )
        if result.get("ok") is False:
            raise ValueError(str(result.get("error") or "发送 Agent 任务失败"))

        run_id = str(
            result.get("run_id")
            or result.get("agent_run_id")
            or result.get("workflow_run_id")
            or ""
        ).strip()
        if not run_id:
            return None

        conversation_id = str(
            result.get("session_id")
            or request.get("conversation_id")
            or getattr(getattr(self._app_runtime, "chat_session", None), "session_id", "")
            or ""
        ).strip()
        task_id = str(
            metadata.get("task_id")
            or metadata.get("client_task_id")
            or run_id
        ).strip()
        link_task_run = getattr(self._runtime, "link_task_run", None)
        if callable(link_task_run):
            link_task_run(task_id=task_id, run_id=run_id, session_id=conversation_id)

        try:
            run = self._runtime.get_run(run_id)
        except KeyError:
            run = {
                **result,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": conversation_id,
            }
        return self._projector.chat_task_payload(
            {**run, "task_id": task_id, "session_id": conversation_id},
            conversation_id=conversation_id,
        )


class LegacyStudioPort:
    """StudioPort adapter for the current Agent Studio runtime API."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()

    def list_agents(self) -> dict[str, Any]:
        return self._runtime.list_agents()

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._runtime.get_agent(agent_id)

    def save_agent(self, request: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(request.get("agent_id") or "").strip()
        if agent_id:
            try:
                self._runtime.get_agent(agent_id)
            except KeyError:
                return self._runtime.create_agent(request)
            return self._runtime.update_agent(agent_id, request)
        return self._runtime.create_agent(request)

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return self._runtime.delete_agent(agent_id)

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        return self._runtime.test_agent_model(agent_id)

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        return self._runtime.attach_skill(agent_id, skill_id)

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        return self._runtime.detach_skill(agent_id, skill_id)

    def list_skills(self) -> dict[str, Any]:
        return self._runtime.list_skills()

    def update_skill(self, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.update_skill(skill_id, request)

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        return self._runtime.delete_skill(skill_id)

    def list_skill_folders(self) -> dict[str, Any]:
        return self._runtime.list_skill_folders()

    def create_skill_folder(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.create_skill_folder(request)

    def update_skill_folder(self, folder_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.update_skill_folder(folder_id, request)

    def delete_skill_folder(self, folder_id: str, delete_skills: bool = False) -> dict[str, Any]:
        return self._runtime.delete_skill_folder(folder_id, delete_skills=delete_skills)

    def list_skill_sources(self) -> dict[str, Any]:
        return self._runtime.list_native_skill_sources()

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        return self._runtime.import_skill(source_path, folder_id)

    def sync_native_skills(self) -> dict[str, Any]:
        return self._runtime.sync_native_skills()

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        return self._runtime.install_skill_command(command, folder_id)

    def list_memories(self, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        return self._runtime.list_memory_items(
            include_deleted=include_deleted,
            limit=limit,
        )

    def create_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.create_memory_item(request)

    def update_memory(self, memory_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.update_memory_item(memory_id, request)

    def delete_memory(self, memory_id: str, reason: str | None = None) -> dict[str, Any]:
        return self._runtime.delete_memory_item(memory_id, reason=reason or "")

    def list_future_tasks(
        self,
        include_finished: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._runtime.list_future_tasks(
            include_finished=include_finished,
            limit=limit,
        )

    def cancel_future_task(
        self,
        future_task_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._runtime.cancel_future_task(future_task_id, reason=reason or "")

    def trigger_due_future_tasks(
        self,
        now_epoch: float | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._runtime.trigger_due_future_tasks(
            now_epoch=now_epoch,
            limit=limit,
        )

    def start_agent_run(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.create_agent_run(
            {
                "agent_id": request.get("agent_id"),
                "user_goal": request.get("objective") or request.get("goal"),
                "source": "yachiyo_studio",
                "client_run_id": request.get("client_run_id"),
                "run_group_id": request.get("run_group_id"),
            }
        )

    def list_groups(self) -> dict[str, Any]:
        list_agent_groups = getattr(self._runtime, "list_agent_groups", None)
        if callable(list_agent_groups):
            return list_agent_groups()

        chat_groups = chat_group_snapshots(self._runtime)
        if chat_groups:
            return {"ok": True, "groups": chat_groups}

        list_run_groups = getattr(self._runtime, "list_run_groups", None)
        if callable(list_run_groups):
            payload = list_run_groups(50)
            return {
                "ok": True,
                "groups": [
                    group_definition_from_run_group(item, self._runtime)
                    for item in payload.get("run_groups") or []
                    if isinstance(item, dict)
                ],
            }
        return {"ok": True, "groups": []}

    def get_group(self, group_id: str) -> dict[str, Any]:
        get_agent_group = getattr(self._runtime, "get_agent_group", None)
        if callable(get_agent_group):
            return get_agent_group(group_id)
        chat_group = chat_group_snapshot(group_id, self._runtime)
        if chat_group is not None:
            return chat_group
        run_group = self._runtime.get_run_group(group_id)
        return group_definition_from_run_group(run_group, self._runtime)

    def save_group(self, request: dict[str, Any]) -> dict[str, Any]:
        save_agent_group = getattr(self._runtime, "save_agent_group", None)
        if callable(save_agent_group):
            return save_agent_group(request)

        group_id = str(request.get("group_id") or request.get("agent_group_id") or "").strip()
        if group_id:
            update_agent_group = getattr(self._runtime, "update_agent_group", None)
            if callable(update_agent_group):
                return update_agent_group(group_id, request)
        else:
            create_agent_group = getattr(self._runtime, "create_agent_group", None)
            if callable(create_agent_group):
                return create_agent_group(request)

        return save_chat_group_snapshot(request, self._runtime)

    def start_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        start_agent_group_run = getattr(self._runtime, "start_agent_group_run", None)
        if callable(start_agent_group_run):
            return start_agent_group_run(request)

        group_id = str(request.get("group_id") or "").strip()
        objective = str(request.get("objective") or request.get("goal") or "").strip()
        client_run_id = str(
            request.get("client_run_id") or request.get("client_request_id") or ""
        ).strip()
        if not group_id:
            raise ValueError("缺少 group_id")
        if not objective:
            raise ValueError("群组运行目标不能为空")

        group = self.get_group(group_id)
        members = [item for item in group.get("members") or [] if isinstance(item, dict)]
        if not members:
            raise NotImplementedError("这个 legacy run group 没有可复用的成员定义")

        child_runs: list[dict[str, Any]] = []
        run_group_id = ""
        for index, member in enumerate(members):
            agent_id = str(member.get("agent_id") or "").strip()
            if not agent_id:
                continue
            child_client_run_id = (
                f"{client_run_id}:{index}:{agent_id}" if client_run_id else ""
            )

            def on_member_complete(
                completed_run: dict[str, Any],
                *,
                current_member: dict[str, Any] = member,
                current_index: int = index,
                current_child_client_run_id: str = child_client_run_id,
            ) -> None:
                append_group_member_event(
                    self._runtime,
                    completed_run,
                    _group_member_terminal_event_type(completed_run),
                    group_id=group_id,
                    group=group,
                    run_group_id="",
                    objective=objective,
                    member=current_member,
                    member_index=current_index,
                    client_run_id=client_run_id,
                    child_client_run_id=current_child_client_run_id,
                )

            child_run = create_runnable_run(
                self._runtime,
                runnable_id=agent_id,
                user_goal=objective,
                run_group_id=run_group_id,
                client_run_id=child_client_run_id,
                on_complete=on_member_complete,
            )
            if not run_group_id:
                run_group_id = str(child_run.get("run_group_id") or "")
                append_group_run_event(
                    self._runtime,
                    child_run,
                    "group.run.started",
                    group_id=group_id,
                    group=group,
                    run_group_id=run_group_id,
                    objective=objective,
                    status="running",
                    members=members,
                    child_run_ids=[str(child_run.get("run_id") or "")],
                    client_run_id=client_run_id,
                )
            append_group_member_event(
                self._runtime,
                child_run,
                "group.member.started",
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                member=member,
                member_index=index,
                client_run_id=client_run_id,
                child_client_run_id=child_client_run_id,
            )
            child_status = str(child_run.get("status") or "").strip()
            if child_status in {"approval_required", "waiting_approval"}:
                append_group_member_event(
                    self._runtime,
                    child_run,
                    "group.member.approval_required",
                    group_id=group_id,
                    group=group,
                    run_group_id=run_group_id,
                    objective=objective,
                    member=member,
                    member_index=index,
                    client_run_id=client_run_id,
                    child_client_run_id=child_client_run_id,
                )
            elif child_status in {"completed", "failed", "cancelled"}:
                append_group_member_event(
                    self._runtime,
                    child_run,
                    _group_member_terminal_event_type(child_run),
                    group_id=group_id,
                    group=group,
                    run_group_id=run_group_id,
                    objective=objective,
                    member=member,
                    member_index=index,
                    client_run_id=client_run_id,
                    child_client_run_id=child_client_run_id,
                )
            child_runs.append(child_run)

        if not child_runs:
            raise NotImplementedError("这个 legacy run group 没有可运行的成员")

        projected_status = _group_run_status_from_child_runs(child_runs)
        if projected_status and run_group_id:
            update_run_group = getattr(self._runtime, "_update_run_group", None)
            if callable(update_run_group):
                update_run_group(
                    run_group_id,
                    status=projected_status,
                    summary=(
                        _group_run_summary_from_child_runs(child_runs)
                        if projected_status in {"completed", "failed", "cancelled"}
                        else None
                    ),
                )
            if projected_status == "approval_required" and child_runs:
                append_group_run_event(
                    self._runtime,
                    child_runs[0],
                    "group.run.approval_required",
                    group_id=group_id,
                    group=group,
                    run_group_id=run_group_id,
                    objective=objective,
                    status=projected_status,
                    members=members,
                    child_run_ids=[
                        str(run.get("run_id") or "")
                        for run in child_runs
                        if str(run.get("run_id") or "")
                    ],
                    client_run_id=client_run_id,
                )

        run_group = self._runtime.get_run_group(run_group_id) if run_group_id else {}
        return {
            "run_group_id": run_group_id,
            "group_run_id": run_group_id,
            "group_id": group_id,
            "title": (
                request.get("title")
                or run_group.get("title")
                or group.get("name")
                or "Group run"
            ),
            "status": run_group.get("status") or "running",
            "objective": objective,
            "participants": members,
            "runs": child_runs,
            "child_run_ids": run_group.get("child_run_ids")
            or [run.get("run_id") for run in child_runs if run.get("run_id")],
            "events": self._projector.group_events_from_child_runs(child_runs, self._runtime),
            "shared_artifacts": self._projector.group_artifacts(child_runs),
            "pending_approvals": [
                run.get("pending_approval")
                for run in child_runs
                if run.get("pending_approval")
            ],
            "final_answer": run_group.get("summary") or "",
            "created_at": run_group.get("created_at") or "",
            "updated_at": run_group.get("updated_at") or "",
        }

    def list_group_runs(self, limit: int = 50) -> dict[str, Any]:
        list_run_groups = getattr(self._runtime, "list_run_groups", None)
        if not callable(list_run_groups):
            return {"ok": True, "group_runs": []}

        payload = list_run_groups(max(1, min(200, int(limit or 50))))
        raw_items = payload.get("run_groups") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raw_items = []
        return {
            "ok": True,
            "group_runs": [
                self._projector.group_run_from_legacy_run_group(item, self._runtime)
                for item in raw_items
                if isinstance(item, dict)
            ],
        }

    def get_group_run(self, group_run_id: str) -> dict[str, Any]:
        run_group = self._runtime.get_run_group(group_run_id)
        return self._projector.group_run_from_legacy_run_group(run_group, self._runtime)

    def get_group_run_event_stream(self, group_run_id: str) -> dict[str, Any]:
        group_run = group_run_snapshot_from_payload(self.get_group_run(group_run_id))
        return {
            "run_id": group_run.group_run_id,
            "events": [event.model_dump(mode="python") for event in group_run.events],
        }

    def get_group_run_event_page(
        self,
        group_run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        return _run_event_page_from_legacy_stream(
            self.get_group_run_event_stream(group_run_id),
            run_id=group_run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def list_workflows(self) -> dict[str, Any]:
        return self._runtime.list_workflows()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._runtime.get_workflow(workflow_id)

    def save_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(request.get("workflow_id") or "").strip()
        if workflow_id:
            try:
                self._runtime.get_workflow(workflow_id)
            except KeyError:
                return self._runtime.create_workflow(request)
            return self._runtime.update_workflow(workflow_id, request)
        return self._runtime.create_workflow(request)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._runtime.delete_workflow(workflow_id)

    def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.create_workflow_run(
            {
                "workflow_id": request.get("workflow_id"),
                "user_goal": request.get("objective") or request.get("goal"),
                "source": "yachiyo_studio",
                "client_run_id": request.get("client_run_id"),
                "run_group_id": request.get("run_group_id"),
            }
        )

    def list_run_timelines(self, limit: int = 50) -> dict[str, Any]:
        return self._runtime.list_runs(limit)

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        return _run_with_replay_events(self._runtime.get_run(run_id), self._runtime)

    def rerun_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.rerun_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.cancel_run(run_id)

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.delete_run(run_id)

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        return self._runtime.approve_run_approval(run_id)

    def reject_run_approval(self, run_id: str, reason: str | None = None) -> dict[str, Any]:
        return self._runtime.reject_run_approval(run_id, reason or "")

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self._runtime.read_run_artifact(run_id, artifact_path)

    def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
        return self._runtime.list_run_events(run_id)

    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        try:
            return self._runtime.list_run_events(
                run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except TypeError:
            raw_page = self._runtime.list_run_events(run_id)
        return _run_event_page_from_legacy_stream(
            raw_page,
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
        )


def _chat_task_payload(run: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.chat_task_payload(run, conversation_id=conversation_id)


def _run_with_replay_events(run: dict[str, Any], runtime: Any) -> dict[str, Any]:
    run_id = str(run.get("run_id") or "").strip()
    list_run_events = getattr(runtime, "list_run_events", None)
    if not run_id or not callable(list_run_events):
        return run
    try:
        events_payload = list_run_events(run_id, limit=500)
    except Exception:
        return run
    events = events_payload.get("events") if isinstance(events_payload, dict) else None
    if not isinstance(events, list) or not events:
        return run
    replay_events = [dict(event) for event in events if isinstance(event, dict)]
    legacy_events = _legacy_run_events(run)
    if not legacy_events:
        return {**run, "events": replay_events}

    enriched_events = list(legacy_events)
    existing_keys = {_event_identity(event) for event in enriched_events}
    for event in replay_events:
        if not _is_memory_or_skill_event(event):
            continue
        event_key = _event_identity(event)
        if event_key in existing_keys:
            continue
        enriched_events.append(event)
        existing_keys.add(event_key)
    if len(enriched_events) == len(legacy_events):
        return run
    return {**run, "events": enriched_events}


def _legacy_run_events(run: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("events", "run_events", "timeline"):
        value = run.get(key)
        if isinstance(value, list) and value:
            return [dict(event) for event in value if isinstance(event, dict)]
    return []


def _is_memory_or_skill_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or event.get("event") or "")
    return event_type.startswith("memory.") or event_type.startswith("skill.")


def _event_identity(event: dict[str, Any]) -> tuple[str, str]:
    event_type = str(event.get("event_type") or event.get("event") or "")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return (event_type, json.dumps(payload, sort_keys=True, default=str))


def _run_event_page_from_legacy_stream(
    payload: dict[str, Any],
    *,
    run_id: str,
    after_sequence: int,
    limit: int,
) -> dict[str, Any]:
    clean_after_sequence = max(0, int(after_sequence or 0))
    clean_limit = max(1, min(500, int(limit or 200)))
    events = [
        dict(event)
        for event in payload.get("events", [])
        if isinstance(event, dict) and _event_sequence(event) > clean_after_sequence
    ]
    page = events[:clean_limit]
    next_after_sequence = max([_event_sequence(event) for event in page] or [clean_after_sequence])
    return {
        "run_id": payload.get("run_id") or run_id,
        "after_sequence": clean_after_sequence,
        "limit": clean_limit,
        "next_after_sequence": next_after_sequence,
        "has_more": len(events) > clean_limit,
        "events": page,
    }


def _event_sequence(event: dict[str, Any]) -> int:
    try:
        return int(event.get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


def _group_artifacts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.group_artifacts(runs)


def _group_run_from_legacy_run_group(
    run_group: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.group_run_from_legacy_run_group(run_group, runtime)


def _child_runs_for_run_group(run_group: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.child_runs_for_run_group(run_group, runtime)


def _group_member_terminal_event_type(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "").strip()
    if status == "failed":
        return "group.member.failed"
    if status == "cancelled":
        return "group.member.cancelled"
    return "group.member.completed"


def _group_run_status_from_child_runs(child_runs: list[dict[str, Any]]) -> str:
    statuses = {
        str(run.get("status") or "").strip()
        for run in child_runs
        if str(run.get("status") or "").strip()
    }
    if not statuses:
        return ""
    if statuses & {"approval_required", "waiting_approval"}:
        return "approval_required"
    if statuses & {"queued", "running", "processing"}:
        return ""
    if "failed" in statuses:
        return "failed"
    if "cancelled" in statuses:
        return "cancelled"
    if statuses == {"completed"}:
        return "completed"
    return ""


def _group_run_summary_from_child_runs(child_runs: list[dict[str, Any]]) -> str | None:
    lines: list[str] = []
    for run in child_runs:
        result = str(run.get("result") or "").strip()
        if not result:
            continue
        label = str(run.get("runnable_name") or run.get("runnable_id") or "").strip()
        lines.append(f"{label}: {result}" if label else result)
    return "\n".join(lines) if lines else None
