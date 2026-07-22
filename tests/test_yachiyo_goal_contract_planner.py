from __future__ import annotations

import pytest

from apps.shell.agent.runtime.goal_runtime import (
    runtime_goal_assessment,
    runtime_goal_contract,
)
from apps.shell.yachiyo_agent.contracts import TaskCoreSnapshot
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_from_decision,
    runtime_execution_requests_from_envelope_payload,
)
from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_entrypoint_runtime_plan,
)
from apps.shell.yachiyo_agent.planner_projection import planner_enriched_chat_request
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


def test_media_plan_carries_application_independent_effect_goal_contract() -> None:
    decision = RuntimePlanner().decision(
        "Play Moonlight",
        allowed_tools=["media.apple_music_play"],
    )

    task_core = decision.plan.task_core
    assert task_core is not None
    contract = task_core.goal_contract
    assert contract is not None
    assert contract.original_goal == "Play Moonlight"
    assert contract.intent_kind == "media_playback"
    assert len(contract.criteria) == 1
    criterion = contract.criteria[0]
    assert criterion.effectful is True
    assert criterion.response_satisfiable is False
    assert criterion.required_capabilities == ["media.playback"]
    assert criterion.expected == {
        "state": "playing",
        "target": {
            "kind": "media",
            "action": "play",
            "query": "Moonlight",
        },
    }
    assert criterion.source_step_ids == ["control-media-playback"]
    # Tool implementation names may live in the plan, but completion semantics
    # cannot become an Apple Music-only contract.
    assert "apple_music" not in str(contract.model_dump()).casefold()

    restored = TaskCoreSnapshot.model_validate(task_core.model_dump())
    assert restored.goal_contract == contract


@pytest.mark.parametrize(
    ("prompt", "allowed_tools", "expected_step_id", "expected_target"),
    (
        (
            "打开 Word 新建文档",
            [
                "app.open_and_safe_shortcut",
                "desktop.verify",
            ],
            "operate-foreground-ui",
                {
                    "kind": "desktop_app",
                    "action": "keyboard_shortcut",
                    "shortcut_action": "new_document",
                    "selection_source": "direct_app_name",
                "app_name": "Word",
                "query": "Word",
            },
        ),
        (
            "现在开了哪些应用",
            ["desktop.running_apps"],
            "read_running_apps-desktop-state",
            {
                "kind": "desktop_discovery",
                "action": "list_running_apps",
                "selection_source": "desktop.running_apps",
            },
        ),
    ),
)
def test_goal_contract_binds_the_authoritative_planned_action_target(
    prompt: str,
    allowed_tools: list[str],
    expected_step_id: str,
    expected_target: dict,
) -> None:
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
    )

    assert envelope is not None
    criterion = decision.plan.task_core.goal_contract.criteria[0]  # type: ignore[union-attr]
    request = next(
        item for item in envelope.requests if item.step_id == expected_step_id
    )
    assert criterion.source_step_ids == [expected_step_id]
    assert criterion.expected["target"] == expected_target
    assert request.action_target == {
        **expected_target,
        "step_id": expected_step_id,
    }


@pytest.mark.parametrize(
    ("prompt", "allowed_tools", "expected_action", "expected_state", "effectful"),
    (
        (
            "Apple Music 暂停",
            ["media.apple_music_control"],
            "pause",
            "paused",
            True,
        ),
        (
            "继续播放当前音乐",
            ["media.system_control"],
            "play",
            "playing",
            True,
        ),
        (
            "查看当前播放状态",
            ["media.apple_music_status"],
            "status",
            None,
            False,
        ),
    ),
)
def test_media_goal_compiler_preserves_generic_control_semantics(
    prompt: str,
    allowed_tools: list[str],
    expected_action: str,
    expected_state: str | None,
    effectful: bool,
) -> None:
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)

    step = decision.plan.tool_plan.steps[0]
    criterion = decision.plan.task_core.goal_contract.criteria[0]  # type: ignore[union-attr]
    assert step.capability_id == "media.playback"
    assert step.action == expected_action
    assert criterion.effectful is effectful
    assert criterion.expected["target"]["action"] == expected_action
    if expected_state is None:
        assert "state" not in criterion.expected
    else:
        assert criterion.expected["state"] == expected_state
    assert "apple_music" not in str(criterion.model_dump()).casefold()


