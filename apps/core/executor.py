"""任务执行策略

定义任务执行的抽象接口（ExecutionStrategy），以及两种实现：
  - SimulatedExecutor:  MVP 阶段模拟执行（sleep + 占位结果），始终可用
  - HermesExecutor:     Hermes Agent subprocess CLI 真实调用

工厂函数 select_executor(runtime) 根据运行时状态自动选择执行器。
Hermes 就绪时工厂自动选用 HermesExecutor，无需修改其他代码。
"""

from __future__ import annotations

import asyncio
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

    携带退出码与标准错误输出，便于上层统一处理。
    """

    def __init__(self, message: str, returncode: int = -1, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


# ── 抽象接口 ─────────────────────────────────────────────────────────────────

class ExecutionStrategy(ABC):
    """任务执行策略抽象接口

    run() 接收任务信息，负责实际执行，返回结果字符串。
    执行失败应抛出异常（由 TaskRunner._execute_with_state 统一捕获处理）。
    """

    @abstractmethod
    async def run(self, task: TaskInfo) -> str:
        """执行任务，返回结果字符串。失败则抛出异常。"""
        ...

    @property
    def name(self) -> str:
        """执行器名称，用于日志与状态展示"""
        return type(self).__name__


# ── MVP 模拟执行器 ────────────────────────────────────────────────────────────

_SIM_RUN_DELAY: float = 2.0
_SIM_COMPLETE_DELAY: float = 5.0


class SimulatedExecutor(ExecutionStrategy):
    """MVP 模拟执行器

    用 sleep 模拟任务耗时，成功后返回占位结果。
    - 不调用任何外部服务，离线可用
    - Hermes 未安装时的安全回退
    """

    async def run(self, task: TaskInfo) -> str:
        logger.debug("[Simulated] 开始执行: %s", task.task_id)
        await asyncio.sleep(_SIM_RUN_DELAY)
        await asyncio.sleep(_SIM_COMPLETE_DELAY)
        return f"[模拟结果] {task.description[:80]}"


# ── Hermes 执行器 ─────────────────────────────────────────────────────────────

# Hermes CLI 调用命令前缀。
# 当前假设：hermes run --prompt "<description>"
# 若接口变更，只需修改此常量。
_HERMES_CMD: list[str] = ["hermes", "run", "--prompt"]


class HermesExecutor(ExecutionStrategy):
    """Hermes Agent 执行器（subprocess CLI 实现）

    调用链：
      run(task)
        └─ _call_hermes(description)
             └─ asyncio.create_subprocess_exec("hermes", "run", "--prompt", description)
                  ├─ returncode == 0 → 返回 stdout
                  └─ returncode != 0 → 抛出 HermesCallError

    回退策略：
      - select_executor() 阶段：is_available() 为 False → 使用 SimulatedExecutor
      - 执行阶段：_call_hermes() 抛出 → TaskRunner 标记任务 FAILED（错误可见）
      - fallback_to_simulated=True 时：单次失败降级 Simulated（调试用，不建议生产）

    若 Hermes Agent 未来改为 HTTP API，只需替换 _call_hermes()，其余逻辑不变。
    """

    _PROBE_TIMEOUT: float = 5.0   # hermes --version 探测超时
    _EXEC_TIMEOUT: float = 60.0   # hermes run 执行超时

    def __init__(self, fallback_to_simulated: bool = False) -> None:
        """
        Args:
            fallback_to_simulated: 为 True 时，单次任务调用失败后回退 SimulatedExecutor
                                   而非标记 FAILED。适合临时调试，生产保持默认 False。
        """
        self._fallback = fallback_to_simulated
        self._sim = SimulatedExecutor()

    def is_available(self) -> bool:
        """探测 Hermes Agent 当前是否可用（同步快速检查）

        检查：hermes 命令存在于 PATH 且 --version 正常执行。
        供 select_executor() 在 Bridge 启动时调用，不应超过 _PROBE_TIMEOUT。
        """
        try:
            result = subprocess.run(
                ["hermes", "--version"],
                capture_output=True,
                text=True,
                timeout=self._PROBE_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning(
                    "HermesExecutor: hermes --version 返回非零 (%d)", result.returncode
                )
            return result.returncode == 0
        except FileNotFoundError:
            logger.info("HermesExecutor: hermes 命令未找到")
            return False
        except subprocess.TimeoutExpired:
            logger.warning(
                "HermesExecutor: hermes --version 超时（%.1fs）", self._PROBE_TIMEOUT
            )
            return False
        except Exception as exc:
            logger.warning("HermesExecutor: 探测异常: %s", exc)
            return False

    async def run(self, task: TaskInfo) -> str:
        """执行任务：调用 Hermes Agent subprocess 并返回输出

        失败时若 fallback_to_simulated=True 则降级到模拟执行，否则抛出异常。
        """
        logger.info("[Hermes] 开始执行任务: %s", task.task_id)
        try:
            result = await self._call_hermes(task.description)
            logger.info("[Hermes] 任务执行完成: %s", task.task_id)
            return result
        except (HermesCallError, asyncio.TimeoutError) as exc:
            if self._fallback:
                logger.warning(
                    "[Hermes] 调用失败，回退 SimulatedExecutor: %s | 原因: %s",
                    task.task_id,
                    exc,
                )
                return await self._sim.run(task)
            raise

    async def _call_hermes(self, description: str) -> str:
        """向 Hermes Agent 提交任务并等待输出

        执行命令：hermes run --prompt "<description>"

        返回：stdout 内容（strip 后），若为空返回占位说明。
        失败：returncode != 0 → HermesCallError；超时 → asyncio.TimeoutError。

        若 Hermes 接口改为 HTTP API，只需替换本方法：
          async with httpx.AsyncClient() as c:
              resp = await c.post(f"{hermes_url}/run",
                                  json={"prompt": description},
                                  timeout=self._EXEC_TIMEOUT)
              resp.raise_for_status()
              return resp.json()["output"]
        """
        cmd = [*_HERMES_CMD, description]
        logger.debug("[Hermes] 执行命令: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise HermesCallError(
                "hermes 命令未找到，请确认 Hermes Agent 已正确安装",
                returncode=-1,
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._EXEC_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise asyncio.TimeoutError(
                f"Hermes 执行超时（{self._EXEC_TIMEOUT:.0f}s），进程已终止"
            )

        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()

        if proc.returncode != 0:
            raise HermesCallError(
                f"Hermes 执行失败（exit={proc.returncode}）: {stderr[:200]}",
                returncode=proc.returncode,
                stderr=stderr,
            )

        return stdout or f"[Hermes 执行完毕，无输出] {description[:60]}"


# ── 执行器选择工厂 ────────────────────────────────────────────────────────────

def select_executor(runtime: "HermesRuntime | None" = None) -> ExecutionStrategy:
    """根据运行时状态选择最优执行器

    策略（优先级从高到低）：
      1. runtime 已就绪 且 HermesExecutor.is_available() → HermesExecutor
      2. 其他情况 → SimulatedExecutor（安全回退）
    """
    if runtime is not None and runtime.is_hermes_ready():
        hermes_exec = HermesExecutor()
        if hermes_exec.is_available():
            logger.info("select_executor: 选用 HermesExecutor（hermes run --prompt）")
            return hermes_exec
        logger.info(
            "select_executor: Hermes 报告就绪但命令不可用，回退 SimulatedExecutor"
        )
    else:
        logger.info("select_executor: Hermes 未就绪，使用 SimulatedExecutor")

    return SimulatedExecutor()
