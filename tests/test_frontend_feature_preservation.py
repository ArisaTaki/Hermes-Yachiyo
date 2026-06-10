"""Frontend feature-preservation smoke tests.

These tests intentionally check source-level entry points because the project
does not yet have a browser E2E runner. They guard the v0.5 rule that Hermes
execution-kernel cleanup must not delete mature UI surfaces.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(relative_path: str, fragments: list[str]) -> None:
    text = _read(relative_path)
    missing = [fragment for fragment in fragments if fragment not in text]
    assert not missing, f"{relative_path} is missing preserved feature fragments: {missing!r}"


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
            "apiPost<",
            "'/ui/chat/messages'",
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


def test_agent_studio_preserves_workflow_run_detail_and_approval_paths() -> None:
    _assert_contains(
        "apps/frontend/src/lib/agents.ts",
        [
            "export type AgentExecutionBackend = 'native_profile';",
            "system?: boolean;",
            "virtual?: boolean;",
            "deletable?: boolean;",
            "export async function listWorkflows()",
            "'/ui/workflows'",
            "export async function listRuns()",
            "'/ui/runs'",
            "export async function getRunEvents(",
            "/runs/${encodeURIComponent(runId)}/events?",
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
            "createAgentRun",
            "createWorkflowRun",
            "listWorkflows",
            "listRuns",
            "cancelRun",
            "rerunRun",
            "approveRunApproval",
            "rejectRunApproval",
            "getRunEvents",
            "runEventReplayToTimelineEvent",
            "selectedRunExecutionEvents",
            "selectedRunReplayRefreshKey",
            "RunEvent replay facts",
            "<h2>Run Detail</h2>",
            "Approval Required",
            "RunApprovalRequest",
            "selectedWorkflowApprovalChildRunId",
            "Artifacts ·",
            "Execution ·",
            "selectedAgentReadOnly",
            "selectedAgentDeletable",
            "系统 Agent 只能查看，不能删除。",
            "系统 Agent 由 oha-yachiyo 管理",
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
