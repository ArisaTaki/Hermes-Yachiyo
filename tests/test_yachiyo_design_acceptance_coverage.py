"""Source-level coverage guards for the Oha-Yachiyo Agent design brief.

The product brief's 10.3 acceptance scenarios span Chat, Bubble/Live2D,
Agent Studio, Groups, Workflow, Run Timeline, and legacy compatibility. These
tests pin each scenario to concrete implementation or smoke-test evidence so
future refactors do not silently drop a required product path.
"""

from __future__ import annotations

from pathlib import Path

from scripts.run_electron_ui_smokes import electron_ui_smoke_scripts

ROOT = Path(__file__).resolve().parents[1]

AcceptanceEvidence = tuple[str, str, tuple[str, ...]]
AcceptanceScenario = tuple[int, str, tuple[AcceptanceEvidence, ...]]

ACCEPTANCE_10_3_REQUIREMENTS = [
    "Chat 发起普通任务。",
    "Chat 看到任务卡片。",
    "Chat 中出现审批卡片。",
    "用户批准后任务继续。",
    "用户拒绝后任务停止或走拒绝分支。",
    "Chat 可打开 Agent Studio 查看完整 run timeline。",
    "Agent Studio 可查看 Agent 列表。",
    "Agent Studio 可查看/编辑群组。",
    "Agent Studio 可发起群组 run。",
    "Agent Studio 可查看 workflow run timeline。",
    "旧 /agents/* API 仍工作。",
    "旧 AgentStudioView 关键功能未丢失。",
]

ACCEPTANCE_10_3_MATRIX: tuple[AcceptanceScenario, ...] = (
    (
        1,
        "Chat 发起普通任务。",
        (
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskSubmit.ts",
                ("startYachiyoTask({", "source: 'chat'", "pollAgentRunInBackground(taskId);"),
            ),
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/api.ts",
                ("apiPost('/yachiyo/tasks'",),
            ),
            (
                "smoke",
                "scripts/smoke_chat_public_task_ui.mjs",
                ("/yachiyo/tasks", "assertPublicTaskContract", "taskRequest.metadata?.source !== 'chat'"),
            ),
        ),
    ),
    (
        2,
        "Chat 看到任务卡片。",
        (
            (
                "source",
                "apps/frontend/src/views/ChatView.tsx",
                ("MessageBubble", "publicTaskSnapshotForMessage"),
            ),
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/components/MessageBubble.tsx",
                ("MessageAgentTaskCard", "onOpenStudio={onOpenRunDetails}"),
            ),
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
                ('data-testid="yachiyo-agent-task-card"', "RuntimeTimelineSummary"),
            ),
            (
                "smoke",
                "scripts/smoke_chat_public_task_ui.mjs",
                (
                    'data-testid="yachiyo-agent-task-card"',
                    'data-testid="yachiyo-agent-task-open-studio"',
                    "Chat public task card rendered",
                ),
            ),
        ),
    ),
    (
        3,
        "Chat 中出现审批卡片。",
        (
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
                ("ApprovalCard", "approvalFacts.slice(0, 2).map((approval)"),
            ),
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskEventReplay.ts",
                ("mergeApprovalSnapshots", "approvalsFromRunEventReplay(replayEvents)"),
            ),
            (
                "smoke",
                "scripts/smoke_chat_approval_ui.mjs",
                ('data-testid="chat-message-approval-card"', 'data-testid="chat-message-approval-approve"'),
            ),
            (
                "smoke",
                "scripts/smoke_chat_public_task_ui.mjs",
                ('data-testid="yachiyo-task-approval-card"', 'data-testid="yachiyo-task-approval-approve"'),
            ),
        ),
    ),
    (
        4,
        "用户批准后任务继续。",
        (
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskActions.ts",
                ("approveYachiyoTask(task.task_id, approval.approval_id)", "pollAgentRunInBackground(nextRunId"),
            ),
            (
                "smoke",
                "scripts/smoke_chat_approval_ui.mjs",
                ('data-testid="chat-message-approval-approve"', "waitForApprovedRunDetailHandoff"),
            ),
            (
                "smoke",
                "scripts/smoke_chat_public_task_ui.mjs",
                ("/yachiyo/tasks/${TASK_ID}/approve", "Chat public task approval approved"),
            ),
        ),
    ),
    (
        5,
        "用户拒绝后任务停止或走拒绝分支。",
        (
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskActions.ts",
                ("rejectYachiyoTask(task.task_id, approval.approval_id, 'Rejected from chat task card')",),
            ),
            (
                "smoke",
                "scripts/smoke_chat_approval_ui.mjs",
                ('data-testid="chat-message-approval-reject"', "waitForRejected"),
            ),
            (
                "smoke",
                "scripts/smoke_chat_public_task_ui.mjs",
                ("/yachiyo/tasks/${TASK_ID}/reject", "Chat public task approval rejected"),
            ),
        ),
    ),
    (
        6,
        "Chat 可打开 Agent Studio 查看完整 run timeline。",
        (
            (
                "source",
                "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
                ('data-testid="yachiyo-agent-task-open-studio"', "onOpenStudio(undefined, studioUrl)"),
            ),
            (
                "smoke",
                "scripts/smoke_chat_run_detail_handoff_ui.mjs",
                ('data-testid="chat-message-open-run-detail"', 'data-testid="agent-run-detail-execution-event"', "Run Detail handoff"),
            ),
        ),
    ),
    (
        7,
        "Agent Studio 可查看 Agent 列表。",
        (
            (
                "smoke",
                "scripts/smoke_agent_studio_agents_ui.mjs",
                ("/yachiyo/studio/agents", 'data-testid="agent-list-item"', "Agent Definition Smoke v1"),
            ),
        ),
    ),
    (
        8,
        "Agent Studio 可查看/编辑群组。",
        (
            (
                "smoke",
                "scripts/smoke_agent_studio_groups_ui.mjs",
                ("/yachiyo/studio/groups", 'data-testid="agent-group-editor"', 'data-testid="agent-group-save"', "existing group edited"),
            ),
            (
                "source",
                "apps/frontend/src/features/yachiyo-studio/api.ts",
                ("/yachiyo/studio/groups", "apiPatch(`/yachiyo/studio/groups/${encodeURIComponent(groupId)}`"),
            ),
        ),
    ),
    (
        9,
        "Agent Studio 可发起群组 run。",
        (
            (
                "smoke",
                "scripts/smoke_agent_studio_groups_ui.mjs",
                (
                    "/yachiyo/studio/groups/${encodeURIComponent(CREATED_GROUP_ID)}/runs",
                    'data-testid="agent-group-run"',
                    'data-testid="agent-run-detail-group-run-artifacts"',
                    "group run detail verified",
                ),
            ),
        ),
    ),
    (
        10,
        "Agent Studio 可查看 workflow run timeline。",
        (
            (
                "smoke",
                "scripts/smoke_workflow_save_run_ui.mjs",
                ('data-testid="workflow-save-and-run"', "/yachiyo/studio/runs/${RUN_ID}/timeline", "workflow.run.completed"),
            ),
        ),
    ),
    (
        11,
        "旧 /agents/* API 仍工作。",
        (
            (
                "source",
                "tests/test_bridge_server.py",
                (
                    "test_agent_studio_crud_http_routes_use_app_runtime_service",
                    'client.get("/ui/agents")',
                    'assert responses[0].json() == {"agents": [{"agent_id": "agent-1"}]}',
                    'assert responses[1].json() == {"agent_id": "agent-1", "name": "Agent 1"}',
                ),
            ),
            (
                "source",
                "apps/bridge/routes/agents.py",
                ('APIRouter(prefix="/ui", tags=["Agent Studio"])', '@router.get("/agents")', '@router.post("/agents")'),
            ),
            (
                "source",
                "tests/test_yachiyo_routes.py",
                ("legacy_agents_source", 'assert \'@router.get("/agents")\' in legacy_agents_source'),
            ),
        ),
    ),
    (
        12,
        "旧 AgentStudioView 关键功能未丢失。",
        (
            (
                "smoke",
                "scripts/smoke_agent_studio_agents_ui.mjs",
                ('data-testid="agent-studio-agents"', "agent updated", "agent deleted"),
            ),
            (
                "smoke",
                "scripts/smoke_agent_studio_groups_ui.mjs",
                ('data-testid="agent-studio-groups"', "group run detail verified"),
            ),
            (
                "smoke",
                "scripts/smoke_workflow_management_ui.mjs",
                ('data-testid="workflow-list-manage"', "workflow management delete paths rendered"),
            ),
            (
                "smoke",
                "scripts/smoke_agent_run_detail_ui.mjs",
                (
                    'data-testid="agent-run-detail-approval"',
                    "artifact preview rendered",
                    "run detail memory skill trace replay verified",
                ),
            ),
            (
                "source",
                "apps/frontend/src/views/AgentStudioView.tsx",
                ("AgentDefinitionsTab", "AgentStudioGroupsTab", "AgentStudioRunsTab", "AgentStudioWorkflowsTab"),
            ),
            (
                "source",
                "apps/frontend/src/features/agent-studio/components/AgentStudioGroupsTab.tsx",
                ("AgentGroupPanel", "agentGroupMemoryScope={agentGroupMemoryScope || 'shared'}"),
            ),
            (
                "source",
                "apps/frontend/src/features/agent-studio/components/AgentStudioWorkflowsTab.tsx",
                ("WorkflowEditorPanel", "agentCapabilityLine"),
            ),
            (
                "source",
                "apps/frontend/src/features/agent-studio/components/AgentStudioRunsTab.tsx",
                ("RunManagementTab", "WorkflowRunPreview", "workflowStepSummary"),
            ),
            (
                "source",
                "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
                ("ToolCallInspector", "ApprovalInspector", "ArtifactInspector", "RunTimeline"),
            ),
        ),
    ),
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(relative_path: str, fragments: list[str]) -> None:
    text = _read(relative_path)
    missing = [fragment for fragment in fragments if fragment not in text]
    assert not missing, f"{relative_path} is missing design acceptance evidence: {missing!r}"


