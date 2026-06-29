from apps.shell.agent.runtime.followup_content_snapshot import (
    browser_extract_text_content_snapshot,
    clipboard_read_content_snapshot,
    desktop_ui_elements_content_snapshot,
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
