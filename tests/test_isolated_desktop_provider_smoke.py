from __future__ import annotations

from scripts import smoke_isolated_desktop_provider as smoke


def test_isolated_desktop_provider_smoke_covers_operate_verify_sequence() -> None:
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["desktop_session_kind"] == "isolated_desktop"
    assert evidence["desktop_session_isolated"] is True
    assert evidence["foreground_takeover_required"] is False
    assert evidence["checks"]["all_tools_routed"] is True
    assert evidence["checks"]["tool_sequence_completed"] is True
    assert evidence["checks"]["read_ui_returned_elements"] is True
    assert evidence["checks"]["verify_expected_text"] is True
    assert evidence["covered_tools"] == list(smoke.SMOKE_TOOLS)
    assert [item["action"] for item in evidence["tool_results"]] == list(
        smoke.SMOKE_TOOLS
    )
