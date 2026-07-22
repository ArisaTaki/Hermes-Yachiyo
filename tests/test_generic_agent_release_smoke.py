from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from scripts import smoke_generic_agent_release as smoke

EXPECTED_SCENARIOS = (
    "file_resolution",
    "app_resolution",
    "browser_research",
    "media_alias",
    "permission_resume",
    "background_non_takeover",
    "bounded_recovery",
    "internal_visibility",
    "research_artifact_sink",
    "bounded_root_recovery",
    "grounded_completion",
    "background_grounded_provider",
    "approval_atomicity",
    "terminal_concurrency",
    "memory_privacy",
)


def _junit_path(command) -> str:
    option = next(part for part in command if part.startswith("--junitxml="))
    return option.split("=", 1)[1]


def _write_junit(
    command,
    *,
    passed: int = 0,
    failed: int = 0,
    errors: int = 0,
    skipped: int = 0,
    xfailed: int = 0,
) -> None:
    total = passed + failed + errors + skipped + xfailed
    suite = ET.Element(
        "testsuite",
        {
            "name": "generic-agent-release",
            "tests": str(total),
            "failures": str(failed),
            "errors": str(errors),
            "skipped": str(skipped + xfailed),
        },
    )
    for index in range(passed):
        ET.SubElement(suite, "testcase", {"name": f"passed-{index}"})
    for index in range(failed):
        case = ET.SubElement(suite, "testcase", {"name": f"failed-{index}"})
        ET.SubElement(case, "failure", {"message": "failed"})
    for index in range(errors):
        case = ET.SubElement(suite, "testcase", {"name": f"error-{index}"})
        ET.SubElement(case, "error", {"message": "error"})
    for index in range(skipped):
        case = ET.SubElement(suite, "testcase", {"name": f"skipped-{index}"})
        ET.SubElement(case, "skipped", {"message": "skipped"})
    for index in range(xfailed):
        case = ET.SubElement(suite, "testcase", {"name": f"xfailed-{index}"})
        ET.SubElement(
            case,
            "skipped",
            {"type": "pytest.xfail", "message": "expected failure"},
        )
    root = ET.Element("testsuites")
    root.append(suite)
    ET.ElementTree(root).write(_junit_path(command), encoding="utf-8", xml_declaration=True)


