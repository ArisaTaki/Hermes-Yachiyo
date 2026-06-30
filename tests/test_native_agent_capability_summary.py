from __future__ import annotations

import json

from scripts import summarize_native_agent_capabilities as summary


def _provider_check(label: str, checks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "label": label,
        "exit_code": 0,
        "summary": {
            "ok": True,
            "checks": checks,
        },
    }


def _passed_section(mode: str, *, cases: list[str] | None = None) -> dict[str, object]:
    return {
        "status": "passed",
        "evidence": {
            "ok": True,
            "mode": mode,
            "case_count": len(cases or []),
            "cases": [{"id": case_id} for case_id in cases or []],
        },
    }


def test_capability_summary_reports_full_native_agent_matrix():
    report = {
        "data_analysis_artifact_smoke": _passed_section(
            "data_analysis_artifact_smoke",
            cases=["csv", "json", "text_table", "xlsx"],
        ),
        "browser_planner_artifact_smoke": _passed_section(
            "browser_planner_artifact_smoke",
            cases=["current_page_report"],
        ),
        "desktop_planner_discovery_smoke": _passed_section(
            "desktop_planner_discovery_smoke",
            cases=["generic_app_open"],
        ),
        "real_desktop_discovery_smoke": _passed_section(
            "real_desktop_discovery_smoke",
            cases=["safari"],
        ),
        "real_desktop_app_open_smoke": _passed_section(
            "real_desktop_app_open_smoke",
            cases=["calculator"],
        ),
        "real_desktop_ui_inspection_smoke": _passed_section(
            "real_desktop_ui_inspection_smoke",
            cases=["calculator"],
        ),
        "real_desktop_interaction_smoke": _passed_section(
            "real_desktop_interaction_smoke",
            cases=["calculator"],
        ),
        "planner_runtime_tool_parity_smoke": _passed_section(
            "planner_runtime_tool_parity_smoke",
            cases=["app_scoped_ui_click"],
        ),
        "media_playback_chain_smoke": _passed_section(
            "media_playback_chain_smoke",
            cases=["apple_music_open_and_play"],
        ),
        "agent_entrypoint_desktop_execution_smoke": _passed_section(
            "agent_entrypoint_desktop_execution_smoke",
            cases=["main_chat_generic_app_open_before_model"],
        ),
        "agent_entrypoint_data_analysis_smoke": _passed_section(
            "agent_entrypoint_data_analysis_smoke",
            cases=["studio_agent_run_data_analysis_before_model"],
        ),
        "approval_policy_gate_smoke": _passed_section("approval_policy_gate_smoke"),
        "approval_resume_timeline_smoke": _passed_section("approval_resume_timeline_smoke"),
        "runtime_approval_resume_smoke": _passed_section("runtime_approval_resume_smoke"),
        "yachiyo_route_approval_smoke": _passed_section("yachiyo_route_approval_smoke"),
        "group_run_timeline_smoke": _passed_section("group_run_timeline_smoke"),
        "provider_smoke": {
            "checks": [
                {
                    "label": "text_stream",
                    "exit_code": 0,
                    "summary": {
                        "ok": True,
                        "finish_reasons": ["stop"],
                        "content_chars": 42,
                    },
                },
                {
                    "label": "tool_call_stream",
                    "exit_code": 0,
                    "summary": {
                        "ok": True,
                        "tool_call_count": 1,
                        "tool_result_followup_finish_reasons": ["stop"],
                    },
                },
                _provider_check(
                    "native_agent_full_chain",
                    [
                        {"name": "model_profile_readiness", "ok": True},
                        {"name": "agent_workspace_read", "ok": True},
                        {"name": "agent_artifact_write", "ok": True},
                        {
                            "name": "agent_multi_tool_pipeline",
                            "ok": True,
                            "tool_call_count": 2,
                            "artifact_paths": ["agent-context.md", "pipeline-report.md"],
                        },
                        {"name": "workflow_child_agent_artifact", "ok": True},
                        {"name": "terminal_approval_resume", "ok": True},
                        {"name": "main_chat_model_loop", "ok": True},
                    ],
                ),
                _provider_check(
                    "native_workflow_full_chain",
                    [
                        {"name": "advanced_workflow_orchestration", "ok": True},
                        {"name": "workflow_budget_boundary", "ok": True},
                    ],
                ),
            ]
        },
        "packaged_backend_bridge_smoke": {
            "status": "passed",
            "bridge_statuses": [{"service": "oha-yachiyo"}],
        },
        "dmg_app_smoke": {
            "status": "passed",
            "bridge_statuses": [{"service": "oha-yachiyo"}],
        },
    }

    result = summary.summarize_capabilities(report)

    assert result["ok"] is True
    assert result["status_counts"] == {"passed": 29, "missing": 0}
    assert result["category_status_counts"] == {
        "source": {"passed": 16, "missing": 0},
        "provider": {"passed": 11, "missing": 0},
        "packaged": {"passed": 2, "missing": 0},
    }
    assert result["missing_capability_ids"] == []
    assert result["missing_by_category"] == {}
    assert result["next_actions"] == []
    assert result["capability_count"] == 29
    by_id = {item["id"]: item for item in result["capabilities"]}
    source_desktop = by_id["source_agent_entrypoint_desktop_execution"]
    assert source_desktop["status"] == "passed"
    assert source_desktop["category"] == "source"
    assert source_desktop["evidence_summary"]["case_ids"] == [
        "main_chat_generic_app_open_before_model"
    ]
    multi_tool = by_id["agent_multi_tool_pipeline"]
    assert multi_tool["status"] == "passed"
    assert multi_tool["evidence_summary"]["tool_call_count"] == 2
    assert "pipeline-report.md" in multi_tool["evidence_summary"]["artifact_paths"]


