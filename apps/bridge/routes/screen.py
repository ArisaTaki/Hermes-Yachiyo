"""GET /screen/current — 截图路由"""

from fastapi import APIRouter, HTTPException

from packages.protocol.enums import ErrorCode
from packages.protocol.errors import ErrorResponse
from packages.protocol.schemas import ScreenshotResponse

router = APIRouter(tags=["屏幕"])


@router.get(
    "/screen/current",
    response_model=ScreenshotResponse,
    responses={500: {"model": ErrorResponse}},
)
async def get_screen_current() -> ScreenshotResponse:
    try:
        from apps.locald.screenshot import capture_screenshot

        return await capture_screenshot()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorCode.ADAPTER_ERROR,
                message=f"截图失败: {e}",
            ).model_dump(),
        )
