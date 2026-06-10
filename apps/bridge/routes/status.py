"""GET /status — 通过 Bridge 暴露 Runtime 状态"""

from fastapi import APIRouter

from apps.bridge.deps import get_runtime
from apps.core.version import get_app_version
from packages.protocol.schemas import StatusResponse

router = APIRouter(tags=["状态"])


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    rt = get_runtime()
    return StatusResponse(
        version=get_app_version(),
        uptime_seconds=rt.uptime,
        task_counts=rt.state.get_task_counts(),
        native_agent_ready=rt.is_native_agent_ready(),
    )


@router.get("/native-agent/readiness")
async def get_native_agent_readiness() -> dict:
    return get_runtime().native_agent_readiness()
