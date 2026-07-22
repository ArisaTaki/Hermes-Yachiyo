from __future__ import annotations

from apps.shell.agent.runtime.tool_candidate_selection import (
    ToolReadinessFacts,
    select_tool_candidate,
    tool_candidate_selection_context,
)
from apps.shell.agent.runtime.tool_capabilities import (
    register_tool_capability_binding,
    unregister_tool_capability_binding,
)
from apps.shell.agent.tools.policy import TOOL_DESCRIPTORS, ToolDescriptor
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY


def test_structured_background_tool_beats_foreground_fallback() -> None:
    selection = select_tool_candidate(
        ("app.focus_and_safe_type_text", "artifact.write"),
        {"app.focus_and_safe_type_text", "artifact.write"},
        required_capability="communication.compose",
        required_action="draft_message",
        readiness_by_tool={
            "app.focus_and_safe_type_text": {
                "status": "ready",
                "structured": False,
                "tool_native": False,
                "background_safe": False,
                "foreground_takeover_required": True,
            },
            "artifact.write": {
                "status": "ready",
                "structured": True,
                "tool_native": True,
                "background_safe": True,
                "foreground_takeover_required": False,
            },
        },
        prefer_background=True,
    )

    assert selection.selected_tool == "artifact.write"
    assert selection.alternatives == ("app.focus_and_safe_type_text",)
    assert selection.ranked_candidates[0].background_safe is True
    assert "background_safe" in selection.ranked_candidates[0].reason_codes


def test_known_ready_tool_beats_explicitly_blocked_tool() -> None:
    selection = select_tool_candidate(
        ("browser.search", "browser.open_url_and_extract_text"),
        {"browser.search", "browser.open_url_and_extract_text"},
        required_capability="browser.research",
        readiness_by_tool={
            "browser.search": {"status": "provider_capability_mismatch"},
            "browser.open_url_and_extract_text": {"status": "ready"},
        },
    )

    assert selection.selected_tool == "browser.open_url_and_extract_text"
    assert selection.blocked_tools == ("browser.search",)
    assert selection.ranked_candidates[0].readiness_class == "ready"


def test_exact_action_affinity_beats_a_read_only_tool_in_same_capability() -> None:
    selection = select_tool_candidate(
        ("browser.search", "browser.click"),
        {"browser.search", "browser.click"},
        required_capability="browser.research",
        required_action="click",
        readiness_by_tool={
            "browser.search": {"status": "ready"},
            "browser.click": {"status": "ready"},
        },
    )

    assert selection.selected_tool == "browser.click"
    assert "exact_action_match" in selection.ranked_candidates[0].reason_codes


def test_lower_approval_and_risk_win_after_equivalent_route_facts() -> None:
    equivalent_route = {
        "status": "ready",
        "structured": True,
        "tool_native": True,
        "read_only": False,
        "background_safe": True,
        "foreground_takeover_required": False,
    }
    selection = select_tool_candidate(
        ("browser.click", "browser.search"),
        {"browser.click", "browser.search"},
        required_capability="browser.research",
        readiness_by_tool={
            "browser.click": equivalent_route,
            "browser.search": equivalent_route,
        },
    )

    assert selection.selected_tool == "browser.search"
    assert selection.ranked_candidates[0].approval_required is False
    assert selection.ranked_candidates[0].risk_level == "low"


def test_unknown_readiness_remains_eligible_and_beats_blocked() -> None:
    selection = select_tool_candidate(
        ("browser.search", "browser.open_url_and_extract_text"),
        {"browser.search", "browser.open_url_and_extract_text"},
        required_capability="browser.research",
        readiness_by_tool={
            "browser.search": {"status": "unavailable"},
            "browser.open_url_and_extract_text": {"status": "not_checked"},
        },
    )

    assert selection.selected_tool == "browser.open_url_and_extract_text"
    assert selection.ranked_candidates[0].readiness_class == "unknown"
    assert "readiness_unknown" in selection.ranked_candidates[0].reason_codes


