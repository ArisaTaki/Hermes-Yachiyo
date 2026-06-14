import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

import { useConfirmDialog } from '../components/ConfirmDialog';
import { UiIcon } from '../components/UiIcon';
import {
  apiGet,
  apiPost,
  hasEmbeddedTerminal,
  killDesktopTerminal,
  onDesktopTerminalData,
  onDesktopTerminalExit,
  openAppView,
  resizeDesktopTerminal,
  writeDesktopTerminal,
} from '../lib/bridge';
import { currentParam, navigateTo } from '../lib/view';

type NativeStatus = {
  status?: string;
  version?: string;
  release_date?: string;
  platform?: string;
  command_exists?: boolean;
  ready?: boolean;
  readiness_level?: string;
  available_tools?: string[];
  limited_tools?: string[];
  limited_tool_details?: Record<string, string>;
  doctor_issues_count?: number;
};

type DashboardData = {
  native_agent?: NativeStatus;
};

type DoctorSummary = {
  readiness_level?: string;
  available_tools?: string[];
  limited_tools?: string[];
  limited_tool_details?: Record<string, string>;
  doctor_issues_count?: number;
};

type DiagnosticResult = {
  success?: boolean;
  label?: string;
  command?: string;
  cached_at?: string;
  stale?: boolean;
  doctor_summary?: DoctorSummary;
  diagnostic_cache?: DiagnosticCache;
};

type DiagnosticCache = {
  stale?: boolean;
  reason?: string;
  updated_at?: string;
  commands?: Record<string, DiagnosticResult>;
};

type NativeToolCatalogItem = {
  id: string;
  label: string;
  category: string;
  description: string;
  requirement?: string;
  aliases?: string[];
  planned?: boolean;
};

type ToolStatus = {
  kind: 'ready' | 'limited' | 'pending' | 'planned';
  label: string;
  detail: string;
};

type ToolConfigField = {
  key: string;
  label: string;
  kind: 'text' | 'password' | 'select' | 'combo' | 'checkbox';
  configured?: boolean;
  value?: string | boolean;
  secret?: boolean;
  target?: 'env' | 'config' | 'none';
  config_key?: string;
  env_key?: string;
  placeholder?: string;
  help?: string;
  allow_custom?: boolean;
  options?: Array<{ value: string; label: string }>;
  option_groups?: Record<string, Array<{ value: string; label: string }>>;
  options_follow_field?: string;
  visible_when?: {
    field?: string;
    equals?: string;
    in?: string[];
  };
};

type ToolConfigItem = {
  id: string;
  title: string;
  summary?: string;
  fields: ToolConfigField[];
  configured_count?: number;
  configurable?: boolean;
  action?: string;
  terminal_command?: string;
};

type NativeToolsetItem = {
  id: string;
  canonical_id?: string;
  label?: string;
  enabled?: boolean;
};

type ToolConfigPayload = {
  ok?: boolean;
  command_exists?: boolean;
  needs_env_refresh?: boolean;
  config_path?: string;
  env_path?: string;
  native_toolsets?: NativeToolsetItem[];
  tools?: ToolConfigItem[];
};

type ToolConfigUpdateResult = {
  ok?: boolean;
  error?: string;
  message?: string;
  tool_config?: ToolConfigPayload;
};

type BrowserCdpLaunchResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  url?: string;
  launched?: boolean;
  manual_command?: string;
  tool_config?: ToolConfigPayload;
};

type ToolConfigTestCheck = {
  label: string;
  status: 'pass' | 'warn' | 'fail';
  detail?: string;
};

type ToolConfigTestResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  tool_id?: string;
  status?: 'pass' | 'warn' | 'fail';
  message?: string;
  checks?: ToolConfigTestCheck[];
  elapsed_seconds?: number;
  tool_config?: ToolConfigPayload;
};

type NativeUpdateResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  update_available?: boolean;
  behind_commits?: number;
  release_date?: string;
  version?: string | { version?: string; release_date?: string; update_available?: boolean; behind_commits?: number; summary?: string };
  summary?: string;
  output?: string;
  check_output?: string;
  toolset_delta?: {
    added?: string[];
    removed?: string[];
    changed?: Array<{ id: string; before_enabled?: boolean; after_enabled?: boolean }>;
  };
  tool_config?: ToolConfigPayload;
  diagnostic_cache?: DiagnosticCache;
  dashboard?: DashboardData;
};

type ConfigFieldValue = string | boolean;
type WorkflowTarget = 'live2d' | 'proactive-tts' | 'chat' | 'bubble' | 'settings' | 'tools';
type YachiyoWorkflowDefinition = {
  id: string;
  title: string;
  summary: string;
  primaryAction: {
    label: string;
    target: WorkflowTarget;
    params?: Record<string, string>;
  };
  requiredCapabilities: string[];
  ownedSettingsRoute: string;
  externalRecommendations: string[];
};
type WorkflowCapabilityStatus = {
  id: string;
  label: string;
  status: ToolStatus;
};
type PendingNavigation =
  | { type: 'tool'; toolId: string }
  | { type: 'overview' }
  | { type: 'main' };
type ToolAttentionItem = {
  id: string;
  label: string;
  reason: 'limited' | 'disabled' | 'unknown';
  detail?: string;
};
type NativeUpdateMode = 'check' | 'run' | 'refresh' | null;
type EmbeddedTerminalStatus = 'idle' | 'starting' | 'running' | 'exited' | 'error';
type EmbeddedTerminalSession = {
  id: string;
  task: string;
  title: string;
};

const NATIVE_TOOL_CATALOG: NativeToolCatalogItem[] = [
  {
    id: 'web',
    label: '联网与网页读取',
    category: '信息检索',
    description: '搜索、读取网页内容并把结果交给 Native 推理。',
    requirement: '需要 Native web/search 工具可用',
    aliases: ['search'],
  },
  {
    id: 'browser',
    label: '浏览器自动化',
    category: '信息检索',
    description: '通过浏览器会话访问需要交互的页面。',
    requirement: '需要 Native browser 工具可用',
  },
  {
    id: 'browser-cdp',
    label: '浏览器 CDP 高级控制',
    category: '信息检索',
    description: '连接本机 Chrome 调试端口，启用 CDP 级高级浏览器操作。',
    requirement: '需要 browser.cdp_url 或本机 Chrome 调试端口',
  },
  {
    id: 'image_gen',
    label: '图片生成',
    category: '多模态',
    description: '调用图片生成 provider 产出图片资产。',
    requirement: '需要图片生成 provider 和密钥',
  },
  {
    id: 'tts',
    label: '语音播报',
    category: '体验能力',
    description: '配置 Yachiyo 的主动关怀语音和桌面播报。',
    requirement: '需要主动关怀语音配置',
  },
  {
    id: 'terminal',
    label: '终端执行',
    category: 'Agent Runtime',
    description: '在用户批准后运行命令并读取结果。',
    requirement: '需要 terminal.run 工具权限',
    aliases: ['terminal.run', 'process'],
  },
  {
    id: 'file',
    label: '文件与工作区',
    category: 'Agent Runtime',
    description: '读取工作区文件，并在允许时生成可审查的修改。',
    requirement: '需要 workspace.* 工具权限',
    aliases: ['workspace', 'workspace.list', 'workspace.read', 'workspace.write_patch'],
  },
  {
    id: 'artifact',
    label: '产物输出',
    category: 'Agent Runtime',
    description: '把报告、Markdown、上下文和交付物保存到 Run 产物里。',
    requirement: '需要 artifact.write 工具启用',
    aliases: ['artifact.write', 'artifacts'],
  },
  {
    id: 'skills',
    label: '技能加载',
    category: '本地工作',
    description: '加载 Native 或项目内定义的技能工作流。',
    requirement: '需要技能目录或插件可读取',
  },
  {
    id: 'code_execution',
    label: '代码执行',
    category: '本地工作',
    description: '运行受控代码片段，处理数据或验证逻辑。',
    requirement: '需要 Native 代码执行环境',
  },
  {
    id: 'computer_use',
    label: 'Computer Use',
    category: '本地工作',
    description: '让 Native 控制本机桌面应用和窗口交互。',
    requirement: '需要 Native computer_use 工具集与 macOS 权限',
    aliases: ['computer-use', 'computer'],
  },
  {
    id: 'memory',
    label: 'Long-term Memory',
    category: 'Agent Runtime',
    description: '由 memory.add/replace/remove 维护持久化记忆，并在 Agent Studio 里管理。',
    requirement: '需要 Agent Runtime memory.* 工具启用',
  },
  {
    id: 'session_search',
    label: '会话检索',
    category: 'Agent Runtime',
    description: '检索历史会话，帮助跨会话延续上下文。',
    requirement: '需要会话索引可用',
  },
  {
    id: 'todo',
    label: '任务清单',
    category: 'Agent Runtime 规划',
    description: '用于后续把轻量待办、任务状态和 FutureTask 结果统一成用户可管理清单。',
    requirement: '规划中；当前以 FutureTask 和 Run History 承接',
    planned: true,
  },
  {
    id: 'future_task',
    label: 'FutureTask 排程',
    category: 'Agent Runtime',
    description: '用 future_task.schedule/list/cancel 创建提醒、回访和周期任务，到期后生成真实 Run。',
    requirement: '需要 Agent Runtime FutureTask 工具启用',
    aliases: ['future-task', 'cronjob', 'cron', 'future_task.schedule', 'future_task.list', 'future_task.cancel'],
  },
  {
    id: 'clarify',
    label: '澄清问题',
    category: 'Agent Runtime 规划',
    description: '把缺失信息的追问做成可审计的运行时节点，而不是旧工具清单里的独立插件。',
    requirement: '规划中；当前由 Agent/Workflow prompt 和审批节点承接',
    planned: true,
  },
  {
    id: 'delegation',
    label: 'Agent / Workflow 委派',
    category: 'Agent Runtime',
    description: '把主聊天任务派给 Agent Studio 的 Agent 或 Workflow，并把结果回收进当前会话。',
    requirement: '需要 Oha delegation runtime 与 Agent Studio 目标',
    aliases: ['delegate_task', 'oha.delegation', 'delegate_agent', 'delegate_workflow'],
  },
  {
    id: 'messaging',
    label: '消息通知',
    category: '外部服务',
    description: '向外部消息渠道发送通知或结果。',
    requirement: '需要 webhook、token 或服务地址',
  },
  {
    id: 'discord',
    label: 'Discord',
    category: '外部服务',
    description: '连接 Discord 用户或频道工作流。',
    requirement: '需要 Discord 凭据',
    aliases: ['discord_admin'],
  },
  {
    id: 'homeassistant',
    label: 'Home Assistant',
    category: '外部服务',
    description: '连接家庭自动化设备和场景。',
    requirement: '需要 Home Assistant 地址和 token',
  },
  {
    id: 'spotify',
    label: 'Spotify',
    category: '外部服务',
    description: '读取或控制 Spotify 相关工作流。',
    requirement: '需要 Spotify 授权',
  },
  {
    id: 'yuanbao',
    label: '腾讯元宝',
    category: '第三方扩展',
    description: '连接 Native 的元宝扩展能力。',
    requirement: '需要 Native yuanbao 配置',
    aliases: ['yuanbao'],
  },
  {
    id: 'moa',
    label: 'MoA',
    category: '第三方扩展',
    description: '使用 Native 的多模型协作能力。',
    requirement: '需要实验工具或额外 provider 配置',
  },
  {
    id: 'rl',
    label: 'RL',
    category: '第三方扩展',
    description: '连接 Native 实验性强化学习相关能力。',
    requirement: '需要实验工具开关或额外依赖',
  },
  {
    id: 'local-app-control',
    label: 'Yachiyo 本机应用控制',
    category: 'Yachiyo 规划',
    description: '未来可把音乐、快捷指令和窗口控制做成 Yachiyo 原生能力。',
    requirement: '当前仅展示规划，不启用调用',
    planned: true,
  },
];

