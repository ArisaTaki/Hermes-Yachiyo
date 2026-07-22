from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from apps.shell.agent.runtime import model_intent_planning as model_intent_module
from apps.shell.agent.runtime.abstract_capability_planning import (
    AbstractCapabilityInputSlotProposal,
    AbstractCapabilitySubgoalProposal,
)
from apps.shell.agent.runtime.goal_runtime import _explicit_pure_conversation_goal
from apps.shell.agent.runtime.model_intent_planning import (
    MODEL_INTENT_PLANNING_TOOL_NAME,
    ModelIntentClarificationResolution,
    ModelIntentPlanningError,
    ModelIntentProposal,
    direct_tool_selection_from_model_intent_proposal,
    goal_contract_payload_from_model_selection,
    model_intent_planning_tool_schema,
    model_intent_proposal_from_tool_requests,
    model_intent_resolution_from_proposal,
    planner_selection_needs_model_assistance,
)
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    DirectToolSelection,
    planner_first_direct_tool_selection,
)
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


_GENERIC_ALLOWED_TOOLS = [
    "artifact.write",
    "browser.search",
    "desktop.active_window",
    "desktop.click_ui_element",
    "desktop.list_apps",
    "desktop.open_app",
    "desktop.ui_elements",
    "file.list",
    "terminal.run",
]


def _selection_for(prompt: str) -> DirectToolSelection:
    decision = RuntimePlanner().decision(prompt, allowed_tools=_GENERIC_ALLOWED_TOOLS)
    return DirectToolSelection(
        decision=decision,
        requests=[],
        event_payload={},
        selected_source="runtime_planner",
    )


def _proposal_tool_call(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": "provider-call-id-is-not-authority",
        "type": "function",
        "function": {
            "name": MODEL_INTENT_PLANNING_TOOL_NAME,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def test_model_intent_schema_exposes_only_semantic_proposal_fields() -> None:
    schema = model_intent_planning_tool_schema()

    assert schema["function"]["name"] == MODEL_INTENT_PLANNING_TOOL_NAME
    parameters = schema["function"]["parameters"]
    assert parameters["additionalProperties"] is False
    assert set(parameters["properties"]) == {
        "intent_kind",
        "planning_goal",
        "action_evidence",
        "subgoals",
        "clarification_question",
        "rationale",
    }
    assert "general" not in parameters["properties"]["intent_kind"]["enum"]
    subgoal = parameters["properties"]["subgoals"]["items"]
    assert subgoal["additionalProperties"] is False
    assert set(subgoal["properties"]) == {
        "capability_id",
        "action_id",
        "planning_goal",
        "action_evidence",
        "input_slots",
    }
    input_slot = subgoal["properties"]["input_slots"]["items"]
    assert input_slot["additionalProperties"] is False
    assert set(input_slot["properties"]) == {"slot", "value", "evidence_quote"}


def test_competing_nonempty_intents_need_model_assistance() -> None:
    selection = _selection_for("搜索网页查找 Python 代码示例")
    candidates = selection.decision.candidate_intents

    assert [candidate.kind for candidate in candidates[:2]] == [
        "web_research",
        "code_task",
    ]
    assert planner_selection_needs_model_assistance(
        selection,
        "搜索网页查找 Python 代码示例",
    )


@pytest.mark.parametrize("prompt", ["打开 Safari", "点击“继续”按钮"])
def test_clear_deterministic_desktop_action_keeps_fast_path(prompt: str) -> None:
    selection = _selection_for(prompt)

    assert selection.decision.selected_intent.kind == "desktop_operation"
    assert not planner_selection_needs_model_assistance(selection, prompt)


def test_atomic_open_hotkey_and_copy_sequence_keeps_fast_path() -> None:
    prompt = "打开 Notes，然后按 Command+L，再复制"
    allowed_tools = [
        "desktop.list_apps",
        "app.open_and_hotkey",
        "desktop.ui_elements",
        "desktop.safe_shortcut",
    ]
    selection = planner_first_direct_tool_selection(prompt, allowed_tools)
    steps = selection.decision.plan.tool_plan.steps

    assert any(step.tool_name == "app.open_and_hotkey" for step in steps)
    assert any(step.tool_name == "desktop.safe_shortcut" for step in steps)
    assert any(
        "open" in model_intent_module._planned_step_action_families(step)
        for step in steps
    )
    assert any(
        "copy" in model_intent_module._planned_step_action_families(step)
        for step in steps
    )
    assert not planner_selection_needs_model_assistance(selection, prompt)


def test_clear_deterministic_terminal_command_keeps_fast_path() -> None:
    selection = planner_first_direct_tool_selection("运行 pwd", _GENERIC_ALLOWED_TOOLS)

    assert selection.decision is not None
    assert selection.decision.selected_intent.kind == "code_task"
    assert not planner_selection_needs_model_assistance(selection, "运行 pwd")
    assert [request["tool"] for request in selection.requests] == ["terminal.run"]
    assert selection.requests[0]["input"] == {"command": "pwd"}


def test_target_bound_discovery_then_action_keeps_the_deterministic_fast_path() -> None:
    prompt = "Find Safari and open it"
    allowed_tools = [
        "desktop.active_window",
        "desktop.list_apps",
        "desktop.open_app",
    ]
    selection = planner_first_direct_tool_selection(prompt, allowed_tools)

    expected_tools = [
        "desktop.list_apps",
        "desktop.open_app",
        "desktop.active_window",
    ]
    assert [request["tool"] for request in selection.requests] == expected_tools
    assert not planner_selection_needs_model_assistance(selection, prompt)

    model_selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="desktop_operation",
            planning_goal=prompt,
            action_evidence="Find",
        ),
        prompt,
        allowed_tools,
    )
    assert [request["tool"] for request in model_selection.requests] == expected_tools


