import { useEffect, useMemo, useRef, useState } from 'react';

import { apiGet, apiPost, copyText } from '../lib/bridge';
import { listModelProfiles, type ModelProfile, type ModelProfilesPayload } from '../lib/modelProfiles';
import { currentParam, navigateTo } from '../lib/view';

type DiagnosticAction = {
  id: string;
  label: string;
  command: string;
  description: string;
};

type DiagnosticResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  action_id?: string;
  label?: string;
  description?: string;
  command?: string;
  returncode?: number;
  stdout?: string;
  stderr?: string;
  output?: string;
  elapsed_seconds?: number;
  cached_at?: string;
  stale?: boolean;
  diagnostic_cache?: DiagnosticCache;
  doctor_summary?: DoctorSummary;
  dashboard?: DashboardStatus;
};

type DoctorSummary = {
  readiness_level?: string;
  available_tools?: string[];
  limited_tools?: string[];
  limited_tool_details?: Record<string, string>;
  doctor_issues_count?: number;
};

type DiagnosticCache = {
  stale?: boolean;
  reason?: string;
  updated_at?: string;
  commands?: Record<string, DiagnosticResult>;
};

type DashboardStatus = {
  bridge?: { state?: string; status?: string; running?: string; url?: string };
  native_agent?: {
    ready?: boolean;
    command_exists?: boolean;
    readiness_level?: string;
    platform?: string;
    available_tools?: string[];
    limited_tools?: string[];
    limited_tool_details?: Record<string, string>;
    doctor_issues_count?: number;
    native_agent?: {
      ready?: boolean;
      reason?: string;
      message?: string;
      profile_id?: string;
      model?: string;
      provider?: string;
    };
  };
  workspace?: { initialized?: boolean; path?: string };
};

type SettingsOverviewPayload = {
  tts?: {
    enabled?: boolean;
    provider?: string;
    gsv_base_url?: string;
  };
  mode_settings?: Record<string, {
    id?: string;
    title?: string;
    summary?: string;
    config?: Record<string, unknown>;
  }>;
};

type RuntimeStatus = {
  service?: string;
  version?: string;
  uptime_seconds?: number;
  task_counts?: Record<string, number>;
  native_agent_ready?: boolean;
};

type TaskInfo = {
  task_id: string;
  description: string;
  task_type: string;
  status: string;
  risk_level: string;
  created_at: string;
  updated_at: string;
  result?: string | null;
  error?: string | null;
  chat_session_id?: string | null;
};

type TaskListResponse = {
  tasks?: TaskInfo[];
  total?: number;
};

type TaskResponse = {
  task?: TaskInfo;
};

type AssistantIntentResult = {
  ok?: boolean;
  action?: string;
  task_id?: string | null;
  message?: string;
};

type ScreenshotProbe = {
  image_base64?: string;
  format?: string;
  width?: number;
  height?: number;
  captured_at?: string;
};

type DesktopPermissionSettingsResult = {
  ok?: boolean;
  opened?: boolean;
  target?: string;
  label?: string;
  settings_url?: string;
  message?: string;
  error?: string;
};

type ActiveWindowProbe = {
  title?: string;
  app_name?: string;
  pid?: number | null;
  queried_at?: string;
};

type DiagnosticOverviewItem = {
  label: string;
  detail: string;
  status: 'passed' | 'warning' | 'error';
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
  native_toolsets?: NativeToolsetItem[];
  tools?: ToolConfigItem[];
};

type DiagnosticToolCard = {
  item: NativeToolCatalogItem;
  status: ToolStatus;
  config?: ToolConfigItem;
  enabledByToolsList: boolean;
  configuredCount: { configured: number; total: number };
};

