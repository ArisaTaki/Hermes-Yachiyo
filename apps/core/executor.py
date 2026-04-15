"""任务执行策略

定义任务执行的抽象接口（ExecutionStrategy），以及两种实现：
  - SimulatedExecutor:  MVP 阶段模拟执行（sleep + 占位结果），始终可用
  - HermesExecutor:     Hermes Agent 接入骨架，Hermes 就绪时可切换

工厂函数 select_executor(runtime) 根据运行时状态自动选择执行器。
切换到真实 Hermes 只需：
  1. 补全 HermesExecutor._call_hermes()
  2. runtime.is_hermes_ready() 返回 True，工厂自动选用 HermesExecutor
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

_SIM_RUN_DELAY: float = 2.0       # 模拟"开始处理"延迟（秒）
_SIM_COMPLETE_DELAY: float = 5.0  # 模拟"处理中"延迟（秒）


class SimulatedExecutor(ExecutionStrategy):
    """MVP 模拟执行器

    用 sleep 模拟任务耗时，成功后返回占位结果。
    - 不调用任何外部服务，离线可用
    - Hermes 未安装时的安全回退
    - 用于开发/测试场景

    后续接 Hermes 时，工厂函数 select_executor() 会自动选用 HermesExecutor，
    本类无需改动。
    """

    async def run(self, task: TaskInfo) -> str:
        logger.debug("[Simulated] 开始执行: %s", task.task_id)
        # 模拟"排队 → 开始处理"的延迟
        await asyncio.sleep(_SIM_RUN_DELAY)
        # 模拟"处理中"的耗时
        await asyncio.sleep(_SIM_COMPLETE_DELAY)
        return f"[模拟结果] {task.description[:80]}"


# ── Hermes 执行器 ─────────────────────────────────────────────────────────────

class HermesExecutor(ExecutionStrategy):
    """Hermes Agent 执行器

    当前状态：最小接入骨架
      - 启动时验证 Hermes 命令可用性
      - run() 中预留 _call_hermes() 调用点
      - _call_hermes() 尚未实现真实 Hermes 调用，直接抛出 NotImplementedError

    接入步骤（后续实现时按顺序操作）：
      1. 确认 Hermes Agent 接口形式（CLI subprocess / HTTP API / SDK）
      2. 补全 _call_hermes(description) 实现
      3. 确认 runtime.is_hermes_ready() 为 True
      4. select_executor(runtime) 将自动选用本类

    失败回退策略：
      - is_available() 返回 False → select_executor() 回退到 SimulatedExecutor
      - run() 内部调用失败 → 抛出异常 → TaskRunner 标记任务 FAILED（不静默吞掉）
    """

    # Hermes CLI 命令超时（秒）
    _PROBE_TIMEOUT: float = 5.0
    _EXEC_TIMEOUT: float = 60.0

    def is_available(self) -> bool:
        """探测 Hermes Agent 当前是否可用（同步快速检查）

        检查内容：
          - hermes 命令是否存在于 PATH
          - hermes --version 是否可正常执行

        此方法供 select_executor() 调用，不应阻塞主线程超过 _PROBE_TIMEOUT。
        """
        try:
            result = subprocess.run(
                ["hermes", "--version"],
                capture_output=True,
                text=True,
                timeout=self._PROBE_TIMEOUT,
            )
            available = result.returncode == 0
            if not available:
                logger.warning(
                    "HermesExecutor: hermes --version 返回非零 (%d)", result.returncode
                )
            return available
        except FileNotFoundError:
            logger.info("HermesExecutor: hermes 命令未找到")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("HermesExecutor: hermes --version 超时")
            return False
        except Exception as exc:
            logger.warning("HermesExecutor: 探测异常: %s", exc)
            return False

    async def run(self, task: TaskInfo) -> str:
        """执行任务：调用 Hermes Agent 并返回结果

        当前阶段：调用 _call_hermes() 存根（抛出 NotImplementedError）。
        实现 _call_hermes() 后，此方法无需修改。
        """
        logger.info("[Hermes] 开始执行任务: %s", task.task_id)
        result = await self._call_hermes(task.description)
        logger.info("[Hermes] 任务执行完成: %s", task.task_id)
        return result

    async def _call_hermes(self, description: str) -> str:
        """向 Hermes Agent 提交任务并等待结果（待实现）

        实现时选择以下其中一种方式：

        方式 A — subprocess CLI（最简单，适合 MVP）：
            proc = await asyncio.create_subprocess_exec(
                "hermes", "run", "--prompt", description,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), self._EXEC_TIMEOUT)
            if proc.returncode != 0:
                raise RuntimeError(f"Hermes 执行失败: {stderr.decode()}")
            return stdout.decode().strip()

        方式 B — Hermes HTTP API（更稳定，适合后续演进）：
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{hermes_api_url}/run",
                    json={"prompt": description},
                    timeout=self._EXEC_TIMEOUT,
                )
                resp.raise_for_status()
                return resp.json()["output"]

        TODO: 确认 Hermes Agent 接口形式后选择并实现上述方式之一。
        """
        raise NotImplementedError(
            "HermesExecutor._call_hermes() 尚未实现。\n"
            "请补全此方法以接入 Hermes Agent。\n"
            "当前自动回退到 SimulatedExecutor。"
        )


# ── 执行器选择工厂 ────────────────────────────────────────────────────────────

def select_executor(runtime: "HermesRuntime | None" = None) -> ExecutionStrategy:
    """根据运行时状态选择最优执行器

    选择策略（优先级从高到低）：
      1. runtime 已就绪 且 HermesExecutor.is_available() → HermesExecutor
      2. 其他情况 → SimulatedExecutor（安全回退）

    Args:
        runtime: HermesRuntime 实例（可为 None，None 时直接回退）

    Returns:
        选中的 ExecutionStrategy 实例
    """
    if runtime is not None and runtime.is_hermes_ready():
        hermes_exec = HermesExecutor()
        if hermes_exec.is_available():
            logger.info("select_executor: 选用 HermesExecutor")
            return hermes_exec
        logger.info(
            "select_executor: Hermes 报告就绪但命令不可用，回退 SimulatedExecutor"
        )
    else:
        logger.info("select_executor: Hermes 未就绪，使用 SimulatedExecutor")

    return SimulatedExecutor()