@pytest.mark.parametrize(
    "prompt",
    [
        "Read README.md and open Safari",
        "打开 Safari，再读取 README.md",
    ],
)
def test_underplanned_compound_action_clauses_require_model_assistance(
    prompt: str,
) -> None:
    selection = _selection_for(prompt)
    steps = selection.decision.plan.tool_plan.steps

    assert any(
        step.action == "read_file"
        for step in steps
    )
    assert not any(
        "open" in model_intent_module._planned_step_action_families(step)
        for step in steps
    )
    assert planner_selection_needs_model_assistance(selection, prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "Open Safari, read README.md",
        "Open Safari; read README.md",
        "打开 Safari，读取 README.md",
        "打开 Safari；读取 README.md",
        "打开 Safari 后读取 README.md",
        "请打开 Safari，顺便读取 README.md",
    ],
)
def test_underplanned_compound_punctuation_and_natural_connectors_need_model_assistance(
    prompt: str,
) -> None:
    selection = _selection_for(prompt)
    steps = selection.decision.plan.tool_plan.steps

    assert any(
        step.action == "read_file"
        for step in steps
    )
    assert not any(
        "open" in model_intent_module._planned_step_action_families(step)
        for step in steps
    )
    assert planner_selection_needs_model_assistance(selection, prompt)


def test_combined_app_inspection_covers_open_and_read_without_model_assistance() -> None:
    prompt = "打开 PixelForge 并读取界面"
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=["desktop.inspect_app"],
    )
    selection = DirectToolSelection(
        decision=decision,
        requests=[],
        event_payload={},
        selected_source="runtime_planner",
    )

    assert len(decision.plan.tool_plan.steps) == 1
    step = decision.plan.tool_plan.steps[0]
    assert step.tool_name == "desktop.inspect_app"
    assert step.input_preview["open_if_needed"] is True
    assert not planner_selection_needs_model_assistance(selection, prompt)


def test_combined_data_analysis_output_covers_analyze_and_write_without_model_assistance() -> None:
    prompt = "请分析 inputs/sales.csv 并输出报告"
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=["data.analyze"],
    )
    selection = DirectToolSelection(
        decision=decision,
        requests=[],
        event_payload={},
        selected_source="runtime_planner",
    )

    assert len(decision.plan.tool_plan.steps) == 1
    step = decision.plan.tool_plan.steps[0]
    assert step.tool_name == "data.analyze"
    assert step.action == "analyze_data_file"
    assert step.input_preview["artifact_path"] == "analysis-report.md"
    assert step.input_preview["requested_outputs"] == ["report"]
    assert not planner_selection_needs_model_assistance(selection, prompt)


@pytest.mark.parametrize(
    "input_preview",
    [
        {"artifact_path": "analysis-report.md"},
        {"output_path": "analysis-report.md"},
        {"requested_outputs": ["report"]},
    ],
)
def test_declared_analysis_output_fields_each_cover_the_write_clause(
    input_preview: dict[str, object],
) -> None:
    step = SimpleNamespace(
        action="analyze_data_file",
        tool_name="data.analyze",
        input_preview=input_preview,
    )

    assert not model_intent_module._compound_action_clauses_underplanned(
        "请分析 inputs/sales.csv 并输出报告",
        [step],
    )


@pytest.mark.parametrize(
    ("prompt", "step"),
    [
        (
            "打开 PixelForge 并读取界面",
            SimpleNamespace(
                action="inspect_app",
                tool_name="desktop.inspect_app",
                input_preview={"open_if_needed": False},
            ),
        ),
        (
            "请分析 inputs/sales.csv 并输出报告",
            SimpleNamespace(
                action="analyze_data_file",
                tool_name="data.analyze",
                input_preview={"path": "inputs/sales.csv"},
            ),
        ),
    ],
)
def test_combined_step_without_secondary_action_contract_remains_underplanned(
    prompt: str,
    step: SimpleNamespace,
) -> None:
    assert model_intent_module._compound_action_clauses_underplanned(prompt, [step])


