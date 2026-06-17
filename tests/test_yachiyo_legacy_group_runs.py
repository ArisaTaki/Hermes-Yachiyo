"""Legacy GroupRun orchestration helper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.legacy_group_runs import (
    group_member_orchestration_context,
    group_orchestration_plan,
    group_run_orchestration_context,
    group_run_status_from_child_runs,
    group_run_summary_from_child_runs,
)


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