def test_capability_summary_marks_missing_multi_tool_pipeline():
    report = {
        "provider_smoke": {
            "checks": [
                _provider_check(
                    "native_agent_full_chain",
                    [
                        {
                            "name": "agent_multi_tool_pipeline",
                            "ok": True,
                            "tool_call_count": 1,
                            "artifact_paths": ["agent-context.md"],
                        },
                    ],
                )
            ]
        }
    }

    result = summary.summarize_capabilities(report)

    assert result["ok"] is False
    assert "agent_multi_tool_pipeline" in result["missing_capability_ids"]


def test_capability_summary_reports_source_only_partial_matrix():
    report = {
        "data_analysis_artifact_smoke": _passed_section(
            "data_analysis_artifact_smoke",
            cases=["csv", "json", "xlsx"],
        ),
        "desktop_planner_discovery_smoke": _passed_section(
            "desktop_planner_discovery_smoke",
            cases=["generic_app_open"],
        ),
        "agent_entrypoint_desktop_execution_smoke": _passed_section(
            "agent_entrypoint_desktop_execution_smoke",
            cases=["main_chat_generic_app_open_before_model"],
        ),
    }

    result = summary.summarize_capabilities(report)

    by_id = {item["id"]: item for item in result["capabilities"]}
    assert result["ok"] is False
    assert by_id["source_data_analysis_artifact"]["status"] == "passed"
    assert by_id["source_desktop_planner_discovery"]["status"] == "passed"
    assert by_id["source_agent_entrypoint_desktop_execution"]["status"] == "passed"
    assert by_id["provider_text_stream"]["status"] == "missing"
    assert "provider_text_stream" in result["missing_capability_ids"]
    assert result["status_counts"] == {"passed": 3, "missing": 26}
    assert result["missing_by_category"]["source"]
    assert result["missing_by_category"]["provider"]
    assert result["missing_by_category"]["packaged"] == [
        "packaged_backend_bridge_identity",
        "packaged_app_bridge_isolation",
    ]
    action_by_id = {item["id"]: item for item in result["next_actions"]}
    assert set(action_by_id) == {
        "source_capability_smoke",
        "real_desktop_smokes",
        "provider_smoke",
        "packaged_backend_bridge_smoke",
        "packaged_app_smoke",
    }
    assert "source_browser_research_artifact" in action_by_id["source_capability_smoke"]["capability_ids"]
    assert "source_real_desktop_interaction" in action_by_id["real_desktop_smokes"]["capability_ids"]
    assert "provider_text_stream" in action_by_id["provider_smoke"]["capability_ids"]
    assert "--run-provider-smoke" in action_by_id["provider_smoke"]["command"]


def test_capability_summary_cli_writes_json(tmp_path):
    report_path = tmp_path / "rc.json"
    output_path = tmp_path / "matrix.json"
    report_path.write_text(
        json.dumps(
            {
                "provider_smoke": {"checks": []},
            }
        ),
        encoding="utf-8",
    )

    assert summary.main([str(report_path), "--output-json", str(output_path)]) == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["source_report"] == str(report_path)
    assert payload["ok"] is False