def test_all_blocked_candidates_still_select_deterministically() -> None:
    selection = select_tool_candidate(
        ("browser.search", "browser.open_url_and_extract_text"),
        {"browser.search", "browser.open_url_and_extract_text"},
        required_capability="browser.research",
        readiness_by_tool={
            "browser.search": {"status": "blocked"},
            "browser.open_url_and_extract_text": {"status": "blocked"},
        },
    )

    assert selection.selected_tool == "browser.search"
    assert selection.blocked_tools == (
        "browser.search",
        "browser.open_url_and_extract_text",
    )
    assert "all_eligible_tools_blocked" in selection.reason_codes
    assert "selected_tool_blocked" in selection.reason_codes


def test_allowlist_is_a_hard_eligibility_boundary() -> None:
    selection = select_tool_candidate(
        ("browser.search", "browser.open_url_and_extract_text"),
        {"browser.open_url_and_extract_text"},
        required_capability="browser.research",
    )

    assert selection.selected_tool == "browser.open_url_and_extract_text"
    assert tuple(item.tool_name for item in selection.ranked_candidates) == (
        "browser.open_url_and_extract_text",
    )
    assert "candidate_not_allowed" in selection.reason_codes


def test_descriptor_and_dispatch_registries_are_hard_boundaries(monkeypatch) -> None:
    monkeypatch.delitem(TOOL_DESCRIPTORS, "browser.search")
    monkeypatch.delitem(TOOL_DISPATCH_REGISTRY, "browser.open_url_and_extract_text")

    selection = select_tool_candidate(
        ("browser.search", "browser.open_url_and_extract_text"),
        {"browser.search", "browser.open_url_and_extract_text"},
        required_capability="browser.research",
    )

    assert selection.selected_tool is None
    assert "candidate_missing_descriptor" in selection.reason_codes
    assert "candidate_missing_dispatch" in selection.reason_codes


def test_dynamic_prefix_or_partial_registration_cannot_claim_capability(monkeypatch) -> None:
    dynamic_tool = "browser.dynamic_plugin_search"
    first = select_tool_candidate(
        (dynamic_tool,),
        {dynamic_tool},
        required_capability="browser.research",
    )
    assert first.selected_tool is None

    monkeypatch.setitem(TOOL_DESCRIPTORS, dynamic_tool, object())
    monkeypatch.setitem(TOOL_DISPATCH_REGISTRY, dynamic_tool, lambda *_args, **_kwargs: {})
    second = select_tool_candidate(
        (dynamic_tool,),
        {dynamic_tool},
        required_capability="browser.research",
    )

    assert second.selected_tool is None
    assert "candidate_missing_required_capability" in second.reason_codes


def test_schema_and_dispatch_without_capability_authority_are_never_selectable(
    monkeypatch,
) -> None:
    dynamic_tool = "plugin.unbound.echo"
    monkeypatch.setitem(
        TOOL_DESCRIPTORS,
        dynamic_tool,
        ToolDescriptor(
            name=dynamic_tool,
            description="Unbound test adapter.",
            properties={},
        ),
    )
    monkeypatch.setitem(
        TOOL_DISPATCH_REGISTRY,
        dynamic_tool,
        lambda _broker, _payload, _approved: {"ok": True},
    )

    selection = select_tool_candidate(
        (dynamic_tool,),
        {dynamic_tool},
    )

    assert selection.selected_tool is None
    assert "candidate_missing_capability_authority" in selection.reason_codes


def test_required_action_fails_closed_when_capability_does_not_declare_it() -> None:
    selection = select_tool_candidate(
        ("browser.search",),
        {"browser.search"},
        required_capability="browser.research",
        required_action="play",
    )

    assert selection.selected_tool is None
    assert "candidate_missing_required_action" in selection.reason_codes