const HIDDEN_NATIVE_TOOLS = new Set(['vision', 'vision_analyze']);
const LEGACY_TOOL_CATEGORIES = new Set(['外部服务', '第三方扩展']);

const YACHIYO_WORKFLOWS: YachiyoWorkflowDefinition[] = [
  {
    id: 'desktop-companion',
    title: '桌面陪伴',
    summary: '管理 Live2D、气泡和语音。',
    primaryAction: { label: '配置 Live2D', target: 'live2d' },
    requiredCapabilities: ['tts', 'memory', 'computer_use'],
    ownedSettingsRoute: 'Live2D 模式 / 气泡模式 / 主动关怀语音',
    externalRecommendations: ['Agent Studio 可编排专用 Agent', 'Skill Library 可注入本地能力包'],
  },
  {
    id: 'proactive-care',
    title: '主动关怀',
    summary: '管理提醒、回访和语音反馈。',
    primaryAction: { label: '配置主动关怀语音', target: 'proactive-tts' },
    requiredCapabilities: ['tts', 'future_task', 'memory'],
    ownedSettingsRoute: '主动关怀语音 / 对话',
    externalRecommendations: ['Agent Studio Memory / FutureTask', '本机 TTS 或 GPT-SoVITS'],
  },
  {
    id: 'context-awareness',
    title: '上下文与工作区',
    summary: '管理聊天、文件和工作区上下文。',
    primaryAction: { label: '打开对话', target: 'chat' },
    requiredCapabilities: ['browser', 'file', 'session_search', 'computer_use'],
    ownedSettingsRoute: '对话 / 资源管理 / 工作区',
    externalRecommendations: ['Codex Runtime 可增强代码 review', 'Browser/CDP 可增强网页上下文'],
  },
];

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function ToolCenterView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [diagnosticCache, setDiagnosticCache] = useState<DiagnosticCache | null>(null);
  const [toolConfig, setToolConfig] = useState<ToolConfigPayload | null>(null);
  const [toolConfigLoaded, setToolConfigLoaded] = useState(false);
  const [draftToolId, setDraftToolId] = useState('');
  const [configDraft, setConfigDraft] = useState<Record<string, ConfigFieldValue>>({});
  const [savedDraftSnapshot, setSavedDraftSnapshot] = useState('');
  const [pendingNavigation, setPendingNavigation] = useState<PendingNavigation | null>(null);
  const [toolTestResult, setToolTestResult] = useState<ToolConfigTestResult | null>(null);
  const [nativeUpdate, setNativeUpdate] = useState<NativeUpdateResult | null>(null);
  const [error, setError] = useState('');
  const [actionStatus, setActionStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [configBusy, setConfigBusy] = useState(false);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateMode, setUpdateMode] = useState<NativeUpdateMode>(null);
  const [updateStartedAt, setUpdateStartedAt] = useState<number | null>(null);
  const [updateElapsedSeconds, setUpdateElapsedSeconds] = useState(0);
  const [updateWithFullBackup, setUpdateWithFullBackup] = useState(false);
  const [updateTerminalStatus, setUpdateTerminalStatus] = useState<EmbeddedTerminalStatus>('idle');
  const [updateTerminalMessage, setUpdateTerminalMessage] = useState('更新终端会显示 Native 的实时输出。');
  const [updateTerminalSession, setUpdateTerminalSession] = useState<EmbeddedTerminalSession | null>(null);
  const updateTerminalPanelRef = useRef<HTMLElement | null>(null);
  const updateTerminalHostRef = useRef<HTMLDivElement | null>(null);
  const updateTerminalRef = useRef<Terminal | null>(null);
  const updateFitAddonRef = useRef<FitAddon | null>(null);
  const updateTerminalIdRef = useRef<string | null>(null);
  const { confirmDialog, requestConfirm } = useConfirmDialog();

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const [payload, cache, config] = await Promise.all([
          apiGet<DashboardData>('/ui/dashboard'),
          apiGet<DiagnosticCache>('/ui/native-agent/diagnostics/cache').catch(() => null),
          apiGet<ToolConfigPayload>('/ui/native-agent/tools/config').catch(() => null),
        ]);
        if (!disposed) {
          setData(payload);
          setDiagnosticCache(cache);
          setToolConfig(config);
          setToolConfigLoaded(true);
          setError('');
        }
      } catch (err) {
        if (!disposed) {
          setToolConfigLoaded(true);
          setError(err instanceof Error ? err.message : '读取工具中心失败');
        }
      }
    }
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  const toolConfigById = useMemo(() => {
    const map = new Map<string, ToolConfigItem>();
    (toolConfig?.tools || []).forEach((tool) => map.set(canonicalToolName(tool.id), tool));
    return map;
  }, [toolConfig]);

  const selectedToolId = currentParam('tool');
  const selectedToolConfig = selectedToolId ? toolConfigById.get(canonicalToolName(selectedToolId)) : undefined;
  const hasUnsavedChanges = Boolean(
    selectedToolConfig
    && draftToolId === selectedToolConfig.id
    && draftSignature(configDraft) !== savedDraftSnapshot,
  );

  useEffect(() => {
    if (!selectedToolId) {
      setDraftToolId('');
      setConfigDraft({});
      setSavedDraftSnapshot('');
      return;
    }
    if (!selectedToolConfig || draftToolId === selectedToolConfig.id) return;
    const nextDraft = initialDraftForTool(selectedToolConfig);
    setDraftToolId(selectedToolConfig.id);
    setConfigDraft(nextDraft);
    setSavedDraftSnapshot(draftSignature(nextDraft));
    setToolTestResult(null);
  }, [selectedToolId, selectedToolConfig, draftToolId]);

  useEffect(() => {
    if (!hasUnsavedChanges) return undefined;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  useEffect(() => {
    if (!updateBusy || !updateStartedAt) {
      setUpdateElapsedSeconds(0);
      return undefined;
    }
    const updateElapsed = () => {
      setUpdateElapsedSeconds(Math.max(0, Math.floor((Date.now() - updateStartedAt) / 1000)));
    };
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [updateBusy, updateStartedAt]);

  useEffect(() => {
    if (!updateTerminalSession) return undefined;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = 'Native Runtime仍在运行，关闭窗口会中断更新。';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [updateTerminalSession]);

  useEffect(() => {
    if (!updateTerminalSession) return undefined;
    const previousGuard = window.ohaRouteLeaveGuard;
    const guard: NonNullable<typeof window.ohaRouteLeaveGuard> = (nextView) => {
      if (nextView === 'tools') return previousGuard ? previousGuard(nextView) : true;
      setActionStatus('Native Runtime正在运行，完成或停止前暂不切换页面。');
      scrollToNativeUpdateTerminal();
      return false;
    };
    window.ohaRouteLeaveGuard = guard;
    return () => {
      if (window.ohaRouteLeaveGuard === guard) {
        window.ohaRouteLeaveGuard = previousGuard;
      }
    };
  }, [updateTerminalSession]);

  useEffect(() => {
    if (!hasEmbeddedTerminal()) return undefined;
    const offData = onDesktopTerminalData((payload) => {
      if (payload.id !== updateTerminalIdRef.current) return;
      updateTerminalRef.current?.write(payload.data);
    });
    const offExit = onDesktopTerminalExit((payload) => {
      if (payload.id !== updateTerminalIdRef.current) return;
      const succeeded = payload.exitCode === 0;
      updateTerminalIdRef.current = null;
      setUpdateTerminalSession(null);
      setUpdateTerminalStatus(succeeded ? 'exited' : 'error');
      setUpdateTerminalMessage(nativeUpdateTerminalExitMessage(succeeded, payload.exitCode));
      if (succeeded) {
        setUpdateBusy(true);
        setUpdateMode('refresh');
        setUpdateStartedAt(Date.now());
        setActionStatus('Native Runtime已结束，正在刷新工具清单和 Doctor 状态...');
        void refreshAfterNativeUpdateTerminal();
      } else {
        setUpdateBusy(false);
        setUpdateMode(null);
        setUpdateStartedAt(null);
        setActionStatus(`Native Runtime异常结束（exit=${payload.exitCode}），请查看终端输出。`);
      }
    });
    return () => {
      offData();
      offExit();
      updateTerminalRef.current?.dispose();
      updateTerminalRef.current = null;
      updateFitAddonRef.current = null;
      updateTerminalIdRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!hasEmbeddedTerminal()) return undefined;
    const onResize = () => fitNativeUpdateTerminal();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (!selectedToolId) return;
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }, [selectedToolId]);

  async function refreshToolCenterState(options: {
    checkUpdate?: boolean;
    runDoctor?: boolean;
    retries?: number;
    retryDelayMs?: number;
  } = {}) {
    const retries = Math.max(1, options.retries || 1);
    let lastError: unknown = null;
    for (let attempt = 0; attempt < retries; attempt += 1) {
      if (attempt > 0) await wait(options.retryDelayMs || 900);
      try {
        const check = options.checkUpdate
          ? await apiPost<NativeUpdateResult>('/ui/native-agent/update/check').catch(() => null)
          : null;
        const doctor = options.runDoctor
          ? await apiPost<DiagnosticResult>('/ui/native-agent/diagnostic-command', { command: 'native doctor' }).catch(() => null)
          : null;
        const [payload, cache, config] = await Promise.all([
          apiPost<DashboardData>('/ui/native-agent/recheck'),
          apiGet<DiagnosticCache>('/ui/native-agent/diagnostics/cache').catch(() => doctor?.diagnostic_cache || null),
          apiGet<ToolConfigPayload>('/ui/native-agent/tools/config').catch(() => null),
        ]);
        if (check) setNativeUpdate(check);
        setData(payload);
        setDiagnosticCache(cache);
        setToolConfig(config);
        setToolConfigLoaded(true);
        setError('');
        return { check, doctor, payload, cache, config };
      } catch (err) {
        lastError = err;
      }
    }
    throw lastError instanceof Error ? lastError : new Error('刷新工具状态失败');
  }

  async function recheckNative() {
    if (busy) return;
    setBusy(true);
    setActionStatus('正在重新检测 Native 工具状态...');
    try {
      await refreshToolCenterState();
      setActionStatus('工具状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '重新检测 Native 失败');
    } finally {
      setBusy(false);
    }
  }

  async function checkNativeUpdate() {
    if (updateBusy) return;
    setUpdateBusy(true);
    setUpdateMode('check');
    setUpdateStartedAt(Date.now());
    setActionStatus('正在检查 Native Runtime...');
    try {
      const result = await apiPost<NativeUpdateResult>('/ui/native-agent/update/check');
      setNativeUpdate(result);
      if (!result.ok) throw new Error(result.error || 'Native Runtime检查失败');
      setActionStatus(result.update_available ? '发现 Native Runtime' : 'Native 已是当前版本');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Native Runtime检查失败');
    } finally {
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
    }
  }

  async function updateNativeAgent() {
    if (updateBusy) return;
    if (hasEmbeddedTerminal()) {
      await startNativeUpdateTerminal();
      return;
    }
    await updateNativeAgentViaBridge();
  }

  async function updateNativeAgentViaBridge() {
    setUpdateBusy(true);
    setUpdateMode('run');
    setUpdateStartedAt(Date.now());
    setActionStatus('正在更新 Native，并在完成后刷新工具清单...');
    try {
      const result = await apiPost<NativeUpdateResult>('/ui/native-agent/update/run', { backup: updateWithFullBackup });
      setNativeUpdate(result);
      if (result.tool_config) setToolConfig(result.tool_config);
      if (result.diagnostic_cache) setDiagnosticCache(result.diagnostic_cache);
      if (result.dashboard) setData(result.dashboard);
      await refreshToolCenterState({ checkUpdate: true, runDoctor: true, retries: 8, retryDelayMs: 1200 });
      if (!result.ok) throw new Error(result.error || result.message || 'Native Runtime失败');
      setActionStatus(result.message || 'Native Runtime完成，工具状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Native Runtime失败');
    } finally {
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
    }
  }

  function ensureNativeUpdateTerminal(): Terminal {
    if (updateTerminalRef.current) return updateTerminalRef.current;
    const host = updateTerminalHostRef.current;
    if (!host) throw new Error('更新终端区域尚未准备好');
    const terminal = new Terminal({
      allowProposedApi: true,
      convertEol: true,
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 12,
      lineHeight: 1.35,
      scrollback: 12000,
      theme: {
        background: '#070b12',
        foreground: '#d8e0ee',
        cursor: '#f4d35e',
        black: '#0d1117',
        blue: '#78a6f7',
        cyan: '#8bdfe0',
        green: '#83d6a3',
        magenta: '#d6a3ff',
        red: '#ff8e95',
        white: '#d8e0ee',
        yellow: '#f4d35e',
      },
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(host);
    terminal.onData((data) => {
      const id = updateTerminalIdRef.current;
      if (id) void writeDesktopTerminal(id, data);
    });
    updateTerminalRef.current = terminal;
    updateFitAddonRef.current = fitAddon;
    fitNativeUpdateTerminal();
    return terminal;
  }

  function fitNativeUpdateTerminal() {
    const terminal = updateTerminalRef.current;
    const fitAddon = updateFitAddonRef.current;
    if (!terminal || !fitAddon) return;
    window.requestAnimationFrame(() => {
      try {
        fitAddon.fit();
        const id = updateTerminalIdRef.current;
        if (id) void resizeDesktopTerminal(id, terminal.cols, terminal.rows);
      } catch {}
    });
  }

  function scrollToNativeUpdateTerminal() {
    window.requestAnimationFrame(() => {
      updateTerminalPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  async function waitForNativeUpdateTerminalHost() {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (updateTerminalHostRef.current) return;
      await new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => resolve());
      });
    }
    throw new Error('更新终端区域尚未准备好');
  }

  async function startNativeUpdateTerminal() {
    if (updateTerminalIdRef.current) {
      setActionStatus('外部执行内核更新终端已经在运行，请先等待完成或停止当前任务。');
      scrollToNativeUpdateTerminal();
      return;
    }
    setUpdateBusy(false);
    setUpdateMode(null);
    setUpdateStartedAt(null);
    setUpdateTerminalStatus('error');
    setUpdateTerminalMessage('外部执行内核 updater 已移除；Oha-Yachiyo 使用内置 Native Runtime 继续执行任务。');
    setActionStatus('外部执行内核 updater 已移除；请使用应用更新、模型配置与 Native Runtime readiness。');
  }

  async function stopNativeUpdateTerminalNow() {
    const id = updateTerminalIdRef.current;
    if (!id) return;
    setUpdateTerminalMessage('正在停止外部执行内核更新终端...');
    await killDesktopTerminal(id);
  }

  async function stopNativeUpdateTerminal(options: { confirm?: boolean } = {}) {
    if (options.confirm === false) {
      await stopNativeUpdateTerminalNow();
      return;
    }
    requestConfirm({
      title: '停止外部执行内核更新终端？',
      description: '外部执行内核更新终端仍在运行。停止终端会中断该更新进程。',
      confirmLabel: '停止终端',
      variant: 'danger',
      onConfirm: () => void stopNativeUpdateTerminalNow(),
    });
  }

  async function refreshAfterNativeUpdateTerminal() {
    try {
      setUpdateTerminalMessage('Native Runtime命令已结束，正在等待 Bridge 和 Native gateway 恢复。');
      await refreshToolCenterState({ checkUpdate: true, runDoctor: true, retries: 10, retryDelayMs: 1300 });
      setActionStatus('Native Runtime完成，工具清单和 Doctor 状态已刷新');
      setUpdateTerminalMessage('Native Runtime完成，工具清单和 Doctor 状态已刷新。');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Native Runtime结束，但刷新工具状态失败');
      setUpdateTerminalMessage('Native Runtime结束，但自动刷新失败；请点击重新检测。');
    } finally {
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
    }
  }

  function selectToolConfig(item: NativeToolCatalogItem) {
    const config = configForCatalogItem(item, toolConfigById);
    if (!config) return;
    requestNavigation({ type: 'tool', toolId: config.id });
  }

  function requestNavigation(next: PendingNavigation) {
    if (updateTerminalSession) {
      setActionStatus('Native Runtime正在运行，完成或停止前暂不切换页面。');
      scrollToNativeUpdateTerminal();
      return;
    }
    if (hasUnsavedChanges) {
      setPendingNavigation(next);
      return;
    }
    performNavigation(next);
  }

  function performNavigation(next: PendingNavigation) {
    setPendingNavigation(null);
    setActionStatus('');
    if (next.type === 'tool') {
      navigateTo('tools', { tool: next.toolId });
      return;
    }
    if (next.type === 'overview') {
      navigateTo('tools', {}, ['tool']);
      return;
    }
    void openAppView('main');
  }

  function updateDraftField(key: string, value: ConfigFieldValue) {
    setToolTestResult(null);
    setConfigDraft((draft) => {
      const next = { ...draft, [key]: value };
      if (!selectedToolConfig) return next;
      return normalizeDependentSelects(selectedToolConfig, next, key);
    });
  }

  async function saveSelectedToolConfig(): Promise<boolean> {
    if (!selectedToolConfig || configBusy) return false;
    setConfigBusy(true);
    setActionStatus('正在保存工具配置...');
    try {
      const visibleKeys = new Set(visibleFieldsForTool(selectedToolConfig, configDraft).map((field) => field.key));
      const visibleChanges = Object.fromEntries(
        Object.entries(configDraft).filter(([key]) => visibleKeys.has(key)),
      );
      const result = await apiPost<ToolConfigUpdateResult>('/ui/native-agent/tools/config', {
        tool_id: selectedToolConfig.id,
        changes: visibleChanges,
      });
      if (!result.ok) throw new Error(result.error || '工具配置保存失败');
      if (result.tool_config) setToolConfig(result.tool_config);
      const savedTool = result.tool_config?.tools?.find((tool) => tool.id === selectedToolConfig.id) || selectedToolConfig;
      const nextDraft = initialDraftForTool(savedTool);
      setConfigDraft(nextDraft);
      setSavedDraftSnapshot(draftSignature(nextDraft));
      setActionStatus(result.message || '工具配置已保存');
      return true;
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '工具配置保存失败');
      return false;
    } finally {
      setConfigBusy(false);
    }
  }

  async function saveAndTestSelectedToolConfig() {
    if (!selectedToolConfig || configBusy) return;
    const toolId = selectedToolConfig.id;
    if (hasUnsavedChanges) {
      const ok = await saveSelectedToolConfig();
      if (!ok) return;
    }
    setConfigBusy(true);
    setActionStatus('正在测试工具配置...');
    setToolTestResult(null);
    try {
      const result = await apiPost<ToolConfigTestResult>('/ui/native-agent/tools/config/test', { tool_id: toolId });
      if (result.tool_config) setToolConfig(result.tool_config);
      setToolTestResult(result);
      if (!result.ok) throw new Error(result.error || '工具配置测试失败');
      setActionStatus(result.message || '工具配置测试完成');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '工具配置测试失败');
    } finally {
      setConfigBusy(false);
    }
  }

  async function savePendingNavigation() {
    if (!pendingNavigation) return;
    const ok = await saveSelectedToolConfig();
    if (ok) performNavigation(pendingNavigation);
  }

  function discardPendingNavigation() {
    if (!pendingNavigation) return;
    performNavigation(pendingNavigation);
  }

  async function launchBrowserCdp() {
    if (configBusy) return;
    setConfigBusy(true);
    setActionStatus('正在启动或连接 Chrome 调试端口...');
    try {
      const result = await apiPost<BrowserCdpLaunchResult>('/ui/native-agent/tools/browser-cdp/launch');
      if (!result.ok) {
        const manual = result.manual_command ? ` 手动命令：${result.manual_command}` : '';
        throw new Error(`${result.error || 'Chrome 调试端口连接失败'}${manual}`);
      }
      if (result.tool_config) setToolConfig(result.tool_config);
      navigateTo('tools', { tool: 'browser-cdp' });
      const nextTool = result.tool_config?.tools?.find((tool) => tool.id === 'browser-cdp') || selectedToolConfig;
      if (nextTool) {
        const nextDraft = initialDraftForTool(nextTool);
        setDraftToolId(nextTool.id);
        setConfigDraft(nextDraft);
        setSavedDraftSnapshot(draftSignature(nextDraft));
      }
      setActionStatus(result.message || `已连接 ${result.url || 'CDP 端口'}`);
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Chrome 调试端口连接失败');
    } finally {
      setConfigBusy(false);
    }
  }

  async function openTerminalWizard(command: string) {
    if (!command || configBusy) return;
    setConfigBusy(true);
    setActionStatus('正在打开 Native 原生向导...');
    try {
      const result = await apiPost<{ success?: boolean; error?: string }>('/ui/native-agent/terminal-command', { command });
      if (!result.success) throw new Error(result.error || '无法打开 Native 原生向导');
      setActionStatus('Native 原生向导已打开');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '无法打开 Native 原生向导');
    } finally {
      setConfigBusy(false);
    }
  }

  const nativeAgent = data?.native_agent;
  const commandExists = Boolean(nativeAgent?.command_exists);
  const doctorCache = diagnosticCache?.commands?.doctor;
  const cacheStale = Boolean(diagnosticCache?.stale);
  const doctorSummary = !cacheStale ? doctorCache?.doctor_summary : undefined;
  const rawLimitedToolNames = cacheStale
    ? []
    : doctorSummary
      ? doctorSummary.limited_tools || []
      : nativeAgent?.limited_tools || [];
  const limitedToolNames = rawLimitedToolNames.filter((tool) => !isHiddenNativeTool(tool));
  const rawAvailableToolNames = cacheStale
    ? []
    : doctorSummary?.available_tools?.length
      ? doctorSummary.available_tools
      : nativeAgent?.available_tools || [];
  const availableToolNames = rawAvailableToolNames.filter((tool) => !isHiddenNativeTool(tool));
  const rawLimitedToolDetails = cacheStale
    ? {}
    : doctorSummary
      ? doctorSummary.limited_tool_details || {}
      : nativeAgent?.limited_tool_details || {};
  const limitedToolDetails = Object.fromEntries(
    Object.entries(rawLimitedToolDetails).filter(([tool]) => !isHiddenNativeTool(tool)),
  );
  const hiddenLimitedCount = rawLimitedToolNames.filter((tool) => isHiddenNativeTool(tool)).length;
  const rawIssueCount = doctorSummary?.doctor_issues_count ?? nativeAgent?.doctor_issues_count ?? 0;
  const issueCount = cacheStale ? 0 : Math.max(0, rawIssueCount - hiddenLimitedCount);
  const doctorReferencedTools = [
    ...limitedToolNames,
    ...availableToolNames,
    ...Object.keys(limitedToolDetails),
  ];
  const nativeToolsets = toolConfig?.native_toolsets || [];
  const visibleToolCatalog = catalogForNativeToolsets(
    NATIVE_TOOL_CATALOG,
    nativeToolsets,
    doctorReferencedTools,
  ).filter(isUserFacingTool);
  const selectedCatalogItem = selectedToolId
    ? visibleToolCatalog.find((item) => toolNameAliases(item).some((alias) => canonicalToolName(alias) === canonicalToolName(selectedToolId)))
    : undefined;
  const selectedToolLoading = Boolean(selectedToolId && !toolConfigLoaded);
  const attentionItems = attentionItemsForTools(
    visibleToolCatalog,
    limitedToolNames,
    nativeToolsets,
    limitedToolDetails,
  );
  const visibleConfigCount = visibleToolCatalog.filter((item) => configForCatalogItem(item, toolConfigById)).length;
  const attentionCount = attentionItems.length;
  const checked = Boolean(
    !cacheStale
    && (
      doctorSummary
      || availableToolNames.length
      || limitedToolNames.length
      || (nativeAgent?.readiness_level && nativeAgent.readiness_level !== 'unknown')
    ),
  );
  const unsavedDialog = pendingNavigation ? (
    <UnsavedChangesDialog
      busy={configBusy}
      onSave={() => void savePendingNavigation()}
      onDiscard={discardPendingNavigation}
      onCancel={() => setPendingNavigation(null)}
    />
  ) : null;

  if (selectedToolId) {
    return (
      <main className="app-shell tools-shell">
        <header className="topbar dashboard-topbar">
          <div>
            <h1>{selectedToolConfig?.title || selectedCatalogItem?.label || '工具配置'}</h1>
            <p>{selectedToolConfig?.summary || selectedCatalogItem?.requirement || '读取配置中。'}</p>
          </div>
          <div className="topbar-actions">
            <button type="button" onClick={() => requestNavigation({ type: 'overview' })}>返回工具概览</button>
            <button type="button" onClick={() => requestNavigation({ type: 'main' })}>主控台</button>
          </div>
        </header>

        {error ? <div className="tool-center-status danger">{error}</div> : null}
        {actionStatus ? <div className={/失败|错误|无法|未通过/.test(actionStatus) ? 'tool-center-status danger' : 'tool-center-status'}>{actionStatus}</div> : null}

        {selectedToolLoading ? (
          <ToolConfigLoadingPanel catalogItem={selectedCatalogItem} />
        ) : selectedToolConfig ? (
          <ToolConfigPanel
            tool={selectedToolConfig}
            catalogItem={selectedCatalogItem}
            draft={configDraft}
            busy={configBusy}
            dirty={hasUnsavedChanges}
            testResult={toolTestResult?.tool_id === selectedToolConfig.id ? toolTestResult : null}
            onChange={updateDraftField}
            onSave={() => void saveSelectedToolConfig()}
            onSaveAndTest={() => void saveAndTestSelectedToolConfig()}
            onLaunchBrowserCdp={() => void launchBrowserCdp()}
            onOpenTerminalWizard={(command) => void openTerminalWizard(command)}
            onRunDoctor={() => void openAppView('diagnostics', { command: 'native doctor', return_to: 'tools' })}
          />
        ) : selectedCatalogItem?.id === 'tts' ? (
          <section className="tool-config-panel empty">
            <strong>Yachiyo 主动关怀语音在独立页面配置</strong>
            <span>
              这里的 TTS 是 Native Agent 的工具能力；Bubble/Live2D 主动播报请到“主动关怀语音”页配置 GPT-SoVITS、HTTP 或本地命令。
            </span>
            <div className="tool-config-actions">
              <button type="button" className="primary-action" onClick={() => navigateTo('proactive-tts')}>
                打开主动关怀语音
              </button>
              <button type="button" onClick={() => void openAppView('diagnostics', { command: 'native doctor', return_to: 'tools' })}>
                运行 Doctor
              </button>
            </div>
          </section>
        ) : (
          <section className="tool-config-panel empty">
            <strong>没有找到这个工具配置</strong>
            <span>配置目录加载完成后仍为空时，请回到工具概览重新选择。</span>
          </section>
        )}
        {unsavedDialog}
      </main>
    );
  }

  return (
    <main className="app-shell tools-shell">
      <header className="topbar dashboard-topbar">
        <div>
          <h1>能力中心</h1>
          <p>管理记忆、提醒、文件、语音和 Agent 协作。</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => requestNavigation({ type: 'main' })}>主控台</button>
          <button
            type="button"
            className="primary-action"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'native doctor', return_to: 'tools' })}
          >
            运行 Doctor
          </button>
          <button
            type="button"
            className={busy ? 'attention-action' : undefined}
            disabled={busy}
            onClick={() => void recheckNative()}
          >
            {busy ? '检测中...' : '重新检测'}
          </button>
        </div>
      </header>

      {error ? <div className="notice danger">{error}</div> : null}
      {actionStatus ? <div className={/失败|错误|无法|未通过/.test(actionStatus) ? 'notice danger' : 'notice'}>{actionStatus}</div> : null}

      <YachiyoWorkflowPanel
        workflows={YACHIYO_WORKFLOWS}
        nativeAgent={nativeAgent}
        nativeToolsets={nativeToolsets}
        limitedTools={limitedToolNames}
        availableTools={availableToolNames}
        limitedToolDetails={limitedToolDetails}
        cacheStale={cacheStale}
        checked={checked}
      />

      <section className="tool-center-panel">
        <div className="section-heading-row">
          <div>
            <h2>系统状态</h2>
          </div>
          <StatusPill
            active={!attentionCount && checked}
            label={checked ? (attentionCount ? `${attentionCount} 个需处理` : '正常') : '待检测'}
          />
        </div>

        <div className="tool-center-summary" aria-label="工具概览">
          <ToolSummaryCard label="常用能力" value={`${visibleToolCatalog.length}`} detail="已隐藏旧外部服务和实验扩展" />
          <ToolSummaryCard
            label="需要处理"
            value={cacheStale ? '需重检' : `${attentionCount}`}
            detail={doctorCache?.cached_at ? `上次检测 ${formatShortDateTime(doctorCache.cached_at)}` : checked ? `${issueCount} 项提示` : '尚未检测'}
            warn={Boolean(cacheStale || attentionCount)}
          />
          <ToolSummaryCard label="可配置项" value={`${visibleConfigCount}`} detail="高级连接不在普通视图显示" muted />
        </div>

        {nativeUpdate || updateBusy ? (
          <NativeUpdatePanel
            version={nativeAgent?.version}
            releaseDate={nativeAgent?.release_date}
            result={nativeUpdate}
            busy={updateBusy}
            mode={updateMode}
            elapsedSeconds={updateElapsedSeconds}
            fullBackup={updateWithFullBackup}
            terminalSupported={hasEmbeddedTerminal()}
            commandExists={commandExists}
            onFullBackupChange={setUpdateWithFullBackup}
            onCheck={() => void checkNativeUpdate()}
            onUpdate={() => void updateNativeAgent()}
          />
        ) : null}

        {(updateTerminalStatus !== 'idle' || updateTerminalSession) ? (
          <NativeUpdateTerminalPanel
            panelRef={updateTerminalPanelRef}
            hostRef={updateTerminalHostRef}
            message={updateTerminalMessage}
            session={updateTerminalSession}
            status={updateTerminalStatus}
            supported={hasEmbeddedTerminal()}
            onStop={() => stopNativeUpdateTerminal()}
          />
        ) : null}

        {cacheStale ? (
          <div className="tool-limited-banner">
            <strong>诊断缓存已过期</strong>
            <div>
              <span>配置文件或密钥状态已变化</span>
              <span>请手动运行 Doctor 刷新工具状态</span>
            </div>
          </div>
        ) : attentionCount ? (
          <div className="tool-limited-banner">
            <strong>需要处理的工具</strong>
            <div>
              {attentionItems.map((item) => (
                <span key={item.id} title={item.detail || undefined}>
                  {item.reason === 'disabled' ? `${item.label} 未启用` : item.label}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <div className="tool-action-row">
          <button
            type="button"
            className="primary-action"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'native doctor', return_to: 'tools' })}
          >
            诊断
          </button>
          <button type="button" disabled={busy} onClick={() => void recheckNative()}>
            {busy ? '检测中...' : '刷新'}
          </button>
        </div>

        <ToolCategoryList
          catalog={visibleToolCatalog}
          nativeToolsets={nativeToolsets}
          nativeAgent={nativeAgent}
          limitedTools={limitedToolNames}
          availableTools={availableToolNames}
          limitedToolDetails={limitedToolDetails}
          cacheStale={cacheStale}
          checked={checked}
          configById={toolConfigById}
          selectedToolId={selectedToolId}
          onSelectConfig={selectToolConfig}
        />
      </section>
      {unsavedDialog}
      {confirmDialog}
    </main>
  );
}

