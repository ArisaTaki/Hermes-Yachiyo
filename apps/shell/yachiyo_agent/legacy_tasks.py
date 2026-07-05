"""Legacy Chat-facing runtime port adapters."""

from __future__ import annotations

import inspect
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError

from .desktop_permissions import (
    desktop_permission_missing_by_capability,
    desktop_runtime_blocking_conditions_by_capability,
)
from .legacy_groups import (
    chat_group_snapshot,
    chat_group_snapshots,
    group_definition_from_run_group,
)
from .legacy_group_runs import start_legacy_group_run
from .legacy_runs import LegacyRunPayloadProjector
from .planner_projection import (
    planner_run_event_payloads,
    runtime_planner_decision,
    runtime_planner_metadata,
)
from .policy import desktop_execution_capability_snapshots
from .runtime_execution import (
    runtime_execution_requests_from_envelope_payload,
    runtime_execution_requests_from_metadata,
)
from .workflow_run_snapshots import workflow_run_snapshot_from_payload

MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"


def _rejection_reason(decision: dict[str, Any] | str | None) -> str:
    if isinstance(decision, dict):
        return str(decision.get("reason") or "").strip()
    return str(decision or "").strip()


def _approval_id_from_decision(decision: dict[str, Any] | str | None) -> str:
    if not isinstance(decision, dict):
        return ""
    metadata = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
    return str(decision.get("approval_id") or metadata.get("approval_id") or "").strip()


def _assert_matching_pending_approval(
    run: dict[str, Any],
    requested_approval_id: str,
) -> None:
    if not requested_approval_id:
        return
    pending = run.get("pending_approval")
    pending_approval_id = ""
    if isinstance(pending, dict):
        pending_approval_id = str(pending.get("approval_id") or "").strip()
    if pending_approval_id == requested_approval_id:
        return
    run_id = str(run.get("run_id") or "").strip()
    raise AgentRuntimeError(
        "审批 ID 与当前待审批项不匹配"
        f"：{requested_approval_id}"
        f"{f' for run {run_id}' if run_id else ''}"
    )


