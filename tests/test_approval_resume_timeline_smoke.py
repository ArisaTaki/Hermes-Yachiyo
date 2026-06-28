from __future__ import annotations

import json

from scripts import smoke_approval_resume_timeline as smoke


def test_approval_resume_timeline_smoke_covers_chat_public_snapshots():
    evidence = smoke.run_smoke()
    chat = evidence["chat"]

    assert evidence["ok"] is True
    assert chat["ok"] is True
    assert chat["started"]["status"] == "waiting_approval"
    assert chat["started"]["needs_user_action"] is True
    assert chat["started"]["pending_approvals"][0]["approval_id"] == smoke.APPROVAL_ID
    assert chat["before_timeline"]["pending_approval"]["status"] == "pending"
    assert chat["after_timeline"]["pending_approval"] is None
    assert chat["after_timeline"]["approvals"][0]["status"] == "approved"
    assert chat["after_timeline"]["tool_calls"][0]["status"] == "completed"
    assert chat["after_event_page"]["event_types"] == [
        "agent.tool.approval_approved",
        "agent.tool.completed",
        "agent.completed",
    ]


def test_approval_resume_timeline_smoke_covers_studio_public_snapshots():
    evidence = smoke.run_smoke()
    studio = evidence["studio"]

    assert evidence["ok"] is True
    assert studio["ok"] is True
    assert studio["before_timeline"]["status"] == "approval_required"
    assert studio["before_timeline"]["pending_approval"]["approval_id"] == smoke.APPROVAL_ID
    assert studio["approved_timeline"]["status"] == "completed"
    assert studio["approved_timeline"]["pending_approval"] is None
    assert studio["approved_timeline"]["approvals"][0]["status"] == "approved"
    assert studio["approved_timeline"]["tool_calls"][0]["approval_id"] == smoke.APPROVAL_ID
    assert studio["approved_timeline"]["tool_calls"][0]["output_preview"]["ok"] is True
    assert studio["after_event_page"]["event_types"] == [
        "agent.tool.approval_approved",
        "agent.tool.completed",
        "agent.completed",
    ]


def test_approval_resume_timeline_smoke_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "approval_resume_timeline_smoke"
    assert output["chat"]["checks"]["approval_payload_preserved"] is True
    assert output["studio"]["checks"]["approval_payload_preserved"] is True
