"""GET /status — 通过 Bridge 暴露 Runtime 状态"""

from fastapi import APIRouter

from apps.bridge.deps import get_runtime
from packages.protocol.schemas import StatusResponse

router = APIRouter(tags=["状态"])


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    rt = get_runtime()
    return StatusResponse(
        uptime_seconds=rt.uptime,
        task_counts=rt.state.get_task_counts(),
    )
