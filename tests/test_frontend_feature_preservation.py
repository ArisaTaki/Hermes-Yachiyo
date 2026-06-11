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
    match = re.search(rf"(?:export\s+)?async function {re.escape(name)}\b[^\n]*\{{", text)
    assert match, f"missing async function {name}"
    depth = 0
    for index in range(match.end() - 1, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]
    raise AssertionError(f"unterminated exported async function {name}")


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
            "['agents', 'skills', 'skill-groups', 'workflows', 'runs']",
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
            "export type LauncherRecentSession",
            "recent_sessions?: LauncherRecentSession[];",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/LauncherView.tsx",
        [
            "launcherRecentSessions(data?.chat)",
            "latestLauncherSessionSummary(data?.chat)",
            'data-testid="bubble-launcher-shell"',
            'data-testid="bubble-launcher-button"',
            'data-testid="bubble-launcher-status-dot"',
            'data-testid="bubble-launcher-summary"',
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
            'data-testid={`${mode}-launcher-session-summary-probe`}',
            'data-testid={`${mode}-launcher-latest-reply`}',
            'data-testid={`${mode}-launcher-status-label`}',
            'data-testid={`${mode}-launcher-recent-session`}',
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
            "client_message_id",
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
            "onClick={() => fileInputRef.current?.click()}",
            "const files = Array.from(event.target.files || []);",
            "event.target.value = '';",
            "if (files.length === 0) return;",
            "void addImageFiles(files);",
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
    _assert_occurs(chat_view, "onClick={() => fileInputRef.current?.click()}", 2)
    _assert_occurs(chat_view, "data-testid=\"chat-image-file-input\"", 1)
    _assert_occurs(chat_view, "disabled={imageAttachDisabled}", 3)
    _assert_occurs(chat_view, "if (imageAttachDisabled) {", 2)
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
            "data-testid=\"chat-message-approval-actions\"",
            "data-approval-id={approvalId}",
            "data-approval-signature={approvalSignature}",
            "data-approval-tool={approvalDetails?.tool || ''}",
            "data-testid=\"chat-message-approval-approve\"",
            "data-testid=\"chat-message-approval-reject\"",
            "data-testid=\"chat-message-approval-open-run-detail\"",
            "data-testid=\"chat-message-open-run-detail\"",
            "data-testid=\"chat-composer-approval-notice\"",
            "data-approval-id={approvalId || ''}",
            "data-approval-item-id={itemId || ''}",
            "data-approval-source={source || ''}",
            "data-approval-tool={details.tool}",
            "data-run-id={runId || ''}",
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
            "Object.defineProperty(input, 'click', { configurable: true, value: () => { clickCount += 1; } })",
            "buttons.forEach((button) => button.click())",
            "if (clickCount !== buttons.length) throw new Error('chat image attach buttons did not target file input')",
            "new File([blob], 'smoke-image.svg', { type: 'image/svg+xml' })",
            "new DataTransfer()",
            "transfer.items.add(file)",
            "Object.defineProperty(input, 'files', { configurable: true, value: transfer.files })",
            "input.dispatchEvent(new Event('change', { bubbles: true }))",
            "chat-composer-attachment-remove",
            "removed composer attachment preview",
            "disabled send button after attachment removal",
            "composer attachment preview after removal",
        ],
    )
    _assert_not_contains(smoke_script, ["oha-chat-e2e-add-image"])


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
            "if (!selectedRunId) return;",
            "getRunEvents(selectedRunId, 0, RUN_EVENT_REPLAY_PAGE_SIZE)",
            "[selectedRunId]: {",
            "events: current[selectedRunId]?.events || [],",
            "events: current[selectedRunId]?.events || currentEvents,",
            "selectedRunExecutionEvents",
            "RunEvent replay facts",
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
            "'/ui/agents'",
            "export async function createAgent(",
            "return apiPost<AgentSpec>('/ui/agents', request);",
            "export async function updateAgent(",
            "apiPatch<AgentSpec>(`/ui/agents/${encodeURIComponent(agentId)}`, request)",
            "export async function deleteAgent(",
            "apiDelete(`/ui/agents/${encodeURIComponent(agentId)}`)",
            "export async function attachSkill(",
            "/ui/agents/${encodeURIComponent(agentId)}/skills",
            "export async function detachSkill(",
            "/ui/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}",
            "export async function listSkills()",
            "'/ui/skills'",
            "export async function importSkill(",
            "apiPost('/ui/skills/import'",
            "export async function listSkillSources()",
            "'/ui/skills/sources'",
            "export async function syncNativeSkills()",
            "apiPost('/ui/skills/sync'",
            "export async function installSkillCommand(",
            "apiPost('/ui/skills/install'",
            "export async function updateSkill(",
            "apiPatch(`/ui/skills/${encodeURIComponent(skillId)}`, request)",
            "export async function deleteSkill(",
            "apiDelete(`/ui/skills/${encodeURIComponent(skillId)}`)",
            "export async function listSkillFolders()",
            "'/ui/skill-folders'",
            "export async function createSkillFolder(",
            "return apiPost('/ui/skill-folders', request);",
            "export async function updateSkillFolder(",
            "apiPatch(`/ui/skill-folders/${encodeURIComponent(folderId)}`, request)",
            "export async function deleteSkillFolder(",
            "apiDelete(`/ui/skill-folders/${encodeURIComponent(folderId)}${query}`)",
            "export async function listWorkflows()",
            "'/ui/workflows'",
            "export async function createWorkflow(",
            "return apiPost('/ui/workflows', request);",
            "export async function updateWorkflow(",
            "apiPatch(`/ui/workflows/${encodeURIComponent(workflowId)}`, request)",
            "export async function deleteWorkflow(",
            "apiDelete(`/ui/workflows/${encodeURIComponent(workflowId)}`)",
            "export async function listRuns()",
            "'/ui/runs'",
            "export async function listRunGroups()",
            "'/ui/run-groups'",
            "export async function getRunGroup(",
            "/ui/run-groups/${encodeURIComponent(runGroupId)}",
            "export async function getRunEvents(",
            "/runs/${encodeURIComponent(runId)}/events?",
            "export async function deleteRun(",
            "apiDelete(`/ui/runs/${encodeURIComponent(runId)}`)",
            "export async function getRunArtifact(",
            "'/ui/agent-runs'",
            "client_run_id: createClientRunId()",
            "'/ui/workflow-runs'",
            "export async function cancelRun(",
            "export async function approveRunApproval(",
            "/approval/approve",
            "export async function rejectRunApproval(",
            "/approval/reject",
        ],
    )
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "type StudioTab = 'agents' | 'skills' | 'skill-groups' | 'workflows' | 'runs';",
            "const studioTabs: StudioTab[] = ['agents', 'skills', 'workflows', 'runs'];",
            "const workflowNodeTypes = new Set(['start', 'agent', 'approval', 'artifact']);",
            "createAgent",
            "updateAgent",
            "deleteAgent",
            "attachSkill",
            "detachSkill",
            "listSkills",
            "importSkill",
            "syncNativeSkills",
            "installSkillCommand",
            "updateSkill",
            "deleteSkill",
            "listSkillFolders",
            "createSkillFolder",
            "updateSkillFolder",
            "deleteSkillFolder",
            "createWorkflow",
            "updateWorkflow",
            "deleteWorkflow",
            "createAgentRun",
            "createWorkflowRun",
            "listWorkflows",
            "listRuns",
            "listRunGroups",
            "getRunGroup",
            "deleteRun",
            "cancelRun",
            "rerunRun",
            "approveRunApproval",
            "rejectRunApproval",
            "getRunEvents",
            "saveAgent",
            "const saved = draft.agent_id ? await updateAgent(draft.agent_id, request) : await createAgent(request);",
            "await deleteAgent(agentId);",
            "await deleteAgent(agent.agent_id);",
            "importSkillSourceList",
            "syncNativeSkillLibrary",
            "installSkillFromCommand",
            "await updateSkill(skill.skill_id, { folder_id: folderId });",
            "await updateSkill(skill.skill_id, { enabled: skill.enabled === false });",
            "await deleteSkill(skill.skill_id);",
            "createSkillFolderFromDraft",
            "updateSkillFolderFromDraft",
            "deleteSkillFolderById",
            "if (mounted) await detachSkill(draft.agent_id, skill.skill_id);",
            "else await attachSkill(draft.agent_id, skill.skill_id);",
            "saveWorkflowDraft",
            "const saved = selectedWorkflow ? await updateWorkflow(selectedWorkflow.workflow_id, request) : await createWorkflow(request);",
            "await deleteWorkflow(workflowId);",
            "await deleteWorkflow(workflow.workflow_id);",
            "refreshRunGroupsForRuns",
            "Promise.all(groupIds.map((groupId) => getRunGroup(groupId).catch(() => null)))",
            "function pruneDeletedRunState(deletedRunIds: Set<string>)",
            "setRunDetailCache((current) => current.filter((run) => !deletedRunIds.has(run.run_id)))",
            "setRunEventReplayByRunId((current) => {",
            "delete next[runId];",
            "childRunIds.some((runId) => !deletedRunIds.has(runId))",
            "const result = await deleteRun(run.run_id);",
            "type RunEventReplayState = {",
            "const RUN_EVENT_REPLAY_PAGE_SIZE = 200;",
            "runEventReplayToTimelineEvent",
            "mergeRunEventReplayPages",
            "const bySequence = new Map<number, RunEventSpec>();",
            "incoming.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));",
            "selectedRunExecutionEvents",
            "selectedRunReplayHasMore",
            "selectedRunReplayRefreshKey",
            "events: current[selectedRunId]?.events || [],",
            "hasMore: events.length >= limit,",
            "error: err instanceof Error ? err.message : '读取 RunEvent replay 失败',",
            "loadMoreSelectedRunEvents",
            "const afterSequence = currentEvents.reduce((max, event) => Math.max(max, Number(event.sequence) || 0), 0);",
            "getRunEvents(selectedRunId, afterSequence, RUN_EVENT_REPLAY_PAGE_SIZE)",
            "const events = mergeRunEventReplayPages(previous?.events || currentEvents, incomingEvents);",
            "hasMore: incomingEvents.length >= limit,",
            "error: err instanceof Error ? err.message : '读取更多 RunEvent replay 失败',",
            "RunEvent replay facts",
            "disabled={selectedRunReplayLoading}",
            "{selectedRunReplayLoading ? '加载中...' : '加载更多 RunEvent'}",
            "加载更多 RunEvent",
            "if (name === 'run.started') return 'Run 已启动';",
            "if (name === 'model.output.completed') return '模型输出完成';",
            "if (name === 'agent.tool.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';",
            "if (name === 'agent.tool.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';",
            "if (name === 'approval.timeout') return '审批已超时';",
            "if (name === 'agent.run.resumed') return 'Agent 已继续执行';",
            "if (name === 'agent.run.cancelled') return 'Agent 已取消';",
            "if (name === 'run.rerun.started') return '从原 Run 重跑';",
            "const run = await rerunRun(selectedRun.run_id);",
            "upsertRunDetailCache([run]);",
            "await refreshRunGroupsForRuns([run]);",
            "openRunDetail(run.run_id, { revealInHistory: true });",
            "if (name === 'workflow.node.artifact') return detail ? `产物节点 · ${detail}` : '产物节点';",
            "typeof payload.workflow_node_label === 'string'",
            "<h2>Run Detail</h2>",
            "Approval Required",
            "RunApprovalRequest",
            "selectedWorkflowApprovalChildRunId",
            "Artifacts ·",
            "Execution ·",
            "selectedRun.task_id ? <code>Task {selectedRun.task_id}</code> : null",
            "selectedRun.session_id ? <code>Session {selectedRun.session_id}</code> : null",
            "selectedRun.task_run_link_run_status ? <span>Task link {runStatusLabel(selectedRun.task_run_link_run_status)}</span> : null",
            "selectedRun.task_run_link_last_event_sequence !== undefined && selectedRun.task_run_link_last_event_sequence !== null",
            "Task link updated {formatRunDate(selectedRun.task_run_link_updated_at || selectedRun.task_run_link_created_at)}",
            "selectedAgentReadOnly",
            "selectedAgentDeletable",
            "系统 Agent 只能查看，不能删除。",
            "系统 Agent 由 oha-yachiyo 管理",
        ],
    )


