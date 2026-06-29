from __future__ import annotations

import json

from scripts import smoke_yachiyo_route_approval as smoke


def test_yachiyo_route_approval_smoke_covers_chat_route_boundary():
    evidence = smoke.run_smoke()
    chat = evidence["chat"]

    assert evidence["ok"] is True
    assert chat["ok"] is True
    assert chat["approved"]["task_id"] == smoke.CHAT_TASK_ID
    assert chat["approved"]["status"] == "completed"
    assert chat["rejected"]["status"] == "failed"
    assert chat["calls"][0]["decision"]["metadata"]["approval_id"] == (
        smoke.CHAT_APPROVAL_ID
    )
    assert chat["calls"][0]["decision"]["metadata"]["surface"] == "bubble"
    assert chat["calls"][1]["decision"]["approved"] is False
    assert chat["calls"][2]["after_sequence"] == 3
    assert chat["events"]["events"][0]["event_type"] == "agent.tool.approval_approved"


def test_yachiyo_route_approval_smoke_covers_studio_route_boundary():
    evidence = smoke.run_smoke()
    studio = evidence["studio"]

    assert evidence["ok"] is True
    assert studio["ok"] is True
    assert studio["approved"]["run_id"] == smoke.STUDIO_RUN_ID
    assert studio["approved"]["status"] == "completed"
    assert studio["rejected"]["status"] == "failed"
    assert studio["calls"][0]["decision"]["metadata"]["approval_id"] == (
        smoke.STUDIO_APPROVAL_ID
    )
    assert studio["calls"][0]["decision"]["metadata"]["surface"] == "studio"
    assert studio["calls"][1]["decision"]["approved"] is False
    assert studio["calls"][2]["after_sequence"] == 5
    assert studio["artifact"]["content"] == "# Route artifact"


def test_yachiyo_route_approval_smoke_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "yachiyo_route_approval_smoke"
    assert output["chat"]["checks"]["approve_preserves_route_approval_id"] is True
    assert output["studio"]["checks"]["artifact_route_shape"] is True


def test_yachiyo_route_approval_smoke_cli_writes_report_json(tmp_path, capsys):
    report_path = tmp_path / "yachiyo-route-approval.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "yachiyo_route_approval_smoke"
    assert "Yachiyo route approval smoke report:" in captured.err
    assert str(report_path) in captured.err