@pytest.mark.parametrize("action", ("next", "previous"))
def test_media_track_navigation_requires_change_evidence(action: str) -> None:
    prompt = "下一首" if action == "next" else "上一首"
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=["media.system_control"],
    )

    criterion = decision.plan.task_core.goal_contract.criteria[0]  # type: ignore[union-attr]
    assert decision.plan.tool_plan.steps[0].action == action
    assert criterion.expected == {
        "track_change_verified": True,
        "target": {
            "kind": "media",
            "action": action,
        },
    }


def test_generated_clipboard_output_owns_its_goal_and_stays_blocked_without_analysis() -> None:
    allowed_tools = ["clipboard.write"]
    decision = RuntimePlanner().decision(
        "分析这段数据并复制结论",
        allowed_tools=allowed_tools,
    )

    task_core = decision.plan.task_core
    assert task_core is not None
    goal_contract = task_core.goal_contract
    assert goal_contract is not None
    criteria_by_capability = {
        tuple(criterion.required_capabilities): criterion
        for criterion in goal_contract.criteria
    }
    analysis_criterion = criteria_by_capability[("data.analysis",)]
    clipboard_criterion = criteria_by_capability[("clipboard.read_write",)]
    assert analysis_criterion.source_step_ids == ["run-analysis"]
    assert clipboard_criterion.source_step_ids == ["write-clipboard-output"]
    assert clipboard_criterion.expected == {
        "state": "persisted",
        "target": {"kind": "clipboard", "action": "write_clipboard"},
    }

    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
    )
    assert envelope is not None
    assert envelope.requests[0].depends_on == ["run-analysis"]
    assert envelope.requests[0].status == "blocked"
    assert runtime_execution_requests_from_envelope_payload(
        envelope.model_dump(mode="json"),
        allowed_tools=allowed_tools,
    ) == []


def test_structured_recovery_request_is_bound_to_the_planner_goal_lineage() -> None:
    metadata = {
        "desktop_permission_recovery": True,
        "recovery_tool": "system.settings_open",
        "recovery_input": {"target": "屏幕录制权限"},
        "recovery_permission_target": "screen_recording",
        "recovery_risk_level": "low",
    }

    plan = daily_desktop_entrypoint_runtime_plan(
        "修复屏幕录制",
        metadata=metadata,
        allowed_tools=["system.settings_open"],
    )

    assert plan.decision is not None
    assert len(plan.entrypoint_requests) == 1
    request = plan.entrypoint_requests[0]
    contract = plan.decision.plan.task_core.goal_contract
    assert contract is not None
    criterion = contract.criteria[0]
    assert request["source"] == "daily_desktop_metadata"
    assert request["plan_id"] == plan.decision.plan.plan_id
    assert request["step_id"] == "open-system-settings"
    assert request["capability_id"] == "system.control"
    assert request["action_target"] == {
        **criterion.expected["target"],
        "step_id": "open-system-settings",
    }
    assert criterion.source_step_ids == ["open-system-settings"]
    assert plan.runtime_execution_envelope["plan_id"] == request["plan_id"]


def test_unrelated_structured_recovery_target_cannot_bind_or_execute_root_goal() -> None:
    plan = daily_desktop_entrypoint_runtime_plan(
        "修复屏幕录制",
        metadata={
            "desktop_permission_recovery": True,
            "recovery_tool": "system.settings_open",
            "recovery_input": {"target": "蓝牙"},
            "recovery_permission_target": "screen_recording",
            "recovery_risk_level": "low",
        },
        allowed_tools=["system.settings_open"],
    )

    assert plan.selected_source == "metadata_unbound"
    assert plan.entrypoint_requests == []
    assert plan.executable_requests == []
    assert plan.runtime_execution_envelope == {}


def test_unbound_structured_recovery_projection_drops_execution_authority() -> None:
    payload = planner_enriched_chat_request(
        {
            "prompt": "修复屏幕录制",
            "allowed_tools": ["system.settings_open"],
            "direct_tool_requests": [
                {
                    "tool": "system.settings_open",
                    "input": {"target": "蓝牙"},
                }
            ],
            "metadata": {
                "desktop_permission_recovery": True,
                "recovery_tool": "system.settings_open",
                "recovery_input": {"target": "蓝牙"},
                "recovery_permission_target": "screen_recording",
                "recovery_risk_level": "low",
            },
        }
    )

    assert "direct_tool_requests" not in payload
    assert "runtime_execution_envelope" not in payload
    assert payload["metadata"]["yachiyo_runtime_blocked"] is True
    assert payload["metadata"]["yachiyo_runtime_block_reason"] == (
        "structured_recovery_goal_binding_failed"
    )
    assert "desktop_permission_recovery" not in payload["metadata"]
    assert "recovery_tool" not in payload["metadata"]