def test_generic_release_scenario_mapping_is_complete_and_fixed() -> None:
    assert tuple(scenario_id for scenario_id, _node_ids in smoke.GENERIC_AGENT_SCENARIOS) == (
        EXPECTED_SCENARIOS
    )
    node_ids = [
        node_id
        for _scenario_id, scenario_node_ids in smoke.GENERIC_AGENT_SCENARIOS
        for node_id in scenario_node_ids
    ]
    scenario_mapping = dict(smoke.GENERIC_AGENT_SCENARIOS)
    assert all(len(scenario_mapping[scenario_id]) >= 2 for scenario_id in EXPECTED_SCENARIOS)
    assert len(node_ids) == len(set(node_ids))
    assert all(node_id.startswith("tests/") and "::test_" in node_id for node_id in node_ids)
    assert any(
        "test_local_app_not_found_batch_only_runs_one_read_only_discovery" in node_id
        for node_id in scenario_mapping["app_resolution"]
    )
    assert any(
        "test_adapter_rejects_nonlocal_source_locus" in node_id
        for node_id in scenario_mapping["media_alias"]
    )
    assert any(
        "test_approval_resume_partial_result_forces_a_fresh_model_replan"
        in node_id
        for node_id in scenario_mapping["permission_resume"]
    )
    assert any(
        "test_approval_resume_nonretryable_denial_projects_failure_without_model"
        in node_id
        for node_id in scenario_mapping["permission_resume"]
    )
    assert any(
        "test_approval_resume_permission_required_stops_without_model_completion"
        in node_id
        for node_id in scenario_mapping["permission_resume"]
    )
    assert any(
        "test_runner_persists_canonical_outcome_only_as_internal_sidecar" in node_id
        for node_id in scenario_mapping["internal_visibility"]
    )
    assert any(
        "test_canonical_outcome_sidecar_preserves_internal_execution_identity"
        in node_id
        for node_id in scenario_mapping["internal_visibility"]
    )
    assert any(
        "test_failed_terminal_event_enters_the_same_recovery_policy" in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_structured_result_distinguishes_terminal_completion_from_continuation"
        in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_model_selected_recovery_disposition_controls_the_next_loop_intent"
        in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_direct_runtime_planner_early_failure_is_not_hidden_by_later_success"
        in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_model_selected_batch_routes_early_failure_before_later_success"
        in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_evaluator_does_not_let_unrelated_success_hide_non_desktop_failure"
        in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_evaluator_accepts_identity_linked_non_desktop_recovery_success"
        in node_id
        for node_id in scenario_mapping["bounded_recovery"]
    )
    assert any(
        "test_runtime_recovery_records_failure_reraises_and_does_not_replay_claim"
        in node_id
        for node_id in scenario_mapping["internal_visibility"]
    )
    assert any(
        "test_background_open_with_explicit_negative_constraints_never_plans_interaction"
        in node_id
        for node_id in scenario_mapping["background_non_takeover"]
    )
    assert any(
        "test_real_planner_artifact_handoff_survives_followup_and_runner" in node_id
        for node_id in scenario_mapping["research_artifact_sink"]
    )
    assert any(
        "test_verified_recovery_retry_returns_to_original_goal_criterion" in node_id
        for node_id in scenario_mapping["bounded_root_recovery"]
    )
    assert any(
        "test_model_prose_cannot_complete_effectful_goal_without_runtime_evidence"
        in node_id
        for node_id in scenario_mapping["grounded_completion"]
    )
    assert any(
        "test_executor_to_cua_verifies_exact_grounded_typed_content" in node_id
        for node_id in scenario_mapping["background_grounded_provider"]
    )
    assert any(
        "test_workflow_approval_claim_and_node_projection_roll_back_together_after_crash"
        in node_id
        for node_id in scenario_mapping["approval_atomicity"]
    )
    assert any(
        "test_tool_approval_claim_and_resume_projection_roll_back_together_after_crash"
        in node_id
        for node_id in scenario_mapping["approval_atomicity"]
    )
    assert any(
        "test_tool_approval_claim_rolls_back_when_run_projection_returns_none"
        in node_id
        for node_id in scenario_mapping["approval_atomicity"]
    )
    assert any(
        "test_root_workflow_group_cas_loss_rolls_back_run_cancellation" in node_id
        for node_id in scenario_mapping["terminal_concurrency"]
    )
    assert any(
        "test_cancelled_root_group_projection_rejects_different_terminal_winner"
        in node_id
        for node_id in scenario_mapping["terminal_concurrency"]
    )
    assert any(
        "test_cancelled_root_group_projection_accepts_same_terminal_cas_winner"
        in node_id
        for node_id in scenario_mapping["terminal_concurrency"]
    )
    assert any(
        "test_external_cancel_is_terminal_against_late_async_owner_completion"
        in node_id
        for node_id in scenario_mapping["terminal_concurrency"]
    )
    assert any(
        "test_model_unconfirmed_memory_is_not_retrieved_by_agent_query" in node_id
        for node_id in scenario_mapping["memory_privacy"]
    )
    assert any(
        "test_main_chat_does_not_bypass_managed_memory_with_raw_history" in node_id
        for node_id in scenario_mapping["memory_privacy"]
    )
    assert any(
        "test_workflow_agent_retrieves_only_authoritative_confirmed_memory" in node_id
        for node_id in scenario_mapping["memory_privacy"]
    )
    assert any(
        "test_agent_tool_cannot_delete_memory_from_another_session_by_id" in node_id
        for node_id in scenario_mapping["memory_privacy"]
    )
    assert any(
        "test_explicit_invalid_memory_scope_is_rejected_instead_of_widened_to_global"
        in node_id
        for node_id in scenario_mapping["memory_privacy"]
    )
    assert any(
        "test_user_api_issues_single_use_memory_consent_capability" in node_id
        for node_id in scenario_mapping["memory_privacy"]
    )