def test_dynamic_tool_requires_exact_explicit_action_binding(monkeypatch) -> None:
    without_action = "plugin.notes.capability_only"
    exact_action = "plugin.notes.create_note"
    for tool_name in (without_action, exact_action):
        monkeypatch.setitem(
            TOOL_DESCRIPTORS,
            tool_name,
            ToolDescriptor(
                name=tool_name,
                description="Test-only note adapter.",
                properties={},
            ),
        )
        monkeypatch.setitem(
            TOOL_DISPATCH_REGISTRY,
            tool_name,
            lambda _broker, _payload, _approved: {"ok": True},
        )

    register_tool_capability_binding(
        without_action,
        capability_ids=("information.capture",),
    )
    register_tool_capability_binding(
        exact_action,
        capability_ids=("information.capture",),
        action_ids=("create_note",),
    )
    try:
        selection = select_tool_candidate(
            (without_action, exact_action),
            {without_action, exact_action},
            required_capability="information.capture",
            required_action="create_note",
        )
    finally:
        unregister_tool_capability_binding(without_action)
        unregister_tool_capability_binding(exact_action)

    assert selection.selected_tool == exact_action
    assert tuple(item.tool_name for item in selection.ranked_candidates) == (
        exact_action,
    )
    assert "candidate_missing_explicit_action_binding" in selection.reason_codes


def test_explicit_dynamic_action_beats_static_name_affinity(monkeypatch) -> None:
    dynamic_tool = "plugin.desktop.precise_adapter"
    monkeypatch.setitem(
        TOOL_DESCRIPTORS,
        dynamic_tool,
        ToolDescriptor(
            name=dynamic_tool,
            description="Exact app-opening adapter.",
            properties={"app_name": {"type": "string"}},
            required=("app_name",),
        ),
    )
    monkeypatch.setitem(
        TOOL_DISPATCH_REGISTRY,
        dynamic_tool,
        lambda _broker, _payload, _approved: {"ok": True},
    )
    register_tool_capability_binding(
        dynamic_tool,
        capability_ids=("desktop.app_control",),
        action_ids=("open_app",),
    )
    try:
        selection = select_tool_candidate(
            ("app.open", dynamic_tool),
            {"app.open", dynamic_tool},
            required_capability="desktop.app_control",
            required_action="open_app",
        )
    finally:
        unregister_tool_capability_binding(dynamic_tool)

    assert selection.selected_tool == dynamic_tool
    assert selection.ranked_candidates[0].reason_codes[-1] == "exact_action_match"


def test_original_candidate_order_is_the_final_stable_tie_break() -> None:
    selection = select_tool_candidate(
        ("browser.open_url_and_extract_text", "browser.search"),
        {"browser.search", "browser.open_url_and_extract_text"},
        required_capability="browser.research",
        readiness_by_tool={
            "browser.open_url_and_extract_text": ToolReadinessFacts(status="not_checked"),
            "browser.search": ToolReadinessFacts(status="not_checked"),
        },
    )

    assert tuple(item.tool_name for item in selection.ranked_candidates) == (
        "browser.open_url_and_extract_text",
        "browser.search",
    )


def test_context_defaults_are_nested_and_do_not_leak() -> None:
    candidates = ("browser.search", "browser.open_url_and_extract_text")
    allowed = set(candidates)

    baseline = select_tool_candidate(candidates, allowed, required_capability="browser.research")
    assert baseline.selected_tool == "browser.search"

    with tool_candidate_selection_context(
        readiness_by_tool={
            "browser.search": {"status": "blocked"},
            "browser.open_url_and_extract_text": {"status": "ready"},
        },
        prefer_background=True,
    ):
        outer = select_tool_candidate(candidates, allowed, required_capability="browser.research")
        assert outer.selected_tool == "browser.open_url_and_extract_text"

        with tool_candidate_selection_context(
            readiness_by_tool={
                "browser.search": {"status": "ready"},
                "browser.open_url_and_extract_text": {"status": "blocked"},
            }
        ):
            inner = select_tool_candidate(
                candidates,
                allowed,
                required_capability="browser.research",
            )
            assert inner.selected_tool == "browser.search"

        restored_outer = select_tool_candidate(
            candidates,
            allowed,
            required_capability="browser.research",
        )
        assert restored_outer.selected_tool == "browser.open_url_and_extract_text"

    restored_baseline = select_tool_candidate(
        candidates,
        allowed,
        required_capability="browser.research",
    )
    assert restored_baseline.selected_tool == "browser.search"
