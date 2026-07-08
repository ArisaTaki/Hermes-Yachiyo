from __future__ import annotations

import json
import zipfile

from scripts import summarize_native_agent_capabilities as capability_summary
from scripts import summarize_release_smoke as release_smoke


def _capability(capability_id: str, status: str = "passed") -> dict[str, object]:
    definition = next(
        item
        for item in capability_summary.CAPABILITY_DEFINITIONS
        if item["id"] == capability_id
    )
    return {
        **definition,
        "category": capability_summary.capability_category(capability_id),
        "status": status,
        "evidence_summary": {"source": "test"},
    }


def _matrix_report(*capability_ids: str) -> dict[str, object]:
    capabilities = [_capability(capability_id) for capability_id in capability_ids]
    return {
        "native_agent_capability_matrix": {
            **capability_summary.capability_matrix_status_summary(capabilities),
            "status": "passed",
            "capabilities": capabilities,
        }
    }


def _item_by_id(summary: dict[str, object], item_id: str) -> dict[str, object]:
    return next(
        item
        for item in summary["items"]
        if isinstance(item, dict) and item.get("id") == item_id
    )


def _diagnostics_zip(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "diagnostics/manifest.json",
            json.dumps(
                {
                    "ok": True,
                    "included_count": 1,
                    "redaction": {"applied": True},
                    "included": [{"source": "tmp/rc.json"}],
                }
            ),
        )


def _public_demo_report_with_passed_flows(passed_flow_ids: set[str]) -> dict[str, object]:
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    missing_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids
    ]
    return {
        "ok": True,
        "status": "partial" if missing_flow_ids else "passed",
        "release_level": "partial_demo_ready"
        if missing_flow_ids
        else "full_public_demo_ready",
        "complete": not missing_flow_ids,
        "selected_count": len(passed_flow_ids),
        "passed_count": len(passed_flow_ids),
        "required_flow_count": len(required_flow_ids),
        "passed_required_flow_count": len(passed_flow_ids),
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": [
            {
                "id": flow_id,
                "status": "skipped",
                "reason": "not collected in this batch",
            }
            for flow_id in missing_flow_ids
        ],
        "flows": [
            {
                "id": flow_id,
                "status": "passed" if flow_id in passed_flow_ids else "skipped",
            }
            for flow_id in required_flow_ids
        ],
    }


def _oha_desktop_agent_release_smoke_report() -> dict[str, object]:
    section_ids = release_smoke.OHA_DESKTOP_AGENT_SECTION_EVIDENCE.keys()
    return {
        "ok": True,
        "mode": release_smoke.OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE,
        "section_count": len(section_ids),
        "failed_sections": [],
        "checks": {"all_sections_passed": True},
        "sections": [
            {
                "id": section_id,
                "objective": f"cover {section_id}",
                "ok": True,
                "mode": section_id,
                "report": {
                    "ok": True,
                    **(
                        {
                            "desktop_backend_kind": "virtual_desktop_backend",
                            "desktop_backend_is_loopback": False,
                            "desktop_backend_ready_for_public_release": True,
                            "requires_real_virtual_desktop_backend": False,
                            "provider_contract": {
                                "ok": True,
                                "contract_version": "oha-yachiyo.desktop-provider.v1",
                                "blocking_conditions": [],
                            },
                        }
                        if section_id == "isolated_desktop_provider"
                        else {}
                    ),
                },
            }
            for section_id in section_ids
        ],
        "isolated_provider_backend": {
            "desktop_backend_kind": "virtual_desktop_backend",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "provider_contract_ok": True,
            "provider_contract_version": "oha-yachiyo.desktop-provider.v1",
            "provider_contract_blocking_conditions": [],
        },
    }


def _provider_workflow_full_chain_report() -> dict[str, object]:
    return {
        "mode": "native_workflow_full_chain_smoke",
        "ok": True,
        "skipped": False,
    }


def _native_provider_contract_report() -> dict[str, object]:
    return {
        "mode": "native_provider_contract_smoke",
        "ok": True,
        "provider": "local_fake_openai_compatible_sse",
        "checks": [
            {
                "label": "native_workflow_full_chain_contract",
                "ok": True,
                "summary": {
                    "ok": True,
                    "checks": [
                        {"name": "advanced_workflow_orchestration", "ok": True},
                        {"name": "workflow_budget_boundary", "ok": True},
                    ],
                },
            },
        ],
    }


