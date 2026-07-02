from apps.shell.agent.runtime.followup_content_snapshot import (
    browser_extract_text_content_snapshot,
    clipboard_read_content_snapshot,
    data_analyze_content_snapshot,
    desktop_inspect_app_content_snapshot,
    desktop_ui_elements_content_snapshot,
    followup_content_snapshots,
    latest_followup_content_snapshot,
    screen_capture_content_snapshot,
    workspace_read_content_snapshot,
)


def test_desktop_ui_elements_content_snapshot_keeps_useful_unique_text() -> None:
    snapshot = desktop_ui_elements_content_snapshot(
        {
            "ok": True,
            "data": {
                "app_name": "Obsidian",
                "title": "Search: yachiyo runtime",
                "count": 5,
                "elements": [
                    {"name": "Search result"},
                    {"value": "Search result"},
                    {"name": "button"},
                    {"description": "Runtime snapshots reduce raw UI tree noise."},
                    {"value": "x"},
                ],
            },
        },
        {},
    )

    assert snapshot == {
        "source_tool": "desktop.ui_elements",
        "ok": True,
        "app_name": "Obsidian",
        "title": "Search: yachiyo runtime",
        "element_count": 5,
        "text_item_count": 2,
        "truncated": False,
        "text": "Search result\nRuntime snapshots reduce raw UI tree noise.",
    }


def test_desktop_inspect_app_content_snapshot_summarizes_readiness_and_ui_text() -> None:
    snapshot = desktop_inspect_app_content_snapshot(
        {
            "ok": True,
            "summary": "Inspected Figma: focused with accessible controls",
            "data": {
                "app_name": "Figma",
                "requested_app_name": "design",
                "discovered_app_name": "Figma",
                "running": True,
                "focus_verified": True,
                "ready_for_foreground_action": True,
                "inspection_level": "control",
                "visibility_limited": False,
                "window_count": 1,
                "ui_element_count": 3,
                "control_like_count": 2,
                "recommended_tools": ["app.focus_and_click_ui_element", "desktop.ui_elements"],
                "recovery_actions": [
                    {
                        "label": "Focus Figma",
                        "tool": "app.focus",
                        "input": {"app_name": "Figma"},
                        "risk_level": "low",
                    }
                ],
                "active_window": {
                    "ok": True,
                    "data": {"app_name": "Figma", "title": "Logo templates"},
                },
                "ui_elements": {
                    "ok": True,
                    "data": {
                        "elements": [
                            {"name": "Logo templates"},
                            {"description": "Create from template"},
                        ],
                        "truncated": False,
                    },
                },
            },
        },
        {"app_name": "design"},
    )

    assert snapshot == {
        "source_tool": "desktop.inspect_app",
        "ok": True,
        "app_name": "Figma",
        "requested_app_name": "design",
        "discovered_app_name": "Figma",
        "running": True,
        "focus_verified": True,
        "ready_for_foreground_action": True,
        "inspection_level": "control",
        "visibility_limited": False,
        "window_count": 1,
        "ui_element_count": 3,
        "control_like_count": 2,
        "recommended_tools": ["app.focus_and_click_ui_element", "desktop.ui_elements"],
        "recovery_actions": [
            {
                "label": "Focus Figma",
                "tool": "app.focus",
                "input": {"app_name": "Figma"},
                "risk_level": "low",
            }
        ],
        "truncated": False,
        "text": (
            "Inspected Figma: focused with accessible controls\n"
            "Active window: Figma - Logo templates\n"
            "Visible UI text:\n"
            "Logo templates\n"
            "Create from template"
        ),
    }


def test_latest_followup_content_snapshot_uses_requested_observation_tool() -> None:
    timeline = [
        {
            "event": "agent.tool.call",
            "detail": "screen.capture",
            "input_preview": {"reason": "verify visible state"},
            "result": {"ok": True, "data": {"path": "/tmp/yachiyo-screen.png"}},
        },
        {
            "event": "agent.tool.call",
            "detail": "desktop.ui_elements",
            "input_preview": {"app_name": "Notes"},
            "result": {
                "ok": True,
                "data": {
                    "count": 1,
                    "elements": [{"name": "Quarterly revenue notes"}],
                },
            },
        },
    ]

    snapshot = latest_followup_content_snapshot(timeline, ["screen.capture"])

    assert snapshot == {
        "source_tool": "screen.capture",
        "ok": True,
        "path": "/tmp/yachiyo-screen.png",
        "reason": "verify visible state",
        "summary": "Screen image captured at /tmp/yachiyo-screen.png; no OCR text was extracted.",
    }


