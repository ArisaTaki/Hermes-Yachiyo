from __future__ import annotations

import json

from scripts import summarize_native_agent_capabilities as capability_summary
from scripts import summarize_release_readiness as readiness


def _capability(capability_id: str, status: str, evidence: dict[str, object] | None = None):
    definition = next(
        item
        for item in capability_summary.CAPABILITY_DEFINITIONS
        if item["id"] == capability_id
    )
    return {
        **definition,
        "category": capability_summary.capability_category(capability_id),
        "status": status,
        "evidence_summary": evidence or {},
    }


def test_release_readiness_groups_runtime_and_provider_blockers_without_secret_values():
    capabilities = [
        _capability(
            "source_real_desktop_interaction",
            "missing",
            {
                "status": "failed",
                "stage": "session_preflight",
                "error": "desktop_session_locked",
                "blocking_conditions": ["desktop_session_locked"],
                "recovery_hints": ["Unlock the active macOS user session."],
                "recommended_tools": ["desktop.active_window"],
                "recovery_actions": [
                    {
                        "label": "Retry foreground check",
                        "tool": "desktop.active_window",
                        "input": {"app_name": "Calculator"},
                        "risk_level": "low",
                    }
                ],
            },
        ),
        _capability("provider_text_stream", "missing"),
        _capability("provider_tool_call_stream", "missing"),
        _capability("packaged_backend_bridge_identity", "passed"),
    ]
    matrix = {
        **capability_summary.capability_matrix_status_summary(capabilities),
        "status": "incomplete",
        "capabilities": capabilities,
        "source_reports": ["tmp/rc-current.json"],
    }

    diagnostics = readiness.release_readiness_diagnostics(
        matrix,
        env={
            "OHA_YACHIYO_SMOKE_BASE_URL": "https://provider.example.test/v1",
            "OHA_YACHIYO_SMOKE_MODEL": "",
            "OHA_YACHIYO_SMOKE_API_KEY": "sk-secret-provider-key",
        },
    )

    assert diagnostics["ok"] is False
    assert diagnostics["status"] == "incomplete"
    assert diagnostics["passed_count"] == 1
    assert diagnostics["missing_count"] == 3
    blockers = {(item["type"], item["id"]): item for item in diagnostics["blockers"]}
    runtime_blocker = blockers[("runtime_blocking_condition", "desktop_session_locked")]
    assert runtime_blocker["capabilities"][0]["id"] == "source_real_desktop_interaction"
    assert runtime_blocker["recovery_hints"] == ["Unlock the active macOS user session."]
    assert runtime_blocker["recovery_actions"][0]["tool"] == "desktop.active_window"
    provider_blocker = blockers[
        ("provider_credentials_missing", "oha_yachiyo_smoke_credentials")
    ]
    assert provider_blocker["missing_env"] == ["OHA_YACHIYO_SMOKE_MODEL"]
    serialized = json.dumps(diagnostics)
    assert "sk-secret-provider-key" not in serialized
    assert "provider.example" not in serialized


def test_release_readiness_treats_default_real_desktop_evidence_as_optional():
    capabilities = [
        _capability("source_real_desktop_app_open", "missing", {"status": "skipped", "run_requested": False}),
        _capability("source_real_desktop_ui_inspection", "missing", {"status": "skipped", "run_requested": False}),
        _capability("source_real_desktop_interaction", "missing", {"status": "skipped", "run_requested": False}),
        _capability("provider_text_stream", "passed"),
        _capability("packaged_backend_bridge_identity", "passed"),
    ]
    matrix = {
        **capability_summary.capability_matrix_status_summary(capabilities),
        "status": "passed",
        "capabilities": capabilities,
        "source_reports": ["tmp/rc-current.json"],
    }

    diagnostics = readiness.release_readiness_diagnostics(matrix, env={})

    assert diagnostics["ok"] is True
    assert diagnostics["status"] == "ready"
    assert diagnostics["missing_count"] == 0
    assert diagnostics["missing_capability_ids"] == []
    assert diagnostics["optional_missing_count"] == 3
    assert diagnostics["optional_missing_capability_ids"] == [
        "source_real_desktop_app_open",
        "source_real_desktop_ui_inspection",
        "source_real_desktop_interaction",
    ]
    assert diagnostics["blockers"] == []
    markdown = readiness.render_markdown(diagnostics)
    assert "Optional Opt-In Evidence" in markdown
    assert "default isolated-desktop release path" in markdown


def test_release_readiness_cli_writes_json_and_markdown(tmp_path, monkeypatch):
    for name in readiness.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    report_path = tmp_path / "rc.json"
    output_json = tmp_path / "readiness.json"
    output_markdown = tmp_path / "readiness.md"
    report_path.write_text(
        json.dumps(
            {
                "real_desktop_interaction_smoke": {
                    "status": "failed",
                    "evidence": {
                        "ok": False,
                        "mode": "real_desktop_interaction_smoke",
                        "case_count": 1,
                        "cases": [{"id": "type_click_verify_control"}],
                        "error": "desktop_session_locked",
                        "stage": "session_preflight",
                        "blocking_conditions": ["desktop_session_locked"],
                        "recovery_hints": ["Unlock the active macOS user session."],
                        "recovery_actions": [
                            {
                                "label": "Retry foreground check",
                                "tool": "desktop.active_window",
                                "permission_target": "desktop_session_unlocked",
                            }
                        ],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = readiness.main(
        [
            str(report_path),
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )

    assert exit_code == 1
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    assert "source_real_desktop_interaction" in payload["missing_capability_ids"]
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "Capability matrix:" in markdown
    assert "Runtime blocker: desktop_session_locked" in markdown
    assert "stage: `session_preflight`" in markdown
    assert "error: `desktop_session_locked`" in markdown
    assert (
        "Retry foreground check -> desktop.active_window (desktop_session_unlocked)"
        in markdown
    )
    assert "OHA_YACHIYO_SMOKE_API_KEY" in markdown


def test_release_readiness_rebuilds_raw_report_matrix_to_keep_blockers():
    stale_capabilities = [
        _capability("source_real_desktop_interaction", "missing"),
        _capability("provider_text_stream", "missing"),
    ]
    report = {
        "native_agent_capability_matrix": {
            **capability_summary.capability_matrix_status_summary(stale_capabilities),
            "status": "incomplete",
            "capabilities": stale_capabilities,
        },
        "real_desktop_interaction_smoke": {
            "status": "failed",
            "evidence": {
                "ok": False,
                "mode": "real_desktop_interaction_smoke",
                "case_count": 1,
                "cases": [{"id": "type_click_verify_control"}],
                "error": "desktop_session_locked",
                "blocking_conditions": ["desktop_session_locked"],
            },
        },
    }

    matrix = readiness._capability_matrix_for_readiness(report)
    diagnostics = readiness.release_readiness_diagnostics(matrix, env={})

    blockers = {(item["type"], item["id"]) for item in diagnostics["blockers"]}
    assert ("runtime_blocking_condition", "desktop_session_locked") in blockers