def _assert_smoke_script(script: str, fragments: list[str]) -> None:
    scripts = {str(path) for path in electron_ui_smoke_scripts(ROOT)}
    assert script in scripts, f"{script} must be discovered by run_electron_ui_smokes.py"
    _assert_contains(script, fragments)


def _assert_acceptance_evidence(evidence: AcceptanceEvidence) -> None:
    kind, relative_path, fragments = evidence
    assert kind in {"source", "smoke"}
    assert fragments, f"{relative_path} must include at least one evidence fragment"
    if kind == "smoke":
        _assert_smoke_script(relative_path, list(fragments))
    else:
        _assert_contains(relative_path, list(fragments))


def test_hanako_hermes_runtime_roadmap_is_guarded() -> None:
    _assert_contains(
        "docs/yachiyo-hanako-hermes-runtime-roadmap.md",
        [
            "Phase 0 - 基线审计与保护网",
            "Phase 1 - Public Contracts",
            "Phase 2 - Capability Registry",
            "Phase 3 - Task Intent Router",
            "Phase 4 - Runtime Planner",
            "Phase 5 - Desktop Discover/Operate Layer",
            "Phase 6 - Data Analysis Capability",
            "Phase 7 - Prompt/Skill Runtime Doctrine",
            "Phase 8 - Chat/Bubble/Live2D Planner Integration",
            "Phase 9 - Agent Studio Debug Surface",
            "Phase 10 - 删除旧硬编码与收敛代码",
            "Runtime planning follows TaskIntent -> CapabilityPlan -> ToolPlan.",
            "Discovery comes before app-specific rules",
            "Main Chat submits no-attachment, non-group messages through the planner-backed",
            "Old route response shapes, database schema, Agent Studio, Groups, Workflow",
            "禁止删除 Agent Studio。",
            "禁止一次性重写 NativeRunEngine。",
            "禁止改数据库 schema。",
            "禁止破坏旧 route response shape。",
            "禁止绕过 approval/policy gate。",
        ],
    )


