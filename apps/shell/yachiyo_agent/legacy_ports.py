"""Ports backed by the existing Agent runtime surface."""

from __future__ import annotations

from typing import Any

from apps.shell.chat_api import ChatAPI
from apps.shell.agent.runtime.errors import AgentRuntimeError

from .daily_desktop import (
    daily_desktop_allowed_tools,
    daily_desktop_direct_metadata_request,
    daily_desktop_entrypoint_requests,
    daily_desktop_planned_timeline,
    daily_desktop_recovery_execution_prompt,
    daily_desktop_user_metadata,
    main_chat_entrypoint_allowed_tools,
)
from .legacy_event_pages import (
    is_replay_enrichment_event as _is_replay_enrichment_event,
    run_event_page_from_legacy_stream as _run_event_page_from_legacy_stream,
    run_with_replay_events as _run_with_replay_events,
)
from .legacy_groups import (
    chat_group_snapshot,
    chat_group_snapshots,
    group_definition_from_run_group,
    save_chat_group_snapshot,
)
from .legacy_group_runs import start_legacy_group_run
from .legacy_runs import LegacyRunPayloadProjector
from .legacy_tasks import (
    LegacyRuntimePort,
    MAIN_CHAT_AGENT_ID,
    _approval_id_from_decision,
    _assert_matching_pending_approval,
)
from .planner_projection import (
    planner_run_event_payloads,
    runtime_planner_decision,
    runtime_planner_metadata,
)
from .planner_execution import planner_tool_requests
from .recovery_actions import (
    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
    recovery_retry_context_payload,
)
from .desktop_permissions import desktop_permission_missing_by_capability
from .desk import LocalAgentDeskStore
from .groups import group_run_snapshot_from_payload
from .tool_catalog import runtime_tool_catalog_snapshot


_LEGACY_RUN_PROJECTOR = LegacyRunPayloadProjector()


def _rejection_reason(decision: dict[str, Any] | str | None) -> str:
    if isinstance(decision, dict):
        return str(decision.get("reason") or "").strip()
    return str(decision or "").strip()


