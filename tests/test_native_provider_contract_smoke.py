from __future__ import annotations

import json

from scripts import smoke_native_provider_contract as smoke


def test_native_provider_contract_smoke_exercises_full_chain_without_secret_leak():
    report = smoke.run_contract_smoke()

    assert report["ok"] is True
    assert report["mode"] == "native_provider_contract_smoke"
    by_label = {check["label"]: check for check in report["checks"]}
    assert by_label["native_agent_full_chain_contract"]["ok"] is True
    assert by_label["native_workflow_full_chain_contract"]["ok"] is True

    agent_checks = {
        check["name"]: check
        for check in by_label["native_agent_full_chain_contract"]["summary"]["checks"]
    }
    assert agent_checks["model_profile_readiness"]["ok"] is True
    assert agent_checks["agent_workspace_read"]["ok"] is True
    assert agent_checks["agent_artifact_write"]["ok"] is True
    assert agent_checks["agent_multi_tool_pipeline"]["tool_call_count"] >= 2
    assert agent_checks["workflow_child_agent_artifact"]["ok"] is True
    assert agent_checks["terminal_approval_resume"]["pending_tool"] == "terminal.run"
    assert agent_checks["main_chat_model_loop"]["result_preview"] == "MAIN_CHAT_OK"

    workflow_checks = {
        check["name"]: check
        for check in by_label["native_workflow_full_chain_contract"]["summary"]["checks"]
    }
    assert workflow_checks["advanced_workflow_orchestration"]["ok"] is True
    assert workflow_checks["workflow_budget_boundary"]["ok"] is True

    assert smoke._FAKE_API_KEY not in json.dumps(report, ensure_ascii=False)


def test_native_provider_contract_smoke_cli_writes_report(tmp_path, capsys):
    report_path = tmp_path / "provider-contract.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["provider"] == "local_fake_openai_compatible_sse"
    assert smoke._FAKE_API_KEY not in capsys.readouterr().out
