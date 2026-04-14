"""GET /status — 通过 Bridge 暴露 Runtime 状态"""

from fastapi import APIRouter

from apps.bridge.deps import get_runtime
from packages.protocol.schemas import StatusResponse

router = APIRouter(tags=["状态"])


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    rt = get_runtime()
    status = rt.get_status()
    
    return StatusResponse(
        uptime_seconds=rt.uptime,
        task_counts=rt.state.get_task_counts(),
    )


@router.get("/hermes/install-info")
async def get_hermes_install_info() -> dict:
    """获取 Hermes Agent 安装信息和引导"""
    rt = get_runtime()
    
    result = {
        "hermes_ready": rt.is_hermes_ready(),
        "install_info": rt.hermes_install_info.model_dump() if rt.hermes_install_info else None,
        "install_guidance": rt.get_hermes_install_guidance()
    }
    
    return result