@pytest.mark.parametrize(
    ("metadata", "allowed_tools", "expected_tools", "expected_goal"),
    [
        pytest.param(
            {
                "desktop_permission_recovery": True,
                "recovery_tool": "desktop.windows",
                "recovery_input": {"app_name": "Google Chrome"},
                "recovery_risk_level": "low",
            },
            ["desktop.list_apps", "desktop.windows"],
            ["desktop.list_apps", "desktop.windows"],
            "查看Google Chrome窗口",
            id="window-discovery",
        ),
        pytest.param(
            {
                "desktop_permission_recovery": True,
                "recovery_tool": "app.focus_and_safe_shortcut",
                "recovery_input": {
                    "app_name": "Google Chrome",
                    "action": "find",
                },
                "recovery_risk_level": "low",
            },
            [
                "desktop.list_apps",
                "app.focus_and_safe_shortcut",
                "desktop.ui_elements",
            ],
            [
                "desktop.list_apps",
                "app.focus_and_safe_shortcut",
                "desktop.ui_elements",
            ],
            "切到Google Chrome并打开查找",
            id="app-scoped-discover-operate-verify",
        ),
        pytest.param(
            {
                "desktop_permission_recovery": True,
                "recovery_tool": "browser.open_url_and_screenshot",
                "recovery_input": {"url": "https://github.com"},
                "recovery_risk_level": "low",
            },
            ["browser.open_url_and_screenshot"],
            ["browser.open_url_and_screenshot"],
            "打开 https://github.com 并截图",
            id="browser-composite",
        ),
        pytest.param(
            {
                "desktop_permission_recovery": True,
                "recovery_tool": "screen.capture",
                "recovery_input": {"reason": "user asked to capture the screen"},
                "recovery_risk_level": "low",
            },
            ["screen.capture"],
            ["screen.capture"],
            "截图当前屏幕",
            id="screen-capture",
        ),
    ],
)
def test_structured_recovery_composites_execute_the_full_planner_lineage(
    metadata: dict[str, object],
    allowed_tools: list[str],
    expected_tools: list[str],
    expected_goal: str,
) -> None:
    plan = daily_desktop_entrypoint_runtime_plan(
        "重试该恢复操作",
        metadata=metadata,
        allowed_tools=allowed_tools,
    )

    assert plan.decision is not None
    assert plan.selected_source == "metadata_runtime_planner"
    assert [request["tool"] for request in plan.entrypoint_requests] == expected_tools
    assert plan.entrypoint_requests == plan.executable_requests
    contract = plan.decision.plan.task_core.goal_contract
    assert contract is not None
    assert contract.original_goal == expected_goal
    assert plan.runtime_execution_envelope["plan_id"] == plan.decision.plan.plan_id
    assert all(
        request["plan_id"] == plan.decision.plan.plan_id
        and request["step_id"]
        and request["capability_id"]
        and request["action_target"]
        for request in plan.entrypoint_requests
    )
    selected = next(
        request
        for request in plan.entrypoint_requests
        if request["tool"] == metadata["recovery_tool"]
    )
    assert selected["source"] == "daily_desktop_metadata"
    assert selected["planning_reason"] == "structured_recovery_metadata"
    assert selected["goal_contract_id"] == contract.contract_id
    assert selected["root_goal_unchanged"] is True


def test_general_plan_has_explicit_response_only_completion_contract() -> None:
    decision = RuntimePlanner().decision(
        "Explain why the sky looks blue",
        allowed_tools=[],
    )

    contract = decision.plan.task_core.goal_contract  # type: ignore[union-attr]
    assert contract is not None
    assert contract.intent_kind == "general"
    assert len(contract.criteria) == 1
    criterion = contract.criteria[0]
    assert criterion.effectful is False
    assert criterion.response_satisfiable is True
    assert criterion.required_capabilities == []


