"""Legacy GroupRun orchestration helper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.legacy_group_runs import (
    _group_run_planner_event_type,
    group_member_orchestration_context,
    group_orchestration_plan,
    group_run_orchestration_context,
    group_run_status_from_child_runs,
    group_run_summary_from_child_runs,
)
from apps.shell.yachiyo_agent import legacy_group_orchestration


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
