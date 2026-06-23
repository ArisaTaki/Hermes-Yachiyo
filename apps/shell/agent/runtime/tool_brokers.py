"""ToolBroker construction helpers for runtime entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.foreground_lock import ForegroundActionLock


class RuntimeToolBrokerFactory:
    """Builds ToolBroker instances with run-scoped memory and FutureTask stores."""

    def __init__(
        self,
        *,
        agent_artifacts_dir: Path,
        tool_broker_factory: Callable[..., Any],
        memory_store: Callable[..., Any],
        future_task_store: Callable[..., Any],
        main_chat_agent_id: str,
        foreground_lock: Any | None = None,
    ) -> None:
        self._agent_artifacts_dir = agent_artifacts_dir
        self._tool_broker_factory = tool_broker_factory
        self._memory_store = memory_store
        self._future_task_store = future_task_store
        self._main_chat_agent_id = main_chat_agent_id
        self._foreground_lock = foreground_lock
        self._foreground_locks: dict[str, ForegroundActionLock] = {}

    def for_run(
        self,
        *,
        run_id: str,
        workspace_policy: dict[str, Any],
        approvals: dict[str, bool] | None = None,
        default_runnable_id: str = "",
        artifacts_dir: Path | None = None,
        skills: list[dict[str, Any]] | None = None,
        foreground_lock: Any | None = None,
        foreground_lock_owner: str = "",
        foreground_lock_key: str = "",
    ) -> Any:
        clean_run_id = str(run_id or "").strip()
        clean_lock_key = str(foreground_lock_key or "").strip()
        root = artifacts_dir or self._agent_artifacts_dir
        lock = foreground_lock
        if lock is None and clean_lock_key:
            lock = self._foreground_locks.setdefault(clean_lock_key, ForegroundActionLock())
        if lock is None:
            lock = self._foreground_lock
        extra: dict[str, Any] = {}
        if lock is not None:
            extra["foreground_lock"] = lock
        clean_owner = str(foreground_lock_owner or "").strip()
        if not clean_owner and clean_lock_key:
            clean_owner = f"{clean_lock_key}:{clean_run_id}"
        if clean_owner:
            extra["foreground_lock_owner"] = clean_owner
        return self._tool_broker_factory(
            workspace_policy,
            root / clean_run_id,
            approvals=approvals,
            skills=skills,
            memory_store=self._memory_store(source_run_id=clean_run_id),
            future_task_store=self._future_task_store(
                source_run_id=clean_run_id,
                default_runnable_id=default_runnable_id,
            ),
            **extra,
        )

    def for_main_chat(
        self,
        *,
        run_id: str,
        workspace_policy: dict[str, Any],
        approvals: dict[str, bool] | None = None,
    ) -> Any:
        return self.for_run(
            run_id=run_id,
            workspace_policy=workspace_policy,
            approvals=approvals,
            default_runnable_id=self._main_chat_agent_id,
        )

    def write_artifact_for_run(
        self,
        *,
        run_id: str,
        workspace_policy: dict[str, Any],
        artifacts_dir: Path | None = None,
        artifact_path: str,
        content: str,
    ) -> dict[str, Any]:
        broker = self.for_run(
            run_id=run_id,
            workspace_policy=workspace_policy,
            artifacts_dir=artifacts_dir,
        )
        return broker.artifact_write(artifact_path, content)


def write_artifact_with_tool_broker(
    *,
    tool_brokers: Any | None,
    run_id: str,
    workspace_policy: dict[str, Any],
    artifacts_dir: Any,
    artifact_path: str,
    content: str,
) -> dict[str, Any]:
    clean_run_id = str(run_id or "").strip()
    root = Path(artifacts_dir)
    if tool_brokers is not None:
        writer = getattr(tool_brokers, "write_artifact_for_run", None)
        if callable(writer):
            return writer(
                run_id=clean_run_id,
                workspace_policy=workspace_policy,
                artifacts_dir=root,
                artifact_path=artifact_path,
                content=content,
            )
        broker = tool_brokers.for_run(
            run_id=clean_run_id,
            workspace_policy=workspace_policy,
            artifacts_dir=root,
        )
    else:
        broker = ToolBroker(workspace_policy, root / clean_run_id)
    return broker.artifact_write(artifact_path, content)
