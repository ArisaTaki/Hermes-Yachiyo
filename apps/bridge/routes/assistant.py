"""POST /assistant/intent — 低风险自然语言入口。"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.bridge.deps import get_runtime
from apps.shell.assets import DEFAULT_BUBBLE_AVATAR_PATH, data_uri, get_user_avatar_assets_dir
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
_PROMPT_ORDER = ["agent_profile", "persona", "user_address", "user_profile", "relevant_memory", "current_session", "request"]
_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_AVATAR_MIME_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class AssistantAvatarImportRequest(BaseModel):
    """Import avatar image from a local path or browser data URL."""

    target: str = Field(default="agent", max_length=16)
    path: str = Field(default="", max_length=1000)
    data_url: str = Field(default="", max_length=8_000_000)
    file_name: str = Field(default="", max_length=255)


def _assistant_config():
    config = get_runtime().config
    return config, config.assistant


def _avatar_url(path_value: str, *, fallback: bool) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path and not fallback:
        return ""
    avatar_path = Path(raw_path or str(DEFAULT_BUBBLE_AVATAR_PATH)).expanduser()
    if not avatar_path.exists():
        if not fallback:
            return ""
        avatar_path = DEFAULT_BUBBLE_AVATAR_PATH
    try:
        return data_uri(avatar_path)
    except Exception:
        return data_uri(DEFAULT_BUBBLE_AVATAR_PATH) if fallback else ""


def _avatar_suffix(file_name: str, mime_type: str = "") -> str:
    suffix = Path(file_name or "").suffix.lower()
    if suffix in _AVATAR_SUFFIXES:
        return suffix
    return _AVATAR_MIME_SUFFIXES.get(mime_type.lower(), "")


def _avatar_bytes_from_request(req: AssistantAvatarImportRequest) -> tuple[bytes, str]:
    path_value = str(req.path or "").strip()
    if path_value:
        source = Path(path_value).expanduser()
        if not source.is_file():
            raise HTTPException(status_code=400, detail="头像文件不存在")
        suffix = _avatar_suffix(source.name)
        if not suffix:
            raise HTTPException(status_code=400, detail="仅支持 PNG、JPG、WEBP 或 GIF 图片")
        data = source.read_bytes()
        if len(data) > _AVATAR_MAX_BYTES:
            raise HTTPException(status_code=400, detail="头像图片不能超过 5 MB")
        return data, suffix

    data_url = str(req.data_url or "").strip()
    if not data_url:
        raise HTTPException(status_code=400, detail="请选择头像图片")
    header, separator, payload = data_url.partition(",")
    if not separator or not header.startswith("data:image/") or ";base64" not in header:
        raise HTTPException(status_code=400, detail="头像图片格式无效")
    mime_type = header.removeprefix("data:").split(";", 1)[0]
    suffix = _avatar_suffix(req.file_name, mime_type)
    if not suffix:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPG、WEBP 或 GIF 图片")
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="头像图片读取失败") from exc
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="头像图片不能超过 5 MB")
    return data, suffix


def _import_avatar(req: AssistantAvatarImportRequest) -> str:
    target = str(req.target or "").strip().lower()
    if target not in {"agent", "user"}:
        raise HTTPException(status_code=400, detail="头像目标无效")
    data, suffix = _avatar_bytes_from_request(req)
    digest = hashlib.sha256(data).hexdigest()[:16]
    avatar_dir = get_user_avatar_assets_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    destination = avatar_dir / f"{target}-{digest}{suffix}"
    destination.write_bytes(data)
    return str(destination)


def _build_profile_response(*, message: str = "") -> AssistantProfileResponse:
    _config, assistant = _assistant_config()
    return AssistantProfileResponse(
        ok=True,
        agent_name=assistant.agent_name,
        agent_nickname=assistant.agent_nickname,
        agent_avatar_path=assistant.agent_avatar_path,
        agent_avatar_url=_avatar_url(assistant.agent_avatar_path, fallback=True),
        persona_prompt=assistant.persona_prompt,
        user_address=assistant.user_address,
        user_name=assistant.user_name,
        user_avatar_path=assistant.user_avatar_path,
        user_avatar_url=_avatar_url(assistant.user_avatar_path, fallback=False),
        user_profile=assistant.user_profile,
        user_preferences=assistant.user_preferences,
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
    """更新共享助手资料；记忆事实同步保留为后续本地端能力。"""
    config, assistant = _assistant_config()
    changed = False
    if req.agent_name is not None:
        assistant.agent_name = str(req.agent_name)
        changed = True
    if req.agent_nickname is not None:
        assistant.agent_nickname = str(req.agent_nickname)
        changed = True
    if req.agent_avatar_path is not None:
        assistant.agent_avatar_path = str(req.agent_avatar_path)
        changed = True
    if req.persona_prompt is not None:
        assistant.persona_prompt = str(req.persona_prompt)
        changed = True
    if req.user_address is not None:
        assistant.user_address = str(req.user_address)
        changed = True
    if req.user_name is not None:
        assistant.user_name = str(req.user_name)
        changed = True
    if req.user_avatar_path is not None:
        assistant.user_avatar_path = str(req.user_avatar_path)
        changed = True
    if req.user_profile is not None:
        assistant.user_profile = str(req.user_profile)
        changed = True
    if req.user_preferences is not None:
        assistant.user_preferences = str(req.user_preferences)
        changed = True
    if changed:
        from apps.shell.config import save_config

        save_config(config)
    return _build_profile_response(message="助手资料已更新")


@router.post("/assistant/profile/avatar/import", response_model=AssistantProfileResponse)
def import_assistant_avatar(req: AssistantAvatarImportRequest) -> AssistantProfileResponse:
    """导入 Agent 或用户头像，并将配置指向用户资料目录中的副本。"""
    config, assistant = _assistant_config()
    avatar_path = _import_avatar(req)
    if str(req.target or "").strip().lower() == "user":
        assistant.user_avatar_path = avatar_path
    else:
        assistant.agent_avatar_path = avatar_path
    from apps.shell.config import save_config

    save_config(config)
    return _build_profile_response(message="头像已更新")


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
