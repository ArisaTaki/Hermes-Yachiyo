"""Hermes Agent 环境设置路由"""

from fastapi import APIRouter, HTTPException

from apps.bridge.deps import get_runtime
from apps.installer.hermes_setup import HermesEnvironmentSetup
from packages.protocol.errors import ErrorResponse
from packages.protocol.install import HermesSetupRequest, HermesSetupResponse
from packages.protocol.enums import ErrorCode

router = APIRouter(tags=["Hermes 环境"])


@router.post("/hermes/setup", response_model=HermesSetupResponse)
async def setup_hermes_environment(request: HermesSetupRequest) -> HermesSetupResponse:
    """设置 Hermes Agent 环境"""
    try:
        response = HermesEnvironmentSetup.setup_hermes_environment(request)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error=ErrorCode.INTERNAL_ERROR,
                message=f"环境设置失败: {str(e)}"
            ).model_dump()
        )


@router.get("/hermes/environment")
async def get_hermes_environment() -> dict:
    """获取当前 Hermes 环境信息"""
    return {
        "current_hermes_home": HermesEnvironmentSetup.get_effective_hermes_home(),
        "default_hermes_home": HermesEnvironmentSetup.get_default_hermes_home(),
        "yachiyo_workspace": HermesEnvironmentSetup.get_hermes_yachiyo_workspace(),
        "hermes_home_env_set": bool(os.getenv("HERMES_HOME"))
    }


# 需要导入 os 模块
import os