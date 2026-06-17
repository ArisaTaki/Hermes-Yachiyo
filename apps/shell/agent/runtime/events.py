"""Run event helper functions split from the legacy runtime module."""

from __future__ import annotations

import json
import re
from typing import Any

from packages.security import (
    contains_sensitive_text,
    redact_api_error_text,
    redact_sensitive_text,
    sanitize_sensitive_value,
)

RUNTIME_JSON_REDACTION_MAX_ITEMS = 1000
_MEMORY_TOOL_NAMES = {"memory.add", "memory.replace", "memory.remove"}
_SENSITIVE_PREVALIDATION_PREVIEW_RE = re.compile(
    r"(?i)\b(?:authorization|bearer|[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD))\b"
)


def redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def redact_run_event_payload(value: Any) -> Any:
    return sanitize_sensitive_value(
        value,
        text_limit=0,
        max_items=RUNTIME_JSON_REDACTION_MAX_ITEMS,
        collapse_whitespace=False,
        trim=False,
    )


def tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


def runtime_trace_input_preview(tool_name: str, input_preview: Any) -> Any:
    if not isinstance(input_preview, dict):
        return input_preview
    if tool_name == "artifact.write":
        return {
            key: value
            for key, value in input_preview.items()
            if str(key) != "content"
        }
    if tool_name not in _MEMORY_TOOL_NAMES:
        return input_preview
    return {
        key: value
        for key, value in input_preview.items()
        if str(key) not in {"content", "old_content"}
    }