def test_atomic_open_path_with_app_covers_both_open_clauses() -> None:
    prompt = "打开一个能编辑 PDF 的应用并打开 Downloads/report.pdf"
    allowed_tools = [
        "desktop.list_apps",
        "desktop.open_path_with_app",
        "desktop.ui_elements",
    ]
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    selection = DirectToolSelection(
        decision=decision,
        requests=[],
        event_payload={},
        selected_source="runtime_planner",
    )

    step = next(
        step
        for step in decision.plan.tool_plan.steps
        if step.tool_name == "desktop.open_path_with_app"
    )
    assert step.input_preview["app_name"]
    assert step.input_preview["target_path"] == "Downloads/report.pdf"
    assert not planner_selection_needs_model_assistance(selection, prompt)


def test_conjunction_inside_one_action_target_keeps_the_fast_path() -> None:
    prompt = "Search cats and dogs"
    selection = _selection_for(prompt)

    assert not planner_selection_needs_model_assistance(selection, prompt)


def test_explicit_pure_conversation_never_becomes_effectful_model_planning() -> None:
    selection = _selection_for("解释一下什么是 Agent runtime")

    assert selection.decision.selected_intent.kind == "general"
    assert not planner_selection_needs_model_assistance(
        selection,
        "解释一下什么是 Agent runtime",
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "Please reply with exactly MAIN_CHAT_OK.",
        "Respond only with READY.",
        'Reply with exactly "I am ready".',
        "Return exactly decision: ship.",
        "Return exactly I am ready.",
        "Output exactly DONE.",
        "请只回复“好的”。",
        "仅输出 READY",
    ],
)
def test_exact_chat_response_never_becomes_effectful_model_planning(
    prompt: str,
) -> None:
    selection = _selection_for(prompt)

    assert _explicit_pure_conversation_goal(prompt)
    assert not planner_selection_needs_model_assistance(selection, prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "Reply to Alice in Slack with exactly OK.",
        "Please reply with exactly OK to Alice in Slack.",
        "Reply with exactly OK in Slack to Alice.",
        "Please answer only with YES to the email from Bob.",
        "只给张三回复“好的”",
        "只在 Slack 回复 READY",
        "只回复 Slack 里的 Alice：好的",
        "只回复“好的”给 Alice",
        "仅回复邮件里的客户：已收到",
    ],
)
def test_targeted_reply_is_not_weakened_to_pure_conversation(prompt: str) -> None:
    assert not _explicit_pure_conversation_goal(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "Return exactly decision: ship in Slack.",
        "Return exactly decision: ship and open Slack.",
        "Return exactly decision: ship and send it to Alice.",
        "Return exactly decision: ship.\nOpen Slack.",
        f"Return exactly {'x' * 101}.",
    ],
)
def test_unquoted_exact_response_with_effectful_tail_fails_closed(
    prompt: str,
) -> None:
    assert not _explicit_pure_conversation_goal(prompt)


def test_missing_or_general_nonconversation_plan_needs_model_assistance() -> None:
    assert planner_selection_needs_model_assistance(
        DirectToolSelection(None, [], {}, "none"),
        "处理一下这个任务",
    )
    assert planner_selection_needs_model_assistance(
        _selection_for("处理一下这个任务"),
        "处理一下这个任务",
    )
    assert planner_selection_needs_model_assistance(
        _selection_for("整理项目文件"),
        "整理项目文件",
    )


def test_nonresponse_goal_without_an_entrypoint_request_needs_assistance() -> None:
    selection = planner_first_direct_tool_selection(
        "帮我打开一个软件",
        ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
    )

    assert selection.requests == []
    assert planner_selection_needs_model_assistance(
        selection,
        "帮我打开一个软件",
    )


def test_model_proposal_parser_accepts_one_provider_call_and_ignores_wrapper_id() -> None:
    proposal = model_intent_proposal_from_tool_requests(
        [
            _proposal_tool_call(
                {
                    "intent_kind": "web_research",
                    "planning_goal": "  搜索网页   查找 Python 新闻  ",
                    "action_evidence": "查找",
                    "rationale": "The request asks for current information.",
                }
            )
        ]
    )

    assert proposal == ModelIntentProposal(
        intent_kind="web_research",
        planning_goal="搜索网页 查找 Python 新闻",
        action_evidence="查找",
        rationale="The request asks for current information.",
    )