class LegacyChatTaskStarter:
    """Starts agent tasks through the existing Chat session path when available."""

    def __init__(self, app_runtime: Any, runtime: Any) -> None:
        self._app_runtime = app_runtime
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if str(request.get("workflow_id") or "").strip():
            return None
        agent_id = str(request.get("agent_id") or request.get("runnable_id") or "").strip()
        if not agent_id:
            agent_id = MAIN_CHAT_AGENT_ID
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
            metadata=metadata,
        )
        if result.get("ok") is False:
            raise ValueError(str(result.get("error") or "发送 Agent 任务失败"))

        run_id = str(
            result.get("run_id")
            or result.get("agent_run_id")
            or result.get("workflow_run_id")
            or ""
        ).strip()
        conversation_id = str(
            result.get("session_id")
            or request.get("conversation_id")
            or getattr(getattr(self._app_runtime, "chat_session", None), "session_id", "")
            or ""
        ).strip()
        task_id = str(
            result.get("task_id")
            or metadata.get("task_id")
            or metadata.get("client_task_id")
            or run_id
        ).strip()
        if not run_id:
            if agent_id != MAIN_CHAT_AGENT_ID or not task_id:
                return None
            executed = self._execute_main_daily_desktop_task(
                task_id=task_id,
                conversation_id=conversation_id,
                prompt=str(request.get("prompt") or request.get("goal") or ""),
                metadata=metadata,
            )
            if executed is not None:
                return executed
            return self._projector.chat_task_payload(
                {
                    "task_id": task_id,
                    "session_id": conversation_id,
                    "status": result.get("status") or "pending",
                    "user_goal": request.get("prompt") or request.get("goal") or "",
                    "summary": result.get("summary") or result.get("result") or "",
                    "timeline": result.get("timeline")
                    or daily_desktop_planned_timeline(str(request.get("prompt") or "")),
                },
                conversation_id=conversation_id,
            )

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

    def execute_existing_main_chat_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._execute_main_daily_desktop_task(
            task_id=task_id,
            conversation_id=conversation_id,
            prompt=prompt,
            metadata=metadata,
        )

    def _execute_main_daily_desktop_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        prompt = str(prompt or "").strip()
        allowed_daily_desktop_tools = daily_desktop_allowed_tools()
        allowed_entrypoint_tools = main_chat_entrypoint_allowed_tools(
            self._runtime,
            fallback=allowed_daily_desktop_tools,
        )
        execution_prompt = daily_desktop_recovery_execution_prompt(prompt, metadata)
        planner_decision = runtime_planner_decision(
            prompt or execution_prompt,
            metadata=metadata,
            allowed_tools=allowed_entrypoint_tools,
        )
        direct_tool_request = daily_desktop_direct_metadata_request(
            metadata,
            allowed_tools=allowed_daily_desktop_tools,
        )
        desktop_requests = daily_desktop_entrypoint_requests(
            prompt,
            metadata=metadata,
            allowed_tools=allowed_daily_desktop_tools,
        )
        planner_requests = (
            []
            if direct_tool_request or desktop_requests
            else planner_tool_requests(
                prompt or execution_prompt,
                allowed_entrypoint_tools,
                metadata=metadata,
            )
        )
        if not task_id:
            return None
        if not direct_tool_request and not desktop_requests and not planner_requests:
            return None
        self._sync_chat_user_daily_desktop_metadata(
            task_id,
            desktop_requests or planner_requests,
            planner_decision=planner_decision,
        )
        start_main_chat_run = getattr(self._runtime, "start_main_chat_run", None)
        execute_main_chat_model_loop = getattr(self._runtime, "execute_main_chat_model_loop", None)
        if not callable(start_main_chat_run) or not callable(execute_main_chat_model_loop):
            return None

        self._sync_app_task_running(task_id)
        run_id = ""
        try:
            run = start_main_chat_run(
                task_id=task_id,
                session_id=conversation_id,
                user_goal=prompt or execution_prompt,
            )
            run_id = str(run.get("run_id") or "").strip()
            if not run_id:
                return None
            self._append_planner_run_events(run_id, planner_decision)
            append_run_event = getattr(self._runtime, "append_run_event", None)
            retry_context_payload = recovery_retry_context_payload(metadata)
            if retry_context_payload and callable(append_run_event):
                append_run_event(
                    run_id,
                    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
                    retry_context_payload,
                )
            run = execute_main_chat_model_loop(
                run_id,
                [{"role": "user", "content": execution_prompt or prompt or "执行恢复后的原操作"}],
                direct_tool_request=direct_tool_request,
            )
            status = str(run.get("status") or "").strip()
            result_text = str(run.get("result") or "").strip()
            if status == "approval_required":
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    "等待你在 Agent Studio 中审批后继续。",
                    status="processing",
                )
                return self._projector.chat_task_payload(
                    {**run, "task_id": task_id, "session_id": conversation_id},
                    conversation_id=conversation_id,
                )
            if status in {"failed", "cancelled"}:
                self._sync_app_task_failed(task_id, result_text or f"Native Run {status}")
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    result_text or f"Native Run {status}",
                    status="failed",
                    error=result_text or f"Native Run {status}",
                )
                return self._projector.chat_task_payload(
                    {**run, "task_id": task_id, "session_id": conversation_id},
                    conversation_id=conversation_id,
                )
            complete_main_chat_run = getattr(self._runtime, "complete_main_chat_run", None)
            if callable(complete_main_chat_run) and result_text:
                run = complete_main_chat_run(run_id, result_text)
            self._sync_app_task_completed(task_id, result_text)
            if result_text:
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    result_text,
                    status="completed",
                )
            return self._projector.chat_task_payload(
                {**run, "task_id": task_id, "session_id": conversation_id},
                conversation_id=conversation_id,
            )
        except Exception as exc:
            if run_id:
                fail_main_chat_run = getattr(self._runtime, "fail_main_chat_run", None)
                if callable(fail_main_chat_run):
                    try:
                        fail_main_chat_run(run_id, exc)
                    except Exception:
                        pass
            self._sync_app_task_failed(task_id, str(exc))
            self._sync_chat_assistant_message(
                task_id,
                conversation_id,
                str(exc),
                status="failed",
                error=str(exc),
            )
            raise

    def _sync_chat_user_daily_desktop_metadata(
        self,
        task_id: str,
        desktop_requests: list[dict[str, Any]],
        *,
        planner_decision: Any | None = None,
    ) -> None:
        chat_session = getattr(self._app_runtime, "chat_session", None)
        update_metadata = getattr(chat_session, "update_message_metadata_for_task", None)
        if not callable(update_metadata):
            return
        metadata = {
            **runtime_planner_metadata(planner_decision),
            **daily_desktop_user_metadata(desktop_requests),
        }
        if not metadata:
            return
        try:
            update_metadata(task_id, metadata, role="user")
        except Exception:
            return

    def _append_planner_run_events(self, run_id: str, planner_decision: Any | None) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not callable(append_run_event):
            return
        for event_type, payload in planner_run_event_payloads(planner_decision):
            try:
                append_run_event(run_id, event_type, payload)
            except Exception:
                continue

    def _sync_app_task_running(self, task_id: str) -> None:
        self._sync_app_task_status(task_id, "running", progress_label="正在执行桌面操作")

    def _sync_app_task_completed(self, task_id: str, result: str) -> None:
        self._sync_app_task_status(
            task_id,
            "completed",
            result=result or "[任务已完成，无输出]",
            progress_label="已完成",
        )

    def _sync_app_task_failed(self, task_id: str, error: str) -> None:
        self._sync_app_task_status(
            task_id,
            "failed",
            error=error or "任务执行失败",
            progress_label="执行失败",
        )

    def _sync_app_task_status(
        self,
        task_id: str,
        status: str,
        *,
        result: str | None = None,
        error: str | None = None,
        progress_label: str | None = None,
    ) -> None:
        state = getattr(self._app_runtime, "state", None)
        update_task_status = getattr(state, "update_task_status", None)
        if not callable(update_task_status):
            return
        try:
            from packages.protocol.enums import TaskStatus

            update_task_status(
                task_id,
                TaskStatus(status),
                result=result,
                error=error,
                progress_label=progress_label,
            )
        except Exception:
            return

    def _sync_chat_assistant_message(
        self,
        task_id: str,
        conversation_id: str,
        content: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        session = self._chat_session_for_conversation(conversation_id)
        upsert = getattr(session, "upsert_assistant_message", None)
        if session is None or not callable(upsert):
            return
        try:
            from apps.core.chat_session import MessageStatus

            message_status = {
                "completed": MessageStatus.COMPLETED,
                "failed": MessageStatus.FAILED,
                "processing": MessageStatus.PROCESSING,
            }.get(status, MessageStatus.PROCESSING)
            upsert(
                task_id=task_id,
                content=content,
                status=message_status,
                error=error,
            )
        except Exception:
            return

    def _chat_session_for_conversation(self, conversation_id: str) -> Any:
        current = getattr(self._app_runtime, "chat_session", None)
        if not conversation_id:
            return current
        if str(getattr(current, "session_id", "") or "") == conversation_id:
            return current
        try:
            from apps.core.chat_session import ChatSession
            from apps.core.chat_store import get_chat_store

            store = getattr(self._app_runtime, "store", None) or get_chat_store()
            session = ChatSession(session_id=conversation_id)
            session.attach_store(
                store,
                load_existing=True,
                fail_active_messages=False,
            )
            return session
        except Exception:
            return current

class LegacyStudioPort:
    """StudioPort adapter for the current Agent Studio runtime API."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()
        self._desk_store = LocalAgentDeskStore(runtime=runtime)

    def list_agents(self) -> dict[str, Any]:
        return self._runtime.list_agents()

    def list_tool_catalog(self) -> dict[str, Any]:
        try:
            missing_permissions = desktop_permission_missing_by_capability()
        except Exception:
            missing_permissions = {"desktop_execution": ["permission_probe_failed"]}
        plugin_states = None
        list_plugins = getattr(self._runtime, "list_restricted_tool_plugins", None)
        if callable(list_plugins):
            try:
                payload = list_plugins()
                plugin_states = payload.get("plugins") if isinstance(payload, dict) else payload
            except Exception:
                plugin_states = None
        return runtime_tool_catalog_snapshot(
            missing_permissions=missing_permissions,
            plugin_states=plugin_states,
        ).model_dump(mode="json")

    def list_restricted_tool_plugins(self) -> dict[str, Any]:
        list_plugins = getattr(self._runtime, "list_restricted_tool_plugins", None)
        if callable(list_plugins):
            payload = list_plugins()
            if isinstance(payload, dict):
                return dict(payload)
            if isinstance(payload, (list, tuple)):
                return {"ok": True, "plugins": list(payload)}
            return {"ok": True, "plugins": []}
        catalog = runtime_tool_catalog_snapshot()
        return {
            "ok": True,
            "plugins": [plugin.model_dump(mode="json") for plugin in catalog.plugins],
        }

    def install_restricted_tool_plugin(self, request: dict[str, Any]) -> dict[str, Any]:
        install_plugin = getattr(self._runtime, "install_restricted_tool_plugin", None)
        if callable(install_plugin):
            return dict(install_plugin(dict(request)))
        raise AgentRuntimeError("Restricted tool plugin install is not available")

    def update_restricted_tool_plugin(
        self,
        plugin_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        update_plugin = getattr(self._runtime, "update_restricted_tool_plugin", None)
        if callable(update_plugin):
            return dict(update_plugin(plugin_id, dict(request)))
        raise AgentRuntimeError("Restricted tool plugin update is not available")

    def uninstall_restricted_tool_plugin(self, plugin_id: str) -> dict[str, Any]:
        uninstall_plugin = getattr(self._runtime, "uninstall_restricted_tool_plugin", None)
        if callable(uninstall_plugin):
            return dict(uninstall_plugin(plugin_id))
        raise AgentRuntimeError("Restricted tool plugin uninstall is not available")

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

    def get_agent_desk(self, agent_id: str) -> dict[str, Any]:
        return self._desk_store.get_agent_desk(agent_id)

    def write_agent_desk_note(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._desk_store.write_agent_desk_note(
            agent_id,
            str(request.get("content") or ""),
        )

    def write_agent_desk_file(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._desk_store.write_agent_desk_file(
            agent_id,
            str(request.get("path") or ""),
            str(request.get("content") or ""),
        )

    def trigger_agent_desk_file_event(
        self,
        agent_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return self._desk_store.trigger_agent_desk_file_event(agent_id, request)

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

        return start_legacy_group_run(
            self._runtime,
            request,
            get_group=self.get_group,
            projector=self._projector,
        )

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
        list_group_run_events = getattr(self._runtime, "list_group_run_events", None)
        if callable(list_group_run_events):
            return list_group_run_events(group_run_id, limit=500)
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
        list_group_run_events = getattr(self._runtime, "list_group_run_events", None)
        if callable(list_group_run_events):
            return list_group_run_events(
                group_run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
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

    def rerun_run(
        self,
        run_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._runtime.rerun_run(run_id, request)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.cancel_run(run_id)

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.delete_run(run_id)

    def approve_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_run_approval(run_id, decision)
        return self._runtime.approve_run_approval(run_id)

    def reject_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        self._assert_run_approval(run_id, decision)
        return self._runtime.reject_run_approval(run_id, _rejection_reason(decision))

    def _assert_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | str | None,
    ) -> None:
        requested_approval_id = _approval_id_from_decision(decision)
        if not requested_approval_id:
            return
        _assert_matching_pending_approval(
            self._runtime.get_run(run_id),
            requested_approval_id,
        )

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


def _group_artifacts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.group_artifacts(runs)


def _group_run_from_legacy_run_group(
    run_group: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.group_run_from_legacy_run_group(run_group, runtime)


def _child_runs_for_run_group(run_group: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.child_runs_for_run_group(run_group, runtime)
