import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
  CODING_REPO_STORAGE_KEY,
  approveCodingJob,
  cancelCodingJob,
  getCodingArtifacts,
  getCodingConfig,
  getCodingJob,
  getCodingProviderInstall,
  getCodingProviders,
  getReviewProviders,
  installCodingProvider,
  testCodingProviderConfig,
  updateCodingConfig,
  type CodingArtifact,
  type CodingConfig,
  type CodingJob,
  type CodingProviderAction,
  type CodingProviderInstall,
  type CodingProviderStatus,
} from '../lib/coding';
import { currentParam, navigateTo } from '../lib/view';

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);
const TABS = ['providers', 'opendesign', 'defaults', 'detail'] as const;
const PRIMARY_PROVIDER_IDS = new Set(['local_claude_code', 'codex_review']);

type CodingTab = typeof TABS[number];
type OpenDesignMode = 'existing' | 'managed';

type DefaultsForm = {
  default_repo_path: string;
  default_writable_scopes: string;
  default_provider: string;
  default_review_strategy: string;
  default_design_mode: string;
  opendesign_artifact_dir: string;
  opendesign_daemon_url: string;
  opendesign_web_url: string;
  opendesign_auth_token: string;
  opendesign_app_path: string;
  opendesign_auto_start: boolean;
  claude_credential_mode: string;
  anthropic_base_url: string;
  anthropic_api_key: string;
  codex_credential_mode: string;
  codex_base_url: string;
  codex_api_key: string;
};

const DEFAULTS_FORM: DefaultsForm = {
  default_repo_path: '',
  default_writable_scopes: '.',
  default_provider: 'local_claude_code',
  default_review_strategy: 'codex_if_available',
  default_design_mode: 'none',
  opendesign_artifact_dir: '',
  opendesign_daemon_url: '',
  opendesign_web_url: '',
  opendesign_auth_token: '',
  opendesign_app_path: '',
  opendesign_auto_start: false,
  claude_credential_mode: 'cli_login',
  anthropic_base_url: '',
  anthropic_api_key: '',
  codex_credential_mode: 'cli_login',
  codex_base_url: '',
  codex_api_key: '',
};

