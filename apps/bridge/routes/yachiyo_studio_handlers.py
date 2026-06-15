"""Agent Studio-facing Yachiyo route handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import (
    StartWorkflowRunBody,
    TaskApprovalRequest,
)
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.bridge.routes.yachiyo_studio_agent_handlers import (
    attach_agent_skill,
    delete_agent,
    detach_agent_skill,
    get_agent,
    list_agents,
    save_agent,
    test_agent_model,
)
from apps.bridge.routes.yachiyo_studio_group_handlers import (
    get_group,
    get_group_run,
    list_group_runs,
    list_groups,
    save_group,
    start_group_run,
)
from apps.bridge.routes.yachiyo_studio_memory_handlers import (
    cancel_future_task,
    create_memory,
    delete_memory,
    list_future_tasks,
    list_memories,
    trigger_due_future_tasks,
    update_memory,
)
from apps.bridge.routes.yachiyo_studio_skill_handlers import (
    create_skill_folder,
    delete_skill,
    delete_skill_folder,
    import_skill,
    install_skill,
    list_skill_folders,
    list_skill_sources,
    list_skills,
    sync_native_skills,
    update_skill,
    update_skill_folder,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import (
    SaveWorkflowRequest,
    StartWorkflowRunRequest,
)


async def list_workflows(http_request: Request | None = None) -> dict[str, Any]:
    workflows = await asyncio.to_thread(studio_service(http_request).list_workflows)
    return {"workflows": [snapshot(workflow) for workflow in workflows]}


async def save_workflow(
    request: SaveWorkflowRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        workflow_snapshot = await asyncio.to_thread(studio_service(http_request).save_workflow, request)
        return snapshot(workflow_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def get_workflow(
    workflow_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        workflow_snapshot = await asyncio.to_thread(
            studio_service(http_request).get_workflow,
            workflow_id,
        )
        return snapshot(workflow_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc


async def delete_workflow(
    workflow_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).delete_workflow, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def start_workflow_run(
    workflow_id: str,
    request: StartWorkflowRunBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_request = StartWorkflowRunRequest(
            workflow_id=workflow_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        run_snapshot = await asyncio.to_thread(
            studio_service(http_request).start_workflow_run,
            run_request,
        )
        return snapshot(run_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def get_run_timeline(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).get_run_timeline, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


async def list_runs(
    limit: int = 50,
    http_request: Request | None = None,
) -> dict[str, Any]:
    runs = await asyncio.to_thread(
        studio_service(http_request).list_run_timelines,
        max(1, min(200, int(limit or 50))),
    )
    return {"runs": [snapshot(run) for run in runs]}


async def rerun_run(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).rerun_run, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def cancel_run(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).cancel_run, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


async def delete_run(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).delete_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def approve_run_approval(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).approve_run_approval, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def reject_run_approval(
    run_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(
            studio_service(http_request).reject_run_approval,
            run_id,
            request.reason if request is not None else "",
        )
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def read_run_artifact(
    run_id: str,
    artifact_path: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            studio_service(http_request).read_run_artifact,
            run_id,
            artifact_path,
        )
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from exc


async def get_run_events(
    run_id: str,
    after_sequence: int = 0,
    limit: int = 200,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        events = await asyncio.to_thread(
            lambda: list(studio_service(http_request).get_run_event_stream(run_id))
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    clean_after_sequence = max(0, int(after_sequence or 0))
    clean_limit = max(1, min(500, int(limit or 200)))
    filtered_events = [
        event
        for event in events
        if int(getattr(event, "sequence", 0) or 0) > clean_after_sequence
    ]
    page = filtered_events[:clean_limit]
    next_after_sequence = max(
        [int(getattr(event, "sequence", 0) or 0) for event in page] or [clean_after_sequence]
    )
    return {
        "run_id": run_id,
        "after_sequence": clean_after_sequence,
        "limit": clean_limit,
        "next_after_sequence": next_after_sequence,
        "has_more": len(filtered_events) > clean_limit,
        "events": [snapshot(event) for event in page],
    }