def test_release_smoke_summary_passes_with_required_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "rc.json"
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    oha_report_path = tmp_path / "tmp" / "oha-desktop-agent-release-smoke.json"
    provider_workflow_path = tmp_path / "tmp" / "provider-workflow.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            _matrix_report(
                "packaged_app_bridge_isolation",
                "source_agent_entrypoint_desktop_execution",
                "source_agent_studio_planner_orchestration",
                "source_approval_resume_timeline",
                "source_yachiyo_route_approval",
                "source_group_run_timeline",
                "source_agent_entrypoint_data_analysis",
                "source_data_analysis_artifact",
            )
        ),
        encoding="utf-8",
    )
    public_demo_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "passed",
                "release_level": "full_public_demo_ready",
                "complete": True,
                "selected_count": 19,
                "passed_count": 19,
                "required_flow_count": 19,
                "passed_required_flow_count": 19,
                "missing_required_flow_ids": [],
                "release_blockers": [],
                "flows": [{"id": "real_desktop_app_open", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    oha_report_path.write_text(
        json.dumps(_oha_desktop_agent_release_smoke_report()),
        encoding="utf-8",
    )
    provider_workflow_path.write_text(
        json.dumps(_provider_workflow_full_chain_report()),
        encoding="utf-8",
    )
    diagnostics_zip = tmp_path / "tmp" / "diagnostics.zip"
    _diagnostics_zip(diagnostics_zip)

    summary = release_smoke.summarize_release_smoke(
        [report_path, public_demo_path, oha_report_path, provider_workflow_path],
        diagnostics_zips=[diagnostics_zip],
    )

    assert summary["ok"] is True
    assert summary["status"] == "passed"
    assert summary["passed_count"] == summary["item_count"] == 10
    assert summary["missing_item_ids"] == []
    oha_item = next(item for item in summary["items"] if item["id"] == "oha_desktop_agent_product")
    assert oha_item["present_evidence_ids"] == [
        release_smoke.OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE,
        "oha_isolated_desktop_provider",
        "oha_real_virtual_desktop_backend",
    ]
    assert "oha_deepagent_core" in oha_item["related_evidence_ids"]
    assert "oha_isolated_desktop_provider" in oha_item["related_evidence_ids"]
    assert "oha_isolated_desktop_backend_boundary" in oha_item["related_evidence_ids"]


def test_release_smoke_summary_rejects_standalone_entrypoint_smoke_without_task_core(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "entrypoint-desktop.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "agent_entrypoint_desktop_execution_smoke",
                "case_count": 1,
                "cases": [{"id": "main_chat_generic_app_open_before_model"}],
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    chat_item = _item_by_id(summary, "chat_desktop_task")
    assert summary["ok"] is False
    assert chat_item["status"] == "missing"
    assert "source_agent_entrypoint_desktop_execution" in chat_item[
        "missing_evidence_ids"
    ]


def test_release_smoke_summary_requires_agent_studio_planner_orchestration(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "rc.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            _matrix_report(
                "source_approval_resume_timeline",
            )
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    studio_item = _item_by_id(summary, "agent_studio_run_timeline")
    assert studio_item["status"] == "missing"
    assert studio_item["missing_evidence_ids"] == [
        "source_agent_studio_planner_orchestration"
    ]


def test_release_smoke_summary_requires_isolated_desktop_provider_section(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "oha-without-isolated-provider.json"
    payload = _oha_desktop_agent_release_smoke_report()
    payload["sections"] = [
        section
        for section in payload["sections"]
        if section["id"] != "isolated_desktop_provider"
    ]
    payload["section_count"] = len(payload["sections"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = release_smoke.summarize_release_smoke([report_path])

    assert "oha_desktop_agent_product" in summary["missing_item_ids"]
    oha_item = next(item for item in summary["items"] if item["id"] == "oha_desktop_agent_product")
    assert oha_item["present_evidence_ids"] == [
        release_smoke.OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE,
        "oha_real_virtual_desktop_backend",
    ]
    assert oha_item["missing_evidence_ids"] == ["oha_isolated_desktop_provider"]
    action = next(
        item for item in summary["next_actions"] if item["id"] == "oha_desktop_agent_product"
    )
    assert "--run-isolated-provider-smoke" in action["command"]
    assert "--use-configured-virtual-desktop-provider" in action["command"]


def test_release_smoke_summary_requires_real_virtual_desktop_backend(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "oha-loopback-provider.json"
    payload = _oha_desktop_agent_release_smoke_report()
    loopback_backend = {
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
        "provider_contract": {
            "ok": False,
            "contract_version": "oha-yachiyo.desktop-provider.v1",
            "blocking_conditions": [
                "loopback_desktop_backend",
                "desktop_backend_not_release_ready",
                "real_virtual_desktop_backend_required",
            ],
        },
    }
    payload["isolated_provider_backend"] = dict(loopback_backend)
    for section in payload["sections"]:
        if section["id"] == "isolated_desktop_provider":
            section["report"] = {"ok": True, **loopback_backend}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = release_smoke.summarize_release_smoke([report_path])

    assert "oha_desktop_agent_product" in summary["missing_item_ids"]
    oha_item = next(
        item for item in summary["items"] if item["id"] == "oha_desktop_agent_product"
    )
    assert oha_item["present_evidence_ids"] == [
        release_smoke.OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE,
        "oha_isolated_desktop_provider",
    ]
    assert oha_item["missing_evidence_ids"] == ["oha_real_virtual_desktop_backend"]
    assert oha_item["release_blockers"][0]["reason"] == (
        "real_virtual_desktop_backend_required"
    )
    action = next(
        item for item in summary["next_actions"] if item["id"] == "oha_desktop_agent_product"
    )
    assert action["release_blockers"][0]["evidence_summary"][
        "desktop_backend_kind"
    ] == "loopback_session_harness"
    assert action["release_blockers"][0]["evidence_summary"][
        "provider_contract_ok"
    ] is False
    assert "loopback_desktop_backend" in action["release_blockers"][0][
        "evidence_summary"
    ]["provider_contract_blocking_conditions"]
    assert "--use-configured-virtual-desktop-provider" in action["command"]


def test_release_smoke_summary_requires_verified_desktop_provider_contract(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "oha-unverified-provider-contract.json"
    payload = _oha_desktop_agent_release_smoke_report()
    backend_without_contract = {
        "desktop_backend_kind": "virtual_desktop_backend",
        "desktop_backend_is_loopback": False,
        "desktop_backend_ready_for_public_release": True,
        "requires_real_virtual_desktop_backend": False,
    }
    payload["isolated_provider_backend"] = dict(backend_without_contract)
    for section in payload["sections"]:
        if section["id"] == "isolated_desktop_provider":
            section["report"] = {"ok": True, **backend_without_contract}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = release_smoke.summarize_release_smoke([report_path])

    assert "oha_desktop_agent_product" in summary["missing_item_ids"]
    oha_item = next(
        item for item in summary["items"] if item["id"] == "oha_desktop_agent_product"
    )
    assert oha_item["present_evidence_ids"] == [
        release_smoke.OHA_DESKTOP_AGENT_RELEASE_SMOKE_MODE,
        "oha_isolated_desktop_provider",
    ]
    assert oha_item["missing_evidence_ids"] == ["oha_real_virtual_desktop_backend"]
    evidence_summary = oha_item["release_blockers"][0]["evidence_summary"]
    assert evidence_summary["provider_contract_ok"] is None
    assert evidence_summary["provider_contract_blocking_conditions"] == [
        "virtual_desktop_provider_contract_not_ready"
    ]


def test_release_smoke_summary_keeps_backend_blocker_when_release_smoke_fails(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "oha-failed-loopback-provider.json"
    payload = _oha_desktop_agent_release_smoke_report()
    payload["ok"] = False
    payload["failed_sections"] = ["isolated_desktop_provider"]
    loopback_backend = {
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
        "provider_contract_ok": False,
        "provider_contract_version": "oha-yachiyo.desktop-provider.v1",
        "provider_contract_blocking_conditions": [
            "loopback_desktop_backend",
            "desktop_backend_not_release_ready",
            "real_virtual_desktop_backend_required",
        ],
    }
    payload["isolated_provider_backend"] = dict(loopback_backend)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = release_smoke.summarize_release_smoke([report_path])

    action = next(
        item for item in summary["next_actions"] if item["id"] == "oha_desktop_agent_product"
    )
    evidence_summary = action["release_blockers"][0]["evidence_summary"]
    assert evidence_summary["desktop_backend_kind"] == "loopback_session_harness"
    assert evidence_summary["provider_contract_ok"] is False
    assert "loopback_desktop_backend" in evidence_summary[
        "provider_contract_blocking_conditions"
    ]


def test_release_smoke_summary_reports_missing_items_and_next_actions(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "partial.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(_matrix_report("source_data_analysis_artifact")),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    assert summary["ok"] is False
    assert "oha_desktop_agent_product" in summary["missing_item_ids"]
    assert "diagnostics_export" in summary["missing_item_ids"]
    assert "public_demo" in summary["missing_item_ids"]
    artifact = next(item for item in summary["items"] if item["id"] == "artifact_readback")
    assert artifact["status"] == "passed"
    packaged = next(item for item in summary["items"] if item["id"] == "packaged_launch")
    assert packaged["missing_evidence_ids"] == ["packaged_app_bridge_isolation"]
    commands = [item["command"] for item in summary["next_actions"]]
    assert any("collect_release_diagnostics.py" in command for command in commands)
    assert any("run_public_demo_smokes.py" in command for command in commands)


def test_release_smoke_summary_requires_complete_public_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "partial",
                "release_level": "partial_demo_ready",
                "complete": False,
                "selected_count": 13,
                "passed_count": 13,
                "required_flow_count": 19,
                "passed_required_flow_count": 13,
                "missing_required_flow_ids": ["real_desktop_app_open"],
                "release_blockers": [
                    {
                        "id": "real_desktop_app_open",
                        "status": "failed",
                        "opt_in_flag": "--include-real-desktop-open",
                        "opt_in_reason": "opens a real macOS application",
                        "reason": "desktop_session_locked",
                        "evidence_summary": {
                            "stage": "session_preflight",
                            "blocking_condition": "desktop_session_locked",
                            "checks": {"desktop_session_ready": False},
                        },
                    }
                ],
                "full_demo_command": "python scripts/run_public_demo_smokes.py --full-test-command",
                "flows": [{"id": "real_desktop_discovery", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([public_demo_path])

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "missing"
    assert public_demo["present_evidence_ids"] == []
    assert public_demo["missing_evidence_ids"] == ["public_demo_complete"]
    assert public_demo["related_evidence_ids"] == [
        "public_demo_assessment",
        "public_demo_selected",
    ]
    assert summary["public_demo"]["release_level"] == "partial_demo_ready"
    assert summary["public_demo"]["passed_required_flow_count"] == 13
    assert summary["public_demo"]["required_flow_count"] == 19
    assert summary["public_demo"]["remaining_required_flow_count"] == 1
    assessment = public_demo["related_evidence"]["public_demo_assessment"][0]
    assert assessment["release_level"] == "partial_demo_ready"
    assert assessment["missing_required_flow_ids"] == ["real_desktop_app_open"]
    assert assessment["release_blockers"][0]["opt_in_flag"] == "--include-real-desktop-open"
    assert assessment["release_blockers"][0]["reason"] == "desktop_session_locked"
    action = next(item for item in summary["next_actions"] if item["id"] == "public_demo")
    assert action["command"] == (
        "python scripts/run_public_demo_smokes.py --include-real-desktop-open "
        "--output-json tmp/public-demo-smokes-missing.json "
        "--output-markdown tmp/public-demo-smokes-missing.md"
    )
    assert "--full-test-command" not in action["command"]
    assert action["release_level"] == "partial_demo_ready"
    assert action["missing_required_flow_ids"] == ["real_desktop_app_open"]
    assert action["release_blockers"][0]["reason"] == "desktop_session_locked"
    markdown = release_smoke.render_markdown(summary)
    assert "Public demo: 13/19 required flows (`partial_demo_ready`)" in markdown
    assert "Demo blocker `real_desktop_app_open`: `desktop_session_locked`" in markdown


def test_release_smoke_summary_projects_rc_capabilities_into_public_demo(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    missing_from_demo = {
        "real_desktop_app_open",
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
        "studio_replay_ui",
        "workflow_ui",
    }
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    rc_report_path = tmp_path / "tmp" / "full-local-rc.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            _public_demo_report_with_passed_flows(set(required_flow_ids) - missing_from_demo)
        ),
        encoding="utf-8",
    )
    rc_report_path.write_text(
        json.dumps(
            _matrix_report(
                "source_real_desktop_app_open",
                "source_real_desktop_ui_inspection",
                "source_real_desktop_interaction",
            )
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([public_demo_path, rc_report_path])

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "missing"
    details = public_demo["related_evidence"]["public_demo_assessment"][-1]
    assert details["kind"] == "public_demo_aggregate"
    assert "real_desktop_app_open" not in details["missing_required_flow_ids"]
    assert "real_desktop_ui_inspection" not in details["missing_required_flow_ids"]
    assert "real_desktop_interaction" not in details["missing_required_flow_ids"]
    assert details["missing_required_flow_ids"] == [
        "studio_replay_ui",
        "workflow_ui",
    ]
    projection = next(
        item
        for item in public_demo["related_evidence"]["public_demo_assessment"]
        if item["kind"] == "rc_capability_public_demo_projection"
    )
    assert projection["capability_flow_map"] == {
        "source_real_desktop_app_open": "real_desktop_app_open",
        "source_real_desktop_ui_inspection": "real_desktop_ui_inspection",
        "source_real_desktop_interaction": "real_desktop_interaction",
    }
    action = next(item for item in summary["next_actions"] if item["id"] == "public_demo")
    assert action["missing_required_flow_ids"] == [
        "studio_replay_ui",
        "workflow_ui",
    ]
    assert action["command"] == (
        "python scripts/run_public_demo_smokes.py --include-ui "
        "--output-json tmp/public-demo-smokes-missing.json "
        "--output-markdown tmp/public-demo-smokes-missing.md"
    )
    assert "--include-real-desktop-open" not in action["command"]
    assert "--include-real-desktop-ui-inspection" not in action["command"]
    assert "--include-real-desktop-interaction" not in action["command"]


def test_release_smoke_summary_projects_electron_ui_smokes_into_public_demo(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    missing_from_demo = {
        "real_desktop_app_open",
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
        "studio_replay_ui",
        "workflow_ui",
    }
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    rc_report_path = tmp_path / "tmp" / "full-local-rc.json"
    electron_report_path = tmp_path / "tmp" / "electron-ui-smoke.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            _public_demo_report_with_passed_flows(set(required_flow_ids) - missing_from_demo)
        ),
        encoding="utf-8",
    )
    rc_report_path.write_text(
        json.dumps(
            _matrix_report(
                "source_real_desktop_app_open",
                "source_real_desktop_ui_inspection",
                "source_real_desktop_interaction",
            )
        ),
        encoding="utf-8",
    )
    electron_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "script_count": 3,
                "scripts": [
                    {
                        "script": "./scripts/smoke_agent_run_detail_ui.mjs",
                        "exit_code": 0,
                    },
                    {
                        "script": "scripts/smoke_workflow_save_run_ui.mjs",
                        "exit_code": 0,
                    },
                    {
                        "script": "scripts/smoke_chat_cancel_ui.mjs",
                        "exit_code": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke(
        [public_demo_path, rc_report_path, electron_report_path]
    )

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "passed"
    details = public_demo["related_evidence"]["public_demo_assessment"][-1]
    assert details["kind"] == "public_demo_aggregate"
    assert details["missing_required_flow_ids"] == []
    projection = next(
        item
        for item in public_demo["related_evidence"]["public_demo_assessment"]
        if item["kind"] == "electron_ui_public_demo_projection"
    )
    assert projection["script_flow_map"] == {
        "scripts/smoke_agent_run_detail_ui.mjs": "studio_replay_ui",
        "scripts/smoke_workflow_save_run_ui.mjs": "workflow_ui",
    }
    assert all(item["id"] != "public_demo" for item in summary["next_actions"])


def test_release_smoke_summary_projects_provider_workflow_smoke_into_public_demo(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    missing_from_demo = {
        "real_desktop_app_open",
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
        "studio_replay_ui",
        "workflow_ui",
    }
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    rc_report_path = tmp_path / "tmp" / "full-local-rc.json"
    electron_report_path = tmp_path / "tmp" / "electron-ui-smoke.json"
    provider_report_path = tmp_path / "tmp" / "provider-smoke.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            _public_demo_report_with_passed_flows(set(required_flow_ids) - missing_from_demo)
        ),
        encoding="utf-8",
    )
    rc_report_path.write_text(
        json.dumps(
            _matrix_report(
                "source_real_desktop_app_open",
                "source_real_desktop_ui_inspection",
                "source_real_desktop_interaction",
            )
        ),
        encoding="utf-8",
    )
    electron_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "script_count": 2,
                "scripts": [
                    {
                        "script": "scripts/smoke_agent_run_detail_ui.mjs",
                        "exit_code": 0,
                    },
                    {
                        "script": "scripts/smoke_workflow_save_run_ui.mjs",
                        "exit_code": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    provider_report_path.write_text(
        json.dumps(
            {
                "provider_smoke": {
                    "status": "passed",
                    "checks": [
                        {
                            "label": "native_workflow_full_chain",
                            "exit_code": 0,
                            "summary": {
                                "ok": True,
                                "checks": [
                                    {
                                        "name": "advanced_workflow_orchestration",
                                        "ok": True,
                                    },
                                    {"name": "workflow_budget_boundary", "ok": True},
                                ],
                            },
                        },
                    ],
                    "findings": [],
                    "run_requested": True,
                }
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke(
        [public_demo_path, rc_report_path, electron_report_path, provider_report_path]
    )

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "passed"
    aggregate = public_demo["evidence"]["public_demo_complete"][0]
    assert aggregate["kind"] == "public_demo_aggregate"
    assert aggregate["missing_required_flow_ids"] == []
    projection = next(
        item
        for item in public_demo["related_evidence"]["public_demo_assessment"]
        if item["kind"] == "provider_workflow_public_demo_projection"
    )
    assert {
        "release_evidence_kind": "",
        "public_demo_flow_id": "",
    } | projection["provider_workflow_evidence"] == {
        "source_kind": "provider_smoke",
        "check_label": "native_workflow_full_chain",
        "exit_code": 0,
        "summary_ok": True,
        "release_evidence_kind": "provider_workflow_full_chain",
        "public_demo_flow_id": "workflow_provider",
    }
    assert "workflow_provider" not in projection["passed_required_flow_ids"]
    assert all(item["id"] != "public_demo" for item in summary["next_actions"])


def test_release_smoke_summary_uses_provider_workflow_as_workflow_release_evidence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    source_report_path = tmp_path / "tmp" / "source-capabilities.json"
    provider_report_path = tmp_path / "tmp" / "workflow-provider.json"
    source_report_path.parent.mkdir(parents=True, exist_ok=True)
    source_report_path.write_text(
        json.dumps(_matrix_report("source_agent_entrypoint_data_analysis")),
        encoding="utf-8",
    )
    provider_report_path.write_text(
        json.dumps(_provider_workflow_full_chain_report()),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke(
        [source_report_path, provider_report_path]
    )

    workflow = next(item for item in summary["items"] if item["id"] == "workflow")
    assert workflow["status"] == "passed"
    assert workflow["present_evidence_ids"] == [
        "source_agent_entrypoint_data_analysis",
        "advanced_workflow_orchestration",
    ]
    assert workflow["evidence"]["advanced_workflow_orchestration"][0]["kind"] == (
        "provider_workflow_full_chain"
    )
    assert "workflow" not in summary["missing_item_ids"]
    assert all(item["id"] != "workflow" for item in summary["next_actions"])


def test_release_smoke_summary_uses_native_provider_contract_as_workflow_release_evidence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    source_report_path = tmp_path / "tmp" / "source-capabilities.json"
    contract_report_path = tmp_path / "tmp" / "native-provider-contract.json"
    source_report_path.parent.mkdir(parents=True, exist_ok=True)
    source_report_path.write_text(
        json.dumps(_matrix_report("source_agent_entrypoint_data_analysis")),
        encoding="utf-8",
    )
    contract_report_path.write_text(
        json.dumps(_native_provider_contract_report()),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke(
        [source_report_path, contract_report_path]
    )

    workflow = next(item for item in summary["items"] if item["id"] == "workflow")
    assert workflow["status"] == "passed"
    assert workflow["evidence"]["advanced_workflow_orchestration"][0]["kind"] == (
        "provider_contract_full_chain"
    )
    provider_evidence = workflow["evidence"]["advanced_workflow_orchestration"][0][
        "provider_workflow_evidence"
    ]
    assert provider_evidence["source_kind"] == "native_provider_contract_smoke"
    assert provider_evidence["public_demo_flow_id"] == "native_provider_contract"
    assert "workflow" not in summary["missing_item_ids"]
    assert all(item["id"] != "workflow" for item in summary["next_actions"])


def test_release_smoke_summary_uses_native_provider_contract_section_from_rc_report(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "rc-source-only.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                **_matrix_report("source_agent_entrypoint_data_analysis"),
                "native_provider_contract_smoke": {
                    "status": "passed",
                    "evidence": _native_provider_contract_report(),
                    "findings": [],
                },
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    workflow = next(item for item in summary["items"] if item["id"] == "workflow")
    assert workflow["status"] == "passed"
    assert workflow["evidence"]["advanced_workflow_orchestration"][0]["kind"] == (
        "provider_contract_full_chain"
    )


def test_release_smoke_summary_does_not_project_provider_workflow_from_capability_matrix(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    rc_report_path = tmp_path / "tmp" / "capability-matrix.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            _public_demo_report_with_passed_flows(
                set(required_flow_ids) - {"studio_replay_ui"}
            )
        ),
        encoding="utf-8",
    )
    rc_report_path.write_text(
        json.dumps(
            _matrix_report(
                "source_agent_entrypoint_data_analysis",
                "advanced_workflow_orchestration",
            )
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([public_demo_path, rc_report_path])

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "missing"
    assert "provider_workflow_public_demo_projection" not in {
        item["kind"]
        for item in public_demo["related_evidence"]["public_demo_assessment"]
    }
    action = next(item for item in summary["next_actions"] if item["id"] == "public_demo")
    assert action["missing_required_flow_ids"] == ["studio_replay_ui"]
    assert "--include-ui" in action["command"]
    workflow = next(item for item in summary["items"] if item["id"] == "workflow")
    assert workflow["status"] == "missing"
    assert workflow["present_evidence_ids"] == ["source_agent_entrypoint_data_analysis"]
    assert workflow["missing_evidence_ids"] == ["advanced_workflow_orchestration"]
    assert workflow["required_evidence_kinds"] == {
        "advanced_workflow_orchestration": [
            "provider_workflow_full_chain",
            "provider_contract_full_chain",
        ]
    }
    assert workflow["rejected_evidence"]["advanced_workflow_orchestration"][0]["kind"] == (
        "capability"
    )


def test_release_smoke_summary_rejects_inconsistent_public_demo_level(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "passed",
                "release_level": "partial_demo_ready",
                "complete": True,
                "selected_count": 19,
                "passed_count": 19,
                "required_flow_count": 19,
                "passed_required_flow_count": 19,
                "missing_required_flow_ids": [],
                "release_blockers": [],
                "flows": [{"id": "workflow_ui", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([public_demo_path])

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "missing"
    assessment = public_demo["related_evidence"]["public_demo_assessment"][0]
    assert assessment["complete"] is True
    assert assessment["release_level"] == "partial_demo_ready"


def test_release_smoke_summary_accepts_raw_smoke_mode_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "group-run.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"ok": True, "mode": "group_run_timeline_smoke"}),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    group_run = next(item for item in summary["items"] if item["id"] == "group_run")
    assert group_run["status"] == "passed"
    assert group_run["present_evidence_ids"] == ["source_group_run_timeline"]


def test_release_smoke_summary_collects_passed_public_demo_flow_reports(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    group_report_path = tmp_path / "tmp" / "group-run.json"
    skipped_report_path = tmp_path / "tmp" / "skipped-artifact.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    group_report_path.write_text(
        json.dumps({"ok": True, "mode": "group_run_timeline_smoke"}),
        encoding="utf-8",
    )
    skipped_report_path.write_text(
        json.dumps({"ok": True, "mode": "data_analysis_artifact_smoke"}),
        encoding="utf-8",
    )
    public_demo_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "partial",
                "release_level": "partial_demo_ready",
                "complete": False,
                "selected_count": 1,
                "passed_count": 1,
                "required_flow_count": 19,
                "passed_required_flow_count": 1,
                "missing_required_flow_ids": ["workflow_provider"],
                "flows": [
                    {
                        "id": "group_run",
                        "status": "passed",
                        "report_json": "tmp/group-run.json",
                    },
                    {
                        "id": "data_analysis_artifact",
                        "status": "skipped",
                        "report_json": "tmp/skipped-artifact.json",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([public_demo_path])

    group_run = next(item for item in summary["items"] if item["id"] == "group_run")
    artifact = next(item for item in summary["items"] if item["id"] == "artifact_readback")
    assert group_run["status"] == "passed"
    assert group_run["evidence"]["source_group_run_timeline"][0]["source"] == "tmp/group-run.json"
    assert artifact["status"] == "missing"


def test_release_smoke_summary_aggregates_partial_public_demo_reports(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    first_batch = set(required_flow_ids[::2])
    second_batch = set(required_flow_ids[1::2])
    first_path = tmp_path / "tmp" / "public-demo-first.json"
    second_path = tmp_path / "tmp" / "public-demo-second.json"
    first_path.parent.mkdir(parents=True, exist_ok=True)
    first_path.write_text(
        json.dumps(_public_demo_report_with_passed_flows(first_batch)),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(_public_demo_report_with_passed_flows(second_batch)),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([first_path, second_path])

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    assert public_demo["status"] == "passed"
    aggregate = public_demo["evidence"]["public_demo_complete"][0]
    assert aggregate["kind"] == "public_demo_aggregate"
    assert aggregate["release_level"] == "full_public_demo_ready"
    assert aggregate["missing_required_flow_ids"] == []
    details = public_demo["related_evidence"]["public_demo_assessment"][-1]
    assert details["kind"] == "public_demo_aggregate"


def test_release_smoke_summary_keeps_more_informative_public_demo_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    required_flow_ids = release_smoke._canonical_public_demo_flow_ids()
    passed_flow_ids = set(required_flow_ids) - {"studio_replay_ui"}
    generic_path = tmp_path / "tmp" / "public-demo-generic.json"
    detailed_path = tmp_path / "tmp" / "public-demo-detailed.json"
    generic = _public_demo_report_with_passed_flows(passed_flow_ids)
    generic["release_blockers"] = [
            {
                "id": "studio_replay_ui",
                "status": "skipped",
                "reason": "ui_smoke_not_collected",
            }
    ]
    detailed = _public_demo_report_with_passed_flows(passed_flow_ids)
    detailed["release_blockers"] = [
            {
                "id": "studio_replay_ui",
                "status": "skipped",
                "reason": "electron_ui_smoke_failed",
                "evidence_summary": {
                    "blocking_condition": "electron_ui_smoke_failed",
                },
            }
    ]
    generic_path.parent.mkdir(parents=True, exist_ok=True)
    generic_path.write_text(json.dumps(generic), encoding="utf-8")
    detailed_path.write_text(json.dumps(detailed), encoding="utf-8")

    summary = release_smoke.summarize_release_smoke([generic_path, detailed_path])

    public_demo = next(item for item in summary["items"] if item["id"] == "public_demo")
    details = public_demo["related_evidence"]["public_demo_assessment"][-1]
    blocker = next(
        item for item in details["release_blockers"] if item["id"] == "studio_replay_ui"
    )
    assert blocker["reason"] == "electron_ui_smoke_failed"


def test_release_smoke_cli_writes_json_and_markdown(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "partial.json"
    output_json = tmp_path / "tmp" / "summary.json"
    output_markdown = tmp_path / "tmp" / "summary.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(_matrix_report("source_data_analysis_artifact")),
        encoding="utf-8",
    )

    exit_code = release_smoke.main(
        [
            str(report_path),
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )

    assert exit_code == 1
    assert capsys.readouterr().out == ""
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "# Oha-Yachiyo Release Smoke Summary" in markdown
    assert "`diagnostics_export`" in markdown


def test_release_smoke_markdown_shows_public_demo_blockers(tmp_path, monkeypatch):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    public_demo_path = tmp_path / "tmp" / "public-demo.json"
    public_demo_path.parent.mkdir(parents=True, exist_ok=True)
    public_demo_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "partial",
                "release_level": "partial_demo_ready",
                "complete": False,
                "selected_count": 14,
                "passed_count": 14,
                "required_flow_count": 16,
                "passed_required_flow_count": 14,
                "missing_required_flow_ids": ["studio_replay_ui", "workflow_ui"],
                "release_blockers": [
                    {"id": "studio_replay_ui", "status": "skipped"},
                    {"id": "workflow_ui", "status": "skipped"},
                ],
                "flows": [{"id": "workflow_run", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([public_demo_path])
    markdown = release_smoke.render_markdown(summary)

    assert "Public demo: 14/16 required flows (`partial_demo_ready`)" in markdown
    assert "Public demo level: `partial_demo_ready`" in markdown
    assert "Missing demo flows: `studio_replay_ui`, `workflow_ui`" in markdown
