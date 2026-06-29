from __future__ import annotations

import json

from scripts import smoke_native_workflow_full_chain as smoke
from scripts import smoke_native_agent_full_chain as base_smoke


def test_workflow_full_chain_smoke_runs_advanced_workflow_with_stubbed_provider(monkeypatch):
    responses = iter(["decision: ship", "SUBFLOW_READY", "DESIGN_READY", "CODE_READY"])

    def fake_create_profile(profile_service, *, base_url, model, api_key):
        profile = profile_service.create_profile(
            {
                "name": "Stubbed Workflow Smoke",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
            }
        )
        profile_service.set_defaults({"chat": profile["profile_id"]})
        return {"profile": profile, "test": {"ok": True, "profile": {"status": "ready"}}}

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": next(responses)}

    monkeypatch.setattr(smoke, "_create_profile", fake_create_profile)
    monkeypatch.setattr(smoke, "get_native_agent_readiness", lambda: {"ready": True})
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)

    summary = smoke.run_workflow_full_chain_smoke(
        base_url="https://provider.example/v1",
        model="demo-model",
        api_key="sk-test-workflow-smoke",
    )

    assert summary["ok"] is True
    assert [check["name"] for check in summary["checks"]] == [
        "model_profile_readiness",
        "advanced_workflow_orchestration",
        "workflow_budget_boundary",
    ]
    assert "reports/advanced-workflow.md" in summary["checks"][1]["artifact_paths"]
    assert summary["checks"][2]["status"] == "failed"


def test_workflow_full_chain_smoke_reports_missing_environment(monkeypatch, capsys):
    monkeypatch.delenv(base_smoke.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(base_smoke.MODEL_ENV, raising=False)
    monkeypatch.delenv(base_smoke.API_KEY_ENV, raising=False)

    assert smoke.main([]) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert base_smoke.BASE_URL_ENV in output["error"]
    assert base_smoke.MODEL_ENV in output["error"]
    assert base_smoke.API_KEY_ENV in output["error"]


def test_workflow_full_chain_smoke_missing_environment_writes_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "native-workflow-full-chain.json"
    monkeypatch.delenv(base_smoke.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(base_smoke.MODEL_ENV, raising=False)
    monkeypatch.delenv(base_smoke.API_KEY_ENV, raising=False)

    assert smoke.main(["--report-json", str(report_path)]) == 1

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is False
    assert base_smoke.API_KEY_ENV in report["error"]
    assert "native workflow full-chain smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_workflow_full_chain_smoke_cli_writes_report_json(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "native-workflow-full-chain.json"
    monkeypatch.setenv(base_smoke.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(base_smoke.MODEL_ENV, "demo-model")
    monkeypatch.setenv(base_smoke.API_KEY_ENV, "sk-test-workflow-smoke")
    monkeypatch.setattr(
        smoke,
        "run_workflow_full_chain_smoke",
        lambda **_kwargs: {
            "ok": True,
            "model": "demo-model",
            "check_count": 1,
            "checks": [{"name": "stubbed", "ok": True}],
        },
    )

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["model"] == "demo-model"
    assert "native workflow full-chain smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_workflow_full_chain_smoke_cli_never_prints_sensitive_summary(monkeypatch, capsys):
    secret = "sk-test-native-workflow-full-chain-secret"
    monkeypatch.setenv(base_smoke.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(base_smoke.MODEL_ENV, "demo-model")
    monkeypatch.setenv(base_smoke.API_KEY_ENV, secret)
    monkeypatch.setattr(
        smoke,
        "run_workflow_full_chain_smoke",
        lambda **_kwargs: {"ok": True, "api_key": secret},
    )

    assert smoke.main([]) == 1

    raw_output = capsys.readouterr().out
    assert secret not in raw_output
    output = json.loads(raw_output)
    assert output == {"ok": False, "error": "smoke output still contains sensitive text"}


def test_workflow_full_chain_smoke_sensitive_summary_writes_safe_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    secret = "sk-test-native-workflow-full-chain-secret"
    report_path = tmp_path / "native-workflow-full-chain.json"
    monkeypatch.setenv(base_smoke.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(base_smoke.MODEL_ENV, "demo-model")
    monkeypatch.setenv(base_smoke.API_KEY_ENV, secret)
    monkeypatch.setattr(
        smoke,
        "run_workflow_full_chain_smoke",
        lambda **_kwargs: {"ok": True, "api_key": secret},
    )

    assert smoke.main(["--report-json", str(report_path)]) == 1

    captured = capsys.readouterr()
    report_text = report_path.read_text(encoding="utf-8")
    assert secret not in captured.out
    assert secret not in report_text
    output = json.loads(captured.out)
    report = json.loads(report_text)
    assert output == report
    assert report == {"ok": False, "error": "smoke output still contains sensitive text"}
    assert "native workflow full-chain smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_workflow_full_chain_smoke_check_redacts_sensitive_details():
    secret = "sk-test-native-workflow-full-chain-secret"

    payload = smoke._check("redaction", True, nested={"api_key": secret})

    assert payload["nested"]["api_key"] == "[redacted]"
    assert secret not in json.dumps(payload)
