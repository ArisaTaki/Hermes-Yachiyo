from __future__ import annotations

import json
from pathlib import Path

from scripts import smoke_native_agent_full_chain as smoke


def test_full_chain_smoke_reports_missing_environment(monkeypatch, capsys):
    monkeypatch.delenv(smoke.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(smoke.MODEL_ENV, raising=False)
    monkeypatch.delenv(smoke.API_KEY_ENV, raising=False)

    assert smoke.main([]) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert smoke.BASE_URL_ENV in output["error"]
    assert smoke.MODEL_ENV in output["error"]
    assert smoke.API_KEY_ENV in output["error"]


def test_full_chain_smoke_missing_environment_writes_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "native-agent-full-chain.json"
    monkeypatch.delenv(smoke.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(smoke.MODEL_ENV, raising=False)
    monkeypatch.delenv(smoke.API_KEY_ENV, raising=False)

    assert smoke.main(["--report-json", str(report_path)]) == 1

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is False
    assert smoke.API_KEY_ENV in report["error"]
    assert "native agent full-chain smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_full_chain_smoke_cli_writes_report_json(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "native-agent-full-chain.json"
    monkeypatch.setenv(smoke.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(smoke.MODEL_ENV, "demo-model")
    monkeypatch.setenv(smoke.API_KEY_ENV, "sk-test-native-full-chain")
    monkeypatch.setattr(
        smoke,
        "run_full_chain_smoke",
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
    assert "native agent full-chain smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_full_chain_smoke_cli_never_prints_sensitive_summary(monkeypatch, capsys):
    secret = "sk-test-native-full-chain-secret"
    monkeypatch.setenv(smoke.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(smoke.MODEL_ENV, "demo-model")
    monkeypatch.setenv(smoke.API_KEY_ENV, secret)
    monkeypatch.setattr(
        smoke,
        "run_full_chain_smoke",
        lambda **_kwargs: {"ok": True, "api_key": secret},
    )

    assert smoke.main([]) == 1

    raw_output = capsys.readouterr().out
    assert secret not in raw_output
    output = json.loads(raw_output)
    assert output == {"ok": False, "error": "smoke output still contains sensitive text"}


def test_full_chain_smoke_sensitive_summary_writes_safe_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    secret = "sk-test-native-full-chain-secret"
    report_path = tmp_path / "native-agent-full-chain.json"
    monkeypatch.setenv(smoke.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(smoke.MODEL_ENV, "demo-model")
    monkeypatch.setenv(smoke.API_KEY_ENV, secret)
    monkeypatch.setattr(
        smoke,
        "run_full_chain_smoke",
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
    assert "native agent full-chain smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_full_chain_smoke_check_redacts_sensitive_details():
    secret = "sk-test-native-full-chain-secret"

    payload = smoke._check("redaction", True, nested={"api_key": secret})

    assert payload["nested"]["api_key"] == "[redacted]"
    assert secret not in json.dumps(payload)


def test_multi_tool_pipeline_check_requires_read_then_artifact(tmp_path):
    class FakeService:
        agent_payload: dict[str, object] = {}

        def create_agent(self, payload):
            self.agent_payload = payload
            return {"agent_id": "agent-pipeline"}

        def create_agent_run(self, payload):
            assert payload["agent_id"] == "agent-pipeline"
            return {
                "run_id": "run-pipeline",
                "status": "completed",
                "result": "PIPELINE_DONE MIYABI-742",
                "artifacts": [{"path": "pipeline-report.md"}],
            }

        def list_run_events(self, run_id):
            assert run_id == "run-pipeline"
            return {
                "events": [
                    {
                        "event_type": "agent.desktop.intent_planned",
                        "payload": {"tool": "workspace.read"},
                    },
                    {
                        "event_type": "agent.desktop.intent_planned",
                        "payload": {"tool": "artifact.write"},
                    },
                    {"event_type": "agent.completed"},
                ]
            }

    service = FakeService()
    result = smoke._run_multi_tool_pipeline(
        service,
        Path(tmp_path),
        {"provider": "openai_compatible", "model": "demo"},
    )

    assert result["name"] == "agent_multi_tool_pipeline"
    assert result["ok"] is True
    assert result["tool_call_count"] == 2
    assert result["executed_tools"] == ["workspace.read", "artifact.write"]
    assert result["tool_evidence_source"] == "public_plan_and_outcome"
    assert result["artifact_paths"] == ["pipeline-report.md"]
    tool_policy = service.agent_payload["tool_policy"]
    assert tool_policy == {"allowed_tools": ["workspace.read", "artifact.write"]}
    instructions = str(service.agent_payload["instructions"])
    assert "First call workspace_read" in instructions
    assert "After you receive the tool result, call artifact_write" in instructions


def test_workspace_read_check_requires_runtime_execution_evidence(tmp_path):
    class FakeService:
        def create_agent(self, _payload):
            return {"agent_id": "agent-reader"}

        def create_agent_run(self, payload):
            assert payload["agent_id"] == "agent-reader"
            return {
                "run_id": "run-reader",
                "status": "completed",
                "result": "MIYABI-742 Oha-Yachiyo",
                "artifacts": [],
            }

        def list_run_events(self, run_id, *, include_internal=False):
            assert run_id == "run-reader"
            assert include_internal is True
            return {
                "events": [
                    {
                        "event_type": "agent.desktop.intent_planned",
                        "payload": {"tool": "workspace.read"},
                    },
                    {"event_type": "agent.completed", "payload": {}},
                ]
            }

    result = smoke._run_workspace_read(
        FakeService(),
        Path(tmp_path),
        {"provider": "openai_compatible", "model": "demo"},
    )

    assert result["name"] == "agent_workspace_read"
    assert result["ok"] is False
    assert result["planned_tools"] == ["workspace.read"]
    assert result["executed_tools"] == []
    assert result["tool_evidence_source"] == (
        "internal_runtime_tool_event_and_result"
    )
