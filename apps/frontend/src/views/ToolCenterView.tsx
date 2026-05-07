import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

import {
  apiGet,
  apiPost,
  hasEmbeddedTerminal,
  killDesktopTerminal,
  onDesktopTerminalData,
  onDesktopTerminalExit,
  openAppView,
  resizeDesktopTerminal,
  startDesktopTerminal,
  writeDesktopTerminal,
  type DesktopTerminalTask,
} from '../lib/bridge';
import { currentParam, navigateTo } from '../lib/view';

type HermesStatus = {
  status?: string;
  version?: string;
  platform?: string;
  command_exists?: boolean;
  hermes_home?: string;
  ready?: boolean;
  readiness_level?: string;
  available_tools?: string[];
  limited_tools?: string[];
  limited_tool_details?: Record<string, string>;
  doctor_issues_count?: number;
};

type DashboardData = {
  hermes?: HermesStatus;
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

type HermesToolCatalogItem = {
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

type HermesToolsetItem = {
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
  hermes_toolsets?: HermesToolsetItem[];
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

type HermesUpdateResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  update_available?: boolean;
  behind_commits?: number;
  version?: string | { version?: string; update_available?: boolean; behind_commits?: number; summary?: string };
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
type HermesUpdateMode = 'check' | 'run' | null;
type EmbeddedTerminalStatus = 'idle' | 'starting' | 'running' | 'exited' | 'error';
type EmbeddedTerminalSession = {
  id: string;
  task: DesktopTerminalTask;
  title: string;
};

const HERMES_TOOL_CATALOG: HermesToolCatalogItem[] = [
  {
    id: 'web',
    label: '联网与网页读取',
    category: '信息检索',
    description: '搜索、读取网页内容并把结果交给 Hermes 推理。',
    requirement: '需要 Hermes web/search 工具可用',
    aliases: ['search'],
  },
  {
    id: 'browser',
    label: '浏览器自动化',
    category: '信息检索',
    description: '通过浏览器会话访问需要交互的页面。',
    requirement: '需要 Hermes browser 工具可用',
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
    label: 'Hermes 文本转语音',
    category: '多模态',
    description: 'Hermes Agent 自己暴露的文本转音频工具；不等同于 Yachiyo 主动关怀的 GPT-SoVITS 播报配置。',
    requirement: '需要 Hermes tts 工具集启用',
  },
  {
    id: 'terminal',
    label: '终端执行',
    category: '本地工作',
    description: '在 Hermes 允许范围内执行命令和读取结果。',
    requirement: '需要 Hermes 本地执行权限',
  },
  {
    id: 'file',
    label: '文件读写',
    category: '本地工作',
    description: '读取、生成和修改本地工作文件。',
    requirement: '需要 Hermes 文件工具权限',
  },
  {
    id: 'skills',
    label: '技能加载',
    category: '本地工作',
    description: '加载 Hermes 或项目内定义的技能工作流。',
    requirement: '需要技能目录或插件可读取',
  },
  {
    id: 'code_execution',
    label: '代码执行',
    category: '本地工作',
    description: '运行受控代码片段，处理数据或验证逻辑。',
    requirement: '需要 Hermes 代码执行环境',
  },
  {
    id: 'memory',
    label: '记忆',
    category: '长期上下文',
    description: '读取和维护 Hermes 记忆信息。',
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
    description: '维护 Hermes 内部的待办与计划状态。',
    requirement: '需要 todo 工具集启用',
  },
  {
    id: 'cronjob',
    label: '定时任务',
    category: '自动化',
    description: '创建或管理 Hermes 侧的定时自动化。',
    requirement: '需要 cronjob 工具集配置',
  },
  {
    id: 'clarify',
    label: '澄清问题',
    category: '自动化',
    description: '让 Hermes 在缺少关键信息时向用户提问。',
    requirement: '需要 clarify 工具集启用',
  },
  {
    id: 'delegation',
    label: '任务委派',
    category: '自动化',
    description: '让 Hermes 将任务拆分给子 agent 或协作流程。',
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
    description: '连接 Hermes 的元宝扩展能力。',
    requirement: '需要 hermes-yuanbao 配置',
    aliases: ['hermes-yuanbao'],
  },
  {
    id: 'moa',
    label: 'MoA',
    category: '第三方扩展',
    description: '使用 Hermes 的多模型协作能力。',
    requirement: '需要实验工具或额外 provider 配置',
  },
  {
    id: 'rl',
    label: 'RL',
    category: '第三方扩展',
    description: '连接 Hermes 实验性强化学习相关能力。',
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

const HIDDEN_HERMES_TOOLS = new Set(['vision', 'vision_analyze']);

export function ToolCenterView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [diagnosticCache, setDiagnosticCache] = useState<DiagnosticCache | null>(null);
  const [toolConfig, setToolConfig] = useState<ToolConfigPayload | null>(null);
  const [draftToolId, setDraftToolId] = useState('');
  const [configDraft, setConfigDraft] = useState<Record<string, ConfigFieldValue>>({});
  const [savedDraftSnapshot, setSavedDraftSnapshot] = useState('');
  const [pendingNavigation, setPendingNavigation] = useState<PendingNavigation | null>(null);
  const [toolTestResult, setToolTestResult] = useState<ToolConfigTestResult | null>(null);
  const [hermesUpdate, setHermesUpdate] = useState<HermesUpdateResult | null>(null);
  const [error, setError] = useState('');
  const [actionStatus, setActionStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [configBusy, setConfigBusy] = useState(false);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateMode, setUpdateMode] = useState<HermesUpdateMode>(null);
  const [updateStartedAt, setUpdateStartedAt] = useState<number | null>(null);
  const [updateElapsedSeconds, setUpdateElapsedSeconds] = useState(0);
  const [updateWithFullBackup, setUpdateWithFullBackup] = useState(false);
  const [updateTerminalStatus, setUpdateTerminalStatus] = useState<EmbeddedTerminalStatus>('idle');
  const [updateTerminalMessage, setUpdateTerminalMessage] = useState('更新终端会显示 Hermes 的实时输出。');
  const [updateTerminalSession, setUpdateTerminalSession] = useState<EmbeddedTerminalSession | null>(null);
  const updateTerminalPanelRef = useRef<HTMLElement | null>(null);
  const updateTerminalHostRef = useRef<HTMLDivElement | null>(null);
  const updateTerminalRef = useRef<Terminal | null>(null);
  const updateFitAddonRef = useRef<FitAddon | null>(null);
  const updateTerminalIdRef = useRef<string | null>(null);

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const [payload, cache, config] = await Promise.all([
          apiGet<DashboardData>('/ui/dashboard'),
          apiGet<DiagnosticCache>('/ui/hermes/diagnostics/cache').catch(() => null),
          apiGet<ToolConfigPayload>('/ui/hermes/tools/config').catch(() => null),
        ]);
        if (!disposed) {
          setData(payload);
          setDiagnosticCache(cache);
          setToolConfig(config);
          setError('');
        }
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取工具中心失败');
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
  const selectedVisibleFields = selectedToolConfig ? visibleFieldsForTool(selectedToolConfig, configDraft) : [];
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
      event.returnValue = 'Hermes 更新仍在运行，关闭窗口会中断更新。';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
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
      setUpdateTerminalMessage(hermesUpdateTerminalExitMessage(succeeded, payload.exitCode));
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
      if (succeeded) {
        setActionStatus('Hermes 更新已结束，正在刷新工具清单和 Doctor 状态...');
        void refreshAfterHermesUpdateTerminal();
      } else {
        setActionStatus(`Hermes 更新异常结束（exit=${payload.exitCode}），请查看终端输出。`);
      }
    });
    return () => {
      const activeId = updateTerminalIdRef.current;
      offData();
      offExit();
      if (activeId) void killDesktopTerminal(activeId);
      updateTerminalRef.current?.dispose();
      updateTerminalRef.current = null;
      updateFitAddonRef.current = null;
      updateTerminalIdRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!hasEmbeddedTerminal()) return undefined;
    const onResize = () => fitHermesUpdateTerminal();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (!selectedToolId) return;
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }, [selectedToolId]);

  async function recheckHermes() {
    if (busy) return;
    setBusy(true);
    setActionStatus('正在重新检测 Hermes 工具状态...');
    try {
      const payload = await apiPost<DashboardData>('/ui/hermes/recheck');
      const cache = await apiGet<DiagnosticCache>('/ui/hermes/diagnostics/cache').catch(() => null);
      const config = await apiGet<ToolConfigPayload>('/ui/hermes/tools/config').catch(() => null);
      setData(payload);
      setDiagnosticCache(cache);
      setToolConfig(config);
      setError('');
      setActionStatus('工具状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '重新检测 Hermes 失败');
    } finally {
      setBusy(false);
    }
  }

  async function checkHermesUpdate() {
    if (updateBusy) return;
    setUpdateBusy(true);
    setUpdateMode('check');
    setUpdateStartedAt(Date.now());
    setActionStatus('正在检查 Hermes 更新...');
    try {
      const result = await apiPost<HermesUpdateResult>('/ui/hermes/update/check');
      setHermesUpdate(result);
      if (!result.ok) throw new Error(result.error || 'Hermes 更新检查失败');
      setActionStatus(result.update_available ? '发现 Hermes 更新' : 'Hermes 已是当前版本');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Hermes 更新检查失败');
    } finally {
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
    }
  }

  async function updateHermesAgent() {
    if (updateBusy) return;
    if (hasEmbeddedTerminal()) {
      await startHermesUpdateTerminal();
      return;
    }
    await updateHermesAgentViaBridge();
  }

  async function updateHermesAgentViaBridge() {
    setUpdateBusy(true);
    setUpdateMode('run');
    setUpdateStartedAt(Date.now());
    setActionStatus('正在更新 Hermes，并在完成后刷新工具清单...');
    try {
      const result = await apiPost<HermesUpdateResult>('/ui/hermes/update/run', { backup: updateWithFullBackup });
      setHermesUpdate(result);
      if (result.tool_config) setToolConfig(result.tool_config);
      if (result.diagnostic_cache) setDiagnosticCache(result.diagnostic_cache);
      if (result.dashboard) setData(result.dashboard);
      if (!result.ok) throw new Error(result.error || result.message || 'Hermes 更新失败');
      setActionStatus(result.message || 'Hermes 更新完成，工具状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Hermes 更新失败');
    } finally {
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
    }
  }

  function ensureHermesUpdateTerminal(): Terminal {
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
    fitHermesUpdateTerminal();
    return terminal;
  }

  function fitHermesUpdateTerminal() {
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

  function scrollToHermesUpdateTerminal() {
    window.requestAnimationFrame(() => {
      updateTerminalPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  async function waitForHermesUpdateTerminalHost() {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (updateTerminalHostRef.current) return;
      await new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => resolve());
      });
    }
    throw new Error('更新终端区域尚未准备好');
  }

  async function startHermesUpdateTerminal() {
    if (updateTerminalIdRef.current) {
      setActionStatus('Hermes 更新终端已经在运行，请先等待完成或停止当前任务。');
      scrollToHermesUpdateTerminal();
      return;
    }
    setUpdateBusy(true);
    setUpdateMode('run');
    setUpdateStartedAt(Date.now());
    setUpdateTerminalStatus('starting');
    setUpdateTerminalMessage('正在启动 Hermes 更新终端...');
    setActionStatus('正在打开 Hermes 更新终端...');
    scrollToHermesUpdateTerminal();
    try {
      await waitForHermesUpdateTerminalHost();
      const terminal = ensureHermesUpdateTerminal();
      scrollToHermesUpdateTerminal();
      terminal.clear();
      terminal.focus();
      terminal.write('\x1b[1;36m更新 Hermes Agent\x1b[0m\r\n');
      fitHermesUpdateTerminal();
      const task: DesktopTerminalTask = updateWithFullBackup ? 'update-hermes-backup' : 'update-hermes';
      const result = await startDesktopTerminal(task, terminal.cols || 100, terminal.rows || 28);
      if (!result.success || !result.id) throw new Error(result.error || '无法启动 Hermes 更新终端');
      updateTerminalIdRef.current = result.id;
      setUpdateTerminalSession({ id: result.id, task, title: result.title || (updateWithFullBackup ? '更新 Hermes Agent（完整备份）' : '更新 Hermes Agent') });
      setUpdateTerminalStatus('running');
      setUpdateTerminalMessage(updateWithFullBackup
        ? 'Hermes 更新正在内置终端运行；已启用完整备份，目录较大时可能需要更久。关闭或停止会中断更新。'
        : 'Hermes 更新正在内置终端运行；输出会实时显示，关闭或停止会中断更新。');
      setActionStatus('Hermes 更新终端已启动');
      fitHermesUpdateTerminal();
    } catch (err) {
      updateTerminalIdRef.current = null;
      setUpdateTerminalSession(null);
      setUpdateTerminalStatus('error');
      setUpdateTerminalMessage(err instanceof Error ? err.message : 'Hermes 更新终端启动失败');
      setUpdateBusy(false);
      setUpdateMode(null);
      setUpdateStartedAt(null);
      setActionStatus(err instanceof Error ? err.message : 'Hermes 更新终端启动失败');
    }
  }

  async function stopHermesUpdateTerminal(options: { confirm?: boolean } = {}) {
    const id = updateTerminalIdRef.current;
    if (!id) return;
    if (options.confirm !== false) {
      const ok = window.confirm('Hermes 更新仍在运行。停止终端会中断 Hermes 更新，确定要停止吗？');
      if (!ok) return;
    }
    setUpdateTerminalMessage('正在停止 Hermes 更新终端...');
    await killDesktopTerminal(id);
  }

  async function refreshAfterHermesUpdateTerminal() {
    try {
      const check = await apiPost<HermesUpdateResult>('/ui/hermes/update/check').catch(() => null);
      const doctor = await apiPost<DiagnosticResult>('/ui/hermes/diagnostic-command', { command: 'hermes doctor' }).catch(() => null);
      const [payload, cache, config] = await Promise.all([
        apiPost<DashboardData>('/ui/hermes/recheck'),
        apiGet<DiagnosticCache>('/ui/hermes/diagnostics/cache').catch(() => doctor?.diagnostic_cache || null),
        apiGet<ToolConfigPayload>('/ui/hermes/tools/config').catch(() => null),
      ]);
      if (check) setHermesUpdate(check);
      setData(payload);
      setDiagnosticCache(cache);
      setToolConfig(config);
      setError('');
      setActionStatus('Hermes 更新完成，工具清单和 Doctor 状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Hermes 更新结束，但刷新工具状态失败');
    }
  }

  function selectToolConfig(item: HermesToolCatalogItem) {
    const config = configForCatalogItem(item, toolConfigById);
    if (!config) return;
    requestNavigation({ type: 'tool', toolId: config.id });
  }

  function requestNavigation(next: PendingNavigation) {
    if (updateTerminalSession) {
      const ok = window.confirm('Hermes 更新仍在运行。离开工具中心会中断更新，确定要离开吗？');
      if (!ok) return;
      void stopHermesUpdateTerminal({ confirm: false });
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
      const result = await apiPost<ToolConfigUpdateResult>('/ui/hermes/tools/config', {
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
      const result = await apiPost<ToolConfigTestResult>('/ui/hermes/tools/config/test', { tool_id: toolId });
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
      const result = await apiPost<BrowserCdpLaunchResult>('/ui/hermes/tools/browser-cdp/launch');
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
    setActionStatus('正在打开 Hermes 原生向导...');
    try {
      const result = await apiPost<{ success?: boolean; error?: string }>('/ui/hermes/terminal-command', { command });
      if (!result.success) throw new Error(result.error || '无法打开 Hermes 原生向导');
      setActionStatus('Hermes 原生向导已打开');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '无法打开 Hermes 原生向导');
    } finally {
      setConfigBusy(false);
    }
  }

  const hermes = data?.hermes;
  const commandExists = Boolean(hermes?.command_exists);
  const doctorCache = diagnosticCache?.commands?.doctor;
  const cacheStale = Boolean(diagnosticCache?.stale);
  const doctorSummary = !cacheStale ? doctorCache?.doctor_summary : undefined;
  const rawLimitedToolNames = cacheStale
    ? []
    : doctorSummary
      ? doctorSummary.limited_tools || []
      : hermes?.limited_tools || [];
  const limitedToolNames = rawLimitedToolNames.filter((tool) => !isHiddenHermesTool(tool));
  const rawAvailableToolNames = cacheStale
    ? []
    : doctorSummary?.available_tools?.length
      ? doctorSummary.available_tools
      : hermes?.available_tools || [];
  const availableToolNames = rawAvailableToolNames.filter((tool) => !isHiddenHermesTool(tool));
  const rawLimitedToolDetails = cacheStale
    ? {}
    : doctorSummary
      ? doctorSummary.limited_tool_details || {}
      : hermes?.limited_tool_details || {};
  const limitedToolDetails = Object.fromEntries(
    Object.entries(rawLimitedToolDetails).filter(([tool]) => !isHiddenHermesTool(tool)),
  );
  const hiddenLimitedCount = rawLimitedToolNames.filter((tool) => isHiddenHermesTool(tool)).length;
  const rawIssueCount = doctorSummary?.doctor_issues_count ?? hermes?.doctor_issues_count ?? 0;
  const issueCount = cacheStale ? 0 : Math.max(0, rawIssueCount - hiddenLimitedCount);
  const doctorReferencedTools = [
    ...limitedToolNames,
    ...availableToolNames,
    ...Object.keys(limitedToolDetails),
  ];
  const visibleToolCatalog = catalogForHermesToolsets(
    HERMES_TOOL_CATALOG,
    toolConfig?.hermes_toolsets,
    doctorReferencedTools,
  );
  const selectedCatalogItem = selectedToolId
    ? visibleToolCatalog.find((item) => toolNameAliases(item).some((alias) => canonicalToolName(alias) === canonicalToolName(selectedToolId)))
    : undefined;
  const attentionItems = attentionItemsForTools(
    visibleToolCatalog,
    limitedToolNames,
    toolConfig?.hermes_toolsets || [],
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
      || (hermes?.readiness_level && hermes.readiness_level !== 'unknown')
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
            <p>{selectedToolConfig?.summary || selectedCatalogItem?.requirement || '读取 Hermes 工具配置中。'}</p>
          </div>
          <div className="topbar-actions">
            <button type="button" onClick={() => requestNavigation({ type: 'overview' })}>返回工具概览</button>
            <button type="button" onClick={() => requestNavigation({ type: 'main' })}>主控台</button>
            {selectedVisibleFields.length ? (
              <button
                type="button"
                className="primary-action"
                disabled={configBusy || !hasUnsavedChanges}
                onClick={() => void saveSelectedToolConfig()}
              >
                {configBusy ? '保存中...' : hasUnsavedChanges ? '保存配置' : '已保存'}
              </button>
            ) : null}
          </div>
        </header>

        {error ? <div className="notice danger">{error}</div> : null}
        {actionStatus ? <div className={/失败|错误|无法|未通过/.test(actionStatus) ? 'notice danger' : 'notice'}>{actionStatus}</div> : null}
        {hasUnsavedChanges ? <div className="notice warn">当前配置有未保存更改。</div> : null}

        {selectedToolConfig ? (
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
            onRunDoctor={() => void openAppView('diagnostics', { command: 'hermes doctor', return_to: 'tools' })}
          />
        ) : selectedCatalogItem?.id === 'tts' ? (
          <section className="tool-config-panel empty">
            <strong>Yachiyo 主动关怀语音在独立页面配置</strong>
            <span>
              这里的 TTS 是 Hermes Agent 的工具能力；Bubble/Live2D 主动播报请到“主动关怀语音”页配置 GPT-SoVITS、HTTP 或本地命令。
            </span>
            <div className="tool-config-actions">
              <button type="button" className="primary-action" onClick={() => navigateTo('proactive-tts')}>
                打开主动关怀语音
              </button>
              <button type="button" onClick={() => void openAppView('diagnostics', { command: 'hermes doctor', return_to: 'tools' })}>
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
          <h1>工具中心</h1>
          <p>集中查看 Hermes toolset、Doctor 受限项和 Yachiyo 后续扩展方向。</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => requestNavigation({ type: 'main' })}>主控台</button>
          <button
            type="button"
            className="primary-action"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'hermes doctor', return_to: 'tools' })}
          >
            运行 Doctor
          </button>
          <button
            type="button"
            className={busy ? 'attention-action' : undefined}
            disabled={busy}
            onClick={() => void recheckHermes()}
          >
            {busy ? '检测中...' : '重新检测'}
          </button>
        </div>
      </header>

      {error ? <div className="notice danger">{error}</div> : null}
      {actionStatus ? <div className={/失败|错误|无法|未通过/.test(actionStatus) ? 'notice danger' : 'notice'}>{actionStatus}</div> : null}

      <section className="tool-center-panel">
        <div className="section-heading-row">
          <div>
            <h2>工具概览</h2>
            <p className="section-caption">Doctor 结果会优先覆盖旧的 ready 汇总；配置变更后请重新运行 Doctor。</p>
          </div>
          <StatusPill
            active={!attentionCount && checked}
            label={checked ? `${attentionCount} 个需处理` : '待 Doctor'}
          />
        </div>

        <div className="tool-center-summary" aria-label="工具概览">
          <ToolSummaryCard label="Hermes 工具组" value={`${visibleToolCatalog.length}`} detail={toolConfig?.hermes_toolsets?.length ? '来自 hermes tools list' : '等待 Hermes 工具清单'} />
          <ToolSummaryCard
            label="Doctor 受限"
            value={cacheStale ? '需重检' : `${attentionCount}`}
            detail={doctorCache?.cached_at ? `上次检查 ${formatShortDateTime(doctorCache.cached_at)}` : checked ? `${issueCount} 项诊断提示` : '尚未完成 Doctor 分级'}
            warn={Boolean(cacheStale || attentionCount)}
          />
          <ToolSummaryCard label="配置入口" value={`${visibleConfigCount}`} detail={toolConfig?.env_path ? '已连接 Hermes 配置' : '等待 Hermes 配置路径'} muted />
        </div>

        <HermesUpdatePanel
          version={hermes?.version}
          result={hermesUpdate}
          busy={updateBusy}
          mode={updateMode}
          elapsedSeconds={updateElapsedSeconds}
          fullBackup={updateWithFullBackup}
          terminalSupported={hasEmbeddedTerminal()}
          commandExists={commandExists}
          onFullBackupChange={setUpdateWithFullBackup}
          onCheck={() => void checkHermesUpdate()}
          onUpdate={() => void updateHermesAgent()}
        />

        {(updateTerminalStatus !== 'idle' || updateTerminalSession) ? (
          <HermesUpdateTerminalPanel
            panelRef={updateTerminalPanelRef}
            hostRef={updateTerminalHostRef}
            message={updateTerminalMessage}
            session={updateTerminalSession}
            status={updateTerminalStatus}
            supported={hasEmbeddedTerminal()}
            onStop={() => stopHermesUpdateTerminal()}
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
        ) : (
          <div className="tool-empty-banner">
            <strong>{checked ? '当前没有受限工具记录' : '还没有 Doctor 结果'}</strong>
            <span>{checked ? '如果扩展能力表现异常，可以重新运行 Doctor。' : '运行 Doctor 后，这里会把受限工具整理成可读的配置清单。'}</span>
          </div>
        )}

        <div className="tool-action-row">
          <button
            type="button"
            className="primary-action"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'hermes doctor', return_to: 'tools' })}
          >
            运行 Doctor 并查看结果
          </button>
          <button
            type="button"
            disabled={!commandExists}
            onClick={() => void openAppView('diagnostics', { command: 'hermes config check', return_to: 'tools' })}
          >
            检查配置结构
          </button>
          <button type="button" disabled={busy} onClick={() => void recheckHermes()}>
            {busy ? '检测中...' : '重新检测'}
          </button>
        </div>

        <ToolCategoryList
          catalog={visibleToolCatalog}
          hermesToolsets={toolConfig?.hermes_toolsets || []}
          hermes={hermes}
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
    </main>
  );
}