function YachiyoWorkflowPanel({
  workflows,
  nativeAgent,
  nativeToolsets,
  limitedTools,
  availableTools,
  limitedToolDetails,
  cacheStale,
  checked,
}: {
  workflows: YachiyoWorkflowDefinition[];
  nativeAgent?: NativeStatus;
  nativeToolsets: NativeToolsetItem[];
  limitedTools: string[];
  availableTools: string[];
  limitedToolDetails: Record<string, string>;
  cacheStale: boolean;
  checked: boolean;
}) {
  return (
    <section className="yachiyo-workflow-panel">
      <div className="section-heading-row">
        <div>
          <h2>常用能力</h2>
        </div>
        <button type="button" onClick={() => navigateTo('settings')}>打开设置</button>
      </div>
      <div className="yachiyo-workflow-grid">
        {workflows.map((workflow) => {
          const capabilities = workflow.requiredCapabilities.map((capability) => workflowCapabilityStatus(
            capability,
            nativeAgent,
            nativeToolsets,
            limitedTools,
            availableTools,
            limitedToolDetails,
            checked,
            cacheStale,
          ));
          const status = workflowStatusFromCapabilities(capabilities, checked, cacheStale);
          return (
            <article className={`yachiyo-workflow-card ${status.kind}`} key={workflow.id}>
              <div className="yachiyo-workflow-head">
                <div>
                  <strong>{workflow.title}</strong>
                  <span>{workflow.ownedSettingsRoute}</span>
                </div>
                <span className={`tool-status-pill ${status.kind}`}>{status.label}</span>
              </div>
              <p>{workflow.summary}</p>
              <div className="workflow-card-actions">
                <button
                  type="button"
                  className="primary-action"
                  onClick={() => navigateTo(workflow.primaryAction.target, workflow.primaryAction.params || {})}
                >
                  {workflow.primaryAction.label}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ToolCategoryList({
  catalog,
  nativeToolsets,
  nativeAgent,
  limitedTools,
  availableTools,
  limitedToolDetails,
  cacheStale,
  checked,
  configById,
  selectedToolId,
  onSelectConfig,
}: {
  catalog: NativeToolCatalogItem[];
  nativeToolsets: NativeToolsetItem[];
  nativeAgent?: NativeStatus;
  limitedTools: string[];
  availableTools: string[];
  limitedToolDetails: Record<string, string>;
  cacheStale: boolean;
  checked: boolean;
  configById: Map<string, ToolConfigItem>;
  selectedToolId: string;
  onSelectConfig: (item: NativeToolCatalogItem) => void;
}) {
  return (
    <div className="tool-category-list">
      {toolCategoryGroups(catalog).map(([category, items]) => (
        <section className="tool-category-section" key={category}>
          <div className="tool-category-heading">
            <strong>{category}</strong>
            <span>{items.length} 项</span>
          </div>
          <div className="tool-grid">
            {items.map((item) => {
              const config = configForCatalogItem(item, configById);
              const enabledByToolsList = toolsetEnabledForItem(item, nativeToolsets);
              const status = enabledByToolsList
                ? toolStatusFor(item, nativeAgent, limitedTools, availableTools, limitedToolDetails, checked, cacheStale)
                : {
                    kind: 'limited' as const,
                    label: '未启用',
                    detail: 'Native tools list 显示此工具组当前已禁用。',
                  };
              const selected = config && canonicalToolName(config.id) === canonicalToolName(selectedToolId);
              const configCount = config ? visibleConfiguredCount(config) : { configured: 0, total: 0 };
              return (
                <article className={`tool-card ${status.kind}${selected ? ' selected' : ''}`} key={item.id}>
                  <div className="tool-card-head">
                    <strong>{item.label}</strong>
                    <span className={`tool-status-pill ${status.kind}`}>{status.label}</span>
                  </div>
                  <p>{item.description}</p>
                  <small>{status.detail || item.requirement}</small>
                  {config ? (
                    <div className="tool-card-actions">
                      <button type="button" onClick={() => onSelectConfig(item)}>
                        {selected ? '正在配置' : '配置'}
                      </button>
                      <span>{configCount.configured}/{configCount.total} 已配置</span>
                    </div>
                  ) : item.id === 'tts' ? (
                    <div className="tool-card-actions">
                      <button type="button" onClick={() => navigateTo('proactive-tts')}>
                        主动关怀语音
                      </button>
                      <span>Yachiyo 播报入口</span>
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function ToolConfigLoadingPanel({ catalogItem }: { catalogItem?: NativeToolCatalogItem }) {
  return (
    <section className="tool-config-panel tool-config-loading" aria-busy="true">
      <div className="tool-config-loading-head">
        <span className="tool-config-loading-icon">
          <UiIcon name="settings" />
        </span>
        <div>
          <strong>正在读取工具配置</strong>
          <span>{catalogItem?.label ? `准备 ${catalogItem.label} 的配置项` : '正在同步 Native 工具配置。'}</span>
        </div>
      </div>
      <div className="tool-config-skeleton-grid" aria-hidden="true">
        <span className="tool-config-skeleton-line title" />
        <span className="tool-config-skeleton-line title" />
        <span className="tool-config-skeleton-line" />
        <span className="tool-config-skeleton-line" />
        <span className="tool-config-skeleton-line wide" />
      </div>
    </section>
  );
}

function ToolConfigPanel({
  tool,
  catalogItem,
  draft,
  busy,
  dirty,
  testResult,
  onChange,
  onSave,
  onSaveAndTest,
  onLaunchBrowserCdp,
  onOpenTerminalWizard,
  onRunDoctor,
}: {
  tool?: ToolConfigItem;
  catalogItem?: NativeToolCatalogItem;
  draft: Record<string, ConfigFieldValue>;
  busy: boolean;
  dirty?: boolean;
  testResult?: ToolConfigTestResult | null;
  onChange: (key: string, value: ConfigFieldValue) => void;
  onSave: () => void;
  onSaveAndTest: () => void;
  onLaunchBrowserCdp: () => void;
  onOpenTerminalWizard: (command: string) => void;
  onRunDoctor: () => void;
}) {
  if (!tool) {
    return (
      <section className="tool-config-panel empty">
        <strong>选择一个受限或可配置工具</strong>
        <span>Web、Browser、Image Gen 与外部服务会显示各自的配置项。</span>
      </section>
    );
  }
  const visibleFields = visibleFieldsForTool(tool, draft);
  const configuredCount = visibleFields.filter((field) => field.configured).length;

  return (
    <section className="tool-config-panel">
      <div className="tool-config-head">
        <div>
          <strong>{tool.title || catalogItem?.label || tool.id}</strong>
          <span>{tool.summary || catalogItem?.requirement || 'Native 工具配置'}</span>
        </div>
        <span className={dirty ? 'tool-config-count dirty' : 'tool-config-count'}>
          {dirty ? '未保存' : `${configuredCount}/${visibleFields.length} 已配置`}
        </span>
      </div>

      {dirty ? (
        <div className="tool-config-unsaved-strip" role="status" aria-live="polite">
          <strong>未保存更改</strong>
          <span>保存后生效；“保存并测试”会先写入当前配置。</span>
        </div>
      ) : null}

      {visibleFields.length ? (
        <div className="tool-config-grid">
          {visibleFields.map((field) => (
            <ToolConfigFieldControl
              key={field.key}
              field={field}
              value={draft[field.key]}
              draft={draft}
              onChange={(value) => onChange(field.key, value)}
            />
          ))}
        </div>
      ) : (
        <div className="tool-config-empty">
          <strong>此工具需要 Native 原生授权流程</strong>
          <span>{tool.summary || '请通过 Native setup 完成。'}</span>
        </div>
      )}

      {testResult ? <ToolConfigTestResultPanel result={testResult} /> : null}

      <div className="tool-config-footer">
        <div className="tool-config-meta">
          {visibleFields.map((field) => (
            <span key={field.key}>{field.env_key || field.config_key || field.key}</span>
          ))}
        </div>
        <div className="tool-config-actions">
          {tool.action === 'launch_browser_cdp' ? (
            <button type="button" disabled={busy} onClick={onLaunchBrowserCdp}>
              启动/连接本机 Chrome
            </button>
          ) : null}
          {tool.terminal_command ? (
            <button type="button" disabled={busy} onClick={() => onOpenTerminalWizard(tool.terminal_command || '')}>
              打开 Native 向导
            </button>
          ) : null}
          {visibleFields.length ? (
            <button type="button" className="primary-action" disabled={busy || !dirty} onClick={onSave}>
              {busy ? '保存中...' : dirty ? '保存配置' : '已保存'}
            </button>
          ) : null}
          <button type="button" disabled={busy} onClick={onSaveAndTest}>
            {busy ? '测试中...' : dirty ? '保存并测试' : '测试配置'}
          </button>
          <button type="button" disabled={busy} onClick={onRunDoctor}>运行 Doctor</button>
        </div>
      </div>
    </section>
  );
}

function ToolConfigTestResultPanel({ result }: { result: ToolConfigTestResult }) {
  const status = result.status || (result.ok ? 'warn' : 'fail');
  return (
    <div className={`tool-config-test-result ${status}`}>
      <div className="tool-config-test-head">
        <strong>{result.message || result.error || '工具配置测试结果'}</strong>
        {typeof result.elapsed_seconds === 'number' ? <span>{result.elapsed_seconds}s</span> : null}
      </div>
      {result.checks?.length ? (
        <div className="tool-config-test-list">
          {result.checks.map((check, index) => (
            <div className={`tool-config-test-row ${check.status}`} key={`${check.label}-${index}`}>
              <span>{check.label}</span>
              <strong>{check.status === 'pass' ? '通过' : check.status === 'warn' ? '待确认' : '失败'}</strong>
              {check.detail ? <small>{check.detail}</small> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ToolConfigFieldControl({
  field,
  value,
  draft,
  onChange,
}: {
  field: ToolConfigField;
  value: ConfigFieldValue | undefined;
  draft: Record<string, ConfigFieldValue>;
  onChange: (value: ConfigFieldValue) => void;
}) {
  if (field.kind === 'checkbox') {
    return (
      <label className="settings-field checkbox-field tool-config-field">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.currentTarget.checked)}
        />
        <span>
          {field.label}
          {field.help ? <small>{field.help}</small> : null}
        </span>
      </label>
    );
  }

  if (field.kind === 'combo') {
    const options = optionsForField(field, draft);
    const listId = `tool-config-${field.key.replace(/[^a-z0-9_-]/gi, '-')}-options`;
    return (
      <label className="settings-field tool-config-field">
        <span>{field.label}</span>
        <input
          list={options.length ? listId : undefined}
          type="text"
          value={String(value ?? '')}
          placeholder={field.placeholder || (field.allow_custom ? '可选择或输入自定义值' : '')}
          onChange={(event) => onChange(event.currentTarget.value)}
        />
        {options.length ? (
          <datalist id={listId}>
            {options.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </datalist>
        ) : null}
        <small>
          {field.config_key || field.env_key}
          {field.configured ? ' · 已配置' : ''}
          {field.help ? ` · ${field.help}` : ''}
        </small>
      </label>
    );
  }

  if (field.kind === 'select') {
    const options = optionsForField(field, draft);
    return (
      <label className="settings-field tool-config-field">
        <span>{field.label}</span>
        <select value={String(value ?? '')} onChange={(event) => onChange(event.currentTarget.value)}>
          {options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <small>
          {field.config_key || field.env_key}
          {field.help ? ` · ${field.help}` : ''}
        </small>
      </label>
    );
  }

  return (
    <label className="settings-field tool-config-field">
      <span>{field.label}</span>
      <input
        type={field.kind === 'password' ? 'password' : 'text'}
        value={String(value ?? '')}
        placeholder={field.kind === 'password' && field.configured ? '已配置，留空则不修改' : field.placeholder || ''}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
      <small>
        {field.env_key || field.config_key}
        {field.configured ? ' · 已配置' : ' · 未配置'}
        {field.help ? ` · ${field.help}` : ''}
      </small>
    </label>
  );
}

function UnsavedChangesDialog({
  busy,
  onSave,
  onDiscard,
  onCancel,
}: {
  busy: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="tool-config-modal-backdrop" role="presentation">
      <section className="tool-config-modal" role="dialog" aria-modal="true" aria-labelledby="tool-config-unsaved-title">
        <strong id="tool-config-unsaved-title">配置还没有保存</strong>
        <span>切换工具前，请选择保存当前配置或弃置这次更改。</span>
        <div className="tool-config-modal-actions">
          <button type="button" className="primary-action" disabled={busy} onClick={onSave}>
            {busy ? '保存中...' : '保存并继续'}
          </button>
          <button type="button" disabled={busy} onClick={onDiscard}>弃置更改</button>
          <button type="button" disabled={busy} onClick={onCancel}>继续编辑</button>
        </div>
      </section>
    </div>
  );
}

function ToolSummaryCard({
  label,
  value,
  detail,
  warn,
  muted,
}: {
  label: string;
  value: string;
  detail: string;
  warn?: boolean;
  muted?: boolean;
}) {
  return (
    <article className={warn ? 'tool-summary-card warn' : muted ? 'tool-summary-card muted' : 'tool-summary-card'}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function formatNativeVersion(version?: string, releaseDate?: string): string {
  const cleanVersion = String(version || '').trim();
  const cleanDate = String(releaseDate || '').trim();
  if (cleanVersion && cleanDate && !cleanVersion.includes(cleanDate)) return `${cleanVersion} · ${cleanDate}`;
  return cleanVersion || cleanDate || '未知版本';
}

function NativeUpdatePanel({
  version,
  releaseDate,
  result,
  busy,
  mode,
  elapsedSeconds,
  fullBackup,
  terminalSupported,
  commandExists,
  onFullBackupChange,
  onCheck,
  onUpdate,
}: {
  version?: string;
  releaseDate?: string;
  result: NativeUpdateResult | null;
  busy: boolean;
  mode: NativeUpdateMode;
  elapsedSeconds: number;
  fullBackup: boolean;
  terminalSupported: boolean;
  commandExists: boolean;
  onFullBackupChange: (value: boolean) => void;
  onCheck: () => void;
  onUpdate: () => void;
}) {
  const versionText = typeof result?.version === 'object' ? result.version.version : result?.version;
  const dateText = result?.release_date || (typeof result?.version === 'object' ? result.version.release_date : '') || releaseDate || '';
  const updateAvailable = Boolean(result?.update_available || (typeof result?.version === 'object' && result.version.update_available));
  const behind = result?.behind_commits || (typeof result?.version === 'object' ? result.version.behind_commits : 0) || 0;
  const delta = result?.toolset_delta;
  const changedCount = (delta?.added?.length || 0) + (delta?.removed?.length || 0) + (delta?.changed?.length || 0);
  const busyText = busy ? nativeUpdateBusyText(mode, elapsedSeconds) : '';
  return (
    <div className={updateAvailable ? 'native-update-panel attention' : 'native-update-panel'}>
      <div>
        <strong>Native Runtime</strong>
        <span>
          {result
            ? updateAvailable
              ? `可更新${behind ? `，落后 ${behind} commits` : ''}`
              : '未发现更新'
            : version
              ? `当前 ${formatNativeVersion(version, releaseDate)}`
              : '可检查 Native 版本与工具清单变化'}
        </span>
        {versionText ? <small>{formatNativeVersion(versionText, dateText)}</small> : null}
        {changedCount ? (
          <small>
            工具清单变化：新增 {delta?.added?.length || 0}，移除 {delta?.removed?.length || 0}，状态变化 {delta?.changed?.length || 0}
          </small>
        ) : null}
        <small>更新通道：外部 Native updater 已移除；Release tag 仅作为应用发布参考，Yachiyo 暂不自动切换 tag。</small>
        <label className="settings-field checkbox-field native-update-backup-option">
          <input
            type="checkbox"
            checked={fullBackup}
            disabled={busy}
            onChange={(event) => onFullBackupChange(event.currentTarget.checked)}
          />
          <span>
            Native Runtime 由应用内置
            <small>Oha-Yachiyo 不再运行外部执行内核更新器；后续能力通过应用更新和模型配置生效。</small>
          </span>
        </label>
        {busy ? (
          <div className="native-update-progress" role="status" aria-live="polite">
            <div>
              <span>{busyText}</span>
              <small>{elapsedSeconds}s</small>
            </div>
            <div className="native-update-progress-track" aria-hidden="true">
              <span />
            </div>
          </div>
        ) : null}
      </div>
      <div className="native-update-actions">
        <button type="button" disabled={!commandExists || busy} onClick={onCheck}>
          {busy && mode === 'check' ? `检查中 ${elapsedSeconds}s...` : '检查更新'}
        </button>
        <button type="button" className="primary-action" disabled={!commandExists || busy || !updateAvailable} onClick={onUpdate}>
          {busy && mode === 'run' ? `更新中 ${elapsedSeconds}s...` : terminalSupported ? '打开更新终端' : '更新并刷新'}
        </button>
      </div>
    </div>
  );
}

function nativeUpdateBusyText(mode: NativeUpdateMode, elapsedSeconds: number): string {
  if (mode === 'check') {
    return elapsedSeconds >= 15 ? '仍在检查远端版本，网络较慢时会多等一会儿。' : '正在检查 Native 远端版本。';
  }
  if (mode === 'refresh') {
    if (elapsedSeconds >= 12) return '仍在等待 Bridge/Native gateway 恢复，恢复后会自动同步工具清单。';
    return '更新命令已完成，正在重新读取版本、Doctor 和工具清单。';
  }
  if (elapsedSeconds >= 90) {
    return '仍在更新 Native；可能正在下载依赖或刷新工具清单。';
  }
  if (elapsedSeconds >= 30) {
    return 'Native Runtime仍在运行，完成后会自动刷新 Doctor 与工具清单。';
  }
  if (elapsedSeconds >= 10) {
    return '正在执行 Native gateway 更新流程，请保持窗口打开。';
  }
  return '正在启动 Native Runtime，请查看更新终端输出。';
}

function NativeUpdateTerminalPanel({
  panelRef,
  hostRef,
  message,
  session,
  status,
  supported,
  onStop,
}: {
  panelRef: RefObject<HTMLElement | null>;
  hostRef: RefObject<HTMLDivElement | null>;
  message: string;
  session: EmbeddedTerminalSession | null;
  status: EmbeddedTerminalStatus;
  supported: boolean;
  onStop: () => Promise<void>;
}) {
  return (
    <section ref={panelRef} className="panel settings-section embedded-terminal-panel tool-update-terminal-panel">
      <div className="section-heading-row">
        <div>
          <h2>Native Runtime终端</h2>
          <p className="section-caption">{session?.title || '实时查看 Native update 输出'}</p>
        </div>
        <div className="terminal-heading-actions">
          <span className={`terminal-status ${status}`}>{toolTerminalStatusLabel(status, supported)}</span>
          <button type="button" className="danger-action" onClick={() => void onStop()} disabled={!session}>
            停止更新
          </button>
        </div>
      </div>
      <p className="embedded-terminal-hint">{message}</p>
      <div className="embedded-terminal-shell">
        <div ref={hostRef} className="embedded-terminal" />
        {status === 'idle' ? (
          <div className="embedded-terminal-placeholder">
            {supported ? '点击“打开更新终端”后，这里会显示 Native 的实时输出。' : '当前环境不支持内置终端，将使用普通更新请求。'}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function toolTerminalStatusLabel(status: EmbeddedTerminalStatus, supported: boolean): string {
  if (!supported) return '无内置终端';
  if (status === 'starting') return '启动中';
  if (status === 'running') return '运行中';
  if (status === 'exited') return '已结束';
  if (status === 'error') return '异常结束';
  return '待命';
}

function nativeUpdateTerminalExitMessage(succeeded: boolean, exitCode: number): string {
  if (succeeded) return 'Native Runtime命令已结束，正在刷新工具清单和 Doctor 状态。';
  return `Native Runtime终端异常结束，退出码 ${exitCode}。输出仍保留在这里，便于排查。`;
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function toolCategoryGroups(items: NativeToolCatalogItem[]): Array<[string, NativeToolCatalogItem[]]> {
  const groups = new Map<string, NativeToolCatalogItem[]>();
  for (const item of items) {
    const entries = groups.get(item.category) || [];
    entries.push(item);
    groups.set(item.category, entries);
  }
  return Array.from(groups.entries());
}

function workflowCapabilityStatus(
  capabilityId: string,
  oha: NativeStatus | undefined,
  nativeToolsets: NativeToolsetItem[],
  limitedTools: string[],
  availableTools: string[],
  limitedToolDetails: Record<string, string>,
  checked: boolean,
  cacheStale: boolean,
): WorkflowCapabilityStatus {
  const item = catalogItemForCapability(capabilityId);
  if (!item) {
    return {
      id: capabilityId,
      label: capabilityId,
      status: {
        kind: 'pending',
        label: '待同步',
        detail: 'Native tools list 暂未暴露这个能力，Yachiyo 会先按规划展示。',
      },
    };
  }
  if (!toolsetEnabledForItem(item, nativeToolsets)) {
    return {
      id: capabilityId,
      label: item.label,
      status: {
        kind: 'limited',
        label: '未启用',
        detail: 'Native tools list 显示此工具组当前已禁用。',
      },
    };
  }
  return {
    id: capabilityId,
    label: item.label,
    status: toolStatusFor(item, oha, limitedTools, availableTools, limitedToolDetails, checked, cacheStale),
  };
}

function workflowStatusFromCapabilities(
  capabilities: WorkflowCapabilityStatus[],
  checked: boolean,
  cacheStale: boolean,
): ToolStatus {
  if (cacheStale || !checked) {
    return {
      kind: 'pending',
      label: '待检测',
      detail: '运行 Doctor 后会刷新这条链路的依赖状态。',
    };
  }
  const limited = capabilities.find((capability) => capability.status.kind === 'limited');
  if (limited) {
    return {
      kind: 'limited',
      label: '部分受限',
      detail: `${limited.label} 需要处理；链路仍可部分使用，但体验会降级。`,
    };
  }
  const pending = capabilities.find((capability) => capability.status.kind === 'pending');
  if (pending) {
    return {
      kind: 'pending',
      label: '待确认',
      detail: `${pending.label} 尚未给出可用性结论。`,
    };
  }
  const planned = capabilities.find((capability) => capability.status.kind === 'planned');
  if (planned) {
    return {
      kind: 'planned',
      label: '规划中',
      detail: `${planned.label} 仍是规划能力，当前链路会用已落地的 Runtime 能力承接。`,
    };
  }
  return {
    kind: 'ready',
    label: '可推进',
    detail: '依赖能力已就绪，可以进入 Yachiyo 自有配置页继续调体验。',
  };
}

function catalogItemForCapability(capabilityId: string): NativeToolCatalogItem | undefined {
  const canonical = canonicalToolName(capabilityId);
  return NATIVE_TOOL_CATALOG.find((item) => toolNameAliases(item).some((alias) => canonicalToolName(alias) === canonical));
}

function catalogForNativeToolsets(
  catalog: NativeToolCatalogItem[],
  toolsets?: NativeToolsetItem[],
  doctorReferencedTools?: string[],
): NativeToolCatalogItem[] {
  const baseCatalog = catalog.filter((item) => !item.planned && !isHiddenNativeTool(item.id));
  if (!toolsets?.length && !doctorReferencedTools?.length) return baseCatalog;
  const supported = new Set(
    (toolsets || [])
      .filter((item) => !isHiddenNativeTool(item.canonical_id || item.id))
      .map((item) => canonicalToolName(item.canonical_id || item.id)),
  );
  const referenced = new Set((doctorReferencedTools || []).filter((tool) => !isHiddenNativeTool(tool)).map(canonicalToolName));
  const visible = baseCatalog.filter((item) => {
    if (item.category === 'Agent Runtime') return true;
    const aliases = toolNameAliases(item).map(canonicalToolName);
    if (item.id === 'browser-cdp') {
      return supported.has('browser') || supported.has('browser-cdp') || referenced.has('browser-cdp');
    }
    return aliases.some((alias) => supported.has(alias) || referenced.has(alias));
  });
  const knownAliases = new Set(visible.flatMap((item) => toolNameAliases(item).map(canonicalToolName)));
  for (const toolset of toolsets || []) {
    const canonical = canonicalToolName(toolset.canonical_id || toolset.id);
    if (!canonical || isHiddenNativeTool(canonical) || knownAliases.has(canonical)) continue;
    visible.push({
      id: canonical,
      label: toolset.label || toolset.id || canonical,
      category: 'Native 新增工具',
      description: 'Native tools list 中发现的新工具；Yachiyo 会先展示状态，专属配置入口可后续补齐。',
      requirement: '随 Native Runtime同步',
      aliases: [toolset.id, toolset.canonical_id || ''].filter((value): value is string => Boolean(value)),
    });
    knownAliases.add(canonical);
  }
  return visible;
}

function isUserFacingTool(item: NativeToolCatalogItem): boolean {
  return !LEGACY_TOOL_CATEGORIES.has(item.category);
}

function toolsetEnabledForItem(item: NativeToolCatalogItem, toolsets?: NativeToolsetItem[]): boolean {
  if (!toolsets?.length) return true;
  const records = new Map(toolsets.map((toolset) => [canonicalToolName(toolset.canonical_id || toolset.id), toolset]));
  if (item.id === 'browser-cdp') return records.get('browser')?.enabled !== false;
  const match = toolNameAliases(item)
    .map((alias) => records.get(canonicalToolName(alias)))
    .find(Boolean);
  return match?.enabled !== false;
}

function toolStatusFor(
  item: NativeToolCatalogItem,
  oha: NativeStatus | undefined,
  limitedTools: string[],
  availableTools: string[],
  limitedToolDetails: Record<string, string>,
  checked: boolean,
  cacheStale: boolean,
): ToolStatus {
  if (item.planned) {
    return {
      kind: 'planned',
      label: '规划中',
      detail: '当前只展示方向，不启用本机工具调用。',
    };
  }
  if (isToolLimited(item, limitedTools)) {
    return {
      kind: 'limited',
      label: '受限',
      detail: limitedDetailFor(item, limitedToolDetails) || 'Doctor 已标记该工具不可用或缺少配置。',
    };
  }
  if (cacheStale || !oha?.command_exists || !checked) {
    return {
      kind: 'pending',
      label: '待检测',
      detail: '运行 Doctor 后会显示更准确的工具状态。',
    };
  }
  if (isToolAvailable(item, availableTools)) {
    return {
      kind: 'ready',
      label: '可用',
      detail: 'Doctor 已确认该工具可用。',
    };
  }
  if (!availableTools.length && oha?.ready && oha.readiness_level && oha.readiness_level !== 'unknown') {
    return {
      kind: 'ready',
      label: '可用',
      detail: '最近一次 Doctor 没有报告该工具受限。',
    };
  }
  return {
    kind: 'pending',
    label: '待检测',
    detail: '当前 Doctor 输出未包含该工具的可用性结论。',
  };
}

function formatShortDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function isToolLimited(item: NativeToolCatalogItem, limitedTools?: string[]): boolean {
  const limited = new Set((limitedTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => limited.has(canonicalToolName(alias)));
}

function isToolAvailable(item: NativeToolCatalogItem, availableTools?: string[]): boolean {
  const available = new Set((availableTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => available.has(canonicalToolName(alias)));
}

function attentionItemsForTools(
  catalog: NativeToolCatalogItem[],
  limitedTools: string[],
  nativeToolsets: NativeToolsetItem[],
  limitedToolDetails: Record<string, string>,
): ToolAttentionItem[] {
  const items: ToolAttentionItem[] = [];
  const seen = new Set<string>();

  for (const item of catalog) {
    const aliases = toolNameAliases(item).map(canonicalToolName);
    const disabled = !toolsetEnabledForItem(item, nativeToolsets);
    const limited = isToolLimited(item, limitedTools);
    if (!disabled && !limited) continue;

    aliases.forEach((alias) => seen.add(alias));
    items.push({
      id: canonicalToolName(item.id),
      label: item.label,
      reason: disabled ? 'disabled' : 'limited',
      detail: disabled
        ? 'Native tools list 显示此工具组当前已禁用。'
        : limitedDetailFor(item, limitedToolDetails) || 'Doctor 已标记该工具不可用或缺少配置。',
    });
  }

  const knownAliases = new Set(catalog.flatMap(toolNameAliases).map(canonicalToolName));
  for (const tool of limitedTools || []) {
    const id = canonicalToolName(tool);
    if (seen.has(id) || knownAliases.has(id)) continue;
    seen.add(id);
    items.push({
      id,
      label: tool,
      reason: 'unknown',
      detail: 'Doctor 报告了这个受限项，但当前工具清单没有对应配置卡片。',
    });
  }

  return items;
}

function isHiddenNativeTool(tool: string | undefined): boolean {
  return Boolean(tool && HIDDEN_NATIVE_TOOLS.has(canonicalToolName(tool)));
}

function limitedDetailFor(item: NativeToolCatalogItem, details: Record<string, string>): string {
  const aliases = new Set(toolNameAliases(item).map(canonicalToolName));
  const match = Object.entries(details || {}).find(([key]) => aliases.has(canonicalToolName(key)));
  return match?.[1] || '';
}

function configForCatalogItem(item: NativeToolCatalogItem, configById: Map<string, ToolConfigItem>): ToolConfigItem | undefined {
  return toolNameAliases(item)
    .map((alias) => configById.get(canonicalToolName(alias)))
    .find(Boolean);
}

function visibleConfiguredCount(tool: ToolConfigItem): { configured: number; total: number } {
  const draft = initialDraftForTool(tool);
  const visible = visibleFieldsForTool(tool, draft);
  return {
    configured: visible.filter((field) => field.configured).length,
    total: visible.length,
  };
}

function visibleFieldsForTool(tool: ToolConfigItem, draft: Record<string, ConfigFieldValue>): ToolConfigField[] {
  return tool.fields.filter((field) => fieldIsVisible(field, draft));
}

function fieldIsVisible(field: ToolConfigField, draft: Record<string, ConfigFieldValue>): boolean {
  const condition = field.visible_when;
  if (!condition?.field) return true;
  const current = String(draft[condition.field] ?? '').trim();
  if (condition.equals !== undefined) return current === String(condition.equals);
  if (Array.isArray(condition.in)) return condition.in.map(String).includes(current);
  return true;
}

function optionsForField(field: ToolConfigField, draft: Record<string, ConfigFieldValue>): Array<{ value: string; label: string }> {
  if (field.option_groups && field.options_follow_field) {
    const provider = String(draft[field.options_follow_field] ?? '').trim();
    const grouped = field.option_groups[provider];
    if (grouped?.length) return grouped;
  }
  return field.options || [];
}

function normalizeDependentSelects(
  tool: ToolConfigItem,
  draft: Record<string, ConfigFieldValue>,
  changedKey?: string,
): Record<string, ConfigFieldValue> {
  const next = { ...draft };
  for (const field of tool.fields) {
    if (!field.options_follow_field) continue;
    if (changedKey && field.options_follow_field !== changedKey) continue;
    const options = optionsForField(field, next);
    if (!options.length) {
      if ((changedKey === field.options_follow_field || !field.configured) && field.kind === 'combo') {
        next[field.key] = '';
      }
      continue;
    }
    const current = String(next[field.key] ?? '');
    const currentIsSuggested = options.some((option) => option.value === current);
    if (
      changedKey === field.options_follow_field
      || (field.kind === 'select' && !currentIsSuggested)
      || (field.kind === 'combo' && !field.configured && !currentIsSuggested)
    ) {
      next[field.key] = options[0].value;
    }
  }
  return next;
}

function initialDraftForTool(tool: ToolConfigItem): Record<string, ConfigFieldValue> {
  const draft = tool.fields.reduce<Record<string, ConfigFieldValue>>((draft, field) => {
    draft[field.key] = field.kind === 'checkbox' ? Boolean(field.value) : String(field.value ?? '');
    return draft;
  }, {});
  return normalizeDependentSelects(tool, draft);
}

function draftSignature(draft: Record<string, ConfigFieldValue>): string {
  return JSON.stringify(
    Object.keys(draft)
      .sort()
      .map((key) => [key, draft[key]]),
  );
}

function toolNameAliases(item: NativeToolCatalogItem): string[] {
  return [item.id, ...(item.aliases || [])];
}

function canonicalToolName(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, '-');
}
