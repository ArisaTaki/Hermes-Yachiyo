"""任务执行策略

定义任务执行的抽象接口（ExecutionStrategy），以及两种实现：
  - SimulatedExecutor:  MVP 阶段模拟执行（sleep + 占位结果），始终可用
  - HermesExecutor:     Hermes Agent subprocess CLI 真实调用

工厂函数 select_executor(runtime) 根据运行时状态自动选择执行器。
Hermes 就绪时工厂自动选用 HermesExecutor，无需修改其他代码。
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from packages.protocol.schemas import TaskInfo

if TYPE_CHECKING:
    from apps.core.chat_session import ChatSession
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)


# ── 自定义异常 ────────────────────────────────────────────────────────────────

class HermesCallError(RuntimeError):
    """Hermes Agent 调用失败

    携带结构化信息便于上层统一处理或写入 TaskInfo.error。
    """

    def __init__(self, message: str, returncode: int = -1, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr

    def to_error_string(self) -> str:
        """格式化为可写入 TaskInfo.error 的简洁字符串"""
        parts = [str(self)]
        if self.returncode != -1:
            parts.append(f"exit={self.returncode}")
        if self.stderr:
            stderr_detail = _compact_error_detail(self.stderr, max_chars=120)
            if stderr_detail and stderr_detail not in str(self):
                parts.append(f"stderr: {stderr_detail}")
        return " | ".join(parts)


# ── 结构化调用结果 ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class HermesInvokeResult:
    """hermes CLI 调用的结构化结果

    无论成功或失败都返回此结构，由调用方决定如何处理。
    避免用裸字符串传递结果，便于日志、测试和后续字段扩展。
    """

    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    error_message: str = ""
    hermes_session_id: Optional[str] = None  # 从 stdout 解析的 Hermes session ID
    hermes_title: Optional[str] = None       # 从 stdout 解析的 Hermes 自动标题

    @property
    def output(self) -> str:
        """任务结果：成功时为 stdout（去除 session_id 行），失败时为空串"""
        return self.stdout if self.success else ""

    def to_task_error(self) -> str:
        """格式化为可写入 TaskInfo.error 的字符串"""
        parts = [self.error_message] if self.error_message else []
        if self.returncode not in (-1, 0):
            parts.append(f"exit={self.returncode}")
        if self.stderr:
            parts.append(f"stderr: {self.stderr[:120]}")
        return " | ".join(parts) if parts else "未知错误"


# ── 独立 CLI 调用函数 ─────────────────────────────────────────────────────────

# Hermes CLI 命令前缀。
# hermes chat -q "<query>" -Q --source tool
#   -q: 非交互单次查询
#   -Q: 安静模式（仅输出最终结果）
#   --source tool: 标记为第三方集成调用
_HERMES_CMD: list[str] = ["hermes", "chat", "-q"]
_HERMES_FLAGS: list[str] = ["-Q", "--source", "tool"]

_EXEC_TIMEOUT_ENV = "HERMES_YACHIYO_EXEC_TIMEOUT_SECONDS"
_DEFAULT_EXEC_TIMEOUT: float = 30 * 60.0
_PROBE_TIMEOUT: float = 5.0   # hermes --version 探测超时（秒）
_STREAM_UPDATE_INTERVAL: float = 0.05
_BRIDGE_SCRIPT = Path(__file__).with_name("hermes_stream_bridge.py")
_ERROR_DETAIL_MAX_CHARS = 500
_ERROR_DETAIL_MAX_LINES = 12


def _read_exec_timeout() -> float:
    raw_value = os.getenv(_EXEC_TIMEOUT_ENV, "").strip()
    if not raw_value:
        return _DEFAULT_EXEC_TIMEOUT
    try:
        timeout = float(raw_value)
    except ValueError:
        logger.warning(
            "%s=%r 不是有效数字，使用默认 Hermes 执行超时 %.0fs",
            _EXEC_TIMEOUT_ENV,
            raw_value,
            _DEFAULT_EXEC_TIMEOUT,
        )
        return _DEFAULT_EXEC_TIMEOUT
    if timeout <= 0:
        logger.warning(
            "%s=%r 必须大于 0，使用默认 Hermes 执行超时 %.0fs",
            _EXEC_TIMEOUT_ENV,
            raw_value,
            _DEFAULT_EXEC_TIMEOUT,
        )
        return _DEFAULT_EXEC_TIMEOUT
    return timeout


def _format_exec_timeout(timeout: float) -> str:
    if timeout >= 60 and timeout % 60 == 0:
        return f"{int(timeout // 60)}min"
    return f"{timeout:.0f}s"


_EXEC_TIMEOUT: float = _read_exec_timeout()  # hermes chat -q 执行超时（秒）
_WEEKDAY_NAMES = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)

# 从 hermes 输出中解析 session id。quiet 模式输出 session_id，非 quiet 模式输出 Session。
_SESSION_ID_RE = re.compile(
    r"^(?:session_id|Session(?: ID)?):\s*(\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_TITLE_RE = re.compile(r"^Title:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_BOX_BORDER_RE = re.compile(
    r"^[╭╮╰╯┌┐└┘├┤┬┴┼╔╗╚╝╠╣╟╢╤╧╪│┃─━═\s]+$"
)
_HERMES_META_PREFIXES = (
    "Query:",
    "Source:",
    "Title:",
    "Duration:",
    "Messages:",
    "Resume this session",
    "hermes --resume",
)
_STREAM_BRIDGE_FALLBACK_MARKERS = (
    "无法定位 Hermes Python 解释器",
    "Hermes streaming bridge 文件不存在",
    "Hermes Python 解释器不存在",
    "启动 Hermes streaming bridge 失败",
    "ModuleNotFoundError",
    "ImportError",
    "No module named",
    "cannot import",
)

# bridge 内部原始异常模式 → 用户友好描述
# 这些异常由 hermes_stream_bridge.py 的 main() 捕获后以 "ExcType: msg" 格式输出，
# 在显示给用户前需要转换为可读提示。
_BRIDGE_RAW_EXCEPTION_TO_FRIENDLY: dict[str, str] = {
    "KeyError:": "Hermes provider 配置字段缺失",
    "AttributeError:": "Hermes API 结构不兼容",
    "TypeError:": "Hermes API 参数不兼容",
    "RuntimeError:": "Hermes 运行时错误",
    "ValueError:": "Hermes 配置值错误",
    "AssertionError:": "Hermes 断言失败",
}
_EMPTY_ERROR_DETAILS = {"", "none", "null"}
_AGENT_FAILURE_WITHOUT_DETAIL = (
    "Hermes 对话执行失败，但 Hermes Agent 没有返回错误详情。"
    "通常是模型/provider 配置、API Key、base URL 或网络请求失败；"
    "请运行 hermes setup 或 hermes config 检查当前模型配置。"
)


def _humanize_bridge_error(message: str) -> str:
    """把 bridge 输出的原始 Python 异常消息转换为用户可读提示。

    例：'KeyError: 'label'' → 'Hermes provider 配置字段缺失（KeyError: 'label'）'
    若不匹配任何已知异常前缀，原样返回。
    """
    if not message:
        return message
    for pattern, friendly in _BRIDGE_RAW_EXCEPTION_TO_FRIENDLY.items():
        if message.startswith(pattern):
            return f"{friendly}（{message}）"
    return message


def _is_empty_error_detail(value: str) -> bool:
    return value.strip().lower() in _EMPTY_ERROR_DETAILS


def _compact_error_detail(text: str, *, max_chars: int = _ERROR_DETAIL_MAX_CHARS) -> str:
    """压缩错误细节，保留末尾最有诊断价值的内容。"""
    cleaned = _ANSI_RE.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in cleaned.split("\n") if line.strip()]
    if not lines:
        return ""
    detail = "\n".join(lines[-_ERROR_DETAIL_MAX_LINES:])
    if len(detail) > max_chars:
        detail = "..." + detail[-max_chars:]
    return detail


def _bridge_failure_message(
    error_message: str,
    *,
    returncode: int,
    stderr: str,
) -> str:
    """为 bridge 进程级失败补充 stderr 摘要。"""
    message = error_message.strip()
    if not message:
        if returncode not in (-1, 0):
            message = f"Hermes streaming bridge 执行失败（exit={returncode}）"
        else:
            message = "Hermes streaming bridge 执行失败"

    stderr_detail = _compact_error_detail(stderr)
    if stderr_detail and "Hermes streaming bridge 执行失败" in message:
        return f"{message}\n{stderr_detail}"
    return message


def format_persona_description(
    description: str,
    persona_prompt: str = "",
    user_address: str = "",
    environment_context: str = "",
) -> str:
    """按共享助手资料包装用户请求，资料为空时保持原始描述。"""
    persona = (persona_prompt or "").strip()
    address = (user_address or "").strip()
    environment = (environment_context or "").strip()
    if not environment and not persona and not address:
        return description
    parts: list[str] = []
    if environment:
        parts.append(environment)
    if persona:
        parts.append(f"[人设设定]\n{persona}")
    if address:
        parts.append(f"[用户称呼]\n请称呼用户为：{address}")
    parts.append(f"[用户请求]\n{description}")
    return "\n\n".join(parts)


def _describe_day_period(hour: int) -> str:
    if 5 <= hour < 9:
        return "早上"
    if 9 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "晚上"
    return "深夜"


def format_environment_context(now: Optional[datetime] = None) -> str:
    """生成每轮对话的本地环境上下文。"""
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    offset = current.strftime("%z")
    timezone_label = f"UTC{offset[:3]}:{offset[3:]}" if offset else "本地时区"
    weekday = _WEEKDAY_NAMES[current.weekday()]
    period = _describe_day_period(current.hour)
    return (
        "[当前环境]\n"
        f"当前本地时间：{current.strftime('%Y-%m-%d %H:%M:%S')}"
        f"（{timezone_label}，{weekday}，{period}）\n"
        "请结合当前时间、日期与时段理解问候、计划和相对时间表达。"
    )


def _clean_hermes_line(line: str, strip_stream_padding: bool = False) -> Optional[str]:
    """过滤 Hermes CLI 的 Rich 边框和摘要行，保留真实回复文本。"""
    raw = _ANSI_RE.sub("", line).rstrip()
    stripped = raw.strip()
    if not stripped:
        return ""

    if stripped[0] in "╭╰┌└╔╚":
        return None
    if _BOX_BORDER_RE.fullmatch(stripped):
        return None

    border_wrapped = False
    if stripped.startswith(("│", "┃")):
        stripped = stripped.strip("│┃ ").rstrip()
        border_wrapped = True
    if stripped.endswith(("│", "┃")):
        stripped = stripped.rstrip("│┃ ").rstrip()
        border_wrapped = True
    if not stripped:
        return ""

    if stripped in {"$ Hermes", "⚕ Hermes", "Hermes"}:
        return None
    if any(stripped.startswith(prefix) for prefix in _HERMES_META_PREFIXES):
        return None
    if border_wrapped:
        return stripped

    if strip_stream_padding and raw.startswith("    "):
        raw = raw[4:]
        stripped = raw.strip()
        if any(stripped.startswith(prefix) for prefix in _HERMES_META_PREFIXES):
            return None
    return raw.rstrip()


def _dedupe_repeated_paragraphs(text: str) -> str:
    """去掉 CLI/渲染层导致的完全重复段落。"""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return ""

    paragraphs = re.split(r"\n\s*\n", text)
    seen: set[str] = set()
    unique: list[str] = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(paragraph)
    return "\n\n".join(unique)


def _sanitize_hermes_response(stdout: str) -> str:
    """清理 Hermes CLI 输出中的 UI 噪声和重复内容。"""
    text = _ANSI_RE.sub("", stdout).replace("\r\n", "\n").replace("\r", "\n")
    strip_stream_padding = (
        any(ch in text for ch in "╭╰┌└╔╚│┃")
        or "Resume this session with:" in text
    )
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        cleaned = _clean_hermes_line(line, strip_stream_padding=strip_stream_padding)
        if cleaned is None:
            continue
        cleaned_lines.append(cleaned)
    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return _dedupe_repeated_paragraphs(cleaned_text)


def _parse_hermes_output(stdout: str) -> tuple[str, Optional[str]]:
    """从 hermes stdout 中分离回复内容和 session id。

    hermes chat -Q 的输出格式：
      <回复内容>
      session_id: <ID>

    非 quiet 模式会额外输出 Rich 边框和会话摘要，此函数会清理这些噪声。

    Returns:
        (content, hermes_session_id)
    """
    matches = list(_SESSION_ID_RE.finditer(stdout))
    session_id = matches[-1].group(1) if matches else None
    content = _SESSION_ID_RE.sub("", stdout)
    return _sanitize_hermes_response(content), session_id


def _parse_hermes_title(stdout: str) -> Optional[str]:
    """从 Hermes 非 quiet 输出中解析自动生成的会话标题。"""
    matches = list(_TITLE_RE.finditer(_ANSI_RE.sub("", stdout)))
    if not matches:
        return None
    title = matches[-1].group(1).strip()
    return title or None


def _resolve_hermes_python(hermes_cmd: Optional[str] = None) -> Optional[str]:
    """从 hermes launcher shebang 找到 Hermes 自己的 Python 解释器。"""
    launcher = hermes_cmd or shutil.which("hermes")
    if not launcher:
        return None
    try:
        with open(launcher, "r", encoding="utf-8") as fh:
            first_line = fh.readline().strip()
    except OSError:
        return None
    if not first_line.startswith("#!"):
        return None
    python = first_line[2:].strip()
    if not python:
        return None
    if " " in python:
        python = python.split(" ", 1)[0]
    return python if os.path.exists(python) else None


def _parse_bridge_event(line: str) -> Optional[dict[str, Any]]:
    """解析 Hermes streaming bridge 输出的一行 NDJSON。"""
    line = (line or "").strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("忽略非 JSON bridge 输出: %s", line[:160])
        return None
    return event if isinstance(event, dict) else None


def _emit_stream_update(on_update: Callable[[str], None], content: str) -> None:
    """把流式内容写回聊天会话，隔离 UI 回写异常。"""
    if not content:
        return
    try:
        on_update(content)
    except Exception:
        logger.debug("Hermes 流式内容回写失败", exc_info=True)


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    """取消/超时时终止子进程并回收管道资源。"""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.communicate(), timeout=3.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()


async def _consume_stream_bridge(
    proc: asyncio.subprocess.Process,
    payload: dict[str, Any],
    on_update: Callable[[str], None],
) -> HermesInvokeResult:
    """消费 bridge 的 delta/done/error 事件并转换为 HermesInvokeResult。"""
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_task = asyncio.create_task(proc.stderr.read())
    parts: list[str] = []
    last_emitted = ""
    last_emit_at = 0.0
    final_response = ""
    error_message = ""
    hermes_session_id: Optional[str] = None
    hermes_title: Optional[str] = None
    failed = False
    saw_done_event = False
    started_at = time.monotonic()
    first_event_logged = False
    first_delta_logged = False

    try:
        while True:
            raw_line = await proc.stdout.readline()
            if not raw_line:
                break
            event = _parse_bridge_event(raw_line.decode(errors="replace"))
            if event is None:
                continue

            event_type = event.get("type")
            if not first_event_logged and event_type is not None:
                logger.info(
                    "[Hermes bridge] 首个事件: type=%s, elapsed=%.2fs",
                    event_type,
                    time.monotonic() - started_at,
                )
                first_event_logged = True
            if event_type == "delta":
                delta = event.get("delta")
                if not isinstance(delta, str) or not delta:
                    continue
                if not first_delta_logged:
                    logger.info(
                        "[Hermes bridge] 首个输出片段: elapsed=%.2fs",
                        time.monotonic() - started_at,
                    )
                    first_delta_logged = True
                parts.append(delta)
                content = "".join(parts)
                now = time.monotonic()
                if now - last_emit_at >= _STREAM_UPDATE_INTERVAL:
                    _emit_stream_update(on_update, content)
                    last_emitted = content
                    last_emit_at = now
            elif event_type == "done":
                saw_done_event = True
                response = event.get("response")
                final_response = response if isinstance(response, str) else ""
                sid = event.get("session_id")
                hermes_session_id = sid if isinstance(sid, str) and sid else hermes_session_id
                title = event.get("title")
                hermes_title = title if isinstance(title, str) and title else hermes_title
                failed = bool(event.get("failed"))
                if failed and _is_empty_error_detail(final_response):
                    final_response = ""
                raw_error = event.get("error") or event.get("message")
                if failed and isinstance(raw_error, str) and not _is_empty_error_detail(raw_error):
                    error_message = _humanize_bridge_error(raw_error.strip())
                logger.info(
                    "[Hermes bridge] 完成事件: elapsed=%.2fs, response_len=%d, failed=%s",
                    time.monotonic() - started_at,
                    len(final_response),
                    failed,
                )
            elif event_type == "error":
                raw_message = event.get("message")
                raw_message = raw_message if isinstance(raw_message, str) else "Hermes streaming bridge 调用失败"
                error_message = _humanize_bridge_error(raw_message)
                failed = True
            elif event_type == "boundary":
                # 流内边界标记，不含有效内容，直接忽略
                pass
            elif event_type is not None:
                # 未知事件类型：不崩溃，仅记录 debug 日志
                logger.debug("忽略未知 bridge 事件类型: %s", event_type)

        stderr_bytes = await stderr_task
        stderr = stderr_bytes.decode(errors="replace").strip()
        rc = await proc.wait()
    finally:
        if not stderr_task.done():
            stderr_task.cancel()

    content = final_response or "".join(parts)
    content = _dedupe_repeated_paragraphs(content)
    if content and content != last_emitted:
        _emit_stream_update(on_update, content)

    if failed and saw_done_event and not error_message:
        response_detail = _compact_error_detail(content)
        error_message = (
            f"Hermes 对话执行失败：{response_detail}"
            if response_detail
            else _AGENT_FAILURE_WITHOUT_DETAIL
        )

    logger.info(
        "[Hermes bridge] 进程结束: exit=%s, elapsed=%.2fs, stdout_len=%d, stderr_len=%d",
        rc,
        time.monotonic() - started_at,
        len(content),
        len(stderr),
    )

    if rc != 0 or failed:
        return HermesInvokeResult(
            success=False,
            stdout=content,
            stderr=stderr,
            returncode=rc,
            error_message=_bridge_failure_message(
                error_message,
                returncode=rc,
                stderr=stderr,
            ),
            hermes_session_id=hermes_session_id,
            hermes_title=hermes_title,
        )

    return HermesInvokeResult(
        success=True,
        stdout=content or f"[Hermes 执行完毕，无输出] {payload.get('description', '')[:60]}",
        stderr=stderr,
        returncode=rc,
        hermes_session_id=hermes_session_id,
        hermes_title=hermes_title,
    )


async def _invoke_hermes_stream_bridge(
    description: str,
    hermes_session_id: Optional[str],
    on_update: Callable[[str], None],
) -> HermesInvokeResult:
    """通过 Hermes agent callback 层获取真实 token 流，避免 CLI 终端 UI 噪声。"""
    started_at = time.monotonic()
    hermes_python = _resolve_hermes_python()
    if not hermes_python:
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message="无法定位 Hermes Python 解释器，不能启用流式 bridge",
        )
    if not _BRIDGE_SCRIPT.exists():
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message="Hermes streaming bridge 文件不存在",
        )

    payload = {
        "description": description,
        "resume": hermes_session_id,
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            hermes_python,
            str(_BRIDGE_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )
    except FileNotFoundError:
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message="Hermes Python 解释器不存在，不能启用流式 bridge",
        )
    except Exception as exc:
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message=f"启动 Hermes streaming bridge 失败: {exc}",
        )

    logger.info(
        "[Hermes bridge] 进程已启动: elapsed=%.2fs, resume=%s",
        time.monotonic() - started_at,
        bool(hermes_session_id),
    )

    try:
        return await asyncio.wait_for(
            _consume_stream_bridge(proc, payload, on_update),
            timeout=_EXEC_TIMEOUT,
        )
    except asyncio.CancelledError:
        await _terminate_process(proc)
        raise
    except asyncio.TimeoutError:
        await _terminate_process(proc)
        logger.warning(
            "[Hermes bridge] 执行超时: elapsed=%.2fs",
            time.monotonic() - started_at,
        )
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message=f"Hermes 执行超时（{_format_exec_timeout(_EXEC_TIMEOUT)}），进程已终止",
        )


def _should_fallback_from_stream_bridge(result: HermesInvokeResult) -> bool:
    """判断 stream bridge 失败是否应回退到普通 CLI。"""
    if result.success:
        return False
    detail = "\n".join(part for part in (result.error_message, result.stderr) if part)
    if any(marker in detail for marker in _STREAM_BRIDGE_FALLBACK_MARKERS):
        return True
    return (
        result.returncode not in (-1, 0)
        and "Hermes streaming bridge 执行失败" in detail
    )


async def invoke_hermes_cli(
    description: str,
    hermes_session_id: Optional[str] = None,
    on_update: Optional[Callable[[str], None]] = None,
) -> HermesInvokeResult:
    """向 Hermes Agent 发起一次 CLI 调用，返回结构化结果。

    此函数是 Hermes 调用的最小单元，职责单一：
      - 构造命令
      - 启动 subprocess
      - 等待结束（带超时）
      - 解析 session_id
      - 返回 HermesInvokeResult（成功或失败均返回，不抛出）

    调用命令：hermes chat -q "<query>" -Q --source tool [--resume SESSION_ID]
    若传入 on_update，则优先使用 Hermes streaming bridge 读取 agent token 回调；
    bridge 不可用时回退普通 CLI，仍返回最终结果。

    Args:
        description: 用户查询字符串，直接作为 -q 参数传入
        hermes_session_id: 若提供，附加 --resume 以延续上一次 Hermes 会话
        on_update: 流式内容更新回调，参数为清理后的当前完整回复

    Returns:
        HermesInvokeResult（不抛出异常，失败信息写入 result.error_message）
    """
    started_at = time.monotonic()
    if on_update is not None:
        stream_result = await _invoke_hermes_stream_bridge(
            description,
            hermes_session_id,
            on_update,
        )
        logger.info(
            "[Hermes] streaming bridge 返回: success=%s, elapsed=%.2fs",
            stream_result.success,
            time.monotonic() - started_at,
        )
        if stream_result.success or not _should_fallback_from_stream_bridge(stream_result):
            return stream_result

        logger.warning(
            "Hermes streaming bridge 不可用，回退普通 CLI: %s",
            stream_result.error_message,
        )
        return await invoke_hermes_cli(
            description,
            hermes_session_id=hermes_session_id,
            on_update=None,
        )

    cmd = [*_HERMES_CMD, description, *_HERMES_FLAGS]
    if hermes_session_id:
        cmd.extend(["--resume", hermes_session_id])
    logger.debug("[Hermes CLI] 执行: %s", " ".join(cmd))

    # ① 启动 subprocess
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message="hermes 命令未找到，请确认 Hermes Agent 已正确安装",
        )
    except Exception as exc:
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message=f"启动 hermes 进程失败: {exc}",
        )

    # ② 等待结束，带超时
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=_EXEC_TIMEOUT
        )
        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
    except asyncio.CancelledError:
        await _terminate_process(proc)
        raise
    except asyncio.TimeoutError:
        await _terminate_process(proc)
        logger.warning(
            "[Hermes CLI] 执行超时: elapsed=%.2fs",
            time.monotonic() - started_at,
        )
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message=f"Hermes 执行超时（{_format_exec_timeout(_EXEC_TIMEOUT)}），进程已终止",
        )

    rc = proc.returncode if proc.returncode is not None else -1

    # ③ 判断成功
    if rc != 0:
        # 对 exit=2（argparse usage error）给出友好提示而非原始 stderr
        if rc == 2:
            err_msg = "Hermes 命令调用失败，请检查 Hermes Agent 版本是否兼容"
        else:
            err_msg = f"Hermes 执行失败（exit={rc}）"
        return HermesInvokeResult(
            success=False,
            stdout=_sanitize_hermes_response(stdout),
            stderr=stderr,
            returncode=rc,
            error_message=err_msg,
        )

    # ④ 解析回复内容和 session_id
    content, parsed_session_id = _parse_hermes_output(stdout)
    parsed_title = _parse_hermes_title(stdout)
    logger.info(
        "[Hermes CLI] 执行完成: exit=%s, elapsed=%.2fs, stdout_len=%d, stderr_len=%d",
        rc,
        time.monotonic() - started_at,
        len(stdout),
        len(stderr),
    )

    return HermesInvokeResult(
        success=True,
        stdout=content or f"[Hermes 执行完毕，无输出] {description[:60]}",
        stderr=stderr,
        returncode=rc,
        hermes_session_id=parsed_session_id,
        hermes_title=parsed_title,
    )


def probe_hermes_available() -> bool:
    """同步探测 hermes 命令是否可用（供 is_available() 使用）。

    独立函数便于单独测试，不依赖类实例。
    """
    try:
        result = subprocess.run(
            ["hermes", "--version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning(
                "probe_hermes_available: --version 返回非零 (%d)", result.returncode
            )
        return result.returncode == 0
    except FileNotFoundError:
        logger.info("probe_hermes_available: hermes 命令未找到")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("probe_hermes_available: 超时（%.1fs）", _PROBE_TIMEOUT)
        return False
    except Exception as exc:
        logger.warning("probe_hermes_available: 异常: %s", exc)
        return False


# ── 抽象接口 ─────────────────────────────────────────────────────────────────

class ExecutionStrategy(ABC):
    """任务执行策略抽象接口"""

    @abstractmethod
    async def run(self, task: TaskInfo) -> str:
        """执行任务，返回结果字符串。失败则抛出异常（TaskRunner 负责捕获）。"""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


# ── MVP 模拟执行器 ────────────────────────────────────────────────────────────

_SIM_RUN_DELAY: float = 2.0
_SIM_COMPLETE_DELAY: float = 5.0


class SimulatedExecutor(ExecutionStrategy):
    """MVP 模拟执行器（sleep + 占位结果，离线可用）"""

    async def run(self, task: TaskInfo) -> str:
        logger.debug("[Simulated] 开始执行: %s", task.task_id)
        await asyncio.sleep(_SIM_RUN_DELAY)
        await asyncio.sleep(_SIM_COMPLETE_DELAY)
        return f"[模拟结果] {task.description[:80]}"


# ── Hermes 执行器 ─────────────────────────────────────────────────────────────

class HermesExecutor(ExecutionStrategy):
    """Hermes Agent 执行器（委托 invoke_hermes_cli() 做实际调用）

    调用链：
      run(task)
        └─ _call_hermes(description)
             └─ invoke_hermes_cli(description, hermes_session_id) → HermesInvokeResult
                  ├─ success=True  → 返回 result.output + 存储 session_id
                  └─ success=False → 抛出 HermesCallError

    多轮对话：
      通过 chat_session.hermes_session_id 传递给 --resume，
      成功后将返回的新 session_id 写回 chat_session。
    """

    def __init__(
        self,
        fallback_to_simulated: bool = False,
        chat_session: Optional["ChatSession"] = None,
        persona_prompt_getter: Optional[Callable[[], str]] = None,
        user_address_getter: Optional[Callable[[], str]] = None,
    ) -> None:
        self._fallback = fallback_to_simulated
        self._sim = SimulatedExecutor()
        self._chat_session = chat_session
        self._persona_prompt_getter = persona_prompt_getter
        self._user_address_getter = user_address_getter

    def set_chat_session(self, chat_session: Optional["ChatSession"]) -> None:
        """更新后续任务使用的聊天会话引用。"""
        self._chat_session = chat_session

    def is_available(self) -> bool:
        """探测 Hermes Agent 是否可用（委托 probe_hermes_available()）"""
        return probe_hermes_available()

    async def run(self, task: TaskInfo) -> str:
        logger.info("[Hermes] 开始执行任务: %s", task.task_id)
        try:
            result = await self._call_hermes(task)
            logger.info("[Hermes] 任务执行完成: %s", task.task_id)
            return result
        except HermesCallError as exc:
            if self._fallback:
                logger.warning(
                    "[Hermes] 调用失败，回退 SimulatedExecutor: %s | %s",
                    task.task_id, exc,
                )
                return await self._sim.run(task)
            raise

    async def _call_hermes(self, task: TaskInfo) -> str:
        """调用 invoke_hermes_cli()，将 HermesInvokeResult 映射为结果字符串或异常。

        成功 → 返回 result.output + 记录 hermes_session_id
        失败 → 抛出 HermesCallError
        """
        # 获取当前 hermes session id 用于 --resume
        persona_prompt = ""
        if self._persona_prompt_getter is not None:
            try:
                persona_prompt = self._persona_prompt_getter()
            except Exception:
                logger.debug("读取助手人设 Prompt 失败", exc_info=True)
        user_address = ""
        if self._user_address_getter is not None:
            try:
                user_address = self._user_address_getter()
            except Exception:
                logger.debug("读取用户称呼失败", exc_info=True)
        description = format_persona_description(
            task.description,
            persona_prompt,
            user_address,
            format_environment_context(),
        )
        chat_session = self._chat_session
        hermes_sid = None
        if chat_session is not None:
            hermes_sid = chat_session.hermes_session_id

        def on_update(content: str) -> None:
            if chat_session is None:
                return
            from apps.core.chat_session import MessageStatus

            chat_session.upsert_assistant_message(
                task_id=task.task_id,
                content=content,
                status=MessageStatus.PROCESSING,
            )

        started_at = time.monotonic()
        invoke_result = await invoke_hermes_cli(
            description,
            hermes_session_id=hermes_sid,
            on_update=on_update if chat_session is not None else None,
        )
        elapsed = time.monotonic() - started_at

        if invoke_result.success:
            logger.debug(
                "[Hermes] 调用成功: returncode=%d, elapsed=%.2fs, stdout_len=%d, session=%s",
                invoke_result.returncode,
                elapsed,
                len(invoke_result.stdout),
                invoke_result.hermes_session_id,
            )
            # 记录 session_id 以便后续 --resume
            if invoke_result.hermes_session_id and chat_session is not None:
                chat_session.set_hermes_session_id(invoke_result.hermes_session_id)
            if invoke_result.hermes_title and chat_session is not None:
                chat_session.set_session_title(invoke_result.hermes_title)
            return invoke_result.output

        # 失败：结构化日志 + 结构化异常
        logger.warning(
            "[Hermes] 调用失败: returncode=%d, elapsed=%.2fs | %s",
            invoke_result.returncode,
            elapsed,
            invoke_result.error_message,
        )
        raise HermesCallError(
            invoke_result.error_message,
            returncode=invoke_result.returncode,
            stderr=invoke_result.stderr,
        )


# ── 执行器选择工厂 ────────────────────────────────────────────────────────────

def select_executor(runtime: "HermesRuntime | None" = None) -> ExecutionStrategy:
    """根据运行时状态选择最优执行器

    1. runtime 已就绪 且 probe_hermes_available() → HermesExecutor（附带 ChatSession）
    2. 其他 → SimulatedExecutor（安全回退）
    """
    if runtime is not None and runtime.is_hermes_ready():
        if probe_hermes_available():
            logger.info("select_executor: 选用 HermesExecutor（hermes chat -q）")
            return HermesExecutor(
                chat_session=runtime.chat_session,
                persona_prompt_getter=lambda: runtime.config.assistant.persona_prompt,
                user_address_getter=lambda: runtime.config.assistant.user_address,
            )
        logger.info(
            "select_executor: Hermes 报告就绪但命令不可用，回退 SimulatedExecutor"
        )
    else:
        logger.info("select_executor: Hermes 未就绪，使用 SimulatedExecutor")

    return SimulatedExecutor()