@pytest.mark.parametrize(
    "prompt",
    (
        "Collect constraints and summarize the tradeoffs.",
        (
            "基于全局目标整理事实、约束和不确定点，"
            "为设计与实现提供依据。"
        ),
        (
            "根据上游设计与约束给出实现方案、必要代码或变更计划，"
            "并说明验证方式。"
        ),
        "审查上游实现或方案，列出风险、缺失测试和可验收结论。",
        "把整条流程的目标、关键决策、产物和风险整理成最终汇报。",
    ),
)
def test_contextual_advisory_goals_remain_response_only(prompt: str) -> None:
    decision = RuntimePlanner().decision(prompt, allowed_tools=[])

    assert decision.selected_intent.kind == "general"
    assert decision.plan.tool_plan.steps == []
    contract = decision.plan.task_core.goal_contract  # type: ignore[union-attr]
    assert contract is not None
    assert contract.original_goal == prompt
    assert len(contract.criteria) == 1
    assert contract.criteria[0].effectful is False
    assert contract.criteria[0].response_satisfiable is True


@pytest.mark.parametrize(
    ("prompt", "expected_kind", "expected_capability"),
    (
        (
            "Write a launch risk report to report.md",
            "report_generation",
            "artifact.write",
        ),
        (
            "根据上游代码修复 login.py 中的 bug",
            "code_task",
            "file.workspace_write",
        ),
        (
            "运行 Daily Summary workflow",
            "workflow_orchestration",
            "workflow.orchestration",
        ),
    ),
)
def test_explicit_effect_goals_keep_their_effect_route(
    prompt: str,
    expected_kind: str,
    expected_capability: str,
) -> None:
    decision = RuntimePlanner().decision(prompt)

    assert decision.selected_intent.kind == expected_kind
    assert expected_capability in {
        step.capability_id for step in decision.plan.tool_plan.steps
    }


@pytest.mark.parametrize(
    "prompt",
    (
        "做真实 Native 群聊派发验证",
        "开展应用路由验证",
        "验证本地任务派发逻辑",
        "Validate the native dispatch mechanism",
        "Conduct a native dispatch verification",
    ),
)
def test_validation_and_dispatch_language_does_not_authorize_desktop_actions(
    prompt: str,
) -> None:
    decision = RuntimePlanner().decision(prompt, allowed_tools=[])

    assert decision.selected_intent.kind == "general"
    assert all(
        candidate.kind != "desktop_operation"
        for candidate in decision.candidate_intents
    )
    assert decision.plan.tool_plan.steps == []
    contract = decision.plan.task_core.goal_contract  # type: ignore[union-attr]
    assert contract is not None
    assert contract.criteria[0].response_satisfiable is True


@pytest.mark.parametrize(
    ("prompt", "expected_app", "expected_operation"),
    (
        ("打开 PixelForge", "PixelForge", "open"),
        ("Open PixelForge", "PixelForge", "open"),
        ("验证 PixelForge 应用窗口", "PixelForge", "read_ui"),
        ("Verify the PixelForge app window", "PixelForge", "read_ui"),
        ("在 PixelForge 输入 hello", "PixelForge", "type"),
        ("In PixelForge, type hello", "PixelForge", "type"),
    ),
)
def test_explicit_desktop_actions_keep_credible_app_targets(
    prompt: str,
    expected_app: str,
    expected_operation: str,
) -> None:
    decision = RuntimePlanner().decision(prompt)

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == expected_app
    assert decision.selected_intent.inputs["operation_hint"] == expected_operation


def test_effectful_desktop_contract_excludes_observation_only_preconditions() -> None:
    decision = RuntimePlanner().decision(
        "退出当前应用",
        allowed_tools=["desktop.quit_app"],
    )

    contract = decision.plan.task_core.goal_contract  # type: ignore[union-attr]
    assert contract is not None
    assert [criterion.required_capabilities for criterion in contract.criteria] == [
        ["desktop.app_control"]
    ]
    criterion = contract.criteria[0]
    # The foreground tool proves that the quit request was dispatched, while
    # the public result deliberately does not claim that the app has exited.
    assert criterion.effectful is False
    assert criterion.source_step_ids == ["manage-foreground"]
    assert criterion.expected == {
        "state": "fulfilled",
        "target": {"action": "dispatch_management"},
    }


def test_effectful_app_open_contract_keeps_effect_and_verifier_not_discovery_goal() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.verify"],
    )

    contract = decision.plan.task_core.goal_contract  # type: ignore[union-attr]
    assert contract is not None
    assert [criterion.required_capabilities for criterion in contract.criteria] == [
        ["desktop.app_control"]
    ]
    criterion = contract.criteria[0]
    assert criterion.source_step_ids == ["open-or-focus-app"]
    assert criterion.verifier_step_ids == ["verify-desktop-result"]


