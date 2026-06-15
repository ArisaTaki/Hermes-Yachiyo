"""Execution budget guards for native Agent and Workflow runs."""

from __future__ import annotations

import time
from dataclasses import dataclass

from apps.shell.agent.runtime.errors import AgentRuntimeError


@dataclass(frozen=True)
class RunBudgetLimits:
    max_model_calls: int = 50
    max_tool_calls: int = 100
    max_terminal_calls: int = 10
    max_run_duration_seconds: int = 600
    max_workflow_steps: int = 200
    max_model_output_chars: int = 200_000
    max_tool_output_chars: int = 100_000
    max_context_chars: int = 200_000


@dataclass
class RunBudget:
    limits: RunBudgetLimits
    started_at_epoch: float
    model_calls_used: int = 0
    tool_calls_used: int = 0
    terminal_calls_used: int = 0

    def check_duration(self) -> None:
        elapsed = max(0.0, time.time() - self.started_at_epoch)
        if elapsed > max(1, int(self.limits.max_run_duration_seconds)):
            raise AgentRuntimeError(
                "Run 已超过 "
                f"max_run_duration_seconds={self.limits.max_run_duration_seconds} 的执行预算"
            )

    def check_context(self, context_chars: int) -> None:
        self.check_duration()
        if context_chars > max(1, int(self.limits.max_context_chars)):
            raise AgentRuntimeError(
                f"Run 上下文超过 max_context_chars={self.limits.max_context_chars} 的执行预算"
            )

    def claim_model_call(self) -> None:
        self.check_duration()
        if self.model_calls_used >= max(1, int(self.limits.max_model_calls)):
            raise AgentRuntimeError(
                f"Run 已超过 max_model_calls={self.limits.max_model_calls} 的执行预算"
            )
        self.model_calls_used += 1

    def claim_tool_call(self, tool_name: str, *, terminal_execution: bool = False) -> None:
        self.check_duration()
        if self.tool_calls_used >= max(1, int(self.limits.max_tool_calls)):
            raise AgentRuntimeError(
                f"Run 已超过 max_tool_calls={self.limits.max_tool_calls} 的执行预算"
            )
        if terminal_execution and self.terminal_calls_used >= max(
            0,
            int(self.limits.max_terminal_calls),
        ):
            raise AgentRuntimeError(
                f"Run 已超过 max_terminal_calls={self.limits.max_terminal_calls} 的执行预算"
            )
        self.tool_calls_used += 1
        if terminal_execution:
            self.terminal_calls_used += 1


@dataclass
class WorkflowRunBudget:
    limits: RunBudgetLimits
    started_at_epoch: float
    steps_used: int = 0

    def check_duration(self) -> None:
        elapsed = max(0.0, time.time() - self.started_at_epoch)
        if elapsed > max(1, int(self.limits.max_run_duration_seconds)):
            raise AgentRuntimeError(
                "Workflow 已超过 "
                f"max_run_duration_seconds={self.limits.max_run_duration_seconds} 的执行预算"
            )

    def check_context(self, context_chars: int) -> None:
        self.check_duration()
        if context_chars > max(1, int(self.limits.max_context_chars)):
            raise AgentRuntimeError(
                "Workflow 上下文超过 "
                f"max_context_chars={self.limits.max_context_chars} 的执行预算"
            )

    def claim_step(self) -> None:
        self.check_duration()
        if self.steps_used >= max(1, int(self.limits.max_workflow_steps)):
            raise AgentRuntimeError(
                f"Workflow 已超过 max_workflow_steps={self.limits.max_workflow_steps} 的执行预算"
            )
        self.steps_used += 1
