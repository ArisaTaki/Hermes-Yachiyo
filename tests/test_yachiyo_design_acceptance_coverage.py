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
