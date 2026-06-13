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


def test_capability_summary_reports_full_native_agent_matrix():
    report = {
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
    assert result["status_counts"] == {"passed": 13, "missing": 0}
    assert result["missing_capability_ids"] == []
    by_id = {item["id"]: item for item in result["capabilities"]}
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
