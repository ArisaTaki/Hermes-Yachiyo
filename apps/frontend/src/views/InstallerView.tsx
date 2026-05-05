import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
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
  openDesktopMode,
  resizeDesktopTerminal,
  startDesktopTerminal,
  writeDesktopTerminal,
  type DesktopTerminalTask,
} from '../lib/bridge';

type InstallInfo = {
  status?: string;
  platform?: string;
  command_exists?: boolean;
  hermes_home?: string | null;
  error_message?: string | null;
  suggestions?: string[];
  checked_at?: string;
  version_info?: { version?: string | null };
  readiness_level?: string;
  limited_tools?: string[];
  doctor_issues_count?: number;
};

type InstallInfoPayload = {
  hermes_ready?: boolean;
  install_info?: InstallInfo | null;
  install_guidance?: { actions?: string[]; can_initialize?: boolean; [key: string]: unknown } | null;
};

type InstallProgress = {
  running?: boolean;
  lines?: string[];
  line_count?: number;
  truncated?: boolean;
  omitted_count?: number;
  success?: boolean | null;
  message?: string;
  setup_triggered?: boolean;
  started_at?: number | null;
  finished_at?: number | null;
  last_line_at?: number | null;
};

type RecheckResult = {
  status?: string;
  message?: string;
  ready?: boolean;
  needs_init?: boolean;
  needs_env_refresh?: boolean;
};

type WorkspaceInitResult = {
  success?: boolean;
  error?: string | null;
  created_items?: string[];
};

type BackupInfo = {
  display_path?: string;
  path?: string;
  created_at?: string;
  size_display?: string;
};

type InstallerBackupStatus = {
  success?: boolean;
  ok?: boolean;
  error?: string;
  has_backup?: boolean;
  latest?: BackupInfo | null;
  backup_root_display?: string;
};

type BackupImportResult = {
  ok?: boolean;
  errors?: string[];
  restored?: string[];
};

type SetupTerminalResult = {
  success?: boolean;
  error?: string | null;
  already_running?: boolean;
};

type HermesConnectionValidation = {
  verified?: boolean;
  success?: boolean;
  provider?: string;
  model?: string;
  base_url?: string;
  api_key_name?: string;
  message?: string;
  error?: string;
  reason?: string;
  tested_at?: string;
  verified_at?: string;
  last_tested_at?: string;
  elapsed_seconds?: number;
};

type HermesConnectionTestResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  output_preview?: string;
  stderr_preview?: string;
  elapsed_seconds?: number;
  returncode?: number;
  command?: string;
  connection_validation?: HermesConnectionValidation;
};

type HermesVisualConfig = {
  ok?: boolean;
  error?: string;
  command_exists?: boolean;
  needs_env_refresh?: boolean;
  config_path?: string;
  env_path?: string;
  model?: {
    provider?: string;
    default?: string;
    base_url?: string;
  };
  provider_options?: HermesProviderOption[];
  api_key?: {
    name?: string;
    configured?: boolean;
    display?: string;
  };
  connection_validation?: HermesConnectionValidation;
};

type HermesProviderOption = {
  id: string;
  label?: string;
  base_url?: string;
  default_model?: string;
  models?: string[];
  api_key_name?: string;
  api_key_names?: string[];
  api_key_configured?: boolean;
  auth_type?: string;
  source?: string;
  is_current?: boolean;
};

type HermesConfigForm = {
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
};

type HermesProviderDraft = Pick<HermesConfigForm, 'model' | 'base_url'>;

type EmbeddedTerminalStatus = 'idle' | 'starting' | 'running' | 'exited' | 'error';
type EmbeddedTerminalSession = {
  id: string;
  task: DesktopTerminalTask;
  title: string;
};

const INSTALL_POLL_MS = 600;
const SETUP_POLL_MS = 3000;
const INSTALL_STALL_WARNING_MS = 60_000;
const MACOS_PREREQUISITE_COMMAND = [
  'echo "Hermes-Yachiyo macOS 基础工具检查"',
  'if ! xcode-select -p >/dev/null 2>&1; then echo "将打开 Xcode Command Line Tools 安装器"; xcode-select --install || true; else echo "Xcode Command Line Tools 已安装"; fi',
  'if ! command -v brew >/dev/null 2>&1; then echo "正在安装 Homebrew"; /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; fi',
  'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
  'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
  'if command -v brew >/dev/null 2>&1; then brew update && brew install git curl; else echo "未检测到 brew，请根据终端提示完成 Homebrew 安装后重新运行"; fi',
  'echo "基础工具准备完成。请回到 Hermes-Yachiyo 点击重新检测或安装 Hermes Agent。"',
].join('; ');

