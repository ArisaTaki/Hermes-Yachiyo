#!/usr/bin/env python3
"""Run focused release scenarios for generic desktop-agent behavior."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.security import redact_log_text  # noqa: E402

CommandRunner = Callable[[Sequence[str]], Any]
OUTPUT_TAIL_LIMIT = 2000
SCENARIO_TIMEOUT_SECONDS = 180

GENERIC_AGENT_SCENARIOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "file_resolution",
        (
            "tests/test_agent_runtime_generic_discovery_recovery.py::"
            "test_file_read_miss_normalizes_to_one_capability_plan",
            "tests/test_agent_runtime_generic_discovery_recovery.py::"
            "test_file_adapter_lists_parent_for_miss_or_self_for_directory_once",
        ),
    ),
    (
        "app_resolution",
        (
            "tests/test_agent_runtime_generic_discovery_recovery.py::"
            "test_explicit_app_miss_normalizes_to_discovery_only_plan",
            "tests/test_agent_runtime_tool_execution_split.py::"
            "test_local_app_not_found_batch_only_runs_one_read_only_discovery",
            "tests/test_agent_runtime_generic_discovery_recovery.py::"
            "test_app_recovery_requires_local_broker_provenance",
        ),
    ),
    (
        "browser_research",
        (
            "tests/test_agent_runtime_custom_api_agent_loop_split.py::"
            "test_custom_api_agent_loop_preplans_runtime_browser_research_before_model",
            "tests/test_agent_runtime_browser_tools.py::"
            "test_browser_open_url_and_extract_text_runs_open_then_extract",
        ),
    ),
    (
        "media_alias",
        (
            "tests/test_agent_runtime_apple_music_alias_recovery.py::"
            "test_adapter_consumes_only_assessment_correlated_source_outcome",
            "tests/test_agent_runtime_apple_music_alias_recovery.py::"
            "test_adapter_rejects_nonlocal_source_locus",
        ),
    ),
    (
        "permission_resume",
        (
            "tests/test_runtime_approval_resume_smoke.py::"
            "test_runtime_approval_resume_smoke_covers_completed_resume",
            "tests/test_runtime_approval_resume_smoke.py::"
            "test_runtime_approval_resume_smoke_covers_execution_gate",
            "tests/test_agent_runtime_approval_resume_split.py::"
            "test_approval_resume_partial_result_forces_a_fresh_model_replan",
            "tests/test_agent_runtime_approval_resume_split.py::"
            "test_approval_resume_nonretryable_denial_projects_failure_without_model",
            "tests/test_agent_runtime_approval_resume_split.py::"
            "test_approval_resume_permission_required_stops_without_model_completion",
        ),
    ),
    (
        "background_non_takeover",
        (
            "tests/test_runtime_planner_desktop_followups.py::"
            "test_background_open_with_explicit_negative_constraints_never_plans_interaction",
            "tests/test_background_media_routing.py::"
            "test_daily_background_policy_never_bypasses_provider_for_media_fallbacks",
            "tests/test_desktop_route_trust_boundary.py::"
            "test_model_authored_apple_music_play_cannot_fall_back_to_local_foreground",
        ),
    ),
    (
        "bounded_recovery",
        (
            "tests/test_agent_runtime_outcome_loop.py::"
            "test_model_selected_recovery_disposition_controls_the_next_loop_intent",
            "tests/test_agent_runtime_outcome_loop.py::"
            "test_direct_runtime_planner_early_failure_is_not_hidden_by_later_success",
            "tests/test_agent_runtime_outcome_loop.py::"
            "test_model_selected_batch_routes_early_failure_before_later_success",
            "tests/test_native_agent_outcome_evaluator.py::"
            "test_evaluator_does_not_let_unrelated_success_hide_non_desktop_failure",
            "tests/test_native_agent_outcome_evaluator.py::"
            "test_evaluator_accepts_identity_linked_non_desktop_recovery_success",
            "tests/test_agent_runtime_recovery_actions.py::"
            "test_structured_result_distinguishes_terminal_completion_from_continuation",
            "tests/test_agent_runtime_generic_discovery_recovery.py::"
            "test_strategy_budget_blocks_same_source_scope",
            "tests/test_agent_runtime_recovery_policies.py::"
            "test_failed_terminal_event_enters_the_same_recovery_policy",
            "tests/test_agent_runtime_apple_music_alias_recovery.py::"
            "test_optional_timeouts_fall_back_quietly",
        ),
    ),
    (
        "internal_visibility",
        (
            "tests/test_agent_runtime_custom_api_agent_loop_split.py::"
            "test_runtime_recovery_records_failure_reraises_and_does_not_replay_claim",
            "tests/test_agent_runtime_tool_events.py::"
            "test_automatic_recovery_tool_events_are_persisted_as_internal",
            "tests/test_agent_runtime_tool_outcome_projection.py::"
            "test_runner_persists_canonical_outcome_only_as_internal_sidecar",
            "tests/test_agent_runtime_tool_outcome_projection.py::"
            "test_canonical_outcome_sidecar_preserves_internal_execution_identity",
        ),
    ),
    (
        "research_artifact_sink",
        (
            "tests/test_yachiyo_goal_contract_planner.py::"
            "test_cross_app_research_contract_requires_the_terminal_app_sink",
            "tests/test_agent_runtime_input_bindings.py::"
            "test_real_planner_artifact_handoff_survives_followup_and_runner",
        ),
    ),
    (
        "bounded_root_recovery",
        (
            "tests/test_agent_runtime_goal_loop_integration.py::"
            "test_recovery_plan_opens_subgoal_bound_to_unsatisfied_root_criterion",
            "tests/test_agent_runtime_goal_loop_integration.py::"
            "test_terminal_recovery_output_cannot_bypass_root_goal_verification",
            "tests/test_agent_runtime_goal_runtime.py::"
            "test_verified_recovery_retry_returns_to_original_goal_criterion",
            "tests/test_agent_runtime_goal_runtime.py::"
            "test_generated_recovery_step_without_goal_lineage_cannot_complete_root",
        ),
    ),
    (
        "grounded_completion",
        (
            "tests/test_agent_runtime_goal_loop_integration.py::"
            "test_model_prose_cannot_complete_effectful_goal_without_runtime_evidence",
            "tests/test_agent_runtime_goal_loop_integration.py::"
            "test_verified_correlated_tool_receipt_allows_effectful_goal_output",
            "tests/test_agent_runtime_goal_runtime.py::"
            "test_public_or_wrong_provider_verifier_cannot_complete_effectful_goal",
            "tests/test_agent_runtime_goal_runtime.py::"
            "test_runtime_requires_the_exact_declared_verifier_step_in_the_same_plan",
        ),
    ),
    (
        "background_grounded_provider",
        (
            "tests/test_cua_background_provider.py::"
            "test_executor_to_cua_verifies_exact_grounded_typed_content",
            "tests/test_cua_background_provider.py::"
            "test_open_composite_stops_when_launch_takes_the_user_foreground",
            "tests/test_background_desktop_safety.py::"
            "test_daily_background_policy_keeps_missing_cua_route_off_local_desktop",
        ),
    ),
    (
        "approval_atomicity",
        (
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_tool_approval_claim_and_resume_projection_roll_back_together_after_crash",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_tool_approval_claim_rolls_back_when_run_projection_returns_none",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_workflow_approval_claim_and_node_projection_roll_back_together_after_crash",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_tool_approval_rejection_claim_and_projection_roll_back_together_after_crash",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_workflow_approval_timeout_claim_and_projection_roll_back_together_after_crash",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_tool_approval_transition_rolls_back_claim_when_projection_returns_none",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_tool_approval_rejection_preserves_terminal_race_without_reprojection",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_next_approval_generation_projection_is_atomic_after_first_tool_executes",
            "tests/test_agent_runtime_approval_atomicity.py::"
            "test_next_approval_generation_cas_loss_discards_projection_timeline",
        ),
    ),
    (
        "terminal_concurrency",
        (
            "tests/test_agent_runtime_agent_outcomes_split.py::"
            "test_agent_run_completion_lost_cas_returns_fresh_terminal_without_events",
            "tests/test_agent_runtime_agent_outcomes_split.py::"
            "test_agent_run_failure_lost_cas_returns_fresh_terminal_without_events",
            "tests/test_agent_runtime_cancellation_split.py::"
            "test_runtime_run_cancellation_cas_loss_returns_fresh_winner_without_side_effects",
            "tests/test_agent_runtime_cancellation_split.py::"
            "test_root_workflow_group_cas_loss_rolls_back_run_cancellation",
            "tests/test_agent_runtime_workflow_transition_services_split.py::"
            "test_cancelled_root_group_projection_rejects_different_terminal_winner",
            "tests/test_agent_runtime_workflow_transition_services_split.py::"
            "test_cancelled_root_group_projection_accepts_same_terminal_cas_winner",
            "tests/test_agent_runtime_workflow_parent_resume_split.py::"
            "test_parent_terminal_winner_blocks_stale_child_failure_projection",
            "tests/test_agent_runtime_async_execution_lease.py::"
            "test_external_cancel_is_terminal_against_late_async_owner_completion",
            "tests/test_agent_runtime_async_execution_lease.py::"
            "test_stale_async_owner_cannot_publish_terminal_events_after_takeover",
        ),
    ),
    (
        "memory_privacy",
        (
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_model_unconfirmed_memory_is_not_retrieved_by_agent_query",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_explicit_user_consent_confirms_candidate_with_bound_receipt",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_agent_replace_stays_candidate_until_bound_user_confirmation",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_consent_receipt_rejects_tool_or_mismatched_identity",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_predictable_memory_consent_receipt_cannot_confirm_agent_candidate",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_user_api_issues_single_use_memory_consent_capability",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_main_chat_run_binds_agent_candidate_to_user_message_receipt",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_memory_query_enforces_exact_project_and_session_scope",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_agent_tool_cannot_delete_memory_from_another_session_by_id",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_agent_tool_cannot_replace_memory_from_another_project_by_content",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_agent_tool_requires_approval_to_replace_confirmed_visible_memory",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_agent_tool_requires_approval_to_remove_confirmed_visible_memory",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_manual_memory_records_user_actor_and_source_provenance",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_explicit_invalid_memory_scope_is_rejected_instead_of_widened_to_global",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_agent_memory_api_reports_stable_invalid_scope_error",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_memory_privacy_migration_preserves_manual_items_as_confirmed",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_delete_and_disable_immediately_remove_memory_from_chat_and_agent_context",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_main_chat_does_not_bypass_managed_memory_with_raw_history",
            "tests/test_agent_runtime_memory_privacy.py::"
            "test_workflow_agent_retrieves_only_authoritative_confirmed_memory",
        ),
    ),
)


def _default_command_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SCENARIO_TIMEOUT_SECONDS,
    )


def _redacted_tail(value: Any, *, limit: int = OUTPUT_TAIL_LIMIT) -> str:
    redacted = redact_log_text(str(value or ""))
    return redacted if len(redacted) <= limit else redacted[-limit:]


def _xml_local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _junit_count(element: ET.Element, name: str) -> int:
    try:
        return max(0, int(element.attrib.get(name, "0") or 0))
    except (TypeError, ValueError):
        return 0


def _empty_test_metrics(*, status: str, error: str = "") -> dict[str, Any]:
    return {
        "metrics_status": status,
        "collected_count": 0,
        "passed_test_count": 0,
        "failed_test_count": 0,
        "error_test_count": 0,
        "skipped_test_count": 0,
        "xfailed_test_count": 0,
        **({"metrics_error": error} if error else {}),
    }


def _junit_test_metrics(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty_test_metrics(status="missing")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return _empty_test_metrics(status="invalid", error=str(exc))
    suites = (
        [root]
        if _xml_local_name(root.tag) == "testsuite"
        else [
            child
            for child in list(root)
            if _xml_local_name(child.tag) == "testsuite"
        ]
    )
    if not suites:
        return _empty_test_metrics(
            status="invalid",
            error="JUnit report contains no testsuite",
        )
    collected = sum(_junit_count(suite, "tests") for suite in suites)
    failures = sum(_junit_count(suite, "failures") for suite in suites)
    errors = sum(_junit_count(suite, "errors") for suite in suites)
    raw_skipped = sum(_junit_count(suite, "skipped") for suite in suites)
    xfailed = 0
    for suite in suites:
        for element in suite.iter():
            if _xml_local_name(element.tag) != "skipped":
                continue
            reason = " ".join(
                (
                    str(element.attrib.get("type") or ""),
                    str(element.attrib.get("message") or ""),
                    str(element.text or ""),
                )
            ).casefold()
            if "xfail" in reason:
                xfailed += 1
    skipped = max(0, raw_skipped - xfailed)
    passed = max(0, collected - failures - errors - raw_skipped)
    return {
        "metrics_status": "available",
        "collected_count": collected,
        "passed_test_count": passed,
        "failed_test_count": failures,
        "error_test_count": errors,
        "skipped_test_count": skipped,
        "xfailed_test_count": xfailed,
    }


def _scenario_blocking_conditions(
    *,
    returncode: int,
    metrics: Mapping[str, Any],
    timeout_count: int,
) -> list[str]:
    conditions: list[str] = []
    if timeout_count:
        conditions.append("scenario_timeout")
    if returncode != 0:
        conditions.append("pytest_exit_nonzero")
    metrics_status = str(metrics.get("metrics_status") or "")
    if metrics_status != "available":
        conditions.append(f"test_metrics_{metrics_status or 'missing'}")
        return conditions
    if int(metrics.get("collected_count") or 0) <= 0:
        conditions.append("no_tests_collected")
    for key, condition in (
        ("failed_test_count", "failed_tests_present"),
        ("error_test_count", "test_errors_present"),
        ("skipped_test_count", "skipped_tests_present"),
        ("xfailed_test_count", "xfailed_tests_present"),
    ):
        if int(metrics.get(key) or 0) > 0:
            conditions.append(condition)
    if int(metrics.get("passed_test_count") or 0) != int(
        metrics.get("collected_count") or 0
    ):
        conditions.append("not_all_collected_tests_passed")
    return conditions


def _scenario_report(
    scenario_id: str,
    node_ids: Sequence[str],
    *,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    started = time.perf_counter()
    timeout_count = 0
    with tempfile.TemporaryDirectory(prefix="oha-agent-eval-") as temp_dir:
        junit_path = Path(temp_dir) / "pytest-junit.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit_path}",
            *node_ids,
        ]
        try:
            completed = command_runner(command)
            returncode = int(getattr(completed, "returncode", 1))
            stdout = getattr(completed, "stdout", "")
            stderr = getattr(completed, "stderr", "")
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            timeout_count = 1
            stdout = exc.stdout or ""
            stderr = f"scenario timed out after {SCENARIO_TIMEOUT_SECONDS}s"
        except Exception as exc:
            returncode = 1
            stdout = ""
            stderr = f"command runner failed: {exc}"
        metrics = _junit_test_metrics(junit_path)
    blocking_conditions = _scenario_blocking_conditions(
        returncode=returncode,
        metrics=metrics,
        timeout_count=timeout_count,
    )
    duration_seconds = round(max(0.0, time.perf_counter() - started), 6)
    return {
        "id": scenario_id,
        "node_ids": list(node_ids),
        "command": command,
        "returncode": returncode,
        "duration_seconds": duration_seconds,
        "status": "passed" if not blocking_conditions else "failed",
        "blocking_conditions": blocking_conditions,
        "timeout_count": timeout_count,
        **metrics,
        "stdout_tail": _redacted_tail(stdout),
        "stderr_tail": _redacted_tail(stderr),
    }


def run_smoke(
    *,
    command_runner: CommandRunner | None = None,
    scenarios: Sequence[tuple[str, Sequence[str]]] = GENERIC_AGENT_SCENARIOS,
) -> dict[str, Any]:
    runner = command_runner or _default_command_runner
    scenario_reports = [
        _scenario_report(scenario_id, node_ids, command_runner=runner)
        for scenario_id, node_ids in scenarios
    ]
    passed_count = sum(
        1 for scenario in scenario_reports if scenario["status"] == "passed"
    )
    failed_count = len(scenario_reports) - passed_count
    test_metric_keys = (
        "collected_count",
        "passed_test_count",
        "failed_test_count",
        "error_test_count",
        "skipped_test_count",
        "xfailed_test_count",
        "timeout_count",
    )
    return {
        "ok": failed_count == 0 and bool(scenario_reports),
        "mode": "generic_agent_release_smoke",
        "scenario_count": len(scenario_reports),
        "passed_count": passed_count,
        "failed_count": failed_count,
        **{
            key: sum(int(scenario.get(key) or 0) for scenario in scenario_reports)
            for key in test_metric_keys
        },
        "failed_scenarios": [
            scenario["id"]
            for scenario in scenario_reports
            if scenario["status"] == "failed"
        ],
        "scenarios": scenario_reports,
    }


def _write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_smoke()
    if args.report_json is not None:
        _write_report(args.report_json, report)
        print(f"generic agent release smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
