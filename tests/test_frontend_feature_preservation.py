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


def _extract_async_function(text: str, name: str) -> str:
    match = re.search(rf"export async function {re.escape(name)}\b[^\n]*\{{", text)
    assert match, f"missing exported async function {name}"
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


def test_chat_ui_preserves_image_approval_and_cancel_interaction_wiring() -> None:
    _assert_contains(
        "apps/frontend/src/views/ChatView.tsx",
        [
            "const [attachments, setAttachments] = useState<PendingAttachment[]>(() => [...retainedComposerDraft.attachments]);",
            "const fileInputRef = useRef<HTMLInputElement>(null);",
            "if (attachments.length > 0 && !canAttachImages(executor))",
            "const outgoingAttachments = attachments;",
            "retainComposerDraft(text, outgoingAttachments);",
            "setAttachments(outgoingAttachments);",
            "onClick={() => fileInputRef.current?.click()}",
            "const files = Array.from(event.target.files || []);",
            "event.target.value = '';",
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
            "if (name === 'approval.timeout') return '审批已超时';",
            "if (name === 'agent.run.cancelled') return 'Agent 已取消';",
            "if (name === 'run.rerun.started') return '从原 Run 重跑';",
            "if (name === 'workflow.node.artifact') return detail ? `产物节点 · ${detail}` : '产物节点';",
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
            "'/ui/tts/gpt-sovits/service/install'",
            "'/ui/tts/gpt-sovits/service/adopt'",
            "'/ui/tts/gpt-sovits/service/uninstall'",
            'id="tts-command-page"',
            'id="tts-test-text-page"',
        ],
    )
    _assert_contains(
        "apps/frontend/electron/preload.cts",
        [
            "oha:chooseLive2DArchive",
            "oha:chooseLive2DModelDirectory",
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
        ],
    )
