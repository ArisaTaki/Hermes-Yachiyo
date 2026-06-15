"""Frontend feature-preservation smoke tests.

These tests intentionally check source-level entry points because the project
does not yet have a browser E2E runner. They guard the v0.5 rule that Hermes
execution-kernel cleanup must not delete mature UI surfaces.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(relative_path: str, fragments: list[str]) -> None:
    text = _read(relative_path)
    missing = [fragment for fragment in fragments if fragment not in text]
    assert not missing, f"{relative_path} is missing preserved feature fragments: {missing!r}"


def _assert_not_contains(relative_path: str, fragments: list[str]) -> None:
    text = _read(relative_path)
    present = [fragment for fragment in fragments if fragment in text]
    assert not present, f"{relative_path} contains forbidden fragments: {present!r}"


def _assert_occurs(relative_path: str, fragment: str, expected_count: int) -> None:
    text = _read(relative_path)
    actual = text.count(fragment)
    assert actual == expected_count, (
        f"{relative_path} expected {fragment!r} to occur {expected_count} times, got {actual}"
    )


def _extract_async_function(text: str, name: str) -> str:
    match = re.search(rf"(?:export\s+)?async function {re.escape(name)}\b", text)
    assert match, f"missing async function {name}"
    body_start = _find_function_body_start(text, match.end())
    depth = 0
    for index in range(body_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]
    raise AssertionError(f"unterminated exported async function {name}")


def _find_function_body_start(text: str, start: int) -> int:
    paren_depth = 0
    angle_depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "<" and paren_depth == 0:
            angle_depth += 1
        elif char == ">" and angle_depth > 0:
            angle_depth -= 1
        elif char == "{" and paren_depth == 0 and angle_depth == 0:
            return index
    raise AssertionError("missing function body")


def _assert_function_contains(relative_path: str, function_name: str, fragments: list[str]) -> None:
    body = _extract_async_function(_read(relative_path), function_name)
    missing = [fragment for fragment in fragments if fragment not in body]
    assert not missing, f"{relative_path}:{function_name} is missing fragments: {missing!r}"


def test_frontend_preserves_top_level_product_routes_and_navigation() -> None:
    _assert_contains(
        "apps/frontend/src/lib/view.ts",
        [
            "| 'chat'",
            "| 'agents'",
            "| 'settings'",
            "| 'provider'",
            "| 'diagnostics'",
            "| 'tools'",
            "| 'activity-all'",
            "| 'activity-detail'",
            "| 'app-update'",
            "| 'proactive-tts'",
            "| 'bubble'",
            "| 'bubble-menu'",
            "| 'live2d'",
            "['agents', 'groups', 'skills', 'skill-groups', 'workflows', 'runs', 'memory']",
        ],
    )
    _assert_contains(
        "apps/frontend/src/App.tsx",
        [
            "const ChatView = lazy(",
            "const AgentStudioView = lazy(",
            "const DiagnosticsView = lazy(",
            "const ModeSettingsView = lazy(",
            "const ModelProfilesView = lazy(",
            "const ProactiveTtsSettingsView = lazy(",
            "const ToolCenterView = lazy(",
            "const AppUpdateView = lazy(",
            "const LauncherView = lazy(",
            "if (view === 'chat') page = <ChatView />;",
            "else if (view === 'agents') page = <AgentStudioView />;",
            "else if (view === 'proactive-tts') page = <ProactiveTtsSettingsView />;",
            "else if (view === 'live2d') page = null;",
            "<Live2DModePage active={view === 'live2d'} />",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/OpenDesignView.tsx",
        [
            "{ view: 'chat', label: '对话'",
            "{ view: 'agents', label: 'Agent Studio'",
            "{ view: 'bubble', label: '气泡模式'",
            "{ view: 'live2d', label: 'Live2D 模式'",
            "{ view: 'proactive-tts', label: '主动关怀'",
            "{ view: 'tools', label: '能力中心'",
            "{ view: 'diagnostics', label: '诊断详情'",
        ],
    )


def test_launcher_views_expose_session_summary_e2e_selectors() -> None:
    _assert_contains(
        "apps/frontend/src/views/launcherTypes.ts",
        [
            "import type { AgentTaskSnapshot } from '../features/yachiyo-chat/types';",
            "export type LauncherRecentSession",
            "recent_sessions?: LauncherRecentSession[];",
            "latest_task_id?: string;",
            "agent_task?: AgentTaskSnapshot | null;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/LauncherView.tsx",
        [
            "launcherRecentSessions(data?.chat)",
            "latestLauncherSessionSummary(data?.chat)",
            "LauncherAgentTaskLight",
            "launcherAgentTaskRunId",
            "launcherAgentTaskChatParams",
            "launcherAgentTaskSummary(agentTask)",
            'data-testid="bubble-launcher-shell"',
            'data-testid="bubble-launcher-button"',
            'data-testid="bubble-launcher-status-dot"',
            'data-testid="bubble-launcher-summary"',
            'data-testid={`${mode}-launcher-agent-task-light`}',
            'data-testid={`${mode}-launcher-agent-task-open-chat`}',
            'data-testid={`${mode}-launcher-agent-task-open-studio`}',
            'data-testid="live2d-launcher-shell"',
            'data-testid="live2d-launcher-stage"',
            'data-testid="live2d-launcher-canvas"',
            'data-testid="live2d-launcher-preview-fallback"',
            'data-testid="live2d-launcher-resource-hint"',
            'data-testid="live2d-launcher-resource-hint-text"',
            'data-testid="live2d-launcher-resource-hint-close"',
            'data-testid="live2d-launcher-reply"',
            'data-testid="live2d-launcher-reply-text"',
            'data-testid="live2d-launcher-quick-input"',
            'data-testid="live2d-launcher-quick-input-field"',
            'data-testid="live2d-launcher-quick-input-submit"',
            "LAUNCHER_SUMMARY_TEST_IDS[mode]",
            "sessionSummaryProbe: 'bubble-launcher-session-summary-probe'",
            "latestReply: 'bubble-launcher-latest-reply'",
            "statusLabel: 'bubble-launcher-status-label'",
            "recentSession: 'bubble-launcher-recent-session'",
            "sessionSummaryProbe: 'live2d-launcher-session-summary-probe'",
            "latestReply: 'live2d-launcher-latest-reply'",
            "statusLabel: 'live2d-launcher-status-label'",
            "recentSession: 'live2d-launcher-recent-session'",
            "const params = launcherChatOpenParams(data, sessionId);",
            "function launcherChatOpenParams(data: LauncherPayload | null, sessionId: string): Record<string, string> | undefined",
            "if (conversationKind) params.conversation_kind = conversationKind;",
            "if (latestTaskId) params.task_id = latestTaskId;",
            "await openAppView('chat', params);",
            "void openAppView('chat', launcherAgentTaskChatParams(task));",
            "void openAppView('agents', { run: runId });",
            "data-session-id={session.session_id || ''}",
            "data-task-id={session.latest_task_id || ''}",
        ],
    )


def test_chat_ui_preserves_sessions_groups_attachments_and_approval_paths() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "apiGet<MessagesPayload>(`/ui/chat/messages?",
            "apiGet<SessionsPayload>(`/ui/chat/sessions?",
            "apiPost<",
            "'/ui/chat/messages'",
            "'/ui/chat/session/clear'",
            "'/ui/chat/session/delete'",
            "'/ui/chat/session/discard-empty'",
            "'/ui/chat/sessions/load'",
            "const [routeTaskId, setRouteTaskId] = useState(() => currentParam('task_id').trim());",
            "setRouteTaskId(currentParam('task_id').trim());",
            "const requestedTaskId = routeTaskId;",
            "const messageId = taskHandoffMessageId(messagePayload.messages, requestedTaskId);",
            "function taskHandoffMessageId(messages: ChatMessage[], taskId: string)",
            "function messageMatchesTaskHandoff(message: ChatMessage, taskId: string)",
            "stringValue(metadata.group_agent_summary_task_id) === taskId",
            "stringValue(metadata.delegated_run_source_task_id) === taskId",
            "metadataListAttribute(metadata.group_followup_for_task_ids).split(',').includes(taskId)",
            "client_message_id",
            "startYachiyoTask({",
            "yachiyoPublicTaskTarget(text, runnables, assistantProfile)",
            "agent_id: publicTaskTarget.id",
            "source: 'chat'",
            "attachments: outgoingAttachments",
            "canAttachImages(executor)",
            "onPaste={(event) => void handlePaste(event)}",
            "clipboardImageFiles(event.clipboardData)",
            "await addImageFiles(files)",
            "Promise.all(accepted.map(readPendingAttachment))",
            "loadImageDimensions(dataUrl)",
            "dimensions.width < 16 || dimensions.height < 16",
            "setStatus(next.length > 1 ? `已添加 ${next.length} 张图片附件` : '已添加图片附件')",
            "aria-label=\"添加附件，当前仅支持图片\"",
            "type=\"file\"",
            "accept=\"image/*\"",
            "listRunnables()",
            "const [sessionTab, setSessionTab] = useState<'agents' | 'groups'>('agents');",
            "apiPost<{",
            "`/ui/chat/groups/${encodeURIComponent(currentSessionId)}`",
            "'/ui/chat/groups'",
            "'/ui/chat/delegated-run-summary'",
            "approveRunApproval(runId)",
            "rejectRunApproval(runId, 'Rejected from chat')",
            "className=\"composer-approval-notice\"",
            "className=\"composer-approval-actions\"",
            "approvalId={composerApprovalItem.approvalId}",
            "itemId={composerApprovalItem.id}",
            "source={composerApprovalItem.source}",
            "className=\"approve\"",
            "className=\"reject\"",
            "onClick={onApprove}",
            "onClick={onReject}",
            "openRunDetails(runId",
            "openWorkflowStudio(runnableId",
            "group_dispatch_count",
            "group_agent_summary_pending",
        ],
    )


def test_chat_group_ui_exposes_stable_e2e_selectors() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            'data-testid="chat-session-tab-agents"',
            'data-testid="chat-session-tab-groups"',
            'data-testid="chat-session-tab-create"',
            'data-testid="chat-group-settings"',
            'data-testid="chat-group-dialog"',
            'data-testid="chat-group-dialog-close"',
            'data-testid="chat-group-avatar-preview"',
            'data-testid="chat-group-avatar-clear"',
            'data-testid="chat-group-avatar-file-input"',
            'data-testid="chat-group-name-input"',
            'data-testid="chat-group-avatar-select"',
            'data-testid="chat-group-avatar-clear-secondary"',
            'data-testid="chat-group-dialog-error"',
            'data-testid="chat-group-member-list"',
            'data-testid="chat-group-main-member"',
            'data-testid="chat-group-agent-member"',
            'data-testid="chat-group-agent-member-checkbox"',
            'data-testid="chat-group-dialog-cancel"',
            'data-testid="chat-group-dialog-submit"',
            'data-testid="chat-composer-input"',
            'data-testid="chat-composer-send"',
        ],
    )


def test_chat_group_summary_ui_smoke_uses_group_create_send_and_summary_status() -> None:
    smoke_script = "scripts/smoke_chat_group_summary_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/chat",
            "request.method === 'POST' && url.pathname === '/ui/chat/groups'",
            "request.method === 'POST' && url.pathname === '/ui/chat/messages'",
            "request.method === 'POST' && url.pathname === '/__smoke/complete-group-summary'",
            "data-testid=\"chat-session-tab-groups\"",
            "data-testid=\"chat-session-tab-create\"",
            "data-testid=\"chat-group-dialog\"",
            "data-testid=\"chat-group-avatar-file-input\"",
            "data-testid=\"chat-group-avatar-select\"",
            "data-testid=\"chat-group-avatar-clear-secondary\"",
            "data-testid=\"chat-group-agent-member-checkbox\"",
            "data-testid=\"chat-group-dialog-submit\"",
            "data-testid=\"chat-composer-input\"",
            "data-testid=\"chat-composer-send\"",
            "data-testid=\"chat-message-summary-status\"",
            "data-testid=\"chat-message-followup-status\"",
            "data-testid=\"chat-message-activity-open-run-detail\"",
            "data-testid=\"chat-message-open-run-detail\"",
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"agent-run-detail-execution-event\"",
            "group_agent_summary_task_id",
            "group_agent_summary_pending",
            "group_agent_summary_status: summaryCompleted ? 'completed' : 'processing'",
            "group_dispatch_run_group_id",
            "GROUP_SUMMARY_RUN_ID",
            "GROUP_SUMMARY_RESULT",
            "GROUP_FOLLOWUP_TEXT",
            "GROUP_AVATAR_DATA_URL",
            "group avatar picker fallback targets file input",
            "new File([blob], 'group-avatar.svg', { type: 'image/svg+xml' })",
            "group avatar preview rendered",
            "group avatar cleared",
            "group avatar was not submitted as a data URL",
            "chat-group-ui-main-summary-message",
            "chat-group-ui-followup-message",
            "url.pathname === `/ui/runs/${GROUP_SUMMARY_RUN_ID}`",
            "url.pathname === `/yachiyo/studio/runs/${GROUP_SUMMARY_RUN_ID}/events`",
            "group_followup_for_task_ids",
            "group_followup_for_agent_message_ids",
            "data-summary-tone') === 'completed'",
            "data-summary-status') === 'completed'",
            "loadChat(win, {",
            "conversation_kind: 'group'",
            "task_id: ${JSON.stringify(SUMMARY_TASK_ID)}",
            "summaryMessage?.className.includes('search-highlighted')",
            "launcher task handoff highlighted group summary",
            "data-followup-task-ids') === ${JSON.stringify(GROUP_AGENT_TASK_ID)}",
            "data-followup-agent-message-ids') === 'chat-group-ui-agent-summary-message'",
            "group follow-up status rendered",
            "GROUP_AGENT_RUN_ID",
            "run_id: GROUP_AGENT_RUN_ID",
            "row?.getAttribute('data-run-id') === ${JSON.stringify(GROUP_AGENT_RUN_ID)}",
            "row?.getAttribute('data-run-status') === 'completed'",
            "openRun?.getAttribute('data-run-id') === ${JSON.stringify(GROUP_AGENT_RUN_ID)}",
            "openRun?.getAttribute('data-run-status') === 'completed'",
            "url.pathname === `/ui/runs/${GROUP_AGENT_RUN_ID}`",
            "url.pathname === `/yachiyo/studio/runs/${GROUP_AGENT_RUN_ID}/events`",
            "run.completed",
            "agent.run.completed",
            "outputEvent?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})",
            "completedEvent?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})",
            "outputEvent?.textContent.includes(${JSON.stringify(GROUP_AGENT_RESULT)})",
            "completedEvent?.textContent.includes(${JSON.stringify(GROUP_AGENT_RESULT)})",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(GROUP_AGENT_TASK_ID)}",
            "detail?.getAttribute('data-session-id') === ${JSON.stringify(GROUP_SESSION_ID)}",
            "data-run-event-run-id",
            "group summary Run Detail replay verified",
            "!document.body.textContent.includes('oha.group_dispatch')",
            "!document.body.textContent.includes('<oha_group_dispatch>')",
            "!document.body.textContent.includes('run_oha_agent')",
            "assertMockBridgeContract",
            "messagePayload.client_message_id",
            "followupPayload.client_message_id",
            "bridgeState.currentSessionId !== GROUP_SESSION_ID",
        ],
    )


def test_chat_renders_yachiyo_agent_task_card_entrypoint() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "AgentTaskCard",
            "approveYachiyoTask",
            "rejectYachiyoTask",
            "cancelYachiyoTask",
            "getYachiyoTask",
            "listYachiyoTasks",
            "from '../features/yachiyo-chat/taskSnapshots';",
            "resolveYachiyoTaskApproval(task, approval, 'approve')",
            "resolveYachiyoTaskApproval(task, approval, 'reject')",
            "cancelYachiyoTaskFromCard",
            "approveYachiyoTask(task.task_id, approval.approval_id)",
            "rejectYachiyoTask(task.task_id, approval.approval_id, 'Rejected from chat task card')",
            "cancelYachiyoTask(task.task_id)",
            "publicTaskSnapshotForMessage(message, agentTaskSnapshotsById)",
            "refreshYachiyoTasksForSession(payload.current_session_id)",
            "refreshYachiyoTaskById(resultRunId)",
            "agentTaskSnapshotFromMessage(message, displayContent)",
            "onOpenStudio={onOpenRunDetails}",
            "onApproveApproval={onApproveTaskApproval}",
            "onRejectApproval={onRejectTaskApproval}",
            "onCancelTask={onCancelTask}",
        ],
    )
    _assert_not_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "function agentTaskSnapshotFromMessage",
            "function publicTaskSnapshotForMessage",
            "function yachiyoTaskCacheKeys",
            "function yachiyoTaskRunId",
            "function yachiyoTaskStatusMessage",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/taskSnapshots.ts",
        [
            "export function agentTaskSnapshotFromMessage",
            "export function publicTaskSnapshotForMessage",
            "export function yachiyoTaskCacheKeys",
            "export function yachiyoTaskRunId",
            "export function yachiyoTaskStatusMessage",
            "pending_approvals: messageTaskApprovals(message, runId)",
            "recent_events: messageTaskEvents(message, runId)",
            "artifacts: messageTaskArtifacts(message, runId)",
            "open_in_studio_url: `#/agents?run_id=${encodeURIComponent(runId)}`",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx",
        [
            'data-testid="yachiyo-agent-task-card"',
            'data-testid="yachiyo-agent-task-open-studio"',
            'data-testid="yachiyo-agent-task-cancel"',
            'data-testid="yachiyo-task-approval-approve"',
            'data-testid="yachiyo-task-approval-reject"',
            'testId="yachiyo-agent-task-timeline"',
            "<ApprovalCard actions={actions}",
            "onApproveApproval(task, approval)",
            "onRejectApproval(task, approval)",
            "onCancelTask?.(task)",
            "RuntimeTimelineSummary",
            "在 Agent Studio 中查看",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/ApprovalCard.tsx",
        [
            "RuntimeApprovalCard",
            "actions={actions}",
            'actionsTestId="yachiyo-task-approval-actions"',
            'testId="yachiyo-task-approval-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/components/ArtifactPreview.tsx",
        [
            "RuntimeArtifactPreview",
            'testId="yachiyo-task-artifact-preview"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeApprovalCard.tsx",
        [
            "export function RuntimeApprovalCard",
            "actions?: ReactNode;",
            "actionsClassName = 'runtime-approval-actions'",
            "actionsTestId = 'runtime-approval-actions'",
            "approvalPreviewRecord",
            "data-approval-id={approval.approval_id}",
            "data-testid={actionsTestId}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeArtifactPreview.tsx",
        [
            "export function RuntimeArtifactPreview",
            "data-artifact-id={artifact.artifact_id}",
            "data-artifact-path={artifact.path || ''}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeTimelineSummary.tsx",
        [
            "export function RuntimeTimelineSummary",
            "export type RuntimeTimelineEventSnapshot",
            "RuntimeTimelineEventList",
            "eventTestId={`${testId}-event`}",
            "variant=\"compact\"",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeTimelineEventList.tsx",
        [
            "export function RuntimeTimelineEventList",
            "variant = 'compact'",
            "variant === 'full'",
            "ExpandableRuntimeContent",
            "data-testid={eventTestId}",
            "data-run-event={eventName}",
            "data-run-event-run-id={eventRunId}",
            "data-run-event-sequence={eventSequence}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-chat/api.ts",
        [
            "/yachiyo/tasks",
            "/yachiyo/readiness",
            "approveYachiyoTask",
            "rejectYachiyoTask",
            "cancelYachiyoTask",
        ],
    )


def test_agent_studio_exposes_yachiyo_public_group_entrypoint() -> None:
    _assert_contains(
        "apps/frontend/src/features/yachiyo-studio/api.ts",
        [
            "/yachiyo/studio/agents",
            "/yachiyo/studio/skills",
            "/yachiyo/studio/skills/sources",
            "/yachiyo/studio/skills/import",
            "/yachiyo/studio/skills/sync",
            "/yachiyo/studio/skills/install",
            "/yachiyo/studio/skill-folders",
            "/yachiyo/studio/memories",
            "/yachiyo/studio/groups",
            "/yachiyo/studio/group-runs",
            "/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}/runs",
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/timeline",
            "listYachiyoStudioAgents",
            "saveYachiyoStudioAgent",
            "deleteYachiyoStudioAgent",
            "listYachiyoSkills",
            "updateYachiyoSkill",
            "deleteYachiyoSkill",
            "listYachiyoSkillFolders",
            "createYachiyoSkillFolder",
            "updateYachiyoSkillFolder",
            "deleteYachiyoSkillFolder",
            "listYachiyoSkillSources",
            "importYachiyoSkill",
            "syncYachiyoNativeSkills",
            "installYachiyoSkillCommand",
            "listYachiyoMemories",
            "createYachiyoMemory",
            "updateYachiyoMemory",
            "deleteYachiyoMemory",
            "listYachiyoAgentGroups",
            "saveYachiyoAgentGroup",
            "startYachiyoGroupRun",
            "listYachiyoGroupRuns",
            "getYachiyoGroupRun",
            "getYachiyoRunTimeline",
            "startYachiyoWorkflowRun",
            "deleteYachiyoWorkflow",
            "function createClientRunId()",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/features/yachiyo-studio/api.ts",
        "startYachiyoGroupRun",
        [
            "const clientRunId = createClientRunId();",
            "/yachiyo/studio/groups/${encodeURIComponent(groupId)}/runs",
            "client_run_id: clientRunId",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/features/yachiyo-studio/api.ts",
        "startYachiyoWorkflowRun",
        [
            "const clientRunId = createClientRunId();",
            "/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}/runs",
            "client_run_id: clientRunId",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/yachiyo-studio/types.ts",
        [
            "export type AgentDefinitionSnapshot",
            "export type SkillSnapshot",
            "export type SkillFolderSnapshot",
            "export type SkillSourceRootSnapshot",
            "export type MemorySnapshot",
            "export type AgentGroupSnapshot",
            "export type GroupRunSnapshot",
            "export type PublicRunEvent",
            "export type ToolCallSnapshot",
            "export type RunTimelineSnapshot",
            "export type ApprovalCardSnapshot",
            "export type ArtifactSnapshot",
            "tool_calls?: ToolCallSnapshot[];",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/studioTabs.tsx",
        [
            "export type StudioTab = 'agents' | 'groups' | 'skills' | 'skill-groups' | "
            "'workflows' | 'runs' | 'memory';",
            "export const studioTabs: StudioTab[] = [",
            "export function normalizeStudioTab",
            "export function isStudioTopTabActive",
            "export function studioTabLabel",
            "export function AgentStudioLoadingState",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "from '../features/agent-studio/studioTabs';",
            "isStudioTopTabActive(tab, item)",
            "studioTabLabel(item)",
            "AgentGroupPanel",
            "useAgentDefinitions",
            "useAgentGroups",
            "useApprovedRunGuard",
            "useRunApprovalActions",
            "useRunApprovalFollowup",
            "useRunEventReplay(selectedRunId, selectedRunReplayRefreshKey)",
            "useRunTimeline(selectedRunId, selectedRunReplayRefreshKey)",
            "useWorkflowDefinitions",
            "RunDetailPanel",
            "selectedPublicRunTimeline={selectedPublicRunTimeline}",
            "selectedRunArtifacts",
        ],
    )
    _assert_not_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "function AgentStudioLoadingState",
            "function normalizeStudioTab",
            "const studioTabs: StudioTab[]",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentDefinitions.ts",
        [
            "export function useAgentDefinitions",
            "applyAgents",
            "selectedAgentReadOnly",
            "selectedAgentDeletable",
            "toggleAgentSelected",
            "finishAgentManagement",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentGroups.ts",
        [
            "export function useAgentGroups",
            "listYachiyoAgentGroups().catch(() => [])",
            "saveYachiyoAgentGroup",
            "startYachiyoGroupRun",
            "runAgentGroup",
            "saveAgentGroupDraft",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunTimeline.ts",
        [
            "export function useRunTimeline",
            "getYachiyoRunTimeline(runId)",
            "selectedPublicRunTimeline",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunEventReplay.ts",
        [
            "export function useRunEventReplay",
            "getRunEvents(runId, 0, pageSize)",
            "mergeRunEventReplayPages(previous?.events || currentEvents, incomingEvents)",
            "clearRunEventReplay",
            "selectedReplayEvents",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useApprovedRunGuard.ts",
        [
            "export function useApprovedRunGuard",
            "const approvedApprovalStaleWindowMs = 6000;",
            "runApprovalSignature(run)",
            "normalizeRunStatus(run.status) !== 'approval_required'",
            "approvedApprovalGuardsRef.current.delete(run.run_id)",
            "nextRuns.filter((run) => shouldAcceptRunUpdate(run))",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunApprovalFollowup.ts",
        [
            "export function useRunApprovalFollowup",
            "const selectedRunIdRef = useRef(selectedRunId);",
            "selectedRunIdRef.current = selectedRunId;",
            "const runApprovalPollAttempts = 100;",
            "window.setTimeout(resolve, attempt === 0 ? 300 : runApprovalPollIntervalMs)",
            "getRun(id).catch(() => null)",
            "const visibleRuns = acceptedRunUpdates(loadedRuns);",
            "await refreshRunGroupsForRuns(visibleRuns);",
            "normalizeRunStatus(watchedRun.status)",
            "setStatus('Run 需要处理下一次审批。');",
            "setStatus(approvedRunStatusMessage(watchedRun));",
            "await refresh(approvalFollowupRefreshOptions(selectedAfterAction));",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunApprovalActions.ts",
        [
            "export function useRunApprovalActions",
            "const approveRunById = useCallback(async (",
            "const approvalRequest = approveRunApproval(runId);",
            "void pollApprovedRunProgress(runId, selectedAfterAction)",
            "updatedRuns.push(await getRun(nextSelectedRunId));",
            "await refreshRunGroupsForRuns(updatedRuns);",
            "const rejectRunById = useCallback(async (",
            "const run = await rejectRunApproval(runId);",
            "const cancelRunById = useCallback(async (",
            "const run = await cancelRun(runId);",
            "statusMessage: nextSelectedRunId ? '已取消子 Run，Workflow 已终止。' : 'Run 已取消。'",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useWorkflowDefinitions.ts",
        [
            "export function useWorkflowDefinitions",
            "applyWorkflows",
            "selectedWorkflow",
            "toggleWorkflowSelected",
            "finishWorkflowManagement",
            "allWorkflowsSelected",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/types.ts",
        [
            "export type AgentDraft",
            "model_mode: 'profile' | 'custom_api';",
            "allow_workspace_write: boolean;",
            "output_contract: string;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/agents.ts",
        [
            "import type { AgentDraft } from '../types';",
            "export function agentToDraft",
            "export function draftToolPolicy",
            "export function agentRunReadinessIssue",
            "export function runnableCapabilityLine",
            "export function agentCapabilityLine",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/skills.ts",
        [
            "export type SkillSourceFilter",
            "export function skillMatchesSourceFilter",
            "export function skillMatchesFolderFilter",
            "export function skillFolderNameError",
            "export const skillFolderNameMaxLength",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/groups.ts",
        [
            "export function agentGroupListMeta",
            "export function agentGroupMemberSummary",
            "export function nextSelectedAgentGroupId",
            "export function buildAgentGroupSaveRequest",
            "export function groupRunTimelineRunId",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/runs.ts",
        [
            "export type RunKindFilter",
            "export type RunStatusFilter",
            "export function runHistoryGroupsFor",
            "export function runMatchesSearch",
            "export function publicRunEventToTimelineEvent",
            "export function publicArtifactsOrLegacy",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/workflow.ts",
        [
            "export type WorkflowStepRef",
            "export type WorkflowValidationReport",
            "const workflowNodeTypes = new Set(['start', 'agent', 'approval', 'artifact', 'condition', 'parallel', 'workflow', 'loop']);",
            "export const workflowRunnableStepRequiredMessage",
            "export function validateWorkflowDraft",
            "export function workflowSpecStepRefs",
            "export function workflowStepRefs",
            "export function workflowRunHasChildRun",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            'data-testid="agent-run-detail-public-timeline"',
            "Public Runtime Snapshot",
            "RunTimelineSnapshot · Approval · Artifact · Events",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentGroupPanel.tsx",
        [
            'data-testid="agent-studio-groups"',
            'data-testid="agent-group-member-picker"',
            "GroupRunPanel",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/GroupRunPanel.tsx",
        [
            'data-testid="agent-group-run-panel"',
            'data-testid="agent-group-run"',
            'data-testid="agent-group-open-run"',
            "打开 Run Timeline",
        ],
    )


def test_agent_studio_uses_extracted_runtime_shared_components() -> None:
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "RunDetailPanel",
            "RunLauncherPanel",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunLauncherPanel.tsx",
        [
            "RunHistoryList",
            "Run Agent / Workflow",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "ApprovalInspector",
            "RunApprovalRequest",
            "RunTimeline",
            "ExpandableRuntimeContent as RunExpandableContent",
            "ArtifactInspector",
            "ToolCallInspector",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ApprovalInspector.tsx",
        [
            "export function ApprovalInspector",
            "RuntimeApprovalCard",
            "RunApprovalRequest",
            "agent-run-detail-approval",
            'actionsClassName="run-approval-actions"',
            'actionsTestId="agent-run-detail-approval-actions"',
            'testId="agent-run-detail-approval-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ArtifactInspector.tsx",
        [
            "export function ArtifactInspector",
            "RuntimeArtifactPreview",
            "agent-run-detail-artifact",
            'testId="agent-run-detail-artifact-preview-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ToolCallInspector.tsx",
        [
            "export function ToolCallInspector",
            "RuntimeToolCallCard",
            "agent-run-detail-tool-calls",
            'testId="agent-run-detail-tool-call-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeToolCallCard.tsx",
        [
            "export function RuntimeToolCallCard",
            "data-tool-call-id={toolCall.tool_call_id}",
            "data-tool-status={toolCall.status}",
            "approvalPreviewRecord",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunApprovalRequest.tsx",
        [
            'data-testid="agent-run-approval-request"',
            "approvalPreviewRecord",
            "formatApprovalInput",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunHistoryList.tsx",
        [
            "export function RunHistoryList",
            'data-testid="agent-run-history-row"',
            'data-testid="agent-run-history-open-run"',
            'data-testid="agent-run-history-select-run"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunTimeline.tsx",
        [
            "RuntimeTimelineEventList",
            'eventTestId="agent-run-detail-execution-event"',
            'childRunTestId="agent-run-detail-execution-open-child-run"',
            'testId="agent-run-detail-execution-events"',
            'data-testid="agent-run-detail-load-more-events"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/approval.ts",
        [
            "approvalPreviewRecord",
            "approvalPreviewValue",
            "formatApprovalInput",
        ],
    )


def test_chat_delegated_summary_ui_smoke_uses_activity_approval_summary_and_run_detail() -> None:
    smoke_script = "scripts/smoke_chat_delegated_summary_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/chat",
            "data-testid=\"chat-composer-approval-notice\"",
            "data-approval-source') === 'activity'",
            "data-testid=\"chat-composer-approval-open-run-detail\"",
            "data-testid=\"chat-composer-approval-approve\"",
            "data-testid=\"chat-composer-approval-reject\"",
            "data-testid=\"chat-message-activity-open-run-detail\"",
            "data-testid=\"chat-message-open-run-detail\"",
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"agent-run-detail-execution-event\"",
            "SUMMARY_RUN_ID",
            "request.method === 'POST' && url.pathname === `/ui/runs/${DELEGATED_RUN_ID}/approval/approve`",
            "request.method === 'POST' && url.pathname === `/ui/runs/${DELEGATED_RUN_ID}/approval/reject`",
            "request.method === 'POST' && url.pathname === '/ui/chat/delegated-run-summary'",
            "summaryRequests.map((request) => request.status).join(',')",
            "agent.tool.approval_required",
            "agent.tool.approval_approved",
            "agent.tool.approval_rejected",
            "agent.run.cancelled",
            "agent.run.completed",
            "run.completed",
            "outputEvent?.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})",
            "completedEvent?.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})",
            "outputEvent?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})",
            "completedEvent?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(SOURCE_TASK_ID)}",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}",
            "detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}",
            "loadChat(win, {",
            "conversation_kind: 'agent'",
            "task_id: ${JSON.stringify(SOURCE_TASK_ID)}",
            "summary?.className.includes('search-highlighted')",
            "launcher task handoff highlighted delegated summary",
            "delegated summary Run Detail replay verified",
            "REJECTED_SUMMARY_RESULT",
            "row?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}",
            "row?.getAttribute('data-run-status') === 'approval_required'",
            "row?.getAttribute('data-run-status') === 'cancelled'",
            "row?.getAttribute('data-run-status') === 'completed'",
            "openRun?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}",
            "openRun?.getAttribute('data-run-status') === 'approval_required'",
            "openRun?.getAttribute('data-run-status') === 'cancelled'",
            "openRun?.getAttribute('data-run-status') === 'completed'",
            "run_oha_agent",
            "<oha_delegation>",
            "assertMockBridgeContract",
        ],
    )


def test_launcher_session_summary_ui_smoke_uses_bubble_and_live2d_summary_paths() -> None:
    smoke_script = "scripts/smoke_launcher_session_summary_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/bubble",
            "#/live2d",
            "surface=desktop",
            "url.pathname === '/ui/launcher'",
            "BUBBLE_SUMMARY",
            "DELEGATED_SUMMARY",
            "GROUP_TASK_ID",
            "DELEGATED_TASK_ID",
            "LIVE2D_REPLY",
            "LIVE2D_QUICK_TEXT",
            "Group summary: Design and Coding finished Native dispatch.",
            "Delegated summary: Coding finished Native delegated run.",
            "Live2D latest reply from launcher smoke",
            "Live2D quick input from launcher smoke",
            'data-testid="bubble-launcher-summary"',
            'data-testid="bubble-launcher-button"',
            'data-testid="bubble-launcher-session-summary-probe"',
            'data-testid="bubble-launcher-status-label"',
            'data-testid="bubble-launcher-recent-session"',
            'data-testid="live2d-launcher-stage"',
            'data-testid="live2d-launcher-quick-input"',
            'data-testid="live2d-launcher-quick-input-field"',
            'data-testid="live2d-launcher-quick-input-submit"',
            'data-testid="live2d-launcher-reply-text"',
            'data-testid="live2d-launcher-latest-reply"',
            'data-testid="live2d-launcher-session-summary-probe"',
            'data-testid="live2d-launcher-recent-session"',
            "request.method === 'POST' && url.pathname === '/ui/launcher/ack'",
            "request.method === 'POST' && url.pathname === '/ui/launcher/quick-message'",
            "request.method === 'GET' && url.pathname === '/__smoke/state'",
            "url.pathname === '/__smoke/live2d-open-chat'",
            "default_open_behavior: 'chat_input'",
            "enable_quick_input: true",
            "live2dClickAction: 'toggle_reply'",
            "bridgeState.live2dClickAction = 'open_chat'",
            "bridgeState.ackPayloads",
            "ackModes.includes('bubble')",
            "ackModes.includes('live2d')",
            "window.__ohaLauncherOpenViewCalls",
            "openView: async (view, params) =>",
            "call?.view === 'chat'",
            "call?.params?.session_id ===",
            "call?.params?.conversation_kind === 'group'",
            "call?.params?.task_id === ${JSON.stringify(GROUP_TASK_ID)}",
            "call?.params?.session_id === ${JSON.stringify(DELEGATED_SESSION_ID)}",
            "call?.params?.conversation_kind === 'agent'",
            "call?.params?.task_id === ${JSON.stringify(DELEGATED_TASK_ID)}",
            "live2d open-chat session handoff verified",
            "!bodyText.includes('oha.group_dispatch')",
            "!bodyText.includes('<oha_group_dispatch>')",
            "!bodyText.includes('run_oha_agent')",
            "!bodyText.includes('<oha_delegation>')",
            "bridgeState.quickMessagePayload",
            "quickPayload.text !== LIVE2D_QUICK_TEXT",
            "quickPayload.mode !== 'live2d'",
            "data-session-id",
            "data-task-id",
            "data-conversation-kind",
            "assertMockBridgeContract",
            "bridgeState.modeRequests.includes('bubble')",
            "bridgeState.modeRequests.includes('live2d')",
        ],
    )


def test_activity_ui_smoke_uses_feed_detail_trace_and_delete_paths() -> None:
    smoke_script = "scripts/smoke_activity_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/OpenDesignView.tsx",
        [
            'data-testid="activity-feed"',
            'data-testid="activity-search-input"',
            'data-testid="activity-list"',
            'data-testid="activity-row"',
            'data-testid="activity-row-open"',
            'data-testid="activity-detail-page"',
            'data-run-id={activityRunId}',
            'data-run-status={event.status || \'\'}',
            'data-session-id={event?.session_id || \'\'}',
            'data-task-id={event?.task_id || \'\'}',
            'data-testid="activity-detail-summary"',
            'data-testid="activity-detail-open-run"',
            "navigateTo('agents', { run: activityRunId }, ['tab', 'target', 'goal'])",
            'data-testid="activity-detail-body"',
            'data-testid="activity-trace"',
            'data-testid="activity-trace-row"',
            'data-testid="activity-trace-expand"',
            'data-testid="activity-detail-delete"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/components/ConfirmDialog.tsx",
        [
            'data-testid="confirm-dialog"',
            'data-testid="confirm-action"',
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/activity-all",
            "request.method === 'GET' && url.pathname === '/ui/activity'",
            "request.method === 'GET' && url.pathname === `/ui/activity/${ACTIVITY_EVENT_ID}`",
            "request.method === 'DELETE' && url.pathname === `/ui/activity/${ACTIVITY_EVENT_ID}`",
            "request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`",
            "request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`",
            "data-testid=\"activity-search-input\"",
            "data-testid=\"activity-row\"",
            "data-testid=\"activity-row-open\"",
            "data-testid=\"activity-detail-page\"",
            "data-testid=\"activity-detail-open-run\"",
            "openRun?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}",
            "openRun?.getAttribute('data-run-status') === 'completed'",
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"activity-trace-expand\"",
            "data-testid=\"activity-detail-delete\"",
            "data-testid=\"confirm-action\"",
            "bridgeState.listRequests.some((request) => request.query === 'workspace')",
            "bridgeState.detailRequests.includes(ACTIVITY_EVENT_ID)",
            "bridgeState.runDetailRequests.includes(RUN_ID)",
            "bridgeState.runEventRequests.some((request) => request.after_sequence === 0 && request.limit === 200)",
            "startedEvent?.textContent.includes(${JSON.stringify(TASK_ID)})",
            "completedEvent?.textContent.includes('Activity UI smoke opened Run Detail')",
            "bridgeState.deletedEventIds.includes(ACTIVITY_EVENT_ID)",
        ],
    )


def test_proactive_tts_ui_smoke_uses_screen_permission_tts_and_voice_import_paths() -> None:
    smoke_script = "scripts/smoke_proactive_tts_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/proactive-tts",
            "request.method === 'POST' && url.pathname === '/ui/proactive/screen-permission/check'",
            "request.method === 'POST' && url.pathname === '/ui/proactive/test'",
            "request.method === 'POST' && url.pathname === '/ui/tts/voice-resource/import'",
            "request.method === 'POST' && url.pathname === '/ui/tts/test'",
            "request.method === 'POST' && url.pathname === '/ui/tts/gpt-sovits/service-status'",
            "request.method === 'POST' && url.pathname === '/ui/tts/gpt-sovits/service/install'",
            "request.method === 'POST' && url.pathname === '/ui/tts/gpt-sovits/service/uninstall'",
            "request.method === 'POST' && url.pathname === '/ui/settings'",
            "proactive-screen-permission-check",
            "proactive-test-run",
            "data-testid=\"tts-gsv-service-panel\"",
            "data-testid=\"tts-gsv-service-status\"",
            "data-testid=\"tts-gsv-service-refresh\"",
            "data-testid=\"tts-gsv-service-install\"",
            "data-testid=\"tts-gsv-service-uninstall\"",
            "data-testid=\"tts-gsv-service-meta\"",
            "data-testid=\\\\\"confirm-action\\\\\"",
            'data-testid="tts-voice-archive-path"',
            'data-testid="tts-voice-import"',
            'data-testid="tts-save-and-test"',
            'data-testid="tts-test-result"',
            "bridgeState.gsvServiceStatusPayloads.length",
            "bridgeState.gsvServiceInstallRequests !== 1",
            "bridgeState.gsvServiceUninstallRequests !== 1",
            "__ohaTtsVoiceArchivePickerCalls",
            "chooseTtsVoiceArchive: async () =>",
            "expected TTS voice archive picker to be called once",
            "permissionPayload.open_settings !== true",
            "proactivePayload.mode !== 'live2d'",
            "voiceImportPayload.path !== VOICE_ARCHIVE_PATH",
            "ttsTestPayload.text !== TEST_TEXT",
            "Provider: GPT-SoVITS",
        ],
    )


def test_diagnostics_screenshot_ui_smoke_uses_local_screen_probe_path() -> None:
    smoke_script = "scripts/smoke_diagnostics_screenshot_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/DiagnosticsView.tsx",
        [
            "apiGet<ScreenshotProbe>('/screen/current')",
            "listModelProfiles()",
            "apiPost<DiagnosticResult>('/ui/native-agent/diagnostic-command'",
            "if (payload.dashboard) setOverview(payload.dashboard);",
            "void loadModelProfileSnapshot();",
            "function modelDiagnosticStatus(",
            "defaultChatProfile(modelProfiles)",
            "availableChatProfiles(modelProfiles)",
            "await copyText(text);",
            "setScreenProbe(null);",
            'data-testid="diagnostics-status"',
            'data-testid="diagnostics-run-command"',
            'data-testid="diagnostics-output"',
            'data-testid="diagnostics-copy-output"',
            'data-testid="diagnostics-screen-probe"',
            'data-testid="diagnostics-screen-probe-card"',
            'data-testid="diagnostics-screen-probe-summary"',
            'data-testid="diagnostics-screen-probe-image"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/lib/bridge.ts",
        [
            "const detail = data?.detail;",
            "typeof detail?.message === 'string'",
            "typeof detail?.error === 'string'",
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/diagnostics",
            "request.method === 'GET' && url.pathname === '/screen/current'",
            "request.method === 'POST' && url.pathname === '/ui/native-agent/diagnostic-command'",
            "SCREENSHOT_PERMISSION_MESSAGE",
            "screen_capture_permission_denied",
            "data-testid=\"diagnostics-run-command\"",
            "data-testid=\"diagnostics-output\"",
            "data-testid=\"diagnostics-copy-output\"",
            "data-testid=\"diagnostics-screen-probe\"",
            "data-testid=\"diagnostics-screen-probe-card\"",
            "data-testid=\"diagnostics-screen-probe-summary\"",
            "data-testid=\"diagnostics-screen-probe-image\"",
            "diagnostics screenshot permission error clears stale preview",
            "summary?.textContent.includes('未探测')",
            "&& !image",
            "bridgeState.screenRequests !== 2",
            "window.__ohaDiagnosticsCopiedText",
            "copyText: async (text)",
            "window.__ohaDiagnosticsCopiedText[0] ===",
            "diagnosticRequest.command !== DIAGNOSTIC_COMMAND",
        ],
    )


def test_live2d_settings_ui_smoke_uses_resource_import_and_model_prepare_paths() -> None:
    smoke_script = "scripts/smoke_live2d_settings_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/ModeSettingsView.tsx",
        [
            "apiPost<Live2DResourceActionResult>('/ui/live2d/model-path/prepare'",
            "apiPost<Live2DResourceActionResult>('/ui/live2d/archive/import'",
            'data-testid="mode-settings-status"',
            'dataTestId="mode-settings-save"',
            'data-testid="live2d-resource-settings"',
            'data-testid="live2d-model-path-prepare"',
            'data-testid="live2d-archive-import"',
            'data-testid="live2d-open-assets-dir"',
            'data-testid="live2d-open-releases"',
            'data-testid="live2d-manual-model-path"',
            'data-testid="live2d-manual-archive-path"',
            'data-testid="live2d-model-state"',
            'data-testid="live2d-configured-path"',
            'data-testid="live2d-effective-path"',
            "await openPath(assetsRoot)",
            "await openExternalUrl(releasesUrl)",
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/settings/live2d",
            "request.method === 'POST' && url.pathname === '/ui/live2d/archive/import'",
            "request.method === 'POST' && url.pathname === '/ui/live2d/model-path/prepare'",
            "request.method === 'POST' && url.pathname === '/ui/settings'",
            "data-testid=\"live2d-manual-archive-path\"",
            "data-testid=\"live2d-archive-import\"",
            "data-testid=\\\\\"live2d-open-assets-dir\\\\\"",
            "data-testid=\\\\\"live2d-open-releases\\\\\"",
            "data-testid=\"live2d-manual-model-path\"",
            "live2d-model-path-prepare",
            "data-testid=\"mode-settings-save\"",
            "__live2dDesktopActions",
            "chooseLive2DArchive: async () =>",
            "chooseLive2DModelDirectory: async () =>",
            "openPath: async (targetPath)",
            "openExternalUrl: async (url)",
            "expected Live2D openPath to receive assets root",
            "expected Live2D openExternalUrl to receive releases URL",
            "expected Live2D archive picker to be called once",
            "expected Live2D model directory picker to be called once",
            "changes['live2d_mode.model_path'] !== MODEL_PATH",
            "changes.display_mode !== 'live2d'",
        ],
    )


def test_chat_ui_preserves_image_approval_and_cancel_interaction_wiring() -> None:
    chat_view = "apps/frontend/src/views/ChatView.tsx"
    _assert_contains(
        chat_view,
        [
            "const [attachments, setAttachments] = useState<PendingAttachment[]>(() => [...retainedComposerDraft.attachments]);",
            "const CHAT_E2E_ADD_IMAGE_EVENT = 'oha-chat-e2e-add-image';",
            "type ChatE2EImageDetail = {",
            "async function fileFromE2EImageDetail(detail: ChatE2EImageDetail | undefined): Promise<File | null>",
            "if (!import.meta.env.DEV) return undefined;",
            "window.addEventListener(CHAT_E2E_ADD_IMAGE_EVENT, handleE2EAddImage as EventListener);",
            "window.removeEventListener(CHAT_E2E_ADD_IMAGE_EVENT, handleE2EAddImage as EventListener);",
            "const fileInputRef = useRef<HTMLInputElement>(null);",
            "if (attachments.length > 0 && !canAttachImages(executor))",
            "const outgoingAttachments = attachments;",
            "retainComposerDraft(text, outgoingAttachments);",
            "setAttachments(outgoingAttachments);",
            "const imageAttachDisabled = isSending || !canAttachImages(executor) || attachments.length >= MAX_ATTACHMENTS;",
            "if (imageAttachDisabled) {",
            "if (isSending || !canAttachImages(executor)) {",
            "function imageInputBlockedNoticeText()",
            "if (isSending) return '正在发送中，稍后再添加图片';",
            "const detail = imageInputBlockedNoticeText();",
            "setStatus(detail);",
            "disabled={imageAttachDisabled}",
            "const files = Array.from(event.target.files || []);",
            "event.target.value = '';",
            "if (files.length === 0) return;",
            "void addImageFiles(files);",
            "canChooseChatImages",
            "chooseChatImages",
            "async function openImageAttachmentPicker()",
            "fileInputRef.current?.click();",
            "await addDesktopImageSelections(selections);",
            "type=\"file\"",
            "accept=\"image/*\"",
            "multiple",
            "hidden",
            "aria-label={`移除 ${attachment.name}`}",
            "onClick={() => removeAttachment(attachment.id)}",
            "const result = await apiPost<MessagesPayload & { cancelled_tasks?: number }>('/ui/chat/session/cancel');",
            "setMessages(result.messages || []);",
            "setProcessingCount(nextProcessingCount);",
            "onClick={() => void cancelProcessing()}",
            "const approvalPromise = approveRunApproval(runId);",
            "const run = await rejectRunApproval(runId, 'Rejected from chat');",
            "pollAgentRunInBackground(runId, { summarizeDelegatedRun, ignoreInitialApprovalRequired: true });",
            "onApprove={() => void resolveApprovalMessage(message, 'approve')}",
            "onReject={() => void resolveApprovalMessage(message, 'reject')}",
            "onApprove={() => void resolveApprovalItem(composerApprovalItem, 'approve')}",
            "onReject={() => void resolveApprovalItem(composerApprovalItem, 'reject')}",
            "onOpenDetails={() => openRunDetails(composerApprovalItem.runId)}",
            "onReveal={() => revealMessage(composerApprovalItem.messageId)}",
            "className=\"composer-approval-nav\"",
            "className=\"chat-stop-btn\"",
            "aria-label={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}",
            "const eventStatus = String(event?.status || '').trim();",
            "if (['completed', 'success', 'failed', 'error', 'cancelled'].includes(eventStatus)) return false;",
            "(eventStatus === 'approval_required' || String(event?.metadata?.run_status || '').trim() === 'approval_required')",
        ],
    )
    _assert_occurs(chat_view, "onClick={() => void openImageAttachmentPicker()}", 2)
    _assert_occurs(chat_view, "data-testid=\"chat-image-file-input\"", 1)
    _assert_occurs(chat_view, "disabled={imageAttachDisabled}", 3)
    _assert_occurs(chat_view, "if (imageAttachDisabled) {", 3)
    _assert_occurs(chat_view, "import.meta.env.DEV", 1)


def test_chat_ui_exposes_stable_e2e_selectors_for_image_cancel_approval_flow() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "data-testid=\"chat-header-image-attach-button\"",
            "data-testid=\"chat-header-stop-button\"",
            "data-testid=\"chat-composer-image-attach-button\"",
            "data-testid=\"chat-composer-stop-button\"",
            "data-testid=\"chat-image-file-input\"",
            "data-testid=\"chat-composer-attachment-preview\"",
            "data-attachment-id={attachment.id}",
            "data-attachment-mime={attachment.mime_type}",
            "data-attachment-name={attachment.name}",
            "data-attachment-size={attachment.size}",
            "data-attachment-width={attachment.width || ''}",
            "data-attachment-height={attachment.height || ''}",
            "data-testid=\"chat-composer-attachment-remove\"",
            "data-testid=\"chat-message-attachments\"",
            "testId=\"chat-message-attachment-item\"",
            "data-testid=\"chat-message-approval-card\"",
            "data-approval-id={approvalId || ''}",
            "data-approval-kind={workflowApproval ? 'workflow' : 'tool'}",
            "data-approval-source=\"message\"",
            "data-approval-tool={details.tool}",
            "data-run-id={runId}",
            "data-run-status={runStatus}",
            "data-testid=\"chat-message-approval-actions\"",
            "data-approval-id={approvalId}",
            "data-approval-signature={approvalSignature}",
            "data-approval-tool={approvalDetails?.tool || ''}",
            "data-testid=\"chat-message-approval-approve\"",
            "data-testid=\"chat-message-approval-reject\"",
            "data-testid=\"chat-message-approval-open-run-detail\"",
            "data-testid=\"chat-message-retry\"",
            "data-testid=\"chat-message-open-run-detail\"",
            "data-testid=\"chat-composer-approval-notice\"",
            "data-approval-id={approvalId || ''}",
            "data-approval-item-id={itemId || ''}",
            "data-approval-source={source || ''}",
            "data-approval-tool={details.tool}",
            "data-run-id={runId || ''}",
            "data-run-status={runStatus || ''}",
            "data-testid=\"chat-composer-approval-approve\"",
            "data-testid=\"chat-composer-approval-reject\"",
            "data-testid=\"chat-composer-approval-open-run-detail\"",
            "data-testid=\"chat-composer-approval-reveal\"",
            "data-testid=\"chat-composer-approval-previous\"",
            "data-testid=\"chat-composer-approval-next\"",
        ],
    )
    _assert_contains(
        "apps/frontend/src/components/ImageAttachmentViewer.tsx",
        [
            "data-testid=\"chat-image-viewer-backdrop\"",
            "data-testid=\"chat-image-viewer-modal\"",
            "data-testid=\"chat-image-viewer-stage\"",
            "data-testid=\"chat-image-viewer-close\"",
            "data-attachment-id={attachment.id || ''}",
            "data-attachment-kind={kind}",
            "data-attachment-mime={mimeType}",
            "data-attachment-name={name}",
            "data-attachment-size={attachment.size || 0}",
        ],
    )
    _assert_occurs("apps/frontend/src/components/ImageAttachmentViewer.tsx", "data-attachment-id={attachment.id || ''}", 2)


def test_chat_image_attachment_ui_smoke_uses_file_input_path() -> None:
    smoke_script = "scripts/smoke_chat_image_attachment_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "document.querySelector('[data-testid=\"chat-header-image-attach-button\"]')",
            "document.querySelector('[data-testid=\"chat-composer-image-attach-button\"]')",
            "document.querySelector('[data-testid=\"chat-image-file-input\"]')",
            "if (input.type !== 'file') throw new Error('chat image input must stay a file input')",
            "if (input.accept !== 'image/*') throw new Error('chat image input must only accept images')",
            "if (!input.multiple) throw new Error('chat image input must support multiple images')",
            "if (!input.hidden) throw new Error('chat image input must stay hidden behind visible attach buttons')",
            "Object.defineProperty(input, 'click', { configurable: true, value: () => { clickCount += 1; } })",
            "buttons.forEach((button) => button.click())",
            "if (clickCount !== buttons.length) throw new Error('chat image attach buttons did not target file input')",
            "window.ohaDesktop = {",
            "chooseChatImages: async () =>",
            "chat desktop image picker should not click hidden file input",
            "desktop native image picker API rendered attachment preview",
            "new File([blob], 'smoke-image.svg', { type: 'image/svg+xml' })",
            "new DataTransfer()",
            "transfer.items.add(file)",
            "Object.defineProperty(input, 'files', { configurable: true, value: transfer.files })",
            "input.dispatchEvent(new Event('change', { bubbles: true }))",
            "delete input.files",
            "chat-composer-attachment-remove",
            "removed composer attachment preview",
            "disabled send button after attachment removal",
            "setChatImageInputFilesWithCdp",
            "DOM.setFileInputFiles",
            "const CHAT_IMAGE_SMOKE_FILE_NAMES = [",
            "smoke-image-cdp.svg",
            "smoke-image-cdp-second.svg",
            "smoke-image-cdp-third.svg",
            "smoke-image-cdp-fourth.svg",
            "await setChatImageInputFilesWithCdp(win, imageFilePaths);",
            "const expectedNames = ${JSON.stringify(imageFileNames)};",
            "previews.length === expectedNames.length",
            "expectedNames.every((name) => names.includes(name))",
            "buttons.every((button) => button?.disabled)",
            "input?.disabled",
            "attachment previews rendered through CDP file input",
            "items.length === expectedNames.length",
            "item.getAttribute('data-attachment-kind') === 'image'",
            "Number(item.getAttribute('data-attachment-size') || 0) > 0",
            "composer cleared after image send",
            "document.querySelector('textarea.chat-input')?.value === ''",
            "Chat UI did not submit client_message_id for image message idempotency",
            "Chat UI did not submit exactly ${CHAT_IMAGE_SMOKE_FILE_NAMES.length} attachments",
            "missing submitted attachment: ${expectedName}",
            "submitted attachment did not include a client attachment id",
            "attachment.width !== 24 || attachment.height !== 24",
            "assistant-chat-image-ui-smoke-reply",
            "RUN_RESULT",
            "`/ui/runs/${RUN_ID}`",
            "`/yachiyo/studio/runs/${RUN_ID}/events`",
            "model.output.completed",
            "run.completed",
            r'''document.querySelector('[data-message-id=\\"assistant-chat-image-ui-smoke-reply\\"] [data-testid=\\"chat-message-open-run-detail\\"]').click()''',
            "openRun.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}",
            "openRun.getAttribute('data-run-status') === 'completed'",
            "detail?.getAttribute('data-run-kind') === 'main_chat_run'",
            "outputEvent?.textContent.includes(${JSON.stringify(RUN_RESULT)})",
            "image message Run Detail replay verified",
            "chat-image-viewer-modal",
            "document.querySelector('[data-testid=\"chat-image-viewer-stage\"] img')",
            "image?.getAttribute('alt') === 'smoke-image-cdp.svg'",
            "image?.getAttribute('src')?.startsWith('data:image/svg+xml')",
            "image viewer modal with rendered image",
            "chat-image-viewer-close",
            "closed image viewer modal",
            "image viewer closed",
        ],
    )
    _assert_not_contains(smoke_script, ["oha-chat-e2e-add-image"])


def test_chat_run_detail_handoff_ui_smoke_uses_completed_message_run_metadata() -> None:
    smoke_script = "scripts/smoke_chat_run_detail_handoff_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/chat",
            "metadata: {",
            "COMPLETED_MESSAGE_ID",
            "run_id: RUN_ID",
            "run_status: 'completed'",
            "run_id: FAILED_RUN_ID",
            "run_status: 'failed'",
            "source: 'main_chat'",
            "FAILED_RUN_ERROR",
            "FAILED_MESSAGE_ID",
            "request.method === 'POST' && url.pathname === '/ui/chat/messages/retry'",
            "bridgeState.retryPayloads",
            "retryPayload.message_id !== FAILED_MESSAGE_ID",
            "data-testid=\"chat-message-retry\"",
            "button.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}",
            "button.getAttribute('data-run-status') === 'completed'",
            "failedButton.getAttribute('data-run-id') === ${JSON.stringify(FAILED_RUN_ID)}",
            "failedButton.getAttribute('data-run-status') === 'failed'",
            r'''document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-retry"]')''',
            r'''document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-open-run-detail"]')''',
            "openFailedRun.getAttribute('data-run-id') !== ${JSON.stringify(FAILED_RUN_ID)}",
            "openFailedRun.getAttribute('data-run-status') !== 'failed'",
            "data-run-status') === 'failed'",
            "model.request.failed",
            "agent.run.failed",
            "failed Chat message opened matching Run Detail",
            "data-testid=\"chat-message-copy\"",
            "data-testid=\"chat-code-copy\"",
            "CODE_BLOCK",
            "ASSISTANT_CONTENT",
            "window.__ohaChatCopiedText",
            "copyText: async (text)",
            "window.__ohaChatCopiedText[0] ===",
            "completed Chat message copied",
            "window.__ohaChatCopiedText[1] ===",
            "completed Chat code block copied",
            "data-testid=\"chat-message-open-run-detail\"",
            r'''document.querySelector('[data-message-id="${COMPLETED_MESSAGE_ID}"] [data-testid="chat-message-open-run-detail"]')''',
            "openRun.getAttribute('data-run-id') !== ${JSON.stringify(RUN_ID)}",
            "openRun.getAttribute('data-run-status') !== 'completed'",
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"agent-run-detail-task\"",
            "data-testid=\"agent-run-detail-result\"",
            "data-testid=\"agent-run-detail-execution-event\"",
            "`/ui/runs/${RUN_ID}`",
            "`/yachiyo/studio/runs/${RUN_ID}/events`",
            "agent.run.started",
            "model.output.completed",
            "agent.run.completed",
            'outputEvent?.textContent.includes(${JSON.stringify(`"output": "${RUN_RESULT}"`)})',
            "completedEvent?.textContent.includes(${JSON.stringify(RUN_RESULT)})",
            "completed Chat message opened matching Run Detail",
        ],
    )


def test_chat_agent_progress_ui_smoke_uses_run_detail_polling_and_replay() -> None:
    smoke_script = "scripts/smoke_chat_agent_progress_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/chat",
            "status: 'processing'",
            "run_id: RUN_ID",
            "run_status: 'running'",
            "runnable_kind: 'agent'",
            "run_progress_title: PROGRESS_TITLE",
            "RUN_RESULT",
            "data-testid=\"chat-agent-run-progress-card\"",
            "data-testid=\"chat-agent-run-progress-open-run-detail\"",
            "button?.getAttribute('data-run-id') === smoke.runId",
            "button?.getAttribute('data-run-status') === 'processing'",
            "openRun.getAttribute('data-run-id') !== smoke.runId",
            "openRun.getAttribute('data-run-status') !== 'processing'",
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"agent-run-detail-task\"",
            "data-testid=\"agent-run-detail-execution-event\"",
            "`/ui/runs/${RUN_ID}`",
            "`/yachiyo/studio/runs/${RUN_ID}/events`",
            "url.pathname === '/__smoke/complete-run'",
            "agent.run.started",
            "model.output.completed",
            "agent.run.completed",
            "startedEvent.textContent.includes(smoke.taskId)",
            "startedEvent.textContent.includes(smoke.runGoal)",
            "Chat Agent progress opened matching running Run Detail",
            "detail?.getAttribute('data-run-status') === 'completed'",
            "result?.textContent.includes(smoke.runResult)",
            "outputEvent?.getAttribute('data-run-event-sequence') === '2'",
            "completedEvent?.getAttribute('data-run-event-sequence') === '3'",
            "Chat Agent progress completed Run Detail replay verified",
        ],
    )


def test_chat_cancel_ui_smoke_uses_stop_buttons_and_cancel_route() -> None:
    smoke_script = "scripts/smoke_chat_cancel_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "/ui/chat/session/cancel",
            "document.querySelector('[data-testid=\"chat-composer-stop-button\"]')",
            "document.querySelector('[data-testid=\"chat-header-stop-button\"]')",
            r'''document.querySelector('[data-testid=\\"chat-composer-stop-button\\"]').click()''',
            r'''document.querySelector('[data-testid=\\"chat-header-stop-button\\"]').click()''',
            "assistant-cancel-ui-smoke-processing",
            "assistant-cancel-ui-smoke-cancelled",
            "Still running cancel smoke.",
            "Cancelled by user from Chat UI smoke.",
            "/yachiyo/studio/runs/${RUN_ID}/events",
            "run.cancelled",
            "data-run-status') === 'cancelled'",
            "cancelled message Run Detail replay verified",
            "expected two chat cancel calls",
            "composer stop cancelled chat",
            "header stop cancelled chat",
        ],
    )


def test_chat_approval_ui_smoke_uses_message_and_composer_actions() -> None:
    smoke_script = "scripts/smoke_chat_approval_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "`/ui/runs/${RUN_ID}`",
            "`/ui/runs/${RUN_ID}/approval/approve`",
            "`/ui/runs/${RUN_ID}/approval/reject`",
            "`/yachiyo/studio/runs/${RUN_ID}/events`",
            "document.querySelector('[data-testid=\"chat-message-approval-card\"]')",
            "document.querySelector('[data-testid=\"chat-message-approval-actions\"]')",
            "document.querySelector('[data-testid=\"chat-message-approval-approve\"]')",
            "document.querySelector('[data-testid=\"chat-message-approval-reject\"]')",
            "document.querySelector('[data-testid=\"chat-message-approval-open-run-detail\"]')",
            "document.querySelector('[data-testid=\"chat-composer-approval-notice\"]')",
            "document.querySelector('[data-testid=\"chat-composer-approval-approve\"]')",
            "document.querySelector('[data-testid=\"chat-composer-approval-reject\"]')",
            "document.querySelector('[data-testid=\"chat-composer-approval-open-run-detail\"]')",
            "openRun?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}",
            "openRun?.getAttribute('data-run-status') === 'approval_required'",
            "composer?.getAttribute('data-run-status') === 'approval_required'",
            "composerOpenRun?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}",
            "composerOpenRun?.getAttribute('data-run-status') === 'approval_required'",
            r'''document.querySelector('[data-testid=\\"chat-message-approval-open-run-detail\\"]').click()''',
            r'''document.querySelector('[data-testid=\\"chat-message-approval-approve\\"]').click()''',
            r'''document.querySelector('[data-testid=\\"chat-message-approval-reject\\"]').click()''',
            r'''document.querySelector('[data-message-id=\\"assistant-chat-approval-ui-smoke-approved\\"] [data-testid=\\"chat-message-open-run-detail\\"]').click()''',
            r'''document.querySelector('[data-testid=\\"chat-composer-approval-open-run-detail\\"]').click()''',
            r'''document.querySelector('[data-testid=\\"chat-composer-approval-approve\\"]').click()''',
            r'''document.querySelector('[data-testid=\\"chat-composer-approval-reject\\"]').click()''',
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"agent-run-detail-approval\"",
            "data-testid=\"agent-run-approval-request\"",
            "data-testid=\"agent-run-detail-execution-event\"",
            "detail?.getAttribute('data-run-status') === 'approval_required'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'completed'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(TASK_ID)}",
            "detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}",
            "approvalRequiredEvent?.textContent.includes('terminal.run')",
            "approvalRequiredEvent?.textContent.includes(${JSON.stringify(APPROVAL_COMMAND)})",
            "approvalRequiredEvent?.textContent.includes('/workspace')",
            "approvalRequiredEvent?.textContent.includes('Chat approval UI smoke')",
            "Approved from Chat approval UI smoke.",
            "Rejected from chat",
            "waitForApprovedRunDetailHandoff",
            "detail?.getAttribute('data-run-status') === 'completed'",
            "eventTypes.includes('agent.tool.approval_approved')",
            "eventTypes.includes('agent.tool.call')",
            "eventTypes.includes('run.completed')",
            "toolCallEvent?.textContent.includes(${JSON.stringify(APPROVAL_COMMAND)})",
            "message approval opened Run Detail",
            "approved message Run Detail replay verified",
            "composer approval opened Run Detail",
            "expected two chat approval approve calls",
            "expected two chat approval reject calls",
            "message approval approved",
            "message approval rejected",
            "composer approval approved",
            "composer approval rejected",
        ],
    )


def test_agent_run_detail_ui_smoke_uses_replay_route_and_dom_attributes() -> None:
    smoke_script = "scripts/smoke_agent_run_detail_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "`/ui/runs/${RUN_ID}`",
            "`/ui/runs/${APPROVAL_RUN_ID}`",
            "`/ui/runs/${APPROVAL_RUN_ID}/approval/approve`",
            "`/ui/runs/${WORKFLOW_RUN_ID}`",
            "`/ui/runs/${WORKFLOW_CHILD_RUN_ID}`",
            "`/ui/runs/${WORKFLOW_CHILD_RUN_ID}/approval/approve`",
            "`/ui/runs/${WORKFLOW_REJECT_RUN_ID}`",
            "`/ui/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}`",
            "`/ui/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}/approval/reject`",
            "`/ui/runs/${WORKFLOW_CANCEL_RUN_ID}`",
            "`/ui/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}`",
            "`/ui/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}/cancel`",
            "`/ui/runs/${ACTIVE_CANCEL_RUN_ID}`",
            "`/ui/runs/${ACTIVE_CANCEL_RUN_ID}/cancel`",
            "`/ui/runs/${RUN_ID}/rerun`",
            "`/ui/runs/${RERUN_RUN_ID}`",
            "`/ui/runs/${RUN_ID}/artifacts/${ARTIFACT_PATH}`",
            "`/ui/runs/${WORKFLOW_RUN_ID}/artifacts/${WORKFLOW_ARTIFACT_PATH}`",
            "`/yachiyo/studio/runs/${RERUN_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${RUN_ID}/events`",
            "`/yachiyo/studio/runs/${APPROVAL_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${WORKFLOW_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${WORKFLOW_CHILD_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${WORKFLOW_REJECT_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${WORKFLOW_CANCEL_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}/events`",
            "`/yachiyo/studio/runs/${ACTIVE_CANCEL_RUN_ID}/events`",
            "profile-run-detail-smoke",
            "defaults: { chat: 'profile-run-detail-smoke' }",
            "task_id: RUN_TASK_ID",
            "session_id: RUN_SESSION_ID",
            "task_id: APPROVAL_TASK_ID",
            "session_id: APPROVAL_SESSION_ID",
            "task_id: ACTIVE_CANCEL_TASK_ID",
            "session_id: ACTIVE_CANCEL_SESSION_ID",
            "task_id: RERUN_TASK_ID",
            "task_id: WORKFLOW_TASK_ID",
            "session_id: WORKFLOW_SESSION_ID",
            "task_id: WORKFLOW_CHILD_TASK_ID",
            "session_id: WORKFLOW_CHILD_SESSION_ID",
            "task_id: WORKFLOW_REJECT_TASK_ID",
            "session_id: WORKFLOW_REJECT_SESSION_ID",
            "task_id: WORKFLOW_REJECT_CHILD_TASK_ID",
            "session_id: WORKFLOW_REJECT_CHILD_SESSION_ID",
            "task_id: WORKFLOW_CANCEL_TASK_ID",
            "session_id: WORKFLOW_CANCEL_SESSION_ID",
            "task_id: WORKFLOW_CANCEL_CHILD_TASK_ID",
            "session_id: WORKFLOW_CANCEL_CHILD_SESSION_ID",
            "approvalRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "workflowRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "workflowChildRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "workflowRejectRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "workflowRejectChildRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "workflowCancelRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "workflowCancelChildRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "activeCancelRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "events: runEvents.filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "runEventRequests.push({ after_sequence: Math.max(0, afterSequence), limit })",
            "events: rerunEvents.filter((event) => event.sequence > afterSequence).slice(0, limit)",
            "#/agents/",
            "data-testid=\"agent-run-detail\"",
            "data-testid=\"agent-run-detail-approval\"",
            "data-testid=\"agent-run-approval-request\"",
            "data-testid=\"agent-run-detail-approval-approve\"",
            "data-testid=\"agent-run-detail-approval-reject\"",
            "data-testid=\"agent-run-detail-cancel\"",
            "data-testid=\"confirm-dialog\"",
            "data-testid=\"confirm-action\"",
            "data-testid=\"agent-run-detail-workflow-child-approval\"",
            "data-testid=\"agent-run-detail-workflow-child-approve\"",
            "data-testid=\"agent-run-detail-workflow-child-reject\"",
            "data-testid=\"agent-run-detail-workflow-child-cancel\"",
            "data-testid=\"agent-run-detail-workflow-child-open-run\"",
            "data-testid=\"agent-run-detail-execution-open-child-run\"",
            "openRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}",
            "openRun?.getAttribute('data-run-status') === 'approval_required'",
            "executionChildOpenRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}",
            "executionChildOpenRun?.getAttribute('data-run-status') === 'approval_required'",
            "parentOpen?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_RUN_ID)}",
            "parentOpen?.getAttribute('data-run-status') === 'completed'",
            "approvalOpen?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}",
            "approvalOpen?.getAttribute('data-run-status') === 'completed'",
            "selectedOpen?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}",
            "selectedOpen?.getAttribute('data-run-status') === 'completed'",
            "data-testid=\"agent-run-detail-task\"",
            "data-testid=\"agent-run-detail-result\"",
            "data-testid=\"agent-run-detail-workflow-step\"",
            "data-testid=\"agent-run-detail-workflow-step-open-run\"",
            "openStepRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}",
            "openStepRun?.getAttribute('data-run-status') === 'completed'",
            "executionChildOpenRun?.getAttribute('data-run-status') === 'completed'",
            "data-testid=\"agent-run-detail-execution-event\"",
            "data-testid=\"agent-run-detail-artifact\"",
            "data-testid=\"agent-run-detail-artifact-preview\"",
            "data-testid=\"agent-run-history-manage\"",
            "data-testid=\"agent-run-history-bulk-actions\"",
            "agent-run-history-select-all",
            "agent-run-history-clear-selection",
            "data-testid=\"agent-run-history-select-run\"",
            "data-testid=\"agent-run-history-delete-selected\"",
            "agent-run-detail-rerun",
            "request.method === 'DELETE' && url.pathname.startsWith('/ui/runs/')",
            "deletedRunIds.push(runId)",
            "data-artifact-path",
            "data-artifact-source-run-id",
            "agent-run-detail-load-more-events",
            "data-run-event",
            "data-run-event-sequence",
            "data-run-event-run-id",
            "events.length === 200",
            "events.length === 201",
            "sequences[199] === '200'",
            "sequences[200] === '201'",
            'toolEvent?.textContent.includes(\'"path": "README.md"\')',
            "modelEvent?.textContent.includes('Replay page smoke event 3')",
            "completedEvent?.textContent.includes",
            "detail?.getAttribute('data-run-status') === 'running'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(ACTIVE_CANCEL_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'cancelled'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(ACTIVE_CANCEL_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'approval_required'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}",
            "detail?.getAttribute('data-session-id') === ${JSON.stringify(APPROVAL_SESSION_ID)}",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(RUN_TASK_ID)}",
            "document.querySelector('[data-testid=\"agent-run-detail\"]')?.getAttribute('data-task-id') === ${JSON.stringify(RERUN_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'approval_required'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_REJECT_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'cancelled'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_REJECT_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'approval_required'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_CANCEL_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'cancelled'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_CANCEL_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'approval_required'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'completed'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_TASK_ID)}",
            "detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_CHILD_TASK_ID)}",
            "detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_CHILD_SESSION_ID)}",
            "startedEvent?.textContent.includes('Approve Native Run Detail from Agent Studio smoke')",
            "active Run Detail cancel completed",
            "activeRunCancelled",
            "agent.run.cancelled",
            "Run Detail active Run cancelled from UI smoke",
            "approvalRequiredEvent?.textContent.includes('printf run-detail-approval-smoke')",
            "toolCallEvent?.textContent.includes('printf run-detail-approval-smoke')",
            "completedEvent?.textContent.includes('Run Detail approval smoke completed')",
            "childResumedEvent?.textContent.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)})",
            "artifactEvent?.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)})",
            "completedEvent?.textContent.includes('Workflow child approval Electron smoke complete')",
            "startedEvent?.textContent.includes('Approve child Agent from Workflow Run Detail smoke')",
            "approvalRequiredEvent?.textContent.includes('printf workflow-child-electron-approved')",
            "toolCallEvent?.textContent.includes('printf workflow-child-electron-approved')",
            "rejectCancelledEvent?.textContent.includes(${JSON.stringify(WORKFLOW_REJECT_CHILD_RUN_ID)})",
            "cancelCancelledEvent?.textContent.includes(${JSON.stringify(WORKFLOW_CANCEL_CHILD_RUN_ID)})",
            "rerunStartedEvent?.textContent.includes(${JSON.stringify(RUN_ID)})",
            "rerunCompletedEvent?.textContent.includes('Run Detail UI smoke rerun completed')",
            "after_sequence === 200 && request.limit === 200",
            "Artifact preview loaded from mock Bridge.",
            "Run Detail approval smoke completed",
            "Workflow child approval Electron smoke complete",
            "printf workflow-child-electron-approved",
            "Workflow child approval rejected from Electron smoke",
            "printf workflow-child-electron-rejected",
            "Workflow child run cancelled from Electron smoke",
            "printf workflow-child-electron-cancelled",
            "workflow child reject action completed",
            "workflow child cancel action completed",
            "workflow child reject action was not called",
            "workflow child cancel action was not called",
            "agent run history select all",
            "agent run history clear selection",
            "agent run history bulk delete completed",
            "run history selection controls and bulk delete verified",
            "agent run history delete route was not called",
            "workflow child route hash",
            "Run Detail UI smoke rerun completed",
            "run.rerun.started",
            "workflow.run.child_resumed",
            "workflow.run.resumed",
            "workflow.node.artifact",
            "workflow.run.completed",
            "workflow.run.cancelled",
            "agent.tool.approval_required",
            "agent.tool.approval_approved",
            "agent.tool.approval_rejected",
            "agent.run.started",
            "agent.tool.call",
            "agent.run.cancelled",
            "agent.run.completed",
        ],
    )


def test_chat_approval_run_detail_handoff_preserves_route_and_replay_wiring() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "function openRunDetails(runId: string | undefined)",
            "const clean = String(runId || '').trim();",
            "navigateTo('agents', { run: clean }, ['tab', 'target', 'goal']);",
            "onOpenRunDetails={openRunDetails}",
            "onOpenDetails={() => onOpenRunDetails(runId)}",
            "onOpenDetails={() => openRunDetails(composerApprovalItem.runId)}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "const routeRunId = currentParam('run').trim();",
            "const [tab, setTab] = useState<StudioTab>(() => routeRunId || routeRunTarget ? 'runs' : routeTab);",
            "const [selectedRunId, setSelectedRunId] = useState(() => routeRunId);",
            "const nextTab = routeRunId || routeRunTarget ? 'runs' : routeTab;",
            "setSelectedRunId((current) => current === routeRunId ? current : routeRunId);",
            "if (!selectedRunId || selectedRun) return;",
            "getRun(selectedRunId)",
            "useRunEventReplay(selectedRunId, selectedRunReplayRefreshKey)",
            "useRunApprovalFollowup({",
            "selectedRunExecutionEvents",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunApprovalFollowup.ts",
        [
            "const selectedRunIdRef = useRef(selectedRunId);",
            "selectedRunIdRef.current = selectedRunId;",
            "isApprovalFollowupCurrent(selectedAfterAction) ? { selectedRunId: selectedAfterAction } : {}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunApprovalActions.ts",
        [
            "void refresh(approvalFollowupRefreshOptions(selectedAfterAction)).catch(() => undefined);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunTimeline.tsx",
        [
            "RunEvent replay facts",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunEventReplay.ts",
        [
            "getRunEvents(runId, 0, pageSize)",
            "[runId]: {",
            "events: current[runId]?.events || [],",
            "events: current[runId]?.events || currentEvents,",
        ],
    )


def test_chat_ui_preserves_delegated_summary_processing_state_wiring() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "type DelegatedRunSummaryResult = {",
            "async function createDelegatedRunSummary(runId: string): Promise<DelegatedRunSummaryResult>",
            "let refreshed: Awaited<ReturnType<typeof refreshMessages>> | undefined;",
            "refreshed = await refreshMessages();",
            "const refreshedProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));",
            "isProcessing: created ? (refreshed ? Boolean(refreshed.is_processing || refreshedProcessingCount > 0) : true) : false,",
            "processingCount: created ? (refreshed ? refreshedProcessingCount : 1) : 0,",
            "const nextProcessing = delegatedSummary.created ? delegatedSummary.isProcessing : chatStillProcessing;",
            "const nextProcessingCount = delegatedSummary.created ? delegatedSummary.processingCount : chatProcessingCount;",
            "let delegatedSummaryIsProcessing = false;",
            "let delegatedSummaryProcessingCount = 0;",
            "delegatedSummaryIsProcessing = summary.isProcessing;",
            "delegatedSummaryProcessingCount = summary.processingCount;",
            "const nextProcessing = delegatedSummaryCreated ? delegatedSummaryIsProcessing : chatStillProcessing;",
            "const nextProcessingCount = delegatedSummaryCreated ? delegatedSummaryProcessingCount : chatProcessingCount;",
            'data-testid="chat-message-activity-list"',
            'data-testid="chat-message-activity-row"',
            "data-activity-status={displayStatus || ''}",
            "data-activity-tool={event.tool_name || ''}",
            "data-run-id={runId || ''}",
            "data-run-status={displayStatus || ''}",
            'data-testid="chat-message-activity-open"',
            'data-testid="chat-message-activity-toggle"',
            'data-testid="chat-message-activity-open-run-detail"',
            'data-testid="chat-agent-run-progress-card"',
            "data-run-id={runId}",
            "data-run-status={runStatus}",
            "data-run-group-id={runGroupId}",
            "data-runnable-kind={runnableKind}",
            "data-runnable-id={runnableId}",
            'data-testid="chat-agent-run-progress-open-run-detail"',
            'data-testid="chat-message-summary-status"',
            "data-summary-task-id={summaryTaskId}",
            "data-summary-status={summaryStatus}",
            "data-summary-tone={summaryNotice.tone}",
            "data-run-group-id={summaryRunGroupId}",
            'data-testid="chat-message-followup-status"',
            "data-followup-task-ids={followupTaskIds}",
            "data-followup-agent-message-ids={followupAgentMessageIds}",
        ],
    )


def test_agent_studio_preserves_workflow_run_detail_and_approval_paths() -> None:
    _assert_contains(
        "apps/frontend/src/lib/agents.ts",
        [
            "export type AgentExecutionBackend = 'native_profile';",
            "system?: boolean;",
            "virtual?: boolean;",
            "deletable?: boolean;",
            "task_id?: string;",
            "session_id?: string;",
            "task_run_link_created_at?: string;",
            "task_run_link_updated_at?: string;",
            "task_run_link_run_status?: string;",
            "task_run_link_last_event_sequence?: number;",
            "export async function listAgents()",
            "'/yachiyo/studio/agents'",
            "'/ui/agents'",
            "export async function createAgent(",
            "apiPost<AgentSpec>('/yachiyo/studio/agents', request)",
            "apiPost<AgentSpec>('/ui/agents', request)",
            "export async function updateAgent(",
            "apiPost<AgentSpec>('/yachiyo/studio/agents', { ...request, agent_id: agentId })",
            "apiPatch<AgentSpec>(`/ui/agents/${encodeURIComponent(agentId)}`, request)",
            "export async function deleteAgent(",
            "apiDelete(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}`)",
            "apiDelete(`/ui/agents/${encodeURIComponent(agentId)}`)",
            "export async function testAgentModel(",
            "/yachiyo/studio/agents/${encodeURIComponent(agentId)}/test-model",
            "/ui/agents/${encodeURIComponent(agentId)}/test-model",
            "export async function attachSkill(",
            "/yachiyo/studio/agents/${encodeURIComponent(agentId)}/skills",
            "/ui/agents/${encodeURIComponent(agentId)}/skills",
            "export async function detachSkill(",
            "/yachiyo/studio/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}",
            "/ui/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}",
            "export async function listSkills()",
            "'/yachiyo/studio/skills'",
            "'/ui/skills'",
            "export async function importSkill(",
            "apiPost<SkillSpec>('/yachiyo/studio/skills/import'",
            "apiPost<SkillSpec>('/ui/skills/import'",
            "export async function listSkillSources()",
            "'/yachiyo/studio/skills/sources'",
            "'/ui/skills/sources'",
            "export async function syncNativeSkills()",
            "apiPost<SkillSyncResponse>('/yachiyo/studio/skills/sync'",
            "apiPost<SkillSyncResponse>('/ui/skills/sync'",
            "export async function installSkillCommand(",
            "apiPost<SkillInstallResponse>('/yachiyo/studio/skills/install'",
            "apiPost<SkillInstallResponse>('/ui/skills/install'",
            "export async function updateSkill(",
            "/yachiyo/studio/skills/${encodeURIComponent(skillId)}",
            "apiPatch<SkillSpec>(`/ui/skills/${encodeURIComponent(skillId)}`, request)",
            "export async function deleteSkill(",
            "apiDelete(`/yachiyo/studio/skills/${encodeURIComponent(skillId)}`)",
            "apiDelete(`/ui/skills/${encodeURIComponent(skillId)}`)",
            "export async function listSkillFolders()",
            "'/yachiyo/studio/skill-folders'",
            "'/ui/skill-folders'",
            "export async function createSkillFolder(",
            "apiPost<SkillFolderSpec>('/yachiyo/studio/skill-folders', request)",
            "apiPost<SkillFolderSpec>('/ui/skill-folders', request)",
            "export async function updateSkillFolder(",
            "apiPatch<SkillFolderSpec>(`/yachiyo/studio/skill-folders/${encodeURIComponent(folderId)}`, request)",
            "apiPatch<SkillFolderSpec>(`/ui/skill-folders/${encodeURIComponent(folderId)}`, request)",
            "export async function deleteSkillFolder(",
            "apiDelete(`/yachiyo/studio/skill-folders/${encodeURIComponent(folderId)}${query}`)",
            "apiDelete(`/ui/skill-folders/${encodeURIComponent(folderId)}${query}`)",
            "export async function listWorkflows()",
            "'/yachiyo/studio/workflows'",
            "'/ui/workflows'",
            "export async function createWorkflow(",
            "apiPost<WorkflowSpec>('/yachiyo/studio/workflows', request)",
            "apiPost<WorkflowSpec>('/ui/workflows', request)",
            "export async function updateWorkflow(",
            "apiPost<WorkflowSpec>('/yachiyo/studio/workflows', { ...request, workflow_id: workflowId })",
            "apiPatch<WorkflowSpec>(`/ui/workflows/${encodeURIComponent(workflowId)}`, request)",
            "export async function deleteWorkflow(",
            "apiDelete(`/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}`)",
            "apiDelete(`/ui/workflows/${encodeURIComponent(workflowId)}`)",
            "export async function listRuns()",
            "'/yachiyo/studio/runs'",
            "'/ui/runs'",
            "export async function getRun(",
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}",
            "export async function listRunGroups()",
            "'/yachiyo/studio/group-runs'",
            "'/ui/run-groups'",
            "export async function getRunGroup(",
            "/yachiyo/studio/group-runs/${encodeURIComponent(runGroupId)}",
            "/ui/run-groups/${encodeURIComponent(runGroupId)}",
            "function runGroupSpecFromPublicGroupRun(",
            "export async function getRunEvents(",
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/events?",
            "export async function deleteRun(",
            "apiDelete(`/yachiyo/studio/runs/${encodeURIComponent(runId)}`)",
            "apiDelete(`/ui/runs/${encodeURIComponent(runId)}`)",
            "export async function getRunArtifact(",
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}",
            "/yachiyo/studio/agents/${encodeURIComponent(agentId)}/runs",
            "'/ui/agent-runs'",
            "/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}/runs",
            "client_run_id: clientRunId",
            "'/ui/workflow-runs'",
            "export async function cancelRun(",
            "export async function approveRunApproval(",
            "/approval/approve",
            "export async function rejectRunApproval(",
            "/approval/reject",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "listSkills",
        [
            "apiGet<{ skills?: SkillSpec[] }>('/yachiyo/studio/skills')",
            "apiGet<{ skills?: SkillSpec[] }>('/ui/skills')",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "importSkill",
        [
            "apiPost<SkillSpec>('/yachiyo/studio/skills/import'",
            "apiPost<SkillSpec>('/ui/skills/import'",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "listSkillSources",
        [
            "apiGet<{ roots?: SkillSourceRoot[] }>('/yachiyo/studio/skills/sources')",
            "apiGet<{ roots?: SkillSourceRoot[] }>('/ui/skills/sources')",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "syncNativeSkills",
        [
            "apiPost<SkillSyncResponse>('/yachiyo/studio/skills/sync'",
            "apiPost<SkillSyncResponse>('/ui/skills/sync'",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "installSkillCommand",
        [
            "apiPost<SkillInstallResponse>('/yachiyo/studio/skills/install'",
            "apiPost<SkillInstallResponse>('/ui/skills/install'",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "updateSkill",
        [
            "apiPatch<SkillSpec>(`/yachiyo/studio/skills/${encodeURIComponent(skillId)}`",
            "apiPatch<SkillSpec>(`/ui/skills/${encodeURIComponent(skillId)}`",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "deleteSkill",
        [
            "apiDelete(`/yachiyo/studio/skills/${encodeURIComponent(skillId)}`)",
            "apiDelete(`/ui/skills/${encodeURIComponent(skillId)}`)",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "listSkillFolders",
        [
            "apiGet<{ folders?: SkillFolderSpec[] }>('/yachiyo/studio/skill-folders')",
            "apiGet<{ folders?: SkillFolderSpec[] }>('/ui/skill-folders')",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "createSkillFolder",
        [
            "apiPost<SkillFolderSpec>('/yachiyo/studio/skill-folders', request)",
            "apiPost<SkillFolderSpec>('/ui/skill-folders', request)",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "updateSkillFolder",
        [
            "apiPatch<SkillFolderSpec>(`/yachiyo/studio/skill-folders/${encodeURIComponent(folderId)}`",
            "apiPatch<SkillFolderSpec>(`/ui/skill-folders/${encodeURIComponent(folderId)}`",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "deleteSkillFolder",
        [
            "apiDelete(`/yachiyo/studio/skill-folders/${encodeURIComponent(folderId)}${query}`)",
            "apiDelete(`/ui/skill-folders/${encodeURIComponent(folderId)}${query}`)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "from '../features/agent-studio/studioTabs';",
            "studioTabs.map((item) => (",
            "listSkills",
            "updateSkill",
            "listSkillFolders",
            "listWorkflows",
            "listRuns",
            "listRunGroups",
            "useAgentAvatarActions",
            "useAgentDeletionActions",
            "useAgentSaveActions",
            "useAgentSkillMountActions",
            "useRunCacheActions",
            "useRunApprovalActions",
            "useRunEventReplay",
            "useRunArtifactActions",
            "useRunDebugActions",
            "useRunHistoryManagement",
            "useRunLaunchActions",
            "useRunNavigationActions",
            "useSkillDeletionActions",
            "useSkillFolderManagement",
            "useSkillImportActions",
            "useSkillSourceInputActions",
            "useWorkflowCanvasActions",
            "useWorkflowDeletionActions",
            "useWorkflowDraftActions",
            "useWorkflowSaveActions",
            "saveAgent",
            "requestDeleteAgent",
            "requestDeleteSelectedAgents",
            "importSkillSourceList",
            "syncNativeSkillLibrary",
            "installSkillFromCommand",
            "await updateSkill(skill.skill_id, { folder_id: folderId });",
            "await updateSkill(skill.skill_id, { enabled: skill.enabled === false });",
            "requestDeleteSkill",
            "createSkillFolderFromDraft",
            "updateSkillFolderFromDraft",
            "requestDeleteSkillFolder",
            "toggleAgentSkillMount",
            "saveWorkflowDraft",
            "requestDeleteWorkflow",
            "requestDeleteSelectedWorkflows",
            "refreshRunGroupsForRuns",
            "runEventReplayToTimelineEvent",
            "selectedRunExecutionEvents",
            "selectedRunReplayHasMore",
            "selectedRunReplayRefreshKey",
            "loadMoreSelectedRunEvents",
            "onCreateRun={() => void runAction(createRunFromTarget, '创建 Run')}",
            "onRunAgent={() => void runAction(runCurrentAgent, '运行 Agent')}",
            "onRunWorkflow={() => void runAction(runCurrentWorkflow, '保存并运行 Workflow')}",
            "onPrepareSelectedRunRerun={prepareSelectedRunRerun}",
            "onRerunSelectedRun={rerunSelectedRun}",
            "RunDetailPanel",
            "selectedWorkflowApprovalChildRunId",
            "selectedAgentReadOnly",
            "selectedAgentDeletable",
            "AgentEditorPanel",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunCacheActions.ts",
        [
            "export function useRunCacheActions",
            "const upsertRunGroups = useCallback",
            "const nextById = new Map(current.map((group) => [group.run_group_id, group]));",
            "nextGroups.forEach((group) => nextById.set(group.run_group_id, group));",
            "const upsertRunDetailCache = useCallback",
            "const visibleRuns = acceptedRunUpdates(nextRuns);",
            "setRunDetailCache((current) => {",
            "setRuns((current) => {",
            "const refreshRunGroupsForRuns = useCallback",
            "const groupIds = Array.from(new Set(nextRuns.map((run) => String(run.run_group_id || '')).filter(Boolean)));",
            "Promise.all(groupIds.map((groupId) => getRunGroup(groupId).catch(() => null)))",
            "if (!shouldApply()) return;",
            "upsertRunGroups(loadedGroups);",
            "const refreshRunGroupById = useCallback",
            "shouldApply: () => boolean = () => true",
            "if (shouldApply()) upsertRunGroups([group]);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useWorkflowDraftActions.ts",
        [
            "export function useWorkflowDraftActions",
            "function startNewWorkflow()",
            "setNodes(starterNodes);",
            "setWorkflowName('New Workflow');",
            "setStatus('正在编辑新的 Workflow 草稿');",
            "function loadPhase4WorkflowTemplate()",
            "const nextNodes = buildPhase4WorkflowNodes(agents);",
            "setError('当前没有可用 Agent，无法生成全线测试模板。');",
            "setWorkflowName('Phase 4 Agent 全线流通测试');",
            "setEdges(linearEdgesForNodes(nextNodes));",
            "function selectWorkflow(workflowId: string)",
            "function openWorkflowDesign(workflowId: string)",
            "setError('找不到对应的 Workflow 定义，可能已被删除。');",
            "setTab('workflows');",
            "navigateTo('agents', { tab: 'workflows' }, ['run', 'target', 'goal']);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useWorkflowCanvasActions.ts",
        [
            "export function useWorkflowCanvasActions",
            "function addFlowNode(kind: WorkflowCanvasNodeKind, agentId = '')",
            "const id = uniqueWorkflowNodeId(nodeSeed, nodes);",
            "const sourceId = terminalNodeId(nodes, edges);",
            "type: kind === 'artifact' ? 'output' : 'default',",
            "position: { x: 120 + nodes.length * 180, y: 140 },",
            "agent?.name || '选择 Agent'",
            "setNodes((current) => [...current, nextNode]);",
            "id: `edge-${sourceId}-${id}`",
            "function removeFlowNode(nodeId: string)",
            "if (nodeId === 'start') return;",
            "const incoming = edges.find((edge) => edge.target === nodeId);",
            "const outgoing = edges.find((edge) => edge.source === nodeId);",
            "const nextEdges = current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);",
            "id: `edge-${incoming.source}-${outgoing.target}`",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunDebugActions.ts",
        [
            "export function useRunDebugActions",
            "async function loadMoreSelectedRunEvents()",
            "const loadedCount = await loadMoreRunReplayEvents();",
            "setStatus(loadedCount ? `已加载 ${loadedCount} 条 RunEvent replay` : '没有更多 RunEvent replay');",
            "function requestCancelSelectedRun()",
            "if (!selectedRun || !isActiveRunStatus(selectedRun.status)) return;",
            "const runName = selectedRun.runnable_name || selectedRun.runnable_id || 'Run';",
            "confirmLabel: '取消 Run',",
            "variant: 'danger',",
            "onConfirm: () => void runAction(cancelSelectedRun, '取消 Run'),",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunArtifactActions.ts",
        [
            "export function useRunArtifactActions",
            "async function openArtifact(run: RunSpec | string, path: string)",
            "const runId = typeof run === 'string' ? run : run.run_id;",
            "setStatus('读取 artifact...');",
            "const payload = await getRunArtifact(runId, path);",
            "setArtifactPreview({",
            "path: payload.path || path,",
            "content: payload.content || '',",
            "truncated: payload.truncated,",
            "setStatus('Artifact 已读取');",
            "setError(err instanceof Error ? err.message : '读取 artifact 失败');",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunNavigationActions.ts",
        [
            "export function useRunNavigationActions",
            "function openRunDetail(runId: string, options: { revealInHistory?: boolean } = {})",
            "setRunKindFilter('all');",
            "setRunStatusFilter('all');",
            "setRunSearchQuery('');",
            "const groupKey = runHistoryGroupKey(run);",
            "navigateTo('agents', { run: runId }, ['tab', 'target', 'goal']);",
            "function openAgentGroupRunTimeline(groupRun: GroupRunSnapshot | null)",
            "const runId = groupRunTimelineRunId(groupRun);",
            "setError('这个 GroupRun 暂时没有可打开的子 Run。');",
            "function toggleRunHistoryGroup(groupKey: string)",
            "function selectRunKindFilter(nextFilter: RunKindFilter)",
            "function selectRunStatusFilter(nextFilter: RunStatusFilter)",
            "navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentAvatarActions.ts",
        [
            "export function useAgentAvatarActions",
            "async function pickAgentAvatar()",
            "setBusyAction('选择 Agent 头像');",
            "const selection = await chooseAvatarImage();",
            "const avatar = typeof selection === 'string' ? selection : selection?.data_url || selection?.path || '';",
            "setDraft((current) => ({ ...current, avatar_url: avatar }));",
            "setStatus('已选择 Agent 头像');",
            "setError(err instanceof Error ? err.message : '选择 Agent 头像失败');",
            "setBusyAction('');",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentSaveActions.ts",
        [
            "export function useAgentSaveActions",
            "async function saveAgent()",
            "if (selectedAgentReadOnly)",
            "setStatus('系统 Agent 只能查看，不能修改。');",
            "tool_policy: draftToolPolicy(draft),",
            "readable_scopes: textToScopes(draft.readable_scopes),",
            "writable_scopes: textToScopes(draft.writable_scopes),",
            "const saved = draft.agent_id ? await updateAgent(draft.agent_id, request) : await createAgent(request);",
            "setSelectedAgentId(saved.agent_id);",
            "setDraft(agentToDraft(saved));",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentSkillMountActions.ts",
        [
            "export function useAgentSkillMountActions",
            "async function mountVisibleSkills()",
            "if (!draftAgentId || !selectedAgent) return;",
            "setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');",
            "await updateAgent(draftAgentId, { skill_ids: nextSkillIds });",
            "async function unmountVisibleSkills()",
            "const visible = new Set(visibleMountSkillIds);",
            "function toggleAgentSkillMount(skill: SkillSpec, mounted: boolean)",
            "if (mounted) await detachSkill(draftAgentId, skill.skill_id);",
            "else await attachSkill(draftAgentId, skill.skill_id);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useWorkflowDeletionActions.ts",
        [
            "export function useWorkflowDeletionActions",
            "function requestDeleteWorkflow()",
            "await deleteWorkflow(workflowId);",
            "setSelectedWorkflowIds((current) => current.filter((id) => id !== workflowId));",
            "resetWorkflowDraft();",
            "function requestDeleteSelectedWorkflows()",
            "const deletingCurrent = Boolean(selectedWorkflowId && targetIds.has(selectedWorkflowId));",
            "await deleteWorkflow(workflow.workflow_id);",
            "setSelectedWorkflowIds((current) => current.filter((id) => !targetIds.has(id)));",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentDeletionActions.ts",
        [
            "export function useAgentDeletionActions",
            "function requestDeleteAgent()",
            "if (!selectedAgentDeletable)",
            "setStatus('系统 Agent 只能查看，不能删除。');",
            "await deleteAgent(agentId);",
            "setSelectedAgentIds((current) => current.filter((id) => id !== agentId));",
            "resetAgentDraft();",
            "function requestDeleteSelectedAgents()",
            "const deletingCurrent = Boolean(selectedAgentId && targetIds.has(selectedAgentId));",
            "await deleteAgent(agent.agent_id);",
            "setSelectedAgentIds((current) => current.filter((id) => !targetIds.has(id)));",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useSkillDeletionActions.ts",
        [
            "export function useSkillDeletionActions",
            "function requestDeleteSkill(skill: SkillSpec)",
            "description: isNativeSkill(skill)",
            "await deleteSkill(skill.skill_id);",
            "setSelectedSkillIds((current) => current.filter((id) => id !== skill.skill_id));",
            "function requestDeleteSelectedSkills()",
            "const hasNativeSkills = targets.some(isNativeSkill);",
            "const hasInstalledSkills = targets.some(isInstalledSkill);",
            "setSelectedSkillIds((current) => current.filter((id) => !targetIds.has(id)));",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useSkillImportActions.ts",
        [
            "export function useSkillImportActions",
            "async function importSkillSourceList(rawSources: string[]): Promise<SkillImportRefreshOptions | void>",
            "const sources = normalizeSkillSources(rawSources);",
            "const imported = await importSkill(source, skillTargetFolderId);",
            "const result = await syncNativeSkills();",
            "setSkillImportResults(syncResultsToImportResults(result.results || []));",
            "const result = await installSkillCommand(command, skillTargetFolderId);",
            "setSkillImportResults(syncResultsToImportResults(result.sync.results));",
            "throw new Error(result.stderr || result.stdout || `安装命令退出：${result.returncode ?? 'unknown'}`);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useSkillSourceInputActions.ts",
        [
            "export function useSkillSourceInputActions",
            "async function pickSkillSources()",
            "const selected = await chooseSkillSources();",
            "if (selected.length) await runAction(() => importSkillSourceList(selected), '导入 Skills');",
            "setError(err instanceof Error ? err.message : '选择 Skill 文件失败');",
            "function dropSkillSources(event: DragEvent<HTMLElement>)",
            "event.preventDefault();",
            ".map((file) => (file as File & { path?: string }).path || file.name)",
            "void runAction(() => importSkillSourceList(filePaths), '导入 Skills');",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useSkillFolderManagement.ts",
        [
            "export function useSkillFolderManagement",
            "const folder = await createSkillFolder({ name });",
            "await updateSkillFolder(folderId, { name });",
            "await deleteSkillFolder(folderId, { deleteSkills });",
            "function setSkillFolderDeleteMode(folderId: string, mode: SkillFolderDeleteMode | null)",
            "function requestDeleteSkillFolder(folder: SkillFolderSpec, deleteSkills: boolean)",
            "async () => deleteSkillFolderById(folder.folder_id, false)",
            "setSkillTargetFolderId(folder.folder_id);",
            "setSkillLibraryFolderFilter(folder.folder_id);",
            "navigateTo('agents', { tab: 'skills' }, ['run', 'tab']);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunHistoryManagement.ts",
        [
            "deleteRun",
            "function pruneDeletedRunState(deletedRunIds: Set<string>)",
            "setRunDetailCache((current) => current.filter((run) => !deletedRunIds.has(run.run_id)))",
            "clearRunEventReplay(deletedRunIds);",
            "childRunIds.some((runId) => !deletedRunIds.has(runId))",
            "const result = await deleteRun(run.run_id);",
            "setSelectedRunIds((current) => current.filter((id) => !deletedRunIds.has(id)))",
            "navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunLaunchActions.ts",
        [
            "export function useRunLaunchActions",
            "const run = await createAgentRun(agentId, goal);",
            "const run = await createWorkflowRun(saved.workflow_id, goal);",
            "const createRunFromTarget = useCallback(async (): Promise<RunLaunchActionRefreshOptions | void> => {",
            "? await createAgentRun(target.id, goal)",
            ": await createWorkflowRun(target.id, goal);",
            "const run = await rerunRun(selectedRun.run_id);",
            "upsertRunDetailCache([run]);",
            "await refreshRunGroupsForRuns([run]);",
            "openRunDetail(run.run_id, { revealInHistory: true });",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunEventReplay.ts",
        [
            "type RunEventReplayState = {",
            "const defaultRunEventReplayPageSize = 200;",
            "getRunEvents(runId, 0, pageSize)",
            "events: current[runId]?.events || [],",
            "hasMore: events.length >= limit,",
            "error: err instanceof Error ? err.message : '读取 RunEvent replay 失败',",
            "const afterSequence = currentEvents.reduce(",
            "getRunEvents(runId, afterSequence, pageSize)",
            "const events = mergeRunEventReplayPages(previous?.events || currentEvents, incomingEvents);",
            "hasMore: incomingEvents.length >= limit,",
            "error: err instanceof Error ? err.message : '读取更多 RunEvent replay 失败',",
            "for (const runIdToDelete of runIds)",
            "delete next[runIdToDelete];",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentEditorPanel.tsx",
        [
            "系统 Agent 由 oha-yachiyo 管理",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "<h2>Run Detail</h2>",
            "ApprovalInspector",
            "ArtifactInspector",
            "ToolCallInspector",
            "selectedRun.task_id ? <code>Task {selectedRun.task_id}</code> : null",
            "selectedRun.session_id ? <code>Session {selectedRun.session_id}</code> : null",
            "selectedRun.task_run_link_run_status ? <span>Task link {runStatusLabel(selectedRun.task_run_link_run_status)}</span> : null",
            "selectedRun.task_run_link_last_event_sequence !== undefined && selectedRun.task_run_link_last_event_sequence !== null",
            "Task link updated {formatRunDate(selectedRun.task_run_link_updated_at || selectedRun.task_run_link_created_at)}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ApprovalInspector.tsx",
        [
            "Approval Required",
            "RunApprovalRequest",
            "RuntimeApprovalCard",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunTimeline.tsx",
        [
            "RunEvent replay facts",
            "disabled={replayLoading}",
            "{replayLoading ? '加载中...' : '加载更多 RunEvent'}",
            "加载更多 RunEvent",
            "Execution ·",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/utils/runTimeline.ts",
        [
            "export function runEventReplayToTimelineEvent(event: RunEventSpec)",
            "export function mergeRunEventReplayPages(",
            "const bySequence = new Map<number, RunEventSpec>();",
            "incoming.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));",
            "if (name === 'run.started') return 'Run 已启动';",
            "if (name === 'model.output.completed') return '模型输出完成';",
            "if (name === 'agent.tool.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';",
            "if (name === 'agent.tool.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';",
            "if (name === 'skill.dispatch.read') return detail ? `Skill 调度 · ${detail}` : 'Skill 调度';",
            "if (name === 'memory.write.add') return detail ? `Memory 新增 · ${detail}` : 'Memory 新增';",
            "if (name.startsWith('skill.') || name.startsWith('memory.')) return 'tool';",
            "if (name === 'approval.timeout') return '审批已超时';",
            "if (name === 'agent.run.resumed') return 'Agent 已继续执行';",
            "if (name === 'agent.run.cancelled') return 'Agent 已取消';",
            "if (name === 'run.rerun.started') return '从原 Run 重跑';",
            "if (name === 'group.member.started') return detail ? `群组成员启动 · ${detail}` : '群组成员启动';",
            "if (name === 'group.member.completed') return detail ? `群组成员完成 · ${detail}` : '群组成员完成';",
            "if (name === 'workflow.node.artifact') return detail ? `产物节点 · ${detail}` : '产物节点';",
            "if (name === 'workflow.edge.followed') return detail ? `Workflow 路由 · ${detail}` : 'Workflow 路由';",
            "typeof payload.workflow_node_label === 'string'",
        ],
    )


def test_agent_studio_exposes_runtime_memory_and_future_task_management() -> None:
    _assert_contains(
        "apps/frontend/src/lib/agents.ts",
        [
            "export type MemorySpec = {",
            "export type FutureTaskSpec = {",
            "export async function listMemories()",
            "'/yachiyo/studio/memories'",
            "'/ui/memories'",
            "export async function deleteMemory(",
            "apiDelete(`/yachiyo/studio/memories/${encodeURIComponent(memoryId)}${query}`)",
            "apiDelete(`/ui/memories/${encodeURIComponent(memoryId)}${query}`)",
            "export async function listFutureTasks()",
            "'/ui/future-tasks'",
            "export async function cancelFutureTask(",
            "/ui/future-tasks/${encodeURIComponent(futureTaskId)}/cancel",
            "export async function triggerDueFutureTasks()",
            "'/ui/future-tasks/trigger-due'",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "listMemories",
        [
            "apiGet<{ memories?: MemorySpec[] }>('/yachiyo/studio/memories')",
            "apiGet<{ memories?: MemorySpec[] }>('/ui/memories')",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/lib/agents.ts",
        "deleteMemory",
        [
            "apiDelete(`/yachiyo/studio/memories/${encodeURIComponent(memoryId)}${query}`)",
            "apiDelete(`/ui/memories/${encodeURIComponent(memoryId)}${query}`)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "const [memories, setMemories] = useState<MemorySpec[]>([]);",
            "const [futureTasks, setFutureTasks] = useState<FutureTaskSpec[]>([]);",
            "listMemories()",
            "listFutureTasks()",
            "setMemories(nextMemories);",
            "setFutureTasks(nextFutureTasks);",
            "useRuntimeMemoryManagement",
            "requestDeleteMemory",
            "requestCancelFutureTask",
            "triggerDueFutureTaskRuns",
            "RuntimeMemoryPanel",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRuntimeMemoryManagement.ts",
        [
            "export function useRuntimeMemoryManagement",
            "function requestDeleteMemory(memory: MemorySpec)",
            "await deleteMemory(memory.memory_id, 'studio_user_delete');",
            "function requestCancelFutureTask(futureTask: FutureTaskSpec)",
            "await cancelFutureTask(futureTask.future_task_id, 'studio_user_cancel');",
            "async function triggerDueFutureTaskRuns(): Promise<RuntimeMemoryRefreshOptions>",
            "const result = await triggerDueFutureTasks();",
            "openRunDetail(firstRunId, { revealInHistory: true });",
            "return { selectedRunId: firstRunId, statusMessage };",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RuntimeMemoryPanel.tsx",
        [
            "data-testid=\"agent-runtime-memory\"",
            "data-testid=\"agent-memory-list\"",
            "data-testid=\"agent-memory-delete\"",
            "data-testid=\"agent-future-task-list\"",
            "data-testid=\"agent-future-task-trigger-due\"",
            "data-testid=\"agent-future-task-cancel\"",
            "data-testid=\"agent-future-task-open-run\"",
            "futureTaskStatusLabel",
            "futureTaskStatusTone",
        ],
    )
    _assert_contains(
        "apps/frontend/src/lib/view.ts",
        [
            "['agents', 'groups', 'skills', 'skill-groups', 'workflows', 'runs', 'memory']",
        ],
    )
    _assert_contains(
        "apps/frontend/src/styles/app.css",
        [
            ".agent-runtime-grid",
            ".runtime-management-list",
            ".runtime-management-row",
            ".runtime-management-actions",
        ],
    )


def test_agent_studio_exposes_stable_e2e_selectors_for_run_detail_and_approval_flow() -> None:
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "data-testid=\"agent-run-detail\"",
            "data-run-id={selectedRun.run_id}",
            "data-run-kind={selectedRun.kind}",
            "data-run-status={selectedRun.status}",
            "data-run-group-id={selectedRun.run_group_id || ''}",
            "data-session-id={selectedRun.session_id || ''}",
            "data-task-id={selectedRun.task_id || ''}",
            "data-testid=\"agent-run-detail-hero\"",
            "data-testid=\"agent-run-detail-meta\"",
            "data-testid=\"agent-run-detail-prepare-rerun\"",
            "data-testid=\"agent-run-detail-rerun\"",
            "data-testid=\"agent-run-detail-cancel\"",
            "data-testid=\"agent-run-detail-open-parent-run\"",
            "data-run-id={selectedWorkflowParentRunId}",
            "data-run-status={selectedWorkflowParentRun?.status || ''}",
            "data-testid=\"agent-run-detail-open-workflow-studio\"",
            "ApprovalInspector",
            "ToolCallInspector",
            "data-testid=\"agent-run-detail-workflow-child-approval\"",
            "data-testid=\"agent-run-detail-workflow-child-approval-actions\"",
            "data-testid=\"agent-run-detail-workflow-child-approve\"",
            "data-testid=\"agent-run-detail-workflow-child-reject\"",
            "data-testid=\"agent-run-detail-workflow-child-cancel\"",
            "data-testid=\"agent-run-detail-workflow-child-open-run\"",
            "data-run-id={selectedWorkflowApprovalChildRunId}",
            "data-run-status={selectedWorkflowApprovalChildRun?.status || 'approval_required'}",
            "data-testid=\"agent-run-detail-task\"",
            "data-testid=\"agent-run-detail-result\"",
            "data-testid=\"agent-run-detail-workflow-steps\"",
            "data-testid=\"agent-run-detail-workflow-step\"",
            "data-workflow-step-key={step.key}",
            "data-workflow-step-kind={step.kind}",
            "data-workflow-step-node-id={step.nodeId || ''}",
            "data-workflow-step-status={childStatus}",
            "data-testid=\"agent-run-detail-workflow-step-open-run\"",
            "data-run-id={step.childRunId}",
            "data-run-status={childStatus}",
            "ArtifactInspector",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ApprovalInspector.tsx",
        [
            "data-testid=\"agent-run-detail-approval\"",
            "data-testid=\"agent-run-detail-approval-approve\"",
            "data-testid=\"agent-run-detail-approval-reject\"",
            "RuntimeApprovalCard",
            "RunApprovalRequest",
            "actions={(",
            "actionsClassName=\"run-approval-actions\"",
            "actionsTestId=\"agent-run-detail-approval-actions\"",
            'testId="agent-run-detail-approval-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ToolCallInspector.tsx",
        [
            "data-testid=\"agent-run-detail-tool-calls\"",
            "data-testid=\"agent-run-detail-tool-call-list\"",
            "agent-run-detail-tool-call-card",
            "RuntimeToolCallCard",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/ArtifactInspector.tsx",
        [
            "Artifacts ·",
            "data-testid=\"agent-run-detail-artifacts\"",
            "data-testid=\"agent-run-detail-artifact-list\"",
            "data-testid=\"agent-run-detail-artifact\"",
            "data-artifact-kind={artifactKind}",
            "data-artifact-path={path}",
            "data-artifact-source-label={sourceLabel}",
            "data-artifact-source-run-id={sourceRunId}",
            "data-testid=\"agent-run-detail-artifact-preview\"",
            "RuntimeArtifactPreview",
            'testId="agent-run-detail-artifact-preview-card"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunLauncherPanel.tsx",
        [
            "data-testid=\"agent-run-history-manage\"",
            "data-testid=\"agent-run-history-bulk-actions\"",
            "data-testid=\"agent-run-history-select-all\"",
            "data-testid=\"agent-run-history-clear-selection\"",
            "data-testid=\"agent-run-history-delete-selected\"",
            "data-testid=\"agent-run-history-finish-management\"",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunHistoryList.tsx",
        [
            "data-testid=\"agent-run-history-row\"",
            "data-testid=\"agent-run-history-open-run\"",
            "data-testid=\"agent-run-history-select-run\"",
            "data-run-id={run.run_id}",
            "data-run-kind={run.kind}",
            "data-run-status={run.status}",
            "data-run-group-id={run.run_group_id || ''}",
            "data-task-id={run.task_id || ''}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunTimeline.tsx",
        [
            "data-testid=\"agent-run-detail-execution\"",
            "testId=\"agent-run-detail-execution-events\"",
            "eventTestId=\"agent-run-detail-execution-event\"",
            "childRunTestId=\"agent-run-detail-execution-open-child-run\"",
            "data-testid=\"agent-run-detail-load-more-events\"",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/runtime-shared/components/RuntimeTimelineEventList.tsx",
        [
            "data-testid={testId}",
            "data-testid={eventTestId}",
            "data-run-event={eventName}",
            "data-run-event-id={eventId}",
            "data-run-event-run-id={eventRunId}",
            "data-run-event-sequence={eventSequence}",
            "data-run-event-schema-version={defaultEventSchemaVersion(event)}",
            "data-run-event-actor={defaultEventActor(event)}",
            "data-run-event-visibility={defaultEventVisibility(event)}",
            "data-run-event-sensitivity={defaultEventSensitivity(event)}",
            "data-run-event-status={eventStatus || ''}",
            "data-run-event-tone={eventTone}",
            "data-child-run-id={childRunId || ''}",
            "data-testid={childRunTestId || `${eventTestId}-open-child-run`}",
        ],
    )


def test_workflow_studio_exposes_stable_e2e_selectors_for_edit_and_run_flow() -> None:
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "WorkflowEditorPanel",
            "onRunWorkflow={() => void runAction(runCurrentWorkflow, '保存并运行 Workflow')}",
            "onSaveWorkflow={() => void runAction(saveWorkflow, '保存 Workflow')}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/WorkflowEditorPanel.tsx",
        [
            "data-testid=\"workflow-studio\"",
            "data-testid=\"workflow-list\"",
            "data-testid=\"workflow-list-item\"",
            "data-testid=\"workflow-list-open\"",
            "data-testid=\"workflow-list-checkbox\"",
            "data-testid=\"workflow-list-manage\"",
            "data-testid=\"workflow-bulk-actions\"",
            "data-testid=\"workflow-select-all\"",
            "data-testid=\"workflow-clear-selection\"",
            "data-testid=\"workflow-delete-selected\"",
            "data-testid=\"workflow-finish-management\"",
            "data-testid=\"workflow-new\"",
            "data-testid=\"workflow-editor\"",
            "data-testid=\"workflow-toolbar\"",
            "data-testid=\"workflow-name-input\"",
            "data-testid=\"workflow-description-input\"",
            "data-testid=\"workflow-enabled-toggle\"",
            "data-testid=\"workflow-template-button\"",
            "data-testid=\"workflow-add-agent-node\"",
            "data-testid=\"workflow-add-approval-node\"",
            "data-testid=\"workflow-add-artifact-node\"",
            "data-testid=\"workflow-add-workflow-node\"",
            "data-testid=\"workflow-add-loop-node\"",
            "data-testid=\"workflow-save\"",
            "data-testid=\"workflow-delete\"",
            "data-testid=\"workflow-agent-palette\"",
            "data-testid=\"workflow-agent-palette-item\"",
            "WorkflowCanvas",
            "data-testid=\"workflow-node-settings\"",
            "data-testid=\"workflow-validation\"",
            "data-testid=\"workflow-node-setting-row\"",
            "data-testid=\"workflow-node-label-input\"",
            "data-testid=\"workflow-node-agent-select\"",
            "data-testid=\"workflow-node-task-input\"",
            "data-testid=\"workflow-node-artifact-path-input\"",
            "data-testid=\"workflow-node-approval-criteria-input\"",
            "data-testid=\"workflow-node-loop-condition-input\"",
            "data-testid=\"workflow-node-loop-max-iterations-input\"",
            "data-testid=\"workflow-node-workflow-select\"",
            "data-testid=\"workflow-node-workflow-task-input\"",
            "data-testid=\"workflow-node-remove\"",
            "data-testid=\"workflow-quick-run\"",
            "data-testid=\"workflow-run-goal-input\"",
            "data-testid=\"workflow-run-preview\"",
            "data-testid=\"workflow-run-preview-step\"",
            "data-testid=\"workflow-save-and-run\"",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/WorkflowCanvas.tsx",
        [
            "data-testid=\"workflow-canvas\"",
            "<ReactFlow",
            "<MiniMap />",
            "<Controls />",
            "<Background />",
        ],
    )


def test_workflow_studio_save_and_run_uses_persisted_workflow_id() -> None:
    _assert_function_contains(
        "apps/frontend/src/features/agent-studio/hooks/useWorkflowSaveActions.ts",
        "saveWorkflowDraft",
        [
            "if (workflowErrors.length)",
            "const saved = selectedWorkflow ? await updateWorkflow(selectedWorkflow.workflow_id, request) : await createWorkflow(request);",
            "setSelectedWorkflowId(saved.workflow_id);",
            "return saved;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunLaunchActions.ts",
        [
            "const runCurrentWorkflow = useCallback(async (): Promise<RunLaunchActionRefreshOptions> => {",
            "const saved = await saveWorkflowDraft();",
            "const run = await createWorkflowRun(saved.workflow_id, goal);",
            "setWorkflowRunGoal('');",
            "setRunTarget(saved.workflow_id);",
            "openRunDetail(run.run_id, { revealInHistory: true });",
            "return { selectedWorkflowId: saved.workflow_id, runTarget: saved.workflow_id, selectedRunId: run.run_id };",
        ],
    )


def test_workflow_save_run_ui_smoke_uses_studio_route_and_saved_workflow_id() -> None:
    smoke_script = "scripts/smoke_workflow_save_run_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/agents/workflows",
            "data-testid=\"workflow-studio\"",
            "data-testid=\"workflow-new\"",
            "data-testid=\"workflow-agent-palette-item\"",
            "data-testid=\"workflow-add-approval-node\"",
            "data-testid=\"workflow-add-artifact-node\"",
            "data-testid=\"workflow-node-approval-criteria-input\"",
            "data-testid=\"workflow-node-artifact-path-input\"",
            "data-testid=\"workflow-run-goal-input\"",
            "data-testid=\"workflow-save-and-run\"",
            "request.method === 'POST' && url.pathname === '/yachiyo/studio/workflows'",
            "request.method === 'POST' && url.pathname === '/ui/workflow-runs'",
            "createdWorkflowRunRequest.workflow_id !== WORKFLOW_ID",
            "createdWorkflowRunRequest.client_run_id",
            "`/ui/runs/${RUN_ID}/artifacts/${WORKFLOW_ARTIFACT_PATH}`",
            "`/ui/runs/${APPROVAL_RUN_ID}/approval/approve`",
            "`/ui/runs/${APPROVAL_RUN_ID}/artifacts/${APPROVAL_ARTIFACT_PATH}`",
            "assertMockBridgeContract",
            "`/ui/runs/${RUN_ID}`",
            "`/ui/runs/${APPROVAL_RUN_ID}`",
            "`/yachiyo/studio/runs/${RUN_ID}/events`",
            "`/yachiyo/studio/runs/${APPROVAL_RUN_ID}/events`",
            "task_id: WORKFLOW_TASK_ID",
            "session_id: WORKFLOW_SESSION_ID",
            "task_id: APPROVAL_TASK_ID",
            "session_id: APPROVAL_SESSION_ID",
            "document.querySelector('[data-testid=\"agent-run-detail\"]')?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_TASK_ID)}",
            "document.querySelector('[data-testid=\"agent-run-detail\"]')?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_SESSION_ID)}",
            "detail?.getAttribute('data-run-status') === 'approval_required'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}",
            "detail?.getAttribute('data-run-status') === 'completed'\n      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}",
            "detail?.getAttribute('data-session-id') === ${JSON.stringify(APPROVAL_SESSION_ID)}",
            "workflow.run.started",
            "workflow.node.agent.completed",
            "workflow.node.approval_required",
            "workflow.node.approval_approved",
            "workflow.node.artifact",
            "workflow.run.completed",
            "artifactEvent?.textContent.includes",
            "completedEvent?.textContent.includes",
            "approvalEvent?.textContent.includes",
            "WORKFLOW_ARTIFACT_PATH",
            "APPROVAL_CRITERIA",
            "APPROVAL_ARTIFACT_PATH",
            "Artifact node output preview.",
            "Approved artifact preview.",
            "saved workflow did not include artifact node path",
            "saved approval workflow did not include criteria",
            "approval workflow approve route was not called",
            "Workflow save-and-run UI smoke completed",
            "Workflow approval save-and-run UI smoke completed",
        ],
    )


def test_workflow_management_ui_smoke_uses_bulk_and_single_delete_paths() -> None:
    smoke_script = "scripts/smoke_workflow_management_ui.mjs"
    _assert_contains(
        smoke_script,
        [
            "#/agents/workflows",
            "data-testid=\"workflow-studio\"",
            "data-testid=\"workflow-list\"",
            "data-testid=\"workflow-list-item\"",
            "data-testid=\"workflow-list-manage\"",
            "data-testid=\"workflow-bulk-actions\"",
            "data-testid=\"workflow-select-all\"",
            "data-testid=\"workflow-clear-selection\"",
            "data-testid=\"workflow-list-checkbox\"",
            "data-testid=\"workflow-delete-selected\"",
            "data-testid=\"workflow-finish-management\"",
            "data-testid=\"workflow-list-open\"",
            "data-testid=\"workflow-editor\"",
            "data-testid=\"workflow-delete\"",
            "data-testid=\"confirm-dialog\"",
            "data-testid=\"confirm-action\"",
            "url.pathname.startsWith('/yachiyo/studio/workflows/')",
            "url.pathname.startsWith('/ui/workflows/')",
            "deletedWorkflowIds.push(workflowId)",
            "workflow select all",
            "workflow clear selection",
            "workflow selection controls verified",
            "Workflow Management Smoke A",
            "Workflow Management Smoke B",
            "assertMockBridgeContract",
            "unexpected deleted workflow ids",
        ],
    )


def test_agent_studio_agents_ui_smoke_uses_definition_crud_paths() -> None:
    smoke_script = "scripts/smoke_agent_studio_agents_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            'data-testid="agent-studio-agents"',
            "AgentListPanel",
            "AgentEditorPanel",
            "selectedAgentReadOnly",
            "onSetSelectedAgentIds={setSelectedAgentIds}",
            "系统 Agent 只能查看，不能从 Agent Studio 直接运行。",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentDefinitions.ts",
        [
            "const deletableAgentIds = useMemo(",
            "pruneSelectedIds(current, deletableAgentIds)",
            "if (!deletableAgentIds.includes(agentId)) return;",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentEditorPanel.tsx",
        [
            "AgentSkillMountsPanel",
            'data-testid="agent-editor"',
            'data-testid="agent-name-input"',
            'data-testid="agent-nickname-input"',
            'data-testid="agent-avatar-select"',
            'data-testid="agent-avatar-clear"',
            'data-testid="agent-description-input"',
            'data-testid="agent-category-input"',
            'data-testid="agent-output-contract-select"',
            'data-testid="agent-instructions-input"',
            'data-testid="agent-persona-input"',
            'data-testid="agent-save"',
            'data-testid="agent-delete"',
            "readOnly={selectedAgentReadOnly}",
            "disabled={selectedAgentReadOnly || draft.model_mode === 'custom_api'}",
            "disabled={busy || selectedAgentReadOnly}",
            "系统 Agent 由 oha-yachiyo 管理，可查看但不能编辑、删除或直接挂载 Skill。",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentListPanel.tsx",
        [
            'data-testid="agent-new"',
            'data-testid="agent-list"',
            'data-testid="agent-list-item"',
            'data-testid="agent-list-open"',
            'data-testid="agent-management-toggle"',
            'data-testid="agent-list-select-checkbox"',
            'data-testid="agent-select-all"',
            'data-testid="agent-clear-selection"',
            'data-testid="agent-delete-selected"',
            'data-testid="agent-management-done"',
            "data-agent-deletable={!agent.system && agent.deletable !== false ? 'true' : 'false'}",
            "disabled={busy || !agentManagementMode || agent.system || agent.deletable === false}",
            "onSetSelectedAgentIds(allAgentsSelected ? [] : deletableAgentIds)",
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/agents/agents",
            "request.method === 'POST' && url.pathname === '/yachiyo/studio/agents'",
            "request.method === 'POST' && url.pathname === '/ui/agents'",
            "request.method === 'PATCH' && url.pathname === `/ui/agents/${CREATED_AGENT_ID}`",
            "request.method === 'DELETE' && url.pathname === `/yachiyo/studio/agents/${CREATED_AGENT_ID}`",
            "request.method === 'DELETE' && url.pathname === `/ui/agents/${CREATED_AGENT_ID}`",
            "data-testid=\"agent-studio-agents\"",
            r'''data-testid=\\"agent-new\\"''',
            "data-testid=\"agent-name-input\"",
            "data-testid=\"agent-avatar-select\"",
            "data-testid=\"agent-avatar-clear\"",
            "data-testid=\"agent-output-contract-select\"",
            "data-testid=\"agent-save\"",
            "data-testid=\"agent-list-item\"",
            r'''data-testid=\\"agent-management-toggle\\"''',
            "data-testid=\"agent-list-select-checkbox\"",
            "data-testid=\"agent-select-all\"",
            r'''data-testid=\\"agent-clear-selection\\"''',
            "data-testid=\"agent-delete-selected\"",
            r'''data-testid=\\"agent-management-done\\"''',
            "data-testid=\"agent-delete\"",
            "data-testid=\"confirm-action\"",
            "builtin:yachiyo-main",
            "system Agent read-only guard verified",
            "system Agent bulk selection guard verified",
            "agent select all excludes system Agent",
            "readOnlyFields.every((field) => field?.readOnly)",
            "outputContract?.disabled",
            "avatarSelect?.disabled",
            "quickRunGoal?.disabled",
            "!document.querySelector('[data-testid=\"agent-name-input\"]')?.readOnly",
            "quickRun?.getAttribute('title')?.includes('系统 Agent 只能查看')",
            "inlineNotes.some((text) => text.includes('系统 Agent 由 oha-yachiyo 管理'))",
            "assertMockBridgeContract",
            "window.__ohaAgentAvatarPickerCalls",
            "chooseAvatarImage: async () =>",
            "agent avatar cleared",
            "agent avatar reselected",
            "expected Agent avatar picker to be called twice after reselect",
            "createAgentRequest.avatar_url !== AVATAR_DATA_URL",
            "createAgentRequest.output_contract !== 'report'",
            "updateAgentRequest.name !== UPDATED_NAME",
            "deletedAgentId !== CREATED_AGENT_ID",
        ],
    )


def test_agent_studio_skills_ui_smoke_uses_skill_library_paths() -> None:
    smoke_script = "scripts/smoke_agent_studio_skills_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            'data-testid="skill-library"',
            "SkillImportPanel",
            "SkillLibraryPanel",
            "onInstallSkill={() => void runAction(installSkillFromCommand, '安装 Skill')}",
            "onSyncNativeSkillLibrary={() => void runAction(syncNativeSkillLibrary, '同步 Native Skills')}",
            "onMoveSkillFolder={(skill, folderId) => void runAction(async () => {",
            "onToggleSkillEnabled={(skill) => void runAction(async () => {",
        ],
    )
    _assert_not_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "function SkillCard",
            'data-testid="skill-library-panel"',
            'data-testid="skill-list"',
        ],
    )
    _assert_not_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        ['data-testid="skill-import-panel"'],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/SkillImportPanel.tsx",
        [
            "export function SkillImportPanel",
            'data-testid="skill-import-panel"',
            'data-testid="skill-import-folder-select"',
            'data-testid="skill-install-command-input"',
            'data-testid="skill-install-command-submit"',
            'data-testid="skill-native-sync"',
            'data-testid="skill-source-root"',
            'data-testid="skill-import-results"',
            'data-testid="skill-import-result"',
            'data-testid="skill-source-picker"',
            "skillResultStatusLabel(result.status)",
            "skillSourceTypeLabel(source.source_type)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/SkillLibraryPanel.tsx",
        [
            "export function SkillLibraryPanel",
            'data-testid="skill-library-panel"',
            'data-testid="skill-filter-installed"',
            'data-testid="skill-filter-native"',
            'data-testid="skill-library-folder-filter"',
            'data-testid="skill-library-search"',
            'data-testid="skill-list"',
            "SkillCard",
            "onSetSelectedSkillIds(",
            "onMoveSkillFolder(skill, folderId)",
            "onToggleSkillEnabled(skill)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/SkillCard.tsx",
        [
            "export function SkillCard",
            'data-testid="skill-card"',
            'data-testid="skill-card-select"',
            'data-testid="skill-card-enabled-toggle"',
            'data-testid="skill-card-folder-select"',
            'data-testid="skill-card-open-location"',
            'data-testid="skill-card-delete"',
            "skillPathLabel(skill)",
            "skillSourceLabel(skill)",
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/agents/skills",
            "request.method === 'POST' && url.pathname === '/ui/skills/sync'",
            "request.method === 'POST' && url.pathname === '/ui/skills/import'",
            "request.method === 'POST' && url.pathname === '/ui/skills/install'",
            "request.method === 'PATCH' && url.pathname === `/ui/skills/${SKILL_ID}`",
            "request.method === 'DELETE' && url.pathname === `/ui/skills/${SKILL_ID}`",
            "data-testid=\"skill-library\"",
            "data-testid=\"skill-native-sync\"",
            "data-testid=\"skill-import-result\"",
            "data-testid=\"skill-source-root\"",
            "data-testid=\"skill-import-folder-select\"",
            "data-testid=\"skill-source-picker\"",
            "data-testid=\"skill-install-command-input\"",
            "data-testid=\"skill-install-command-submit\"",
            "data-testid=\"skill-card\"",
            "data-testid=\"skill-card-enabled-toggle\"",
            "data-testid=\"skill-card-folder-select\"",
            "data-testid=\"skill-card-open-location\"",
            "data-testid=\"skill-card-delete\"",
            "data-testid=\"confirm-action\"",
            "assertMockBridgeContract",
            "window.__ohaSkillOpenPathCalls",
            "openPath: async (targetPath)",
            "window.__ohaSkillOpenPathCalls[0] === '/tmp/oha-yachiyo/skills/agent-studio-smoke'",
            "window.__ohaSkillSourcesPickerCalls",
            "chooseSkillSources: async () =>",
            "importSkillRequests.length !== 1",
            "importSkillRequest.source_path !== PICKED_SKILL_SOURCE",
            "importSkillRequest.folder_id !== FOLDER_B_ID",
            "installSkillRequest.command !== INSTALL_COMMAND",
            "installSkillRequest.folder_id !== FOLDER_A_ID",
            "request.enabled === false",
            "request.folder_id === FOLDER_B_ID",
            "deletedSkillId !== SKILL_ID",
        ],
    )


def test_agent_studio_skill_mount_ui_smoke_uses_attach_detach_and_bulk_paths() -> None:
    smoke_script = "scripts/smoke_agent_studio_skill_mount_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "AgentEditorPanel",
            "useAgentSkillMountActions",
            "mountVisibleSkills",
            "toggleAgentSkillMount",
            "unmountVisibleSkills",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useAgentSkillMountActions.ts",
        [
            "function toggleAgentSkillMount(skill: SkillSpec, mounted: boolean)",
            "if (selectedAgentReadOnly) {",
            "setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');",
            "if (mounted) await detachSkill(draftAgentId, skill.skill_id);",
            "else await attachSkill(draftAgentId, skill.skill_id);",
            "await updateAgent(draftAgentId, { skill_ids: nextSkillIds });",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentEditorPanel.tsx",
        [
            "AgentSkillMountsPanel",
            "onMountVisibleSkills={onMountVisibleSkills}",
            "onUnmountVisibleSkills={onUnmountVisibleSkills}",
            "onToggleSkillMount={onToggleSkillMount}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/AgentSkillMountsPanel.tsx",
        [
            'data-testid="agent-skill-mounts"',
            'data-testid="agent-skill-mount-summary"',
            'data-testid="agent-skill-mount-filter-installed"',
            'data-testid="agent-skill-mount-filter-native"',
            'data-testid="agent-skill-mount-folder-filter"',
            'data-testid="agent-skill-mount-search"',
            'data-testid="agent-skill-mount-visible-count"',
            'data-testid="agent-skill-mount-all-visible"',
            'data-testid="agent-skill-unmount-all-visible"',
            'data-testid="agent-skill-mount-grid"',
            'data-testid="agent-skill-mount-item"',
            "data-skill-mounted={mounted ? 'true' : 'false'}",
            "disabled={busy || selectedAgentReadOnly}",
            "onToggleSkillMount(skill, mounted)",
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/agents/agents",
            "request.method === 'POST' && url.pathname === `/ui/agents/${AGENT_ID}/skills`",
            "request.method === 'DELETE' && url.pathname === `/ui/agents/${AGENT_ID}/skills/${SKILL_A_ID}`",
            "request.method === 'PATCH' && url.pathname === `/ui/agents/${AGENT_ID}`",
            "data-testid=\"agent-list-open\"",
            "data-testid=\"agent-skill-mounts\"",
            "data-testid=\"agent-skill-mount-summary\"",
            "data-testid=\"agent-skill-mount-filter-native\"",
            "data-testid=\"agent-skill-mount-filter-installed\"",
            "data-testid=\"agent-skill-mount-search\"",
            "data-testid=\"agent-skill-mount-folder-filter\"",
            "data-testid=\"agent-skill-mount-visible-count\"",
            "data-testid=\"agent-skill-mount-item\"",
            "data-testid=\"agent-skill-mount-all-visible\"",
            "data-testid=\"agent-skill-unmount-all-visible\"",
            "data-skill-mounted",
            "builtin:yachiyo-main",
            "system Agent skill mount read-only guard verified",
            "system Agent Skill mount mutation was attempted",
            "skillA?.disabled",
            "skillB?.disabled",
            "mountAll?.disabled",
            "unmountAll?.disabled",
            "native skill mount filter",
            "installed skill mount filter",
            "skill mount search filter",
            "skill mount uncategorized folder filter",
            "skill mount folder filter",
            "skill mount filters verified",
            "assertMockBridgeContract",
            "attachSkillRequests[0].skill_id !== SKILL_A_ID",
            "detachSkillRequests[0] !== SKILL_A_ID",
            "request.skill_ids.length === 2",
            "request.skill_ids.length === 0",
        ],
    )


def test_agent_studio_skill_folders_ui_smoke_uses_folder_management_paths() -> None:
    smoke_script = "scripts/smoke_agent_studio_skill_folders_ui.mjs"
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "SkillFolderPanel",
            "useSkillFolderManagement",
            "createSkillFolderFromDraft",
            "updateSkillFolderFromDraft",
            "requestDeleteSkillFolder",
            "onCreateSkillFolder={() => void runAction(createSkillFolderFromDraft, '创建 Skill 文件夹')}",
            "onUpdateSkillFolder={(folderId) => {",
        ],
    )
    _assert_not_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        ['data-testid="skill-folder-page"'],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/SkillFolderPanel.tsx",
        [
            "export function SkillFolderPanel",
            'data-testid="skill-folder-page"',
            'data-testid="skill-folder-name-input"',
            'data-testid="skill-folder-create"',
            'data-testid="skill-folder-list"',
            'data-testid="skill-folder-row"',
            'data-testid="skill-folder-edit-name-input"',
            'data-testid="skill-folder-save-rename"',
            'data-testid="skill-folder-cancel-rename"',
            'data-testid="skill-folder-rename"',
            'data-testid="skill-folder-open"',
            'data-testid="skill-folder-delete-with-skills"',
            'data-testid="skill-folder-delete"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useSkillFolderManagement.ts",
        [
            "const folder = await createSkillFolder({ name });",
            "await updateSkillFolder(folderId, { name });",
            "async () => deleteSkillFolderById(folder.folder_id, false)",
            "setSkillTargetFolderId(folder.folder_id);",
            "setSkillLibraryFolderFilter(folder.folder_id);",
        ],
    )
    _assert_contains(
        smoke_script,
        [
            "#/agents/skill-groups",
            "request.method === 'POST' && url.pathname === '/ui/skill-folders'",
            "request.method === 'PATCH' && url.pathname === `/ui/skill-folders/${FOLDER_ID}`",
            "request.method === 'DELETE' && url.pathname === `/ui/skill-folders/${FOLDER_ID}`",
            "data-testid=\"skill-folder-page\"",
            "data-testid=\"skill-folder-name-input\"",
            "data-testid=\"skill-folder-create\"",
            "data-testid=\"skill-folder-row\"",
            "data-testid=\"skill-folder-rename\"",
            "data-testid=\"skill-folder-edit-name-input\"",
            "data-testid=\"skill-folder-save-rename\"",
            "data-testid=\"skill-folder-open\"",
            "data-testid=\"skill-import-folder-select\"",
            "data-testid=\"skill-library-folder-filter\"",
            "data-testid=\"skill-folder-delete\"",
            "data-testid=\"confirm-action\"",
            "assertMockBridgeContract",
            "createFolderRequest.name !== CREATED_FOLDER_NAME",
            "updateFolderRequest.name !== RENAMED_FOLDER_NAME",
            "deletedFolderPath !== `/ui/skill-folders/${FOLDER_ID}`",
        ],
    )


def test_agent_frontend_run_helpers_preserve_native_run_bridge_contract() -> None:
    agents_lib = "apps/frontend/src/lib/agents.ts"
    _assert_function_contains(
        agents_lib,
        "listRuns",
        [
            "apiGet<{ runs?: RunTimelinePublicSnapshot[] }>('/yachiyo/studio/runs')",
            ".then((payload) => (payload.runs || []).map(runSpecFromPublicTimelineSnapshot))",
            "apiGet<{ runs?: RunSpec[] }>('/ui/runs')",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "getRun",
        [
            "apiGet<RunTimelinePublicSnapshot>(`/yachiyo/studio/runs/${encodeURIComponent(runId)}`)",
            ".then(runSpecFromPublicTimelineSnapshot)",
            "apiGet(`/ui/runs/${encodeURIComponent(runId)}`)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "listRunGroups",
        [
            "apiGet<{ group_runs?: GroupRunPublicSnapshot[] }>('/yachiyo/studio/group-runs')",
            ".then((payload) => (payload.group_runs || []).map(runGroupSpecFromPublicGroupRun))",
            "apiGet<{ run_groups?: RunGroupSpec[] }>('/ui/run-groups')",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "getRunGroup",
        [
            "apiGet<GroupRunPublicSnapshot>(`/yachiyo/studio/group-runs/${encodeURIComponent(runGroupId)}`)",
            ".then(runGroupSpecFromPublicGroupRun)",
            "apiGet(`/ui/run-groups/${encodeURIComponent(runGroupId)}`)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "getRunEvents",
        [
            "after_sequence: String(Math.max(0, afterSequence))",
            "limit: String(Math.max(1, limit))",
            "apiGet(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/events?${query.toString()}`)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "deleteRun",
        [
            "apiDelete(`/yachiyo/studio/runs/${encodeURIComponent(runId)}`)",
            "apiDelete(`/ui/runs/${encodeURIComponent(runId)}`)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "createAgentRun",
        [
            "const clientRunId = createClientRunId();",
            "/yachiyo/studio/agents/${encodeURIComponent(agentId)}/runs",
            "objective: userGoal",
            "client_run_id: clientRunId",
            "runSpecFromPublicTimeline(snapshot, agentId, userGoal, 'agent_run')",
            "apiPost('/ui/agent-runs'",
            "agent_id: agentId",
            "user_goal: userGoal",
            "client_run_id: clientRunId",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "getRunArtifact",
        [
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}",
            "/ui/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "createWorkflowRun",
        [
            "const clientRunId = createClientRunId();",
            "/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}/runs",
            "client_run_id: clientRunId",
            "apiPost('/ui/workflow-runs'",
            "workflow_id: workflowId",
            "user_goal: userGoal",
            "client_run_id: clientRunId",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "rerunRun",
        [
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/rerun",
            "apiPost(`/ui/runs/${encodeURIComponent(runId)}/rerun`, {})",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "cancelRun",
        [
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/cancel",
            "apiPost(`/ui/runs/${encodeURIComponent(runId)}/cancel`, {})",
        ],
    )


def test_agent_studio_preserves_workflow_child_approval_refresh_wiring() -> None:
    agents_lib = "apps/frontend/src/lib/agents.ts"
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "useRunApprovalActions({",
            "onApproveRunById={approveRunById}",
            "onRejectRunById={rejectRunById}",
            "onCancelRunById={cancelRunById}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunApprovalActions.ts",
        [
            "const approveRunById = useCallback(async (",
            "const selectedAfterAction = nextSelectedRunId || runId;",
            "const approvalRequest = approveRunApproval(runId);",
            "void pollApprovedRunProgress(runId, selectedAfterAction)",
            "updatedRuns.push(await getRun(nextSelectedRunId));",
            "await refreshRunGroupsForRuns(updatedRuns);",
            "const rejectRunById = useCallback(async (",
            "const run = await rejectRunApproval(runId);",
            "upsertRunDetailCache(updatedRuns);",
            "setSelectedRunId(selectedAfterAction);",
            "const cancelRunById = useCallback(async (",
            "const run = await cancelRun(runId);",
            "statusMessage: nextSelectedRunId ? '已取消子 Run，Workflow 已终止。' : 'Run 已取消。'",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "() => onApproveRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id)",
            "() => onRejectRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id)",
            "() => onCancelRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id)",
            "取消子 Run",
            "onOpenRunDetail(selectedWorkflowApprovalChildRunId)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "approveRunApproval",
        [
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/approval/approve",
            "apiPost(`/ui/runs/${encodeURIComponent(runId)}/approval/approve`, {})",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "rejectRunApproval",
        [
            "/yachiyo/studio/runs/${encodeURIComponent(runId)}/approval/reject",
            "apiPost(`/ui/runs/${encodeURIComponent(runId)}/approval/reject`",
            "reason ? { reason } : {}",
        ],
    )


def test_agent_studio_preserves_workflow_child_approval_run_detail_wiring() -> None:
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "workflowPendingApprovalChildRunId(selectedRun)",
            "selectedWorkflowApprovalChildRunId",
            "selectedWorkflowApprovalChildRun = selectedWorkflowApprovalChildRunId",
            "selectedWorkflowApprovalStep = selectedWorkflowApprovalChildRunId",
            "maybeAdd(selectedWorkflowApprovalChildRunId);",
            "...selectedWorkflowChildRefs.map((ref) => ref.childRunId),",
            "selectedWorkflowApprovalChildRunId,",
            "Promise.all(uniqueChildRunIds.map((runId) => getRun(runId).catch(() => null)))",
            "useRunApprovalActions({",
            "onApproveRunById={approveRunById}",
            "onRejectRunById={rejectRunById}",
            "onCancelRunById={cancelRunById}",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/hooks/useRunApprovalActions.ts",
        [
            "const selectedAfterAction = nextSelectedRunId || runId;",
            "const selectedAfterRun = selectedAfterAction !== runId ? runById.get(selectedAfterAction) || null : null;",
            "makeRunContinuingAfterApproval(selectedAfterRun, '已批准子 Agent，Workflow 正在继续执行。')",
            "const approvalRequest = approveRunApproval(runId);",
            "void pollApprovedRunProgress(runId, selectedAfterAction).catch",
            "updatedRuns.push(await getRun(nextSelectedRunId));",
            "await refreshRunGroupsForRuns(updatedRuns);",
            "const run = await rejectRunApproval(runId);",
            "upsertRunDetailCache(updatedRuns);",
            "setSelectedRunId(selectedAfterAction);",
        ],
    )
    _assert_contains(
        "apps/frontend/src/features/agent-studio/components/RunDetailPanel.tsx",
        [
            "className=\"run-approval-box workflow-approval-bridge\"",
            "RunApprovalRequest",
            "runId={selectedWorkflowApprovalChildRun.run_id}",
            "() => onApproveRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),",
            "() => onRejectRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),",
            "onClick={() => onOpenRunDetail(selectedWorkflowApprovalChildRunId)}",
        ],
    )


def test_model_profiles_ui_preserves_profile_lifecycle_paths() -> None:
    _assert_contains(
        "apps/frontend/src/lib/modelProfiles.ts",
        [
            "export async function listModelProfiles()",
            "return apiGet('/ui/model-profiles');",
            "export async function createModelProfile(",
            "return apiPost('/ui/model-profiles', request);",
            "export async function updateModelProfile(",
            "apiPatch(`/ui/model-profiles/${encodeURIComponent(profileId)}`, request)",
            "export async function deleteModelProfile(",
            "apiDelete(`/ui/model-profiles/${encodeURIComponent(profileId)}`)",
            "export async function testModelProfile(",
            "apiPost(`/ui/model-profiles/${encodeURIComponent(profileId)}/test`)",
            "export async function updateModelProfileDefaults(",
            "return apiPatch('/ui/model-profiles/defaults', defaults);",
            "export async function syncNativeProfileDefault(",
            "return apiPost('/ui/native-agent/config', capability === 'chat' ? { chat_profile_id: profileId } : { vision_profile_id: profileId });",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/ModelProfilesView.tsx",
        [
            "const profilePayload = await listModelProfiles();",
            "if (modelDraft.profile_id) return updateModelProfile(modelDraft.profile_id, payload);",
            "return createModelProfile(payload);",
            "const test = await testModelProfile(model.profile_id);",
            "await deleteModelProfile(profileId);",
            "const result = await updateModelProfileDefaults({ [profile.capability]: profile.profile_id });",
            "const nativeResult = await syncNativeProfileDefault(profile.capability, profile.profile_id);",
        ],
    )


def test_model_profiles_ui_preserves_source_lifecycle_paths() -> None:
    _assert_contains(
        "apps/frontend/src/lib/modelProfiles.ts",
        [
            "export async function listModelSources()",
            "return apiGet('/ui/model-sources');",
            "export async function createModelSource(",
            "return apiPost('/ui/model-sources', request);",
            "export async function updateModelSource(",
            "apiPatch(`/ui/model-sources/${encodeURIComponent(sourceId)}`, request)",
            "export async function deleteModelSource(",
            "apiDelete(`/ui/model-sources/${encodeURIComponent(sourceId)}`)",
            "export async function testModelSource(",
            "apiPost(`/ui/model-sources/${encodeURIComponent(sourceId)}/test`, model ? { model } : {})",
            "export async function fetchModelSourceModels(",
            "apiPost(`/ui/model-sources/${encodeURIComponent(sourceId)}/models/fetch`)",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/ModelProfilesView.tsx",
        [
            "const saved = sourceDraft.source_id",
            "? await updateModelSource(sourceDraft.source_id, payload)",
            ": await createModelSource(payload);",
            "async function fetchModelsForSource()",
            "const result = await fetchModelSourceModels(saved.source_id);",
            "await deleteModelSource(sourceDraft.source_id);",
            "function requestRemoveSource()",
            "onConfirm: () => void removeSource(),",
        ],
    )


def test_desktop_presence_features_preserve_live2d_screenshot_and_tts_entrypoints() -> None:
    _assert_contains(
        "apps/frontend/src/views/ModeSettingsView.tsx",
        [
            "chooseLive2DArchive",
            "chooseLive2DModelDirectory",
            "'/ui/live2d/model-path/prepare'",
            "'/ui/live2d/archive/import'",
            'id="manual-live2d-model-path"',
            'id="manual-live2d-archive-path"',
            "'live2d_mode.proactive_enabled'",
            "'bubble_mode.proactive_enabled'",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/DiagnosticsView.tsx",
        [
            "apiGet<ScreenshotProbe>('/screen/current')",
            "navigateTo('proactive-tts')",
            "label: 'Live2D'",
            "label: 'TTS'",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/ProactiveTtsSettingsView.tsx",
        [
            "apiGet<TtsRuntimeStatus>('/ui/tts/status')",
            "apiGet<TtsVoiceResource>('/ui/tts/voice-resource')",
            "apiPost<ProactiveActionResult>('/ui/proactive/screen-permission/check'",
            "apiPost<ProactiveActionResult>('/ui/proactive/test'",
            "apiPost<TtsTestResult>('/ui/tts/test'",
            "apiPost<TtsVoiceImportResult>('/ui/tts/voice-resource/import'",
            "chooseTtsVoiceArchive",
            "hasDesktopTtsVoiceArchivePicker",
            "const selectedPath = voiceArchivePickerAvailable",
            'data-testid="proactive-screen-permission-check"',
            'data-testid="proactive-test-run"',
            'data-testid="proactive-save-settings"',
            'data-testid="proactive-tts-provider"',
            'data-testid="tts-gsv-service-panel"',
            'data-testid="tts-gsv-service-status"',
            'data-testid="tts-gsv-service-refresh"',
            'data-testid="tts-gsv-service-install"',
            'data-testid="tts-gsv-service-uninstall"',
            'data-testid="tts-gsv-service-meta"',
            'data-testid="tts-voice-import"',
            'data-testid="tts-voice-archive-path"',
            'data-testid="tts-save-and-test"',
            'data-testid="tts-test-result"',
            "'/ui/tts/gpt-sovits/service/install'",
            "'/ui/tts/gpt-sovits/service/adopt'",
            "'/ui/tts/gpt-sovits/service/uninstall'",
            'id="tts-command-page"',
            'id="tts-test-text-page"',
        ],
    )
    _assert_contains(
        "apps/frontend/src/lib/bridge.ts",
        [
            "chooseTtsVoiceArchive?: () => Promise<string | null>;",
            "export async function chooseTtsVoiceArchive(): Promise<string | null>",
            "window.ohaDesktop.chooseTtsVoiceArchive()",
            "export function hasDesktopTtsVoiceArchivePicker(): boolean",
        ],
    )
    _assert_contains(
        "apps/frontend/electron/preload.cts",
        [
            "oha:chooseLive2DArchive",
            "oha:chooseLive2DModelDirectory",
            "oha:chooseTtsVoiceArchive",
        ],
    )
    _assert_contains(
        "apps/frontend/electron/main.ts",
        [
            "ipcMain.handle('oha:chooseTtsVoiceArchive'",
            "导入 GPT-SoVITS 音色包 ZIP",
            "{ name: 'TTS 音色包', extensions: ['zip'] }",
        ],
    )


def test_tool_center_copy_preserves_builtin_native_runtime_boundary() -> None:
    tool_center = "apps/frontend/src/views/ToolCenterView.tsx"
    _assert_contains(
        tool_center,
        [
            "外部执行内核 updater 已移除；Oha-Yachiyo 使用内置 Native Runtime 继续执行任务。",
            "外部执行内核 updater 已移除；请使用应用更新、模型配置与 Native Runtime readiness。",
            "Native Runtime 由应用内置",
            "Oha-Yachiyo 不再运行外部执行内核更新器；后续能力通过应用更新和模型配置生效。",
        ],
    )
    _assert_not_contains(
        tool_center,
        [
            "不再启动 Native Runtime",
            "不再运行 Native Runtime 更新",
            "Native Runtime仍在运行。停止终端会中断 Native Runtime。",
        ],
    )


def test_tool_center_uses_oha_agent_runtime_capability_names() -> None:
    tool_center = "apps/frontend/src/views/ToolCenterView.tsx"
    _assert_contains(
        tool_center,
        [
            "<h1>能力中心</h1>",
            "管理记忆、提醒、文件、语音和 Agent 协作。",
            "const LEGACY_TOOL_CATEGORIES = new Set(['外部服务', '第三方扩展']);",
            ").filter(isUserFacingTool);",
            "return !LEGACY_TOOL_CATEGORIES.has(item.category);",
            "label: '语音播报'",
            "label: '文件与工作区'",
            "id: 'artifact'",
            "label: '产物输出'",
            "label: 'Long-term Memory'",
            "由 memory.add/replace/remove 维护持久化记忆，并在 Agent Studio 里管理。",
            "id: 'future_task'",
            "label: 'FutureTask 排程'",
            "future_task.schedule/list/cancel",
            "aliases: ['future-task', 'cronjob', 'cron', 'future_task.schedule', 'future_task.list', 'future_task.cancel']",
            "label: 'Agent / Workflow 委派'",
            "把主聊天任务派给 Agent Studio 的 Agent 或 Workflow，并把结果回收进当前会话。",
            "requiredCapabilities: ['tts', 'future_task', 'memory']",
            "if (item.category === 'Agent Runtime') return true;",
            "const planned = capabilities.find((capability) => capability.status.kind === 'planned');",
            "<h2>常用能力</h2>",
        ],
    )
    _assert_not_contains(
        tool_center,
        [
            "Agent Runtime 能力中心",
            "展示 Oha 自研 Agent Runtime 的记忆、排程、委派和本机工具状态；外部工具只作为推荐环境显示。",
            "Native toolset 是这些链路的底座",
            "requiredCapabilities: ['tts', 'todo', 'cronjob', 'memory']",
            "label: '定时任务'",
            "需要 cronjob 工具集配置",
        ],
    )
    _assert_contains(
        "apps/shell/main_api.py",
        [
            '"terminal": ("terminal", "terminal.run", "process"),',
            '"workspace.list",',
            '"workspace.read",',
            '"workspace.write_patch",',
            '"artifact": ("artifact", "artifact.write", "artifacts"),',
            '"memory": ("memory", "memory.add", "memory.replace", "memory.remove"),',
            '"future_task.schedule",',
            '"future_task.list",',
            '"future_task.cancel",',
        ],
    )


def test_desktop_bridge_token_is_generated_injected_and_sent_by_frontend() -> None:
    _assert_contains(
        "apps/frontend/electron/main.ts",
        [
            "const BRIDGE_TOKEN_ENV = 'OHA_YACHIYO_BRIDGE_TOKEN';",
            "randomBytes(32).toString('hex')",
            "[BRIDGE_TOKEN_ENV]: bridgeSessionToken",
            "'X-Oha-Yachiyo-Bridge-Token': bridgeSessionToken",
            "ipcMain.handle('oha:getBridgeToken'",
        ],
    )
    _assert_contains(
        "apps/frontend/electron/preload.cts",
        [
            "getBridgeToken: () => ipcRenderer.invoke('oha:getBridgeToken') as Promise<string>",
        ],
    )
    _assert_contains(
        "apps/frontend/src/lib/bridge.ts",
        [
            "async function bridgeToken(): Promise<string>",
            "'X-Oha-Yachiyo-Bridge-Token': token",
            "headers = await bridgeJsonHeaders()",
            "const result = await window.ohaDesktop.restartBackend({ bridgeUrl });",
            "cachedBridgeToken = null;",
        ],
    )