def test_agent_studio_exposes_stable_e2e_selectors_for_run_detail_and_approval_flow() -> None:
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
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
            "data-testid=\"agent-run-detail-open-workflow-studio\"",
            "data-testid=\"agent-run-detail-approval\"",
            "data-testid=\"agent-run-detail-approval-actions\"",
            "data-testid=\"agent-run-detail-approval-approve\"",
            "data-testid=\"agent-run-detail-approval-reject\"",
            "data-testid=\"agent-run-approval-request\"",
            "data-testid=\"agent-run-detail-workflow-child-approval\"",
            "data-testid=\"agent-run-detail-workflow-child-approval-actions\"",
            "data-testid=\"agent-run-detail-workflow-child-approve\"",
            "data-testid=\"agent-run-detail-workflow-child-reject\"",
            "data-testid=\"agent-run-detail-workflow-child-cancel\"",
            "data-testid=\"agent-run-detail-workflow-child-open-run\"",
            "data-testid=\"agent-run-detail-task\"",
            "data-testid=\"agent-run-detail-result\"",
            "data-testid=\"agent-run-detail-workflow-steps\"",
            "data-testid=\"agent-run-detail-workflow-step\"",
            "data-workflow-step-key={step.key}",
            "data-workflow-step-kind={step.kind}",
            "data-workflow-step-node-id={step.nodeId || ''}",
            "data-workflow-step-status={childStatus}",
            "data-testid=\"agent-run-detail-workflow-step-open-run\"",
            "data-testid=\"agent-run-detail-execution\"",
            "data-testid=\"agent-run-detail-execution-events\"",
            "data-testid=\"agent-run-detail-execution-event\"",
            "data-run-event={eventName}",
            "data-run-event-id={eventId}",
            "data-run-event-run-id={eventRunId}",
            "data-run-event-sequence={eventSequence}",
            "data-run-event-schema-version={eventSchemaVersion}",
            "data-run-event-actor={eventActor}",
            "data-run-event-visibility={eventVisibility}",
            "data-run-event-sensitivity={eventSensitivity}",
            "data-run-event-status={eventStatus || ''}",
            "data-run-event-tone={eventTone}",
            "data-child-run-id={childRunId || ''}",
            "data-testid=\"agent-run-detail-execution-open-child-run\"",
            "data-testid=\"agent-run-detail-load-more-events\"",
            "data-testid=\"agent-run-detail-artifacts\"",
            "data-testid=\"agent-run-detail-artifact-list\"",
            "data-testid=\"agent-run-detail-artifact\"",
            "data-artifact-kind={artifactKind}",
            "data-artifact-path={path}",
            "data-artifact-source-label={sourceLabel}",
            "data-artifact-source-run-id={sourceRunId}",
            "data-testid=\"agent-run-detail-artifact-preview\"",
            "data-testid=\"agent-run-history-manage\"",
            "data-testid=\"agent-run-history-bulk-actions\"",
            "data-testid=\"agent-run-history-select-all\"",
            "data-testid=\"agent-run-history-clear-selection\"",
            "data-testid=\"agent-run-history-delete-selected\"",
            "data-testid=\"agent-run-history-finish-management\"",
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


