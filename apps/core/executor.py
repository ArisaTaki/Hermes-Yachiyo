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
import logging
import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from packages.protocol.schemas import TaskInfo

if TYPE_CHECKING:
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
            parts.append(f"stderr: {self.stderr[:120]}")
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

    @property
    def output(self) -> str:
        """任务结果：成功时为 stdout，失败时为空串"""
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

_EXEC_TIMEOUT: float = 60.0   # hermes chat -q 执行超时（秒）
_PROBE_TIMEOUT: float = 5.0   # hermes --version 探测超时（秒）


async def invoke_hermes_cli(description: str) -> HermesInvokeResult:
    """向 Hermes Agent 发起一次 CLI 调用，返回结构化结果。

    此函数是 Hermes 调用的最小单元，职责单一：
      - 构造命令
      - 启动 subprocess
      - 等待结束（带超时）
      - 返回 HermesInvokeResult（成功或失败均返回，不抛出）

    HermesExecutor._call_hermes() 调用此函数并根据 result.success 决定后续处理。
    若 CLI 接口变更（如改为 HTTP API），只需替换本函数，类逻辑不变。

    调用命令：hermes chat -q "<query>" -Q --source tool

    Args:
        description: 用户查询字符串，直接作为 -q 参数传入

    Returns:
        HermesInvokeResult（不抛出异常，失败信息写入 result.error_message）
    """
    cmd = [*_HERMES_CMD, description, *_HERMES_FLAGS]
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
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return HermesInvokeResult(
            success=False,
            returncode=-1,
            error_message=f"Hermes 执行超时（{_EXEC_TIMEOUT:.0f}s），进程已终止",
        )

    stdout = stdout_bytes.decode(errors="replace").strip()
    stderr = stderr_bytes.decode(errors="replace").strip()
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
            stdout=stdout,
            stderr=stderr,
            returncode=rc,
            error_message=err_msg,
        )

    return HermesInvokeResult(
        success=True,
        stdout=stdout or f"[Hermes 执行完毕，无输出] {description[:60]}",
        stderr=stderr,
        returncode=rc,
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
             └─ invoke_hermes_cli(description) → HermesInvokeResult
                  ├─ success=True  → 返回 result.output（写入 TaskInfo.result）
                  └─ success=False → 抛出 HermesCallError（写入 TaskInfo.error）

    回退策略：
      - Bridge 启动时：is_available()=False → select_executor() 全局使用 Simulated
      - 执行阶段：失败默认抛出（TaskRunner 标记 FAILED，错误可见）
      - fallback_to_simulated=True：失败降级 Simulated（调试用）

    CLI 接口变更只需修改 invoke_hermes_cli() 函数，本类无需改动。
    """

    def __init__(self, fallback_to_simulated: bool = False) -> None:
        self._fallback = fallback_to_simulated
        self._sim = SimulatedExecutor()

    def is_available(self) -> bool:
        """探测 Hermes Agent 是否可用（委托 probe_hermes_available()）"""
        return probe_hermes_available()

    async def run(self, task: TaskInfo) -> str:
        logger.info("[Hermes] 开始执行任务: %s", task.task_id)
        try:
            result = await self._call_hermes(task.description)
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

    async def _call_hermes(self, description: str) -> str:
        """调用 invoke_hermes_cli()，将 HermesInvokeResult 映射为结果字符串或异常。

        成功 → 返回 result.output（供 TaskRunner 写入 TaskInfo.result）
        失败 → 抛出 HermesCallError（供 TaskRunner 写入 TaskInfo.error）
        """
        invoke_result = await invoke_hermes_cli(description)

        if invoke_result.success:
            logger.debug(
                "[Hermes] 调用成功: returncode=%d, stdout_len=%d",
                invoke_result.returncode,
                len(invoke_result.stdout),
            )
            return invoke_result.output

        # 失败：结构化日志 + 结构化异常
        logger.warning(
            "[Hermes] 调用失败: returncode=%d | %s",
            invoke_result.returncode,
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

    1. runtime 已就绪 且 probe_hermes_available() → HermesExecutor
    2. 其他 → SimulatedExecutor（安全回退）
    """
    if runtime is not None and runtime.is_hermes_ready():
        if probe_hermes_available():
            logger.info("select_executor: 选用 HermesExecutor（hermes chat -q）")
            return HermesExecutor()
        logger.info(
            "select_executor: Hermes 报告就绪但命令不可用，回退 SimulatedExecutor"
        )
    else:
        logger.info("select_executor: Hermes 未就绪，使用 SimulatedExecutor")

    return SimulatedExecutor()
