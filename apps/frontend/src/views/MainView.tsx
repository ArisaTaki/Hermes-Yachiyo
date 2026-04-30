import { useEffect, useRef, useState } from 'react';

import { apiGet, apiPost, openAppView, openDesktopMode, quitApp } from '../lib/bridge';

type StatusRecord = {
  status?: string;
  label?: string;
  description?: string;
  blockers?: string[];
};

type ChatSession = {
  session_id?: string;
  title?: string;
  message_count?: number;
  is_current?: boolean;
  summary?: string;
  latest_role?: string;
  latest_status?: string;
  updated_at?: string;
  created_at?: string;
};

type HermesConfigAction = {
  id?: string;
  label?: string;
  command?: string;
  description?: string;
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

type DashboardData = {
  app?: { uptime_seconds?: number; version?: string; running?: boolean };
  hermes?: {
    status?: string;
    version?: string;
    platform?: string;
    command_exists?: boolean;
    hermes_home?: string;
    ready?: boolean;
    readiness_level?: string;
    limited_tools?: string[];
    doctor_issues_count?: number;
    configuration_actions?: HermesConfigAction[];
  };
  workspace?: { path?: string; initialized?: boolean; created_at?: string };
  bridge?: { state?: string; status?: string; running?: string; url?: string; config_dirty?: boolean; drift_details?: string[] };
  integrations?: { astrbot?: StatusRecord; hapi?: StatusRecord };
  modes?: { current?: string; items?: Array<{ id: string; name?: string; label?: string; description?: string }> };
  tasks?: { pending?: number; running?: number; completed?: number };
  chat?: {
    status_label?: string;
    is_processing?: boolean;
    empty?: boolean;
    recent_sessions?: ChatSession[];
    executor?: string;
    session_id?: string;
  };
};

export function MainView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [actionStatus, setActionStatus] = useState('');
  const [busyAction, setBusyAction] = useState('');
  const [hermesTestResult, setHermesTestResult] = useState<HermesConnectionTestResult | null>(null);
  const [hermesConfig, setHermesConfig] = useState<HermesVisualConfig | null>(null);
  const [configForm, setConfigForm] = useState<HermesConfigForm>(emptyHermesConfigForm());
  const busyActionRef = useRef('');

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const payload = await apiGet<DashboardData>('/ui/dashboard');
        if (!disposed) {
          setData(payload);
          setError('');
        }
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取主控台失败');
      }
    }
    refresh();
    void loadHermesConfig();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  function beginHermesAction(action: string) {
    if (busyActionRef.current) {
      setActionStatus('上一个 Hermes 操作正在处理，请稍候');
      return false;
    }
    busyActionRef.current = action;
    setBusyAction(action);
    return true;
  }

  function finishHermesAction(action: string) {
    if (busyActionRef.current !== action) return;
    busyActionRef.current = '';
    setBusyAction('');
  }

  async function refreshDashboardData() {
    const payload = await apiGet<DashboardData>('/ui/dashboard');
    setData(payload);
    setError('');
    return payload;
  }

  async function loadHermesConfig() {
    try {
      const result = await apiGet<HermesVisualConfig>('/ui/hermes/config');
      setHermesConfig(result);
      setConfigForm(formFromHermesConfig(result));
      return result;
    } catch {
      return null;
    }
  }

  function updateHermesConfigField(field: keyof HermesConfigForm, value: string) {
    if (field === 'provider') {
      const option = providerOptionById(hermesConfig, value);
      setConfigForm((current) => ({
        ...current,
        provider: value,
        model: option?.default_model || option?.models?.[0] || current.model,
        base_url: option?.base_url ?? current.base_url,
        api_key: '',
      }));
    } else {
      setConfigForm((current) => ({ ...current, [field]: value }));
    }
    if (actionStatus && /不能为空|配置已保存|连接测试/.test(actionStatus)) setActionStatus('');
  }

  async function saveHermesConfig() {
    const action = 'config-save';
    if (!beginHermesAction(action)) return;
    if (!configForm.provider.trim()) {
      setActionStatus('Provider 不能为空');
      finishHermesAction(action);
      return;
    }
    if (!configForm.model.trim()) {
      setActionStatus('模型名称不能为空');
      finishHermesAction(action);
      return;
    }
    setActionStatus('正在保存 Hermes 配置...');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; message?: string; configuration?: HermesVisualConfig }>('/ui/hermes/config', configForm);
      if (result.ok === false) throw new Error(result.error || '保存 Hermes 配置失败');
      if (result.configuration) {
        setHermesConfig(result.configuration);
        setConfigForm(formFromHermesConfig(result.configuration));
      } else {
        await loadHermesConfig();
      }
      setActionStatus(result.message || 'Hermes 配置已保存');
      await refreshDashboardData();
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '保存 Hermes 配置失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function openHermesCommand(command: string) {
    const action = `terminal:${command}`;
    if (!beginHermesAction(action)) return;
    setActionStatus(`正在打开终端：${command}`);
    try {
      const result = await apiPost<{ success?: boolean; error?: string }>('/ui/hermes/terminal-command', { command });
      if (!result.success) throw new Error(result.error || '打开终端失败');
      setActionStatus(`已打开终端：${command}`);
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '打开终端失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function testHermesConnection() {
    const action = 'connection-test';
    if (!beginHermesAction(action)) return;
    setHermesTestResult(null);
    setActionStatus('正在测试 Hermes provider/API Key 连接...');
    try {
      const result = await apiPost<HermesConnectionTestResult>('/ui/hermes/connection-test');
      setHermesTestResult(result);
      setActionStatus(result.success ? result.message || 'Hermes 连接测试通过' : result.error || 'Hermes 连接测试失败');
      await refreshDashboardData();
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Hermes 连接测试失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function recheckHermes() {
    const action = 'recheck';
    if (!beginHermesAction(action)) return;
    setActionStatus('正在重新检测 Hermes 状态...');
    try {
      const payload = await apiPost<DashboardData>('/ui/hermes/recheck');
      setData(payload);
      setError('');
      await loadHermesConfig();
      setActionStatus('Hermes 状态已刷新');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '重新检测 Hermes 失败');
    } finally {
      finishHermesAction(action);
    }
  }

  return (
    <main className="app-shell dashboard-shell">
      <header className="topbar">
        <div>
          <h1>Hermes-Yachiyo</h1>
          <p>桌面优先本地个人 Agent</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => void openAppView('chat')}>打开对话</button>
          <button className="ghost-button" type="button" onClick={quitApp}>退出</button>
        </div>
      </header>

      {error ? <div className="notice danger">{error}</div> : null}
      {actionStatus ? <div className={statusNoticeClass(actionStatus)}>{actionStatus}</div> : null}

      <section className="metric-grid dashboard-metrics">
        <Metric title="Hermes Agent" value={data?.hermes?.status || '读取中'} detail={hermesDetail(data)} />
        <Metric title="Workspace" value={data?.workspace?.initialized ? '已初始化' : '未初始化'} detail={data?.workspace?.path || '—'} />
        <Metric title="Runtime" value={formatUptime(data?.app?.uptime_seconds)} detail={data?.app?.version || '—'} />
        <Metric title="Bridge" value={bridgeState(data)} detail={data?.bridge?.url || '—'} />
        <Metric title="Tasks" value={`${data?.tasks?.running ?? 0} 运行中`} detail={`${data?.tasks?.pending ?? 0} 等待 / ${data?.tasks?.completed ?? 0} 完成`} />
        <Metric title="Integrations" value={data?.integrations?.astrbot?.label || data?.integrations?.astrbot?.status || '—'} detail={data?.integrations?.hapi?.label || data?.integrations?.hapi?.status || '—'} />
      </section>

      <section className="dashboard-layout">
        <article className="panel dashboard-card wide">
          <div className="section-heading-row">
            <h2>Hermes 配置中心</h2>
            <StatusPill active={Boolean(data?.hermes?.ready)} label={data?.hermes?.ready ? '能力就绪' : '待检查'} />
          </div>
          <HermesConfigCenter
            hermes={data?.hermes}
            config={hermesConfig}
            form={configForm}
            busyAction={busyAction}
            testResult={hermesTestResult}
            onConfigChange={updateHermesConfigField}
            onOpenCommand={openHermesCommand}
            onRecheck={recheckHermes}
            onSaveConfig={saveHermesConfig}
            onTestConnection={testHermesConnection}
          />
        </article>

        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>Yachiyo 工作空间</h2>
            <StatusPill active={Boolean(data?.workspace?.initialized)} label={data?.workspace?.initialized ? '已初始化' : '未初始化'} />
          </div>
          <InfoList rows={[
            ['路径', data?.workspace?.path],
            ['创建时间', formatDateTime(data?.workspace?.created_at)],
          ]} />
        </article>

        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>运行信息</h2>
            <StatusPill active={Boolean(data?.app?.running)} label={data?.app?.running ? '运行中' : '未运行'} />
          </div>
          <InfoList rows={[
            ['运行时间', formatUptime(data?.app?.uptime_seconds)],
            ['版本', data?.app?.version],
            ['Bridge', bridgeState(data)],
            ['Bridge 地址', data?.bridge?.url],
            ['配置漂移', data?.bridge?.config_dirty ? listOrDash(data?.bridge?.drift_details) : '无'],
          ]} />
        </article>

        <article className="panel dashboard-card">
          <div className="section-heading-row">
            <h2>任务统计</h2>
          </div>
          <InfoList rows={[
            ['等待中', String(data?.tasks?.pending ?? 0)],
            ['运行中', String(data?.tasks?.running ?? 0)],
            ['已完成', String(data?.tasks?.completed ?? 0)],
          ]} />
        </article>

        <article className="panel dashboard-card wide">
          <div className="section-heading-row">
            <h2>集成服务</h2>
          </div>
          <IntegrationBlock title="AstrBot / QQ" item={data?.integrations?.astrbot} />
          <IntegrationBlock title="Hapi / Codex" item={data?.integrations?.hapi} />
        </article>
      </section>

      <section className="panel action-panel">
        <h2>主控台</h2>
        <div className="action-row control-action-row">
          <button type="button" onClick={() => openDesktopMode(data?.modes?.current)}>打开表现态</button>
          <button type="button" onClick={() => void openAppView('chat')}>打开 Chat Window</button>
          <button type="button" onClick={() => void openAppView('settings')}>应用设置</button>
          <button type="button" onClick={() => void openAppView('settings', { mode: 'bubble' })}>Bubble 设置</button>
          <button type="button" onClick={() => void openAppView('settings', { mode: 'live2d' })}>Live2D 设置</button>
        </div>
      </section>

      <section className="dashboard-bottom-grid">
        <article className="panel chat-overview-panel">
          <div className="section-heading-row">
            <h2>会话中心</h2>
            <span>{conversationCountLabel(data?.chat?.recent_sessions, data?.chat?.status_label)}</span>
          </div>
          <ConversationList sessions={data?.chat?.recent_sessions || []} />
          <button type="button" className="wide-action" onClick={() => void openAppView('chat')}>打开完整对话窗口</button>
        </article>

        <article className="panel mode-overview-panel">
          <div className="section-heading-row">
            <h2>模式设置</h2>
            <span>当前：{modeName(data)}</span>
          </div>
          <div className="mode-summary-list">
            {(data?.modes?.items || []).map((mode) => (
              <button type="button" key={mode.id} onClick={() => void openAppView('settings', { mode: mode.id })}>
                <strong>{mode.name || mode.label || mode.id}</strong>
                <span>{mode.description || (mode.id === data?.modes?.current ? '当前模式' : '可切换表现态')}</span>
              </button>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}

function bridgeState(data: DashboardData | null) {
  return data?.bridge?.state || data?.bridge?.status || data?.bridge?.running || '—';
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

function providerOptionLabel(option: HermesProviderOption): string {
  const status = option.api_key_configured ? '已配置' : option.auth_type && option.auth_type !== 'api_key' ? '外部授权' : '未配置';
  const source = option.source === 'user-config' ? '自定义' : '';
  return `${option.label || option.id} (${option.id}) · ${source || status}`;
}

function statusNoticeClass(message: string) {
  return /失败|错误|无法|不支持|超时/.test(message) ? 'notice danger' : 'notice';
}

function hermesDetail(data: DashboardData | null): string {
  const version = data?.hermes?.version || '—';
  const readiness = data?.hermes?.readiness_level || (data?.hermes?.ready ? 'ready' : 'unknown');
  return `${version} / ${readiness}`;
}

function modeName(data: DashboardData | null): string {
  const current = data?.modes?.current || '';
  const item = data?.modes?.items?.find((entry) => entry.id === current);
  return item?.name || item?.label || current || '—';
}

function Metric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <article className="panel metric-card">
      <span>{title}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? 'status-pill ok' : 'status-pill warn'}>{label}</span>;
}

function InfoList({ rows }: { rows: Array<[string, string | number | undefined | null]> }) {
  return (
    <div className="settings-meta-list compact-list">
      {rows.map(([label, value]) => (
        <div className="settings-meta-row" key={label}>
          <span>{label}</span>
          <strong>{value === undefined || value === null || value === '' ? '—' : value}</strong>
        </div>
      ))}
    </div>
  );
}

function IntegrationBlock({ title, item }: { title: string; item?: StatusRecord }) {
  return (
    <div className="integration-block">
      <div className="integration-title-row">
        <strong>{title}</strong>
        <span>{item?.label || item?.status || '—'}</span>
      </div>
      {item?.description ? <p>{item.description}</p> : null}
      {item?.blockers?.length ? <p className="warn-text">{item.blockers.join('；')}</p> : null}
    </div>
  );
}

function HermesConfigCenter({
  hermes,
  config,
  form,
  busyAction,
  testResult,
  onConfigChange,
  onOpenCommand,
  onRecheck,
  onSaveConfig,
  onTestConnection,
}: {
  hermes?: DashboardData['hermes'];
  config: HermesVisualConfig | null;
  form: HermesConfigForm;
  busyAction: string;
  testResult: HermesConnectionTestResult | null;
  onConfigChange: (field: keyof HermesConfigForm, value: string) => void;
  onOpenCommand: (command: string) => Promise<void>;
  onRecheck: () => Promise<void>;
  onSaveConfig: () => Promise<void>;
  onTestConnection: () => Promise<void>;
}) {
  const actions = hermes?.configuration_actions || [];
  const busy = Boolean(busyAction);
  const providerOptions = config?.provider_options || [];
  const selectedProvider = providerOptionById(config, form.provider);
  const modelOptions = selectedProvider?.models || [];
  const apiKeyLabel = selectedProvider?.api_key_name || config?.api_key?.name || '';
  const apiKeyConfigured = selectedProvider?.api_key_configured ?? config?.api_key?.configured;
  return (
    <div className="hermes-config-center dashboard-hermes-center">
      <InfoList rows={[
        ['安装状态', hermes?.status],
        ['能力就绪', hermes?.ready ? '是' : '否'],
        ['就绪等级', hermes?.readiness_level],
        ['版本', hermes?.version],
        ['平台', hermes?.platform],
        ['命令可用', hermes?.command_exists ? '是' : '否'],
        ['Hermes Home', hermes?.hermes_home],
        ['受限工具', listOrDash(hermes?.limited_tools)],
        ['诊断提示', hermes?.doctor_issues_count ? `${hermes.doctor_issues_count} 项` : '无'],
      ]} />
      <form
        className="hermes-visual-config"
        onSubmit={(event) => {
          event.preventDefault();
          void onSaveConfig();
        }}
      >
        <div className="hermes-subsection-title">
          <strong>模型配置向导</strong>
          <span>{apiKeyLabel ? `${apiKeyLabel}：${apiKeyConfigured ? '已配置' : '未配置'}` : 'API Key：未检测'}</span>
        </div>
        <div className="hermes-config-form-grid">
          <label className="settings-field" htmlFor="hermes-provider">
            <span>Provider</span>
            <select
              id="hermes-provider"
              value={form.provider}
              disabled={busy}
              onChange={(event) => onConfigChange('provider', event.target.value)}
            >
              {providerOptions.length ? providerOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {providerOptionLabel(option)}
                </option>
              )) : <option value={form.provider}>{form.provider || '读取中'}</option>}
            </select>
          </label>
          <label className="settings-field" htmlFor="hermes-model">
            <span>模型</span>
            <input
              id="hermes-model"
              list="hermes-model-options"
              value={form.model}
              placeholder={modelOptions[0] || '输入模型名称'}
              disabled={busy}
              onChange={(event) => onConfigChange('model', event.target.value)}
            />
            {modelOptions.length ? (
              <datalist id="hermes-model-options">
                {modelOptions.map((model) => <option key={model} value={model} />)}
              </datalist>
            ) : null}
          </label>
          <label className="settings-field wide" htmlFor="hermes-base-url">
            <span>Base URL</span>
            <input
              id="hermes-base-url"
              value={form.base_url}
              placeholder="https://api.openai.com/v1"
              disabled={busy}
              onChange={(event) => onConfigChange('base_url', event.target.value)}
            />
          </label>
          <label className="settings-field wide" htmlFor="hermes-api-key">
            <span>API Key</span>
            <input
              id="hermes-api-key"
              type="password"
              value={form.api_key}
              placeholder={apiKeyConfigured ? '已配置，留空则不修改' : apiKeyLabel ? `输入 ${apiKeyLabel}` : '当前 provider 不需要在这里输入 API Key'}
              disabled={busy || !apiKeyLabel}
              onChange={(event) => onConfigChange('api_key', event.target.value)}
            />
          </label>
        </div>
        <div className="hermes-config-footer">
          <span>{selectedProvider?.auth_type && selectedProvider.auth_type !== 'api_key' ? '该 provider 使用外部授权；如需登录请用下方高级命令。' : config?.config_path || '读取 Hermes 配置中'}</span>
          <button
            type="submit"
            className="primary-action"
            disabled={busy || !hermes?.command_exists}
          >
            {busyAction === 'config-save' ? '保存中...' : '保存 Hermes 配置'}
          </button>
        </div>
      </form>
      <div className="hermes-test-strip">
        <button
          type="button"
          className="primary-action"
          disabled={busy || !hermes?.command_exists}
          onClick={() => void onTestConnection()}
        >
          {busyAction === 'connection-test' ? '测试中...' : '测试模型连接'}
        </button>
        <button
          type="button"
          className={busyAction === 'recheck' ? 'attention-action' : undefined}
          disabled={busy}
          onClick={() => void onRecheck()}
        >
          {busyAction === 'recheck' ? '检测中...' : '重新检测'}
        </button>
      </div>
      {testResult ? <HermesConnectionResult result={testResult} /> : null}
      <div className="hermes-command-grid">
        {actions.map((action) => {
          const command = action.command || '';
          const commandBusy = busyAction === `terminal:${command}`;
          return (
            <button
              type="button"
              className="hermes-command-button"
              disabled={busy || !command || !hermes?.command_exists}
              key={action.id || command}
              onClick={() => command ? void onOpenCommand(command) : undefined}
            >
              <span>{action.label || command}</span>
              <small>{commandBusy ? '正在打开终端...' : command}</small>
              {action.description ? <em>{action.description}</em> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function HermesConnectionResult({ result }: { result: HermesConnectionTestResult }) {
  const preview = result.output_preview || result.stderr_preview || '';
  return (
    <div className={`hermes-test-result ${result.success ? 'success' : 'danger'}`}>
      <strong>{result.success ? result.message || '连接测试通过' : result.error || '连接测试失败'}</strong>
      <span>{result.elapsed_seconds !== undefined ? `${result.elapsed_seconds}s` : result.command || '—'}</span>
      {preview ? <pre>{preview}</pre> : null}
    </div>
  );
}

function ConversationList({ sessions }: { sessions: ChatSession[] }) {
  if (!sessions.length) {
    return <div className="empty-state inline-empty">暂无对话。打开聊天窗口开始完整对话。</div>;
  }
  return (
    <div className="conversation-list">
      {sessions.map((session) => (
        <button
          className={session.is_current ? 'conversation-card current' : 'conversation-card'}
          key={session.session_id || session.title}
          type="button"
          onClick={() => void openAppView('chat')}
        >
          <span className="conversation-main-row">
            <strong>{session.title || '新对话'}</strong>
            {session.is_current ? <span className="conversation-pill">当前</span> : null}
          </span>
          <span className="conversation-summary">{session.summary || '暂无摘要'}</span>
          <span className="conversation-meta">
            <span>{session.message_count ?? 0} 条消息</span>
            <span>{formatConversationStatus(session)}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

function conversationCountLabel(sessions?: ChatSession[], fallback?: string) {
  if (!sessions) return fallback || '读取中';
  if (!sessions.length) return fallback || '暂无对话';
  return `${sessions.length} 个对话`;
}

function formatConversationStatus(session: ChatSession) {
  const status = session.latest_status;
  if (status === 'pending') return '等待中';
  if (status === 'processing') return '处理中';
  if (status === 'failed') return '失败';
  const time = formatShortDateTime(session.updated_at || session.created_at);
  if (time !== '—') return time;
  return status || '就绪';
}

function listOrDash(items?: string[]): string {
  return items?.length ? items.join('、') : '—';
}

function formatDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatShortDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatUptime(seconds?: number) {
  if (typeof seconds !== 'number') return '读取中';
  if (seconds < 60) return `${Math.floor(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 小时 ${minutes} 分钟`;
}