def test_model_proposal_parser_accepts_only_semantic_ordered_subgoals() -> None:
    proposal = model_intent_proposal_from_tool_requests(
        [
            _proposal_tool_call(
                {
                    "intent_kind": "web_research",
                    "planning_goal": "Search for Python news, then open Safari",
                    "action_evidence": "Search",
                    "subgoals": [
                        {
                            "capability_id": "browser.research",
                            "action_id": "search",
                            "planning_goal": "Search for Python news",
                            "action_evidence": "Search",
                            "input_slots": [
                                {
                                    "slot": "query",
                                    "value": "Python news",
                                    "evidence_quote": "Python news",
                                }
                            ],
                        },
                        {
                            "capability_id": "desktop.app_control",
                            "action_id": "open_app",
                            "planning_goal": "open Safari",
                            "action_evidence": "open",
                            "input_slots": [
                                {
                                    "slot": "app_name",
                                    "value": "Safari",
                                    "evidence_quote": "Safari",
                                }
                            ],
                        },
                    ],
                }
            )
        ]
    )

    assert proposal is not None
    assert proposal.subgoals == (
        AbstractCapabilitySubgoalProposal(
            capability_id="browser.research",
            action_id="search",
            planning_goal="Search for Python news",
            action_evidence="Search",
            input_slots=(
                AbstractCapabilityInputSlotProposal(
                    slot="query",
                    value="Python news",
                    evidence_quote="Python news",
                ),
            ),
        ),
        AbstractCapabilitySubgoalProposal(
            capability_id="desktop.app_control",
            action_id="open_app",
            planning_goal="open Safari",
            action_evidence="open",
            input_slots=(
                AbstractCapabilityInputSlotProposal(
                    slot="app_name",
                    value="Safari",
                    evidence_quote="Safari",
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    "authority_field",
    [
        "tool_name",
        "step_id",
        "risk_level",
        "approval_required",
        "fallback_tools",
        "target_authority",
        "completion_evidence",
        "verifier",
    ],
)
def test_abstract_subgoal_parser_rejects_nested_authority_fields(
    authority_field: str,
) -> None:
    subgoal = {
        "capability_id": "browser.research",
        "action_id": "search",
        "planning_goal": "Search for Python news",
        "action_evidence": "Search",
        "input_slots": [
            {
                "slot": "query",
                "value": "Python news",
                "evidence_quote": "Python news",
            }
        ],
        authority_field: "model-authored-authority",
    }

    with pytest.raises(
        ModelIntentPlanningError,
        match="abstract_capability_authority_fields_forbidden",
    ):
        model_intent_proposal_from_tool_requests(
            [
                _proposal_tool_call(
                    {
                        "intent_kind": "web_research",
                        "planning_goal": "Search for Python news",
                        "action_evidence": "Search",
                        "subgoals": [subgoal],
                    }
                )
            ]
        )


def test_abstract_input_slot_parser_rejects_nested_authority_fields() -> None:
    with pytest.raises(
        ModelIntentPlanningError,
        match="abstract_capability_authority_fields_forbidden",
    ):
        model_intent_proposal_from_tool_requests(
            [
                _proposal_tool_call(
                    {
                        "intent_kind": "web_research",
                        "planning_goal": "Search for Python news",
                        "action_evidence": "Search",
                        "subgoals": [
                            {
                                "capability_id": "browser.research",
                                "action_id": "search",
                                "planning_goal": "Search for Python news",
                                "action_evidence": "Search",
                                "input_slots": [
                                    {
                                        "slot": "query",
                                        "value": "Python news",
                                        "evidence_quote": "Python news",
                                        "tool": "browser.search",
                                    }
                                ],
                            }
                        ],
                    }
                )
            ]
        )


@pytest.mark.parametrize(
    "requests",
    [
        [
            _proposal_tool_call(
                {
                    "intent_kind": "not_a_real_intent",
                    "planning_goal": "Search the web",
                }
            )
        ],
        [
            {
                "tool": MODEL_INTENT_PLANNING_TOOL_NAME,
                "input": [],
            }
        ],
        [
            {
                "function": {
                    "name": MODEL_INTENT_PLANNING_TOOL_NAME,
                    "arguments": "{not valid json",
                }
            }
        ],
        [
            _proposal_tool_call(
                {
                    "intent_kind": "web_research",
                    "planning_goal": "Search the web",
                }
            ),
            _proposal_tool_call(
                {
                    "intent_kind": "code_task",
                    "planning_goal": "Inspect the code",
                }
            ),
        ],
        [
            _proposal_tool_call(
                {
                    "intent_kind": "web_research",
                    "planning_goal": "Search the web",
                    "tool_name": "browser.search",
                    "approval_required": False,
                    "decision_id": "model-owned-id",
                }
            )
        ],
    ],
)
def test_unknown_malformed_multiple_or_authority_bearing_proposal_is_rejected(
    requests: list[dict[str, object]],
) -> None:
    with pytest.raises(ModelIntentPlanningError):
        model_intent_proposal_from_tool_requests(requests)


def test_unrelated_model_tool_call_is_not_misread_as_intent_proposal() -> None:
    assert (
        model_intent_proposal_from_tool_requests(
            [{"tool": "browser.search", "input": {"query": "Python"}}]
        )
        is None
    )


def test_model_hint_mints_original_goal_bound_decision_contract_and_request() -> None:
    original_goal = "帮我查一下今天的 Python 新闻"
    planning_goal = "搜索网页查找今天的 Python 新闻"
    proposal = ModelIntentProposal(
        intent_kind="web_research",
        planning_goal=planning_goal,
        rationale="Current information requires research.",
    )

    selection = direct_tool_selection_from_model_intent_proposal(
        proposal,
        original_goal,
        ["browser.search"],
    )

    decision = selection.decision
    contract = decision.plan.task_core.goal_contract
    assert decision.source == "runtime_planner"
    assert selection.selected_source == "runtime_planner"
    assert decision.prompt == original_goal
    assert decision.selected_intent.user_goal == original_goal
    assert decision.plan.intent.user_goal == original_goal
    assert contract.original_goal == original_goal
    assert decision.selected_intent.inputs["runtime_model_planning_goal"] == planning_goal
    assert [request["tool"] for request in selection.requests] == ["browser.search"]
    assert selection.requests[0]["capability_id"] == "browser.research"
    assert selection.requests[0]["source"] == "runtime_planner"
    assert selection.event_payload["selection_reason"] == "model_assisted_intent"
    assert goal_contract_payload_from_model_selection(selection, original_goal)[
        "original_goal"
    ] == original_goal


def test_abstract_capability_subgoals_compile_into_one_runtime_owned_selection() -> None:
    original_goal = (
        "Search the web for Python release news, read docs/guide.md, then open Safari"
    )
    proposal = ModelIntentProposal(
        intent_kind="web_research",
        planning_goal=original_goal,
        action_evidence="Search",
        subgoals=(
            AbstractCapabilitySubgoalProposal(
                capability_id="browser.research",
                action_id="search",
                planning_goal="Search the web for Python release news",
                action_evidence="Search",
                input_slots=(
                    AbstractCapabilityInputSlotProposal(
                        slot="query",
                        value="Python release news",
                        evidence_quote="Python release news",
                    ),
                ),
            ),
            AbstractCapabilitySubgoalProposal(
                capability_id="file.workspace_read",
                action_id="read_file",
                planning_goal="read docs/guide.md",
                action_evidence="read",
                input_slots=(
                    AbstractCapabilityInputSlotProposal(
                        slot="path",
                        value="docs/guide.md",
                        evidence_quote="docs/guide.md",
                    ),
                ),
            ),
            AbstractCapabilitySubgoalProposal(
                capability_id="desktop.app_control",
                action_id="open_app",
                planning_goal="open Safari",
                action_evidence="open",
                input_slots=(
                    AbstractCapabilityInputSlotProposal(
                        slot="app_name",
                        value="Safari",
                        evidence_quote="Safari",
                    ),
                ),
            ),
        ),
    )

    selection = direct_tool_selection_from_model_intent_proposal(
        proposal,
        original_goal,
        ["browser.search", "workspace.read", "desktop.open_app", "desktop.verify"],
    )

    decision = selection.decision
    steps = decision.plan.tool_plan.steps
    assert decision.prompt == original_goal
    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["runtime_model_proposed_intent_kind"] == (
        "web_research"
    )
    assert decision.selected_intent.user_goal == original_goal
    assert decision.plan.intent.user_goal == original_goal
    assert decision.plan.task_core.goal_contract.original_goal == original_goal
    assert [step.tool_name for step in steps] == [
        "browser.search",
        "workspace.read",
        "desktop.open_app",
        "desktop.verify",
    ]
    assert steps[1].depends_on == [steps[0].step_id]
    assert steps[2].depends_on == [steps[1].step_id]
    assert [
        criterion.required_capabilities
        for criterion in decision.plan.task_core.goal_contract.criteria
    ] == [
        ["browser.research"],
        ["file.workspace_read"],
        ["desktop.app_control"],
    ]
    assert [request["tool"] for request in selection.requests] == [
        "browser.search",
        "workspace.read",
        "desktop.open_app",
        "desktop.verify",
    ]
    assert selection.event_payload["selection_reason"] == (
        "model_assisted_abstract_capability_plan"
    )
    semantic_audit = selection.event_payload["model_intent_planning"]["subgoals"]
    assert [subgoal["action_id"] for subgoal in semantic_audit] == [
        "search",
        "read_file",
        "open_app",
    ]
    assert "tool_name" not in repr(semantic_audit)
    assert goal_contract_payload_from_model_selection(selection, original_goal)[
        "original_goal"
    ] == original_goal


@pytest.mark.parametrize(
    ("original_goal", "planning_goal", "action_evidence"),
    [
        ("Open Safari, read README.md", "Open Safari", "Open"),
        ("打开 Safari，读取 README.md", "打开 Safari", "打开"),
    ],
)
def test_model_hint_cannot_drop_a_compound_action_clause_without_subgoals(
    original_goal: str,
    planning_goal: str,
    action_evidence: str,
) -> None:
    with pytest.raises(
        ModelIntentPlanningError,
        match="model_intent_abstract_subgoals_required",
    ):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal=planning_goal,
                action_evidence=action_evidence,
            ),
            original_goal,
            [
                "desktop.active_window",
                "desktop.list_apps",
                "desktop.open_app",
                "workspace.read",
            ],
        )


def test_abstract_capability_selection_rejects_one_unsupported_subgoal_atomically() -> None:
    original_goal = "Search for Python news, then delete docs/guide.md"
    proposal = ModelIntentProposal(
        intent_kind="web_research",
        planning_goal=original_goal,
        action_evidence="Search",
        subgoals=(
            AbstractCapabilitySubgoalProposal(
                capability_id="browser.research",
                action_id="search",
                planning_goal="Search for Python news",
                action_evidence="Search",
                input_slots=(
                    AbstractCapabilityInputSlotProposal(
                        slot="query",
                        value="Python news",
                        evidence_quote="Python news",
                    ),
                ),
            ),
            AbstractCapabilitySubgoalProposal(
                capability_id="file.workspace_read",
                action_id="delete",
                planning_goal="delete docs/guide.md",
                action_evidence="delete",
                input_slots=(
                    AbstractCapabilityInputSlotProposal(
                        slot="path",
                        value="docs/guide.md",
                        evidence_quote="docs/guide.md",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            proposal,
            original_goal,
            ["browser.search", "workspace.read"],
        )


def test_model_hint_cannot_invent_an_effectful_intent_absent_from_original_goal() -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Safari",
            ),
            "帮我处理一下",
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
        )


def test_grounded_model_semantics_can_bridge_a_deterministic_router_gap() -> None:
    original_goal = "运行一个命令"
    user_reply = "pwd"
    continued_goal = f"{original_goal}\n{user_reply}"

    selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="code_task",
            planning_goal="运行 pwd",
            action_evidence="运行",
        ),
        continued_goal,
        ["terminal.run"],
        metadata=_clarification_metadata(original_goal, user_reply),
    )

    assert selection.decision.prompt == continued_goal
    assert selection.decision.selected_intent.kind == "code_task"
    assert selection.decision.selected_intent.inputs["terminal_command_hint"] == {
        "command": "pwd"
    }
    assert selection.requests[0]["tool"] == "terminal.run"
    assert selection.requests[0]["input"] == {"command": "pwd"}


def test_model_semantics_without_explicit_action_evidence_remain_rejected() -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="code_task",
                planning_goal="运行 pwd",
            ),
            "运行一个命令\npwd",
            ["terminal.run"],
            metadata=_clarification_metadata("运行一个命令", "pwd"),
        )


