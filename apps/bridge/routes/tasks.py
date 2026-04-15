"""任务路由: GET /tasks, GET /tasks/{task_id}, POST /tasks, POST /tasks/{task_id}/cancel"""

from fastapi import APIRouter, HTTPException

from apps.bridge.deps import get_runtime
from packages.protocol.enums import ErrorCode
from packages.protocol.errors import ErrorResponse
from packages.protocol.schemas import (
    TaskCancelResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskGetResponse,
    TaskListResponse,
)

router = APIRouter(tags=["任务"])


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks() -> TaskListResponse:
    state = get_runtime().state
    tasks = state.list_tasks()
    return TaskListResponse(tasks=tasks, total=len(tasks))


@router.get(
    "/tasks/{task_id}",
    response_model=TaskGetResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_task(task_id: str) -> TaskGetResponse:
    task = get_runtime().state.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorCode.NOT_FOUND,
                message=f"任务 {task_id} 不存在",
            ).model_dump(),
        )
    return TaskGetResponse(task=task)


@router.post("/tasks", response_model=TaskCreateResponse, status_code=201)
async def create_task(req: TaskCreateRequest) -> TaskCreateResponse:
    state = get_runtime().state
    task = state.create_task(
        description=req.description,
        task_type=req.task_type,
        risk_level=req.risk_level,
    )
    return TaskCreateResponse(task=task)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskCancelResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def cancel_task(task_id: str) -> TaskCancelResponse:
    state = get_runtime().state
    try:
        task = state.cancel_task(task_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorCode.NOT_FOUND,
                message=f"任务 {task_id} 不存在",
            ).model_dump(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error=ErrorCode.TASK_NOT_CANCELLABLE,
                message=str(e),
            ).model_dump(),
        )
    return TaskCancelResponse(task=task)
