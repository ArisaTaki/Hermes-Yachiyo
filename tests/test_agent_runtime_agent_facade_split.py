"""Tests for Agent facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_facade import RuntimeAgentFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_agent_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeAgentFacadeMixin is RuntimeAgentFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeAgentFacadeMixin)
    for method_name in (
        "_load_agent_skills",
        "_compile_agent_runtime",
        "_agent_context",
        "_agent_workspace_dir",
        "create_agent_run",
        "create_agent_run_async",
        "_execute_agent_run",
        "_run_custom_api_agent",
        "test_agent_model",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_agent_facade_methods_available_after_split(tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []

    class _SkillLoader:
        @staticmethod
        def load(skill_ids: list[str]) -> list[dict[str, Any]]:
            calls.append(("skills", skill_ids))
            return [{"skill_id": skill_ids[0], "name": "Reader"}]

    class _RuntimePolicy:
        @staticmethod
        def compile_agent_runtime(agent: dict[str, Any]) -> dict[str, Any]:
            calls.append(("runtime", agent["agent_id"]))
            return {"runtime": "oha_agent", "agent_id": agent["agent_id"]}

    class _ContextBuilder:
        @staticmethod
        def build(
            agent: dict[str, Any],
            user_goal: str,
            upstream: str,
            *,
            skills: list[dict[str, Any]] | None = None,
        ) -> str:
            calls.append(("context", agent["agent_id"], user_goal, upstream, skills))
            return "agent-context"

    class _RunCoordinator:
        @staticmethod
        def create_sync(payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(("create-sync", payload))
            return {"run_id": "run-sync"}

    class _AsyncRunCoordinator:
        @staticmethod
        def create_async(payload: dict[str, Any], *, on_complete: Any = None) -> dict[str, Any]:
            calls.append(("create-async", payload, on_complete))
            return {"run_id": "run-async"}

    class _RunExecutor:
        @staticmethod
        def execute(run_id: str, agent: dict[str, Any], user_goal: str, upstream: str) -> dict[str, Any]:
            calls.append(("execute", run_id, agent["agent_id"], user_goal, upstream))
            return {"run_id": run_id, "status": "completed"}

    class _CustomApiAgentLoop:
        @staticmethod
        def run(
            agent: dict[str, Any],
            context: str,
            broker: Any,
            timeline: list[dict[str, Any]],
            artifacts: list[dict[str, Any]],
            **kwargs: Any,
        ) -> str:
            calls.append(("custom-api", agent["agent_id"], context, broker, timeline, artifacts, kwargs))
            return "model result"

    class _AgentModelTester:
        @staticmethod
        def test_agent_model(agent: dict[str, Any]) -> dict[str, Any]:
            calls.append(("test-model", agent["agent_id"]))
            return {"ok": True, "agent_id": agent["agent_id"]}

    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        service.agent_skill_loader = _SkillLoader()
        service.runtime_policy = _RuntimePolicy()
        service.agent_context_builder = _ContextBuilder()
        service.agent_run_coordinator = _RunCoordinator()
        service.agent_run_async_coordinator = _AsyncRunCoordinator()
        service.agent_run_executor = _RunExecutor()
        service.custom_api_agent_loop = _CustomApiAgentLoop()
        service.agent_model_tester = _AgentModelTester()
        service._get_agent_private = lambda agent_id: {"agent_id": agent_id}

        agent = {
            "agent_id": "agent-1",
            "workspace_policy": {"default_workdir": str(tmp_path / "workspace")},
        }
        on_complete = object()
        timeline = [{"event": "agent.run.started"}]
        artifacts = [{"artifact_id": "artifact-1"}]

        assert service._load_agent_skills(["skill-1"]) == [{"skill_id": "skill-1", "name": "Reader"}]
        assert service._compile_agent_runtime(agent) == {"runtime": "oha_agent", "agent_id": "agent-1"}
        assert service._agent_context(agent, "Ship", "Upstream", skills=[]) == "agent-context"
        assert service._agent_workspace_dir(agent) == str(tmp_path / "workspace")
        assert service.create_agent_run({"agent_id": "agent-1"}) == {"run_id": "run-sync"}
        assert service.create_agent_run_async({"agent_id": "agent-1"}, on_complete=on_complete) == {"run_id": "run-async"}
        assert service._execute_agent_run("run-1", agent, "Ship", "Upstream") == {
            "run_id": "run-1",
            "status": "completed",
        }
        assert service._run_custom_api_agent(
            agent,
            "context",
            {"broker": True},
            timeline,
            artifacts,
            messages=[{"role": "user", "content": "hi"}],
            start_iteration=2,
            run_id="run-1",
            budget="budget",
        ) == "model result"
        assert service.test_agent_model("agent-1") == {"ok": True, "agent_id": "agent-1"}

        assert calls == [
            ("skills", ["skill-1"]),
            ("runtime", "agent-1"),
            ("context", "agent-1", "Ship", "Upstream", []),
            ("create-sync", {"agent_id": "agent-1"}),
            ("create-async", {"agent_id": "agent-1"}, on_complete),
            ("execute", "run-1", "agent-1", "Ship", "Upstream"),
            (
                "custom-api",
                "agent-1",
                "context",
                {"broker": True},
                timeline,
                artifacts,
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "direct_tool_request": None,
                    "direct_tool_requests": None,
                    "runtime_execution_envelope": None,
                    "runtime_execution_metadata": None,
                    "daily_desktop_planning_context": None,
                    "start_iteration": 2,
                    "run_id": "run-1",
                    "budget": "budget",
                    "resume_after_approved_tool": False,
                },
            ),
            ("test-model", "agent-1"),
        ]
    finally:
        service.close()


def test_agent_facade_forwards_direct_tool_execution_options() -> None:
    captured: dict[str, Any] = {}

    class _RunExecutor:
        @staticmethod
        def execute(
            run_id: str,
            agent: dict[str, Any],
            user_goal: str,
            upstream: str,
            *,
            run_group_id: str = "",
            workflow_run_id: str = "",
            direct_tool_request: dict[str, Any] | None = None,
            direct_tool_requests: list[dict[str, Any]] | None = None,
            daily_desktop_planning_context: str | None = None,
        ) -> dict[str, Any]:
            captured.update(
                {
                    "run_id": run_id,
                    "agent_id": agent["agent_id"],
                    "user_goal": user_goal,
                    "upstream": upstream,
                    "run_group_id": run_group_id,
                    "workflow_run_id": workflow_run_id,
                    "direct_tool_request": direct_tool_request,
                    "direct_tool_requests": direct_tool_requests,
                    "daily_desktop_planning_context": daily_desktop_planning_context,
                }
            )
            return {"run_id": run_id, "status": "completed"}

    class _Service(RuntimeAgentFacadeMixin):
        agent_run_executor = _RunExecutor()

    result = _Service()._execute_agent_run(
        "run-1",
        {"agent_id": "agent-1"},
        "打开 Apple Music",
        "upstream context",
        run_group_id="group-run-1",
        workflow_run_id="workflow-run-1",
        direct_tool_request={"tool": "desktop.list_apps", "input": {"query": "Music"}},
        direct_tool_requests=[
            {"tool": "app.open", "input": {"app_name": "Music"}},
        ],
        daily_desktop_planning_context="打开 Apple Music",
    )

    assert result == {"run_id": "run-1", "status": "completed"}
    assert captured == {
        "run_id": "run-1",
        "agent_id": "agent-1",
        "user_goal": "打开 Apple Music",
        "upstream": "upstream context",
        "run_group_id": "group-run-1",
        "workflow_run_id": "workflow-run-1",
        "direct_tool_request": {"tool": "desktop.list_apps", "input": {"query": "Music"}},
        "direct_tool_requests": [
            {"tool": "app.open", "input": {"app_name": "Music"}},
        ],
        "daily_desktop_planning_context": "打开 Apple Music",
    }