def test_weak_action_evidence_cannot_authorize_a_new_effectful_route() -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Safari",
                action_evidence="处理",
            ),
            "Safari 帮我处理一下",
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
        )


def test_action_evidence_cannot_authorize_an_ungrounded_concrete_input() -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="code_task",
                planning_goal="运行 rm -rf ~",
                action_evidence="运行",
            ),
            "运行一个命令",
            ["terminal.run"],
        )


@pytest.mark.parametrize(
    ("original_goal", "planning_goal", "action_evidence"),
    [
        ("不要运行 pwd", "运行 pwd", "运行"),
        ("不要帮我运行 pwd", "运行 pwd", "运行"),
        ("为什么不能运行 pwd？", "运行 pwd", "运行"),
        ("为什么运行 pwd 会失败？", "运行 pwd", "运行"),
        ("如何运行 pwd？", "运行 pwd", "运行"),
        ("你能告诉我怎么运行 pwd 吗？", "运行 pwd", "运行"),
        ("如果需要的话运行 pwd", "运行 pwd", "运行"),
        ('他说"运行 pwd"，这是什么意思？', "运行 pwd", "运行"),
        ("把‘运行 pwd’翻译成英文", "运行 pwd", "运行"),
        ("给 Alice 发消息说运行 pwd", "运行 pwd", "运行"),
        ("发消息给 Alice：运行 pwd", "运行 pwd", "运行"),
        ("我想知道运行 pwd 会发生什么", "运行 pwd", "运行"),
        ("Do not run pwd", "run pwd", "run"),
        ("How do I run pwd?", "run pwd", "run"),
        ("Why can't I run pwd?", "run pwd", "run"),
        ("He said 'run pwd' yesterday", "run pwd", "run"),
        ("Send Alice a message saying run pwd", "run pwd", "run"),
        ("If needed, run pwd", "run pwd", "run"),
        ("If needed, please run pwd", "run pwd", "run"),
        ("如果需要的话请运行 pwd", "运行 pwd", "运行"),
        ("He said please run pwd yesterday", "run pwd", "run"),
        (
            "running diagnostics. do not run pwd. please write a summary",
            "run pwd",
            "run",
        ),
        ("please write a summary; do not run pwd", "run pwd", "run"),
        ("please search cats and if needed run pwd", "run pwd", ""),
        ("please search cats and he said run pwd", "run pwd", ""),
        ("please search cats. do not run pwd", "run pwd", ""),
    ],
)
def test_negated_or_diagnostic_action_evidence_cannot_authorize_execution(
    original_goal: str,
    planning_goal: str,
    action_evidence: str,
) -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="code_task",
                planning_goal=planning_goal,
                action_evidence=action_evidence,
            ),
            original_goal,
            ["terminal.run"],
        )