def test_workflow_studio_exposes_stable_e2e_selectors_for_edit_and_run_flow() -> None:
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
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
            "data-testid=\"workflow-save\"",
            "data-testid=\"workflow-delete\"",
            "data-testid=\"workflow-agent-palette\"",
            "data-testid=\"workflow-agent-palette-item\"",
            "data-testid=\"workflow-canvas\"",
            "data-testid=\"workflow-node-settings\"",
            "data-testid=\"workflow-validation\"",
            "data-testid=\"workflow-node-setting-row\"",
            "data-testid=\"workflow-node-label-input\"",
            "data-testid=\"workflow-node-agent-select\"",
            "data-testid=\"workflow-node-task-input\"",
            "data-testid=\"workflow-node-artifact-path-input\"",
            "data-testid=\"workflow-node-approval-criteria-input\"",
            "data-testid=\"workflow-node-remove\"",
            "data-testid=\"workflow-quick-run\"",
            "data-testid=\"workflow-run-goal-input\"",
            "data-testid=\"workflow-run-preview\"",
            "data-testid=\"workflow-run-preview-step\"",
            "data-testid=\"workflow-save-and-run\"",
        ],
    )


def test_workflow_studio_save_and_run_uses_persisted_workflow_id() -> None:
    _assert_function_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        "saveWorkflowDraft",
        [
            "const saved = selectedWorkflow ? await updateWorkflow(selectedWorkflow.workflow_id, request) : await createWorkflow(request);",
            "setSelectedWorkflowId(saved.workflow_id);",
            "return saved;",
        ],
    )
    _assert_function_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        "runCurrentWorkflow",
        [
            "const saved = await saveWorkflowDraft();",
            "const run = await createWorkflowRun(saved.workflow_id, goal);",
            "setWorkflowRunGoal('');",
            "setRunTarget(saved.workflow_id);",
            "openRunDetail(run.run_id, { revealInHistory: true });",
            "return { selectedWorkflowId: saved.workflow_id, runTarget: saved.workflow_id, selectedRunId: run.run_id };",
        ],
    )


