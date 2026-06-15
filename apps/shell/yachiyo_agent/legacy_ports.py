"""Ports backed by the existing Agent runtime surface."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"


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
                child_runs.append(runtime.get_run(str(run_id)))
            except KeyError:
                continue
        return child_runs


_LEGACY_RUN_PROJECTOR = LegacyRunPayloadProjector()


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
                link_task_run(task_id=task_id, run_id=run_id, session_id=conversation_id)
                try:
                    run = self._runtime.get_run(run_id)
                except KeyError:
                    run = {**run, "task_id": task_id, "session_id": conversation_id}
            else:
                run = {**run, "task_id": task_id, "session_id": conversation_id}
        return self._projector.chat_task_payload(run, conversation_id=conversation_id)

    def get_task_snapshot(self, task_id: str) -> dict[str, Any]:
        return self._projector.chat_task_payload(
            self._runtime.get_run(self._run_id_for_task(task_id))
        )

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
        return self._projector.chat_task_payload(
            self._runtime.approve_run_approval(self._run_id_for_task(approval_id))
        )

    def reject(self, approval_id: str, reason: str | None = None) -> dict[str, Any]:
        return self._projector.chat_task_payload(
            self._runtime.reject_run_approval(self._run_id_for_task(approval_id), reason or "")
        )

    def cancel(self, task_id: str) -> dict[str, Any]:
        return self._projector.chat_task_payload(
            self._runtime.cancel_run(self._run_id_for_task(task_id))
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

        chat_groups = _chat_group_snapshots(self._runtime)
        if chat_groups:
            return {"ok": True, "groups": chat_groups}

        list_run_groups = getattr(self._runtime, "list_run_groups", None)
        if callable(list_run_groups):
            payload = list_run_groups(50)
            return {
                "ok": True,
                "groups": [
                    _group_definition_from_run_group(item, self._runtime)
                    for item in payload.get("run_groups") or []
                    if isinstance(item, dict)
                ],
            }
        return {"ok": True, "groups": []}

    def get_group(self, group_id: str) -> dict[str, Any]:
        get_agent_group = getattr(self._runtime, "get_agent_group", None)
        if callable(get_agent_group):
            return get_agent_group(group_id)
        chat_group = _chat_group_snapshot(group_id, self._runtime)
        if chat_group is not None:
            return chat_group
        run_group = self._runtime.get_run_group(group_id)
        return _group_definition_from_run_group(run_group, self._runtime)

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

        return _save_chat_group_snapshot(request, self._runtime)

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
                _append_group_member_event(
                    self._runtime,
                    completed_run,
                    "group.member.completed",
                    group_id=group_id,
                    run_group_id="",
                    objective=objective,
                    member=current_member,
                    member_index=current_index,
                    client_run_id=client_run_id,
                    child_client_run_id=current_child_client_run_id,
                )

            child_run = _create_runnable_run(
                self._runtime,
                runnable_id=agent_id,
                user_goal=objective,
                run_group_id=run_group_id,
                client_run_id=child_client_run_id,
                on_complete=on_member_complete,
            )
            if not run_group_id:
                run_group_id = str(child_run.get("run_group_id") or "")
            _append_group_member_event(
                self._runtime,
                child_run,
                "group.member.started",
                group_id=group_id,
                run_group_id=run_group_id,
                objective=objective,
                member=member,
                member_index=index,
                client_run_id=client_run_id,
                child_client_run_id=child_client_run_id,
            )
            if str(child_run.get("status") or "") in {"completed", "failed", "cancelled"}:
                _append_group_member_event(
                    self._runtime,
                    child_run,
                    "group.member.completed",
                    group_id=group_id,
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
        return self._runtime.get_run(run_id)

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


def _chat_task_payload(run: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.chat_task_payload(run, conversation_id=conversation_id)


def _group_artifacts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.group_artifacts(runs)


def _group_run_from_legacy_run_group(
    run_group: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.group_run_from_legacy_run_group(run_group, runtime)


def _child_runs_for_run_group(run_group: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.child_runs_for_run_group(run_group, runtime)


def _chat_group_snapshots(runtime: Any) -> list[dict[str, Any]]:
    try:
        store = _chat_store()
        sessions = store.list_sessions(limit=200)
    except Exception:
        return []
    return [
        _group_definition_from_chat_session(session, runtime)
        for session in sessions
        if str(getattr(session, "conversation_kind", "") or "") == "group"
    ]


def _chat_group_snapshot(group_id: str, runtime: Any) -> dict[str, Any] | None:
    try:
        session = _chat_store().get_session(group_id)
    except Exception:
        return None
    if session is None:
        return None
    if str(getattr(session, "conversation_kind", "") or "") != "group":
        return None
    return _group_definition_from_chat_session(session, runtime)


def _save_chat_group_snapshot(request: dict[str, Any], runtime: Any) -> dict[str, Any]:
    store = _chat_store()
    requested_group_id = str(
        request.get("group_id") or request.get("agent_group_id") or ""
    ).strip()
    existing = store.get_session(requested_group_id) if requested_group_id else None
    if existing is not None and getattr(existing, "conversation_kind", "") != "group":
        raise ValueError("只能修改手动 Agent 群组")

    participants = _group_participants_from_request(request, runtime)
    if not participants and existing is not None:
        participants = _parse_participants_json(getattr(existing, "participants_json", "[]"))
    if not _agent_participants(participants):
        raise ValueError("群组至少需要一个已启用 Agent")

    group_id = requested_group_id or f"agent_group_{uuid4().hex[:12]}"
    if existing is None:
        store.create_session(group_id, _group_name_from_request(request, participants))
        existing = store.get_session(group_id)

    group_name = _group_name_from_request(request, participants, existing=existing)
    avatar_url = str(
        request.get("avatar_url")
        if request.get("avatar_url") is not None
        else getattr(existing, "avatar_url", "")
    ).strip()
    store.update_session_title(group_id, group_name)
    store.update_session_context(
        group_id,
        conversation_kind="group",
        runnable_id="",
        runnable_name=group_name,
        run_group_id=str(getattr(existing, "run_group_id", "") or ""),
        participants_json=json.dumps(participants, ensure_ascii=False),
        avatar_url=avatar_url,
    )
    saved = store.get_session(group_id)
    if saved is None:
        raise KeyError(group_id)
    return _group_definition_from_chat_session(saved, runtime)


def _chat_store() -> Any:
    from apps.core.chat_store import get_chat_store

    return get_chat_store()


def _group_definition_from_chat_session(session: Any, runtime: Any) -> dict[str, Any]:
    del runtime
    participants = _parse_participants_json(getattr(session, "participants_json", "[]"))
    members = [
        {
            "agent_id": str(item.get("id") or item.get("agent_id") or ""),
            "name": str(item.get("nickname") or item.get("name") or item.get("id") or ""),
            "role": str(item.get("role") or "member"),
            "sort_order": index,
            "enabled": bool(item.get("enabled", True)),
        }
        for index, item in enumerate(_agent_participants(participants))
        if str(item.get("id") or item.get("agent_id") or "").strip()
    ]
    group_id = str(getattr(session, "session_id", "") or "").strip()
    name = str(
        getattr(session, "runnable_name", "")
        or getattr(session, "title", "")
        or group_id
        or "Agent Group"
    ).strip()
    return {
        "group_id": group_id,
        "name": name,
        "description": None,
        "members": members,
        "mode": "moderated",
        "moderator_agent_id": members[0]["agent_id"] if members else None,
        "memory_scope": "shared",
        "enabled": True,
        "created_at": getattr(session, "created_at", "") or "",
        "updated_at": "",
    }


def _group_participants_from_request(
    request: dict[str, Any],
    runtime: Any,
) -> list[dict[str, Any]]:
    agent_ids = _agent_ids_from_group_request(request)
    if not agent_ids:
        return []

    participants = [_main_participant(runtime)]
    for agent_id in agent_ids:
        participants.append(_participant_for_agent_id(runtime, agent_id))
    return participants


def _agent_ids_from_group_request(request: dict[str, Any]) -> list[str]:
    raw_items: list[Any] = []
    for key in ("participant_ids", "agent_ids", "member_ids"):
        value = request.get(key)
        if isinstance(value, list):
            raw_items.extend(value)

    for key in ("members", "participants"):
        value = request.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                raw_items.append(item.get("agent_id") or item.get("id"))
            else:
                raw_items.append(item)

    seen: set[str] = set()
    agent_ids: list[str] = []
    for raw_item in raw_items:
        agent_id = str(raw_item or "").strip()
        if not agent_id or agent_id == "main" or agent_id in seen:
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


def _participant_for_agent_id(runtime: Any, agent_id: str) -> dict[str, Any]:
    resolve_runnable = getattr(runtime, "resolve_runnable", None)
    if not callable(resolve_runnable):
        return {"kind": "agent", "id": agent_id, "name": agent_id}

    try:
        runnable = resolve_runnable(runnable_id=agent_id)
    except TypeError:
        runnable = resolve_runnable(agent_id)

    if not isinstance(runnable, dict) or runnable.get("kind", "agent") != "agent":
        raise ValueError("群组成员必须是已启用的 Agent")
    if not runnable.get("enabled", True):
        raise ValueError("群组成员包含已停用 Agent")
    return _participant_for_runnable(runnable)


def _participant_for_runnable(runnable: dict[str, Any]) -> dict[str, Any]:
    participant = {
        "kind": "agent",
        "id": str(runnable.get("id") or runnable.get("agent_id") or ""),
        "name": str(runnable.get("name") or runnable.get("id") or ""),
    }
    for key in (
        "nickname",
        "description",
        "avatar_url",
        "category",
        "output_contract",
    ):
        value = runnable.get(key)
        if value:
            participant[key] = str(value)
    tool_policy = runnable.get("tool_policy")
    if isinstance(tool_policy, dict):
        participant["tool_policy"] = dict(tool_policy)
    return participant


def _main_participant(runtime: Any) -> dict[str, Any]:
    assistant = getattr(getattr(runtime, "config", None), "assistant", None)
    participant: dict[str, Any] = {
        "kind": "main",
        "id": "main",
        "name": str(getattr(assistant, "agent_name", "") or "Yachiyo"),
        "nickname": str(getattr(assistant, "agent_nickname", "") or "月見八千代"),
    }
    avatar_path = str(getattr(assistant, "agent_avatar_path", "") or "")
    if avatar_path:
        participant["avatar_path"] = avatar_path
    return participant


def _parse_participants_json(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _agent_participants(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in participants
        if str(item.get("kind") or "agent") == "agent"
        and str(item.get("id") or item.get("agent_id") or "").strip()
    ]


def _group_name_from_request(
    request: dict[str, Any],
    participants: list[dict[str, Any]],
    *,
    existing: Any | None = None,
) -> str:
    name = str(request.get("name") or "").strip()
    if name:
        return name
    existing_name = str(
        getattr(existing, "runnable_name", "") or getattr(existing, "title", "")
    ).strip()
    if existing_name:
        return existing_name
    names = [
        str(item.get("nickname") or item.get("name") or "").strip()
        for item in participants
        if str(item.get("kind") or "") in {"main", "agent"}
    ]
    return "、".join([name for name in names if name]) or "新群组"


def _group_definition_from_run_group(run_group: dict[str, Any], runtime: Any) -> dict[str, Any]:
    run_group_id = str(run_group.get("run_group_id") or run_group.get("group_id") or "")
    members = _run_group_members(run_group, runtime)
    source = str(run_group.get("source") or "").strip()
    summary = str(run_group.get("summary") or "").strip()
    description_parts = [part for part in (source, summary) if part]
    return {
        "group_id": run_group_id,
        "name": str(run_group.get("title") or run_group_id or "Run Group"),
        "description": " · ".join(description_parts) or None,
        "members": members,
        "mode": _run_group_mode(source),
        "moderator_agent_id": members[0]["agent_id"] if members else None,
        "memory_scope": "shared",
        "enabled": True,
        "created_at": run_group.get("created_at") or "",
        "updated_at": run_group.get("updated_at") or "",
    }


def _run_group_members(run_group: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, run_id in enumerate(run_group.get("child_run_ids") or []):
        try:
            run = runtime.get_run(str(run_id))
        except Exception:
            continue
        agent_id = str(run.get("agent_id") or run.get("runnable_id") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        members.append(
            {
                "agent_id": agent_id,
                "name": str(run.get("runnable_name") or agent_id),
                "role": str(run.get("kind") or "member"),
                "sort_order": index,
                "enabled": True,
            }
        )
    return members


def _run_group_mode(source: str) -> str:
    clean = source.strip().lower()
    if clean == "workflow":
        return "pipeline"
    if clean in {"delegation", "agent"}:
        return "moderated"
    return "custom"


def _create_runnable_run(
    runtime: Any,
    *,
    runnable_id: str,
    user_goal: str,
    run_group_id: str = "",
    client_run_id: str = "",
    on_complete: Any | None = None,
) -> dict[str, Any]:
    create_async = getattr(runtime, "create_run_for_runnable_async", None)
    if callable(create_async):
        return create_async(
            runnable_id=runnable_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            on_complete=on_complete,
        )
    return runtime.create_run_for_runnable(
        runnable_id=runnable_id,
        user_goal=user_goal,
        run_group_id=run_group_id,
        client_run_id=client_run_id,
    )


def _append_group_member_event(
    runtime: Any,
    run: dict[str, Any],
    event_type: str,
    *,
    group_id: str,
    run_group_id: str,
    objective: str,
    member: dict[str, Any],
    member_index: int,
    client_run_id: str = "",
    child_client_run_id: str = "",
) -> None:
    append_run_event = getattr(runtime, "append_run_event", None)
    run_id = str(run.get("run_id") or "").strip()
    if not callable(append_run_event) or not run_id:
        return
    payload = {
        "agent_id": str(member.get("agent_id") or run.get("runnable_id") or ""),
        "agent_name": str(member.get("name") or run.get("runnable_name") or ""),
        "group_id": group_id,
        "member_index": member_index,
        "member_role": str(member.get("role") or ""),
        "objective": objective,
        "run_group_id": run_group_id or str(run.get("run_group_id") or ""),
        "run_id": run_id,
        "status": str(run.get("status") or ""),
    }
    if client_run_id:
        payload["client_run_id"] = client_run_id
    if child_client_run_id:
        payload["child_client_run_id"] = child_client_run_id
    append_run_event(run_id, event_type, payload)
