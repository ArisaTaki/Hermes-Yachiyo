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
                    {"event_type": "agent.tool.call"},
                    {"event_type": "agent.tool.call"},
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
    assert result["artifact_paths"] == ["pipeline-report.md"]
    tool_policy = service.agent_payload["tool_policy"]
    assert tool_policy == {"allowed_tools": ["workspace.read", "artifact.write"]}
    instructions = str(service.agent_payload["instructions"])
    assert "First call workspace_read" in instructions
    assert "After you receive the tool result, call artifact_write" in instructions