def test_observation_only_desktop_request_keeps_discovery_as_user_goal() -> None:
    decision = RuntimePlanner().decision(
        "列出当前运行的应用",
        allowed_tools=["desktop.running_apps"],
    )

    contract = decision.plan.task_core.goal_contract  # type: ignore[union-attr]
    assert contract is not None
    assert [criterion.required_capabilities for criterion in contract.criteria] == [
        ["desktop.app_discovery"]
    ]
    assert contract.criteria[0].source_step_ids == [
        "read_running_apps-desktop-state"
    ]


def test_cross_app_research_contract_requires_the_terminal_app_sink() -> None:
    prompt = "搜索上海明天天气，并把结果写入备忘录"
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=[
            "browser.search",
            "browser.extract_text",
            "artifact.write",
            "app.open",
            "desktop.safe_type_text",
            "desktop.ui_elements",
            "desktop.verify",
        ],
    )

    task_core = decision.plan.task_core
    assert task_core is not None
    contract_template = task_core.goal_contract
    assert contract_template is not None
    criteria_by_capability = {
        tuple(criterion.required_capabilities): criterion
        for criterion in contract_template.criteria
    }
    assert set(criteria_by_capability) == {
        ("browser.research",),
        ("desktop.ui_operation",),
    }
    assert ("artifact.write",) not in criteria_by_capability
    assert ("desktop.app_control",) not in criteria_by_capability

    browser_criterion = criteria_by_capability[("browser.research",)]
    sink_criterion = criteria_by_capability[("desktop.ui_operation",)]
    assert browser_criterion.effectful is False
    assert browser_criterion.source_step_ids == [
        "open-web-search",
        "inspect-web-search-results",
    ]
    assert browser_criterion.verifier_step_ids == []
    assert sink_criterion.effectful is True
    assert sink_criterion.source_step_ids == ["insert-research-into-target-app"]
    assert sink_criterion.verifier_step_ids == ["verify-research-target-app"]
    verifier_step = next(
        step
        for step in decision.plan.tool_plan.steps
        if step.step_id == "verify-research-target-app"
    )
    assert verifier_step.tool_name == "desktop.verify"
    assert verifier_step.input_preview == {"app_name": "Notes"}
    assert sink_criterion.expected == {
        "state": "fulfilled",
        "target": {
            "kind": "desktop_app",
            "action": "type_ui",
            "app_name": "Notes",
        },
    }

    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=[
            "browser.search",
            "browser.extract_text",
            "artifact.write",
            "app.open",
            "desktop.safe_type_text",
            "desktop.ui_elements",
            "desktop.verify",
        ],
        full_plan=True,
    )
    assert envelope is not None
    sink_request = next(
        request
        for request in envelope.requests
        if request.step_id == "insert-research-into-target-app"
    )
    assert sink_request.action_target == {
        "kind": "desktop_app",
        "action": "type_ui",
        "selection_source": "direct_app_name",
        "app_name": "Notes",
        "query": "Notes",
        "step_id": "insert-research-into-target-app",
    }

    contract = runtime_goal_contract(
        run_id="run-cross-app-research",
        runtime_execution_envelope={"task_core": task_core.model_dump()},
        runtime_execution_metadata=None,
        messages=[{"role": "user", "content": prompt}],
        timeline=[],
    )
    assert contract is not None
    assessment = runtime_goal_assessment(
        contract,
        [
            {
                "event": "agent.tool.call",
                "run_id": contract.run_id,
                "detail": "browser.extract_text",
                "tool_call_id": "inspect-weather-results",
                "step_id": "inspect-web-search-results",
                "capability_id": "browser.research",
                "action_target": {"kind": "web", "action": "extract_text"},
                "result": {"ok": True, "data": {"text": "明天晴，18°C"}},
            }
        ],
    )

    bound_browser_id = next(
        criterion.criterion_id
        for criterion in contract.criteria
        if criterion.required_capabilities == ("browser.research",)
    )
    bound_sink_id = next(
        criterion.criterion_id
        for criterion in contract.criteria
        if criterion.required_capabilities == ("desktop.ui_operation",)
    )
    assert assessment.satisfied_criterion_ids == (bound_browser_id,)
    assert assessment.unsatisfied_criterion_ids == (bound_sink_id,)
    assert assessment.completed is False
