"""Shared runtime configuration constants and normalizers."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError

EXECUTION_BACKENDS = {"native_profile", "yachiyo_profile", "external_cli"}
MEMORY_CONTEXT_LIMIT = 12
MEMORY_CONTENT_MAX_CHARS = 4000
FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
WORKFLOW_NODE_TYPES = {"start", "agent", "approval", "artifact", "condition", "parallel", "workflow", "loop"}
NATIVE_LIBRARY_SOURCE_TYPES = {"native_global", "native_project"}
SKILL_SOURCE_TYPES = {*NATIVE_LIBRARY_SOURCE_TYPES, "npx_skills", "local_zip", "local_dir"}
MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"
SYSTEM_AGENT_IDS = {MAIN_CHAT_AGENT_ID}
DEFAULT_AGENT_IDS = {
    MAIN_CHAT_AGENT_ID,
    "agent_yachiyo_orchestrator",
    "agent_coding",
    "agent_design",
    "agent_review",
    "agent_research",
    "agent_office",
    "agent_custom",
}
MARKET_AGENT_OPERATING_DOCTRINE = (
    "Market-grade Agent operating doctrine:\n"
    "- Act as a persistent personal agent, not a one-shot chatbot: preserve user intent, "
    "handoff context, and reusable outputs when the task has follow-up value.\n"
    "- Prefer the smallest reliable action loop: reason from available context, inspect before "
    "acting, use tools only when they materially improve the answer, and do not fabricate tool results.\n"
    "- Treat Skills as task manuals and tools as external actions; use mounted Skills when relevant, "
    "but keep direct answers lightweight when no Skill is needed.\n"
    "- For multi-step work, expose progress through concise summaries, artifacts, or workflow handoffs "
    "instead of hiding important intermediate decisions.\n"
    "- Respect safety boundaries: approval gates, workspace scopes, credential redaction, and user "
    "instructions outrank autonomy."
)


def is_active_run_status(status: str) -> bool:
    return (status.strip() or "running") not in FINAL_RUN_STATUSES


def normalize_execution_backend(value: Any, *, model_mode: str = "") -> str:
    """Normalize all Studio execution backends to the native runtime."""
    backend = str(value or "").strip()
    if backend and backend not in EXECUTION_BACKENDS:
        raise AgentRuntimeError("execution_backend 不再支持 legacy 或未知执行后端；请使用 native_profile")
    return "native_profile"


def normalize_skill_source_type(value: Any) -> str:
    source_type = str(value or "").strip()
    return source_type


def is_native_library_source_type(value: Any) -> bool:
    return normalize_skill_source_type(value) in NATIVE_LIBRARY_SOURCE_TYPES