def canonical_tool_input_preview(
    tool_name: str,
    input_preview: Any,
    *,
    pre_validation: bool = False,
) -> Any:
    preview = runtime_trace_input_preview(tool_name, input_preview)
    if not pre_validation:
        return preview
    try:
        serialized = json.dumps(preview, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        serialized = str(preview)
    if (
        contains_sensitive_text(serialized)
        or redact_secrets(serialized) != serialized
        or _SENSITIVE_PREVALIDATION_PREVIEW_RE.search(serialized)
    ):
        return {"redacted": True, "reason": "sensitive_input"}
    return preview


def canonical_tool_event_payload(
    tool_name: str,
    input_preview: Any,
    *,
    approved: bool = False,
    pre_validation: bool = False,
    result: dict[str, Any] | None = None,
    error: Any = None,
    status: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": tool_name,
        "input_preview": canonical_tool_input_preview(
            tool_name,
            input_preview,
            pre_validation=pre_validation,
        ),
        "approved": bool(approved),
    }
    if status:
        payload["status"] = status
    if result is not None:
        payload["output_preview"] = tool_input_preview(result)
    if error is not None:
        payload["error"] = redact_api_error_text(error)
    return payload


def model_output_completed_payload(
    content: str,
    *,
    truncated: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": content,
        "output_chars": len(content),
        "truncated": truncated,
    }
    for key, value in (metadata or {}).items():
        if value is not None:
            payload[key] = value
    return payload


def model_request_started_payload(
    *,
    profile_id: str,
    model: str,
    capability: str,
    message_count: int,
) -> dict[str, Any]:
    return {
        "profile_id": str(profile_id or ""),
        "model": str(model or ""),
        "capability": str(capability or ""),
        "message_count": max(0, int(message_count or 0)),
    }


def model_request_failed_payload(error: Any) -> dict[str, Any]:
    return {"error": redact_secrets(error)}


def task_run_event_payload(
    *,
    task_id: str = "",
    run_id: str = "",
    session_id: str = "",
    status: str = "",
    result: Any = None,
    error: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": str(task_id or ""),
        "run_id": str(run_id or ""),
        "session_id": str(session_id or ""),
    }
    if status:
        payload["status"] = status
    if result is not None:
        payload["result"] = redact_secrets(result)
    if error is not None:
        payload["error"] = redact_secrets(error)
    return payload


class RuntimeTaskModelEventBuilder:
    """Builds RunEvent payloads shared by Chat task and model execution facts."""

    def model_request_started_payload(
        self,
        *,
        profile_id: str,
        model: str,
        capability: str,
        message_count: int,
    ) -> dict[str, Any]:
        return model_request_started_payload(
            profile_id=profile_id,
            model=model,
            capability=capability,
            message_count=message_count,
        )

    def model_request_failed_payload(self, error: Any) -> dict[str, Any]:
        return model_request_failed_payload(error)

    def model_output_completed_payload(
        self,
        content: str,
        *,
        truncated: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return model_output_completed_payload(
            content,
            truncated=truncated,
            metadata=metadata,
        )

    def task_run_event_payload(
        self,
        *,
        task_id: str = "",
        run_id: str = "",
        session_id: str = "",
        status: str = "",
        result: Any = None,
        error: Any = None,
    ) -> dict[str, Any]:
        return task_run_event_payload(
            task_id=task_id,
            run_id=run_id,
            session_id=session_id,
            status=status,
            result=result,
            error=error,
        )


class RuntimeTaskEventRecorder:
    """Records Chat task lifecycle RunEvents without owning run state."""

    def __init__(
        self,
        *,
        append_run_event: Any,
        payload_builder: RuntimeTaskModelEventBuilder | None = None,
    ) -> None:
        self._append_run_event = append_run_event
        self._payload_builder = payload_builder or RuntimeTaskModelEventBuilder()

    def started(
        self,
        run_id: str,
        *,
        task_id: str = "",
        session_id: str = "",
    ) -> None:
        clean_task_id = str(task_id or "")
        clean_run_id = str(run_id or "")
        clean_session_id = str(session_id or "")
        self._append_run_event(
            clean_run_id,
            "run.started",
            {"task_id": clean_task_id, "session_id": clean_session_id},
        )
        task_payload = self._payload_builder.task_run_event_payload(
            task_id=clean_task_id,
            run_id=clean_run_id,
            session_id=clean_session_id,
            status="running",
        )
        self._append_run_event(clean_run_id, "task.created", task_payload)
        self._append_run_event(clean_run_id, "task.started", task_payload)
        self._append_run_event(
            clean_run_id,
            "task.linked",
            {"task_id": clean_task_id, "session_id": clean_session_id},
        )

    def completed(
        self,
        run_id: str,
        *,
        task_id: str = "",
        session_id: str = "",
        result: Any = None,
    ) -> None:
        clean_run_id = str(run_id or "")
        safe_payload = self._payload_builder.task_run_event_payload(
            task_id=task_id,
            run_id=clean_run_id,
            session_id=session_id,
            status="completed",
            result=result,
        )
        self._append_run_event(clean_run_id, "task.completed", safe_payload)
        self._append_run_event(clean_run_id, "run.completed", {"result": redact_secrets(result)})

    def failed(
        self,
        run_id: str,
        *,
        task_id: str = "",
        session_id: str = "",
        error: Any = None,
    ) -> None:
        clean_run_id = str(run_id or "")
        safe_payload = self._payload_builder.task_run_event_payload(
            task_id=task_id,
            run_id=clean_run_id,
            session_id=session_id,
            status="failed",
            error=error,
        )
        self._append_run_event(clean_run_id, "task.failed", safe_payload)
        self._append_run_event(clean_run_id, "run.failed", {"error": redact_secrets(error)})


def agent_run_started_payload(
    *,
    agent_id: str,
    agent_name: str,
    backend: str,
    runtime: str,
) -> dict[str, Any]:
    return {
        "agent_id": str(agent_id or ""),
        "agent_name": str(agent_name or ""),
        "backend": str(backend or ""),
        "runtime": str(runtime or ""),
    }


def agent_run_completed_payload(result: Any) -> dict[str, Any]:
    return {"result": result}


def agent_run_failed_payload(error: Any) -> dict[str, Any]:
    return {"error": error}


class RuntimeAgentRunEventRecorder:
    """Records Agent run lifecycle RunEvents without owning run state."""

    def __init__(self, *, append_run_event: Any) -> None:
        self._append_run_event = append_run_event

    def started(
        self,
        run_id: str,
        *,
        agent_id: str,
        agent_name: str,
        backend: str,
        runtime: str,
    ) -> None:
        self._append_run_event(
            run_id,
            "agent.run.started",
            agent_run_started_payload(
                agent_id=agent_id,
                agent_name=agent_name,
                backend=backend,
                runtime=runtime,
            ),
        )

    def completed(self, run_id: str, result: Any) -> None:
        self._append_run_event(
            run_id,
            "agent.run.completed",
            agent_run_completed_payload(result),
        )

    def failed(self, run_id: str, error: Any) -> None:
        self._append_run_event(
            run_id,
            "agent.run.failed",
            agent_run_failed_payload(error),
        )


class ToolEventPayloadBuilder:
    """Builds canonical ToolCall RunEvent payloads."""

    def payload(
        self,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
        pre_validation: bool = False,
        result: dict[str, Any] | None = None,
        error: Any = None,
        status: str = "",
    ) -> dict[str, Any]:
        return canonical_tool_event_payload(
            tool_name,
            input_preview,
            approved=approved,
            pre_validation=pre_validation,
            result=result,
            error=error,
            status=status,
        )


class RuntimeToolCallEventRecorder:
    """Records ToolCall lifecycle RunEvents without owning tool execution."""

    def __init__(
        self,
        *,
        append_run_event: Any,
        payload_builder: ToolEventPayloadBuilder | None = None,
    ) -> None:
        self._append_run_event = append_run_event
        self._payload_builder = payload_builder or ToolEventPayloadBuilder()

    def _append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not run_id:
            return None
        return self._append_run_event(run_id, event_type, payload)

    def denied(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
    ) -> dict[str, Any] | None:
        return self._append(
            run_id,
            "agent.tool.denied",
            {"tool": tool_name, "input_preview": input_preview},
        )

    def requested(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
    ) -> dict[str, Any] | None:
        return self._append(
            run_id,
            "tool.requested",
            self._payload_builder.payload(
                tool_name,
                input_preview,
                approved=approved,
                pre_validation=True,
                status="requested",
            ),
        )

    def started(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
    ) -> dict[str, Any] | None:
        return self._append(
            run_id,
            "tool.started",
            self._payload_builder.payload(
                tool_name,
                input_preview,
                approved=approved,
                status="running",
            ),
        )

    def failed(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
        pre_validation: bool = False,
        error: Any = None,
    ) -> dict[str, Any] | None:
        return self._append(
            run_id,
            "tool.failed",
            self._payload_builder.payload(
                tool_name,
                input_preview,
                approved=approved,
                pre_validation=pre_validation,
                error=error,
                status="failed",
            ),
        )

    def result(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any] | None:
        if tool_result.get("approval_required"):
            return self._append(
                run_id,
                "tool.approval_required",
                self._payload_builder.payload(
                    tool_name,
                    input_preview,
                    approved=approved,
                    result=tool_result,
                    status="waiting_approval",
                ),
            )
        ok = bool(tool_result.get("ok"))
        return self._append(
            run_id,
            "tool.completed" if ok else "tool.failed",
            self._payload_builder.payload(
                tool_name,
                input_preview,
                approved=approved,
                result=tool_result,
                status="completed" if ok else "failed",
            ),
        )

    def agent_tool_call(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any] | None:
        return self._append(
            run_id,
            "agent.tool.call",
            {
                "tool": tool_name,
                "input_preview": input_preview,
                "result": tool_result,
                "approved": bool(approved),
            },
        )


def artifact_created_payload(
    tool_result: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    return {
        "artifact_id": str(tool_result.get("artifact_id") or tool_result.get("path") or ""),
        "run_id": run_id,
        "kind": "tool_artifact",
        "path": str(tool_result.get("path") or ""),
        "size_bytes": int(tool_result.get("bytes") or 0),
        "source_tool": "artifact.write",
    }


def tool_trace_status(tool_result: dict[str, Any]) -> str:
    return "completed" if tool_result.get("ok") else "failed"


def skill_trace_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    result = {
        "ok": bool(tool_result.get("ok")),
        "skill_id": str(tool_result.get("skill_id") or ""),
        "name": str(tool_result.get("name") or ""),
        "description": str(tool_result.get("description") or ""),
        "asset_paths": list(tool_result.get("asset_paths") or []),
    }
    if tool_result.get("error"):
        result["error"] = str(tool_result.get("error") or "")
    return result


def memory_trace_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    memory = tool_result.get("memory") if isinstance(tool_result.get("memory"), dict) else {}
    result = {
        "ok": bool(tool_result.get("ok")),
        "action": str(tool_result.get("action") or ""),
        "memory_id": str(memory.get("memory_id") or ""),
        "kind": str(memory.get("kind") or ""),
        "scope": str(memory.get("scope") or ""),
        "deleted": bool(memory.get("deleted_at")),
    }
    if tool_result.get("error"):
        result["error"] = str(tool_result.get("error") or "")
    return result


def memory_skill_trace_event(
    tool_name: str,
    input_preview: Any,
    tool_result: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name == "skill.read":
        return {
            "event_type": "skill.dispatch.read",
            "payload": {
                "tool": tool_name,
                "status": tool_trace_status(tool_result),
                "input_preview": runtime_trace_input_preview(tool_name, input_preview),
                "result": skill_trace_result(tool_result),
            },
        }
    if tool_name in _MEMORY_TOOL_NAMES:
        action = tool_name.split(".", 1)[1]
        return {
            "event_type": f"memory.write.{action}",
            "payload": {
                "tool": tool_name,
                "status": tool_trace_status(tool_result),
                "input_preview": runtime_trace_input_preview(tool_name, input_preview),
                "result": memory_trace_result(tool_result),
            },
        }
    return None


def memory_retrieved_payload(memories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(memories),
        "memories": [
            {
                "memory_id": str(memory.get("memory_id") or ""),
                "kind": str(memory.get("kind") or ""),
                "scope": str(memory.get("scope") or ""),
                "deleted": bool(memory.get("deleted_at")),
            }
            for memory in memories
        ],
    }


class RuntimeTraceEventBuilder:
    """Builds compact RunEvent payloads for Artifact, Memory, and Skill facts."""

    def artifact_created_payload(
        self,
        tool_result: dict[str, Any],
        *,
        run_id: str,
    ) -> dict[str, Any]:
        return artifact_created_payload(tool_result, run_id=run_id)

    def memory_skill_trace_event(
        self,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        return memory_skill_trace_event(tool_name, input_preview, tool_result)

    def memory_retrieved_payload(self, memories: list[dict[str, Any]]) -> dict[str, Any]:
        return memory_retrieved_payload(memories)


def canonical_run_event_aliases(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    clean_event_type = str(event_type or "")
    direct_aliases = {
        "model.request.started": ["model.requested"],
        "model.output.completed": ["model.completed"],
        "workflow.run.started": ["workflow.started"],
        "workflow.run.approval_required": ["workflow.paused_for_approval", "approval.required"],
        "workflow.run.resumed": ["workflow.resumed"],
        "workflow.run.completed": ["workflow.completed"],
        "workflow.run.failed": ["workflow.failed"],
        "workflow.run.cancelled": ["workflow.cancelled"],
        "skill.dispatch.read": ["skill.selected"],
        "agent.tool.started": ["tool.started"],
        "agent.tool.completed": ["tool.completed"],
        "agent.tool.failed": ["tool.failed"],
        "agent.tool.denied": ["tool.denied"],
        "agent.tool.approval_required": ["tool.approval_required", "approval.required"],
        "workflow.node.approval_required": ["workflow.paused_for_approval", "approval.required"],
        "group.approval_required": ["approval.required"],
        "group.member.approval_required": ["approval.required"],
        "agent.tool.approval_approved": ["tool.approved", "approval.approved"],
        "agent.tool.approval_rejected": ["tool.rejected", "approval.rejected"],
        "agent.tool.approval_timeout": ["approval.timeout"],
        "workflow.node.approval_approved": ["approval.approved"],
        "workflow.node.approval_rejected": ["approval.rejected"],
        "workflow.node.approval_timeout": ["approval.timeout"],
    }.get(clean_event_type)
    if direct_aliases:
        return direct_aliases

    if clean_event_type in {
        "workflow.node.start",
        "workflow.node.agent",
        "workflow.node.workflow",
        "workflow.node.artifact",
        "workflow.node.condition",
        "workflow.node.parallel",
        "workflow.node.loop",
    }:
        status = str((payload or {}).get("status") or "").strip()
        aliases = ["workflow.node.started"]
        if status == "completed":
            aliases.append("workflow.node.completed")
        elif status in {"failed", "cancelled"}:
            aliases.append("workflow.node.failed")
        elif status == "approval_required":
            aliases.append("workflow.paused_for_approval")
        return aliases
    return []


class RuntimeRunEventRecorder:
    """Writes replayable RunEvents and their public compatibility aliases."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        event = self._repository.append(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )
        for alias in canonical_run_event_aliases(event_type, payload):
            self._repository.append(
                run_id,
                alias,
                payload,
                actor=actor,
                visibility=visibility,
                sensitivity=sensitivity,
            )
        return event

    def list(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self._repository.list(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            include_internal=include_internal,
        )