def test_interrogative_effect_request_can_supply_grounded_action_evidence() -> None:
    selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="code_task",
            planning_goal="运行 pwd",
            action_evidence="运行",
        ),
        "能不能运行 pwd？",
        ["terminal.run"],
    )

    assert selection.requests[0]["tool"] == "terminal.run"
    assert selection.requests[0]["input"] == {"command": "pwd"}


def test_action_evidence_must_describe_the_model_planning_action() -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="code_task",
                planning_goal="运行 rm",
                action_evidence="open",
            ),
            "open rm.txt",
            ["terminal.run"],
        )


def test_diagnostic_desktop_question_never_mints_direct_execution() -> None:
    prompt = "为什么打开 Safari 会报错？"
    selection = planner_first_direct_tool_selection(
        prompt,
        ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
    )

    assert selection.decision.selected_intent.kind == "general"
    assert selection.requests == []
    assert not planner_selection_needs_model_assistance(selection, prompt)
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Safari",
                action_evidence="打开",
            ),
            prompt,
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
        )


def test_model_hint_cannot_fill_a_missing_effectful_target_for_the_user() -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Terminal",
            ),
            "帮我打开一个软件",
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
        )


def _clarification_metadata(original_goal: str, user_reply: str) -> dict[str, object]:
    return {
        "clarification_authority": {
            "version": 1,
            "original_goal": original_goal,
            "user_reply": user_reply,
        }
    }


