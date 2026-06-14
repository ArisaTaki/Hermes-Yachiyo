from __future__ import annotations

import json

from scripts import summarize_agent_market_parity as market


def test_market_parity_summary_reports_passed_partial_and_missing(tmp_path, monkeypatch):
    source = tmp_path / "runtime.py"
    source.write_text(
        "\n".join(
            [
                "class ToolBroker:",
                "    pass",
                "def _load_agent_skills():",
                "    return skill_markdown",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        market,
        "MARKET_REQUIREMENTS",
        (
            {
                "id": "tool_loop",
                "label": "Tool loop",
                "market_pattern": "Controlled tools.",
                "priority": "P0",
                "passed": [{"path": "runtime.py", "fragments": ["class ToolBroker"]}],
            },
            {
                "id": "skill_progressive",
                "label": "Skill progressive disclosure",
                "market_pattern": "Load skill details only when matched.",
                "priority": "P0",
                "passed": [{"path": "runtime.py", "fragments": ["load_full_skill_on_match"]}],
                "partial": [{"path": "runtime.py", "fragments": ["_load_agent_skills", "skill_markdown"]}],
                "next_action": "Add progressive disclosure.",
            },
            {
                "id": "future_task",
                "label": "Future task",
                "market_pattern": "Scheduled self wakeups.",
                "priority": "P1",
                "passed": [{"path": "runtime.py", "fragments": ["FutureTask"]}],
            },
        ),
    )

    result = market.summarize_market_parity(tmp_path)

    assert result["ok"] is False
    assert result["status"] == "incomplete"
    assert result["status_counts"] == {"passed": 1, "partial": 1, "missing": 1}
    assert result["incomplete_capability_ids"] == ["skill_progressive", "future_task"]
    by_id = {item["id"]: item for item in result["capabilities"]}
    assert by_id["tool_loop"]["status"] == "passed"
    assert by_id["skill_progressive"]["status"] == "partial"
    assert by_id["skill_progressive"]["next_action"] == "Add progressive disclosure."
    assert by_id["future_task"]["status"] == "missing"


def test_market_parity_summary_cli_writes_json(tmp_path, monkeypatch):
    (tmp_path / "runtime.py").write_text("partial only", encoding="utf-8")
    output = tmp_path / "market.json"
    monkeypatch.setattr(market, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        market,
        "MARKET_REQUIREMENTS",
        (
            {
                "id": "demo",
                "label": "Demo",
                "market_pattern": "Demo pattern.",
                "priority": "P0",
                "passed": [{"path": "runtime.py", "fragments": ["complete"]}],
                "partial": [{"path": "runtime.py", "fragments": ["partial"]}],
            },
        ),
    )

    assert market.main(["--output-json", str(output)]) == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    assert payload["status_counts"] == {"passed": 0, "partial": 1, "missing": 0}
