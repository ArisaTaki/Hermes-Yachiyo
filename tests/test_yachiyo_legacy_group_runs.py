"""Legacy GroupRun orchestration helper regressions."""

from __future__ import annotations

import pytest

from apps.shell.yachiyo_agent.legacy_group_runs import (
    _group_run_planner_event_type,
    group_member_orchestration_context,
    group_orchestration_plan,
    group_run_orchestration_context,
    group_run_status_from_child_runs,
    group_run_summary_from_child_runs,
    start_legacy_group_run,
)
from apps.shell.yachiyo_agent import legacy_group_orchestration
from apps.shell.agent.runtime import group_facade
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort


def test_legacy_group_run_plan_orders_debate_members_before_moderator() -> None:
    plan = group_orchestration_plan(
        {"mode": "debate", "moderator_agent_id": "agent-mod"},
        [
            {"agent_id": "agent-mod", "sort_order": 0},
            {"agent_id": "agent-a", "sort_order": 1},
            {"agent_id": "agent-b", "sort_order": 2},
        ],
    )

    assert plan["mode"] == "debate"
    assert plan["strategy"] == "participants_then_moderator"
    assert plan["member_order"] == ["agent-a", "agent-b", "agent-mod"]
    assert group_run_orchestration_context(plan) == {
        "group_execution_mode": "debate",
        "group_execution_strategy": "participants_then_moderator",
        "group_member_order": ["agent-a", "agent-b", "agent-mod"],
        "group_parallel": False,
        "group_moderator_agent_id": "agent-mod",
    }
    assert group_member_orchestration_context(plan, plan["members"][0], 0) == {
        "group_execution_mode": "debate",
        "group_execution_strategy": "participants_then_moderator",
        "group_member_phase": "debate_argument",
        "group_member_turn": 1,
        "group_member_parallel": False,
        "group_member_is_moderator": False,
    }
    assert group_member_orchestration_context(plan, plan["members"][2], 2)[
        "group_member_phase"
    ] == "moderator_summary"


def test_native_group_facade_owns_group_run_start(monkeypatch) -> None:
    captured = {}

    def fake_start(runtime, request, *, group):
        captured.update({"runtime": runtime, "request": request, "group": group})
        return {"group_run_id": "group-run-1"}

    monkeypatch.setattr(group_facade, "_start_agent_group_run", fake_start)

    class Runtime(group_facade.RuntimeGroupFacadeMixin):
        pass

    runtime = Runtime()
    result = runtime.start_agent_group_run(
        {
            "group_id": "group-1",
            "objective": "Prepare report",
            "group": {"group_id": "group-1", "members": []},
        }
    )

    assert result == {"group_run_id": "group-run-1"}
    assert captured == {
        "runtime": runtime,
        "request": {"group_id": "group-1", "objective": "Prepare report"},
        "group": {"group_id": "group-1", "members": []},
    }


def test_legacy_studio_port_resolves_group_before_native_start() -> None:
    class Runtime:
        _native_group_run_orchestration = True

        def __init__(self) -> None:
            self.requests = []

        def get_agent_group(self, group_id):
            return {
                "group_id": group_id,
                "name": "Research",
                "members": [{"agent_id": "agent-1"}],
            }

        def start_agent_group_run(self, request):
            self.requests.append(request)
            return {"group_run_id": "group-run-1"}

    runtime = Runtime()
    result = LegacyStudioPort(runtime).start_group_run(
        {"group_id": "group-1", "objective": "Prepare report"}
    )

    assert result == {"group_run_id": "group-run-1"}
    assert runtime.requests == [
        {
            "group_id": "group-1",
            "objective": "Prepare report",
            "group": {
                "group_id": "group-1",
                "name": "Research",
                "members": [{"agent_id": "agent-1"}],
            },
        }
    ]


