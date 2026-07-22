"""Shared discovered-app follow-up execution guard tests."""

from __future__ import annotations

from apps.shell.yachiyo_agent.discovered_app_followups import (
    discovered_app_click_followup_target_from_planned_requests,
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
        _target(target_action="open_app"),
        ["desktop.open_app"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        _target(target_action="focus_app"),
        ["app.focus"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        _target(target_action="focus_app"),
        ["desktop.focus_app"],
    )


def test_discovered_app_followup_allows_grounded_click_with_app_scope_or_preparation() -> None:
    target = _target(target_action="click", target="登录")

    assert not discovered_app_followup_target_can_direct_execute(
        target,
        ["app.focus_and_click_ui_element"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        target,
        ["app.open_and_click_ui_element"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        target,
        ["app.focus", "desktop.click_ui_element"],
    )
    assert discovered_app_followup_target_can_direct_execute(
        target,
        ["desktop.open_app", "desktop.click_ui_element"],
    )


def test_discovered_app_followup_click_fails_closed_without_target_or_complete_capability() -> None:
    assert not discovered_app_followup_target_can_direct_execute(
        _target(target_action="click"),
        ["app.focus_and_click_ui_element"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(target_action="click", target="   "),
        ["app.open_and_click_ui_element"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(target_action="click", target="登录"),
        ["desktop.click_ui_element"],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        _target(target_action="click", target="登录"),
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
    assert discovered_app_followup_target_can_direct_execute(
        _target(target_action="safe_shortcut", safe_shortcut_action="new_document"),
        ["desktop.open_app", "desktop.safe_shortcut"],
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
    click_target = _target(
        target_action="app_search",
        app_search={
            "query": "logo 模板",
            "submit": True,
            "focus": {
                "tool": "desktop.click_ui_element",
                "input": {"target": "搜索", "role_filter": "text"},
            },
        },
    )
    assert discovered_app_followup_target_can_direct_execute(
        click_target,
        [
            "desktop.open_app",
            "desktop.click_ui_element",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        click_target,
        ["desktop.click_ui_element", "desktop.safe_type_text", "desktop.search_submit"],
    )
    result_click_target = _target(
        target_action="app_search",
        safe_shortcut_action="find",
        app_search={
            "query": "logo 模板",
            "submit": True,
            "result_selection": {
                "action": "click",
                "tool": "desktop.click_ui_element",
                "input": {"target": "第一个结果", "click_count": 1},
            },
        },
    )
    assert discovered_app_followup_target_can_direct_execute(
        result_click_target,
        [
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.click_ui_element",
        ],
    )
    key_confirm_target = _target(
        target_action="app_search",
        safe_shortcut_action="find",
        app_search={
            "query": "logo 模板",
            "submit": True,
            "submit_action": "confirm",
            "result_selection": {
                "action": "key_confirm",
                "key": {"tool": "desktop.safe_key", "input": {"action": "arrow_down"}},
                "confirm": {
                    "tool": "desktop.submit_foreground",
                    "input": {"action": "confirm"},
                },
            },
        },
    )
    assert discovered_app_followup_target_can_direct_execute(
        key_confirm_target,
        [
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
        ],
    )
    assert not discovered_app_followup_target_can_direct_execute(
        key_confirm_target,
        [
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
        ],
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
        ["desktop.open_app"],
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


def test_planner_discovered_app_followup_can_continue_to_grounded_click() -> None:
    request = {"tool": "desktop.list_apps", "continue_to_model": True}

    assert planner_discovered_app_followup_can_direct_execute(
        {"followup_target": _target(target_action="click", target="登录")},
        [request],
        ["app.open_and_click_ui_element"],
    )
    assert not planner_discovered_app_followup_can_direct_execute(
        {"followup_target": _target(target_action="click", target="登录")},
        [request],
        ["app.focus_and_click_ui_element"],
    )
    assert not planner_discovered_app_followup_can_direct_execute(
        {"followup_target": _target(target_action="click")},
        [request],
        ["app.focus_and_click_ui_element"],
    )


def test_discovered_app_click_followup_target_comes_only_from_planned_semantic_tool() -> None:
    target = discovered_app_click_followup_target_from_planned_requests(
        "Chrome",
        [
            {
                "tool_name": "app.focus_and_click_ui_element",
                "input": {
                    "app_name": "Chrome",
                    "target": "登录",
                    "role_filter": "button",
                    "limit": 40,
                    "click_count": 1,
                    "x": 120,
                    "y": 240,
                },
            }
        ],
    )

    assert target == {
        "kind": "desktop_discovered_app_action",
        "app_query": "Chrome",
        "app_name_source": "desktop.list_apps",
        "target_action": "click",
        "target": "登录",
        "role_filter": "button",
        "limit": 40,
        "click_count": 1,
    }
    assert "x" not in target
    assert "y" not in target
    assert discovered_app_click_followup_target_from_planned_requests(
        "Chrome",
        [{"tool_name": "desktop.click", "input": {"x": 120, "y": 240}}],
    ) == {}
    assert discovered_app_click_followup_target_from_planned_requests(
        "Chrome",
        [
            {
                "tool_name": "app.focus_and_click_ui_element",
                "input": {"target": "登录"},
            },
            {
                "tool_name": "app.open_and_click_ui_element",
                "input": {"target": "注册"},
            },
        ],
    ) == {}