def test_10_3_acceptance_matrix_has_concrete_evidence() -> None:
    ids = [scenario_id for scenario_id, _requirement, _evidence in ACCEPTANCE_10_3_MATRIX]
    requirements = [requirement for _scenario_id, requirement, _evidence in ACCEPTANCE_10_3_MATRIX]

    assert ids == list(range(1, 13))
    assert requirements == ACCEPTANCE_10_3_REQUIREMENTS

    for scenario_id, requirement, evidence_items in ACCEPTANCE_10_3_MATRIX:
        assert requirement
        assert evidence_items, f"Scenario {scenario_id} must have concrete evidence"
        for evidence in evidence_items:
            _assert_acceptance_evidence(evidence)


def test_chat_daily_entry_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskSubmit.ts",
        [
            "startYachiyoTask({",
            "rememberYachiyoTasks([task]);",
            "pollAgentRunInBackground(taskId);",
            "return true;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "MessageBubble",
            "publicTaskSnapshotForMessage",
            "String(activeSessionContext?.conversation_kind || '') !== 'group'",
            "if (shouldTryPublicTask)",
            "planner_entrypoint: publicTaskTarget",
            ": 'chat_default'",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/MessageBubble.tsx",
        [
            "MessageAgentTaskCard",
            "onOpenStudio={onOpenRunDetails}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
        [
            "ApprovalCard",
            "onApproveApproval(task, approval)",
            "onRejectApproval(task, approval)",
            'data-testid="yachiyo-task-approval-open-studio"',
            "yachiyoTaskApprovalStudioTarget(task, approval)",
            "ArtifactPreview",
            "ToolCallSummary",
            "在 Agent Studio 中查看",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/taskSnapshots.ts",
        [
            "export function yachiyoTaskApprovalStudioTarget",
            "const publicUrl = String(approval.open_in_studio_url || '').trim();",
            "runIdFromStudioUrl(publicUrl)",
            "approval.source_run_id",
            "approval.workflow_run_id",
            "String(approval.group_run_id || '').trim() || yachiyoTaskStudioGroupRunId(task)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskEventReplay.ts",
        [
            "mergeApprovalSnapshots",
            "mergeArtifactSnapshots",
            "timelineEventSource",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/hooks/useYachiyoTaskActions.ts",
        [
            "approveYachiyoTask(task.task_id, approval.approval_id)",
            "rejectYachiyoTask(task.task_id, approval.approval_id, 'Rejected from chat task card')",
            "cancelYachiyoTask(task.task_id)",
        ],
    )
    _assert_contains(
        "apps/bridge/routes/yachiyo.py",
        [
            '@router.post("/tasks/{task_id}/approvals/{approval_id}/approve")',
            '@router.post("/tasks/{task_id}/approvals/{approval_id}/reject")',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/api.ts",
        [
            "function yachiyoTaskApprovalPath",
            "approvals/${encodeURIComponent(cleanApprovalId)}/${action}",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_chat_public_task_ui.mjs",
        [
            "/yachiyo/tasks",
            "approvals/${APPROVAL_ID}/approve",
            "approvals/${APPROVAL_ID}/reject",
            "assertPublicTaskContract",
            'data-testid="yachiyo-agent-task-card"',
            'data-testid="yachiyo-task-approval-card"',
            'data-testid="yachiyo-task-approval-approve"',
            'data-testid="yachiyo-task-approval-reject"',
            'data-testid="yachiyo-agent-task-open-studio"',
            "Chat public task approval approved",
            "Chat public task approval rejected",
            "Chat public task card rendered",
        ],
    )


def test_tasks_daily_entry_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/frontend/src/lib/view.ts",
        [
            "| 'tasks'",
            "| 'memories'",
            "| 'skills'",
            "'tasks'",
            "'memories'",
            "'skills'",
        ],
    )
    _assert_contains(
        "apps/frontend/src/App.tsx",
        [
            "const TasksView = lazy(() => import('./views/TasksView')",
            "else if (view === 'tasks') page = <TasksView />;",
            "else if (view === 'agents' || view === 'skills' || view === 'memories') page = <AgentStudioView />;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/OpenDesignView.tsx",
        [
            "{ view: 'tasks', label: '任务', icon: 'activity' }",
            "{ view: 'memories', label: '记忆', icon: 'sparkle' }",
            "{ view: 'skills', label: 'Skills', icon: 'resources' }",
            "if (view === 'tasks') return 'Oha Yachiyo — 任务';",
            "if (view === 'memories') return 'Oha Yachiyo — 记忆';",
            "if (view === 'skills') return 'Oha Yachiyo — Skills';",
            "if (view === 'tasks') {",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/TasksView.tsx",
        [
            "listYachiyoTasks()",
            "<AgentTaskCard",
            "onApproveApproval={(nextTask, approval) => resolveTaskApproval(nextTask, approval, 'approve')}",
            "onCancelTask={cancelTask}",
            "onOpenStudio={openTaskInStudio}",
            "onRejectApproval={(nextTask, approval) => resolveTaskApproval(nextTask, approval, 'reject')}",
            'data-testid="yachiyo-tasks-page"',
            'data-testid="yachiyo-tasks-filter-active"',
            'data-testid="yachiyo-tasks-filter-all"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentStudioRouteState.ts",
        [
            "studioTabFromTopLevelView(view) || normalizeStudioTab(currentParam('tab'))",
            "if (view === 'skills') return 'skills';",
            "if (view === 'memories') return 'memory';",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_yachiyo_entry_routes_ui.mjs",
        [
            "#/tasks",
            "#/skills",
            "#/memories",
            "/yachiyo/tasks",
            "/yachiyo/studio/skills",
            "/yachiyo/studio/memories",
            'data-testid="yachiyo-tasks-page"',
            'data-testid="skill-library"',
            'data-testid="agent-runtime-memory"',
            "tasks handoff opened Agent Studio run route",
            "assertMockBridgeContract",
        ],
    )


def test_shared_runtime_surface_components_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/ApprovalCard.tsx",
        [
            "RuntimeApprovalGate",
            "RuntimeApprovalCard",
            'cardVariant="compact"',
            'variant="compact"',
            'approveTestId="yachiyo-task-approval-approve"',
            'rejectTestId="yachiyo-task-approval-reject"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/ArtifactPreview.tsx",
        [
            "RuntimeReadableArtifactPreview",
            "yachiyoTaskArtifactReadTarget",
            "readYachiyoChatRunArtifact(artifactTarget.runId, artifactPath)",
            "readYachiyoTaskArtifact(artifactTarget.taskId, artifactPath)",
            'previewVariant="compact"',
            'previewTestId="yachiyo-task-artifact-preview"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/taskSnapshots.ts",
        [
            "export function yachiyoTaskArtifactReadTarget",
            "path: String(artifact.path || '').trim()",
            "artifact.source_run_id",
            "artifact.workflow_run_id",
            "taskId: String(taskId || '').trim()",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
        [
            "RuntimeTimelineSummary",
            'testId="yachiyo-agent-task-timeline"',
            "<ApprovalCard",
            "<ArtifactPreview artifact={artifact}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ApprovalInspector.tsx",
        [
            "RuntimeApprovalGate",
            "RuntimeApprovalCard",
            'cardVariant="inspector"',
            'variant="inspector"',
            'testId="agent-run-detail-approval"',
            'testId="agent-run-detail-approval-history-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ArtifactInspector.tsx",
        [
            "RuntimeArtifactList",
            'previewVariant="full"',
            'testId="agent-run-detail-artifact-list"',
            'previewTestId="agent-run-detail-artifact-preview-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeArtifactList.tsx",
        [
            "const openRunId = item.source_run_id || item.run_id || fallbackRunId",
            "const openPath = item.path || ''",
            "const openable = Boolean(openPath && openRunId)",
            "data-artifact-openable={openable ? 'true' : 'false'}",
            "disabled={!openable}",
            "onOpenArtifact(openRunId, openPath)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunTimeline.tsx",
        [
            "RuntimeTimelinePanel",
            'eventTestId="agent-run-detail-execution-event"',
            'panelTestId="agent-run-detail-execution"',
            "onLoadMoreEvents={replayEventCount ? onLoadMoreEvents : undefined}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeApprovalCard.tsx",
        [
            "export type RuntimeApprovalVariant",
            "variant = 'compact'",
            "data-approval-variant={variant}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeApprovalGate.tsx",
        [
            "function runtimeApprovalIsPending",
            "const actions = actionable && (onApprove || onReject)",
            "data-approval-actionable={actionable ? 'true' : 'false'}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeArtifactPreview.tsx",
        [
            "export type RuntimeArtifactVariant",
            "variant = 'compact'",
            "data-artifact-variant={variant}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeTimelinePanel.tsx",
        [
            "RuntimeTimelineEventList",
            "replayHasMore && onLoadMoreEvents",
            "data-testid={loadMoreTestId}",
        ],
    )


def test_runtime_core_split_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "tests/test_agent_runtime_pr8_compatibility.py",
        [
            "test_pr8_runtime_split_keeps_legacy_agent_runtime_import_surface",
            "agent_runtime.RunRepository is RunRepository",
            "agent_runtime.RuntimeToolBrokerFactory is RuntimeToolBrokerFactory",
            "agent_runtime.PolicyGate is PolicyGate",
            "agent_runtime.RuntimeRunEventRecorder is RuntimeRunEventRecorder",
            "agent_runtime._RunBudgetLimits is RunBudgetLimits",
        ],
    )
    _assert_contains(
        "apps/shell/agent_runtime.py",
        [
            "from apps.shell.agent.runtime.native_engine import NativeRunEngine",
            "AgentRuntimeService = NativeRunEngine",
            "_RunBudgetLimits",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/native_engine.py",
        [
            "class NativeRunEngine(",
            "RuntimeStudioFacadeMixin",
            "RuntimeMainChatFacadeMixin",
            "RuntimeRunFacadeMixin",
            "RuntimeAgentFacadeMixin",
            "RuntimeToolFacadeMixin",
            "RuntimeWorkflowFacadeMixin",
            "_install_runtime_run_layer()",
            "_install_runtime_tooling_and_custom_agent_loop(",
            "_install_runtime_agent_and_approval_services(",
        ],
    )
    _assert_contains(
        "apps/shell/agent/repositories/runs.py",
        [
            "class RunRepository",
            "def insert(",
            "def update(",
            "pending_approval_private",
            "_sync_projections",
        ],
    )
    _assert_contains(
        "apps/shell/agent/repositories/events.py",
        [
            "class RunEventRepository",
            "def append(",
            "def list(",
            "redact_run_event_payload",
        ],
    )
    _assert_contains(
        "apps/shell/agent/repositories/approvals.py",
        [
            "class ApprovalRepository",
            "def sync(",
            "def upsert_pending(",
            "def claim_pending_approval(",
            "def resolve_pending(",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/tool_brokers.py",
        [
            "class RuntimeToolBrokerFactory",
            "def for_run(",
            "def for_main_chat(",
            "def write_artifact_with_tool_broker(",
        ],
    )
    _assert_contains(
        "apps/shell/agent/tools/policy.py",
        [
            "class ToolDescriptor",
            "def validate_payload(",
            "class PolicyGate",
            "class RuntimePolicyCompiler",
            "HIGH_RISK_AGENT_TOOLS",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/events.py",
        [
            "def redact_run_event_payload",
            "def canonical_tool_event_payload",
            "def model_request_started_payload",
            "def task_run_event_payload",
            '"agent.run.completed": ["run.completed"]',
            '"agent.run.cancelled": ["run.cancelled"]',
            '"agent.tool.denied": ["tool.denied"]',
            '"approval.required"',
            '"agent.artifact.write": ["artifact.created"]',
            'aliases.append("artifact.created")',
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/tool_call_snapshots.py",
        [
            "tool_call_snapshots_from_events",
            "tool_call_snapshot_from_payload",
            "def tool_call_snapshots_from_payloads",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/tool_call_payload_snapshots.py",
        [
            "redact_run_event_payload",
            "redact_secrets",
            "def tool_call_snapshot_from_payload",
            "return _redacted_tool_call_snapshot(payload)",
            "def tool_output_preview",
            "def tool_foreground_lock_is_busy",
            "foreground_lock_holder",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/tool_call_event_snapshots.py",
        [
            "def tool_call_snapshots_from_events",
            "def tool_call_payload_from_event",
            "def merge_tool_call_snapshots",
            "def tool_call_correlation_key",
            "def tool_status_from_event_type",
            "foreground_lock_busy=current.foreground_lock_busy",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/run_timeline_snapshots.py",
        [
            "def run_timeline_snapshot_from_payload",
            "def approval_snapshots_from_payload",
            "def artifact_snapshots_from_timeline_payload",
            "tool_call_snapshots_from_payloads(",
            "memory_trace_snapshots_from_events(events)",
            "skill_trace_snapshots_from_events(events)",
            "timeline_child_snapshots_from_payloads(",
            "timeline_child_snapshots_from_events(events)",
            "merge_timeline_child_snapshots(",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/run_snapshots.py",
        [
            "run_timeline_snapshot_from_payload as _run_timeline_snapshot_from_payload",
            "return _run_timeline_snapshot_from_payload(payload)",
            "tool_call_snapshots_from_payloads as _tool_call_snapshots_from_payloads",
            "return _tool_call_snapshots_from_payloads(payloads, run_id=run_id, events=events)",
            "return _tool_call_snapshots_from_events(events)",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/timeline_metadata_snapshots.py",
        [
            "def timeline_child_snapshots_from_payloads",
            "def timeline_child_snapshots_from_events",
            "def timeline_child_snapshot_from_event",
            "def merge_timeline_child_snapshots",
            "def run_timeline_rerun_provenance_from_payload",
            "def run_timeline_agent_id_from_payload",
            "def workflow_run_id_from_payload",
            "\"run.rerun.started\"",
            "RunTimelineChildSnapshot",
        ],
    )
    _assert_contains(
        "tests/test_yachiyo_run_snapshots.py",
        [
            "test_workflow_run_snapshot_derives_child_approval_bridge_from_replay_events",
            "test_group_run_snapshot_rolls_foreground_lock_waiting_tool_calls_to_member",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/task_snapshots.py",
        [
            "def agent_task_snapshot_from_payload",
            "def run_events_from_payload",
            "def approval_snapshots_from_payload",
            "def artifact_snapshots_from_task_payload",
            "def task_status_from_value",
            "studio_run_url(run_id, group_run_id=group_run_id)",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/trace_snapshots.py",
        [
            "def memory_trace_snapshots_from_events",
            "def skill_trace_snapshots_from_events",
            "def _trace_payload_preview",
            "return _mapping(payload)",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/events.py",
        [
            "redact_run_event_payload",
            "_SECRET_EVENT_PAYLOAD",
            '"reason": "secret_event"',
            "def _public_event_payload",
            "if sensitivity == \"secret\"",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/adapters.py",
        [
            "redact_run_event_payload",
            "redact_secrets",
            "model_settings=_mapping(payload.get(\"model_config\"))",
            "if key_text.endswith(\"_configured\") and isinstance(item, bool)",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/approvals.py",
        [
            "redact_run_event_payload",
            "redact_secrets",
            "input_preview=input_preview",
            "def _mapping",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/approval_event_snapshots.py",
        [
            "ApprovalEventCorrelationTracker",
            "approval_correlation_keys",
            "def approval_snapshots_from_events",
            "def approval_payload_from_event",
            "merge_trace_context_into_approval",
            "event.sensitivity == \"secret\"",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/approval_event_correlation.py",
        [
            "class ApprovalEventCorrelationTracker",
            "def approval_correlation_keys",
            "_AMBIGUOUS_APPROVAL_INDEX",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/approval_snapshot_merging.py",
        [
            "def merge_approval_snapshots",
            "def merge_approval_snapshot_lists",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/artifacts.py",
        [
            "redact_secrets",
            "def artifact_snapshot_from_payload",
            "def artifact_content_snapshot_from_payload",
            "return _redacted_artifact_snapshot(payload)",
            "return _redacted_artifact_content_snapshot(payload)",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/artifact_event_snapshots.py",
        [
            "def artifact_snapshots_from_events",
            "def artifact_payload_from_event",
            "def merge_artifact_snapshot_lists",
            "def merge_artifact_snapshots",
            "event.sensitivity == \"secret\"",
            "\"workflow.node.artifact\"",
            "\"group.shared_artifact.created\"",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/groups.py",
        [
            "redact_secrets",
            "def agent_group_snapshot_from_payload",
            "group_run_snapshot_from_payload",
            "agent_group_members_from_payloads(payload.get(\"members\"))",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/group_member_snapshots.py",
        [
            "def agent_group_member_from_payload",
            "def agent_group_members_from_payloads",
            "def group_run_participants_from_payload",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/group_run_snapshots.py",
        [
            "def group_run_snapshot_from_payload",
            "def group_run_events_with_lifecycle",
            "def group_run_child_payload",
            "objective=_text(payload.get(\"objective\") or payload.get(\"user_goal\"))",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/workflows.py",
        [
            "redact_run_event_payload",
            "redact_json_value",
            "workflow_run_snapshot_from_payload",
            "is_workflow_run_payload",
            "nodes=_list_of_mappings(payload.get(\"nodes\"))",
            "default_input_schema=_schema_mapping(payload.get(\"default_input_schema\"))",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/workflow_run_snapshots.py",
        [
            "def workflow_run_snapshot_from_payload",
            "def workflow_run_payload_with_lifecycle",
            "def is_workflow_run_payload",
            "def workflow_event_context_from_events",
            '"workflow.run.started"',
            '"workflow.run.completed"',
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/skills.py",
        [
            "redact_secrets",
            "def skill_snapshot_from_payload",
            "content_summary=_optional_text(payload.get(\"content_summary\"))",
            "skill_markdown=_optional_text(payload.get(\"skill_markdown\"))",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/future_tasks.py",
        [
            "redact_secrets",
            "def future_task_snapshot_from_payload",
            "prompt=_text(raw.get(\"prompt\"))",
            "error=_optional_text(raw.get(\"error\"))",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/memories.py",
        [
            "redact_secrets",
            "def memory_snapshot_from_payload",
            "content=_text(payload.get(\"content\"))",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/agent_preparation.py",
        [
            "def write_context_artifact",
            '"memory.retrieved"',
            '"agent.artifact.write"',
            '"kind": "agent_artifact"',
            "**artifact",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/run_timeline.py",
        [
            "class RuntimeRunTimelineService",
            "def list_events",
            "def list_group_events",
            "_normalize_event_page_request(",
            "max_limit=1000",
            "max_limit=500",
            "def _group_scoped_event",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/budget.py",
        [
            "class RunBudgetLimits",
            "class RunBudget",
            "def run_budget_from_timeline",
            "def check_context_budget",
            "class WorkflowRunBudget",
        ],
    )


def test_light_launcher_entry_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/frontend/src/views/LauncherView.tsx",
        [
            "startYachiyoTask({",
            "agent_id: LAUNCHER_MAIN_AGENT_ID,",
            "source: 'launcher'",
            "launcher_mode: mode,",
            "runnable_kind: 'main',",
            "launcher_surface: 'desktop_launcher'",
            "LauncherAgentTaskLight",
            "type LauncherQuickMessageResult",
            "const result = await apiPost<LauncherQuickMessageResult>('/ui/launcher/quick-message'",
            "setAgentTaskSnapshot: setPublicAgentTask,",
            "onAgentTaskSnapshot={launcher.setAgentTaskSnapshot}",
            "if (result.agent_task) onAgentTaskSnapshot(result.agent_task);",
            "onApproveTaskApproval={launcher.approveAgentTaskApproval}",
            "onCancelTask={launcher.cancelAgentTask}",
            "onRejectTaskApproval={launcher.rejectAgentTaskApproval}",
            "refreshLauncherAgentTaskAfterAction({",
            "loadTask: getYachiyoTask,",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/launcherTasks.ts",
        [
            "LAUNCHER_MAIN_AGENT_ID",
            "launcherPreferredActiveTask",
            "task.status === 'waiting_approval') return 0;",
            "refreshLauncherAgentTaskAfterAction",
            "LAUNCHER_TASK_ACTION_POLL_DELAYS_MS",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/LauncherView.tsx",
        [
            "launcherAgentTaskIsActive(publicAgentTask || data?.chat?.agent_task)",
            "if (result.agent_task) onAgentTaskSnapshot(result.agent_task);",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_launcher_session_summary_ui.mjs",
        [
            "PUBLIC_TASK_ID",
            "PUBLIC_RUN_ID",
            "/yachiyo/tasks",
            "bubble-launcher-agent-task-light",
            "live2d-launcher-agent-task-light",
            "bubble-launcher-agent-task-approve",
            "bubble-launcher-agent-task-open-diagnostics",
            "live2d-launcher-agent-task-reject",
            "live2d-launcher-agent-task-open-diagnostics",
            "bubble-launcher-quick-input",
            "live2d-launcher-quick-input",
        ],
    )


def test_agent_studio_professional_entry_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/bridge/routes/yachiyo.py",
        [
            '@router.get("/studio/agents")',
            '@router.post("/studio/agents")',
            '@router.patch("/studio/agents/{agent_id}")',
            '@router.get("/studio/groups")',
            '@router.post("/studio/groups")',
            '@router.patch("/studio/groups/{group_id}")',
            '@router.post("/studio/groups/{group_id}/runs")',
            '@router.get("/studio/workflows")',
            '@router.patch("/studio/workflows/{workflow_id}")',
            '@router.post("/studio/workflows/{workflow_id}/runs")',
            '@router.get("/studio/runs/{run_id}/timeline")',
            '@router.get("/studio/runs/{run_id}/events")',
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "AgentDefinitionsTab",
            "AgentStudioGroupsTab",
            "AgentStudioSkillsTab",
            "AgentStudioSkillFoldersTab",
            "AgentStudioRunsTab",
            "AgentStudioWorkflowsTab",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentStudioGroupsTab.tsx",
        [
            "export function AgentStudioGroupsTab",
            "AgentGroupPanel",
            "agentGroupMemoryScope={agentGroupMemoryScope || 'shared'}",
            "agentGroupMode={agentGroupMode || 'moderated'}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentStudioSkillsTab.tsx",
        [
            "export function AgentStudioSkillsTab",
            "SkillLibraryTab",
            "<SkillLibraryTab {...props} />",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentStudioSkillFoldersTab.tsx",
        [
            "export function AgentStudioSkillFoldersTab",
            "SkillFolderPanel",
            "<SkillFolderPanel {...props} />",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentStudioWorkflowsTab.tsx",
        [
            "export function AgentStudioWorkflowsTab",
            "WorkflowEditorPanel",
            "agentCapabilityLine={agentCapabilityLine}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentStudioRunsTab.tsx",
        [
            "export function AgentStudioRunsTab",
            "RunManagementTab",
            "WorkflowRunPreview",
            "workflowPreview={workflowPreview}",
            "runnableCapabilityLine={runnableCapabilityLine}",
            "workflowStepSummary={workflowStepSummary}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunManagementTab.tsx",
        [
            "RunDetailPanel",
            "<RunDetailPanel {...props} />",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "ToolCallInspector",
            "ApprovalInspector",
            "ArtifactInspector",
            "PlannerTraceInspector",
            "RunTimeline",
            "selectedRunReplayEvents",
            'data-testid="agent-run-detail-rerun-source"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/PlannerTraceInspector.tsx",
        [
            "export function PlannerTraceInspector",
            "agent.intent.selected",
            "agent.plan.created",
            "agent.plan.step",
            "agent.plan.selection",
            "group.run.intent.selected",
            "group.run.plan.created",
            "group.run.plan.step",
            "runtimePlannerEventType",
            "plan_tools",
            "plan_capabilities",
            "selection_role",
            "legacy_fallback",
            "plan_step_count",
            'data-testid="agent-run-detail-planner-intent"',
            'data-testid="agent-run-detail-planner-selection"',
            'data-testid="agent-run-detail-planner-capabilities"',
            "data-selection-capability={capabilityId}",
            "data-selection-missing-capability={capabilityId}",
            'data-testid="agent-run-detail-planner-step"',
            "data-input-preview={inputPreview}",
            "data-depends-on={dependsOn.join(',')}",
            "data-fallback-tools={fallbackTools.join(',')}",
            "depends on: {dependsOn.join(', ')}",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_studio_agents_ui.mjs",
        [
            "/yachiyo/studio/agents",
            "Agent Definition Smoke v1",
            "Agent Definition Smoke v2",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_run_detail_ui.mjs",
        [
            'data-testid="agent-run-detail-approval"',
            'data-testid="agent-run-detail-approval-approve"',
            "approval action completed",
            'data-testid="agent-run-detail-execution-event"',
            "agent.tool.call",
            'data-testid="agent-run-detail-artifact-preview"',
            "artifact preview rendered",
        ],
    )


def test_group_and_workflow_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/shell/yachiyo_agent/studio_service.py",
        [
            "def list_groups",
            "def save_group",
            "def start_group_run",
            "def get_group_run",
            "def list_workflows",
            "def save_workflow",
            "def start_workflow_run",
            "def get_run_timeline",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/contracts.py",
        [
            "class GroupRunSnapshot",
            "tool_calls: list[ToolCallSnapshot]",
            "memory_traces: list[MemoryTraceSnapshot]",
            "skill_traces: list[SkillTraceSnapshot]",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/group_run_snapshots.py",
        [
            "def _group_run_tool_calls",
            "def _group_run_memory_traces",
            "def _group_run_skill_traces",
            "child_tool_calls = [tool_call for run in runs for tool_call in run.tool_calls]",
            "child_traces = [trace for run in runs for trace in run.memory_traces]",
            "child_traces = [trace for run in runs for trace in run.skill_traces]",
            "event_tool_calls = (",
            "event_traces = [] if child_traces else",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/legacy_group_runs.py",
        [
            "def start_legacy_group_run",
            "def group_orchestration_plan",
            '"group.run.plan"',
            '"participants_then_moderator"',
            '"fan_out"',
            '"moderator_first"',
            "group_member_phase",
            "group_member_parallel",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentGroupPanel.tsx",
        [
            "agent-group-settings-grid",
            "groupModeOptions",
            "GroupRunPanel",
            "onOpenArtifact={onOpenArtifact}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/GroupRunPanel.tsx",
        [
            "onRunAgentGroup",
            "onOpenArtifact={onOpenArtifact}",
            'data-testid="agent-group-run"',
            'itemTestId="agent-group-run-artifact-item"',
            "onOpenAgentGroupRunTimeline(latestAgentGroupRun)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/GroupRunDetailPanel.tsx",
        [
            "RuntimeTimelineSummary",
            "RuntimeApprovalCard",
            "RuntimeArtifactList",
            "ToolCallInspector",
            "MemorySkillTraceInspector",
            "onOpenArtifact={onOpenArtifact}",
            'data-testid="agent-run-detail-group-run-replay"',
            'testId="agent-run-detail-group-run-planner-trace"',
            'data-testid="agent-run-detail-group-run-approvals"',
            'data-testid="agent-run-detail-group-run-tool-calls"',
            'data-testid="agent-run-detail-group-run-memory-skill-traces"',
            'data-testid="agent-run-detail-group-run-artifacts"',
            'data-testid="agent-run-detail-group-run-child-planner-trace"',
            'itemTestId="agent-run-detail-group-run-artifact-item"',
            "function groupRunChildPlannerTraceSummary",
            "const summary = publicRun?.planner_summary;",
            "summary.intent_kind ? 'intent' : '',",
            "summary.plan_capabilities?.length ? `${summary.plan_capabilities.length} capabilities` : '',",
            "summary.step_count ? `${summary.step_count} steps` : '',",
            "summary.selection_source || summary.selected_tools?.length ? 'selection' : '',",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_studio_groups_ui.mjs",
        [
            "/yachiyo/studio/groups",
            "/yachiyo/studio/groups/${encodeURIComponent(CREATED_GROUP_ID)}/runs",
            "/yachiyo/studio/runs/${encodeURIComponent(GROUP_RUN_ROOT_RUN_ID)}/timeline",
            'data-testid="agent-group-run-artifact-item"',
            'data-testid="agent-run-detail-group-run-artifacts"',
            "assertMockBridgeContract",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_chat_group_summary_ui.mjs",
        [
            "RUN_GROUP_ID",
            "/ui/run-groups/${RUN_GROUP_ID}",
            "/yachiyo/studio/runs/${GROUP_SUMMARY_RUN_ID}/events",
            "data-run-group-id",
            "group summary Run Detail replay verified",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_workflow_save_run_ui.mjs",
        [
            "/yachiyo/studio/workflows",
            "/yachiyo/studio/workflows/${WORKFLOW_ID}/runs",
            "/yachiyo/studio/runs/${RUN_ID}/timeline",
            "workflow.run.completed",
            "workflow.node.approval_required",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_workflow_management_ui.mjs",
        [
            "/yachiyo/studio/workflows",
            'data-testid="workflow-list-manage"',
            'data-testid="workflow-delete-selected"',
            'data-testid="workflow-delete"',
            "workflow management delete paths rendered",
            "assertMockBridgeContract",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeTimelineSummary.tsx",
        [
            "export function runtimeTimelineSummaryEvents",
            "slice(-Math.max(1, limit))",
            "approval.required",
            "task.created",
            "model.requested",
            "model.completed",
            "workflow.started",
            "workflow.paused_for_approval",
            "workflow.resumed",
            "workflow.completed",
            "workflow.failed",
            "group.run.plan",
        ],
    )


def test_run_replay_rerun_and_workflow_branch_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/bridge/routes/yachiyo.py",
        [
            '@router.post("/studio/runs/{run_id}/rerun")',
            "return await yachiyo_studio_handlers.rerun_run(run_id, request_body, http_request)",
            '@router.get("/studio/runs/{run_id}/events")',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-studio/api.ts",
        [
            "export async function listYachiyoRunEvents",
            "export async function rerunYachiyoRun",
            "request: RerunRunRequest = {}",
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/events?${query.toString()}",
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/rerun",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunLaunchActions.ts",
        [
            "const rerunSelectedRun = useCallback",
            "await rerunYachiyoRun(selectedRun.run_id)",
            "const rerunWorkflowScope = useCallback",
            "await rerunYachiyoRun(selectedRun.run_id, request)",
            "openRunDetail(run.run_id, { revealInHistory: true });",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "selectedRunReplayEvents",
            'data-testid="agent-run-detail-rerun"',
            'data-testid="agent-run-detail-rerun-source"',
            "onRerunSelectedRun",
            "onRerunWorkflowScope",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/run_rerun.py",
        [
            "class RuntimeRunRerunService",
            '"run.rerun.started"',
            '"source": "rerun"',
            '"start_node_id": rerun_request["workflow_start_node_id"]',
            '"rerun_scope": rerun_request["scope"]',
            '"original_goal": user_goal',
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/workflow_projections.py",
        [
            '"workflow.edge.followed"',
            "WorkflowEdgeFollowedProjection.from_node",
        ],
    )
    _assert_contains(
        "apps/shell/agent/runtime/workflow_projections.py",
        [
            "workflow_node_selected_branch",
            "workflow_node_selected_target",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/runTimeline.ts",
        [
            "if (name === 'workflow.edge.followed')",
            "workflow_node_selected_branch: payload.workflow_node_selected_branch",
            "workflow_node_selected_target: payload.workflow_node_selected_target",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/workflow.ts",
        [
            "workflow_node_selected_branch",
            "workflow_node_selected_target",
            "selectedBranch: branch",
            "selectedTargetNodeId: target",
            "workflow_node_branch_count",
            "workflow_node_completed_branch_count",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_run_detail_ui.mjs",
        [
            'data-testid="agent-run-detail-rerun"',
            "agent-run-detail-workflow-step-rerun-branch",
            "workflow scoped branch rerun detail",
            "run.rerun.started",
            "rerun replay events",
            "loaded more run event replay page",
        ],
    )


def test_runtime_memory_and_skill_trace_acceptance_paths_are_guarded() -> None:
    _assert_contains(
        "apps/shell/yachiyo_agent/contracts.py",
        [
            "class MemoryTraceSnapshot",
            "class SkillTraceSnapshot",
            "memory_traces: list[MemoryTraceSnapshot]",
            "skill_traces: list[SkillTraceSnapshot]",
            "class SkillSnapshot",
            "class MemorySnapshot",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/legacy_event_pages.py",
        [
            "def is_replay_enrichment_event",
            '"memory.",',
            '"skill.",',
            "def run_with_replay_events",
            "def run_event_page_from_legacy_stream",
        ],
    )
    _assert_contains(
        "apps/shell/yachiyo_agent/trace_snapshots.py",
        [
            "def memory_trace_snapshot_from_event",
            "def skill_trace_snapshot_from_event",
            "MemoryTraceSnapshot",
            "SkillTraceSnapshot",
            "event.sensitivity == \"secret\"",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "MemorySkillTraceInspector",
            "const timelineMemoryTraces = selectedPublicRunTimeline?.memory_traces || [];",
            "const timelineSkillTraces = selectedPublicRunTimeline?.skill_traces || [];",
            "events={memorySkillTraceEvents}",
            "memoryTraces={timelineMemoryTraces}",
            "skillTraces={timelineSkillTraces}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/MemorySkillTraceInspector.tsx",
        [
            "testId = 'agent-run-detail-memory-skill-traces'",
            "itemTestId = 'agent-run-detail-memory-skill-trace'",
            "memorySkillTraceFromMemorySnapshot",
            "memorySkillTraceFromSkillSnapshot",
            "memorySkillTraceFromEvent",
            "publicRunEventIsSecret",
            "eventType.startsWith('memory.')",
            "eventType.startsWith('skill.')",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeTimelineSummary.tsx",
        [
            "type.startsWith('skill.dispatch.')",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_run_detail_ui.mjs",
        [
            "memory.retrieved",
            "skill.dispatch.read",
            'data-testid="agent-run-detail-memory-skill-trace"',
            "data-runtime-trace-kind",
            "run detail memory skill trace replay verified",
        ],
    )


def test_legacy_agents_compatibility_acceptance_path_is_guarded() -> None:
    _assert_contains(
        "apps/bridge/routes/agents.py",
        [
            'router = APIRouter(prefix="/ui", tags=["Agent Studio"])',
            '@router.get("/agents")',
            '@router.post("/agents")',
            "get_agent_runtime_service",
            "list_agents",
            "list_run_groups",
            "rerun_run",
        ],
    )
    _assert_contains(
        "tests/test_yachiyo_routes.py",
        [
            "legacy_agents_source",
            'APIRouter(prefix="/ui", tags=["Agent Studio"])',
            "assert '@router.get(\"/agents\")' in legacy_agents_source",
            "assert '@router.post(\"/agents\")' in legacy_agents_source",
            "assert '@router.get(\"/tasks\")' in source",
            "assert \"return await yachiyo_chat_handlers.start_task(request, http_request)\" in source",
        ],
    )
    _assert_contains(
        "tests/test_bridge_server.py",
        [
            "test_agent_studio_crud_http_routes_use_app_runtime_service",
            'client.get("/ui/agents")',
            'assert responses[0].json() == {"agents": [{"agent_id": "agent-1"}]}',
            'assert responses[1].json() == {"agent_id": "agent-1", "name": "Agent 1"}',
            'assert responses[6].json() == {"ok": True, "agent_id": "agent-1", "skill_id": "skill-1"}',
        ],
    )


def test_agent_studio_view_preservation_acceptance_path_is_guarded() -> None:
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "AgentDefinitionsTab",
            "AgentStudioGroupsTab",
            "AgentStudioRunsTab",
            "AgentStudioWorkflowsTab",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "ToolCallInspector",
            "ApprovalInspector",
            "ArtifactInspector",
            "PlannerTraceInspector",
            "RunTimeline",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_studio_agents_ui.mjs",
        [
            'data-testid="agent-studio-agents"',
            "agent updated",
            "agent deleted",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_studio_groups_ui.mjs",
        [
            'data-testid="agent-studio-groups"',
            "group run detail verified",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_workflow_management_ui.mjs",
        [
            'data-testid="workflow-list-manage"',
            "workflow management delete paths rendered",
        ],
    )
    _assert_smoke_script(
        "scripts/smoke_agent_run_detail_ui.mjs",
        [
            'data-testid="agent-run-detail-approval"',
            "artifact preview rendered",
            "run detail memory skill trace replay verified",
        ],
    )