def test_agent_frontend_run_helpers_preserve_native_run_bridge_contract() -> None:
    agents_lib = "apps/frontend/src/lib/agents.ts"
    _assert_function_contains(
        agents_lib,
        "getRunEvents",
        [
            "after_sequence: String(Math.max(0, afterSequence))",
            "limit: String(Math.max(1, limit))",
            "apiGet(`/runs/${encodeURIComponent(runId)}/events?${query.toString()}`)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "createAgentRun",
        [
            "apiPost('/ui/agent-runs'",
            "agent_id: agentId",
            "user_goal: userGoal",
            "client_run_id: createClientRunId()",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "createWorkflowRun",
        [
            "apiPost('/ui/workflow-runs'",
            "workflow_id: workflowId",
            "user_goal: userGoal",
            "client_run_id: createClientRunId()",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "rerunRun",
        ["apiPost(`/ui/runs/${encodeURIComponent(runId)}/rerun`, {})"],
    )
    _assert_function_contains(
        agents_lib,
        "cancelRun",
        ["apiPost(`/ui/runs/${encodeURIComponent(runId)}/cancel`, {})"],
    )


def test_agent_studio_preserves_workflow_child_approval_refresh_wiring() -> None:
    agents_lib = "apps/frontend/src/lib/agents.ts"
    _assert_contains(
        "apps/frontend/src/views/AgentStudioView.tsx",
        [
            "async function approveRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions>",
            "const selectedAfterAction = nextSelectedRunId || runId;",
            "const approvalRequest = approveRunApproval(runId);",
            "void pollApprovedRunProgress(runId, selectedAfterAction)",
            "updatedRuns.push(await getRun(nextSelectedRunId));",
            "await refreshRunGroupsForRuns(updatedRuns);",
            "async function rejectRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions>",
            "const run = await rejectRunApproval(runId);",
            "upsertRunDetailCache(updatedRuns);",
            "setSelectedRunId(selectedAfterAction);",
            "async function cancelRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions>",
            "const run = await cancelRun(runId);",
            "statusMessage: nextSelectedRunId ? '已取消子 Run，Workflow 已终止。' : 'Run 已取消。'",
            "() => approveRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id)",
            "() => rejectRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id)",
            "() => cancelRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id)",
            "取消子 Run",
            "openRunDetail(selectedWorkflowApprovalChildRunId)",
        ],
    )
    _assert_function_contains(
        agents_lib,
        "approveRunApproval",
        ["apiPost(`/ui/runs/${encodeURIComponent(runId)}/approval/approve`, {})"],
    )
    _assert_function_contains(
        agents_lib,
        "rejectRunApproval",
        [
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
            "className=\"run-approval-box workflow-approval-bridge\"",
            "RunApprovalRequest",
            "runId={selectedWorkflowApprovalChildRun.run_id}",
            "() => approveRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),",
            "() => rejectRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),",
            "onClick={() => openRunDetail(selectedWorkflowApprovalChildRunId)}",
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