function ToolCategoryList({
  catalog,
  hermesToolsets,
  hermes,
  limitedTools,
  availableTools,
  limitedToolDetails,
  cacheStale,
  checked,
  configById,
  selectedToolId,
  onSelectConfig,
}: {
  catalog: HermesToolCatalogItem[];
  hermesToolsets: HermesToolsetItem[];
  hermes?: HermesStatus;
  limitedTools: string[];
  availableTools: string[];
  limitedToolDetails: Record<string, string>;
  cacheStale: boolean;
  checked: boolean;
  configById: Map<string, ToolConfigItem>;
  selectedToolId: string;
  onSelectConfig: (item: HermesToolCatalogItem) => void;
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
              const enabledByToolsList = toolsetEnabledForItem(item, hermesToolsets);
              const status = enabledByToolsList
                ? toolStatusFor(item, hermes, limitedTools, availableTools, limitedToolDetails, checked, cacheStale)
                : {
                    kind: 'limited' as const,
                    label: '未启用',
                    detail: 'Hermes tools list 显示此工具组当前已禁用。',
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
  catalogItem?: HermesToolCatalogItem;
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
          <span>{tool.summary || catalogItem?.requirement || 'Hermes 工具配置'}</span>
        </div>
        <span className={dirty ? 'tool-config-count dirty' : 'tool-config-count'}>
          {dirty ? '未保存' : `${configuredCount}/${visibleFields.length} 已配置`}
        </span>
      </div>

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
          <strong>此工具需要 Hermes 原生授权流程</strong>
          <span>{tool.summary || '请通过 Hermes setup 完成。'}</span>
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
              打开 Hermes 向导
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

function HermesUpdatePanel({
  version,
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
  result: HermesUpdateResult | null;
  busy: boolean;
  mode: HermesUpdateMode;
  elapsedSeconds: number;
  fullBackup: boolean;
  terminalSupported: boolean;
  commandExists: boolean;
  onFullBackupChange: (value: boolean) => void;
  onCheck: () => void;
  onUpdate: () => void;
}) {
  const versionText = typeof result?.version === 'object' ? result.version.version : result?.version;
  const updateAvailable = Boolean(result?.update_available || (typeof result?.version === 'object' && result.version.update_available));
  const behind = result?.behind_commits || (typeof result?.version === 'object' ? result.version.behind_commits : 0) || 0;
  const delta = result?.toolset_delta;
  const changedCount = (delta?.added?.length || 0) + (delta?.removed?.length || 0) + (delta?.changed?.length || 0);
  const busyText = busy ? hermesUpdateBusyText(mode, elapsedSeconds) : '';
  return (
    <div className={updateAvailable ? 'hermes-update-panel attention' : 'hermes-update-panel'}>
      <div>
        <strong>Hermes 更新</strong>
        <span>
          {result
            ? updateAvailable
              ? `可更新${behind ? `，落后 ${behind} commits` : ''}`
              : '未发现更新'
            : version
              ? `当前 ${version}`
              : '可检查 Hermes 版本与工具清单变化'}
        </span>
        {versionText ? <small>{versionText}</small> : null}
        {changedCount ? (
          <small>
            工具清单变化：新增 {delta?.added?.length || 0}，移除 {delta?.removed?.length || 0}，状态变化 {delta?.changed?.length || 0}
          </small>
        ) : null}
        <small>更新通道：Hermes 官方 updater 使用当前 checkout 的 origin/main；Release tag 仅作为保守参考，Yachiyo 暂不自动切换 tag。</small>
        <label className="settings-field checkbox-field hermes-update-backup-option">
          <input
            type="checkbox"
            checked={fullBackup}
            disabled={busy}
            onChange={(event) => onFullBackupChange(event.currentTarget.checked)}
          />
          <span>
            完整备份后更新
            <small>{fullBackup ? '会运行 hermes update --gateway --yes --backup，可能在 Creating pre-update backup 停留较久。' : '默认运行 hermes update --gateway --yes --no-backup，速度更快；Hermes 仍会保留自身的轻量状态快照。'}</small>
          </span>
        </label>
        {busy ? (
          <div className="hermes-update-progress" role="status" aria-live="polite">
            <div>
              <span>{busyText}</span>
              <small>{elapsedSeconds}s</small>
            </div>
            <div className="hermes-update-progress-track" aria-hidden="true">
              <span />
            </div>
          </div>
        ) : null}
      </div>
      <div className="hermes-update-actions">
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

function hermesUpdateBusyText(mode: HermesUpdateMode, elapsedSeconds: number): string {
  if (mode === 'check') {
    return elapsedSeconds >= 15 ? '仍在检查远端版本，网络较慢时会多等一会儿。' : '正在检查 Hermes 远端版本。';
  }
  if (elapsedSeconds >= 90) {
    return '仍在更新 Hermes；可能正在下载依赖或刷新工具清单。';
  }
  if (elapsedSeconds >= 30) {
    return 'Hermes 更新仍在运行，完成后会自动刷新 Doctor 与工具清单。';
  }
  if (elapsedSeconds >= 10) {
    return '正在执行 Hermes gateway 更新流程，请保持窗口打开。';
  }
  return '正在启动 Hermes 更新，请查看更新终端输出。';
}

function HermesUpdateTerminalPanel({
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
          <h2>Hermes 更新终端</h2>
          <p className="section-caption">{session?.title || '实时查看 Hermes update 输出'}</p>
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
            {supported ? '点击“打开更新终端”后，这里会显示 Hermes 的实时输出。' : '当前环境不支持内置终端，将使用普通更新请求。'}
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

function hermesUpdateTerminalExitMessage(succeeded: boolean, exitCode: number): string {
  if (succeeded) return 'Hermes 更新命令已结束，正在刷新工具清单和 Doctor 状态。';
  return `Hermes 更新终端异常结束，退出码 ${exitCode}。输出仍保留在这里，便于排查。`;
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function toolCategoryGroups(items: HermesToolCatalogItem[]): Array<[string, HermesToolCatalogItem[]]> {
  const groups = new Map<string, HermesToolCatalogItem[]>();
  for (const item of items) {
    const entries = groups.get(item.category) || [];
    entries.push(item);
    groups.set(item.category, entries);
  }
  return Array.from(groups.entries());
}

function catalogForHermesToolsets(
  catalog: HermesToolCatalogItem[],
  toolsets?: HermesToolsetItem[],
  doctorReferencedTools?: string[],
): HermesToolCatalogItem[] {
  const baseCatalog = catalog.filter((item) => !item.planned && !isHiddenHermesTool(item.id));
  if (!toolsets?.length && !doctorReferencedTools?.length) return baseCatalog;
  const supported = new Set(
    (toolsets || [])
      .filter((item) => !isHiddenHermesTool(item.canonical_id || item.id))
      .map((item) => canonicalToolName(item.canonical_id || item.id)),
  );
  const referenced = new Set((doctorReferencedTools || []).filter((tool) => !isHiddenHermesTool(tool)).map(canonicalToolName));
  return baseCatalog.filter((item) => {
    const aliases = toolNameAliases(item).map(canonicalToolName);
    if (item.id === 'browser-cdp') {
      return supported.has('browser') || supported.has('browser-cdp') || referenced.has('browser-cdp');
    }
    return aliases.some((alias) => supported.has(alias) || referenced.has(alias));
  });
}

function toolsetEnabledForItem(item: HermesToolCatalogItem, toolsets?: HermesToolsetItem[]): boolean {
  if (!toolsets?.length) return true;
  const records = new Map(toolsets.map((toolset) => [canonicalToolName(toolset.canonical_id || toolset.id), toolset]));
  if (item.id === 'browser-cdp') return records.get('browser')?.enabled !== false;
  const match = toolNameAliases(item)
    .map((alias) => records.get(canonicalToolName(alias)))
    .find(Boolean);
  return match?.enabled !== false;
}

function toolStatusFor(
  item: HermesToolCatalogItem,
  hermes: HermesStatus | undefined,
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
  if (cacheStale || !hermes?.command_exists || !checked) {
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
  if (!availableTools.length && hermes.ready && hermes.readiness_level && hermes.readiness_level !== 'unknown') {
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

function isToolLimited(item: HermesToolCatalogItem, limitedTools?: string[]): boolean {
  const limited = new Set((limitedTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => limited.has(canonicalToolName(alias)));
}

function isToolAvailable(item: HermesToolCatalogItem, availableTools?: string[]): boolean {
  const available = new Set((availableTools || []).map(canonicalToolName));
  return toolNameAliases(item).some((alias) => available.has(canonicalToolName(alias)));
}

function attentionItemsForTools(
  catalog: HermesToolCatalogItem[],
  limitedTools: string[],
  hermesToolsets: HermesToolsetItem[],
  limitedToolDetails: Record<string, string>,
): ToolAttentionItem[] {
  const items: ToolAttentionItem[] = [];
  const seen = new Set<string>();

  for (const item of catalog) {
    const aliases = toolNameAliases(item).map(canonicalToolName);
    const disabled = !toolsetEnabledForItem(item, hermesToolsets);
    const limited = isToolLimited(item, limitedTools);
    if (!disabled && !limited) continue;

    aliases.forEach((alias) => seen.add(alias));
    items.push({
      id: canonicalToolName(item.id),
      label: item.label,
      reason: disabled ? 'disabled' : 'limited',
      detail: disabled
        ? 'Hermes tools list 显示此工具组当前已禁用。'
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

function isHiddenHermesTool(tool: string | undefined): boolean {
  return Boolean(tool && HIDDEN_HERMES_TOOLS.has(canonicalToolName(tool)));
}

function limitedDetailFor(item: HermesToolCatalogItem, details: Record<string, string>): string {
  const aliases = new Set(toolNameAliases(item).map(canonicalToolName));
  const match = Object.entries(details || {}).find(([key]) => aliases.has(canonicalToolName(key)));
  return match?.[1] || '';
}

function configForCatalogItem(item: HermesToolCatalogItem, configById: Map<string, ToolConfigItem>): ToolConfigItem | undefined {
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

function toolNameAliases(item: HermesToolCatalogItem): string[] {
  return [item.id, ...(item.aliases || [])];
}

function canonicalToolName(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, '-');
}
