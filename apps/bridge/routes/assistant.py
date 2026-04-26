"""POST /assistant/intent — 低风险自然语言入口。"""

from __future__ import annotations

from fastapi import APIRouter

from apps.bridge.deps import get_runtime
from packages.protocol.enums import RiskLevel, TaskType
from packages.protocol.schemas import (
    AssistantIntentRequest,
    AssistantIntentResponse,
    AssistantProfilePatchRequest,
    AssistantProfileResponse,
)

router = APIRouter(tags=["Assistant"])

_STATUS_KEYWORDS = {"状态", "status", "运行状态", "是否就绪"}
_SCREEN_KEYWORDS = {"截图", "屏幕", "screen", "screenshot"}
_WINDOW_KEYWORDS = {"活动窗口", "当前窗口", "窗口", "window"}
_PROMPT_ORDER = ["persona", "relevant_memory", "current_session", "request"]


def _assistant_config():
    config = get_runtime().config
    return config, config.assistant


def _build_profile_response(*, message: str = "") -> AssistantProfileResponse:
    _config, assistant = _assistant_config()
    return AssistantProfileResponse(
        ok=True,
        persona_prompt=assistant.persona_prompt,
        memory_enabled=False,
        memory_scope="local_only",
        prompt_order=list(_PROMPT_ORDER),
        message=message,
    )


def _contains_any(text: str, keywords: set[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


@router.get("/assistant/profile", response_model=AssistantProfileResponse)
def get_assistant_profile() -> AssistantProfileResponse:
    """返回桌面端共享助手资料。AstrBot 只读取/转发，不另建人格。"""
    return _build_profile_response()


@router.patch("/assistant/profile", response_model=AssistantProfileResponse)
def patch_assistant_profile(req: AssistantProfilePatchRequest) -> AssistantProfileResponse:
    """更新共享人设 Prompt；记忆事实同步保留为后续本地端能力。"""
    config, assistant = _assistant_config()
    if req.persona_prompt is not None:
        assistant.persona_prompt = str(req.persona_prompt)
        from apps.shell.config import save_config

        save_config(config)
    return _build_profile_response(message="助手资料已更新")


def _format_status() -> str:
    rt = get_runtime()
    status = rt.get_status()
    hermes_ready = rt.is_hermes_ready()
    counts = status.get("task_counts", {})
    return (
        "Hermes-Yachiyo 正在运行；"
        f"Hermes {'已就绪' if hermes_ready else '未就绪'}；"
        f"任务 pending={counts.get('pending', 0)} running={counts.get('running', 0)} completed={counts.get('completed', 0)}"
    )


async def _format_screen() -> str:
    from apps.locald.screenshot import capture_screenshot

    screenshot = await capture_screenshot()
    return f"已获取当前屏幕截图：{screenshot.width}×{screenshot.height} {screenshot.format.upper()}"


async def _format_active_window() -> str:
    from apps.locald.active_window import get_active_window

    window = await get_active_window()
    return f"当前活动窗口：{window.app_name} — {window.title or '（无标题）'}"


@router.post("/assistant/intent", response_model=AssistantIntentResponse)
async def assistant_intent(req: AssistantIntentRequest) -> AssistantIntentResponse:
    """面向 AstrBot 的低风险自然语言入口，不在插件侧执行本机控制。"""
    text = (req.text or "").strip()
    if not text:
        return AssistantIntentResponse(ok=False, action="invalid", message="内容不能为空")

    if _contains_any(text, _STATUS_KEYWORDS):
        if req.dry_run:
            return AssistantIntentResponse(ok=True, action="status", message="将返回运行状态")
        return AssistantIntentResponse(ok=True, action="status", message=_format_status())

    if _contains_any(text, _SCREEN_KEYWORDS):
        if req.dry_run:
            return AssistantIntentResponse(ok=True, action="screen", message="将获取当前屏幕截图摘要")
        try:
            return AssistantIntentResponse(ok=True, action="screen", message=await _format_screen())
        except Exception as exc:
            return AssistantIntentResponse(ok=False, action="screen", message=f"截图失败: {exc}")

    if _contains_any(text, _WINDOW_KEYWORDS):
        if req.dry_run:
            return AssistantIntentResponse(ok=True, action="active_window", message="将返回活动窗口摘要")
        try:
            return AssistantIntentResponse(ok=True, action="active_window", message=await _format_active_window())
        except Exception as exc:
            return AssistantIntentResponse(ok=False, action="active_window", message=f"获取活动窗口失败: {exc}")

    if req.dry_run:
        return AssistantIntentResponse(
            ok=True,
            action="create_low_risk_task",
            message="将创建 RiskLevel.LOW 的 Hermes 自然语言任务",
        )

    task = get_runtime().state.create_task(
        description=text,
        task_type=TaskType.GENERAL,
        risk_level=RiskLevel.LOW,
    )
    return AssistantIntentResponse(
        ok=True,
        action="create_low_risk_task",
        task_id=task.task_id,
        message="已创建低风险 Hermes 任务",
    )
