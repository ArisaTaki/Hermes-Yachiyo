"""Handler 共享格式化工具

提供统一的状态标签、时间格式化、错误分类格式化工具函数。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

# 完整标签（含文字）
STATUS_LABEL: dict[str, str] = {
    "pending":   "⏳ 等待中",
    "running":   "🔄 运行中",
    "completed": "✅ 已完成",
    "cancelled": "🚫 已取消",
    "failed":    "❌ 已失败",
}

# 仅图标（用于列表紧凑展示）
STATUS_ICON: dict[str, str] = {
    "pending":   "⏳",
    "running":   "🔄",
    "completed": "✅",
    "cancelled": "🚫",
    "failed":    "❌",
}


def fmt_status(status: str) -> str:
    """status 枚举值 → 带图标中文标签"""
    return STATUS_LABEL.get(status, f"❓ {status}")


def fmt_status_icon(status: str) -> str:
    """status 枚举值 → 仅图标"""
    return STATUS_ICON.get(status, "❓")


def fmt_uptime(seconds: float) -> str:
    """秒数 → 人类可读运行时长（如 '2h 3m 5s' / '5m 3s' / '3s'）"""
    secs = int(seconds)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def fmt_dt(dt_str: str) -> str:
    """ISO 8601 字符串 → 短格式 'MM-DD HH:MM:SS'"""
    if not dt_str:
        return "—"
    try:
        m = re.match(r"\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", str(dt_str))
        if m:
            return f"{m.group(1)} {m.group(2)}"
    except Exception:
        pass
    return str(dt_str)[:19]


# ── 错误分类与格式化 ────────────────────────────────────


def fmt_error(exc: Exception, command: str = "") -> str:
    """将异常分类为统一的 QQ 可读错误消息。

    分类规则：
      - 连接失败 / 拒绝 → Bridge 不可达
      - 超时           → Bridge 响应超时
      - HTTP 5xx       → Bridge 内部错误
      - HTTP 4xx       → 请求错误（含服务端返回的可读消息）
      - 其他           → 未知错误

    Args:
        exc:     捕获到的异常
        command: 子命令名（用于提示上下文，可省略）

    Returns:
        适合直接发回 QQ 的错误文本
    """
    try:
        import httpx  # 仅在运行时导入，避免强制依赖

        if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError)):
            return (
                "⚠️ 无法连接到 Hermes-Yachiyo\n"
                "请确认桌面应用正在运行，Bridge 已启用"
            )

        if isinstance(exc, httpx.ConnectTimeout):
            return (
                "⚠️ 连接 Hermes-Yachiyo 超时\n"
                "请检查桌面应用是否正常运行"
            )

        if isinstance(exc, httpx.ReadTimeout):
            cmd_hint = f" /y {command}" if command else ""
            return (
                f"⚠️ 请求{cmd_hint} 超时\n"
                "Bridge 响应过慢，请稍后重试"
            )

        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            return _fmt_http_error(status_code, str(exc))

    except ImportError:
        pass

    # RuntimeError 由 _raise_readable() 生成，格式为 "[状态码] 消息"
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        m = re.match(r"\[(\d{3})\]\s*(.*)", msg, re.DOTALL)
        if m:
            return _fmt_http_error(int(m.group(1)), m.group(2).strip())
        return f"⚠️ 执行失败\n{msg}"

    return f"⚠️ 未知错误\n{exc}"


def _fmt_http_error(status_code: int, detail: str) -> str:
    """HTTP 状态码 + 详情 → QQ 可读文本。"""
    if status_code == 503:
        return (
            "⚠️ Hermes Agent 未就绪\n"
            "请在桌面应用中确认 Hermes 安装状态"
        )
    if status_code == 404:
        return f"⚠️ 资源不存在\n{detail or '请求的资源未找到'}"
    if status_code == 422:
        return f"⚠️ 请求参数有误\n{detail or '请检查命令格式'}"
    if status_code >= 500:
        return (
            f"⚠️ Bridge 内部错误 [{status_code}]\n"
            f"{detail or '请查看桌面应用日志'}"
        )
    if status_code >= 400:
        return f"⚠️ 请求错误 [{status_code}]\n{detail or '请检查命令格式'}"
    return f"⚠️ 请求失败 [{status_code}]\n{detail or ''}"
