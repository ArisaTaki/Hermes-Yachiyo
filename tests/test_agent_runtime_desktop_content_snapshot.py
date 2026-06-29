from apps.shell.agent.runtime.desktop_content_snapshot import (
    desktop_ui_elements_content_snapshot,
    latest_desktop_content_snapshot,
    screen_capture_content_snapshot,
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


def test_latest_desktop_content_snapshot_uses_requested_observation_tool() -> None:
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

    snapshot = latest_desktop_content_snapshot(timeline, ["screen.capture"])

    assert snapshot == {
        "source_tool": "screen.capture",
        "ok": True,
        "path": "/tmp/yachiyo-screen.png",
        "reason": "verify visible state",
        "summary": "Screen image captured at /tmp/yachiyo-screen.png; no OCR text was extracted.",
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