def _planner_metadata_with_desktop_readiness(metadata: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(metadata or {})
    enriched.setdefault("runtime_planner_request_trace", True)
    if not isinstance(enriched.get("desktop_missing_permissions_by_capability"), dict):
        try:
            missing_permissions = desktop_permission_missing_by_capability()
        except Exception:
            missing_permissions = {"desktop_execution": ["permission_probe_failed"]}
        if missing_permissions:
            enriched["desktop_missing_permissions_by_capability"] = missing_permissions
    if not isinstance(enriched.get("desktop_blocking_conditions_by_capability"), dict):
        try:
            blocking_conditions = desktop_runtime_blocking_conditions_by_capability()
        except Exception:
            blocking_conditions = {}
        if blocking_conditions:
            enriched["desktop_blocking_conditions_by_capability"] = blocking_conditions
    return enriched


def _chat_runtime_execution_kwargs(
    request: dict[str, Any],
    *,
    metadata: dict[str, Any],
    prompt: str,
    planner_decision: Any | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    request_allowed_tools = _request_allowed_tools(request)
    planner_metadata = (
        runtime_planner_metadata(
            planner_decision,
            allowed_tools=request_allowed_tools,
        )
        if planner_decision is not None
        else {}
    )
    effective_metadata = {**planner_metadata, **dict(metadata)}
    envelope = request.get("runtime_execution_envelope")
    if envelope is None and isinstance(
        effective_metadata.get("yachiyo_execution_envelope"),
        dict,
    ):
        envelope = effective_metadata.get("yachiyo_execution_envelope")
    if envelope is not None:
        kwargs["runtime_execution_envelope"] = envelope
    if effective_metadata and (
        effective_metadata.get("yachiyo_runtime_planner") is True
        or isinstance(effective_metadata.get("yachiyo_execution_envelope"), dict)
    ):
        kwargs["metadata"] = dict(effective_metadata)

    direct_requests = _request_direct_tool_requests(request)
    if not direct_requests:
        direct_requests = runtime_execution_requests_from_envelope_payload(
            envelope,
            allowed_tools=request_allowed_tools,
        )
    if not direct_requests:
        direct_requests = runtime_execution_requests_from_metadata(
            effective_metadata,
            allowed_tools=request_allowed_tools,
        )
    if direct_requests:
        kwargs["direct_tool_requests"] = direct_requests

    if kwargs or effective_metadata.get("yachiyo_runtime_planner") is True:
        kwargs["runtime_planner_entrypoint"] = True
        planning_context = str(
            request.get("daily_desktop_planning_context") or prompt or ""
        ).strip()
        if planning_context:
            kwargs["daily_desktop_planning_context"] = planning_context
    if _should_apply_daily_desktop_overlay(metadata, direct_requests):
        kwargs["daily_desktop_policy_overlay"] = True
    return kwargs


def _runnable_chat_execution_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return dict(kwargs)


def _request_direct_tool_requests(request: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    direct_tool_request = request.get("direct_tool_request")
    if isinstance(direct_tool_request, dict):
        requests.append(dict(direct_tool_request))
    direct_tool_requests = request.get("direct_tool_requests")
    if isinstance(direct_tool_requests, list):
        requests.extend(
            dict(item)
            for item in direct_tool_requests
            if isinstance(item, dict)
        )
    return [
        {**item, "tool": str(item.get("tool") or item.get("tool_name") or "").strip()}
        for item in requests
        if str(item.get("tool") or item.get("tool_name") or "").strip()
    ]


def _request_allowed_tools(request: dict[str, Any]) -> list[str] | None:
    allowed_tools = request.get("allowed_tools")
    if not isinstance(allowed_tools, list):
        return None
    tools = [
        str(tool or "").strip()
        for tool in allowed_tools
        if str(tool or "").strip()
    ]
    return tools or None


def _should_apply_daily_desktop_overlay(
    metadata: dict[str, Any],
    direct_requests: list[dict[str, Any]],
) -> bool:
    intent_kind = str(metadata.get("yachiyo_intent_kind") or "").strip()
    if intent_kind in {
        "desktop_operation",
        "media_playback",
        "system_control",
        "clipboard_operation",
        "web_research",
        "information_capture",
        "communication",
        "schedule",
    }:
        return True
    return any(
        str(request.get("tool") or "").strip().startswith(
            ("app.", "desktop.", "media.", "browser.")
        )
        for request in direct_requests
    )


def _call_with_supported_kwargs(callable_obj: Any, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        callable_signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(**payload)
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in callable_signature.parameters.values()
    ):
        return callable_obj(**payload)
    supported_payload = {
        key: value
        for key, value in payload.items()
        if key in callable_signature.parameters
    }
    return callable_obj(**supported_payload)


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
        try:
            from apps.shell.agent.tools import KNOWN_AGENT_TOOLS
        except Exception:
            known_tools = set()
        else:
            known_tools = set(KNOWN_AGENT_TOOLS)
        try:
            missing_permissions = desktop_permission_missing_by_capability()
        except Exception:
            missing_permissions = {"desktop_execution": ["permission_probe_failed"]}
        try:
            blocking_conditions = desktop_runtime_blocking_conditions_by_capability()
        except Exception:
            blocking_conditions = {}
        return {
            "ok": True,
            "status": "ready",
            "capabilities": {
                "tasks": True,
                "runnables": len(payload.get("runnables") or []),
                **desktop_execution_capability_snapshots(
                    registered_tools=known_tools,
                    missing_permissions=missing_permissions,
                    blocking_conditions=blocking_conditions,
                ),
            },
        }

    def list_runnable_catalog(self) -> dict[str, Any]:
        return {
            "agents": self._payload_items(self._runtime.list_agents(), "agents"),
            "workflows": self._payload_items(self._runtime.list_workflows(), "workflows"),
            "groups": self._list_groups_for_catalog(),
        }

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = str(request.get("prompt") or request.get("goal") or "").strip()
        workflow_id = str(request.get("workflow_id") or "").strip()
        group_id = str(request.get("group_id") or request.get("agent_group_id") or "").strip()
        runnable_id = str(
            request.get("agent_id") or request.get("runnable_id") or MAIN_CHAT_AGENT_ID
        )
        conversation_id = str(request.get("conversation_id") or "").strip()
        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        planner_metadata = _planner_metadata_with_desktop_readiness(metadata)
        planner_decision = runtime_planner_decision(prompt, metadata=planner_metadata)
        execution_kwargs = _chat_runtime_execution_kwargs(
            request,
            metadata=metadata,
            prompt=prompt,
            planner_decision=planner_decision,
        )
        requested_task_id = str(
            request.get("task_id")
            or request.get("client_task_id")
            or metadata.get("task_id")
            or metadata.get("client_task_id")
            or ""
        ).strip()
        if group_id:
            return self._start_group_chat_task(
                request,
                group_id=group_id,
                prompt=prompt,
                conversation_id=conversation_id,
                metadata=metadata,
                execution_kwargs=execution_kwargs,
                requested_task_id=requested_task_id,
            )
        if workflow_id:
            run = self._runtime.create_workflow_run(
                {
                    "workflow_id": workflow_id,
                    "user_goal": prompt,
                    "source": "yachiyo_chat",
                    "client_run_id": request.get("client_run_id") or requested_task_id or None,
                    **execution_kwargs,
                }
            )
        else:
            create_run = getattr(self._runtime, "create_run_for_runnable_async", None)
            run_payload = {
                "runnable_id": runnable_id,
                "user_goal": prompt,
                **_runnable_chat_execution_kwargs(execution_kwargs),
            }
            if callable(create_run):
                run = _call_with_supported_kwargs(create_run, run_payload)
            else:
                run = _call_with_supported_kwargs(
                    self._runtime.create_run_for_runnable,
                    run_payload,
                )
        run_id = str(run.get("run_id") or "").strip()
        self._append_planner_run_events(run_id, planner_decision)
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
        if workflow_id:
            workflow_payload = self._workflow_chat_task_payload(task_id, run)
            if workflow_payload is not None:
                return self._projector.chat_task_payload(
                    workflow_payload,
                    conversation_id=conversation_id,
                    runtime=self._runtime,
                )
        return self._projector.chat_task_payload(
            run,
            conversation_id=conversation_id,
            runtime=self._runtime,
        )

    def _start_group_chat_task(
        self,
        request: dict[str, Any],
        *,
        group_id: str,
        prompt: str,
        conversation_id: str,
        metadata: dict[str, Any],
        execution_kwargs: dict[str, Any],
        requested_task_id: str,
    ) -> dict[str, Any]:
        group_request = {
            **request,
            "group_id": group_id,
            "objective": prompt,
            "goal": prompt,
            "title": request.get("title") or prompt,
            "client_run_id": request.get("client_run_id") or requested_task_id or None,
            **execution_kwargs,
        }
        start_agent_group_run = getattr(self._runtime, "start_agent_group_run", None)
        if callable(start_agent_group_run):
            group_run = start_agent_group_run(group_request)
        else:
            group_run = start_legacy_group_run(
                self._runtime,
                group_request,
                get_group=self._get_group_for_run,
                projector=self._projector,
            )

        run_group_id = str(
            group_run.get("run_group_id") or group_run.get("group_run_id") or ""
        ).strip()
        run_id = self._first_group_child_run_id(group_run) or run_group_id
        task_id = requested_task_id or run_id or run_group_id
        if task_id and run_id:
            link_task_run = getattr(self._runtime, "link_task_run", None)
            if callable(link_task_run):
                try:
                    link_task_run(task_id=task_id, run_id=run_id, session_id=conversation_id)
                except Exception:
                    pass

        pending_approvals = [
            dict(item)
            for item in group_run.get("pending_approvals") or []
            if isinstance(item, dict)
        ]
        status = str(group_run.get("status") or "running").strip()
        if pending_approvals and status in {"", "queued", "running", "processing"}:
            status = "approval_required"
        payload = {
            **group_run,
            "run_id": run_id,
            "task_id": task_id,
            "session_id": conversation_id,
            "conversation_id": conversation_id,
            "user_goal": prompt,
            "status": status,
            "summary": group_run.get("summary") or group_run.get("final_answer") or "",
            "artifacts": group_run.get("artifacts") or group_run.get("shared_artifacts") or [],
            "pending_approvals": pending_approvals,
            "pending_approval": pending_approvals[0] if pending_approvals else None,
            "metadata": {
                **dict(metadata),
                "runnable_kind": "group",
                "group_id": group_id,
                "group_run_id": group_run.get("group_run_id") or run_group_id,
                "run_group_id": run_group_id,
            },
        }
        return self._projector.chat_task_payload(
            payload,
            conversation_id=conversation_id,
            runtime=self._runtime,
        )

    def _append_planner_run_events(self, run_id: str, planner_decision: Any | None) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not callable(append_run_event):
            return
        for event_type, payload in planner_run_event_payloads(planner_decision):
            try:
                append_run_event(run_id, event_type, payload)
            except Exception:
                continue

    def get_task_snapshot(self, task_id: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        payload = self._payload_with_task_link(task_id, self._runtime.get_run(run_id))
        group_payload = self._group_chat_task_payload(task_id, payload)
        if group_payload is not None:
            return self._projector.chat_task_payload(
                group_payload,
                runtime=self._runtime,
            )
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        if workflow_payload is not None:
            return self._projector.chat_task_payload(
                workflow_payload,
                runtime=self._runtime,
            )
        if not payload.get("task_id"):
            payload = {**payload, "task_id": task_id}
        return self._projector.chat_task_payload(
            payload,
            runtime=self._runtime,
        )

    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        payload = self._payload_with_task_link(task_id, self._runtime.get_run(run_id))
        group_payload = self._group_chat_task_payload(task_id, payload)
        if group_payload is not None:
            return group_payload
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        if workflow_payload is not None:
            return workflow_payload
        if not payload.get("task_id"):
            payload = {**payload, "task_id": task_id}
        events = self._projector.chat_events_for_run(payload, self._runtime)
        if events:
            payload = {**payload, "events": events}
        return payload

    def get_task_event_stream(self, task_id: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        try:
            payload = self._payload_with_task_link(task_id, self._runtime.get_run(run_id))
        except KeyError:
            payload = {}
        group_payload = self._group_chat_task_payload(task_id, payload)
        if group_payload is not None:
            group_run_id = str(
                group_payload.get("group_run_id") or group_payload.get("run_group_id") or ""
            ).strip()
            list_group_run_events = getattr(self._runtime, "list_group_run_events", None)
            if group_run_id and callable(list_group_run_events):
                stream = list_group_run_events(group_run_id, limit=500)
                if isinstance(stream, dict):
                    return {
                        **stream,
                        "run_id": stream.get("run_id") or group_run_id,
                        "task_id": stream.get("task_id") or task_id,
                        "group_run_id": stream.get("group_run_id") or group_run_id,
                        "run_group_id": stream.get("run_group_id") or group_run_id,
                    }
            return {
                "run_id": group_run_id or run_id,
                "task_id": task_id,
                "group_run_id": group_run_id,
                "run_group_id": group_run_id,
                "events": list(group_payload.get("events") or []),
            }
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        if workflow_payload is not None:
            workflow_run_id = str(
                workflow_payload.get("workflow_run_id") or workflow_payload.get("run_id") or run_id
            ).strip()
            return {
                "run_id": workflow_run_id or run_id,
                "task_id": task_id,
                "workflow_run_id": workflow_run_id or None,
                "run_group_id": workflow_payload.get("run_group_id"),
                "events": list(workflow_payload.get("events") or []),
            }
        list_run_events = getattr(self._runtime, "list_run_events", None)
        if callable(list_run_events):
            payload = list_run_events(run_id)
            if isinstance(payload, dict):
                return {**payload, "run_id": payload.get("run_id") or run_id}
            return {"run_id": run_id, "events": payload if isinstance(payload, list) else []}
        run = self._runtime.get_run(run_id)
        return {"run_id": run_id, "events": run.get("timeline") or []}

    def get_task_event_page(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        clean_after_sequence = max(0, int(after_sequence or 0))
        clean_limit = max(1, min(500, int(limit or 200)))
        try:
            payload = self._payload_with_task_link(task_id, self._runtime.get_run(run_id))
        except KeyError:
            payload = {}
        group_payload = self._group_chat_task_payload(task_id, payload)
        if group_payload is not None:
            group_run_id = str(
                group_payload.get("group_run_id") or group_payload.get("run_group_id") or ""
            ).strip()
            list_group_run_events = getattr(self._runtime, "list_group_run_events", None)
            if group_run_id and callable(list_group_run_events):
                page = list_group_run_events(
                    group_run_id,
                    after_sequence=clean_after_sequence,
                    limit=clean_limit,
                )
                if isinstance(page, dict):
                    return {
                        **page,
                        "run_id": page.get("run_id") or group_run_id,
                        "task_id": page.get("task_id") or task_id,
                        "group_run_id": page.get("group_run_id") or group_run_id,
                        "run_group_id": page.get("run_group_id") or group_run_id,
                        "after_sequence": page.get("after_sequence", clean_after_sequence),
                        "limit": page.get("limit", clean_limit),
                    }
            return self._event_page_from_events(
                group_payload.get("events"),
                run_id=group_run_id or run_id,
                task_id=task_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
                group_run_id=group_run_id,
            )
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        if workflow_payload is not None:
            workflow_run_id = str(
                workflow_payload.get("workflow_run_id") or workflow_payload.get("run_id") or run_id
            ).strip()
            page = self._event_page_from_events(
                workflow_payload.get("events"),
                run_id=workflow_run_id or run_id,
                task_id=task_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            return {
                **page,
                "workflow_run_id": workflow_run_id or None,
                "run_group_id": workflow_payload.get("run_group_id"),
            }
        get_run_event_page = getattr(self._runtime, "get_run_event_page", None)
        if callable(get_run_event_page):
            payload = get_run_event_page(
                run_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            if isinstance(payload, dict):
                return {
                    **payload,
                    "run_id": payload.get("run_id") or run_id,
                    "after_sequence": payload.get("after_sequence", clean_after_sequence),
                    "limit": payload.get("limit", clean_limit),
                }

        stream = self.get_task_event_stream(task_id)
        raw_events = stream.get("events") if isinstance(stream, dict) else []
        events = [
            dict(event)
            for event in raw_events or []
            if isinstance(event, dict)
        ]
        filtered_events = []
        for index, event in enumerate(events):
            event_sequence = self._event_sequence(event, index)
            if event_sequence > clean_after_sequence:
                filtered_events.append((event_sequence, event))
        page_pairs = filtered_events[:clean_limit]
        page = [event for _, event in page_pairs]
        next_after_sequence = max(
            [sequence for sequence, _ in page_pairs] or [clean_after_sequence]
        )
        stream_run_id = stream.get("run_id") if isinstance(stream, dict) else ""
        return {
            "run_id": stream_run_id or run_id,
            "after_sequence": clean_after_sequence,
            "limit": clean_limit,
            "next_after_sequence": next_after_sequence,
            "has_more": len(filtered_events) > clean_limit,
            "events": page,
        }

    def read_task_artifact(self, task_id: str, artifact_path: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        try:
            task_payload = self._payload_with_task_link(task_id, self._runtime.get_run(run_id))
        except KeyError:
            task_payload = {}
        group_payload = self._group_chat_task_payload(task_id, task_payload)
        workflow_payload = self._workflow_chat_task_payload(task_id, task_payload)
        artifact_run_id = (
            self._workflow_artifact_source_run_id(workflow_payload, artifact_path)
            or self._group_artifact_source_run_id(group_payload, artifact_path)
            or run_id
        )
        payload = self._runtime.read_run_artifact(artifact_run_id, artifact_path)
        return {
            **payload,
            "run_id": payload.get("run_id") or artifact_run_id,
            "task_id": payload.get("task_id") or task_id,
            "workflow_run_id": payload.get("workflow_run_id")
            or (workflow_payload or {}).get("workflow_run_id"),
            "workflow_id": payload.get("workflow_id")
            or (workflow_payload or {}).get("workflow_id"),
            "group_run_id": payload.get("group_run_id")
            or (group_payload or {}).get("group_run_id"),
            "run_group_id": payload.get("run_group_id")
            or (workflow_payload or {}).get("run_group_id")
            or (group_payload or {}).get("run_group_id"),
            "path": payload.get("path") or artifact_path,
        }

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
                runtime=self._runtime,
            )
            for run in runs
        ]

    def approve(self, task_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = self._run_id_for_task_approval(task_id, decision)
        self._assert_task_approval(run_id, decision)
        approved = self._run_action_payload(run_id, self._runtime.approve_run_approval(run_id))
        approved = self._complete_main_chat_daily_desktop_approval_if_ready(run_id, approved)
        payload = self._payload_with_task_link(task_id, approved)
        group_payload = self._group_chat_task_payload(task_id, payload)
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        return self._projector.chat_task_payload(
            group_payload or workflow_payload or payload,
            runtime=self._runtime,
        )

    def reject(self, task_id: str, decision: dict[str, Any] | str | None = None) -> dict[str, Any]:
        run_id = self._run_id_for_task_approval(task_id, decision)
        self._assert_task_approval(run_id, decision)
        reason = _rejection_reason(decision)
        payload = self._payload_with_task_link(
            task_id,
            self._run_action_payload(
                run_id,
                self._runtime.reject_run_approval(run_id, reason),
            ),
        )
        group_payload = self._group_chat_task_payload(task_id, payload)
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        return self._projector.chat_task_payload(
            group_payload or workflow_payload or payload,
            runtime=self._runtime,
        )

    def cancel(self, task_id: str) -> dict[str, Any]:
        run_id = self._run_id_for_task(task_id)
        payload = self._payload_with_task_link(
            task_id,
            self._run_action_payload(run_id, self._runtime.cancel_run(run_id)),
        )
        group_payload = self._group_chat_task_payload(task_id, payload)
        workflow_payload = self._workflow_chat_task_payload(task_id, payload)
        return self._projector.chat_task_payload(
            group_payload or workflow_payload or payload,
            runtime=self._runtime,
        )

    def _assert_task_approval(
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

    def _run_id_for_task_approval(
        self,
        task_id: str,
        decision: dict[str, Any] | str | None,
    ) -> str:
        run_id = self._run_id_for_task(task_id)
        requested_approval_id = _approval_id_from_decision(decision)
        if not requested_approval_id:
            return run_id
        try:
            run = self._runtime.get_run(run_id)
        except KeyError:
            return run_id
        if self._payload_pending_approval_id(run) == requested_approval_id:
            return run_id
        for child in self._group_child_runs_for_run(run):
            child_run_id = str(child.get("run_id") or "").strip()
            if child_run_id and self._payload_pending_approval_id(child) == requested_approval_id:
                return child_run_id
        for child in self._workflow_child_runs_for_run(run):
            child_run_id = str(child.get("run_id") or "").strip()
            if child_run_id and self._payload_pending_approval_id(child) == requested_approval_id:
                return child_run_id
        return run_id

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

    def _group_chat_task_payload(
        self,
        task_id: str,
        run: dict[str, Any],
    ) -> dict[str, Any] | None:
        run_group_id = str(run.get("run_group_id") or run.get("group_run_id") or "").strip()
        if not run_group_id:
            return None
        group_run = self._group_run_payload_for_task(run_group_id)
        if (
            group_run is None
            or self._is_workflow_run_group_payload(group_run)
            or not self._is_agent_group_run_payload(group_run)
        ):
            return None

        events = list(group_run.get("events") or [])
        shared_artifacts = list(group_run.get("shared_artifacts") or [])
        pending_approvals = [
            dict(item)
            for item in group_run.get("pending_approvals") or []
            if isinstance(item, dict)
        ]
        status = str(group_run.get("status") or run.get("status") or "running").strip()
        if pending_approvals and status in {"", "queued", "running", "processing"}:
            status = "approval_required"
        group_id = str(group_run.get("group_id") or "").strip()
        metadata = dict(run.get("metadata")) if isinstance(run.get("metadata"), dict) else {}
        metadata.update(
            {
                "runnable_kind": "group",
                "group_id": group_id,
                "group_run_id": run_group_id,
                "run_group_id": run_group_id,
            }
        )
        run_id = str(run.get("run_id") or "").strip() or self._first_group_child_run_id(group_run)
        return {
            **group_run,
            "run_id": run_id or run_group_id,
            "task_id": task_id,
            "session_id": run.get("session_id") or run.get("conversation_id") or "",
            "conversation_id": run.get("conversation_id") or run.get("session_id") or "",
            "user_goal": group_run.get("objective") or run.get("user_goal") or "",
            "title": group_run.get("title") or run.get("user_goal") or "Group run",
            "status": status,
            "summary": group_run.get("summary") or group_run.get("final_answer") or run.get("summary") or "",
            "events": events,
            "recent_events": events,
            "timeline": events,
            "artifacts": shared_artifacts or run.get("artifacts") or [],
            "pending_approvals": pending_approvals,
            "pending_approval": run.get("pending_approval")
            or (pending_approvals[0] if pending_approvals else None),
            "metadata": metadata,
        }

    def _group_run_payload_for_task(self, run_group_id: str) -> dict[str, Any] | None:
        try:
            run_group = self._runtime.get_run_group(run_group_id)
        except (KeyError, AttributeError):
            return None
        if not isinstance(run_group, dict):
            return None
        return self._projector.group_run_from_legacy_run_group(run_group, self._runtime)

    def _is_agent_group_run_payload(self, group_run: dict[str, Any]) -> bool:
        if str(group_run.get("group_id") or "").strip():
            return True
        for event in group_run.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type") or event.get("event") or "").strip()
            if event_type.startswith("group."):
                return True
        return False

    def _is_workflow_run_group_payload(self, group_run: dict[str, Any]) -> bool:
        if str(group_run.get("group_id") or "").strip():
            return False
        if str(group_run.get("source") or "").strip() == "workflow":
            return True
        return any(
            isinstance(run, dict) and self._is_workflow_parent_run(run)
            for run in group_run.get("runs") or []
        )

    def _group_child_runs_for_run(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        run_group_id = str(run.get("run_group_id") or run.get("group_run_id") or "").strip()
        if not run_group_id:
            return []
        group_run = self._group_run_payload_for_task(run_group_id)
        if (
            group_run is None
            or self._is_workflow_run_group_payload(group_run)
            or not self._is_agent_group_run_payload(group_run)
        ):
            return []
        return [dict(item) for item in group_run.get("runs") or [] if isinstance(item, dict)]

    def _workflow_chat_task_payload(
        self,
        task_id: str,
        run: dict[str, Any],
    ) -> dict[str, Any] | None:
        parent = self._workflow_parent_run_for_run(run)
        if parent is None:
            return None
        parent_run_id = str(parent.get("run_id") or parent.get("workflow_run_id") or "").strip()
        if not parent_run_id:
            return None
        parent = self._payload_with_task_link(task_id, parent)
        workflow_events = self._projector.chat_events_for_run(parent, self._runtime)
        child_runs = self._workflow_child_runs_for_parent(parent, events=workflow_events)
        workflow_events = self._workflow_events_with_child_replay(
            parent,
            workflow_events,
            child_runs,
        )
        workflow_payload = {
            **parent,
            "run_id": parent_run_id,
            "workflow_run_id": parent.get("workflow_run_id") or parent_run_id,
            "workflow_id": parent.get("workflow_id") or parent.get("runnable_id") or "",
            "events": workflow_events or parent.get("events") or parent.get("timeline") or [],
            "runs": child_runs,
        }
        snapshot = workflow_run_snapshot_from_payload(workflow_payload).model_dump(mode="python")
        approvals = [
            dict(item)
            for item in snapshot.get("approvals") or []
            if isinstance(item, dict)
        ]
        pending = snapshot.get("pending_approval")
        if isinstance(pending, dict):
            pending_id = str(pending.get("approval_id") or "").strip()
            pending_run_id = str(pending.get("run_id") or "").strip()
            approvals = [
                dict(pending),
                *[
                    item
                    for item in approvals
                    if str(item.get("approval_id") or "").strip() != pending_id
                    or str(item.get("run_id") or "").strip() != pending_run_id
                ],
            ]
        pending_approvals = [
            dict(item)
            for item in approvals
            if str(item.get("status") or "pending") == "pending"
        ]
        status = str(snapshot.get("status") or parent.get("status") or "running").strip()
        if pending_approvals and status in {"", "queued", "running", "processing"}:
            status = "approval_required"
        session_id = str(parent.get("session_id") or parent.get("conversation_id") or "").strip()
        metadata = dict(parent.get("metadata")) if isinstance(parent.get("metadata"), dict) else {}
        metadata.update(
            {
                "runnable_kind": "workflow",
                "workflow_id": snapshot.get("workflow_id") or workflow_payload.get("workflow_id"),
                "workflow_run_id": snapshot.get("workflow_run_id") or parent_run_id,
            }
        )
        run_group_id = str(snapshot.get("run_group_id") or snapshot.get("group_run_id") or "").strip()
        if run_group_id:
            metadata["run_group_id"] = run_group_id
        return {
            **snapshot,
            "run_id": parent_run_id,
            "kind": "workflow_run",
            "workflow_id": snapshot.get("workflow_id") or workflow_payload.get("workflow_id"),
            "workflow_run_id": snapshot.get("workflow_run_id") or parent_run_id,
            "task_id": task_id,
            "session_id": session_id,
            "conversation_id": session_id,
            "user_goal": parent.get("user_goal") or snapshot.get("objective") or "",
            "title": parent.get("title") or parent.get("user_goal") or snapshot.get("objective") or "Workflow run",
            "status": status,
            "summary": snapshot.get("final_answer") or parent.get("summary") or parent.get("result") or "",
            "events": snapshot.get("events") or [],
            "recent_events": snapshot.get("events") or [],
            "timeline": snapshot.get("events") or [],
            "artifacts": snapshot.get("artifacts") or [],
            "approvals": approvals,
            "pending_approvals": pending_approvals,
            "pending_approval": pending if isinstance(pending, dict) else None,
            "metadata": metadata,
        }

    def _workflow_parent_run_for_run(self, run: dict[str, Any]) -> dict[str, Any] | None:
        if self._is_workflow_parent_run(run):
            return dict(run)
        workflow_run_id = str(run.get("workflow_run_id") or "").strip()
        run_id = str(run.get("run_id") or "").strip()
        if workflow_run_id and workflow_run_id != run_id:
            try:
                parent = self._runtime.get_run(workflow_run_id)
            except KeyError:
                parent = None
            if isinstance(parent, dict) and self._is_workflow_parent_run(parent):
                return parent
        run_group_id = str(run.get("run_group_id") or run.get("group_run_id") or "").strip()
        if not run_group_id:
            return None
        for candidate in self._run_group_runs(run_group_id):
            if self._is_workflow_parent_run(candidate):
                return candidate
        return None

    def _is_workflow_parent_run(self, run: dict[str, Any]) -> bool:
        run_id = str(run.get("run_id") or "").strip()
        workflow_run_id = str(run.get("workflow_run_id") or "").strip()
        return str(run.get("kind") or "").strip() == "workflow_run" or bool(
            workflow_run_id and workflow_run_id == run_id
        )

    def _workflow_child_runs_for_run(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        parent = self._workflow_parent_run_for_run(run)
        if parent is None:
            return []
        return self._workflow_child_runs_for_parent(parent)

    def _workflow_child_runs_for_parent(
        self,
        parent: dict[str, Any],
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        parent_run_id = str(parent.get("run_id") or parent.get("workflow_run_id") or "").strip()
        raw_children = self._explicit_workflow_child_runs(parent)
        run_group_id = str(parent.get("run_group_id") or parent.get("group_run_id") or "").strip()
        if run_group_id:
            raw_children.extend(self._run_group_runs(run_group_id))
        context_by_child = self._workflow_child_context_by_run_id(parent, events=events)
        workflow_id = str(parent.get("workflow_id") or parent.get("runnable_id") or "").strip()
        children: list[dict[str, Any]] = []
        seen: set[str] = set()
        for child in raw_children:
            child_run_id = str(child.get("run_id") or "").strip()
            if not child_run_id or child_run_id == parent_run_id or child_run_id in seen:
                continue
            seen.add(child_run_id)
            child_payload = self._projector.child_run_payload(dict(child), self._runtime)
            child_payload.setdefault("workflow_id", workflow_id)
            child_payload.setdefault("workflow_run_id", parent_run_id)
            child_payload.setdefault("parent_run_id", parent_run_id)
            context = context_by_child.get(child_run_id) or {}
            for key, value in context.items():
                if value and not child_payload.get(key):
                    child_payload[key] = value
            children.append(child_payload)
        return children

    def _explicit_workflow_child_runs(self, parent: dict[str, Any]) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        for key in ("runs", "child_runs", "children"):
            value = parent.get(key)
            if not isinstance(value, list):
                continue
            children.extend(dict(item) for item in value if isinstance(item, dict))
        return children

    def _run_group_runs(self, run_group_id: str) -> list[dict[str, Any]]:
        try:
            run_group = self._runtime.get_run_group(run_group_id)
        except (KeyError, AttributeError):
            return []
        if not isinstance(run_group, dict):
            return []
        runs = [
            dict(item)
            for item in run_group.get("runs") or run_group.get("child_runs") or []
            if isinstance(item, dict)
        ]
        seen = {str(item.get("run_id") or "") for item in runs if str(item.get("run_id") or "")}
        for run_id in run_group.get("child_run_ids") or []:
            clean_run_id = str(run_id or "").strip()
            if not clean_run_id or clean_run_id in seen:
                continue
            try:
                runs.append(dict(self._runtime.get_run(clean_run_id)))
                seen.add(clean_run_id)
            except KeyError:
                continue
        return runs

    def _workflow_child_context_by_run_id(
        self,
        parent: dict[str, Any],
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, str]]:
        raw_events = events
        if raw_events is None:
            raw_events = self._projector.chat_events_for_run(parent, self._runtime)
        context: dict[str, dict[str, str]] = {}
        for event in raw_events or []:
            if not isinstance(event, dict):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            child_run_id = str(
                payload.get("child_run_id")
                or payload.get("child_agent_run_id")
                or event.get("child_run_id")
                or event.get("child_agent_run_id")
                or ""
            ).strip()
            if not child_run_id:
                continue
            item: dict[str, str] = {}
            for key in (
                "workflow_node_id",
                "workflow_node_kind",
                "workflow_node_label",
                "workflow_parent_node_id",
                "workflow_parent_node_kind",
                "workflow_parent_node_label",
                "workflow_parallel_branch_entry_node_id",
                "workflow_parallel_branch_label",
            ):
                value = str(payload.get(key) or event.get(key) or "").strip()
                if value:
                    item[key] = value
            if item:
                context.setdefault(child_run_id, {}).update(item)
        return context

    def _workflow_events_with_child_replay(
        self,
        parent: dict[str, Any],
        parent_events: list[dict[str, Any]],
        child_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        parent_run_id = str(parent.get("run_id") or parent.get("workflow_run_id") or "").strip()
        if not parent_run_id:
            return parent_events
        workflow_id = str(parent.get("workflow_id") or parent.get("runnable_id") or "").strip()
        context_by_child = self._workflow_child_context_by_run_id(
            parent,
            events=parent_events,
        )
        events = [dict(event) for event in parent_events if isinstance(event, dict)]
        for child in child_runs:
            child_run_id = str(child.get("run_id") or "").strip()
            if not child_run_id:
                continue
            context = context_by_child.get(child_run_id) or {}
            for event in self._events_from_payload(child):
                events.append(
                    self._workflow_child_replay_event(
                        event,
                        parent_run_id=parent_run_id,
                        workflow_id=workflow_id,
                        child_run_id=child_run_id,
                        context=context,
                    )
                )
        return self._resequence_events(events)

    def _workflow_child_replay_event(
        self,
        event: dict[str, Any],
        *,
        parent_run_id: str,
        workflow_id: str,
        child_run_id: str,
        context: dict[str, str],
    ) -> dict[str, Any]:
        item = dict(event)
        payload = dict(item.get("payload")) if isinstance(item.get("payload"), dict) else {}
        source_sequence = str(item.get("sequence") or "").strip()
        source_event_id = str(item.get("event_id") or "").strip()
        payload.setdefault("source_run_id", child_run_id)
        if source_sequence:
            payload.setdefault("source_sequence", source_sequence)
        if source_event_id:
            payload.setdefault("source_event_id", source_event_id)
        if workflow_id:
            payload.setdefault("workflow_id", workflow_id)
        payload.setdefault("workflow_run_id", parent_run_id)
        for key, value in context.items():
            if value:
                payload.setdefault(key, value)
        item["run_id"] = parent_run_id
        item["payload"] = payload
        return item

    def _events_from_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("events", "run_events", "recent_events", "timeline"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                return [dict(item) for item in value if isinstance(item, dict)]
        return []

    def _resequence_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resequenced = []
        for index, event in enumerate(events, start=1):
            resequenced.append({**event, "sequence": index})
        return resequenced

    def _payload_pending_approval_id(self, payload: dict[str, Any]) -> str:
        pending = payload.get("pending_approval")
        if isinstance(pending, dict):
            return str(pending.get("approval_id") or "").strip()
        for item in payload.get("pending_approvals") or []:
            if not isinstance(item, dict):
                continue
            approval_id = str(item.get("approval_id") or "").strip()
            if approval_id:
                return approval_id
        return ""

    def _group_artifact_source_run_id(
        self,
        group_payload: dict[str, Any] | None,
        artifact_path: str,
    ) -> str:
        if not isinstance(group_payload, dict):
            return ""
        clean_path = str(artifact_path or "").strip()
        for artifact in group_payload.get("artifacts") or group_payload.get("shared_artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            if str(artifact.get("path") or "").strip() != clean_path:
                continue
            source_run_id = str(artifact.get("source_run_id") or "").strip()
            if source_run_id:
                return source_run_id
        return ""

    def _workflow_artifact_source_run_id(
        self,
        workflow_payload: dict[str, Any] | None,
        artifact_path: str,
    ) -> str:
        if not isinstance(workflow_payload, dict):
            return ""
        clean_path = str(artifact_path or "").strip()
        for artifact in workflow_payload.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            if str(artifact.get("path") or "").strip() != clean_path:
                continue
            source_run_id = str(artifact.get("source_run_id") or artifact.get("run_id") or "").strip()
            if source_run_id:
                return source_run_id
        return ""

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

    def _run_action_payload(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("kind") and payload.get("workflow_run_id"):
            return payload
        try:
            existing = self._runtime.get_run(run_id)
        except KeyError:
            return payload
        merged = {**payload, "run_id": payload.get("run_id") or existing.get("run_id")}
        preserve_workflow_identity = (
            existing.get("kind") == "workflow_run"
            and payload.get("kind") != "workflow_run"
        )
        for key in (
            "kind",
            "workflow_id",
            "workflow_run_id",
            "workflow_node_id",
            "workflow_node_label",
            "run_group_id",
            "group_run_id",
            "runnable_id",
            "runnable_name",
        ):
            if existing.get(key) and (preserve_workflow_identity or not merged.get(key)):
                merged[key] = existing[key]
        return merged

    def _complete_main_chat_daily_desktop_approval_if_ready(
        self,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if str(payload.get("kind") or "").strip() != "main_chat_run":
            return payload
        if str(payload.get("status") or "").strip() not in {"running", "processing"}:
            return payload
        if payload.get("pending_approval"):
            return payload
        result_text = str(payload.get("result") or "").strip()
        if not result_text:
            return payload
        if not self._has_daily_desktop_intent_completed(payload):
            return payload
        complete_main_chat_run = getattr(self._runtime, "complete_main_chat_run", None)
        if not callable(complete_main_chat_run):
            return payload
        completed = complete_main_chat_run(run_id, result_text)
        if not isinstance(completed, dict):
            return payload
        return self._run_action_payload(run_id, completed)

    def _has_daily_desktop_intent_completed(self, payload: dict[str, Any]) -> bool:
        if _has_runtime_planner_desktop_tool_completion(payload):
            return True
        for event in payload.get("timeline") or []:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type") or event.get("event") or "").strip()
            if event_type != "agent.desktop.intent_completed":
                continue
            event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            source = str(event.get("source") or event_payload.get("source") or "").strip()
            if source in {"daily_desktop_intent", "runtime_planner", "daily_desktop_metadata"}:
                return True
        return False

    def _payload_items(self, payload: Any, key: str) -> list[dict[str, Any]]:
        items = payload.get(key) if isinstance(payload, dict) else payload
        return [dict(item) for item in items or [] if isinstance(item, dict)]

    def _list_groups_for_catalog(self) -> list[dict[str, Any]]:
        list_agent_groups = getattr(self._runtime, "list_agent_groups", None)
        if callable(list_agent_groups):
            return self._payload_items(list_agent_groups(), "groups")

        chat_groups = chat_group_snapshots(self._runtime)
        if chat_groups:
            return chat_groups

        list_run_groups = getattr(self._runtime, "list_run_groups", None)
        if callable(list_run_groups):
            payload = list_run_groups(50)
            return [
                group_definition_from_run_group(item, self._runtime)
                for item in self._payload_items(payload, "run_groups")
            ]
        return []

    def _get_group_for_run(self, group_id: str) -> dict[str, Any]:
        get_agent_group = getattr(self._runtime, "get_agent_group", None)
        if callable(get_agent_group):
            return get_agent_group(group_id)

        chat_group = chat_group_snapshot(group_id, self._runtime)
        if chat_group is not None:
            return chat_group

        run_group = self._runtime.get_run_group(group_id)
        return group_definition_from_run_group(run_group, self._runtime)

    def _first_group_child_run_id(self, group_run: dict[str, Any]) -> str:
        for item in group_run.get("runs") or []:
            if not isinstance(item, dict):
                continue
            run_id = str(item.get("run_id") or "").strip()
            if run_id:
                return run_id
        for item in group_run.get("child_run_ids") or []:
            run_id = str(item or "").strip()
            if run_id:
                return run_id
        return ""

    def _event_page_from_events(
        self,
        raw_events: Any,
        *,
        run_id: str,
        task_id: str,
        after_sequence: int,
        limit: int,
        group_run_id: str = "",
    ) -> dict[str, Any]:
        events = [dict(event) for event in raw_events or [] if isinstance(event, dict)]
        filtered_events = []
        for index, event in enumerate(events):
            event_sequence = self._event_sequence(event, index)
            if event_sequence > after_sequence:
                filtered_events.append((event_sequence, event))
        page_pairs = filtered_events[:limit]
        page = [event for _, event in page_pairs]
        next_after_sequence = max([sequence for sequence, _ in page_pairs] or [after_sequence])
        return {
            "run_id": run_id,
            "task_id": task_id,
            "group_run_id": group_run_id,
            "run_group_id": group_run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": next_after_sequence,
            "has_more": len(filtered_events) > limit,
            "events": page,
        }

    def _event_sequence(self, event: dict[str, Any], index: int) -> int:
        try:
            return int(event.get("sequence"))
        except (TypeError, ValueError):
            return index + 1


def _has_runtime_planner_desktop_tool_completion(payload: dict[str, Any]) -> bool:
    for event in payload.get("timeline") or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or event.get("event") or "").strip()
        if event_type != "agent.tool.call":
            continue
        event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        source = str(event.get("source") or event_payload.get("source") or "").strip()
        if source not in {"runtime_planner", "daily_desktop_intent", "daily_desktop_metadata"}:
            continue
        tool_name = str(
            event.get("tool")
            or event.get("detail")
            or event_payload.get("tool")
            or ""
        ).strip()
        if not _runtime_planner_desktop_completion_tool(tool_name):
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            result = event_payload.get("result") if isinstance(event_payload.get("result"), dict) else {}
        if result.get("ok") is True and not result.get("approval_required"):
            return True
    return False


def _runtime_planner_desktop_completion_tool(tool_name: str) -> bool:
    clean = str(tool_name or "").strip()
    if clean in {
        "desktop.hotkey",
        "desktop.shortcut",
        "desktop.type_text",
        "desktop.type",
        "desktop.click",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.search_submit",
        "desktop.submit_foreground",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
    }:
        return True
    return clean.startswith("app.") and (
        "_and_" in clean
        or clean in {"app.open", "app.focus", "app.show", "app.hide", "app.minimize"}
    )