def test_user_clarification_reply_can_fill_missing_non_action_target() -> None:
    original_goal = "帮我打开一个软件"
    user_reply = "Apple Music"
    continued_goal = f"{original_goal}\n{user_reply}"

    selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="desktop_operation",
            planning_goal="打开 Apple Music",
        ),
        continued_goal,
        ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
        metadata=_clarification_metadata(original_goal, user_reply),
    )

    assert selection.decision.prompt == continued_goal
    assert selection.decision.selected_intent.user_goal == continued_goal
    assert selection.decision.selected_intent.inputs["operation_hint"] == "open"
    assert selection.decision.selected_intent.inputs["app_name_hint"] == "Apple Music"
    assert selection.decision.plan.task_core.goal_contract.original_goal == continued_goal
    assert any(
        request["tool"] == "desktop.open_app"
        and request["input"].get("query") == "Apple Music"
        for request in selection.requests
    )


def test_user_clarification_reply_cannot_authorize_a_different_target() -> None:
    original_goal = "帮我打开一个软件"
    user_reply = "Apple Music"
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Terminal",
            ),
            f"{original_goal}\n{user_reply}",
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
            metadata=_clarification_metadata(original_goal, user_reply),
        )


def test_user_clarification_reply_cannot_change_original_action() -> None:
    original_goal = "帮我打开一个软件"
    user_reply = "Apple Music"
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="在 Apple Music 中输入 Apple Music",
            ),
            f"{original_goal}\n{user_reply}",
            [
                "desktop.active_window",
                "desktop.list_apps",
                "desktop.open_app",
                "desktop.type_text",
            ],
            metadata=_clarification_metadata(original_goal, user_reply),
        )


@pytest.mark.parametrize(
    "authority",
    [
        {"version": 2, "original_goal": "帮我打开一个软件", "user_reply": "Terminal"},
        {"version": 1, "original_goal": "别的目标", "user_reply": "Terminal"},
        {"version": 1, "original_goal": "帮我打开一个软件", "user_reply": "Terminal", "target": "Terminal"},
    ],
)
def test_malformed_or_spoofed_clarification_authority_is_rejected(
    authority: dict[str, object],
) -> None:
    with pytest.raises(ModelIntentPlanningError, match="hint_rejected"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Terminal",
            ),
            "帮我打开一个软件\nTerminal",
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
            metadata={"clarification_authority": authority},
        )


def test_model_disambiguation_keeps_original_target_as_execution_authority() -> None:
    original_goal = "播放超时空辉夜姬的歌"
    selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="media_playback",
            planning_goal="播放 Chou Kaguya-hime 的歌曲",
        ),
        original_goal,
        ["media.apple_music_play"],
    )

    assert selection.decision.selected_intent.inputs["query"] == "超时空辉夜姬的歌"
    assert selection.requests[0]["input"] == {"query": "超时空辉夜姬的歌"}
    assert (
        selection.decision.selected_intent.inputs["runtime_model_planning_goal"]
        == "播放 Chou Kaguya-hime 的歌曲"
    )


def test_requested_intent_must_be_a_real_router_candidate() -> None:
    with pytest.raises(ValueError, match="model_intent_kind_not_routed"):
        RuntimePlanner().decision_from_model_intent_hint(
            "帮我处理一下",
            "搜索网页查找 Python 新闻",
            "schedule",
            ["browser.search"],
        )


def test_runtime_accepts_read_only_and_trusted_deferred_execution_plans() -> None:
    clipboard_selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="clipboard_operation",
            planning_goal="读取剪贴板内容",
        ),
        "读一下剪贴板",
        ["clipboard.read"],
    )
    assert [request["tool"] for request in clipboard_selection.requests] == [
        "clipboard.read"
    ]

    click_selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="desktop_operation",
            planning_goal="点击当前应用的继续按钮",
        ),
        "请点一下继续",
        ["desktop.active_window", "desktop.click_ui_element", "desktop.ui_elements"],
    )
    assert [request["tool"] for request in click_selection.requests] == [
        "desktop.ui_elements"
    ]
    assert click_selection.requests[0]["deferred_tool"] == "desktop.click_ui_element"


