"""Shared discovered-app follow-up execution guard tests."""

from __future__ import annotations

from apps.shell.yachiyo_agent.discovered_app_followups import (
    discovered_app_followup_target_can_direct_execute,
    planner_discovered_app_followup_can_direct_execute,
)


def _target(**overrides):
    return {
        "kind": "desktop_discovered_app_action",
        "app_query": "pdf",
        "app_name_source": "desktop.list_apps",
        "target_action": "open_app",
        **overrides,
    }


def test_discovered_app_followup_allows_open_or_focus_actions() -> None:
    assert discovered_app_followup_target_can_direct_execute(
        _target(target_action="open_app"),
        ["app.open"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        _target(target_action="focus_app"),
        ["app.focus"],
    )


def test_discovered_app_followup_open_path_requires_explicit_opt_in() -> None:
    target = _target(
        target_action="open_path_with_selected_app",
        target_path="/tmp/report.pdf",
    )

    assert not discovered_app_followup_target_can_direct_execute(
        target,
        ["desktop.open_path_with_app"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        target,
        ["desktop.open_path_with_app"],
        allow_open_path=True,
    )


def test_discovered_app_followup_allows_safe_shortcut_with_preparation_tool() -> None:
    assert discovered_app_followup_target_can_direct_execute(
        _target(target_action="safe_shortcut", safe_shortcut_action="new_document"),
        ["app.open", "desktop.safe_shortcut"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(target_action="safe_shortcut"),
        ["app.open", "desktop.safe_shortcut"],
    )


def test_discovered_app_followup_allows_explicit_app_search() -> None:
    target = _target(
        target_action="app_search",
        safe_shortcut_action="find",
        app_search={"query": "logo 模板", "submit": True},
    )

    assert discovered_app_followup_target_can_direct_execute(
        target,
        [
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        target,
        ["app.open", "desktop.safe_shortcut", "desktop.safe_type_text"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(
            target_action="app_search",
            safe_shortcut_action="find",
            app_search={"query": "logo 模板"},
        ),
        ["app.open", "desktop.safe_shortcut"],
    )


def test_discovered_app_followup_rejects_model_required_or_risky_targets() -> None:
    assert not discovered_app_followup_target_can_direct_execute(
        _target(creative_canvas={"kind": "image_edit"}),
        ["app.open"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(communication_compose={"recipient": "Alice", "body": "hi"}),
        ["app.open", "desktop.safe_type_text"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(compose_text="hello"),
        ["app.open"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        _target(compose_text="hello"),
        ["app.open", "desktop.safe_type_text"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(body_source="model_generated_content"),
        ["app.open", "desktop.safe_type_text"],
    )


def test_planner_discovered_app_followup_requires_list_apps_continuation() -> None:
    selection_payload = {"followup_target": _target(target_action="open_app")}

    assert planner_discovered_app_followup_can_direct_execute(
        selection_payload,
        [
            {
                "tool": "desktop.list_apps",
                "continue_to_model": True,
            }
        ],
        ["app.open"],
    )
    assert not planner_discovered_app_followup_can_direct_execute(
        selection_payload,
        [{"tool": "desktop.list_apps"}],
        ["app.open"],
    )
    assert not planner_discovered_app_followup_can_direct_execute(
        selection_payload,
        [{"tool": "workspace.read", "continue_to_model": True}],
        ["app.open"],
    )