def test_browser_extract_text_content_snapshot_preserves_text_lines() -> None:
    snapshot = browser_extract_text_content_snapshot(
        {
            "ok": True,
            "data": {
                "selector": "#main",
                "text": "region,revenue\nEast,10\nWest,20",
                "truncated": False,
            },
        },
        {},
    )

    assert snapshot == {
        "source_tool": "browser.extract_text",
        "ok": True,
        "selector": "#main",
        "text_length": 30,
        "truncated": False,
        "text": "region,revenue\nEast,10\nWest,20",
    }


def test_browser_extract_text_content_snapshot_marks_preview_truncation() -> None:
    raw_text = "x" * 4001

    snapshot = browser_extract_text_content_snapshot(
        {"ok": True, "data": {"text": raw_text, "truncated": False}},
        {},
    )

    assert snapshot["text_length"] == 4001
    assert snapshot["truncated"] is True
    assert snapshot["text"] == f"{'x' * 4000}..."


def test_latest_followup_content_snapshot_reads_browser_open_extract_text() -> None:
    snapshot = latest_followup_content_snapshot(
        [
            {
                "event": "agent.tool.call",
                "detail": "browser.open_url_and_extract_text",
                "input_preview": {"url": "https://example.com"},
                "result": {
                    "ok": True,
                    "data": {
                        "url": "https://example.com",
                        "text": "Example Domain\nThis domain is for examples.",
                    },
                },
            }
        ],
        ["browser.open_url_and_extract_text"],
    )

    assert snapshot == {
        "source_tool": "browser.open_url_and_extract_text",
        "ok": True,
        "url": "https://example.com",
        "text_length": 43,
        "truncated": False,
        "text": "Example Domain\nThis domain is for examples.",
    }


def test_clipboard_read_content_snapshot_preserves_bounded_preview() -> None:
    snapshot = clipboard_read_content_snapshot(
        {
            "ok": True,
            "data": {
                "text": "alpha\t beta\n gamma",
                "text_length": 18,
                "truncated": True,
                "max_chars": 18,
            },
        },
        {},
    )

    assert snapshot == {
        "source_tool": "clipboard.read",
        "ok": True,
        "text_length": 18,
        "truncated": True,
        "max_chars": 18,
        "text": "alpha beta\ngamma",
    }


def test_workspace_read_content_snapshot_records_path_and_content() -> None:
    snapshot = workspace_read_content_snapshot(
        {
            "ok": True,
            "path": "data/sales.csv",
            "content": "region,revenue\nEast,10\nWest,20",
        },
        {},
    )

    assert snapshot == {
        "source_tool": "workspace.read",
        "ok": True,
        "path": "data/sales.csv",
        "text_length": 30,
        "truncated": False,
        "text": "region,revenue\nEast,10\nWest,20",
    }


def test_data_analyze_content_snapshot_records_artifact_context() -> None:
    snapshot = data_analyze_content_snapshot(
        {
            "ok": True,
            "path": "data/sales.csv",
            "source_kind": "csv",
            "rows": 3,
            "analyzed_rows": 3,
            "columns": ["region", "revenue", "units"],
            "artifact_paths": [
                "reports/sales.md",
                "reports/sales-summary.csv",
                "reports/sales-chart.png",
            ],
            "artifact_manifest": [
                {"path": "reports/sales.md", "kind": "markdown"},
                {"path": "reports/sales-summary.csv", "kind": "csv"},
                {"path": "reports/sales-chart.png", "kind": "chart"},
            ],
            "summary": "Analyzed data/sales.csv: 3 rows, 3 columns. Report: reports/sales.md.",
        },
        {},
    )

    assert snapshot == {
        "source_tool": "data.analyze",
        "ok": True,
        "path": "data/sales.csv",
        "source_kind": "csv",
        "rows": 3,
        "analyzed_rows": 3,
        "columns": ["region", "revenue", "units"],
        "artifact_paths": [
            "reports/sales.md",
            "reports/sales-summary.csv",
            "reports/sales-chart.png",
        ],
        "artifact_manifest": [
            {"path": "reports/sales.md", "kind": "markdown"},
            {"path": "reports/sales-summary.csv", "kind": "csv"},
            {"path": "reports/sales-chart.png", "kind": "chart"},
        ],
        "artifact_count": 3,
        "text": (
            "Data analysis result for data/sales.csv (csv).\n"
            "3 rows\n"
            "Columns: region, revenue, units\n"
            "Artifacts: reports/sales.md (markdown), "
            "reports/sales-summary.csv (csv), reports/sales-chart.png (chart)\n"
            "Analyzed data/sales.csv: 3 rows, 3 columns. Report: reports/sales.md."
        ),
    }