export function CodingJobsView() {
  const jobIdFromRoute = currentParam('job');
  const tabFromRoute = currentParam('tab') as CodingTab;
  const [activeTab, setActiveTab] = useState<CodingTab>(() => jobIdFromRoute ? 'detail' : TABS.includes(tabFromRoute) ? tabFromRoute : 'providers');
  const [providers, setProviders] = useState<CodingProviderStatus[]>([]);
  const [reviewProviders, setReviewProviders] = useState<CodingProviderStatus[]>([]);
  const [config, setConfig] = useState<CodingConfig | null>(null);
  const [job, setJob] = useState<CodingJob | null>(null);
  const [artifacts, setArtifacts] = useState<CodingArtifact[]>([]);
  const [installs, setInstalls] = useState<Record<string, CodingProviderInstall>>({});
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [defaultsForm, setDefaultsForm] = useState<DefaultsForm>(DEFAULTS_FORM);
  const [openDesignMode, setOpenDesignMode] = useState<OpenDesignMode>('existing');
  const [openDesignModeTouched, setOpenDesignModeTouched] = useState(false);

  useEffect(() => {
    let disposed = false;
    async function loadInitial() {
      setBusy('load');
      try {
        const [coding, review, nextConfig] = await Promise.all([
          getCodingProviders(),
          getReviewProviders(),
          getCodingConfig(),
        ]);
        if (disposed) return;
        setProviders(coding);
        setReviewProviders(review);
        setConfig(nextConfig);
        setDefaultsForm(configToForm(nextConfig));
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取 Coding 配置失败');
      } finally {
        if (!disposed) setBusy('');
      }
    }
    void loadInitial();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!jobIdFromRoute) return;
    setActiveTab('detail');
    let disposed = false;
    async function loadJob() {
      try {
        const nextJob = await getCodingJob(jobIdFromRoute);
        if (disposed) return;
        setJob(nextJob);
        setError('');
        setArtifacts(await getCodingArtifacts(nextJob.job_id).catch(() => []));
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取 coding job 失败');
      }
    }
    void loadJob();
    return () => {
      disposed = true;
    };
  }, [jobIdFromRoute]);

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getCodingJob(job.job_id);
        setJob(nextJob);
        setArtifacts(await getCodingArtifacts(job.job_id).catch(() => []));
      } catch (err) {
        setError(err instanceof Error ? err.message : '刷新 job 失败');
      }
    }, 1400);
    return () => window.clearInterval(timer);
  }, [job]);

  useEffect(() => {
    const running = Object.values(installs).filter((item) => item.status === 'running');
    if (!running.length) return;
    const timer = window.setInterval(async () => {
      const updates = await Promise.all(running.map((item) => getCodingProviderInstall(item.install_id).catch(() => item)));
      setInstalls((current) => {
        const next = { ...current };
        updates.forEach((item) => {
          next[item.install_id] = item;
        });
        return next;
      });
      if (updates.some((item) => item.status !== 'running')) await refreshProviders(true);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [installs]);

  const allProviders = useMemo(() => [...providers, ...reviewProviders], [providers, reviewProviders]);
  const visibleProviders = useMemo(() => allProviders.filter((provider) => PRIMARY_PROVIDER_IDS.has(provider.id)), [allProviders]);
  const openDesignProvider = useMemo(() => allProviders.find((provider) => provider.id === 'opendesign'), [allProviders]);
  const openDesignInstall = useMemo(() => Object.values(installs).find((item) => item.provider_id === 'opendesign'), [installs]);
  const hasRunningInstall = useMemo(() => Object.values(installs).some((item) => item.status === 'running'), [installs]);
  const providerOperationLocked = Boolean(busy) || hasRunningInstall;
  const initialLoading = busy === 'load' && !config && !allProviders.length;

  useEffect(() => {
    if (openDesignModeTouched) return;
    if (!openDesignProvider) return;
    const capabilities = openDesignProvider.capabilities || {};
    const appPath = String(capabilities.app_path || defaultsForm.opendesign_app_path || '');
    const managedPath = String(capabilities.managed_path || '');
    if (appPath && managedPath && appPath.startsWith(managedPath)) {
      setOpenDesignMode('managed');
    } else if (defaultsForm.opendesign_daemon_url) {
      setOpenDesignMode('existing');
    }
  }, [openDesignModeTouched, openDesignProvider, defaultsForm.opendesign_app_path, defaultsForm.opendesign_daemon_url]);

  async function reloadProvidersAndConfig() {
    const [coding, review, nextConfig] = await Promise.all([getCodingProviders(), getReviewProviders(), getCodingConfig()]);
    setProviders(coding);
    setReviewProviders(review);
    setConfig(nextConfig);
    setDefaultsForm(configToForm(nextConfig));
    return nextConfig;
  }

  async function refreshProviders(force = false) {
    if (!force && providerOperationLocked) return;
    setBusy('providers');
    setError('');
    setStatus('正在重新检测 provider...');
    try {
      await reloadProvidersAndConfig();
      setStatus('Provider 状态已刷新。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新检测 provider 失败');
      setStatus('');
    } finally {
      setBusy('');
    }
  }

  async function saveDefaults(event: FormEvent) {
    event.preventDefault();
    setBusy('defaults');
    setError('');
    setStatus('正在保存 Coding 默认配置...');
    try {
      const nextConfig = await updateCodingConfig({
        default_repo_path: defaultsForm.default_repo_path,
        default_provider: defaultsForm.default_provider,
        default_review_strategy: defaultsForm.default_review_strategy,
        default_design_mode: defaultsForm.default_design_mode,
        default_writable_scopes: splitScopes(defaultsForm.default_writable_scopes),
      });
      setConfig(nextConfig);
      setDefaultsForm(configToForm(nextConfig));
      window.localStorage.setItem(CODING_REPO_STORAGE_KEY, nextConfig.default_repo_path || '');
      setStatus('Coding 默认配置已保存。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存默认配置失败');
      setStatus('');
    } finally {
      setBusy('');
    }
  }

  async function saveAndTestProviderConfig(providerId: string) {
    if (providerOperationLocked) return;
    setBusy(`save-test-${providerId}`);
    setError('');
    setStatus('正在保存并测试 provider 配置...');
    try {
      let payload: Partial<CodingConfig>;
      if (providerId === 'local_claude_code') {
        payload = {
          claude_credential_mode: defaultsForm.claude_credential_mode,
          anthropic_base_url: defaultsForm.anthropic_base_url,
          anthropic_api_key: defaultsForm.anthropic_api_key || (config?.anthropic_api_key_configured ? '[configured]' : ''),
        };
      } else if (providerId === 'codex_review') {
        payload = {
          codex_credential_mode: defaultsForm.codex_credential_mode,
          codex_base_url: defaultsForm.codex_base_url,
          codex_api_key: defaultsForm.codex_api_key || (config?.codex_api_key_configured ? '[configured]' : ''),
        };
      } else if (providerId === 'opendesign') {
        payload = {
          opendesign_daemon_url: defaultsForm.opendesign_daemon_url,
          opendesign_web_url: defaultsForm.opendesign_web_url,
          opendesign_auth_token: defaultsForm.opendesign_auth_token || (config?.opendesign_auth_token_configured ? '[configured]' : ''),
          opendesign_app_path: defaultsForm.opendesign_app_path,
          opendesign_auto_start: defaultsForm.opendesign_auto_start,
          opendesign_artifact_dir: defaultsForm.opendesign_artifact_dir,
        };
      } else {
        return;
      }
      await updateCodingConfig(payload);
      await reloadProvidersAndConfig();
      if (providerId === 'local_claude_code' || providerId === 'codex_review' || providerId === 'opendesign') {
        const result = await testCodingProviderConfig(providerId);
        await reloadProvidersAndConfig();
        setStatus(result.message || (result.available ? 'Provider 配置可用。' : 'Provider 配置不可用。'));
      } else {
        setStatus('Provider 配置已保存。');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存并测试 provider 配置失败');
      setStatus('');
    } finally {
      setBusy('');
    }
  }

  async function approveJob() {
    if (!job) return;
    setBusy('approve');
    setError('');
    setStatus('正在审批并启动 job...');
    try {
      const nextJob = await approveCodingJob(job.job_id);
      setJob(nextJob);
      setStatus(nextJob.ok === false ? nextJob.error || '审批失败' : 'Job 已启动。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '审批失败');
      setStatus('');
    } finally {
      setBusy('');
    }
  }

  async function cancelJob() {
    if (!job) return;
    setBusy('cancel');
    setError('');
    setStatus('正在取消 job...');
    try {
      const nextJob = await cancelCodingJob(job.job_id);
      setJob(nextJob);
      setArtifacts(await getCodingArtifacts(job.job_id).catch(() => []));
      setStatus(nextJob.ok === false ? nextJob.error || '取消失败' : 'Job 已取消。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消失败');
      setStatus('');
    } finally {
      setBusy('');
    }
  }

  async function runProviderAction(provider: CodingProviderStatus, action: CodingProviderAction) {
    if (providerOperationLocked) return;
    if (action.available === false) return;
    if (action.confirmation && !window.confirm(action.confirmation)) return;
    setBusy(`action-${provider.id}-${action.id}`);
    setError('');
    setStatus(`${provider.display_name || provider.id}: ${action.label}`);
    try {
      const install = await installCodingProvider(provider.id, action.id);
      setInstalls((current) => ({ ...current, [install.install_id]: install }));
      if (install.status !== 'running') await refreshProviders(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'provider 动作失败');
    } finally {
      setBusy('');
    }
  }

  async function runOpenDesignAction(action: CodingProviderAction, mode: OpenDesignMode = openDesignMode) {
    if (!openDesignProvider) return;
    if (providerOperationLocked) return;
    const managedPath = String(openDesignProvider.capabilities?.managed_path || '');
    if (mode === 'managed' && managedPath && ['install', 'start', 'upgrade'].includes(action.id)) {
      setBusy(`prepare-opendesign-${action.id}`);
      setError('');
      setStatus('正在切换 OpenDesign 到 Yachiyo 管辖目录...');
      try {
        const nextConfig = await updateCodingConfig({ opendesign_app_path: managedPath });
        setConfig(nextConfig);
        setDefaultsForm(configToForm(nextConfig));
      } catch (err) {
        setError(err instanceof Error ? err.message : '切换 OpenDesign 管辖目录失败');
        setStatus('');
        setBusy('');
        return;
      } finally {
        setBusy('');
      }
    }
    await runProviderAction(openDesignProvider, action);
  }

  function updateDefaults(key: keyof DefaultsForm, value: string | boolean) {
    setDefaultsForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <main className="hy-route-page coding-page">
      <header className="coding-hero hy-stagger">
        <button type="button" className="page-back-link" onClick={() => navigateTo('main')}>← 返回主控台</button>
        <div>
          <h1>Coding</h1>
          <p>配置 Claude Code、OpenDesign 与 Codex CLI，通过 /start-code 创建受控任务，并在审批后执行、review、收集产物。</p>
        </div>
      </header>

      <nav className="coding-tabs" aria-label="Coding sections">
        {TABS.map((tab) => (
          <button key={tab} type="button" className={activeTab === tab ? 'active' : ''} onClick={() => setActiveTab(tab)}>
            {tabLabel(tab)}
          </button>
        ))}
      </nav>

      {error ? <div className="tool-center-status danger">{error}</div> : null}
      {status ? <div className="tool-center-status">{status}</div> : null}

      {activeTab === 'providers' ? (
        <section className="coding-panel">
          <div className="section-heading-row">
            <h2>Providers</h2>
            <button type="button" className="hy-btn hy-btn-ghost" disabled={providerOperationLocked} onClick={() => void refreshProviders()}>
              {busy === 'providers' ? '检测中...' : '重新检测'}
            </button>
          </div>
          {initialLoading ? (
            <CodingLoadingSkeleton />
          ) : (
            <div className="coding-provider-grid">
              {visibleProviders.map((provider) => (
                <ProviderCard
                  key={`${provider.role}-${provider.id}`}
                  provider={provider}
                  config={config}
                  configForm={defaultsForm}
                  busy={busy}
                  locked={providerOperationLocked}
                  install={Object.values(installs).find((item) => item.provider_id === provider.id)}
                  onAction={(action) => void runProviderAction(provider, action)}
                  onConfigChange={updateDefaults}
                  onSaveAndTest={(providerId) => void saveAndTestProviderConfig(providerId)}
                />
              ))}
              {!visibleProviders.length ? <p className="empty-state">未读取到 Claude Code 或 Codex CLI provider。</p> : null}
            </div>
          )}
        </section>
      ) : null}

      {activeTab === 'opendesign' ? (
        <OpenDesignPanel
          provider={openDesignProvider}
          config={config}
          configForm={defaultsForm}
          install={openDesignInstall}
          busy={busy}
          locked={providerOperationLocked}
          mode={openDesignMode}
          onModeChange={(mode) => {
            setOpenDesignModeTouched(true);
            setOpenDesignMode(mode);
          }}
          onConfigChange={updateDefaults}
          onSaveAndTest={() => void saveAndTestProviderConfig('opendesign')}
          onAction={(action, mode) => void runOpenDesignAction(action, mode)}
          onRefresh={() => void refreshProviders()}
        />
      ) : null}

      {activeTab === 'defaults' ? (
        <section className="coding-panel">
          <div className="section-heading-row">
            <h2>Defaults</h2>
            <span>{config?.config_path || 'coding-config.json'}</span>
          </div>
          {initialLoading ? (
            <CodingLoadingSkeleton rows={2} />
          ) : (
            <form className="coding-form" onSubmit={saveDefaults}>
              <p className="coding-panel-note">Defaults 只作为 /start-code 未显式传参时的兜底值。Claude、Codex、OpenDesign 的安装、登录和 API 配置在 Providers 里完成。</p>
              <label>
                <span>Default Repo Path</span>
                <input className="hy-input" value={defaultsForm.default_repo_path} onChange={(event) => updateDefaults('default_repo_path', event.target.value)} placeholder="/path/to/git/repo" />
              </label>
              <label>
                <span>Default Writable Scopes</span>
                <input className="hy-input" value={defaultsForm.default_writable_scopes} onChange={(event) => updateDefaults('default_writable_scopes', event.target.value)} placeholder="src, tests" />
              </label>
              <div className="coding-form-row">
                <SelectField label="Default Provider" value={defaultsForm.default_provider} onChange={(value) => updateDefaults('default_provider', value)} options={['local_claude_code']} />
                <SelectField label="Default Review" value={defaultsForm.default_review_strategy} onChange={(value) => updateDefaults('default_review_strategy', value)} options={['codex_if_available', 'manual_only', 'none']} />
              </div>
              <SelectField label="Default Design Mode" value={defaultsForm.default_design_mode} onChange={(value) => updateDefaults('default_design_mode', value)} options={['none', 'brief_only', 'opendesign_daemon_if_available', 'opendesign_daemon_required', 'manual_artifact_import']} />
              <button type="submit" className="hy-btn hy-btn-primary" disabled={busy === 'defaults'}>保存默认配置</button>
            </form>
          )}
        </section>
      ) : null}

      {activeTab === 'detail' ? (
        job ? (
          <>
            <section className="coding-grid coding-grid-wide">
              <section className="coding-panel">
                <div className="section-heading-row">
                  <h2>Plan & Approval</h2>
                  <StatusPill status={job.status} />
                </div>
                <div className="coding-job-meta">
                  <span>Job: <code>{job.job_id}</code></span>
                  <span>Branch: <code>{job.branch_name || '-'}</code></span>
                  <span>Risk: <code>{job.risk_level || '-'}</code></span>
                </div>
                <pre className="diagnostic-output">{job.plan_summary || '暂无计划'}</pre>
                {job.dirty_summary?.dirty ? (
                  <div className="coding-warning">目标仓库已有 {job.dirty_summary.count || 0} 个 dirty changes：{(job.dirty_summary.files || []).slice(0, 6).join('，')}</div>
                ) : null}
                {job.blockers?.length ? (
                  <div className="coding-blockers">
                    {job.blockers.map((blocker, index) => (
                      <div className="coding-blocker" key={`${blocker.provider_id}-${index}`}>
                        <strong>{blocker.provider_id || 'blocker'} · {blocker.reason}</strong>
                        <p>{blocker.message}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="coding-actions">
                  <button type="button" className="hy-btn hy-btn-primary" disabled={busy === 'approve' || job.status !== 'awaiting_approval'} onClick={() => void approveJob()}>
                    审批并执行
                  </button>
                  <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy) || TERMINAL_STATUSES.has(job.status)} onClick={() => void cancelJob()}>
                    取消
                  </button>
                </div>
              </section>

              <section className="coding-panel">
                <div className="section-heading-row">
                  <h2>Job Timeline</h2>
                  <span>{job.updated_at ? new Date(job.updated_at).toLocaleString() : ''}</span>
                </div>
                <Timeline status={job.status} />
                {job.error ? <div className="tool-center-status danger">{job.error}</div> : null}
                {job.changed_files?.length ? (
                  <div className="coding-files">
                    <strong>Changed Files</strong>
                    {job.changed_files.map((file) => <code key={file}>{file}</code>)}
                  </div>
                ) : null}
              </section>
            </section>

            <section className="coding-panel">
              <div className="section-heading-row">
                <h2>Artifacts</h2>
                <span>{artifacts.length} files</span>
              </div>
              <div className="coding-artifacts">
                {artifacts.map((artifact) => (
                  <details key={artifact.path} open={artifact.path === 'review.md' || artifact.path === 'plan.md'}>
                    <summary><code>{artifact.path}</code><span>{formatBytes(artifact.size || 0)}</span></summary>
                    {artifact.content ? <pre>{artifact.content}</pre> : <p>此 artifact 过大或不是文本预览。</p>}
                  </details>
                ))}
                {!artifacts.length ? <p className="empty-state">暂无 artifact</p> : null}
              </div>
            </section>
          </>
        ) : (
          <section className="coding-panel"><p className="empty-state">在对话页使用 /start-code 创建任务后，这里会显示审批、执行进度和 artifacts。</p></section>
        )
      ) : null}
    </main>
  );
}

function CodingLoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="coding-loading-skeleton" aria-label="正在加载 Coding 配置">
      {Array.from({ length: rows }).map((_, index) => (
        <div className="coding-loading-card" key={index}>
          <span className="settings-skeleton-line title" />
          <span className="settings-skeleton-line detail" />
          <span className="settings-skeleton-control" />
        </div>
      ))}
    </div>
  );
}

function OpenDesignPanel({
  provider,
  config,
  configForm,
  install,
  busy,
  locked,
  mode,
  onModeChange,
  onConfigChange,
  onSaveAndTest,
  onAction,
  onRefresh,
}: {
  provider?: CodingProviderStatus;
  config: CodingConfig | null;
  configForm: DefaultsForm;
  install?: CodingProviderInstall;
  busy: string;
  locked: boolean;
  mode: OpenDesignMode;
  onModeChange: (mode: OpenDesignMode) => void;
  onConfigChange: (key: keyof DefaultsForm, value: string | boolean) => void;
  onSaveAndTest: () => void;
  onAction: (action: CodingProviderAction, mode: OpenDesignMode) => void;
  onRefresh: () => void;
}) {
  const capabilities = provider?.capabilities || {};
  const actions = provider?.actions || [];
  const actionById = (id: string) => actions.find((action) => action.id === id);
  const scanAction = actionById('scan');
  const installAction = actionById('install');
  const startAction = actionById('start');
  const openWebAction = actionById('open_web');
  const upgradeAction = actionById('upgrade');
  const managedPath = String(capabilities.managed_path || '');
  const appPath = String(capabilities.app_path || configForm.opendesign_app_path || '');
  const daemonUrl = String(capabilities.daemon_url || configForm.opendesign_daemon_url || '');
  const webUrl = String(capabilities.web_url || configForm.opendesign_web_url || '');
  const managedInstalled = Boolean(capabilities.managed_installed);
  const scanCandidates = Array.isArray(capabilities.scan_candidates)
    ? capabilities.scan_candidates as Array<{ exists?: string; path?: string; source?: string }>
    : [];
  const foundCount = scanCandidates.filter((item) => item.exists === 'true').length;
  const saveTestBusy = busy === 'save-test-opendesign';

  return (
    <section className="coding-panel coding-opendesign-panel">
      <div className="section-heading-row">
        <div>
          <h2>OpenDesign</h2>
          <p className="coding-panel-note">OpenDesign 是本地 web app + daemon。Yachiyo 只保存 daemon 连接信息，或管理一份专属源码目录并后台启动服务。</p>
        </div>
        <button type="button" className="hy-btn hy-btn-ghost" disabled={locked} onClick={onRefresh}>
          {busy === 'providers' ? '检测中...' : '重新检测'}
        </button>
      </div>

      {!provider ? (
        <CodingLoadingSkeleton rows={1} />
      ) : (
        <>
          <div className="coding-opendesign-status">
            <div>
              <span>连接状态</span>
              <StatusPill status={provider.availability} />
            </div>
            <div>
              <span>项目路径</span>
              <code>{appPath || '未配置'}</code>
            </div>
            <div>
              <span>Daemon</span>
              <code>{daemonUrl || '未连接'}</code>
            </div>
            <div>
              <span>WebUI</span>
              <code>{webUrl || '启动后从日志自动更新'}</code>
            </div>
          </div>

          <div className="coding-mode-switch" role="tablist" aria-label="OpenDesign setup mode">
            <button type="button" className={mode === 'existing' ? 'active' : ''} disabled={locked} onClick={() => onModeChange('existing')}>
              本机已有 OpenDesign
            </button>
            <button type="button" className={mode === 'managed' ? 'active' : ''} disabled={locked} onClick={() => onModeChange('managed')}>
              安装到 Yachiyo 管辖目录
            </button>
          </div>

          {mode === 'existing' ? (
            <div className="coding-opendesign-layout">
              <div className="coding-provider-config">
                <h3>手动连接</h3>
                <small>适用于你已经自己启动了 OpenDesign。这里只需要保存 daemon 地址并测试 `/api/health`。</small>
                <label>
                  <span>Daemon URL</span>
                  <input className="hy-input" value={configForm.opendesign_daemon_url} disabled={locked} onChange={(event) => onConfigChange('opendesign_daemon_url', event.target.value)} placeholder="http://127.0.0.1:57824" />
                </label>
                <label>
                  <span>WebUI URL（可选）</span>
                  <input className="hy-input" value={configForm.opendesign_web_url} disabled={locked} onChange={(event) => onConfigChange('opendesign_web_url', event.target.value)} placeholder="http://127.0.0.1:57828" />
                </label>
                <div className="coding-provider-config-actions">
                  <button type="button" className="hy-btn hy-btn-primary" disabled={locked || saveTestBusy} onClick={onSaveAndTest}>
                    {saveTestBusy ? '保存并测试中...' : '保存并测试连接'}
                  </button>
                  {openWebAction ? (
                    <button type="button" className="hy-btn hy-btn-ghost" disabled={locked || openWebAction.available === false} onClick={() => onAction(openWebAction, mode)}>
                      打开 WebUI
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="coding-opendesign-summary">
                <h3>检测结果</h3>
                <div className="coding-provider-checks">
                  <div className="coding-provider-check-row"><span>Daemon Health</span><small>{capabilities.daemon_reachable ? '可连接' : provider.blocking_reason || '未连接'}</small></div>
                  <div className="coding-provider-check-row"><span>版本</span><small>{provider.version || '未知'}</small></div>
                  <div className="coding-provider-check-row"><span>配置文件</span><code>{config?.config_path || 'coding-config.json'}</code></div>
                </div>
              </div>
            </div>
          ) : (
            <div className="coding-opendesign-layout">
              <div className="coding-provider-config">
                <h3>Yachiyo 管辖服务</h3>
                <small>找不到本机项目时，安装到 Yachiyo 工作区；之后由 Yachiyo 后台运行 `pnpm tools-dev run web`，并从启动日志更新 Daemon/WebUI 地址。</small>
                <div className="coding-provider-checks">
                  <div className="coding-provider-check-row"><span>管辖目录</span><code>{managedPath || '~/.hermes/yachiyo/external/open-design'}</code></div>
                  <div className="coding-provider-check-row"><span>已安装</span><small>{managedInstalled ? '是' : '否'}</small></div>
                  <div className="coding-provider-check-row"><span>扫描</span><small>{foundCount} found / {scanCandidates.length || 0} checked</small></div>
                </div>
                <div className="coding-provider-config-actions">
                  {scanAction ? <button type="button" className="hy-btn hy-btn-ghost" disabled={locked || scanAction.available === false} onClick={() => onAction(scanAction, mode)}>检查本机项目</button> : null}
                  {installAction ? <button type="button" className="hy-btn hy-btn-ghost" disabled={locked || installAction.available === false} onClick={() => onAction(installAction, mode)}>安装到管辖目录</button> : null}
                  {startAction ? <button type="button" className="hy-btn hy-btn-primary" disabled={locked || startAction.available === false} onClick={() => onAction(startAction, mode)}>一键安装依赖并启动</button> : null}
                  <button type="button" className="hy-btn hy-btn-ghost" disabled={locked || saveTestBusy} onClick={onSaveAndTest}>{saveTestBusy ? '测试中...' : '测试连接'}</button>
                  {openWebAction ? <button type="button" className="hy-btn hy-btn-ghost" disabled={locked || openWebAction.available === false} onClick={() => onAction(openWebAction, mode)}>打开 WebUI</button> : null}
                  {upgradeAction ? <button type="button" className="hy-btn hy-btn-ghost" disabled={locked || upgradeAction.available === false} onClick={() => onAction(upgradeAction, mode)}>检查版本并升级</button> : null}
                </div>
              </div>

              <div className="coding-opendesign-summary">
                <h3>服务地址</h3>
                <div className="coding-provider-checks">
                  <div className="coding-provider-check-row"><span>Daemon URL</span><code>{daemonUrl || '启动后自动更新'}</code></div>
                  <div className="coding-provider-check-row"><span>WebUI URL</span><code>{webUrl || '启动后自动更新'}</code></div>
                  <div className="coding-provider-check-row"><span>健康检查</span><small>{capabilities.daemon_reachable ? '可连接' : '未连接'}</small></div>
                </div>
              </div>
            </div>
          )}

          {install ? (
            <details className="coding-install-log coding-opendesign-log" open>
              <summary>{install.action} · {install.status}</summary>
              <pre>{(install.lines || []).slice(-80).join('\n') || install.error || install.command_preview || ''}</pre>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}

function ProviderCard({
  provider,
  config,
  configForm,
  busy,
  locked,
  install,
  onAction,
  onConfigChange,
  onSaveAndTest,
}: {
  provider: CodingProviderStatus;
  config: CodingConfig | null;
  configForm: DefaultsForm;
  busy: string;
  locked: boolean;
  install?: CodingProviderInstall;
  onAction: (action: CodingProviderAction) => void;
  onConfigChange: (key: keyof DefaultsForm, value: string | boolean) => void;
  onSaveAndTest: (providerId: string) => void;
}) {
  const apiConfigured = provider.id === 'local_claude_code'
    ? Boolean(config?.anthropic_api_key_configured)
    : provider.id === 'codex_review'
      ? Boolean(config?.codex_api_key_configured)
      : false;
  const isClaude = provider.id === 'local_claude_code';
  const isCodex = provider.id === 'codex_review';
  const credentialMode = isClaude ? configForm.claude_credential_mode : isCodex ? configForm.codex_credential_mode : '';
  const savedCredentialMode = String(provider.capabilities?.credential_mode || '');
  const modeDirty = Boolean(savedCredentialMode && credentialMode && credentialMode !== savedCredentialMode);
  const authAction = provider.actions?.find((action) => action.id === 'auth');
  const commonActions = (provider.actions || []).filter((action) => action.id !== 'auth' && (action.id === 'upgrade' || action.available !== false));
  const saveTestBusy = busy === `save-test-${provider.id}`;

  return (
    <article className={`coding-provider-card ${provider.availability === 'available' ? 'ready' : 'limited'}`}>
      <div className="coding-provider-card-head">
        <strong>{provider.display_name || provider.id}</strong>
        <span>{provider.role}</span>
      </div>
      <StatusPill status={provider.availability} />
      {provider.version ? <small>{provider.version}</small> : null}
      {provider.blocking_reason ? <p>{provider.blocking_reason}</p> : null}
      {provider.install_hint ? <p>{provider.install_hint}</p> : null}
      {provider.auth_hint && !isClaude && !isCodex ? <p>{provider.auth_hint}</p> : null}
      {provider.id === 'local_claude_code' ? (
        <div className="coding-provider-config">
          <h3>Credential Mode</h3>
          <CredentialModeSelect
            value={configForm.claude_credential_mode}
            onChange={(value) => onConfigChange('claude_credential_mode', value)}
            disabled={locked}
          />
          {credentialMode === 'api_env' ? (
            <ApiEnvPanel
              baseLabel="ANTHROPIC_BASE_URL"
              baseValue={configForm.anthropic_base_url}
              keyLabel="ANTHROPIC_API_KEY"
              keyValue={configForm.anthropic_api_key}
              apiConfigured={apiConfigured}
              keyPlaceholder={config?.anthropic_api_key_configured ? '已配置，留空不覆盖' : 'your_key'}
              onBaseChange={(value) => onConfigChange('anthropic_base_url', value)}
              onKeyChange={(value) => onConfigChange('anthropic_api_key', value)}
              onSaveAndTest={() => onSaveAndTest(provider.id)}
              busy={saveTestBusy}
              disabled={locked}
              note="只注入这里保存的 ANTHROPIC_*，并使用隔离 HOME，避免读取本机 Claude 登录态。"
            />
          ) : (
            <CliLoginPanel
              provider={provider}
              authAction={authAction}
              modeDirty={modeDirty}
              onAction={onAction}
              onSaveAndTest={() => onSaveAndTest(provider.id)}
              busy={saveTestBusy}
              disabled={locked}
              note="使用本机 Claude Code 登录态；不会注入 Yachiyo 保存的 Anthropic API Key。"
            />
          )}
        </div>
      ) : null}
      {provider.id === 'codex_review' ? (
        <div className="coding-provider-config">
          <h3>Credential Mode</h3>
          <CredentialModeSelect
            value={configForm.codex_credential_mode}
            onChange={(value) => onConfigChange('codex_credential_mode', value)}
            disabled={locked}
          />
          {credentialMode === 'api_env' ? (
            <ApiEnvPanel
              baseLabel="OPENAI_BASE_URL"
              baseValue={configForm.codex_base_url}
              keyLabel="OPENAI_API_KEY"
              keyValue={configForm.codex_api_key}
              apiConfigured={apiConfigured}
              keyPlaceholder={config?.codex_api_key_configured ? '已配置，留空不覆盖' : 'your_key'}
              onBaseChange={(value) => onConfigChange('codex_base_url', value)}
              onKeyChange={(value) => onConfigChange('codex_api_key', value)}
              onSaveAndTest={() => onSaveAndTest(provider.id)}
              busy={saveTestBusy}
              disabled={locked}
              note="只注入这里保存的 OPENAI_*，并使用隔离 HOME，避免读取本机 Codex 登录态。"
            />
          ) : (
            <CliLoginPanel
              provider={provider}
              authAction={authAction}
              modeDirty={modeDirty}
              onAction={onAction}
              onSaveAndTest={() => onSaveAndTest(provider.id)}
              busy={saveTestBusy}
              disabled={locked}
              note="使用本机 Codex 登录态；不会注入 Yachiyo 保存的 OpenAI API Key。"
            />
          )}
        </div>
      ) : null}
      {commonActions.length ? (
        <div className="coding-provider-actions">
          {commonActions.map((action) => (
            <button key={action.id} type="button" className="hy-btn hy-btn-ghost" disabled={locked || action.available === false || install?.status === 'running'} onClick={() => onAction(action)}>
              {providerActionLabel(action)}
            </button>
          ))}
        </div>
      ) : null}
      {install ? (
        <details className="coding-install-log" open={install.status === 'running'}>
          <summary>{install.action} · {install.status}</summary>
          <pre>{(install.lines || []).slice(-16).join('\n') || install.error || install.command_preview || ''}</pre>
        </details>
      ) : null}
    </article>
  );
}

function providerActionLabel(action: CodingProviderAction) {
  if (action.id === 'upgrade') return '检查最新版本并升级';
  return action.label;
}

function ApiEnvPanel({
  baseLabel,
  baseValue,
  keyLabel,
  keyValue,
  apiConfigured,
  keyPlaceholder,
  note,
  busy,
  disabled,
  onBaseChange,
  onKeyChange,
  onSaveAndTest,
}: {
  baseLabel: string;
  baseValue: string;
  keyLabel: string;
  keyValue: string;
  apiConfigured: boolean;
  keyPlaceholder: string;
  note: string;
  busy: boolean;
  disabled: boolean;
  onBaseChange: (value: string) => void;
  onKeyChange: (value: string) => void;
  onSaveAndTest: () => void;
}) {
  return (
    <div className="coding-provider-mode-panel">
      <small>{note}</small>
      <small>{apiConfigured ? `${keyLabel} 已配置。` : `未配置 ${keyLabel}；API Env 模式会阻止执行。`}</small>
      <label>
        <span>{baseLabel}</span>
        <input className="hy-input" value={baseValue} disabled={disabled} onChange={(event) => onBaseChange(event.target.value)} placeholder="https://your-gateway.example.com" />
      </label>
      <label>
        <span>{keyLabel}</span>
        <input className="hy-input" type="password" value={keyValue} disabled={disabled} onChange={(event) => onKeyChange(event.target.value)} placeholder={keyPlaceholder} />
      </label>
      <div className="coding-provider-config-actions">
        <button type="button" className="hy-btn hy-btn-primary" disabled={disabled || busy} onClick={onSaveAndTest}>
          {busy ? '保存并测试中...' : '保存并测试'}
        </button>
      </div>
    </div>
  );
}

function CliLoginPanel({
  provider,
  authAction,
  modeDirty,
  note,
  busy,
  disabled,
  onAction,
  onSaveAndTest,
}: {
  provider: CodingProviderStatus;
  authAction?: CodingProviderAction;
  modeDirty: boolean;
  note: string;
  busy: boolean;
  disabled: boolean;
  onAction: (action: CodingProviderAction) => void;
  onSaveAndTest: () => void;
}) {
  const authStatus = provider.capabilities?.auth_status as { logged_in?: boolean; summary?: string } | undefined;
  const loginState = modeDirty
    ? '模式已切换，保存并测试后刷新。'
    : authStatus?.logged_in
      ? '已检测到本机 CLI 登录态。'
      : provider.availability === 'not_authenticated'
        ? authStatus?.summary || '未检测到本机 CLI 登录态。'
        : provider.auth_required
          ? '需要本机 CLI 登录态。'
          : '当前模式不要求交互登录。';
  return (
    <div className="coding-provider-mode-panel">
      <small>{note}</small>
      <div className="coding-provider-checks">
        <div className="coding-provider-check-row">
          <span>CLI 可用性</span>
          <StatusPill status={modeDirty ? 'pending' : provider.availability} />
        </div>
        <div className="coding-provider-check-row">
          <span>登录态</span>
          <small>{loginState}</small>
        </div>
        {provider.executable_path ? (
          <div className="coding-provider-check-row">
            <span>命令路径</span>
            <code>{provider.executable_path}</code>
          </div>
        ) : null}
      </div>
      <div className="coding-provider-config-actions">
        <button type="button" className="hy-btn hy-btn-primary" disabled={disabled || busy} onClick={onSaveAndTest}>
          {busy ? '保存并测试中...' : '保存并测试'}
        </button>
        {authAction ? (
          <button type="button" className="hy-btn hy-btn-ghost" disabled={disabled || authAction.available === false} onClick={() => onAction(authAction)}>
            {authAction.label}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <select className="hy-select" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function CredentialModeSelect({ value, onChange, disabled = false }: { value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <label>
      <span>Mode</span>
      <select className="hy-select" value={value || 'cli_login'} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        <option value="api_env">API Env (isolated)</option>
        <option value="cli_login">CLI Login</option>
      </select>
    </label>
  );
}

function StatusPill({ status }: { status?: string }) {
  const value = status || 'unknown';
  const tone = ['available', 'completed', 'awaiting_approval'].includes(value)
    ? 'ready'
    : ['running', 'reviewing', 'planning', 'pending', 'installed_stopped'].includes(value)
      ? 'pending'
      : value === 'failed' || value === 'blocked' || value === 'not_installed' || value === 'not_authenticated' || value === 'unhealthy'
        ? 'limited'
        : 'planned';
  return <span className={`tool-status-pill ${tone}`}>{value}</span>;
}

function Timeline({ status }: { status: string }) {
  const steps = ['planning', 'awaiting_approval', 'running', 'reviewing', 'completed'];
  const terminal = status === 'failed' || status === 'cancelled';
  const currentIndex = steps.indexOf(status);
  return (
    <ol className="coding-timeline">
      {steps.map((step, index) => (
        <li className={index <= currentIndex && !terminal ? 'done' : step === status ? 'active' : ''} key={step}>
          <span>{index + 1}</span>{step}
        </li>
      ))}
      {terminal ? <li className="active danger"><span>!</span>{status}</li> : null}
    </ol>
  );
}

function configToForm(config: CodingConfig): DefaultsForm {
  return {
    default_repo_path: config.default_repo_path || '',
    default_writable_scopes: (config.default_writable_scopes || ['.']).join(', '),
    default_provider: config.default_provider || 'local_claude_code',
    default_review_strategy: config.default_review_strategy || 'codex_if_available',
    default_design_mode: config.default_design_mode || 'none',
    opendesign_artifact_dir: config.opendesign_artifact_dir || '',
    opendesign_daemon_url: config.opendesign_daemon_url || '',
    opendesign_web_url: config.opendesign_web_url || '',
    opendesign_auth_token: '',
    opendesign_app_path: config.opendesign_app_path || '',
    opendesign_auto_start: Boolean(config.opendesign_auto_start),
    claude_credential_mode: config.claude_credential_mode || 'cli_login',
    anthropic_base_url: config.anthropic_base_url || '',
    anthropic_api_key: '',
    codex_credential_mode: config.codex_credential_mode || 'cli_login',
    codex_base_url: config.codex_base_url || '',
    codex_api_key: '',
  };
}

function splitScopes(value: string) {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function tabLabel(tab: CodingTab) {
  if (tab === 'providers') return 'Providers';
  if (tab === 'opendesign') return 'OpenDesign';
  if (tab === 'defaults') return 'Defaults';
  return 'Job Detail';
}

function formatBytes(value: number) {
  if (!value) return '0 B';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