def test_legacy_studio_port_validates_group_id_before_native_lookup() -> None:
    class Runtime:
        _native_group_run_orchestration = True

        def get_agent_group(self, group_id):
            raise AssertionError(f"must not resolve blank group id: {group_id}")

        def start_agent_group_run(self, request):
            raise AssertionError(f"must not start invalid group run: {request}")

    with pytest.raises(ValueError, match="缺少 group_id"):
        LegacyStudioPort(Runtime()).start_group_run({"objective": "Prepare report"})

    with pytest.raises(ValueError, match="群组运行目标不能为空"):
        LegacyStudioPort(Runtime()).start_group_run({"group_id": "group-1"})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"objective": "Prepare report"}, "缺少 group_id"),
        ({"group_id": "group-1"}, "群组运行目标不能为空"),
    ],
)
def test_legacy_group_run_validates_before_group_lookup(payload, message: str) -> None:
    def fail_lookup(group_id: str):
        raise AssertionError(f"must not resolve invalid request: {group_id}")

    with pytest.raises(ValueError, match=message):
        start_legacy_group_run(object(), payload, get_group=fail_lookup)


def test_legacy_group_run_wrappers_delegate_to_split_orchestration_module() -> None:
    group = {"mode": "parallel"}
    members = [
        {"agent_id": "agent-b", "sort_order": 2},
        {"agent_id": "agent-a", "sort_order": 1},
    ]

    legacy_plan = group_orchestration_plan(group, members)
    split_plan = legacy_group_orchestration.group_orchestration_plan(group, members)

    assert legacy_plan == split_plan
    assert group_run_orchestration_context(legacy_plan) == (
        legacy_group_orchestration.group_run_orchestration_context(split_plan)
    )
    assert group_member_orchestration_context(legacy_plan, legacy_plan["members"][0], 0) == (
        legacy_group_orchestration.group_member_orchestration_context(
            split_plan,
            split_plan["members"][0],
            0,
        )
    )


def test_legacy_group_run_status_and_summary_project_from_child_runs() -> None:
    child_runs = [
        {
            "run_id": "run-1",
            "runnable_name": "Planner",
            "status": "completed",
            "result": "Plan ready",
        },
        {
            "run_id": "run-2",
            "runnable_id": "agent-reviewer",
            "status": "completed",
            "result": "Review done",
        },
    ]

    assert group_run_status_from_child_runs(child_runs) == "completed"
    assert group_run_summary_from_child_runs(child_runs) == (
        "Planner: Plan ready\nagent-reviewer: Review done"
    )
    assert group_run_status_from_child_runs(
        [{"status": "processing"}, {"status": "completed"}]
    ) == ""
    assert group_run_status_from_child_runs(
        [{"status": "waiting_approval"}, {"status": "completed"}]
    ) == "approval_required"


def test_legacy_group_run_scopes_replan_planner_events() -> None:
    assert _group_run_planner_event_type("agent.plan.selection") == (
        "group.run.plan.selection"
    )
    assert _group_run_planner_event_type("agent.replan.requested") == (
        "group.run.replan.requested"
    )
    assert _group_run_planner_event_type("agent.replan.recovery.updated") == (
        "group.run.replan.recovery.updated"
    )
    assert _group_run_planner_event_type("agent.desktop.intent_planned") == (
        "group.run.desktop.intent_planned"
    )
    assert _group_run_planner_event_type("agent.desktop.intent_approval_required") == (
        "group.run.desktop.intent_approval_required"
    )
    assert _group_run_planner_event_type("agent.desktop.intent_completed") == (
        "group.run.desktop.intent_completed"
    )
    assert _group_run_planner_event_type("agent.desktop.intent_unavailable") == (
        "group.run.desktop.intent_unavailable"
    )
    assert _group_run_planner_event_type("agent.task.workspace_item.updated") == (
        "group.run.task.workspace_item.updated"
    )
    assert _group_run_planner_event_type("agent.task.todo.updated") == (
        "group.run.task.todo.updated"
    )
    assert _group_run_planner_event_type("agent.task.checkpoint.updated") == (
        "group.run.task.checkpoint.updated"
    )