def test_generic_release_smoke_reports_all_scenarios_passed_and_redacts_tails() -> None:
    commands: list[list[str]] = []

    def runner(command):
        commands.append(list(command))
        test_count = sum(str(part).startswith("tests/") for part in command)
        _write_junit(command, passed=test_count)
        return SimpleNamespace(
            returncode=0,
            stdout="passed\nAuthorization: Bearer sk-super-secret",
            stderr="",
        )

    report = smoke.run_smoke(command_runner=runner)

    assert report["ok"] is True
    assert report["mode"] == "generic_agent_release_smoke"
    assert report["scenario_count"] == len(EXPECTED_SCENARIOS)
    assert report["passed_count"] == len(EXPECTED_SCENARIOS)
    assert report["failed_count"] == 0
    assert [scenario["status"] for scenario in report["scenarios"]] == [
        "passed"
    ] * len(EXPECTED_SCENARIOS)
    assert len(commands) == len(EXPECTED_SCENARIOS)
    expected_test_count = sum(
        len(node_ids) for _scenario_id, node_ids in smoke.GENERIC_AGENT_SCENARIOS
    )
    assert report["collected_count"] == expected_test_count
    assert report["passed_test_count"] == expected_test_count
    assert report["failed_test_count"] == 0
    assert report["error_test_count"] == 0
    assert report["skipped_test_count"] == 0
    assert report["xfailed_test_count"] == 0
    assert report["timeout_count"] == 0
    assert all(
        scenario["metrics_status"] == "available"
        and scenario["blocking_conditions"] == []
        for scenario in report["scenarios"]
    )
    assert all(
        command[:6]
        == [smoke.sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        for command in commands
    )
    assert "sk-super-secret" not in json.dumps(report, ensure_ascii=False)


def test_generic_release_smoke_reports_one_failed_scenario() -> None:
    def runner(command):
        failed = any("app_resolution" in part for part in command)
        _write_junit(command, failed=1) if failed else _write_junit(command, passed=1)
        return SimpleNamespace(
            returncode=1 if failed else 0,
            stdout="",
            stderr="one focused scenario failed" if failed else "",
        )

    scenarios = (
        ("file_resolution", ("tests/example.py::test_file_resolution",)),
        ("app_resolution", ("tests/example.py::test_app_resolution",)),
    )
    report = smoke.run_smoke(command_runner=runner, scenarios=scenarios)

    assert report["ok"] is False
    assert report["passed_count"] == 1
    assert report["failed_count"] == 1
    assert [scenario["status"] for scenario in report["scenarios"]] == [
        "passed",
        "failed",
    ]
    assert report["scenarios"][1]["returncode"] == 1
    assert report["scenarios"][1]["failed_test_count"] == 1
    assert "failed_tests_present" in report["scenarios"][1]["blocking_conditions"]
    assert report["scenarios"][1]["stderr_tail"] == "one focused scenario failed"


def test_generic_release_smoke_fails_closed_without_junit_metrics() -> None:
    report = smoke.run_smoke(
        command_runner=lambda _command: SimpleNamespace(
            returncode=0,
            stdout="1 passed",
            stderr="",
        ),
        scenarios=(("grounded_completion", ("tests/example.py::test_passed",)),),
    )

    assert report["ok"] is False
    assert report["scenarios"][0]["metrics_status"] == "missing"
    assert report["scenarios"][0]["blocking_conditions"] == [
        "test_metrics_missing"
    ]


def test_generic_release_smoke_rejects_skipped_and_xfailed_tests() -> None:
    def runner(command):
        if any("test_skipped" in part for part in command):
            _write_junit(command, skipped=1)
        else:
            _write_junit(command, xfailed=1)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    report = smoke.run_smoke(
        command_runner=runner,
        scenarios=(
            ("skipped", ("tests/example.py::test_skipped",)),
            ("xfailed", ("tests/example.py::test_xfailed",)),
        ),
    )

    assert report["ok"] is False
    assert report["skipped_test_count"] == 1
    assert report["xfailed_test_count"] == 1
    assert report["passed_test_count"] == 0
    assert report["failed_scenarios"] == ["skipped", "xfailed"]
    assert "skipped_tests_present" in report["scenarios"][0]["blocking_conditions"]
    assert "xfailed_tests_present" in report["scenarios"][1]["blocking_conditions"]


def test_generic_release_smoke_reports_timeout_without_hanging() -> None:
    def runner(command):
        raise subprocess.TimeoutExpired(command, smoke.SCENARIO_TIMEOUT_SECONDS)

    report = smoke.run_smoke(
        command_runner=runner,
        scenarios=(("bounded_recovery", ("tests/example.py::test_timeout",)),),
    )

    assert report["ok"] is False
    assert report["failed_scenarios"] == ["bounded_recovery"]
    assert report["scenarios"][0]["returncode"] == 124
    assert report["timeout_count"] == 1
    assert "scenario_timeout" in report["scenarios"][0]["blocking_conditions"]
    assert "timed out after 180s" in report["scenarios"][0]["stderr_tail"]


def test_generic_release_smoke_cli_writes_json_report(tmp_path, monkeypatch) -> None:
    expected = {
        "ok": True,
        "mode": "generic_agent_release_smoke",
        "scenario_count": len(EXPECTED_SCENARIOS),
        "passed_count": len(EXPECTED_SCENARIOS),
        "failed_count": 0,
        "scenarios": [],
    }
    monkeypatch.setattr(smoke, "run_smoke", lambda: expected)
    report_path = tmp_path / "nested" / "generic-agent-smoke.json"

    exit_code = smoke.main(["--report-json", str(report_path)])

    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8")) == expected