def test_latest_followup_content_snapshot_reads_data_analysis_result() -> None:
    snapshot = latest_followup_content_snapshot(
        [
            {
                "event": "agent.tool.call",
                "detail": "data.analyze",
                "input_preview": {"path": "data/sales.csv", "source_kind": "csv"},
                "result": {
                    "ok": True,
                    "path": "data/sales.csv",
                    "source_kind": "csv",
                    "rows": 2,
                    "columns": ["region", "revenue"],
                    "artifacts": [
                        {"path": "analysis-report.md", "kind": "markdown"},
                    ],
                },
            }
        ],
        ["data.analyze"],
    )

    assert snapshot["source_tool"] == "data.analyze"
    assert snapshot["path"] == "data/sales.csv"
    assert snapshot["rows"] == 2
    assert snapshot["columns"] == ["region", "revenue"]
    assert snapshot["artifact_paths"] == ["analysis-report.md"]
    assert "Data analysis result for data/sales.csv (csv)." in snapshot["text"]


def test_followup_content_snapshots_preserve_multiple_observation_sources() -> None:
    timeline = [
        {
            "event": "agent.tool.call",
            "detail": "workspace.read",
            "input_preview": {"path": "data/sales.csv"},
            "result": {
                "ok": True,
                "path": "data/sales.csv",
                "content": "region,revenue\nEast,10\nWest,20",
            },
        },
        {
            "event": "agent.tool.call",
            "detail": "desktop.active_window",
            "result": {"ok": True, "title": "ignored"},
        },
        {
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "input_preview": {"path": "data/sales.csv", "source_kind": "csv"},
            "result": {
                "ok": True,
                "path": "data/sales.csv",
                "source_kind": "csv",
                "rows": 2,
                "columns": ["region", "revenue"],
                "artifact_paths": ["analysis-report.md"],
            },
        },
    ]

    snapshots = followup_content_snapshots(
        timeline,
        ["workspace.read", "desktop.active_window", "data.analyze"],
    )

    assert [snapshot["source_tool"] for snapshot in snapshots] == [
        "workspace.read",
        "data.analyze",
    ]
    assert snapshots[0]["text"] == "region,revenue\nEast,10\nWest,20"
    assert snapshots[1]["artifact_paths"] == ["analysis-report.md"]
    assert latest_followup_content_snapshot(timeline, ["workspace.read", "data.analyze"]) == snapshots[1]


def test_followup_content_snapshots_keep_latest_per_tool() -> None:
    snapshots = followup_content_snapshots(
        [
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "old.csv"},
                "result": {"ok": True, "path": "old.csv", "content": "old"},
            },
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "latest.csv"},
                "result": {"ok": True, "path": "latest.csv", "content": "latest"},
            },
        ],
        ["workspace.read"],
    )

    assert snapshots == [
        {
            "source_tool": "workspace.read",
            "ok": True,
            "path": "latest.csv",
            "text_length": 6,
            "truncated": False,
            "text": "latest",
        }
    ]


def test_screen_capture_content_snapshot_preserves_recovery_details() -> None:
    snapshot = screen_capture_content_snapshot(
        {
            "ok": False,
            "summary": "Screen recording permission is missing.",
            "permission_targets": ["Screen Recording"],
            "recovery_hints": ["Open System Settings"],
        },
        {"reason": "inspect current app"},
    )

    assert snapshot == {
        "source_tool": "screen.capture",
        "ok": False,
        "reason": "inspect current app",
        "summary": "Screen recording permission is missing.",
        "permission_targets": ["Screen Recording"],
        "recovery_hints": ["Open System Settings"],
    }
