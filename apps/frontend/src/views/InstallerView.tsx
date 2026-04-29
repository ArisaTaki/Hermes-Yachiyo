import { useCallback, useEffect, useRef, useState } from 'react';

import { apiGet, apiPost, openAppView, restartApp } from '../lib/bridge';

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
  success?: boolean | null;
  message?: string;
  setup_triggered?: boolean;
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

const INSTALL_POLL_MS = 1500;
const SETUP_POLL_MS = 3000;

export function InstallerView() {
  const [payload, setPayload] = useState<InstallInfoPayload | null>(null);
  const [backupStatus, setBackupStatus] = useState<InstallerBackupStatus | null>(null);
  const [installProgress, setInstallProgress] = useState<InstallProgress | null>(null);
  const [setupRunning, setSetupRunning] = useState(false);
  const [status, setStatus] = useState('正在检测 Hermes Agent…');
  const [logLines, setLogLines] = useState<string[]>([]);
  const [busy, setBusy] = useState('');
  const setupTerminalOpenedRef = useRef(false);

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
      } catch (error) {
        if (!disposed) setStatus(error instanceof Error ? error.message : '检测失败');
      }
    }
    void load();
    return () => {
      disposed = true;
    };
  }, [loadBackupStatus, loadInstallInfo]);

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

  async function startInstall() {
    setBusy('install');
    setStatus('正在启动 Hermes Agent 安装…');
    setLogLines([]);
    setupTerminalOpenedRef.current = false;
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
    const progress = await apiGet<InstallProgress>('/ui/installer/install/progress');
    setInstallProgress(progress);
    if (progress.lines?.length) setLogLines(progress.lines);

    if (progress.setup_triggered && !setupTerminalOpenedRef.current) {
      setupTerminalOpenedRef.current = true;
      await openSetupTerminal(true);
    }

    if (progress.running) return;
    setBusy('');
    if (progress.setup_triggered) {
      setStatus('Hermes 安装已进入初次配置，请在终端完成 setup 后重新检测');
      return;
    }
    if (progress.success) {
      setStatus('安装完成，正在重新检测…');
      await recheckStatus();
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
      setStatus(result.already_running ? '配置终端已在运行，请完成后重新检测' : '终端已打开，请完成 Hermes setup 后重新检测');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '打开配置终端失败');
    } finally {
      setBusy('');
    }
  }

  async function refreshSetupProcess() {
    try {
      const result = await apiGet<{ running?: boolean }>('/ui/installer/hermes/setup-process');
      setSetupRunning(Boolean(result.running));
      if (!result.running && setupRunning) setStatus('配置终端已关闭；如果已完成 setup，请重新检测');
    } catch {}
  }

  async function recheckStatus() {
    setBusy('recheck');
    try {
      const result = await apiPost<RecheckResult>('/ui/installer/status/recheck');
      await loadInstallInfo();
      if (result.ready) {
        setStatus(`Hermes 已就绪${envRefreshNote(result)}`);
        window.setTimeout(() => void openAppView('main'), 600);
      } else if (result.needs_init) {
        setStatus(`Hermes 配置完成，进入工作空间初始化${envRefreshNote(result)}`);
        await loadBackupStatus();
      } else if (result.status === 'installed_needs_setup' || result.status === 'setup_in_progress') {
        setStatus('Hermes setup 尚未完成，请确认终端配置结束后再次检测');
      } else {
        setStatus(result.message ? `检测结果：${result.status}（${result.message}）` : `检测结果：${result.status || 'unknown'}`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '重新检测失败');
    } finally {
      setBusy('');
    }
  }

  async function initializeWorkspace() {
    setBusy('init');
    setLogLines(['开始初始化 Yachiyo 工作空间…']);
    setStatus('正在初始化工作空间…');
    try {
      const result = await apiPost<WorkspaceInitResult>('/ui/installer/workspace/initialize');
      if (!result.success) throw new Error(result.error || '初始化失败');
      setLogLines(['开始初始化 Yachiyo 工作空间…', ...(result.created_items || []).map((item) => `已创建：${item}`), '工作空间初始化完成']);
      setStatus('初始化完成，正在重启应用…');
      window.setTimeout(() => void restartApp(), 1200);
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
      setStatus(`已导入 ${result.restored?.length || 0} 项备份资料，正在重启应用…`);
      window.setTimeout(() => void restartApp(), 1200);
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

  return (
    <main className="app-shell installer-shell">
      <header className="topbar">
        <div>
          <h1>{title}</h1>
          <p>{installerSubtitle(statusValue, installInfo)}</p>
        </div>
        {ready ? <button type="button" onClick={() => void openAppView('main')}>进入主控台</button> : null}
      </header>

      {status ? <div className={installerNoticeClass(status)}>{status}</div> : null}

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

        <article className="panel settings-section">
          <div className="section-heading-row">
            <h2>操作</h2>
            <span>{busy ? '执行中' : '待操作'}</span>
          </div>
          <InstallerActions
            backupStatus={backupStatus}
            busy={busy}
            canInitialize={Boolean(payload?.install_guidance?.can_initialize)}
            installRunning={Boolean(installProgress?.running)}
            ready={ready}
            setupRunning={setupRunning || statusValue === 'setup_in_progress'}
            statusValue={statusValue}
            onImportBackup={importBackup}
            onInitializeWorkspace={initializeWorkspace}
            onOpenSetupTerminal={() => openSetupTerminal(false)}
            onRecheck={recheckStatus}
            onRefreshBackup={loadBackupStatus}
            onStartInstall={startInstall}
          />
        </article>
      </section>

      {backupStatus ? <BackupImportPanel status={backupStatus} /> : null}
      {logLines.length || installProgress?.running ? <InstallLog lines={logLines} progress={installProgress} /> : null}
    </main>
  );
}

function InstallerActions({
  backupStatus,
  busy,
  canInitialize,
  installRunning,
  ready,
  setupRunning,
  statusValue,
  onImportBackup,
  onInitializeWorkspace,
  onOpenSetupTerminal,
  onRecheck,
  onRefreshBackup,
  onStartInstall,
}: {
  backupStatus: InstallerBackupStatus | null;
  busy: string;
  canInitialize: boolean;
  installRunning: boolean;
  ready: boolean;
  setupRunning: boolean;
  statusValue: string;
  onImportBackup: () => Promise<void>;
  onInitializeWorkspace: () => Promise<void>;
  onOpenSetupTerminal: () => Promise<void>;
  onRecheck: () => Promise<void>;
  onRefreshBackup: () => Promise<void>;
  onStartInstall: () => Promise<void>;
}) {
  const disabled = Boolean(busy);
  if (ready) {
    return (
      <div className="settings-action-strip">
        <button type="button" onClick={() => void openAppView('main')}>进入主控台</button>
        <button type="button" onClick={() => void onRecheck()} disabled={disabled}>重新检测</button>
      </div>
    );
  }
  if (statusValue === 'not_installed' || statusValue === 'install_failed' || statusValue === 'not_checked') {
    return (
      <div className="settings-action-strip vertical-actions">
        <button type="button" onClick={() => void onStartInstall()} disabled={disabled || installRunning}>
          {installRunning ? '安装中…' : '安装 Hermes Agent'}
        </button>
        <button type="button" onClick={() => void onRecheck()} disabled={disabled}>重新检测</button>
      </div>
    );
  }
  if (statusValue === 'installed_needs_setup' || statusValue === 'setup_in_progress') {
    return (
      <div className="settings-action-strip vertical-actions">
        <button type="button" onClick={() => void onOpenSetupTerminal()} disabled={disabled || setupRunning}>
          {setupRunning ? '配置终端运行中' : '开始配置 Hermes'}
        </button>
        <button type="button" onClick={() => void onRecheck()} disabled={disabled}>我已完成配置，重新检测</button>
      </div>
    );
  }
  if (statusValue === 'installed_not_initialized') {
    return (
      <div className="settings-action-strip vertical-actions">
        <button type="button" onClick={() => void onInitializeWorkspace()} disabled={disabled || !canInitialize}>初始化工作空间</button>
        <button type="button" onClick={() => void onImportBackup()} disabled={disabled || !backupStatus?.has_backup}>导入最近备份</button>
        <button type="button" onClick={() => void onRefreshBackup()} disabled={disabled}>刷新备份</button>
        <button type="button" onClick={() => void onRecheck()} disabled={disabled}>重新检测</button>
      </div>
    );
  }
  return (
    <div className="settings-action-strip vertical-actions">
      <button type="button" onClick={() => void onRecheck()} disabled={disabled}>重新检测</button>
    </div>
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
  return (
    <section className="panel settings-section">
      <div className="section-heading-row">
        <h2>安装日志</h2>
        <span>{progress?.running ? '运行中' : progress?.success === false ? '失败' : '已停止'}</span>
      </div>
      <pre className="installer-log">{lines.length ? lines.join('\n') : '等待安装输出…'}</pre>
    </section>
  );
}

function installerTitle(status: string) {
  if (status === 'installed_not_initialized') return '初始化 Yachiyo 工作空间';
  if (status === 'installed_needs_setup' || status === 'setup_in_progress') return '配置 Hermes Agent';
  if (status === 'ready') return 'Hermes-Yachiyo 已就绪';
  return '安装 Hermes Agent';
}

function installerSubtitle(status: string, info: InstallInfo | null) {
  if (status === 'installed_not_initialized') return 'Hermes 已安装，下一步创建本地工作空间或导入备份。';
  if (status === 'installed_needs_setup') return 'Hermes 已安装，但需要完成初次 setup 配置。';
  if (status === 'setup_in_progress') return '配置终端正在运行，完成后回到此处重新检测。';
  if (status === 'ready') return 'Hermes Agent 与 Yachiyo 工作空间均可用。';
  if (status === 'platform_unsupported' || status === 'wsl2_required') return info?.error_message || '当前平台需要按引导完成额外准备。';
  return '按当前平台自动安装 Hermes Agent，并在需要时引导完成 setup。';
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

function installerNoticeClass(value: string) {
  return /失败|错误|异常|不支持|无法|尚未/.test(value) ? 'notice danger' : 'notice';
}

function formatDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
