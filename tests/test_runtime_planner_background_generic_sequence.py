from __future__ import annotations

from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


def test_background_preference_launches_before_readonly_composite_preflight() -> None:
    """Background desktop work must establish its owned target before observing it."""
    app_name = "AtlasLab"
    decision = RuntimePlanner().decision(
        f"在后台打开 {app_name}，在 Search 文本框输入 7070802",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.inspect_app",
            "desktop.ui_elements",
            "desktop.type_into_ui_element",
            "desktop.verify",
            # Keep the receipt-producing app-scoped composite after the
            # explicit launch and read-only target observation.
            "app.open_and_type_into_ui_element",
        ],
        metadata={"prefer_background_desktop": True},
    )

    steps = decision.plan.tool_plan.steps
    assert [step.tool_name for step in steps] == [
        "desktop.list_apps",
        "app.open",
        "desktop.inspect_app",
        "app.open_and_type_into_ui_element",
        "desktop.verify",
    ]
    assert [step.depends_on for step in steps] == [
        [],
        ["discover-desktop-state"],
        ["open-or-focus-app"],
        ["inspect-app"],
        ["operate-foreground-ui"],
    ]

    assert steps[0].input_preview == {"query": app_name, "limit": 20}
    assert steps[1].input_preview == {"app_name": app_name}
    assert steps[2].input_preview == {
        "app_name": app_name,
        "open_if_needed": False,
        "focus": False,
        "role_filter": "text",
        "limit": 80,
    }
    assert steps[3].input_preview == {
        "app_name": app_name,
        "target": "Search",
        "text": "7070802",
        "role_filter": "text",
        "limit": 80,
    }
    assert steps[4].input_preview == {"app_name": app_name}
