"""任务执行策略

定义任务执行的抽象接口（ExecutionStrategy），以及两种实现：
  - SimulatedExecutor:  MVP 阶段模拟执行（sleep + 占位结果）
  - HermesExecutor:     未来 Hermes Agent 接入点（当前为存根）

TaskRunner 只依赖 ExecutionStrategy 接口，与具体执行实现解耦。
切换到真实 Hermes 只需：
  1. 补全 HermesExecutor.run()
  2. 在 TaskRunner 构造时传入 HermesExecutor 实例
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from packages.protocol.schemas import TaskInfo

logger = logging.getLogger(__name__)


# ── 抽象接口 ────────────────────────────────────────────────────

class ExecutionStrategy(ABC):
    """任务执行策略抽象接口

    run() 收到任务信息后，负责实际执行逻辑，并返回执行结果字符串。
    若执行失败，应抛出异常（由 TaskRunner._execute_with_state 统一捕获）。
    """

    @abstractmethod
    async def run(self, task: TaskInfo) -> str:
        """执行任务，返回结果字符串。失败则抛出异常。"""
        ...


# ── MVP 模拟执行器 ───────────────────────────────────────────────

_SIM_RUN_DELAY: float = 2.0      # PENDING → RUNNING 延迟（秒）
_SIM_COMPLETE_DELAY: float = 5.0  # RUNNING → COMPLETED 延迟（秒）


class SimulatedExecutor(ExecutionStrategy):
    """MVP 模拟执行器

    用 sleep 模拟任务耗时，成功后返回占位结果。
    不调用任何外部服务，保证离线可用。

    后续真正接 Hermes 时，用 HermesExecutor 替换此类，无需改动 TaskRunner。
    """

    async def run(self, task: TaskInfo) -> str:
        logger.debug("[Simulated] 开始执行任务 %s: %s", task.task_id, task.description)
        await asyncio.sleep(_SIM_RUN_DELAY)
        # 此处是 RUNNING 阶段的"工作"。
        # 真实版本中，这里是向 Hermes 提交 prompt 并等待响应。
        await asyncio.sleep(_SIM_COMPLETE_DELAY)
        return f"[模拟结果] {task.description[:80]}"


# ── Hermes 执行器（存根，待实现）────────────────────────────────

class HermesExecutor(ExecutionStrategy):
    """Hermes Agent 执行器（待接入）

    接入步骤：
      1. 安装并配置 Hermes Agent（通过 apps/installer/）
      2. 补全 run()：向 Hermes CLI 或 Hermes API 提交任务描述
      3. 等待 Hermes 返回结果，填入 result 字段
      4. 在 TaskRunner 构造时注入此实例替换 SimulatedExecutor

    当前为存根，调用后立即抛出 NotImplementedError。
    """

    async def run(self, task: TaskInfo) -> str:
        # TODO: 接入 Hermes Agent
        #   参考：apps/installer/hermes_check.py（验证可用性）
        #   参考：apps/core/runtime.py（is_hermes_ready()）
        #   预期实现：
        #     result = await hermes_client.submit(task.description)
        #     return result.output
        raise NotImplementedError(
            "HermesExecutor 尚未实现。"
            "请在此处接入 Hermes Agent 调用逻辑。"
        )
