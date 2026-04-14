"""GET /system/active-window — 活动窗口路由"""

from fastapi import APIRouter, HTTPException

from packages.protocol.enums import ErrorCode
from packages.protocol.errors import ErrorResponse
from packages.protocol.schemas import ActiveWindowResponse

router = APIRouter(tags=["系统"])


@router.get(
    "/system/active-window",
    response_model=ActiveWindowResponse,
    responses={500: {"model": ErrorResponse}},
)
async def get_active_window_route() -> ActiveWindowResponse:
    try:
        from apps.locald.active_window import get_active_window

        return await get_active_window()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorCode.ADAPTER_ERROR,
                message=f"获取活动窗口失败: {e}",
            ).model_dump(),
        )