const DIAGNOSTIC_ACTIONS: DiagnosticAction[] = [
  {
    id: 'config-check',
    label: '检查配置结构',
    command: 'native config check',
    description: '检查缺失或过期配置，不会发起模型请求。',
  },
  {
    id: 'doctor',
    label: '运行 Doctor',
    command: 'native doctor',
    description: '检查 Native Runtime、模型配置和本地运行环境。',
  },
  {
    id: 'auth-list',
    label: '查看凭据池',
    command: 'native auth list',
    description: '查看 Model Profile 记录的 provider 凭据状态；输出会脱敏。',
  },
];

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
    label: 'Native 文本转语音',
    category: '多模态',
    description: 'Native Agent 自己暴露的文本转音频工具；不等同于 Yachiyo 主动关怀的 GPT-SoVITS 播报配置。',
    requirement: '需要 Native tts 工具启用',
  },
  {
    id: 'terminal',
    label: '终端执行',
    category: '本地工作',
    description: '经过 Native PolicyGate 和审批后执行命令并读取结果。',
    requirement: '需要 Native terminal.run 工具权限',
  },
  {
    id: 'file',
    label: '文件读写',
    category: '本地工作',
    description: '读取、生成和修改本地工作文件。',
    requirement: '需要 Native 文件工具权限',
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
    id: 'memory',
    label: '记忆',
    category: '长期上下文',
    description: '读取和维护 Native 记忆信息。',
    requirement: '需要 memory 工具集启用',
  },
  {
    id: 'session_search',
    label: '会话检索',
    category: '长期上下文',
    description: '检索历史会话，帮助跨会话延续上下文。',
    requirement: '需要会话索引可用',
  },
  {
    id: 'todo',
    label: '任务清单',
    category: '长期上下文',
    description: '维护 Native 内部的待办与计划状态。',
    requirement: '需要 todo 工具集启用',
  },
  {
    id: 'cronjob',
    label: '定时任务',
    category: '自动化',
    description: '创建或管理 Native 侧的定时自动化。',
    requirement: '需要 cronjob 工具集配置',
  },
  {
    id: 'clarify',
    label: '澄清问题',
    category: '自动化',
    description: '让 Native 在缺少关键信息时向用户提问。',
    requirement: '需要 clarify 工具集启用',
  },
  {
    id: 'delegation',
    label: '任务委派',
    category: '自动化',
    description: '让 Native 将任务拆分给子 agent 或协作流程。',
    requirement: '需要 delegation 工具集启用',
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

export function DiagnosticsView() {
  const initialCommand = normalizeDiagnosticCommand(currentParam('command'));
  const permissionTargets = diagnosticPermissionTargets(currentParam('permission_targets'));
  const permissionTargetSummary = diagnosticPermissionTargetSummary(permissionTargets);
  const [selectedCommand, setSelectedCommand] = useState(initialCommand || DIAGNOSTIC_ACTIONS[0].command);
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [diagnosticCache, setDiagnosticCache] = useState<DiagnosticCache | null>(null);
  const [overview, setOverview] = useState<DashboardStatus | null>(null);
  const [modelProfiles, setModelProfiles] = useState<ModelProfilesPayload | null>(null);
  const [settingsOverview, setSettingsOverview] = useState<SettingsOverviewPayload | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [toolConfig, setToolConfig] = useState<ToolConfigPayload | null>(null);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [taskDraft, setTaskDraft] = useState({ description: '', task_type: 'general', risk_level: 'low' });
  const [intentText, setIntentText] = useState('');
  const [intentResult, setIntentResult] = useState<AssistantIntentResult | null>(null);
  const [screenProbe, setScreenProbe] = useState<ScreenshotProbe | null>(null);
  const [activeWindowProbe, setActiveWindowProbe] = useState<ActiveWindowProbe | null>(null);
  const [runtimeBusy, setRuntimeBusy] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const lastAutoRunRef = useRef('');

  const selectedAction = useMemo(
    () => DIAGNOSTIC_ACTIONS.find((action) => action.command === selectedCommand) || DIAGNOSTIC_ACTIONS[0],
    [selectedCommand],
  );
  const toolConfigById = useMemo(() => {
    const map = new Map<string, ToolConfigItem>();
    (toolConfig?.tools || []).forEach((tool) => map.set(canonicalToolName(tool.id), tool));
    return map;
  }, [toolConfig]);
  const nativeToolsets = toolConfig?.native_toolsets || [];
  const toolCards = useMemo(() => {
    const doctorState = diagnosticDoctorState(overview, diagnosticCache);
    return NATIVE_TOOL_CATALOG
      .filter((item) => !isHiddenNativeTool(item.id))
      .map((item) => diagnosticToolCardFor(item, doctorState, nativeToolsets, toolConfigById));
  }, [diagnosticCache, nativeToolsets, overview, toolConfigById]);
  const attentionToolCount = toolCards.filter((card) => card.status.kind === 'limited' || !card.enabledByToolsList).length;
  const configuredToolCount = toolCards.filter((card) => card.config).length;
  const initialLoading = overviewLoading || toolsLoading || (runtimeBusy === 'refresh' && !runtimeStatus);
  const loadingActive = initialLoading || busy || Boolean(runtimeBusy);

  useEffect(() => {
    if (!initialCommand || lastAutoRunRef.current === initialCommand) return;
    lastAutoRunRef.current = initialCommand;
    void runDiagnostic(initialCommand);
  }, [initialCommand]);

  useEffect(() => {
    if (initialCommand) return;
    void loadDiagnosticCache(selectedAction.id);
  }, [initialCommand, selectedAction.id]);

  useEffect(() => {
    let disposed = false;
    void loadDashboardSnapshot(() => disposed);
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void loadModelProfileSnapshot(() => disposed);
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    apiGet<SettingsOverviewPayload>('/ui/settings')
      .then((payload) => {
        if (!disposed) setSettingsOverview(payload);
      })
      .catch(() => {
        if (!disposed) setSettingsOverview(null);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void loadRuntimeSnapshot(() => disposed);
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void refreshToolConfig(() => disposed);
    return () => {
      disposed = true;
    };
  }, []);

  async function loadDiagnosticCache(actionId: string) {
    try {
      const cache = await apiGet<DiagnosticCache>('/ui/native-agent/diagnostics/cache');
      setDiagnosticCache(cache);
      const cachedResult = cache.commands?.[actionId];
      if (cachedResult) {
        setResult(cachedResult);
        setStatus(diagnosticCacheStatus(cache, cachedResult));
      }
    } catch {
      setDiagnosticCache(null);
    }
  }

  async function runDiagnostic(command: string = selectedCommand) {
    const normalized = normalizeDiagnosticCommand(command) || DIAGNOSTIC_ACTIONS[0].command;
    const action = DIAGNOSTIC_ACTIONS.find((item) => item.command === normalized) || DIAGNOSTIC_ACTIONS[0];
    setSelectedCommand(action.command);
    setBusy(true);
    setStatus(`正在执行：${action.command}`);
    try {
      const payload = await apiPost<DiagnosticResult>('/ui/native-agent/diagnostic-command', { command: action.command });
      setResult(payload);
      if (payload.diagnostic_cache) setDiagnosticCache(payload.diagnostic_cache);
      if (payload.dashboard) setOverview(payload.dashboard);
      else void loadDashboardSnapshot();
      void loadModelProfileSnapshot();
      setStatus(payload.success ? payload.message || `${action.label} 完成` : payload.error || `${action.label} 失败`);
      void refreshToolConfig();
    } catch (err) {
      setResult(null);
      setStatus(err instanceof Error ? err.message : `${action.label} 失败`);
    } finally {
      setBusy(false);
    }
  }

  async function loadDashboardSnapshot(isDisposed: () => boolean = () => false) {
    setOverviewLoading(true);
    try {
      const payload = await apiGet<DashboardStatus>('/ui/dashboard');
      if (!isDisposed()) setOverview(payload);
    } catch {
      if (!isDisposed()) setOverview(null);
    } finally {
      if (!isDisposed()) setOverviewLoading(false);
    }
  }

  async function loadModelProfileSnapshot(isDisposed: () => boolean = () => false) {
    try {
      const payload = await listModelProfiles();
      if (!isDisposed()) setModelProfiles(payload);
    } catch {
      if (!isDisposed()) setModelProfiles(null);
    }
  }

  async function copyOutput() {
    if (!result) return;
    const text = result.output || [result.stdout, result.stderr].filter(Boolean).join('\n') || '';
    if (!text) return;
    await copyText(text);
    setStatus('诊断输出已复制');
  }

  async function loadRuntimeSnapshot(isDisposed: () => boolean = () => false) {
    setRuntimeBusy((current) => current || 'refresh');
    try {
      const [runtimeResult, tasksResult] = await Promise.allSettled([
        apiGet<RuntimeStatus>('/status'),
        apiGet<TaskListResponse>('/tasks'),
      ]);
      if (isDisposed()) return;
      if (runtimeResult.status === 'fulfilled') setRuntimeStatus(runtimeResult.value);
      if (tasksResult.status === 'fulfilled') setTasks(tasksResult.value.tasks || []);
    } finally {
      if (!isDisposed()) setRuntimeBusy((current) => (current === 'refresh' ? '' : current));
    }
  }

  async function refreshToolConfig(isDisposed: () => boolean = () => false) {
    setToolsLoading(true);
    try {
      const payload = await apiGet<ToolConfigPayload>('/ui/native-agent/tools/config');
      if (!isDisposed()) setToolConfig(payload);
    } catch {
      if (!isDisposed()) setToolConfig(null);
    } finally {
      if (!isDisposed()) setToolsLoading(false);
    }
  }

  async function createTask() {
    if (!taskDraft.description.trim() || runtimeBusy) return;
    setRuntimeBusy('create-task');
    setStatus('正在创建低风险任务...');
    try {
      const result = await apiPost<TaskResponse>('/tasks', {
        description: taskDraft.description.trim(),
        task_type: taskDraft.task_type,
        risk_level: taskDraft.risk_level,
      });
      if (result.task) setTasks((current) => [result.task as TaskInfo, ...current.filter((task) => task.task_id !== result.task?.task_id)]);
      setTaskDraft((current) => ({ ...current, description: '' }));
      setStatus('任务已创建');
      void loadRuntimeSnapshot();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '创建任务失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function cancelTask(taskId: string) {
    if (runtimeBusy) return;
    setRuntimeBusy(`cancel-${taskId}`);
    setStatus('正在取消任务...');
    try {
      const result = await apiPost<TaskResponse>(`/tasks/${encodeURIComponent(taskId)}/cancel`);
      if (result.task) setTasks((current) => current.map((task) => task.task_id === taskId ? result.task as TaskInfo : task));
      setStatus('任务已取消');
      void loadRuntimeSnapshot();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '取消任务失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function runAssistantIntent(dryRun: boolean) {
    const text = intentText.trim();
    if (!text || runtimeBusy) return;
    setRuntimeBusy(dryRun ? 'intent-dry-run' : 'intent-create');
    setIntentResult(null);
    setStatus(dryRun ? '正在分析助手意图...' : '正在通过助手意图创建低风险任务...');
    try {
      const result = await apiPost<AssistantIntentResult>('/assistant/intent', {
        text,
        source: 'desktop-diagnostics',
        sender_id: 'desktop',
        dry_run: dryRun,
      });
      setIntentResult(result);
      setStatus(result.ok ? result.message || '助手意图已完成' : result.message || '助手意图未执行');
      if (!dryRun) void loadRuntimeSnapshot();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '助手意图测试失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function probeScreen() {
    if (runtimeBusy) return;
    setRuntimeBusy('screen');
    setStatus('正在获取当前屏幕摘要...');
    try {
      const result = await apiGet<ScreenshotProbe>('/screen/current');
      setScreenProbe(result);
      setStatus(`已获取屏幕截图摘要：${result.width || '—'}×${result.height || '—'}`);
    } catch (err) {
      setScreenProbe(null);
      setStatus(err instanceof Error ? err.message : '截图探测失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function openDesktopPermissionSettings(target: string) {
    if (runtimeBusy) return;
    setRuntimeBusy(`permission-${target}`);
    setStatus('正在打开系统权限设置...');
    try {
      const result = await apiPost<DesktopPermissionSettingsResult>(
        '/ui/yachiyo/desktop-permissions/open-settings',
        { target },
      );
      setStatus(result.message || result.error || (result.ok ? '已打开系统权限设置' : '未能打开系统权限设置'));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开系统权限设置失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  async function probeActiveWindow() {
    if (runtimeBusy) return;
    setRuntimeBusy('active-window');
    setStatus('正在读取活动窗口...');
    try {
      const result = await apiGet<ActiveWindowProbe>('/system/active-window');
      setActiveWindowProbe(result);
      setStatus(`当前活动窗口：${result.app_name || '—'} — ${result.title || '无标题'}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '活动窗口探测失败');
    } finally {
      setRuntimeBusy('');
    }
  }

  return (
    <section className="hy-route-page hy-diagnostics-page">
      <header className="hy-page-header hy-diagnostics-header hy-stagger">
        <div>
          <span className="hy-eyebrow">Diagnostics · Raw Output</span>
          <h2>诊断详情</h2>
          <p>查看 Doctor 原始输出、运行时任务、本地能力探测和排障日志；工作链路与基础设施状态统一在能力中心查看。</p>
        </div>
        <div className="hy-action-row">
          <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('tools')}>
            打开能力中心
          </button>
          <button
            className="hy-btn hy-btn-primary"
            type="button"
            data-testid="diagnostics-run-command"
            disabled={busy}
            onClick={() => void runDiagnostic()}
          >
            {busy ? '运行中...' : '重新运行'}
          </button>
          <button type="button" className="hy-btn hy-btn-ghost" disabled={loadingActive} onClick={() => void refreshToolConfig()}>
            {toolsLoading ? '同步中...' : '同步工具'}
          </button>
        </div>
      </header>

      <DiagnosticLoadingStrip
        active={loadingActive}
        label={diagnosticLoadingLabel({ initialLoading, busy, runtimeBusy, toolsLoading })}
      />

      {status ? <div className={diagnosticNoticeClass(status)} data-testid="diagnostics-status">{status}</div> : null}

      <section className="hy-diagnostic-grid hy-stagger" aria-label="系统检测">
        {diagnosticOverviewItems(overview, diagnosticCache, settingsOverview, modelProfiles).map((item) => (
          <article className={`hy-diagnostic-check ${item.status}`} key={item.label}>
            <span>{item.label}</span>
            <strong>{diagnosticStatusLabel(item.status)}</strong>
            <small>{item.detail}</small>
          </article>
        ))}
      </section>

      <section className="hy-diagnostics-command-grid hy-stagger" aria-label="诊断命令">
        {DIAGNOSTIC_ACTIONS.map((action) => (
          <button
            type="button"
            className={action.command === selectedAction.command ? 'hy-diagnostics-command-card selected' : 'hy-diagnostics-command-card'}
            disabled={busy}
            key={action.id}
            onClick={() => void runDiagnostic(action.command)}
          >
            <span>{action.label}</span>
            <strong>{action.command}</strong>
            <small>{action.description}</small>
          </button>
        ))}
      </section>

      <section className="hy-diagnostics-card hy-diagnostics-tools hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>工具配置入口</h2>
            <p className="section-caption">Native Runtime、Doctor 摘要和工具清单入口已经下沉到能力中心的基础设施区；这里保留 raw output 和排障详情。</p>
          </div>
          <StatusPill active={!attentionToolCount && !toolsLoading} label={toolsLoading ? '同步中' : `${attentionToolCount} 个需处理`} />
        </div>
        <div className="hy-diagnostics-tool-summary" aria-label="工具统计">
          <span>工具目录：{toolCards.length}</span>
          <span>配置入口：{configuredToolCount}</span>
          <span>Doctor：{diagnosticCache?.stale ? '需重检' : diagnosticDoctorState(overview, diagnosticCache).checked ? '已读取' : '待运行'}</span>
        </div>
        <div className="hy-diagnostics-routing-grid">
          <article className="hy-diagnostics-route-card">
            <strong>能力中心</strong>
            <span>Native Runtime、工具清单同步、Provider 配置、Agent Runtime 与 API 测试。</span>
            <button type="button" className="hy-btn hy-btn-primary" onClick={() => navigateTo('tools')}>打开能力中心</button>
          </article>
          <article className="hy-diagnostics-route-card">
            <strong>诊断详情</strong>
            <span>Doctor raw output、配置检查、Bridge runtime、任务队列和本地探测仍在这里。</span>
            <button type="button" className="hy-btn hy-btn-ghost" disabled={busy} onClick={() => void runDiagnostic('native doctor')}>
              {busy ? '运行中...' : '运行 Doctor'}
            </button>
          </article>
        </div>
      </section>

      <section className="hy-diagnostics-card diagnostic-result-panel hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>运行状态</h2>
            <p className="section-caption">读取 /status 与 /tasks，显示 Bridge Runtime、Native ready 和任务计数。</p>
          </div>
          <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(runtimeBusy)} onClick={() => void loadRuntimeSnapshot()}>
            {runtimeBusy === 'refresh' ? '刷新中...' : '刷新'}
          </button>
        </div>
        <div className="diagnostic-result-meta">
          <span>服务：{runtimeStatus?.service || '—'}</span>
          <span>版本：{runtimeStatus?.version || '—'}</span>
          <span>Uptime：{formatDuration(runtimeStatus?.uptime_seconds)}</span>
          <span>Native Agent：{runtimeStatus?.native_agent_ready ? 'ready' : 'not ready'}</span>
          <span>任务：{formatTaskCounts(runtimeStatus?.task_counts)}</span>
        </div>
      </section>

      <section className="hy-diagnostics-card diagnostic-result-panel hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>任务队列</h2>
            <p className="section-caption">只创建默认低风险任务；pending / running 任务可以取消。</p>
          </div>
          <span>{tasks.length} 项</span>
        </div>
        <div className="native-config-form-grid">
          <label className="settings-field wide" htmlFor="diagnostics-task-description">
            <span>任务描述</span>
            <input
              id="diagnostics-task-description"
              value={taskDraft.description}
              maxLength={500}
              placeholder="例如：检查当前运行状态"
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setTaskDraft((current) => ({ ...current, description: event.target.value }))}
            />
          </label>
          <label className="settings-field" htmlFor="diagnostics-task-type">
            <span>任务类型</span>
            <select
              id="diagnostics-task-type"
              value={taskDraft.task_type}
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setTaskDraft((current) => ({ ...current, task_type: event.target.value }))}
            >
              <option value="general">general</option>
              <option value="status_query">status_query</option>
              <option value="screenshot">screenshot</option>
              <option value="active_window">active_window</option>
            </select>
          </label>
          <label className="settings-field" htmlFor="diagnostics-task-risk">
            <span>风险等级</span>
            <select
              id="diagnostics-task-risk"
              value={taskDraft.risk_level}
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setTaskDraft((current) => ({ ...current, risk_level: event.target.value }))}
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
            </select>
          </label>
          <div className="settings-savebar wide-form-note">
            <span>不提供 high 风险快捷创建入口。</span>
            <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(runtimeBusy) || !taskDraft.description.trim()} onClick={() => void createTask()}>
              {runtimeBusy === 'create-task' ? '创建中...' : '创建任务'}
            </button>
          </div>
        </div>
        <div className="diagnostic-task-list">
          {tasks.slice(0, 10).map((task) => (
            <article className="diagnostic-task-row" key={task.task_id}>
              <div>
                <strong>{task.description}</strong>
                <small>{task.task_type} · {task.risk_level} · {formatShortDateTime(task.updated_at)}</small>
                {task.result || task.error ? <p>{task.error || task.result}</p> : null}
              </div>
              <div className="diagnostic-task-actions">
                <span className={task.status === 'completed' ? 'status-pill ok' : 'status-pill warn'}>{task.status}</span>
                {task.status === 'pending' || task.status === 'running' ? (
                  <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(runtimeBusy)} onClick={() => void cancelTask(task.task_id)}>
                    {runtimeBusy === `cancel-${task.task_id}` ? '取消中...' : '取消'}
                  </button>
                ) : null}
              </div>
            </article>
          ))}
          {!tasks.length ? <div className="empty-state inline-empty">暂无任务</div> : null}
        </div>
      </section>

      <section className="hy-diagnostics-card diagnostic-result-panel hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>助手意图测试</h2>
            <p className="section-caption">默认先 dry-run；执行按钮会调用 /assistant/intent 创建低风险任务。</p>
          </div>
        </div>
        <div className="native-config-form-grid">
          <label className="settings-field wide" htmlFor="diagnostics-intent-text">
            <span>输入文本</span>
            <input
              id="diagnostics-intent-text"
              value={intentText}
              maxLength={1000}
              placeholder="例如：帮我检查当前系统状态"
              disabled={Boolean(runtimeBusy)}
              onChange={(event) => setIntentText(event.target.value)}
            />
          </label>
          <div className="settings-savebar wide-form-note">
            <span>{intentResult ? `${intentResult.action || 'intent'}：${intentResult.message || '完成'}` : '不会自动执行高风险动作。'}</span>
            <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(runtimeBusy) || !intentText.trim()} onClick={() => void runAssistantIntent(true)}>
              {runtimeBusy === 'intent-dry-run' ? '分析中...' : 'Dry-run'}
            </button>
            <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(runtimeBusy) || !intentText.trim()} onClick={() => void runAssistantIntent(false)}>
              {runtimeBusy === 'intent-create' ? '执行中...' : '创建低风险任务'}
            </button>
          </div>
        </div>
      </section>

      <section className="hy-diagnostics-card diagnostic-result-panel hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>本地能力探测</h2>
            <p className="section-caption">手动调用截图与活动窗口接口；截图只显示本地缩略预览和尺寸。</p>
            {permissionTargetSummary ? (
              <p className="section-caption diagnostic-targeted-caption" data-testid="diagnostics-permission-targets">
                Chat 提示的恢复目标：{permissionTargetSummary}
              </p>
            ) : null}
          </div>
          <div className="diagnostic-result-actions">
            <button type="button" className="hy-btn hy-btn-ghost" data-testid="diagnostics-screen-probe" disabled={Boolean(runtimeBusy)} onClick={() => void probeScreen()}>{runtimeBusy === 'screen' ? '探测中...' : '截图摘要'}</button>
            <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(runtimeBusy)} onClick={() => void probeActiveWindow()}>{runtimeBusy === 'active-window' ? '探测中...' : '活动窗口'}</button>
            <button type="button" className={diagnosticPermissionActionClass(permissionTargets, 'screen_recording')} data-testid="diagnostics-open-screen-recording-settings" disabled={Boolean(runtimeBusy)} onClick={() => void openDesktopPermissionSettings('screen_recording')}>屏幕录制权限</button>
            <button type="button" className={diagnosticPermissionActionClass(permissionTargets, 'accessibility')} data-testid="diagnostics-open-accessibility-settings" disabled={Boolean(runtimeBusy)} onClick={() => void openDesktopPermissionSettings('accessibility')}>辅助功能权限</button>
            <button type="button" className={diagnosticPermissionActionClass(permissionTargets, 'automation')} data-testid="diagnostics-open-automation-settings" disabled={Boolean(runtimeBusy)} onClick={() => void openDesktopPermissionSettings('automation')}>自动化权限</button>
            <button type="button" className={diagnosticPermissionActionClass(permissionTargets, 'music_app')} data-testid="diagnostics-open-music-app" disabled={Boolean(runtimeBusy)} onClick={() => void openDesktopPermissionSettings('music_app')}>Music.app</button>
            <button type="button" className={diagnosticPermissionActionClass(permissionTargets, 'chrome_cdp')} data-testid="diagnostics-open-browser-cdp-settings" disabled={Boolean(runtimeBusy)} onClick={() => navigateTo('tools', { tool: 'browser-cdp' })}>Chrome CDP</button>
          </div>
        </div>
        <div className="diagnostic-probe-grid">
          <article className="diagnostic-probe-card" data-testid="diagnostics-screen-probe-card">
            <strong>屏幕截图</strong>
            <span data-testid="diagnostics-screen-probe-summary">{screenProbe ? `${screenProbe.width || '—'}×${screenProbe.height || '—'} · ${screenProbe.format || 'png'} · ${formatShortDateTime(screenProbe.captured_at)}` : '未探测'}</span>
            {screenProbe?.image_base64 ? <img data-testid="diagnostics-screen-probe-image" src={`data:image/${screenProbe.format || 'png'};base64,${screenProbe.image_base64}`} alt="当前屏幕缩略图" /> : null}
          </article>
          <article className="diagnostic-probe-card">
            <strong>活动窗口</strong>
            <span>{activeWindowProbe ? `${activeWindowProbe.app_name || '—'} · ${activeWindowProbe.title || '无标题'}` : '未探测'}</span>
            <small>{activeWindowProbe?.pid ? `pid ${activeWindowProbe.pid}` : ''}{activeWindowProbe?.queried_at ? ` · ${formatShortDateTime(activeWindowProbe.queried_at)}` : ''}</small>
          </article>
        </div>
      </section>

      <section className="hy-diagnostics-card diagnostic-result-panel hy-stagger">
        <div className="section-heading-row">
          <div>
            <h2>{result?.label || selectedAction.label}</h2>
            <p className="section-caption">{result?.command || selectedAction.command}</p>
          </div>
          <StatusPill active={Boolean(result?.success) && !result?.stale} label={diagnosticResultLabel(result, busy)} />
        </div>
        <div className="diagnostic-result-meta">
          <span>退出码：{result?.returncode ?? '—'}</span>
          <span>耗时：{result?.elapsed_seconds !== undefined ? `${result.elapsed_seconds}s` : '—'}</span>
          {result?.cached_at ? <span>缓存：{formatShortDateTime(result.cached_at)}</span> : null}
          {diagnosticCache?.stale ? <span>配置已变化，建议重新运行</span> : null}
        </div>
        <pre className="diagnostic-output" data-testid="diagnostics-output">{diagnosticOutput(result, busy)}</pre>
        <div className="diagnostic-result-actions">
          <button type="button" className="hy-btn hy-btn-ghost" data-testid="diagnostics-copy-output" disabled={!result || busy} onClick={() => void copyOutput()}>复制输出</button>
        </div>
      </section>
    </section>
  );
}

function normalizeDiagnosticCommand(value: string): string {
  const normalized = value.trim().replace(/\s+/g, ' ');
  return DIAGNOSTIC_ACTIONS.find((action) => action.command === normalized || action.id === normalized)?.command || '';
}

type DiagnosticPermissionAction = 'screen_recording' | 'accessibility' | 'automation' | 'music_app' | 'chrome_cdp';

const diagnosticPermissionLabels: Record<DiagnosticPermissionAction, string> = {
  accessibility: '辅助功能权限',
  automation: '自动化权限',
  chrome_cdp: 'Chrome CDP',
  music_app: 'Music.app',
  screen_recording: '屏幕录制权限',
};

function diagnosticPermissionTargets(value: string): Set<DiagnosticPermissionAction> {
  const targets = new Set<DiagnosticPermissionAction>();
  value.split(',').forEach((item) => {
    const token = item.trim();
    if (!token) return;
    const action = diagnosticPermissionTargetAction(token);
    if (action) targets.add(action);
  });
  return targets;
}

function diagnosticPermissionTargetAction(token: string): DiagnosticPermissionAction | null {
  if (token === 'screen_recording' || token === 'screen_capture_probe_failed') return 'screen_recording';
  if (token === 'accessibility' || token === 'foreground_input') return 'accessibility';
  if (
    token === 'automation'
    || token === 'automation_or_accessibility'
    || token === 'active_window'
    || token === 'app_control'
    || token === 'open_command'
  ) {
    return 'automation';
  }
  if (token === 'music' || token === 'music_app' || token === 'apple_music' || token === 'media_control') return 'music_app';
  if (token === 'chrome_cdp' || token === 'browser_control') return 'chrome_cdp';
  return null;
}

function diagnosticPermissionTargetSummary(targets: Set<DiagnosticPermissionAction>): string {
  return Array.from(targets).map((target) => diagnosticPermissionLabels[target]).join('、');
}

function diagnosticPermissionActionClass(
  targets: Set<DiagnosticPermissionAction>,
  action: DiagnosticPermissionAction,
): string {
  return targets.has(action)
    ? 'hy-btn hy-btn-ghost diagnostic-targeted-action'
    : 'hy-btn hy-btn-ghost';
}

function diagnosticNoticeClass(message: string) {
  return /失败|错误|无法|不支持|超时/.test(message) ? 'notice danger' : 'notice';
}

function diagnosticCacheStatus(cache: DiagnosticCache, result: DiagnosticResult): string {
  const label = result.label || result.command || '诊断结果';
  const time = formatShortDateTime(result.cached_at || cache.updated_at);
  if (cache.stale) return `${label} 使用上次缓存（${time}），配置已变化，请手动重新运行`;
  return `${label} 使用上次缓存（${time}）`;
}

function diagnosticResultLabel(result: DiagnosticResult | null, busy: boolean): string {
  if (busy) return '运行中';
  if (!result) return '待运行';
  if (result.stale) return '需重检';
  return result.success ? '完成' : '失败';
}

function diagnosticOutput(result: DiagnosticResult | null, busy: boolean): string {
  if (busy && !result) return '正在等待 Native 输出...';
  if (!result) return '选择一个诊断命令后，结果会显示在这里。';
  return result.output || result.stdout || result.stderr || '命令没有输出。';
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function DiagnosticLoadingStrip({ active, label }: { active: boolean; label: string }) {
  return (
    <div className={active ? 'hy-diagnostics-loading active hy-stagger' : 'hy-diagnostics-loading hy-stagger'} role="status" aria-live="polite">
      <span className="hy-diagnostics-loading-dot" aria-hidden="true" />
      <strong>{label}</strong>
      <div className="hy-diagnostics-loading-track" aria-hidden="true">
        <span />
      </div>
    </div>
  );
}

function DiagnosticToolCardView({ card }: { card: DiagnosticToolCard }) {
  const { item, status, config, configuredCount } = card;
  const cardClass = `hy-diagnostics-tool-card ${status.kind}${card.enabledByToolsList ? '' : ' disabled'}`;
  return (
    <article className={cardClass}>
      <div className="hy-diagnostics-tool-head">
        <span>{item.category}</span>
        <strong className={`hy-diagnostics-tool-pill ${status.kind}`}>{status.label}</strong>
      </div>
      <h3>{item.label}</h3>
      <p>{item.description}</p>
      <small>{status.detail || item.requirement}</small>
      {config || item.id === 'tts' ? (
        <div className="hy-diagnostics-tool-actions">
          {config ? (
            <>
              <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('tools', { tool: config.id })}>
                配置
              </button>
              <span>{configuredCount.configured}/{configuredCount.total} 已配置</span>
            </>
          ) : (
            <>
              <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('proactive-tts')}>
                主动关怀语音
              </button>
              <span>Yachiyo 播报入口</span>
            </>
          )}
        </div>
      ) : null}
    </article>
  );
}

function diagnosticLoadingLabel({
  initialLoading,
  busy,
  runtimeBusy,
  toolsLoading,
}: {
  initialLoading: boolean;
  busy: boolean;
  runtimeBusy: string;
  toolsLoading: boolean;
}) {
  if (busy) return '正在运行 Native 诊断命令';
  if (runtimeBusy === 'refresh') return '正在刷新运行时状态';
  if (runtimeBusy) return '正在执行本地探测任务';
  if (toolsLoading) return '正在同步 Native 工具清单';
  if (initialLoading) return '正在整理诊断状态';
  return '诊断状态已同步';
}

type DiagnosticDoctorState = {
  checked: boolean;
  cacheStale: boolean;
  nativeAgent?: DashboardStatus['native_agent'];
  availableTools: string[];
  limitedTools: string[];
  limitedToolDetails: Record<string, string>;
};

function diagnosticDoctorState(data: DashboardStatus | null, cache: DiagnosticCache | null): DiagnosticDoctorState {
  const nativeAgent = data?.native_agent;
  const cacheStale = Boolean(cache?.stale);
  const doctorSummary = cacheStale ? undefined : cache?.commands?.doctor?.doctor_summary;
  const rawLimitedTools = doctorSummary ? doctorSummary.limited_tools || [] : nativeAgent?.limited_tools || [];
  const rawAvailableTools = doctorSummary?.available_tools?.length ? doctorSummary.available_tools : nativeAgent?.available_tools || [];
  const rawLimitedDetails = doctorSummary ? doctorSummary.limited_tool_details || {} : nativeAgent?.limited_tool_details || {};
  const limitedToolDetails = Object.fromEntries(
    Object.entries(rawLimitedDetails).filter(([tool]) => !isHiddenNativeTool(tool)),
  );
  const checked = Boolean(
    !cacheStale
    && (
      doctorSummary
      || rawAvailableTools.length
      || rawLimitedTools.length
      || (nativeAgent?.readiness_level && nativeAgent.readiness_level !== 'unknown')
    ),
  );

  return {
    checked,
    cacheStale,
    nativeAgent,
    availableTools: rawAvailableTools.filter((tool) => !isHiddenNativeTool(tool)),
    limitedTools: rawLimitedTools.filter((tool) => !isHiddenNativeTool(tool)),
    limitedToolDetails,
  };
}

function diagnosticToolCardFor(
  item: NativeToolCatalogItem,
  state: DiagnosticDoctorState,
  nativeToolsets: NativeToolsetItem[],
  configById: Map<string, ToolConfigItem>,
): DiagnosticToolCard {
  const config = configForCatalogItem(item, configById);
  const enabledByToolsList = toolsetEnabledForItem(item, nativeToolsets);
  const status = enabledByToolsList
    ? toolStatusFor(item, state)
    : {
        kind: 'limited' as const,
        label: '未启用',
        detail: 'Native tools list 显示此工具组当前已禁用。',
      };
  return {
    item,
    status,
    config,
    enabledByToolsList,
    configuredCount: config ? configuredCountForTool(config) : { configured: 0, total: 0 },
  };
}

function toolStatusFor(item: NativeToolCatalogItem, state: DiagnosticDoctorState): ToolStatus {
  if (item.planned) {
    return {
      kind: 'planned',
      label: '规划中',
      detail: '当前只展示方向，不启用本机工具调用。',
    };
  }
  if (isToolLimited(item, state.limitedTools)) {
    return {
      kind: 'limited',
      label: '受限',
      detail: limitedDetailFor(item, state.limitedToolDetails) || 'Doctor 已标记该工具不可用或缺少配置。',
    };
  }
  if (state.cacheStale || !state.nativeAgent?.command_exists || !state.checked) {
    return {
      kind: 'pending',
      label: '待检测',
      detail: '运行 Doctor 后会显示更准确的工具状态。',
    };
  }
  if (isToolAvailable(item, state.availableTools)) {
    return {
      kind: 'ready',
      label: '可用',
      detail: 'Doctor 已确认该工具可用。',
    };
  }
  if (!state.availableTools.length && state.nativeAgent.ready && state.nativeAgent.readiness_level && state.nativeAgent.readiness_level !== 'unknown') {
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

function toolsetEnabledForItem(item: NativeToolCatalogItem, toolsets?: NativeToolsetItem[]): boolean {
  if (!toolsets?.length) return true;
  const records = new Map(toolsets.map((toolset) => [canonicalToolName(toolset.canonical_id || toolset.id), toolset]));
  if (item.id === 'browser-cdp') return records.get('browser')?.enabled !== false;
  const match = toolNameAliases(item)
    .map((alias) => records.get(canonicalToolName(alias)))
    .find(Boolean);
  return match?.enabled !== false;
}

function configForCatalogItem(item: NativeToolCatalogItem, configById: Map<string, ToolConfigItem>): ToolConfigItem | undefined {
  return toolNameAliases(item)
    .map((alias) => configById.get(canonicalToolName(alias)))
    .find(Boolean);
}

function configuredCountForTool(tool: ToolConfigItem): { configured: number; total: number } {
  const visibleFields = tool.fields.filter((field) => fieldIsVisibleWithSavedValues(field, tool.fields));
  return {
    configured: tool.configured_count ?? visibleFields.filter((field) => field.configured).length,
    total: visibleFields.length,
  };
}

function fieldIsVisibleWithSavedValues(field: ToolConfigField, fields: ToolConfigField[]): boolean {
  const condition = field.visible_when;
  if (!condition?.field) return true;
  const source = fields.find((item) => item.key === condition.field);
  const current = String(source?.value ?? '').trim();
  if (condition.equals !== undefined) return current === String(condition.equals);
  if (Array.isArray(condition.in)) return condition.in.map(String).includes(current);
  return true;
}

function isToolLimited(item: NativeToolCatalogItem, limitedTools?: string[]): boolean {
  const limited = new Set((limitedTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => limited.has(canonicalToolName(alias)));
}

function isToolAvailable(item: NativeToolCatalogItem, availableTools?: string[]): boolean {
  const available = new Set((availableTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => available.has(canonicalToolName(alias)));
}

function limitedDetailFor(item: NativeToolCatalogItem, details: Record<string, string>): string {
  const aliases = new Set(toolNameAliases(item).map(canonicalToolName));
  const match = Object.entries(details || {}).find(([key]) => aliases.has(canonicalToolName(key)));
  return match?.[1] || '';
}

function isHiddenNativeTool(tool: string | undefined): boolean {
  return Boolean(tool && HIDDEN_NATIVE_TOOLS.has(canonicalToolName(tool)));
}

function toolNameAliases(item: NativeToolCatalogItem): string[] {
  return [item.id, ...(item.aliases || [])];
}

function canonicalToolName(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, '-');
}

function diagnosticOverviewItems(
  data: DashboardStatus | null,
  cache: DiagnosticCache | null,
  settings: SettingsOverviewPayload | null,
  modelProfiles: ModelProfilesPayload | null,
): DiagnosticOverviewItem[] {
  const bridge = data?.bridge?.state || data?.bridge?.status || data?.bridge?.running || '';
  const bridgeOk = /running|listening|ready|ok/i.test(bridge);
  const nativeAgent = data?.native_agent;
  const commandExists = Boolean(nativeAgent?.command_exists);
  const workspaceReady = Boolean(data?.workspace?.initialized);
  const doctorIssues = Number(nativeAgent?.doctor_issues_count || 0);
  const hasDoctorCache = Boolean(cache?.commands?.doctor);
  const model = modelDiagnosticStatus(data, modelProfiles);
  const live2d = live2dDiagnosticStatus(settings);
  const tts = ttsDiagnosticStatus(settings);

  return [
    {
      label: 'Python',
      status: commandExists ? 'passed' : 'warning',
      detail: nativeAgent?.platform || '随 Native Runtime 检测',
    },
    {
      label: 'Node.js',
      status: 'passed',
      detail: '桌面前端运行中',
    },
    {
      label: 'Bridge',
      status: bridgeOk ? 'passed' : 'warning',
      detail: data?.bridge?.url || bridge || '等待本机 Bridge',
    },
    {
      label: '模型',
      status: model.status,
      detail: model.detail,
    },
    {
      label: 'GPU',
      status: hasDoctorCache && !doctorIssues ? 'passed' : 'warning',
      detail: hasDoctorCache ? (doctorIssues ? `${doctorIssues} 项 Doctor 提示` : 'Doctor 未报告受限项') : '运行 Doctor 后刷新',
    },
    {
      label: '工作区',
      status: workspaceReady ? 'passed' : 'warning',
      detail: data?.workspace?.path || '等待初始化',
    },
    {
      label: 'Live2D',
      status: live2d.status,
      detail: live2d.detail,
    },
    {
      label: 'TTS',
      status: tts.status,
      detail: tts.detail,
    },
  ];
}

function modelDiagnosticStatus(
  data: DashboardStatus | null,
  modelProfiles: ModelProfilesPayload | null,
): DiagnosticOverviewItem {
  const nativeAgent = data?.native_agent;
  const commandExists = Boolean(nativeAgent?.command_exists);
  if (!commandExists && data) return { label: '模型', status: 'error', detail: 'Native Agent 未就绪' };
  const runtimeReadiness = nativeAgent?.native_agent;
  if (nativeAgent?.ready) {
    const model = runtimeReadiness?.model || defaultChatProfile(modelProfiles)?.model || '';
    return { label: '模型', status: 'passed', detail: model ? `默认模型：${model}` : '基础链路可用' };
  }
  const defaultProfile = defaultChatProfile(modelProfiles);
  if (defaultProfile) {
    if (defaultProfile.enabled === false) return { label: '模型', status: 'warning', detail: '默认模型已暂停' };
    if (!defaultProfile.api_key_configured) return { label: '模型', status: 'warning', detail: '默认模型缺少密钥' };
    if (!defaultProfile.base_url || !defaultProfile.model) return { label: '模型', status: 'warning', detail: '默认模型配置不完整' };
    if (defaultProfile.status !== 'available') return { label: '模型', status: 'warning', detail: '默认模型待测试' };
    return { label: '模型', status: 'passed', detail: `默认模型：${defaultProfile.model}` };
  }
  const availableProfiles = availableChatProfiles(modelProfiles);
  if (availableProfiles.length === 1) {
    return { label: '模型', status: 'passed', detail: `可用模型：${availableProfiles[0].model}` };
  }
  if (availableProfiles.length > 1) {
    return { label: '模型', status: 'warning', detail: '请选择默认对话模型' };
  }
  const readinessMessage = runtimeReadiness?.message || '';
  if (readinessMessage) return { label: '模型', status: 'warning', detail: readinessMessage };
  return { label: '模型', status: modelProfiles ? 'warning' : 'error', detail: modelProfiles ? '未找到可用对话模型' : '等待模型配置' };
}

function defaultChatProfile(modelProfiles: ModelProfilesPayload | null): ModelProfile | null {
  const profileId = String(modelProfiles?.defaults?.chat || '').trim();
  if (!profileId) return null;
  return (modelProfiles?.profiles || []).find((profile) => profile.profile_id === profileId && profile.capability === 'chat') || null;
}

function availableChatProfiles(modelProfiles: ModelProfilesPayload | null): ModelProfile[] {
  return (modelProfiles?.profiles || []).filter((profile) => profile.capability === 'chat'
    && profile.enabled !== false
    && profile.status === 'available'
    && Boolean(profile.api_key_configured)
    && Boolean(profile.model)
    && Boolean(profile.base_url));
}

function live2dDiagnosticStatus(settings: SettingsOverviewPayload | null): DiagnosticOverviewItem {
  const config = asPlainRecord(settings?.mode_settings?.live2d?.config);
  const resource = asPlainRecord(config.resource);
  const state = stringValue(config.model_state || resource.state);
  const detail = stringValue(resource.status_label || config.status_label || settings?.mode_settings?.live2d?.summary);
  if (state === 'path_valid' || state === 'loaded') {
    return { label: 'Live2D', status: 'passed', detail: detail || '资源已就绪' };
  }
  if (state === 'path_invalid' || state === 'path_not_live2d') {
    return { label: 'Live2D', status: 'error', detail: detail || '模型路径不可用' };
  }
  if (state === 'not_configured') {
    return { label: 'Live2D', status: 'warning', detail: detail || '尚未导入 Live2D 资源' };
  }
  return { label: 'Live2D', status: settings ? 'warning' : 'error', detail: settings ? '等待资源状态' : '等待设置数据' };
}

function ttsDiagnosticStatus(settings: SettingsOverviewPayload | null): DiagnosticOverviewItem {
  const tts = settings?.tts;
  if (!settings) return { label: 'TTS', status: 'error', detail: '等待设置数据' };
  if (!tts?.enabled || !tts.provider || tts.provider === 'none') {
    return { label: 'TTS', status: 'warning', detail: '主动关怀语音未启用' };
  }
  const provider = ttsProviderDiagnosticLabel(tts.provider);
  if (tts.provider === 'gpt-sovits') {
    return {
      label: 'TTS',
      status: 'passed',
      detail: tts.gsv_base_url ? `${provider} · ${tts.gsv_base_url}` : provider,
    };
  }
  return { label: 'TTS', status: 'passed', detail: provider };
}

function ttsProviderDiagnosticLabel(provider: string): string {
  if (provider === 'gpt-sovits') return 'GPT-SoVITS 本地服务';
  if (provider === 'http') return 'HTTP POST';
  if (provider === 'command') return '本地命令';
  return provider || '未知 Provider';
}

function asPlainRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

function diagnosticStatusLabel(status: DiagnosticOverviewItem['status']): string {
  if (status === 'passed') return 'passed';
  if (status === 'error') return 'error';
  return 'warning';
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

function formatDuration(value?: number) {
  if (!Number.isFinite(Number(value))) return '—';
  const seconds = Math.max(0, Math.floor(Number(value)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${rest}s`;
  return `${rest}s`;
}

function formatTaskCounts(counts?: Record<string, number>) {
  if (!counts) return '—';
  const parts = ['pending', 'running', 'completed', 'failed', 'cancelled']
    .map((key) => `${key}=${Number(counts[key] || 0)}`);
  return parts.join(' · ');
}
