"""Direct boundary tests for extracted planner strategy modules."""

from apps.shell.yachiyo_agent.contracts import TaskIntentSnapshot
from apps.shell.yachiyo_agent.execution_strategy import (
    execution_strategy_snapshot,
    runtime_planner_preflight_ui_before_action,
)
from apps.shell.yachiyo_agent.planner_primitives import (
    stable_planner_id,
    unique_planner_strings,
)


def test_stable_planner_id_preserves_runtime_planner_contract() -> None:
    assert stable_planner_id(
        "execution-strategy",
        "desktop_operation",
        "打开应用:isolated_desktop:foreground",
    ) == "execution-strategy-81e1bfe167d6"


def test_runtime_planner_preflight_reads_nested_desktop_policy() -> None:
    assert runtime_planner_preflight_ui_before_action(
        {
            "desktop_execution_policy": {
                "preflight_ui_before_action": True,
            }
        }
    ) is True


def test_unique_planner_strings_preserves_clean_first_seen_values() -> None:
    assert unique_planner_strings(["alpha", " alpha ", "", "beta", "alpha"]) == [
        "alpha",
        "beta",
    ]


def test_execution_strategy_handles_plan_without_executable_steps() -> None:
    strategy = execution_strategy_snapshot(
        TaskIntentSnapshot(
            intent_id="intent-general",
            kind="general",
            title="General task",
            user_goal="Answer the user",
        ),
        [],
        {},
    )

    assert strategy.preferred_environment == "structured_runtime"
    assert strategy.interaction_mode == "background"
    assert strategy.reasons == ["no_executable_steps_planned"]
