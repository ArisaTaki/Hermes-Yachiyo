"""Tests for Runnable facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser
from apps.shell.agent.runtime.runnable_facade import RuntimeRunnableFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_runnable_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunnableFacadeMixin is RuntimeRunnableFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeRunnableFacadeMixin)
    for method_name in (
        "list_runnables",
        "_agent_runnable_summary",
        "_workflow_participants",
        "_workflow_runnable_summary",
        "list_delegation_targets",
        "resolve_runnable",
        "create_run_for_runnable",
        "create_run_for_runnable_async",
        "rerun_run",
        "delegate_runnable",
        "parse_known_chat_runnable",
        "parse_chat_runnable",
        "_chat_mention_parts",
        "_chat_mention_goal",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_runnable_static_helpers_available_after_split() -> None:
    text = '@"Research Agent" summarize this'
    assert agent_runtime.NativeRunEngine.parse_chat_runnable(text) == ChatRunnableMentionParser.parse(text)
    assert agent_runtime.NativeRunEngine._chat_mention_parts(text) == ChatRunnableMentionParser.mention_parts(text)
    assert agent_runtime.NativeRunEngine._chat_mention_goal(
        "please",
        "continue",
        ["line two"],
    ) == ChatRunnableMentionParser.mention_goal("please", "continue", ["line two"])


def test_native_runtime_keeps_runnable_facade_methods_available_after_split(tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []

    class _RunnableCatalog:
        @staticmethod
        def list_runnables(agents: list[dict[str, Any]], workflows: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append(("list", agents, workflows))
            return {"runnables": [{"id": "agent-1", "kind": "agent"}]}

        @staticmethod
        def agent_summary(agent: dict[str, Any]) -> dict[str, Any]:
            calls.append(("agent-summary", agent))
            return {"id": agent["agent_id"], "kind": "agent"}

        @staticmethod
        def workflow_participants(workflow: dict[str, Any]) -> list[dict[str, Any]]:
            calls.append(("participants", workflow))
            return [{"id": "agent-1"}]

        @staticmethod
        def workflow_summary(workflow: dict[str, Any]) -> dict[str, Any]:
            calls.append(("workflow-summary", workflow))
            return {"id": workflow["workflow_id"], "kind": "workflow"}

        @staticmethod
        def list_delegation_targets(agents: list[dict[str, Any]], workflows: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append(("targets", agents, workflows))
            return {"agents": agents, "workflows": workflows}

    class _RunnableResolver:
        @staticmethod
        def resolve(*, runnable_id: str = "", name: str = "") -> dict[str, Any] | None:
            calls.append(("resolve", runnable_id, name))
            return {"id": runnable_id or "agent-1", "name": name or "Agent", "kind": "agent"}

    class _RunnableRunCoordinator:
        @staticmethod
        def create_run(**kwargs: Any) -> dict[str, Any]:
            calls.append(("create", kwargs))
            return {"run_id": "run-1", **kwargs}

        @staticmethod
        def create_run_async(**kwargs: Any) -> dict[str, Any]:
            calls.append(("create-async", kwargs))
            return {"run_id": "run-async", **kwargs}

        @staticmethod
        def delegate(**kwargs: Any) -> dict[str, Any]:
            calls.append(("delegate", kwargs))
            return {"ok": True, "run_id": "run-1", **kwargs}

    class _RunRerun:
        @staticmethod
        def rerun(run_id: str, request: dict[str, Any] | None = None) -> dict[str, Any]:
            calls.append(("rerun", run_id, request))
            return {"run_id": "rerun-1", "source_run_id": run_id, "request": request or {}}

    class _ChatRunnableParser:
        @staticmethod
        def parse_known(text: str) -> tuple[str, str] | None:
            calls.append(("parse-known", text))
            return "agent-1", "summarize"

    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        agents = [{"agent_id": "agent-1", "name": "Agent"}]
        workflows = [{"workflow_id": "workflow-1", "name": "Flow"}]
        service.list_agents = lambda: {"agents": agents}
        service.list_workflows = lambda: {"workflows": workflows}
        service.runnable_catalog = _RunnableCatalog()
        service.runnable_resolver = _RunnableResolver()
        service.runnable_run_coordinator = _RunnableRunCoordinator()
        service.run_rerun = _RunRerun()
        service.chat_runnable_parser = _ChatRunnableParser()
        on_complete = object()

        assert service.list_runnables() == {"runnables": [{"id": "agent-1", "kind": "agent"}]}
        assert service._agent_runnable_summary(agents[0]) == {"id": "agent-1", "kind": "agent"}
        assert service._workflow_participants(workflows[0]) == [{"id": "agent-1"}]
        assert service._workflow_runnable_summary(workflows[0]) == {"id": "workflow-1", "kind": "workflow"}
        assert service.list_delegation_targets() == {"agents": agents, "workflows": workflows}
        assert service.resolve_runnable(runnable_id="agent-1") == {
            "id": "agent-1",
            "name": "Agent",
            "kind": "agent",
        }
        assert service.create_run_for_runnable(
            runnable_id="agent-1",
            user_goal="Ship",
            run_group_id="group-1",
            upstream="context",
            client_run_id="client-1",
            client_request_id="request-1",
        )["run_id"] == "run-1"
        assert service.create_run_for_runnable_async(
            name="Agent",
            user_goal="Ship",
            run_group_id="group-1",
            upstream="context",
            on_complete=on_complete,
        )["run_id"] == "run-async"
        assert service.rerun_run("run-1") == {
            "run_id": "rerun-1",
            "source_run_id": "run-1",
            "request": {},
        }
        assert service.delegate_runnable(
            kind="agent",
            runnable_id="agent-1",
            user_goal="Ship",
        )["ok"] is True
        assert service.parse_known_chat_runnable("@Agent summarize") == ("agent-1", "summarize")

        create_async_call = next(item for item in calls if item[0] == "create-async")
        assert create_async_call[1]["on_complete"] is on_complete
        assert ("list", agents, workflows) in calls
        assert ("targets", agents, workflows) in calls
        assert ("rerun", "run-1", None) in calls
        assert ("parse-known", "@Agent summarize") in calls
    finally:
        service.close()