def test_unavailable_or_out_of_allowlist_effect_plan_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal = ModelIntentProposal(
        intent_kind="web_research",
        planning_goal="搜索网页查找 Python 新闻",
    )
    with pytest.raises(ModelIntentPlanningError, match="allowed_tools_empty"):
        direct_tool_selection_from_model_intent_proposal(
            proposal,
            "帮我查资料",
            [],
        )
    with pytest.raises(ModelIntentPlanningError, match="unavailable"):
        direct_tool_selection_from_model_intent_proposal(
            proposal,
            "帮我查资料",
            ["desktop.open_app"],
        )

    monkeypatch.setattr(
        model_intent_module,
        "planner_tool_requests_for_decision",
        lambda *_args, **_kwargs: [
            {
                "tool": "browser.extract_text",
                "input": {},
                "step_id": "open-web-search",
                "capability_id": "browser.research",
            }
        ],
    )
    with pytest.raises(ModelIntentPlanningError, match="outside_allowlist"):
        direct_tool_selection_from_model_intent_proposal(
            proposal,
            "帮我查资料",
            ["browser.search"],
        )


def test_runtime_rejects_tool_capability_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_intent_module,
        "planner_tool_requests_for_decision",
        lambda *_args, **_kwargs: [
            {
                "tool": "browser.search",
                "input": {"query": "Python"},
                "step_id": "open-web-search",
                "capability_id": "file.workspace_write",
            }
        ],
    )

    with pytest.raises(ModelIntentPlanningError, match="capability_mismatch"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="web_research",
                planning_goal="搜索网页查找 Python 新闻",
            ),
            "帮我查资料",
            ["browser.search"],
        )


def test_runtime_rejects_trusted_tool_capability_that_does_not_match_plan_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_intent_module,
        "planner_tool_requests_for_decision",
        lambda *_args, **_kwargs: [
            {
                "tool": "desktop.active_window",
                "input": {},
                "step_id": "discover-desktop-state",
                # The adapter supports this capability too, but this exact plan
                # step was minted for desktop.app_discovery.
                "capability_id": "desktop.visual_verification",
            }
        ],
    )

    with pytest.raises(ModelIntentPlanningError, match="plan_capability_mismatch"):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="desktop_operation",
                planning_goal="打开 Safari",
            ),
            "请打开 Safari",
            ["desktop.active_window", "desktop.list_apps", "desktop.open_app"],
        )


def test_clarification_proposal_cannot_become_executable_selection() -> None:
    with pytest.raises(
        ModelIntentPlanningError,
        match="clarification_requires_user_turn",
    ):
        direct_tool_selection_from_model_intent_proposal(
            ModelIntentProposal(
                intent_kind="file_organization",
                planning_goal="整理项目文件",
                clarification_question="请问要整理哪个目录？",
            ),
            "帮我整理一下文件",
            ["file.list", "terminal.run", "artifact.write"],
        )


def test_clarification_proposal_becomes_non_executable_turn_resolution() -> None:
    original_goal = "帮我整理一下文件"
    question = "请问要整理哪个目录？"

    resolution = model_intent_resolution_from_proposal(
        ModelIntentProposal(
            intent_kind="file_organization",
            planning_goal="整理用户指定的目录",
            clarification_question=question,
            rationale="This text must never cross the clarification boundary.",
        ),
        original_goal,
        ["file.list", "terminal.run", "artifact.write"],
    )

    assert resolution == ModelIntentClarificationResolution(
        original_goal=original_goal,
        question=question,
    )
    assert not isinstance(resolution, DirectToolSelection)
    assert not hasattr(resolution, "rationale")
    assert not hasattr(resolution, "requests")


@pytest.mark.parametrize("question", ["   ", "x" * 501])
def test_clarification_resolution_rejects_blank_or_oversized_question(
    question: str,
) -> None:
    with pytest.raises(ModelIntentPlanningError):
        model_intent_resolution_from_proposal(
            ModelIntentProposal(
                intent_kind="file_organization",
                planning_goal="整理用户指定的目录",
                clarification_question=question,
            ),
            "帮我整理一下文件",
            ["file.list"],
        )


def test_goal_contract_projection_rejects_tampered_root_goal() -> None:
    selection = direct_tool_selection_from_model_intent_proposal(
        ModelIntentProposal(
            intent_kind="web_research",
            planning_goal="搜索网页查找 Python 新闻",
        ),
        "帮我查资料",
        ["browser.search"],
    )
    tampered = DirectToolSelection(
        decision=selection.decision.model_copy(update={"prompt": "另一个目标"}),
        requests=selection.requests,
        event_payload=selection.event_payload,
        selected_source=selection.selected_source,
    )

    with pytest.raises(ModelIntentPlanningError, match="goal_authority_conflict"):
        goal_contract_payload_from_model_selection(tampered, "帮我查资料")
