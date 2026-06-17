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
                ("startYachiyoTask({", "source: 'chat'", "pollAgentRunInBackground(task.task_id);"),
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
                ("MessageAgentTaskCard", "publicTaskSnapshotForMessage"),
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
                ("ApprovalCard", "mergeApprovalSnapshots", "approvalFacts.slice(0, 2).map((approval)"),
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
                ("AgentDefinitionsTab", "AgentGroupPanel", "RunManagementTab", "WorkflowCanvas"),
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
            "pollAgentRunInBackground(task.task_id);",
            "return true;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "MessageAgentTaskCard",
            "publicTaskSnapshotForMessage",
            "onOpenStudio={onOpenRunDetails}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
        [
            "ApprovalCard",
            "mergeApprovalSnapshots",
            "onApproveApproval(task, approval)",
            "onRejectApproval(task, approval)",
            'data-testid="yachiyo-task-approval-open-studio"',
            "approval.open_in_studio_url",
            "ArtifactPreview",
            "ToolCallSummary",
            "在 Agent Studio 中查看",
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
    _assert_smoke_script(
        "scripts/smoke_chat_public_task_ui.mjs",
        [
            "/yachiyo/tasks",
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
            "readYachiyoRunArtifact(sourceRunId, artifactPath)",
            "readYachiyoTaskArtifact(taskId, artifactPath)",
            'previewVariant="compact"',
            'previewTestId="yachiyo-task-artifact-preview"',
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
            "source: 'launcher'",
            "launcher_mode: mode,",
            "LauncherAgentTaskLight",
            "onApproveTaskApproval={launcher.approveAgentTaskApproval}",
            "onCancelTask={launcher.cancelAgentTask}",
            "onRejectTaskApproval={launcher.rejectAgentTaskApproval}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/launcherTasks.ts",
        [
            "launcherPreferredActiveTask",
            "task.status === 'waiting_approval') return 0;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/LauncherView.tsx",
        [
            "launcherAgentTaskIsActive(publicAgentTask || data?.chat?.agent_task)",
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
            "live2d-launcher-agent-task-reject",
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
            "AgentGroupPanel",
            "RunManagementTab",
            "WorkflowCanvas",
            "WorkflowRunPreview",
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
            "RunTimeline",
            "selectedRunReplayEvents",
            'data-testid="agent-run-detail-rerun-source"',
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
            "onOpenArtifact={onOpenArtifact}",
            'data-testid="agent-run-detail-group-run-replay"',
            'data-testid="agent-run-detail-group-run-approvals"',
            'data-testid="agent-run-detail-group-run-artifacts"',
            'itemTestId="agent-run-detail-group-run-artifact-item"',
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
            "task.created",
            "model.requested",
            "model.completed",
            "workflow.started",
            "workflow.paused_for_approval",
            "workflow.resumed",
            "workflow.completed",
            "workflow.failed",
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
        "apps/shell/yachiyo_agent/legacy_ports.py",
        [
            "def _is_replay_enrichment_event",
            '"memory.",',
            '"skill.",',
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
            'data-testid="agent-run-detail-memory-skill-traces"',
            'data-testid="agent-run-detail-memory-skill-trace"',
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
            "AgentGroupPanel",
            "RunManagementTab",
            "WorkflowCanvas",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "ToolCallInspector",
            "ApprovalInspector",
            "ArtifactInspector",
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