export function InstallerView() {
  const [payload, setPayload] = useState<InstallInfoPayload | null>(null);
  const [backupStatus, setBackupStatus] = useState<InstallerBackupStatus | null>(null);
  const [installProgress, setInstallProgress] = useState<InstallProgress | null>(null);
  const [setupRunning, setSetupRunning] = useState(false);
  const [setupAttention, setSetupAttention] = useState(false);
  const [status, setStatus] = useState('正在检测 Hermes Agent…');
  const [logLines, setLogLines] = useState<string[]>([]);
  const [busy, setBusy] = useState('');
  const [configStatus, setConfigStatus] = useState('');
  const [hermesConfig, setHermesConfig] = useState<HermesVisualConfig | null>(null);
  const [configForm, setConfigForm] = useState<HermesConfigForm>(emptyHermesConfigForm());
  const [hermesTestResult, setHermesTestResult] = useState<HermesConnectionTestResult | null>(null);
  const [terminalStatus, setTerminalStatus] = useState<EmbeddedTerminalStatus>('idle');
  const [terminalMessage, setTerminalMessage] = useState('等待启动终端任务');
  const [terminalSession, setTerminalSession] = useState<EmbeddedTerminalSession | null>(null);
  const configFormDirtyRef = useRef(false);
  const hermesConfigLoadingRef = useRef(false);
  const providerDraftsRef = useRef<Record<string, HermesProviderDraft>>({});
  const setupTerminalOpenedRef = useRef(false);
  const lastInstallLineCountRef = useRef(0);
  const lastInstallLogAtRef = useRef(0);
  const terminalPanelRef = useRef<HTMLElement | null>(null);
  const terminalHostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const terminalIdRef = useRef<string | null>(null);
  const terminalTaskRef = useRef<DesktopTerminalTask | null>(null);
  const actionsPanelRef = useRef<HTMLElement | null>(null);
  const configPanelRef = useRef<HTMLElement | null>(null);

  const loadHermesConfig = useCallback(async (options: { forceFormSync?: boolean } = {}) => {
    if (hermesConfigLoadingRef.current) return null;
    hermesConfigLoadingRef.current = true;
    try {
      const result = await apiGet<HermesVisualConfig>('/ui/hermes/config');
      setHermesConfig(result);
      if (options.forceFormSync || !configFormDirtyRef.current) {
        syncProviderDraftFromConfig(result);
        setConfigForm(formFromHermesConfig(result));
      }
      return result;
    } catch (error) {
      setConfigStatus(error instanceof Error ? error.message : '读取 Hermes 配置失败');
      return null;
    } finally {
      hermesConfigLoadingRef.current = false;
    }
  }, []);

  const loadInstallInfo = useCallback(async () => {
    const data = await apiGet<InstallInfoPayload>('/hermes/install-info');
    setPayload(data);
    setStatus(statusText(data.install_info?.status, data.hermes_ready));
    return data;
  }, []);

  const loadBackupStatus = useCallback(async () => {
    try {
      const data = await apiGet<InstallerBackupStatus>('/ui/installer/backup/status');
      setBackupStatus(data);
    } catch (error) {
      setBackupStatus({ success: false, error: error instanceof Error ? error.message : '读取备份状态失败' });
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    async function load() {
      try {
        const data = await loadInstallInfo();
        if (!disposed && data.install_info?.status === 'installed_not_initialized') void loadBackupStatus();
        if (!disposed && data.install_info?.command_exists) void loadHermesConfig({ forceFormSync: true });
        const progress = await apiGet<InstallProgress>('/ui/installer/install/progress');
        if (!disposed) applyInstallProgress(progress, true);
      } catch (error) {
        if (!disposed) setStatus(error instanceof Error ? error.message : '检测失败');
      }
    }
    void load();
    return () => {
      disposed = true;
    };
  }, [loadBackupStatus, loadHermesConfig, loadInstallInfo]);

  useEffect(() => {
    if (!installProgress?.running) return undefined;
    const timer = window.setInterval(() => void refreshInstallProgress(), INSTALL_POLL_MS);
    return () => window.clearInterval(timer);
  }, [installProgress?.running]);

  useEffect(() => {
    const statusValue = payload?.install_info?.status;
    if (statusValue !== 'setup_in_progress' && !setupRunning) return undefined;
    const timer = window.setInterval(() => void refreshSetupProcess(), SETUP_POLL_MS);
    return () => window.clearInterval(timer);
  }, [payload?.install_info?.status, setupRunning]);

  useEffect(() => {
    if (!hasEmbeddedTerminal()) return undefined;
    const offData = onDesktopTerminalData((payload) => {
      if (payload.id !== terminalIdRef.current) return;
      terminalRef.current?.write(payload.data);
    });
    const offExit = onDesktopTerminalExit((payload) => {
      if (payload.id !== terminalIdRef.current) return;
      const task = terminalTaskRef.current || payload.task || 'install-hermes';
      const succeeded = payload.exitCode === 0;
      terminalIdRef.current = null;
      terminalTaskRef.current = null;
      setTerminalSession(null);
      setTerminalStatus(succeeded ? 'exited' : 'error');
      setTerminalMessage(terminalExitMessage(task, succeeded, payload.exitCode));
      setBusy('');
      if (task === 'hermes-setup') {
        setSetupRunning(false);
        setSetupAttention(!succeeded);
        if (succeeded) {
          setStatus('Hermes setup 已结束，正在重新检测配置状态…');
          window.setTimeout(() => void recheckStatus(), 100);
          return;
        }
      }
      if (task === 'install-hermes') {
        setInstallProgress({ running: false, success: succeeded, message: terminalExitMessage(task, succeeded, payload.exitCode) });
        setSetupAttention(!succeeded);
        if (succeeded) {
          setStatus('安装完成，正在重新检测…');
          window.setTimeout(() => void recheckStatus({ afterInstall: true }), 100);
          return;
        }
      }
      setStatus(terminalExitStatus(task, succeeded, payload.exitCode));
    });
    return () => {
      const activeId = terminalIdRef.current;
      offData();
      offExit();
      if (activeId) void killDesktopTerminal(activeId);
      terminalRef.current?.dispose();
      terminalRef.current = null;
      fitAddonRef.current = null;
      terminalIdRef.current = null;
      terminalTaskRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!hasEmbeddedTerminal()) return undefined;
    const onResize = () => fitEmbeddedTerminal();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  function applyInstallProgress(progress: InstallProgress, fromInitialLoad: boolean) {
    setInstallProgress(progress);
    const lines = progress.lines || [];
    if (lines.length) setLogLines(lines);
    const lineCount = progress.line_count ?? lines.length;
    if (lineCount !== lastInstallLineCountRef.current) {
      lastInstallLineCountRef.current = lineCount;
      lastInstallLogAtRef.current = Date.now();
    }
    if (progress.running) {
      setBusy('install');
      if (fromInitialLoad) setStatus('安装仍在进行中，请等待日志更新');
      return;
    }
    if (fromInitialLoad && progress.success === false) {
      setBusy('');
      setStatus(`上次安装失败：${progress.message || '请查看安装日志后重试'}`);
    }
  }

  function ensureEmbeddedTerminal(): Terminal {
    if (terminalRef.current) return terminalRef.current;
    const host = terminalHostRef.current;
    if (!host) throw new Error('终端区域尚未准备好');
    const terminal = new Terminal({
      allowProposedApi: true,
      convertEol: true,
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 12,
      lineHeight: 1.35,
      scrollback: 8000,
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
      const id = terminalIdRef.current;
      if (id) void writeDesktopTerminal(id, data);
    });
    terminalRef.current = terminal;
    fitAddonRef.current = fitAddon;
    fitEmbeddedTerminal();
    return terminal;
  }

  function fitEmbeddedTerminal() {
    const terminal = terminalRef.current;
    const fitAddon = fitAddonRef.current;
    if (!terminal || !fitAddon) return;
    window.requestAnimationFrame(() => {
      try {
        fitAddon.fit();
        const id = terminalIdRef.current;
        if (id) void resizeDesktopTerminal(id, terminal.cols, terminal.rows);
      } catch {}
    });
  }

  function scrollToEmbeddedTerminal() {
    window.requestAnimationFrame(() => {
      terminalPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function scrollToHermesConfig() {
    window.requestAnimationFrame(() => {
      configPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function scrollToInstallerActions() {
    window.requestAnimationFrame(() => {
      actionsPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  async function enterMainWithBubble() {
    await openAppView('main');
    window.setTimeout(() => {
      void openDesktopMode('bubble');
    }, 250);
  }

  async function startEmbeddedTerminal(task: DesktopTerminalTask) {
    scrollToEmbeddedTerminal();
    if (!hasEmbeddedTerminal()) {
      if (task === 'mac-prerequisites') {
        await prepareMacPrerequisites();
      } else if (task === 'hermes-setup') {
        await openSetupTerminal(false);
      } else {
        await startInstall();
      }
      return;
    }
    if (terminalIdRef.current) {
      setStatus('已有内置终端任务正在运行，请先完成或停止当前任务');
      setTerminalMessage('已有任务正在运行');
      return;
    }
    const terminal = ensureEmbeddedTerminal();
    terminal.clear();
    terminal.focus();
    fitEmbeddedTerminal();
    setBusy(terminalBusyValue(task));
    setTerminalStatus('starting');
    setTerminalMessage(`正在启动：${terminalTaskLabel(task)}`);
    setSetupAttention(false);
    if (task === 'install-hermes') {
      setInstallProgress(null);
      setLogLines([]);
      setupTerminalOpenedRef.current = false;
    }
    terminal.write(`\x1b[1;36m${terminalTaskLabel(task)}\x1b[0m\r\n`);
    try {
      const result = await startDesktopTerminal(task, terminal.cols || 100, terminal.rows || 28);
      if (!result.success || !result.id) throw new Error(result.error || '无法启动内置终端任务');
      terminalIdRef.current = result.id;
      terminalTaskRef.current = task;
      setTerminalSession({ id: result.id, task, title: result.title || terminalTaskLabel(task) });
      setTerminalStatus('running');
      setTerminalMessage('终端已连接，安装脚本输出会实时显示；需要输入时可以直接在这里输入');
      if (task === 'hermes-setup') {
        setSetupRunning(true);
        setSetupAttention(true);
      }
      setStatus(`${terminalTaskLabel(task)}正在内置终端运行`);
      fitEmbeddedTerminal();
    } catch (error) {
      setBusy('');
      setTerminalStatus('error');
      const message = error instanceof Error ? error.message : '内置终端启动失败';
      setTerminalMessage(message);
      setStatus(message);
    }
  }

  async function stopEmbeddedTerminal() {
    const id = terminalIdRef.current;
    if (!id) return;
    setTerminalMessage('正在停止终端任务…');
    await killDesktopTerminal(id);
  }

  async function startInstall() {
    setBusy('install');
    setStatus('正在启动 Hermes Agent 安装…');
    setLogLines([]);
    lastInstallLineCountRef.current = 0;
    lastInstallLogAtRef.current = Date.now();
    setupTerminalOpenedRef.current = false;
    setSetupAttention(false);
    try {
      const result = await apiPost<{ started?: boolean; error?: string }>('/ui/installer/install');
      if (!result.started) throw new Error(result.error || '无法启动安装');
      setInstallProgress({ running: true, lines: [], success: null });
      setStatus('安装中，请等待日志更新');
      await refreshInstallProgress();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '启动安装失败');
      setBusy('');
    }
  }

  async function refreshInstallProgress() {
    let progress: InstallProgress;
    try {
      progress = await apiGet<InstallProgress>('/ui/installer/install/progress');
    } catch (error) {
      const message = error instanceof Error ? error.message : '读取安装进度失败';
      setInstallProgress((previous) => ({ ...(previous || {}), running: false, success: false, message }));
      setStatus(message);
      setBusy('');
      return;
    }

    applyInstallProgress(progress, false);

    if (progress.setup_triggered && !setupTerminalOpenedRef.current) {
      setupTerminalOpenedRef.current = true;
      await openSetupTerminal(true);
    }

    if (progress.running) {
      const lastUpdate = lastInstallLogAtRef.current || Date.now();
      if (Date.now() - lastUpdate > INSTALL_STALL_WARNING_MS) {
        setStatus('安装仍在运行，但最近没有新的日志；如果终端或网络已停止，可重新检测后重试');
      }
      return;
    }
    setBusy('');
    if (progress.setup_triggered) {
      setStatus('Hermes 安装已进入初次配置，请在终端完成 setup 后重新检测');
      setSetupAttention(true);
      return;
    }
    if (progress.success) {
      setStatus('安装完成，正在重新检测…');
      await recheckStatus({ afterInstall: true });
      return;
    }
    if (progress.success === false) {
      setStatus(`安装失败：${progress.message || '未知错误'}`);
    }
  }

  async function openSetupTerminal(fromInstaller = false) {
    setBusy('setup');
    setStatus(fromInstaller ? '正在打开 Hermes setup 终端…' : '正在打开配置终端…');
    try {
      const result = await apiPost<SetupTerminalResult>('/ui/installer/hermes/setup-terminal');
      if (!result.success) throw new Error(result.error || '无法打开终端');
      setSetupRunning(true);
      setSetupAttention(true);
      setStatus(result.already_running ? '配置终端已在运行，请完成后重新检测' : '终端已打开，请完成 Hermes setup 后重新检测');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '打开配置终端失败');
    } finally {
      setBusy('');
    }
  }

  async function prepareMacPrerequisites() {
    setBusy('prep');
    setStatus('正在打开 macOS 基础工具准备终端…');
    try {
      const result = await apiPost<{ success?: boolean; error?: string }>('/ui/hermes/terminal-command', { command: MACOS_PREREQUISITE_COMMAND });
      if (!result.success) throw new Error(result.error || '无法打开终端');
      setStatus('已打开基础工具准备终端；完成后回到这里点击重新检测或安装 Hermes Agent');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '打开基础工具终端失败');
    } finally {
      setBusy('');
    }
  }

  async function refreshSetupProcess() {
    try {
      const result = await apiGet<{ running?: boolean }>('/ui/installer/hermes/setup-process');
      setSetupRunning(Boolean(result.running));
      if (!result.running && setupRunning) {
        setSetupAttention(true);
        setStatus('配置终端已关闭；如果已完成 setup，请重新检测');
      }
    } catch {}
  }

  function rememberProviderDraft(provider: string, draft: HermesConfigForm) {
    const key = provider.trim();
    if (!key) return;
    providerDraftsRef.current[key] = {
      model: draft.model,
      base_url: draft.base_url,
    };
  }

  function syncProviderDraftFromConfig(config: HermesVisualConfig | null) {
    const form = formFromHermesConfig(config);
    if (!form.provider) return;
    rememberProviderDraft(form.provider, form);
  }

  function formForProvider(provider: string, current: HermesConfigForm): HermesConfigForm {
    const option = providerOptionById(hermesConfig, provider);
    const cached = providerDraftsRef.current[provider.trim()];
    const saved = hermesConfig?.model?.provider === provider ? hermesConfig.model : null;
    return {
      ...current,
      provider,
      model: cached?.model || saved?.default || option?.default_model || option?.models?.[0] || '',
      base_url: cached?.base_url ?? saved?.base_url ?? option?.base_url ?? current.base_url,
      api_key: '',
    };
  }

  function updateHermesConfigField(field: keyof HermesConfigForm, value: string) {
    configFormDirtyRef.current = true;
    if (field === 'provider') {
      setConfigForm((current) => {
        rememberProviderDraft(current.provider, current);
        return formForProvider(value, current);
      });
    } else {
      setConfigForm((current) => {
        const next = { ...current, [field]: value };
        if (field === 'model' || field === 'base_url') rememberProviderDraft(next.provider, next);
        return next;
      });
    }
    if (configStatus && /不能为空|配置已保存|连接测试/.test(configStatus)) setConfigStatus('');
  }

  async function refreshAfterHermesConfig() {
    const result = await apiPost<RecheckResult>('/ui/installer/status/recheck');
    const latest = await loadInstallInfo();
    if (result.needs_init || latest.install_info?.status === 'installed_not_initialized') {
      await loadBackupStatus();
    }
    await loadHermesConfig();
    if (result.ready) {
      setSetupAttention(false);
      setStatus(`Hermes 已就绪${envRefreshNote(result)}`);
      window.setTimeout(() => void enterMainWithBubble(), 600);
    } else if (result.needs_init || latest.install_info?.status === 'installed_not_initialized') {
      setSetupAttention(false);
      setStatus(`Hermes 配置已保存，下一步初始化 Yachiyo 工作空间${envRefreshNote(result)}`);
      scrollToInstallerActions();
    } else if (result.status === 'installed_needs_setup' || result.status === 'setup_in_progress') {
      setSetupAttention(false);
      setStatus('Hermes 配置已保存；如仍未通过检测，可使用高级终端 setup 补充配置');
      scrollToHermesConfig();
    } else if (result.message) {
      setStatus(`检测结果：${result.status}（${result.message}）`);
    }
  }

  function applySavedHermesConfig(config: HermesVisualConfig | undefined) {
    configFormDirtyRef.current = false;
    if (!config) return;
    syncProviderDraftFromConfig(config);
    setHermesConfig(config);
    setConfigForm(formFromHermesConfig(config));
  }

  async function saveHermesConfig(testAfterSave = false) {
    if (busy) {
      setConfigStatus('上一个操作正在处理，请稍候');
      return;
    }
    if (!configForm.provider.trim()) {
      setConfigStatus('Provider 不能为空');
      return;
    }
    if (!configForm.model.trim()) {
      setConfigStatus('模型名称不能为空');
      return;
    }
    setBusy(testAfterSave ? 'config-test' : 'config');
    setHermesTestResult(null);
    setConfigStatus(testAfterSave ? '正在保存配置并测试模型连接…' : '正在保存 Hermes 配置…');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; message?: string; configuration?: HermesVisualConfig }>('/ui/hermes/config', configForm);
      if (result.ok === false) throw new Error(result.error || '保存 Hermes 配置失败');
      applySavedHermesConfig(result.configuration);
      setConfigStatus(result.message || 'Hermes 配置已保存');
      if (testAfterSave) {
        const testResult = await apiPost<HermesConnectionTestResult>('/ui/hermes/connection-test');
        setHermesTestResult(testResult);
        if (testResult.connection_validation) {
          setHermesConfig((current) => (
            current ? { ...current, connection_validation: testResult.connection_validation } : current
          ));
        }
        setConfigStatus(testResult.success ? testResult.message || 'Hermes 连接测试通过' : testResult.error || 'Hermes 连接测试失败');
      }
      await refreshAfterHermesConfig();
    } catch (error) {
      setConfigStatus(error instanceof Error ? error.message : '保存 Hermes 配置失败');
    } finally {
      setBusy('');
    }
  }

  async function recheckStatus(options: { afterInstall?: boolean } = {}) {
    setBusy('recheck');
    setStatus('正在重新检测 Hermes 状态…');
    try {
      const result = await apiPost<RecheckResult>('/ui/installer/status/recheck');
      const latest = await loadInstallInfo();
      if (latest.install_info?.command_exists) await loadHermesConfig();
      const needsInitialization = Boolean(result.needs_init || latest.install_info?.status === 'installed_not_initialized');
      if (result.ready) {
        setSetupAttention(false);
        setStatus(`Hermes 已就绪${envRefreshNote(result)}`);
        window.setTimeout(() => void enterMainWithBubble(), 600);
      } else if (needsInitialization) {
        setSetupAttention(false);
        if (options.afterInstall) {
          setStatus(`Hermes Agent 已安装，下一步配置模型 Provider 与 API Key${envRefreshNote(result)}`);
          scrollToHermesConfig();
        } else {
          setStatus(`Hermes 配置完成，进入工作空间初始化${envRefreshNote(result)}`);
          await loadBackupStatus();
          scrollToInstallerActions();
        }
      } else if (result.status === 'installed_needs_setup' || result.status === 'setup_in_progress') {
        setSetupAttention(false);
        setStatus('Hermes 尚未完成配置，请在下方模型配置向导填写并保存');
        scrollToHermesConfig();
      } else {
        setStatus(result.message ? `检测结果：${result.status}（${result.message}）` : `检测结果：${result.status || 'unknown'}`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '重新检测失败');
    } finally {
      setBusy('');
    }
  }

  function shouldWarnBeforeWorkspaceInit(): boolean {
    const provider = configForm.provider.trim() || hermesConfig?.model?.provider || '';
    const model = configForm.model.trim() || hermesConfig?.model?.default || '';
    const option = providerOptionById(hermesConfig, provider);
    const apiKeyName = option?.api_key_name || hermesConfig?.api_key?.name || '';
    const apiKeyConfigured = option?.api_key_configured ?? hermesConfig?.api_key?.configured;
    return !provider || !model || (Boolean(apiKeyName) && !apiKeyConfigured && !configForm.api_key.trim());
  }

  async function initializeWorkspace() {
    if (shouldWarnBeforeWorkspaceInit() && !window.confirm('当前 Hermes 模型/API Key 尚未完整配置。直接初始化工作空间可能导致首次对话不可用；之后仍可在主控台补充配置。仍要继续吗？')) {
      setStatus('已取消初始化；请先在模型配置向导补全 Provider、模型和 API Key');
      scrollToHermesConfig();
      return;
    }
    setBusy('init');
    setLogLines(['开始初始化 Yachiyo 工作空间…']);
    setStatus('正在初始化工作空间…');
    try {
      const result = await apiPost<WorkspaceInitResult>('/ui/installer/workspace/initialize');
      if (!result.success) throw new Error(result.error || '初始化失败');
      setLogLines(['开始初始化 Yachiyo 工作空间…', ...(result.created_items || []).map((item) => `已创建：${item}`), '工作空间初始化完成']);
      setStatus('初始化完成，正在重新检测…');
      await recheckStatus();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '初始化失败');
    } finally {
      setBusy('');
    }
  }

  async function importBackup() {
    setBusy('backup');
    setStatus('正在导入最近备份…');
    try {
      const result = await apiPost<BackupImportResult>('/ui/installer/backup/import');
      if (!result.ok) throw new Error(result.errors?.join('；') || '导入失败');
      setStatus(`已导入 ${result.restored?.length || 0} 项备份资料，正在重新检测…`);
      await recheckStatus();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '导入备份失败');
    } finally {
      setBusy('');
    }
  }

  const installInfo = payload?.install_info || null;
  const statusValue = installInfo?.status || 'not_checked';
  const title = installerTitle(statusValue);
  const ready = Boolean(payload?.hermes_ready || statusValue === 'ready');
  const isMacOS = isMacOSPlatform(installInfo?.platform);
  const showVisualConfig = Boolean(
    installInfo?.command_exists
    && !ready
    && ['installed_needs_setup', 'setup_in_progress', 'installed_not_initialized'].includes(statusValue),
  );

  return (
    <main className="app-shell installer-shell">
      <header className="topbar">
        <div>
          <h1>{title}</h1>
          <p>{installerSubtitle(statusValue, installInfo)}</p>
        </div>
        {ready ? <button type="button" onClick={() => void enterMainWithBubble()}>进入主控台</button> : null}
      </header>

      <InstallerProgressBanner
        busy={busy}
        installProgress={installProgress}
        setupAttention={setupAttention}
        setupRunning={setupRunning || statusValue === 'setup_in_progress'}
        status={status}
        statusValue={statusValue}
      />

      <section className="settings-grid expanded-settings-grid">
        <article className="panel setting-card">
          <span>安装状态</span>
          <strong>{installStatusLabel(statusValue)}</strong>
          <small>{installInfo?.platform || '—'}</small>
        </article>
        <article className="panel setting-card">
          <span>Hermes 命令</span>
          <strong>{installInfo?.command_exists ? '已检测到' : '未检测到'}</strong>
          <small>{installInfo?.version_info?.version || '—'}</small>
        </article>
        <article className="panel setting-card">
          <span>Hermes Home</span>
          <strong>{installInfo?.hermes_home || '—'}</strong>
          <small>{formatDateTime(installInfo?.checked_at)}</small>
        </article>
      </section>

      {installInfo?.error_message ? <div className="notice danger">{installInfo.error_message}</div> : null}

      <section className="settings-detail-grid">
        <article className="panel settings-section">
          <div className="section-heading-row">
            <h2>引导步骤</h2>
            <span>{installStatusLabel(statusValue)}</span>
          </div>
          <GuidanceList actions={payload?.install_guidance?.actions || []} suggestions={installInfo?.suggestions || []} />
        </article>

        <article className="panel settings-section" ref={actionsPanelRef}>
          <div className="section-heading-row">
            <h2>操作</h2>
            <span className={`process-badge ${busy ? 'active' : setupAttention ? 'attention' : ''}`}>
              {operationLabel(busy, setupAttention)}
            </span>
          </div>
          <InstallerActions
            backupStatus={backupStatus}
            busy={busy}
            canInitialize={Boolean(payload?.install_guidance?.can_initialize)}
            installRunning={Boolean(installProgress?.running || terminalSession?.task === 'install-hermes')}
            isMacOS={isMacOS}
            ready={ready}
            recheckAttention={setupAttention || installProgress?.success === false}
            setupRunning={setupRunning || statusValue === 'setup_in_progress'}
            statusValue={statusValue}
            onImportBackup={importBackup}
            onInitializeWorkspace={initializeWorkspace}
            onOpenSetupTerminal={() => startEmbeddedTerminal('hermes-setup')}
            onPrepareMacTools={() => startEmbeddedTerminal('mac-prerequisites')}
            onRecheck={recheckStatus}
            onRefreshBackup={loadBackupStatus}
            onStartInstall={() => startEmbeddedTerminal('install-hermes')}
            onEnterMain={enterMainWithBubble}
          />
        </article>
      </section>

      {showVisualConfig ? (
        <InstallerHermesConfigPanel
          busy={busy}
          config={hermesConfig}
          panelRef={configPanelRef}
          form={configForm}
          status={configStatus}
          testResult={hermesTestResult}
          onConfigChange={updateHermesConfigField}
          onOpenAdvancedSetup={() => startEmbeddedTerminal('hermes-setup')}
          onSaveAndTest={() => saveHermesConfig(true)}
        />
      ) : null}

      {!ready ? (
        <EmbeddedTerminalPanel
          panelRef={terminalPanelRef}
          hostRef={terminalHostRef}
          message={terminalMessage}
          session={terminalSession}
          status={terminalStatus}
          supported={hasEmbeddedTerminal()}
          onStop={stopEmbeddedTerminal}
        />
      ) : null}

      {backupStatus ? <BackupImportPanel status={backupStatus} /> : null}
      {logLines.length || installProgress?.running ? <InstallLog lines={logLines} progress={installProgress} /> : null}
    </main>
  );
}

function InstallerProgressBanner({
  busy,
  installProgress,
  setupAttention,
  setupRunning,
  status,
  statusValue,
}: {
  busy: string;
  installProgress: InstallProgress | null;
  setupAttention: boolean;
  setupRunning: boolean;
  status: string;
  statusValue: string;
}) {
  const tone = installerBannerTone(status, statusValue, installProgress, setupAttention);
  const title = installerBannerTitle(busy, statusValue, installProgress, setupRunning, setupAttention);
  const detail = installerBannerDetail(status, installProgress);
  return (
    <section className={`installer-step-banner ${tone}`} aria-live="polite">
      <div className="installer-step-dot" />
      <div className="installer-step-copy">
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      <span className={`process-badge ${busy ? 'active' : setupAttention ? 'attention' : ''}`}>
        {operationLabel(busy, setupAttention)}
      </span>
    </section>
  );
}

function InstallerActions({
  backupStatus,
  busy,
  canInitialize,
  installRunning,
  isMacOS,
  ready,
  recheckAttention,
  setupRunning,
  statusValue,
  onImportBackup,
  onInitializeWorkspace,
  onOpenSetupTerminal,
  onPrepareMacTools,
  onRecheck,
  onRefreshBackup,
  onStartInstall,
  onEnterMain,
}: {
  backupStatus: InstallerBackupStatus | null;
  busy: string;
  canInitialize: boolean;
  installRunning: boolean;
  isMacOS: boolean;
  ready: boolean;
  recheckAttention: boolean;
  setupRunning: boolean;
  statusValue: string;
  onImportBackup: () => Promise<void>;
  onInitializeWorkspace: () => Promise<void>;
  onOpenSetupTerminal: () => Promise<void>;
  onPrepareMacTools: () => Promise<void>;
  onRecheck: () => Promise<void>;
  onRefreshBackup: () => Promise<void>;
  onStartInstall: () => Promise<void>;
  onEnterMain: () => Promise<void>;
}) {
  const disabled = Boolean(busy && busy !== 'install');
  const recheckDisabled = Boolean(busy && busy !== 'install');
  const recheckClass = recheckAttention ? 'attention-action' : undefined;
  if (ready) {
    return (
      <div className="settings-action-strip">
        <button type="button" className="primary-action" onClick={() => void onEnterMain()}>进入主控台</button>
        <button type="button" onClick={() => void onRecheck()} disabled={recheckDisabled}>重新检测</button>
      </div>
    );
  }
  if (statusValue === 'not_installed' || statusValue === 'install_failed' || statusValue === 'not_checked') {
    return (
      <div className="settings-action-strip vertical-actions">
        {isMacOS ? (
          <button type="button" className="attention-action" onClick={() => void onPrepareMacTools()} disabled={disabled || installRunning}>
            准备 macOS 基础工具
          </button>
        ) : null}
        <button type="button" className="primary-action" onClick={() => void onStartInstall()} disabled={disabled || installRunning}>
          {installRunning ? '安装中…' : '安装 Hermes Agent'}
        </button>
        <button type="button" className={recheckClass} onClick={() => void onRecheck()} disabled={recheckDisabled}>重新检测</button>
      </div>
    );
  }
  if (statusValue === 'installed_needs_setup' || statusValue === 'setup_in_progress') {
    return (
      <div className="settings-action-strip vertical-actions">
        <button type="button" onClick={() => void onOpenSetupTerminal()} disabled={disabled || setupRunning}>
          {setupRunning ? '配置终端运行中' : '高级：打开终端 setup'}
        </button>
        <button type="button" className={recheckClass || 'attention-action'} onClick={() => void onRecheck()} disabled={recheckDisabled}>重新检测配置状态</button>
      </div>
    );
  }
  if (statusValue === 'installed_not_initialized') {
    return (
      <div className="settings-action-strip vertical-actions">
        <button type="button" className="primary-action" onClick={() => void onInitializeWorkspace()} disabled={disabled || !canInitialize}>初始化工作空间</button>
        <button type="button" onClick={() => void onImportBackup()} disabled={disabled || !backupStatus?.has_backup}>导入最近备份</button>
        <button type="button" onClick={() => void onRefreshBackup()} disabled={disabled}>刷新备份</button>
        <button type="button" className={recheckClass} onClick={() => void onRecheck()} disabled={recheckDisabled}>重新检测</button>
      </div>
    );
  }
  return (
    <div className="settings-action-strip vertical-actions">
      <button type="button" className={recheckClass} onClick={() => void onRecheck()} disabled={recheckDisabled}>重新检测</button>
    </div>
  );
}

function InstallerHermesConfigPanel({
  busy,
  config,
  panelRef,
  form,
  status,
  testResult,
  onConfigChange,
  onOpenAdvancedSetup,
  onSaveAndTest,
}: {
  busy: string;
  config: HermesVisualConfig | null;
  panelRef: RefObject<HTMLElement | null>;
  form: HermesConfigForm;
  status: string;
  testResult: HermesConnectionTestResult | null;
  onConfigChange: (field: keyof HermesConfigForm, value: string) => void;
  onOpenAdvancedSetup: () => Promise<void>;
  onSaveAndTest: () => Promise<void>;
}) {
  const disabled = Boolean(busy);
  const providerOptions = config?.provider_options || [];
  const selectedProvider = providerOptionById(config, form.provider);
  const modelOptions = modelSelectOptions(form.model, selectedProvider?.models || []);
  const apiKeyLabel = selectedProvider?.api_key_name || config?.api_key?.name || '';
  const apiKeyConfigured = selectedProvider?.api_key_configured ?? config?.api_key?.configured;
  const notice = installerHermesConfigNotice(config, apiKeyLabel, Boolean(apiKeyConfigured), testResult);
  return (
    <section ref={panelRef} className="panel settings-section installer-config-panel">
      <div className="section-heading-row">
        <div>
          <h2>模型配置向导</h2>
          <p className="section-caption">填写 Provider、模型、Base URL 和 API Key；保存后无需进入终端 setup。</p>
        </div>
        <span>{installerConnectionStatusLabel(testResult, config?.connection_validation)}</span>
      </div>
      <div className="hermes-config-center">
        {notice ? (
          <div className={`hermes-config-alert ${notice.kind}`}>
            <strong>{notice.title}</strong>
            <span>{notice.detail}</span>
          </div>
        ) : null}
        {status ? <div className={installerNoticeClass(status)}>{status}</div> : null}
        <form
          className="hermes-visual-config"
          onSubmit={(event) => {
            event.preventDefault();
            void onSaveAndTest();
          }}
        >
          <div className="hermes-subsection-title">
            <strong>Hermes 模型配置</strong>
            <span>{apiKeyLabel ? `${apiKeyLabel}：${apiKeyConfigured ? '已配置' : '未配置'}` : 'API Key：当前 provider 不需要填写'}</span>
          </div>
          <div className="hermes-config-form-grid">
            <label className="settings-field" htmlFor="installer-hermes-provider">
              <span>Provider</span>
              <select
                id="installer-hermes-provider"
                value={form.provider}
                disabled={disabled}
                onChange={(event) => onConfigChange('provider', event.target.value)}
              >
                {providerOptions.length ? providerOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {providerOptionLabel(option)}
                  </option>
                )) : <option value={form.provider}>{form.provider || '读取中'}</option>}
              </select>
            </label>
            <label className="settings-field" htmlFor="installer-hermes-model">
              <span>模型</span>
              {modelOptions.length ? (
                <select
                  id="installer-hermes-model"
                  value={form.model}
                  disabled={disabled}
                  onChange={(event) => onConfigChange('model', event.target.value)}
                >
                  {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              ) : (
                <input
                  id="installer-hermes-model"
                  value={form.model}
                  placeholder="输入模型名称"
                  disabled={disabled}
                  onChange={(event) => onConfigChange('model', event.target.value)}
                />
              )}
            </label>
            <label className="settings-field wide" htmlFor="installer-hermes-base-url">
              <span>Base URL</span>
              <input
                id="installer-hermes-base-url"
                value={form.base_url}
                placeholder="https://api.openai.com/v1"
                disabled={disabled}
                onChange={(event) => onConfigChange('base_url', event.target.value)}
              />
            </label>
            <label className="settings-field wide" htmlFor="installer-hermes-api-key">
              <span>API Key</span>
              <input
                id="installer-hermes-api-key"
                type="password"
                value={form.api_key}
                placeholder={apiKeyConfigured ? '已配置，留空则不修改' : apiKeyLabel ? `输入 ${apiKeyLabel}` : '当前 provider 不需要在这里输入 API Key'}
                disabled={disabled || !apiKeyLabel}
                onChange={(event) => onConfigChange('api_key', event.target.value)}
              />
            </label>
          </div>
          <div className="hermes-config-footer installer-config-actions">
            <span>{selectedProvider?.auth_type && selectedProvider.auth_type !== 'api_key' ? '该 provider 使用外部授权；如需登录请使用高级终端 setup。' : config?.config_path || '读取 Hermes 配置中'}</span>
            <div className="settings-action-strip">
              <button type="submit" className="primary-action" disabled={disabled || !config?.command_exists}>
                {busy === 'config-test' ? '测试中...' : '保存并测试连接'}
              </button>
              <button type="button" onClick={() => void onOpenAdvancedSetup()} disabled={disabled}>
                高级终端 setup
              </button>
            </div>
          </div>
        </form>
        {testResult ? <InstallerHermesConnectionResult result={testResult} /> : null}
      </div>
    </section>
  );
}

function InstallerHermesConnectionResult({ result }: { result: HermesConnectionTestResult }) {
  const preview = result.output_preview || result.stderr_preview || '';
  return (
    <div className={`hermes-test-result ${result.success ? 'success' : 'danger'}`}>
      <strong>{result.success ? result.message || '连接测试通过' : result.error || '连接测试失败'}</strong>
      <span>{result.elapsed_seconds !== undefined ? `${result.elapsed_seconds}s` : result.command || '—'}</span>
      {preview ? <pre>{preview}</pre> : null}
    </div>
  );
}

function EmbeddedTerminalPanel({
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
    <section ref={panelRef} className="panel settings-section embedded-terminal-panel">
      <div className="section-heading-row">
        <h2>内置终端</h2>
        <div className="terminal-heading-actions">
          <span className={`terminal-status ${status}`}>{terminalStatusLabel(status, supported)}</span>
          <button type="button" className="danger-action" onClick={() => void onStop()} disabled={!session}>
            停止
          </button>
        </div>
      </div>
      <p className="embedded-terminal-hint">{message}</p>
      <div className="embedded-terminal-shell">
        <div ref={hostRef} className="embedded-terminal" />
        {status === 'idle' ? (
          <div className="embedded-terminal-placeholder">
            {supported ? '点击上方操作后，这里会显示真实终端输出。' : '当前环境不支持内置终端，会自动改用系统终端或后端日志。'}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function GuidanceList({ actions, suggestions }: { actions: string[]; suggestions: string[] }) {
  const items = actions.length ? actions : suggestions;
  if (!items.length) return <div className="empty-state inline-empty">暂无额外步骤。</div>;
  return (
    <div className="installer-guidance-list">
      {items.map((item, index) => {
        const trimmed = item.trim();
        const codeLike = item.startsWith('  ') || /^[a-z0-9_-]+(\s+[a-z0-9:_./-]+)+$/i.test(trimmed);
        return codeLike
          ? <pre key={`${trimmed}-${index}`}>{trimmed}</pre>
          : <p key={`${trimmed}-${index}`}>{trimmed}</p>;
      })}
    </div>
  );
}

function BackupImportPanel({ status }: { status: InstallerBackupStatus }) {
  return (
    <section className="panel settings-section">
      <div className="section-heading-row">
        <h2>导入备份</h2>
        <span>{status.has_backup ? '检测到备份' : '暂无备份'}</span>
      </div>
      <div className="settings-meta-list">
        <div className="settings-meta-row">
          <span>最近备份</span>
          <strong>{status.latest ? `${status.latest.display_path || status.latest.path || '备份文件'} · ${formatDateTime(status.latest.created_at)}` : '未检测到'}</strong>
        </div>
        <div className="settings-meta-row">
          <span>默认目录</span>
          <strong>{status.backup_root_display || '—'}</strong>
        </div>
        {status.error ? (
          <div className="settings-meta-row">
            <span>错误</span>
            <strong className="warn-text">{status.error}</strong>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function InstallLog({ lines, progress }: { lines: string[]; progress: InstallProgress | null }) {
  const logRef = useRef<HTMLPreElement | null>(null);
  const notice = installLogNotice(lines, progress);
  useEffect(() => {
    const element = logRef.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
  }, [lines, progress?.running]);
  return (
    <section className="panel settings-section">
      <div className="section-heading-row">
        <h2>安装日志</h2>
        <span>{progress?.running ? `${progress.line_count || lines.length} 行 · 同步中` : progress?.success === false ? '失败' : '已停止'}</span>
      </div>
      {progress?.truncated ? (
        <div className="installer-log-truncated">
          已隐藏最早 {progress.omitted_count || 0} 行日志，以保持界面流畅。
        </div>
      ) : null}
      {notice ? (
        <div className={`installer-log-notice ${notice.tone}`}>
          <strong>{notice.title}</strong>
          <span>{notice.detail}</span>
        </div>
      ) : null}
      <pre ref={logRef} className="installer-log">{lines.length ? lines.join('\n') : '等待安装输出…'}</pre>
    </section>
  );
}

function installLogNotice(lines: string[], progress: InstallProgress | null) {
  const text = lines.join('\n');
  if (/RPC failed|early EOF|fetch-pack|invalid index-pack|unexpected disconnect|transfer closed with outstanding read data/i.test(text)) {
    return {
      tone: 'danger',
      title: 'GitHub 克隆中断',
      detail: '安装脚本正在从 GitHub 克隆 Hermes Agent，但网络传输提前断开。请检查网络或代理后重试；如果多次失败，建议从 Releases 下载 macOS 二进制文件手动安装。',
    };
  }
  if (/Failed to parse `?pyproject\.toml`?|TOML parse error|failed to parse year in date "7 days"/i.test(text)) {
    return {
      tone: progress?.success === false ? 'danger' : 'warn',
      title: '检测到安装脚本警告',
      detail: '这是 Hermes 安装脚本或依赖项目的配置解析警告；如果安装仍在运行，可以先等待最终结果。若最后失败，可先完成 macOS 基础工具准备后重试，或改用 Releases 二进制安装。',
    };
  }
  if (progress?.running && lines.some((line) => /^\s*warning[:\s]/i.test(line))) {
    return {
      tone: 'warn',
      title: '安装过程中出现警告',
      detail: '警告不一定会中断安装；界面会继续等待最终成功或失败结果。',
    };
  }
  return null;
}

function emptyHermesConfigForm(): HermesConfigForm {
  return { provider: '', model: '', base_url: '', api_key: '' };
}

function formFromHermesConfig(config: HermesVisualConfig | null): HermesConfigForm {
  return {
    provider: config?.model?.provider || '',
    model: config?.model?.default || '',
    base_url: config?.model?.base_url || '',
    api_key: '',
  };
}

function providerOptionById(config: HermesVisualConfig | null, provider: string): HermesProviderOption | undefined {
  return config?.provider_options?.find((option) => option.id === provider);
}

function modelSelectOptions(currentModel: string, models: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of [currentModel, ...models]) {
    const model = value.trim();
    if (!model || seen.has(model)) continue;
    seen.add(model);
    result.push(model);
  }
  return result;
}

function providerOptionLabel(option: HermesProviderOption): string {
  const status = option.api_key_configured ? '已配置' : option.auth_type && option.auth_type !== 'api_key' ? '外部授权' : '未配置';
  const source = option.source === 'user-config' ? '自定义' : '';
  return `${option.label || option.id} (${option.id}) · ${source || status}`;
}

function installerHermesConfigNotice(
  config: HermesVisualConfig | null,
  apiKeyLabel: string,
  apiKeyConfigured: boolean,
  testResult: HermesConnectionTestResult | null,
): { kind: 'warn' | 'danger'; title: string; detail: string } | null {
  if (config?.ok === false) {
    return {
      kind: 'danger',
      title: '读取 Hermes 配置失败',
      detail: config.error || '请确认 hermes 命令可用，或使用高级终端 setup。',
    };
  }
  if (!config?.command_exists) {
    return {
      kind: 'danger',
      title: '未找到 hermes 命令',
      detail: '请先完成安装，或重新检测当前应用能否读取到 hermes 所在 PATH。',
    };
  }
  if (apiKeyLabel && !apiKeyConfigured && !testResult?.success) {
    return {
      kind: 'warn',
      title: '当前 Provider 缺少 API Key',
      detail: `请填写 ${apiKeyLabel} 后使用“保存并测试连接”；如果已经在外部配置过，也会在保存后一起验证。`,
    };
  }
  if (testResult && !testResult.success) {
    return {
      kind: 'danger',
      title: '模型连接测试失败',
      detail: testResult.error || '请检查 Provider、模型、Base URL 和 API Key。',
    };
  }
  return null;
}

function installerConnectionStatusLabel(
  testResult: HermesConnectionTestResult | null,
  validation: HermesConnectionValidation | undefined,
): string {
  if (testResult) return testResult.success ? '本次已验证' : '本次失败';
  if (validation?.verified) return `已验证 · ${formatDateTime(validation.verified_at || validation.tested_at)}`;
  if (validation?.reason === 'config_changed') return '配置变更后未验证';
  if (validation?.tested_at && !validation.verified) return '上次失败';
  return '未验证';
}

function installerNoticeClass(message: string) {
  return /失败|错误|无法|不支持|超时/.test(message) ? 'notice danger' : 'notice';
}

function operationLabel(busy: string, setupAttention: boolean) {
  if (busy === 'prep') return '准备中';
  if (busy === 'install') return '安装中';
  if (busy === 'setup') return '配置中';
  if (busy === 'config' || busy === 'config-test') return '配置中';
  if (busy === 'recheck') return '检测中';
  if (busy === 'init') return '初始化';
  if (busy === 'backup') return '导入中';
  if (setupAttention) return '等待确认';
  return '待操作';
}

function terminalBusyValue(task: DesktopTerminalTask) {
  if (task === 'mac-prerequisites') return 'prep';
  if (task === 'hermes-setup') return 'setup';
  if (task === 'update-hermes' || task === 'update-hermes-backup') return 'install';
  return 'install';
}

function terminalTaskLabel(task: DesktopTerminalTask) {
  if (task === 'mac-prerequisites') return '准备 macOS 基础工具';
  if (task === 'hermes-setup') return '配置 Hermes Agent';
  if (task === 'update-hermes') return '更新 Hermes Agent';
  if (task === 'update-hermes-backup') return '更新 Hermes Agent（完整备份）';
  return '安装 Hermes Agent';
}

function terminalStatusLabel(status: EmbeddedTerminalStatus, supported: boolean) {
  if (!supported) return '系统终端 fallback';
  if (status === 'starting') return '启动中';
  if (status === 'running') return '运行中';
  if (status === 'exited') return '已结束';
  if (status === 'error') return '异常结束';
  return '待命';
}

function terminalExitMessage(task: DesktopTerminalTask, succeeded: boolean, exitCode: number) {
  if (succeeded) {
    if (task === 'mac-prerequisites') return '基础工具命令已结束；请点击重新检测或继续安装 Hermes Agent。';
    if (task === 'hermes-setup') return 'Hermes setup 已结束；如果配置完成，请点击重新检测。';
    if (task === 'update-hermes' || task === 'update-hermes-backup') return 'Hermes 更新命令已结束，请重新检测工具状态。';
    return '安装命令已结束；正在重新检测 Hermes 是否可用。';
  }
  return `${terminalTaskLabel(task)}异常结束，退出码 ${exitCode}。请查看终端输出后重试。`;
}

function terminalExitStatus(task: DesktopTerminalTask, succeeded: boolean, exitCode: number) {
  if (succeeded) {
    if (task === 'mac-prerequisites') return '基础工具准备命令已结束，请重新检测或继续安装 Hermes Agent';
    if (task === 'hermes-setup') return 'Hermes setup 已结束，请重新检测';
    if (task === 'update-hermes' || task === 'update-hermes-backup') return 'Hermes 更新命令已结束，请重新检测';
    return '安装命令已结束，请重新检测 Hermes 状态';
  }
  return `${terminalTaskLabel(task)}异常结束（退出码 ${exitCode}）`;
}

function installerBannerTone(
  status: string,
  statusValue: string,
  progress: InstallProgress | null,
  setupAttention: boolean,
) {
  if (progress?.success === false || /失败|错误|异常|不支持|无法/.test(status)) return 'danger';
  if (statusValue === 'ready') return 'success';
  if (setupAttention || statusValue === 'installed_not_initialized' || statusValue === 'installed_needs_setup' || statusValue === 'setup_in_progress') return 'attention';
  if (progress?.running || statusValue === 'installing') return 'active';
  return 'neutral';
}

function installerBannerTitle(
  busy: string,
  statusValue: string,
  progress: InstallProgress | null,
  setupRunning: boolean,
  setupAttention: boolean,
) {
  if (busy === 'recheck') return '正在重新检测环境';
  if (progress?.running || busy === 'install') return '正在安装 Hermes Agent';
  if (progress?.success === false) return '安装没有完成';
  if (setupRunning) return '等待你在终端完成 Hermes setup';
  if (setupAttention) return '完成终端步骤后请重新检测';
  if (statusValue === 'installed_needs_setup' || statusValue === 'setup_in_progress') return '下一步：填写模型配置';
  if (statusValue === 'installed_not_initialized') return '下一步：初始化 Yachiyo 工作空间';
  if (statusValue === 'ready') return 'Hermes-Yachiyo 已就绪';
  return '按步骤完成 Hermes Agent 准备';
}

function installerBannerDetail(status: string, progress: InstallProgress | null) {
  if (progress?.running) {
    const lineCount = progress.line_count ?? progress.lines?.length ?? 0;
    return lineCount
      ? `已收到 ${lineCount} 行安装日志，下面会持续更新。`
      : '安装脚本已启动，日志出现前请稍候。';
  }
  if (progress?.success === false) return progress.message || status || '请查看安装日志后重试。';
  return status || '等待下一步操作。';
}

function installerTitle(status: string) {
  if (status === 'installed_not_initialized') return '初始化 Yachiyo 工作空间';
  if (status === 'installed_needs_setup' || status === 'setup_in_progress') return '配置 Hermes Agent';
  if (status === 'ready') return 'Hermes-Yachiyo 已就绪';
  return '安装 Hermes Agent';
}

function installerSubtitle(status: string, info: InstallInfo | null) {
  if (status === 'installed_not_initialized') return 'Hermes 已安装，下一步创建本地工作空间或导入备份。';
  if (status === 'installed_needs_setup') return 'Hermes 已安装，可以在下方 GUI 填写模型与 API Key。';
  if (status === 'setup_in_progress') return '可以继续使用下方 GUI 配置；如已打开终端 setup，完成后重新检测。';
  if (status === 'ready') return 'Hermes Agent 与 Yachiyo 工作空间均可用。';
  if (status === 'platform_unsupported' || status === 'wsl2_required') return info?.error_message || '当前平台需要按引导完成额外准备。';
  return '按当前平台自动安装 Hermes Agent，并用 GUI 完成模型配置。';
}

function statusText(status?: string, ready?: boolean) {
  if (ready || status === 'ready') return 'Hermes-Yachiyo 已就绪';
  return `当前状态：${installStatusLabel(status || 'not_checked')}`;
}

function installStatusLabel(status: string) {
  const labels: Record<string, string> = {
    not_checked: '未检测',
    not_installed: '未安装',
    installing: '安装中',
    install_failed: '安装失败',
    incompatible_version: '版本不兼容',
    platform_unsupported: '平台不支持',
    wsl2_required: '需要 WSL2',
    installed_needs_setup: '需要 setup',
    setup_in_progress: 'setup 进行中',
    installed_not_initialized: '需要初始化',
    initializing: '初始化中',
    ready: '已就绪',
  };
  return labels[status] || status || '未知';
}

function envRefreshNote(result: RecheckResult) {
  return result.needs_env_refresh ? '；提示：新终端中可能还需要重新加载 shell 环境' : '';
}

function isMacOSPlatform(value?: string) {
  return String(value || '').toLowerCase().includes('mac');
}

function formatDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
