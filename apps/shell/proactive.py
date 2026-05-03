"""共享主动桌面观察服务。"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from apps.core.executor import HermesExecutor
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)

_DESKTOP_WATCH_PROMPT = (
    "主动桌面观察：请查看用户当前桌面状态。必要时调用可用的屏幕截图/视觉工具，"
    "用简短中文判断是否有需要提醒用户的事项；如果当前模型或工具无法读取截图，"
    "请明确说明缺少的多模态/vision 能力。"
)
_DEFAULT_PROACTIVE_VOICE_PROMPT = (
    "主动提醒只输出适合语音播报的一句中文招呼或提醒，保持八千代人设，"
    "不要朗读长段分析、列表、代码、路径或调试信息。"
)


def build_proactive_desktop_prompt(runtime: Any | None = None) -> str:
    """Build the desktop-watch prompt with short-notification constraints."""
    tts_config = getattr(getattr(runtime, "config", None), "tts", None) if runtime is not None else None
    try:
        max_chars = max(20, min(240, int(getattr(tts_config, "max_chars", 80) or 80)))
    except (TypeError, ValueError):
        max_chars = 80
    prompt = str(
        getattr(tts_config, "notification_prompt", "") or _DEFAULT_PROACTIVE_VOICE_PROMPT
    ).strip()
    return (
        f"{_DESKTOP_WATCH_PROMPT}\n\n"
        "输出约束："
        f"{prompt} 最多 {max_chars} 个中文字符；"
        "如果没有明确需要提醒的事项，就只给一句自然的问候，不要展开桌面细节。"
    )


class ProactiveDesktopService:
    """Bubble / Live2D 共享的主动桌面观察状态机。"""

    def __init__(self, runtime: "HermesRuntime", mode_config: Any) -> None:
        self._runtime = runtime
        self._mode_config = mode_config
        self._last_check_at = 0.0
        self._last_task_id: str | None = None
        self._attention_task_id: str | None = None
        self._acknowledged_task_id: str | None = None
        self._reported_failed_task_id: str | None = None

    @property
    def last_task_id(self) -> str | None:
        return self._last_task_id

    def acknowledge(self) -> None:
        """确认当前主动观察提示，清除 attention 状态。"""
        if self._attention_task_id:
            self._acknowledged_task_id = self._attention_task_id
        self._attention_task_id = None

    def get_state(self) -> dict[str, Any]:
        """返回当前主动观察状态，并在满足间隔时创建低风险截图任务。"""
        enabled = bool(getattr(self._mode_config, "proactive_enabled", False))
        desktop_watch_enabled = bool(
            getattr(self._mode_config, "proactive_desktop_watch_enabled", False)
        )
        if not enabled:
            return {
                "enabled": False,
                "desktop_watch_enabled": desktop_watch_enabled,
                "status": "disabled",
                "has_attention": False,
                "message": "主动关怀已关闭",
            }

        if not desktop_watch_enabled:
            return {
                "enabled": True,
                "desktop_watch_enabled": False,
                "status": "idle",
                "has_attention": False,
                "message": "主动关怀已开启，桌面观察未开启",
            }

        blocker = self._desktop_watch_blocker()
        if blocker:
            return {
                "enabled": True,
                "desktop_watch_enabled": True,
                "status": "blocked",
                "has_attention": False,
                "error": blocker,
            }

        now = time.monotonic()
        interval = max(60, int(getattr(self._mode_config, "proactive_interval_seconds", 300) or 300))
        task = self._current_task()
        if task is not None:
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                return {
                    "enabled": True,
                    "desktop_watch_enabled": True,
                    "status": task.status.value,
                    "has_attention": False,
                    "task_id": task.task_id,
                    "message": "正在进行主动桌面观察",
                }
            if task.status == TaskStatus.COMPLETED:
                has_attention = self._acknowledged_task_id != task.task_id
                if has_attention:
                    self._attention_task_id = task.task_id
                elif now - self._last_check_at >= interval:
                    task_id = self._schedule_desktop_watch_task()
                    return self._scheduled_state(task_id)
                result = str(getattr(task, "result", "") or "").strip()
                attention_text = _compact_attention_text(result)
                return {
                    "enabled": True,
                    "desktop_watch_enabled": True,
                    "status": "completed",
                    "has_attention": has_attention,
                    "task_id": task.task_id,
                    "message": attention_text if has_attention and attention_text else "主动观察结果已查看",
                    "result": result,
                    "attention_text": attention_text,
                    "attention_source": "proactive_desktop_watch",
                }
            if task.status == TaskStatus.FAILED:
                if (
                    self._reported_failed_task_id == task.task_id
                    and now - self._last_check_at >= interval
                ):
                    task_id = self._schedule_desktop_watch_task()
                    return self._scheduled_state(task_id)
                self._reported_failed_task_id = task.task_id
                return {
                    "enabled": True,
                    "desktop_watch_enabled": True,
                    "status": "failed",
                    "has_attention": False,
                    "task_id": task.task_id,
                    "error": task.error or "主动桌面观察失败",
                }

        if now - self._last_check_at >= interval:
            task_id = self._schedule_desktop_watch_task()
            return self._scheduled_state(task_id)

        return {
            "enabled": True,
            "desktop_watch_enabled": True,
            "status": "waiting",
            "has_attention": False,
            "next_check_seconds": int(interval - (now - self._last_check_at)),
        }

    @staticmethod
    def _scheduled_state(task_id: str) -> dict[str, Any]:
        return {
            "enabled": True,
            "desktop_watch_enabled": True,
            "status": "scheduled",
            "has_attention": False,
            "task_id": task_id,
            "message": "已安排主动桌面观察",
        }

    def _current_task(self):
        if not self._last_task_id:
            return None
        return self._runtime.state.get_task(self._last_task_id)

    def _desktop_watch_blocker(self) -> str | None:
        try:
            if not self._runtime.is_hermes_ready():
                return "主动桌面观察需要 Hermes Agent 就绪"
        except Exception:
            return "主动桌面观察需要 Hermes Agent 就绪"

        runner = getattr(self._runtime, "task_runner", None)
        if runner is None:
            return "任务执行器尚未启动，暂时无法进行主动桌面观察"

        executor = getattr(runner, "executor", None)
        if not isinstance(executor, HermesExecutor) and getattr(executor, "name", "") != "HermesExecutor":
            return "主动桌面观察需要 Hermes 执行器；当前执行器不支持读取桌面截图"

        hermes_info = {}
        try:
            hermes_info = self._runtime.get_status().get("hermes", {})
        except Exception:
            hermes_info = {}
        limited_tools = set(hermes_info.get("limited_tools") or [])
        if "vision" in limited_tools:
            return "Hermes vision 工具受限，当前模型/配置无法读取截图；请在主控台运行 hermes setup 或 hermes doctor"
        return None

    def _schedule_desktop_watch_task(self) -> str:
        prompt = build_proactive_desktop_prompt(self._runtime)
        message_id = ""
        chat_session = getattr(self._runtime, "chat_session", None)
        if chat_session is not None:
            try:
                message_id = chat_session.add_user_message(prompt)
            except Exception:
                logger.debug("主动桌面观察写入聊天消息失败", exc_info=True)

        task = self._runtime.state.create_task(
            prompt,
            task_type=TaskType.SCREENSHOT,
            risk_level=RiskLevel.LOW,
        )
        if message_id and chat_session is not None:
            try:
                chat_session.link_message_to_task(message_id, task.task_id)
            except Exception:
                logger.debug("主动桌面观察消息关联任务失败", exc_info=True)
        self._last_task_id = task.task_id
        self._attention_task_id = None
        self._reported_failed_task_id = None
        self._last_check_at = time.monotonic()
        return task.task_id


def _compact_attention_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return "有新的主动观察结果"
    return value if len(value) <= 160 else value[:159].rstrip() + "…"
