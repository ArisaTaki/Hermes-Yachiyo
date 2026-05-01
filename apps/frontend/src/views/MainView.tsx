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
  connection_validation?: HermesConnectionValidation;
};

type HermesImageConnectionTestResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  detail?: string;
  output_preview?: string;
  stderr_preview?: string;
  elapsed_seconds?: number;
  returncode?: number;
  command?: string;
  route?: string;
  image_input?: HermesVisualConfig['image_input'];
  image_connection_validation?: HermesImageConnectionValidation;
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
  previous_provider?: string;
  previous_model?: string;
  elapsed_seconds?: number;
};

type HermesImageConnectionValidation = HermesConnectionValidation & {
  route?: string;
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
  image_input?: {
    can_attach_images?: boolean;
    mode?: string;
    route?: string;
    supports_native_vision?: boolean | null;
    requires_vision_pipeline?: boolean;
    label?: string;
    reason?: string;
    validation?: HermesImageConnectionValidation;
  };
  connection_validation?: HermesConnectionValidation;
  image_connection_validation?: HermesImageConnectionValidation;
  vision?: {
    configured?: boolean;
    provider?: string;
    model?: string;
    base_url?: string;
    api_key_name?: string;
    api_key_configured?: boolean;
    effective_provider?: string;
    effective_model?: string;
    effective_base_url?: string;
  };
};

type HermesProviderOption = {
  id: string;
  label?: string;
  base_url?: string;
  default_model?: string;
  default_vision_model?: string;
  models?: string[];
  vision_models?: string[];
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
  image_input_mode: string;
  vision_provider: string;
  vision_model: string;
  vision_base_url: string;
  vision_api_key: string;
};

type HermesProviderDraft = Pick<HermesConfigForm, 'model' | 'base_url'>;

type TtsSettings = {
  enabled?: boolean;
  provider?: string;
  endpoint?: string;
  command?: string;
  voice?: string;
  timeout_seconds?: number;
  max_chars?: number;
  notification_prompt?: string;
};

type SettingsData = {
  tts?: TtsSettings;
  mode_settings?: {
    live2d?: { config?: { tts?: TtsSettings } };
    bubble?: { config?: { tts?: TtsSettings } };
  };
};

type TtsForm = {
  enabled: boolean;
  provider: string;
  endpoint: string;
  command: string;
  voice: string;
  timeout_seconds: number;
  max_chars: number;
  notification_prompt: string;
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
  const [hermesImageTestResult, setHermesImageTestResult] = useState<HermesImageConnectionTestResult | null>(null);
  const [hermesConfig, setHermesConfig] = useState<HermesVisualConfig | null>(null);
  const [configForm, setConfigForm] = useState<HermesConfigForm>(emptyHermesConfigForm());
  const [ttsForm, setTtsForm] = useState<TtsForm>(emptyTtsForm());
  const busyActionRef = useRef('');
  const configFormDirtyRef = useRef(false);
  const ttsFormDirtyRef = useRef(false);
  const hermesConfigLoadedRef = useRef(false);
  const hermesConfigLoadingRef = useRef(false);
  const settingsLoadingRef = useRef(false);
  const providerDraftsRef = useRef<Record<string, HermesProviderDraft>>({});
  const mountedRef = useRef(false);

  useEffect(() => {
    let disposed = false;
    mountedRef.current = true;
    async function refresh() {
      try {
        const payload = await apiGet<DashboardData>('/ui/dashboard');
        if (!disposed) {
          setData(payload);
          setError('');
          if (!hermesConfigLoadedRef.current) void loadHermesConfig();
          if (!ttsFormDirtyRef.current) void loadSettings();
        }
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : '读取主控台失败');
      }
    }
    refresh();
    void loadHermesConfig();
    void loadSettings();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      disposed = true;
      mountedRef.current = false;
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

  async function loadHermesConfig(options: { forceFormSync?: boolean } = {}) {
    if (hermesConfigLoadingRef.current) return null;
    hermesConfigLoadingRef.current = true;
    try {
      const result = await apiGet<HermesVisualConfig>('/ui/hermes/config');
      hermesConfigLoadedRef.current = hasLoadedHermesConfig(result);
      if (mountedRef.current) {
        setHermesConfig(result);
        if (options.forceFormSync || !configFormDirtyRef.current) {
          syncProviderDraftFromConfig(result);
          setConfigForm(formFromHermesConfig(result));
        }
      }
      return result;
    } catch {
      hermesConfigLoadedRef.current = false;
      return null;
    } finally {
      hermesConfigLoadingRef.current = false;
    }
  }

  async function loadSettings(options: { forceFormSync?: boolean } = {}) {
    if (settingsLoadingRef.current) return null;
    settingsLoadingRef.current = true;
    try {
      const result = await apiGet<SettingsData>('/ui/settings');
      const tts = ttsFromSettings(result);
      if (mountedRef.current && (options.forceFormSync || !ttsFormDirtyRef.current)) {
        setTtsForm(formFromTtsSettings(tts));
      }
      return result;
    } catch {
      return null;
    } finally {
      settingsLoadingRef.current = false;
    }
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
      image_input_mode: current.image_input_mode || 'auto',
      vision_provider: current.vision_provider,
      vision_model: current.vision_model,
      vision_base_url: current.vision_base_url,
      vision_api_key: '',
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
        let next = { ...current, [field]: value };
        if (field === 'vision_provider') {
          const option = providerOptionById(hermesConfig, value);
          next = {
            ...next,
            vision_model: defaultVisionModel(option),
            vision_base_url: option?.base_url || '',
            vision_api_key: '',
          };
        }
        if (field === 'model' || field === 'base_url') rememberProviderDraft(next.provider, next);
        return next;
      });
    }
    if (actionStatus && /不能为空|配置已保存|连接测试/.test(actionStatus)) setActionStatus('');
    if (field === 'provider' || field === 'model' || field === 'base_url' || field === 'image_input_mode') {
      setHermesImageTestResult(null);
    }
  }

  function updateTtsField(field: keyof TtsForm, value: string | boolean | number) {
    ttsFormDirtyRef.current = true;
    setTtsForm((current) => {
      const next = { ...current, [field]: value };
      if (field === 'provider') {
        next.enabled = value !== 'none';
      }
      return next;
    });
    if (actionStatus && /TTS|播报/.test(actionStatus)) setActionStatus('');
  }

  async function saveHermesConfig() {
    const action = 'config-save';
    if (!beginHermesAction(action)) return;
    setActionStatus('正在保存 Hermes 配置...');
    try {
      const result = await persistHermesConfigDraft('保存 Hermes 配置失败');
      setActionStatus(result.message || 'Hermes 配置已保存');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '保存 Hermes 配置失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function persistHermesConfigDraft(errorMessage: string) {
    if (!configForm.provider.trim()) throw new Error('Provider 不能为空');
    if (!configForm.model.trim()) throw new Error('模型名称不能为空');
    const result = await apiPost<{ ok?: boolean; error?: string; message?: string; configuration?: HermesVisualConfig }>('/ui/hermes/config', configForm);
    if (result.ok === false) throw new Error(result.error || errorMessage);
    if (result.configuration) {
      configFormDirtyRef.current = false;
      hermesConfigLoadedRef.current = hasLoadedHermesConfig(result.configuration);
      syncProviderDraftFromConfig(result.configuration);
      setHermesConfig(result.configuration);
      setConfigForm(formFromHermesConfig(result.configuration));
    } else {
      configFormDirtyRef.current = false;
      await loadHermesConfig({ forceFormSync: true });
    }
    await refreshDashboardData();
    return result;
  }

  async function saveTtsSettings() {
    const action = 'tts-save';
    if (!beginHermesAction(action)) return;
    setActionStatus('正在保存 TTS 播报设置...');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; app_state?: { tts?: TtsSettings } }>('/ui/settings', {
        changes: {
          'tts.enabled': ttsForm.provider !== 'none',
          'tts.provider': ttsForm.provider,
          'tts.endpoint': ttsForm.endpoint,
          'tts.command': ttsForm.command,
          'tts.timeout_seconds': Number(ttsForm.timeout_seconds),
          'tts.max_chars': Number(ttsForm.max_chars),
          'tts.notification_prompt': ttsForm.notification_prompt,
        },
      });
      if (result.ok === false) throw new Error(result.error || '保存 TTS 设置失败');
      ttsFormDirtyRef.current = false;
      if (result.app_state?.tts) {
        setTtsForm(formFromTtsSettings(result.app_state.tts));
      } else {
        await loadSettings({ forceFormSync: true });
      }
      setActionStatus('TTS 播报设置已保存');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '保存 TTS 设置失败');
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
      if (result.connection_validation) {
        setHermesConfig((current) => (
          current ? { ...current, connection_validation: result.connection_validation } : current
        ));
      }
      setActionStatus(result.success ? result.message || 'Hermes 连接测试通过' : result.error || 'Hermes 连接测试失败');
      await refreshDashboardData();
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Hermes 连接测试失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function testHermesImageConnection() {
    const action = 'image-connection-test';
    if (!beginHermesAction(action)) return;
    setHermesImageTestResult(null);
    setActionStatus('正在测试 Hermes 图片链路...');
    try {
      if (configFormDirtyRef.current) {
        setActionStatus('正在保存当前图片链路配置...');
        await persistHermesConfigDraft('保存当前图片链路配置失败');
        setActionStatus('配置已保存，正在测试 Hermes 图片链路...');
      }
      const result = await apiPost<HermesImageConnectionTestResult>('/ui/hermes/image-connection-test');
      setHermesImageTestResult(result);
      if (result.image_connection_validation || result.image_input) {
        setHermesConfig((current) => {
          if (!current) return current;
          const validation = result.image_connection_validation || current.image_connection_validation;
          const imageInput = {
            ...(current.image_input || {}),
            ...(result.image_input || {}),
            validation,
          };
          return {
            ...current,
            image_input: imageInput,
            image_connection_validation: validation,
          };
        });
      }
      setActionStatus(result.success ? result.message || 'Hermes 图片链路测试通过' : result.error || 'Hermes 图片链路测试失败');
      await loadHermesConfig();
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : 'Hermes 图片链路测试失败');
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

  const currentMode = data?.modes?.current || 'bubble';
  return (
    <main className="app-shell dashboard-shell">
      <header className="topbar dashboard-topbar">
        <div>
          <h1>Hermes-Yachiyo</h1>
          <p>{data?.hermes?.ready ? 'Hermes 已就绪，桌面 Agent 可以使用' : '完成 Hermes 配置后开始使用桌面 Agent'}</p>
        </div>
        <div className="topbar-actions">
          <button className="primary-action" type="button" onClick={() => void openAppView('chat')}>打开对话</button>
          <button type="button" onClick={() => openDesktopMode(currentMode)}>打开表现态</button>
          <button className="ghost-button" type="button" onClick={quitApp}>退出</button>
        </div>
      </header>

      {error ? <div className="notice danger">{error}</div> : null}
      {actionStatus ? <div className={statusNoticeClass(actionStatus)}>{actionStatus}</div> : null}

      <section className="dashboard-status-strip" aria-label="状态概览">
        <StatusTile label="Hermes" value={data?.hermes?.status || '读取中'} detail={hermesDetail(data)} active={Boolean(data?.hermes?.ready)} />
        <StatusTile label="Workspace" value={data?.workspace?.initialized ? '已初始化' : '未初始化'} detail={data?.workspace?.path || '—'} active={Boolean(data?.workspace?.initialized)} />
        <StatusTile label="Bridge" value={bridgeState(data)} detail={data?.bridge?.url || '—'} active={bridgeState(data) === 'running'} />
        <StatusTile label="任务" value={`${data?.tasks?.running ?? 0} 运行中`} detail={`${data?.tasks?.pending ?? 0} 等待 / ${data?.tasks?.completed ?? 0} 完成`} active={!data?.tasks?.running} />
      </section>

      <section className="control-hub" aria-label="常用入口">
        <ControlHubButton
          title="对话"
          detail={data?.chat?.status_label || conversationCountLabel(data?.chat?.recent_sessions)}
          action="打开对话窗口"
          primary
          onClick={() => void openAppView('chat')}
        />
        <ControlHubGroup
          title="桌面表现"
          detail={`当前：${modeName(data)}`}
          primaryAction="打开角色"
          secondaryAction="配置表现态"
          onPrimary={() => openDesktopMode(currentMode)}
          onSecondary={() => void openAppView('settings', { mode: currentMode })}
        />
        <ControlHubButton
          title="应用维护"
          detail="Bridge、备份、卸载和应用选项"
          action="打开应用设置"
          onClick={() => void openAppView('settings')}
        />
        <ControlHubButton
          title="工具中心"
          detail={toolCenterDetail(data?.hermes)}
          action="查看工具状态"
          onClick={() => void openAppView('tools')}
        />
      </section>

      <section className="dashboard-workbench">
        <div className="dashboard-main-column">
          <article className="panel dashboard-card" id="hermes-config">
            <div className="section-heading-row">
              <div>
                <h2>Hermes 配置中心</h2>
                <p className="section-caption">Provider、模型、Base URL、API Key 和连接测试集中在这里。</p>
              </div>
              <StatusPill active={Boolean(data?.hermes?.ready)} label={data?.hermes?.ready ? '基础就绪' : '待检查'} />
            </div>
            <HermesConfigCenter
              hermes={data?.hermes}
              config={hermesConfig}
              form={configForm}
              busyAction={busyAction}
              testResult={hermesTestResult}
              imageTestResult={hermesImageTestResult}
              ttsForm={ttsForm}
              onConfigChange={updateHermesConfigField}
              onTtsChange={updateTtsField}
              onRecheck={recheckHermes}
              onSaveConfig={saveHermesConfig}
              onSaveTts={saveTtsSettings}
              onTestConnection={testHermesConnection}
              onTestImageConnection={testHermesImageConnection}
            />
          </article>

          <article className="panel chat-overview-panel" id="conversation-center">
            <div className="section-heading-row">
              <div>
                <h2>会话中心</h2>
                <p className="section-caption">最近对话和摘要；完整收发消息请进入对话窗口。</p>
              </div>
              <span>{conversationCountLabel(data?.chat?.recent_sessions, data?.chat?.status_label)}</span>
            </div>
            <ConversationList sessions={data?.chat?.recent_sessions || []} />
            <button type="button" className="wide-action" onClick={() => void openAppView('chat')}>打开完整对话窗口</button>
          </article>
        </div>

        <aside className="dashboard-side-column" aria-label="系统信息">
          <article className="panel dashboard-card">
            <div className="section-heading-row">
              <h2>运行状态</h2>
              <StatusPill active={Boolean(data?.app?.running)} label={data?.app?.running ? '运行中' : '未运行'} />
            </div>
            <InfoList rows={[
              ['运行时间', formatUptime(data?.app?.uptime_seconds)],
              ['Yachiyo 版本', data?.app?.version],
              ['Bridge', bridgeState(data)],
              ['配置漂移', data?.bridge?.config_dirty ? listOrDash(data?.bridge?.drift_details) : '无'],
            ]} />
          </article>

          <article className="panel dashboard-card">
            <div className="section-heading-row">
              <h2>工作空间</h2>
              <StatusPill active={Boolean(data?.workspace?.initialized)} label={data?.workspace?.initialized ? '已初始化' : '未初始化'} />
            </div>
            <InfoList rows={[
              ['路径', data?.workspace?.path],
              ['创建时间', formatDateTime(data?.workspace?.created_at)],
            ]} />
          </article>

          <article className="panel dashboard-card">
            <div className="section-heading-row">
              <h2>集成服务</h2>
            </div>
            <IntegrationBlock title="AstrBot / QQ" item={data?.integrations?.astrbot} />
            <IntegrationBlock title="Hapi / Codex" item={data?.integrations?.hapi} />
          </article>
        </aside>
      </section>
    </main>
  );
}

function bridgeState(data: DashboardData | null) {
  return data?.bridge?.state || data?.bridge?.status || data?.bridge?.running || '—';
}

function emptyHermesConfigForm(): HermesConfigForm {
  return {
    provider: '',
    model: '',
    base_url: '',
    api_key: '',
    image_input_mode: 'auto',
    vision_provider: '',
    vision_model: '',
    vision_base_url: '',
    vision_api_key: '',
  };
}

function formFromHermesConfig(config: HermesVisualConfig | null): HermesConfigForm {
  return {
    provider: config?.model?.provider || '',
    model: config?.model?.default || '',
    base_url: config?.model?.base_url || '',
    api_key: '',
    image_input_mode: config?.image_input?.mode === 'text' ? 'text' : 'auto',
    vision_provider: config?.vision?.provider || '',
    vision_model: config?.vision?.configured ? (config?.vision?.effective_model || config?.vision?.model || '') : (config?.vision?.model || ''),
    vision_base_url: config?.vision?.base_url || '',
    vision_api_key: '',
  };
}

function emptyTtsForm(): TtsForm {
  return {
    enabled: false,
    provider: 'none',
    endpoint: '',
    command: '',
    voice: '',
    timeout_seconds: 20,
    max_chars: 80,
    notification_prompt: '主动提醒只输出适合语音播报的一句中文招呼或提醒，保持八千代人设，不要朗读长段分析、列表、代码、路径或调试信息。',
  };
}

function ttsFromSettings(settings: SettingsData | null): TtsSettings | undefined {
  return settings?.tts || settings?.mode_settings?.live2d?.config?.tts || settings?.mode_settings?.bubble?.config?.tts;
}

function formFromTtsSettings(settings: TtsSettings | undefined): TtsForm {
  return {
    ...emptyTtsForm(),
    ...settings,
    enabled: Boolean(settings?.enabled),
    provider: settings?.provider || 'none',
    timeout_seconds: Number(settings?.timeout_seconds || 20),
    max_chars: Number(settings?.max_chars || 80),
  };
}

function hasLoadedHermesConfig(config: HermesVisualConfig | null): boolean {
  return Boolean(
    config
    && config.ok !== false
    && (
      config.provider_options?.length
      || config.model?.provider
      || config.config_path
      || config.env_path
    ),
  );
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

function buildVisionModelOptions(option: HermesProviderOption | undefined, currentModel: string): string[] {
  const models = option?.vision_models?.length ? option.vision_models : option?.models || [];
  const preferred = option?.default_vision_model || models[0] || '';
  return modelSelectOptions(currentModel && currentModel !== option?.default_model ? currentModel : preferred, models);
}

function defaultVisionModel(option: HermesProviderOption | undefined): string {
  return option?.default_vision_model || option?.vision_models?.[0] || option?.default_model || option?.models?.[0] || '';
}

function providerOptionLabel(option: HermesProviderOption): string {
  const status = option.api_key_configured ? '已配置' : option.auth_type && option.auth_type !== 'api_key' ? '外部授权' : '未配置';
  const source = option.source === 'user-config' ? '自定义' : '';
  return `${option.label || option.id} (${option.id}) · ${source || status}`;
}

function hermesInstallStatusLabel(status?: string): string {
  if (status === 'ready') return '已安装并初始化';
  if (status === 'installed_needs_setup') return '已安装，待 setup';
  if (status === 'setup_in_progress') return 'setup 进行中';
  if (status === 'installed_not_initialized') return '待初始化 Yachiyo 工作空间';
  if (status === 'not_installed') return '未安装';
  if (status === 'incompatible_version') return '版本不兼容';
  if (status === 'install_failed') return '安装失败';
  return status || '未知';
}

function hermesReadinessLevelLabel(level?: string): string {
  if (level === 'full_ready') return '完整就绪';
  if (level === 'basic_ready') return '基础可用，部分能力受限';
  if (level === 'unknown') return '未完成 Doctor 分级';
  return level || '未检测';
}

function hermesConfigNotice(
  hermes: DashboardData['hermes'] | undefined,
  apiKeyLabel: string,
  apiKeyConfigured: boolean,
  testResult: HermesConnectionTestResult | null,
  validation: HermesConnectionValidation | undefined,
): { kind: 'warn' | 'danger'; title: string; detail: string } | null {
  if (!hermes?.command_exists) {
    return {
      kind: 'danger',
      title: '未找到 hermes 命令',
      detail: '请先安装 Hermes Agent，或确认当前应用进程能读取到 hermes 所在 PATH。',
    };
  }
  if (!hermes.ready) {
    return {
      kind: 'warn',
      title: '基础环境尚未完成',
      detail: '需要完成 Hermes setup 和 Yachiyo 工作空间初始化后，桌面 Agent 才能正常运行。',
    };
  }
  if (apiKeyLabel && !apiKeyConfigured) {
    return {
      kind: 'danger',
      title: '当前 Provider 缺少 API Key',
      detail: `请在上方填写 ${apiKeyLabel} 并保存，或切换到已配置凭据的 Provider。`,
    };
  }
  if (testResult && !testResult.success) {
    return {
      kind: 'danger',
      title: '模型连接测试失败',
      detail: testResult.error || '请检查 Provider、模型、Base URL 和 API Key。',
    };
  }
  if (testResult?.success) return null;
  return hermesConnectionNotice(validation);
}

function hermesConnectionNotice(
  validation: HermesConnectionValidation | undefined,
): { kind: 'warn' | 'danger'; title: string; detail: string } | null {
  if (validation?.verified) return null;
  if (validation?.reason === 'config_changed') {
    return {
      kind: 'warn',
      title: '模型配置变更后尚未重新验证',
      detail: '检测到 provider、模型、Base URL 或配置文件已变化，请重新测试模型连接。',
    };
  }
  if (validation?.tested_at && !validation.verified) {
    return {
      kind: 'danger',
      title: '上次模型连接测试失败',
      detail: validation.error || '请检查 Provider、模型、Base URL 和 API Key 后重新测试。',
    };
  }
  return {
    kind: 'warn',
    title: '模型连接尚未验证',
    detail: '基础状态 ready 只代表 Hermes 命令、setup 和 Yachiyo 工作空间通过检查；API Key 是否能调用模型需要点击“测试模型连接”。',
  };
}

function hermesConnectionStatusLabel(
  testResult: HermesConnectionTestResult | null,
  validation: HermesConnectionValidation | undefined,
): string {
  if (testResult) return testResult.success ? '本次已验证' : '本次失败';
  if (validation?.verified) {
    const testedAt = formatShortDateTime(validation.verified_at || validation.tested_at);
    return testedAt === '—' ? '已验证' : `已验证 · ${testedAt}`;
  }
  if (validation?.reason === 'config_changed') return '配置变更后未验证';
  if (validation?.tested_at && !validation.verified) return '上次失败';
  return '未验证';
}

function hermesImageConnectionNotice(
  imageInput: HermesVisualConfig['image_input'] | undefined,
  testResult: HermesImageConnectionTestResult | null,
  validation: HermesImageConnectionValidation | undefined,
): { kind: 'warn' | 'danger'; title: string; detail: string } | null {
  if (!imageInput) return null;
  if (testResult && !testResult.success) {
    return {
      kind: 'danger',
      title: '图片链路测试失败',
      detail: testResult.error || '请检查图片输入模式、vision provider、Base URL 和 API Key。',
    };
  }
  if (testResult?.success) return null;
  if (validation?.verified) return null;
  if (imageInput.route === 'blocked') {
    return {
      kind: 'warn',
      title: '图片输入还不能使用',
      detail: imageInput.reason || '请切换支持图片的主模型，或在图片识别链路中选择单独图片模型。',
    };
  }
  if (validation?.tested_at && !validation.verified) {
    return {
      kind: 'danger',
      title: '上次图片链路测试失败',
      detail: validation.error || '文本模型连接可用，但图片预分析链路没有通过。',
    };
  }
  if (validation?.reason === 'config_changed') {
    return {
      kind: 'warn',
      title: '图片配置变更后尚未重新验证',
      detail: '检测到 provider、模型、Base URL 或图片输入模式变化，请重新测试图片链路。',
    };
  }
  if (imageInput.requires_vision_pipeline) {
    return {
      kind: 'warn',
      title: '图片需要单独验证',
      detail: '当前配置会先用 Hermes vision 链路识图，再把分析结果交给文本模型；“测试模型连接”只验证文字请求。',
    };
  }
  return null;
}

function hermesImageInputLabel(imageInput: HermesVisualConfig['image_input'] | undefined): string {
  if (!imageInput) return '未检测';
  const suffix = imageInput.mode ? ` · ${imageInput.mode}` : '';
  if (imageInput.can_attach_images === false) return `不可用${suffix}`;
  return `${imageInput.label || '可用'}${suffix}`;
}

function hermesImageConnectionStatusLabel(
  imageInput: HermesVisualConfig['image_input'] | undefined,
  validation: HermesImageConnectionValidation | undefined,
): string {
  if (!imageInput) return '未检测';
  if (imageInput.route === 'blocked') return '不可用';
  if (imageInput.route === 'native' && imageInput.supports_native_vision === true) return '原生多模态';
  if (validation?.verified) {
    const testedAt = formatShortDateTime(validation.verified_at || validation.tested_at);
    return testedAt === '—' ? '已验证' : `已验证 · ${testedAt}`;
  }
  if (validation?.reason === 'config_changed') return '配置变更后未验证';
  if (validation?.tested_at && !validation.verified) return '上次失败';
  if (imageInput.requires_vision_pipeline) return '需验证';
  return '未验证';
}

function statusNoticeClass(message: string) {
  return /失败|错误|无法|不支持|超时/.test(message) ? 'notice danger' : 'notice';
}

function hermesDetail(data: DashboardData | null): string {
  const version = data?.hermes?.version || '—';
  const readiness = data?.hermes?.readiness_level || (data?.hermes?.ready ? 'ready' : 'unknown');
  return `${version} / ${readiness}`;
}

function toolCenterDetail(hermes: DashboardData['hermes'] | undefined): string {
  const limitedCount = hermes?.limited_tools?.length || 0;
  if (limitedCount) return `${limitedCount} 个 Doctor 受限项`;
  if (!hermes?.ready) return 'Hermes 就绪后显示完整工具状态';
  if (!hermes.readiness_level || hermes.readiness_level === 'unknown') return '尚未完成 Doctor 分级';
  return '查看 Hermes toolset 和诊断结果';
}

function modeName(data: DashboardData | null): string {
  const current = data?.modes?.current || '';
  const item = data?.modes?.items?.find((entry) => entry.id === current);
  return item?.name || item?.label || current || '—';
}

function StatusTile({
  label,
  value,
  detail,
  active,
}: {
  label: string;
  value: string;
  detail: string;
  active: boolean;
}) {
  return (
    <article className={active ? 'status-tile active' : 'status-tile'}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function ControlHubButton({
  title,
  detail,
  action,
  primary,
  onClick,
}: {
  title: string;
  detail: string;
  action: string;
  primary?: boolean;
  onClick: () => void;
}) {
  return (
    <button className={primary ? 'control-hub-card primary' : 'control-hub-card'} type="button" onClick={onClick}>
      <span>{title}</span>
      <strong>{action}</strong>
      <small>{detail}</small>
    </button>
  );
}

function ControlHubGroup({
  title,
  detail,
  primaryAction,
  secondaryAction,
  onPrimary,
  onSecondary,
}: {
  title: string;
  detail: string;
  primaryAction: string;
  secondaryAction: string;
  onPrimary: () => void;
  onSecondary: () => void;
}) {
  return (
    <div className="control-hub-card grouped">
      <span>{title}</span>
      <strong>{detail}</strong>
      <div className="control-hub-actions">
        <button type="button" className="primary-action" onClick={onPrimary}>{primaryAction}</button>
        <button type="button" onClick={onSecondary}>{secondaryAction}</button>
      </div>
    </div>
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
  imageTestResult,
  ttsForm,
  onConfigChange,
  onTtsChange,
  onRecheck,
  onSaveConfig,
  onSaveTts,
  onTestConnection,
  onTestImageConnection,
}: {
  hermes?: DashboardData['hermes'];
  config: HermesVisualConfig | null;
  form: HermesConfigForm;
  busyAction: string;
  testResult: HermesConnectionTestResult | null;
  imageTestResult: HermesImageConnectionTestResult | null;
  ttsForm: TtsForm;
  onConfigChange: (field: keyof HermesConfigForm, value: string) => void;
  onTtsChange: (field: keyof TtsForm, value: string | boolean | number) => void;
  onRecheck: () => Promise<void>;
  onSaveConfig: () => Promise<void>;
  onSaveTts: () => Promise<void>;
  onTestConnection: () => Promise<void>;
  onTestImageConnection: () => Promise<void>;
}) {
  const busy = Boolean(busyAction);
  const providerOptions = config?.provider_options || [];
  const selectedProvider = providerOptionById(config, form.provider);
  const selectedVisionProvider = providerOptionById(config, form.vision_provider);
  const modelOptions = modelSelectOptions(form.model, selectedProvider?.models || []);
  const visionModelOptions = buildVisionModelOptions(selectedVisionProvider, form.vision_model);
  const apiKeyLabel = selectedProvider?.api_key_name || config?.api_key?.name || '';
  const apiKeyConfigured = selectedProvider?.api_key_configured ?? config?.api_key?.configured;
  const visionApiKeyLabel = selectedVisionProvider?.api_key_name || config?.vision?.api_key_name || '';
  const visionApiKeyConfigured = selectedVisionProvider?.api_key_configured ?? config?.vision?.api_key_configured;
  const connectionValidation = config?.connection_validation;
  const imageValidation = config?.image_connection_validation || config?.image_input?.validation;
  const configNotice = hermesConfigNotice(
    hermes,
    apiKeyLabel,
    Boolean(apiKeyConfigured),
    testResult,
    connectionValidation,
  );
  const imageNotice = hermesImageConnectionNotice(config?.image_input, imageTestResult, imageValidation);
  const imageInputMode = form.image_input_mode === 'text' ? 'text' : 'auto';
  const usesSeparateVision = imageInputMode === 'text';
  const ttsProvider = ttsForm.provider || 'none';
  const ttsEnabled = ttsProvider !== 'none';
  const imageTestDisabled = busy || !hermes?.command_exists;
  return (
    <div className="hermes-config-center dashboard-hermes-center">
      <InfoList rows={[
        ['安装/初始化', hermesInstallStatusLabel(hermes?.status)],
        ['基础状态', hermes?.ready ? 'Hermes 与 Yachiyo 已就绪' : '未完成'],
        ['模型连接', hermesConnectionStatusLabel(testResult, connectionValidation)],
        ['图片输入', hermesImageInputLabel(config?.image_input)],
        ['图片链路', hermesImageConnectionStatusLabel(config?.image_input, imageValidation)],
        ['Doctor 等级', hermesReadinessLevelLabel(hermes?.readiness_level)],
        ['Hermes Agent 版本', hermes?.version],
        ['平台', hermes?.platform],
        ['hermes 命令', hermes?.command_exists ? '可执行' : '未找到'],
        ['Hermes Home', hermes?.hermes_home],
        ['诊断提示', hermes?.doctor_issues_count ? `${hermes.doctor_issues_count} 项` : '无'],
      ]} />
      {configNotice ? (
        <div className={`hermes-config-alert ${configNotice.kind}`}>
          <strong>{configNotice.title}</strong>
          <span>{configNotice.detail}</span>
        </div>
      ) : null}
      {imageNotice ? (
        <div className={`hermes-config-alert ${imageNotice.kind}`}>
          <strong>{imageNotice.title}</strong>
          <span>{imageNotice.detail}</span>
        </div>
      ) : null}
      <div className="hermes-secondary-actions">
        <button
          type="button"
          className={busyAction === 'recheck' ? 'attention-action' : undefined}
          disabled={busy}
          onClick={() => void onRecheck()}
        >
          {busyAction === 'recheck' ? '检测中...' : '重新检测'}
        </button>
      </div>
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
            {modelOptions.length ? (
              <select
                id="hermes-model"
                value={form.model}
                disabled={busy}
                onChange={(event) => onConfigChange('model', event.target.value)}
              >
                {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            ) : (
              <input
                id="hermes-model"
                value={form.model}
                placeholder="输入模型名称"
                disabled={busy}
                onChange={(event) => onConfigChange('model', event.target.value)}
              />
            )}
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
          <div className="hermes-form-actions">
            <button
              type="button"
              disabled={busy || !hermes?.command_exists}
              onClick={() => void onTestConnection()}
            >
              {busyAction === 'connection-test' ? '测试中...' : '测试模型连接'}
            </button>
            <button
              type="submit"
              className="primary-action"
              disabled={busy || !hermes?.command_exists}
            >
              {busyAction === 'config-save' ? '保存中...' : '保存 Hermes 配置'}
            </button>
          </div>
        </div>
        {testResult ? <HermesConnectionResult result={testResult} /> : null}
      </form>
      <div className="capability-settings-grid">
        <form
          className="hermes-visual-config capability-config-card"
          onSubmit={(event) => {
            event.preventDefault();
            void onSaveConfig();
          }}
        >
          <div className="hermes-subsection-title">
            <strong>图片识别链路</strong>
            <span>{config?.image_input?.label || '未检测'}</span>
          </div>
          <p className="capability-note">
            默认直接把图片交给主模型。只有主模型不是多模态时，才需要单独设置图片识别模型。
          </p>
          <div className="hermes-config-form-grid compact">
            <label className="settings-field wide" htmlFor="hermes-image-input-mode">
              <span>图片输入模式</span>
              <select
                id="hermes-image-input-mode"
                value={imageInputMode}
                disabled={busy}
                onChange={(event) => onConfigChange('image_input_mode', event.target.value)}
              >
                <option value="auto">使用主模型识别图片（推荐）</option>
                <option value="text">单独设置图片识别模型</option>
              </select>
            </label>
            {usesSeparateVision ? (
              <>
                <label className="settings-field" htmlFor="hermes-vision-provider">
                  <span>图片 Provider</span>
                  <select
                    id="hermes-vision-provider"
                    value={form.vision_provider}
                    disabled={busy}
                    onChange={(event) => onConfigChange('vision_provider', event.target.value)}
                  >
                    <option value="">自动跟随主模型</option>
                    {providerOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {providerOptionLabel(option)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="settings-field" htmlFor="hermes-vision-model">
                  <span>图片模型</span>
                  {visionModelOptions.length ? (
                    <select
                      id="hermes-vision-model"
                      value={form.vision_model}
                      disabled={busy}
                      onChange={(event) => onConfigChange('vision_model', event.target.value)}
                    >
                      <option value="">自动选择</option>
                      {visionModelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
                    </select>
                  ) : (
                    <input
                      id="hermes-vision-model"
                      value={form.vision_model}
                      placeholder="留空则由 Hermes 自动选择"
                      disabled={busy}
                      onChange={(event) => onConfigChange('vision_model', event.target.value)}
                    />
                  )}
                </label>
                <label className="settings-field wide" htmlFor="hermes-vision-base-url">
                  <span>图片 Base URL</span>
                  <input
                    id="hermes-vision-base-url"
                    value={form.vision_base_url}
                    placeholder={config?.vision?.effective_base_url || '留空则跟随 provider 默认值'}
                    disabled={busy}
                    onChange={(event) => onConfigChange('vision_base_url', event.target.value)}
                  />
                </label>
                <label className="settings-field wide" htmlFor="hermes-vision-api-key">
                  <span>图片 API Key</span>
                  <input
                    id="hermes-vision-api-key"
                    type="password"
                    value={form.vision_api_key}
                    placeholder={visionApiKeyConfigured ? '已配置，留空则不修改' : visionApiKeyLabel ? `输入 ${visionApiKeyLabel}` : '留空则复用主 provider 凭据'}
                    disabled={busy || (!visionApiKeyLabel && !form.vision_provider)}
                    onChange={(event) => onConfigChange('vision_api_key', event.target.value)}
                  />
                </label>
              </>
            ) : (
              <p className="capability-note wide-form-note">
                当前未单独设置图片模型。聊天窗口会把图片直接交给主模型；如果主模型不支持图片，会在发送前给出提示并阻止粘贴。
              </p>
            )}
          </div>
          <div className="hermes-config-footer">
            <span>{usesSeparateVision ? '图片会先由独立模型识别，再把结果交给主模型。' : '主模型承担图片识别；不需要额外 vision 配置。'}</span>
            <div className="hermes-form-actions">
              <button type="submit" className="primary-action" disabled={busy || !hermes?.command_exists}>
                {busyAction === 'config-save' ? '保存中...' : '保存图片链路'}
              </button>
              <button
                type="button"
                disabled={imageTestDisabled}
                onClick={() => void onTestImageConnection()}
              >
                {busyAction === 'image-connection-test' ? '测试中...' : '测试图片链路'}
              </button>
            </div>
          </div>
          {imageTestResult ? <HermesConnectionResult result={imageTestResult} /> : null}
        </form>
        <form
          className="hermes-visual-config capability-config-card"
          onSubmit={(event) => {
            event.preventDefault();
            void onSaveTts();
          }}
        >
          <div className="hermes-subsection-title">
            <strong>TTS 播报链路</strong>
            <span>{ttsEnabled ? '已启用' : '未启用'}</span>
          </div>
          <p className="capability-note">
            Live2D 收到新回复时只播报短提醒；主动桌面观察也会按这里的提示词生成适合语音的短句。
          </p>
          <div className="hermes-config-form-grid compact">
            <label className="settings-field wide" htmlFor="tts-provider-main">
              <span>TTS Provider</span>
              <select
                id="tts-provider-main"
                value={ttsForm.provider}
                disabled={busy}
                onChange={(event) => onTtsChange('provider', event.target.value)}
              >
                <option value="none">none（关闭）</option>
                <option value="http">HTTP POST</option>
                <option value="command">本地命令</option>
              </select>
            </label>
            {ttsProvider === 'none' ? (
              <p className="capability-note wide-form-note">
                关闭后不会自动播放语音。对话文本和 Live2D 表情状态不受影响。
              </p>
            ) : null}
            {ttsProvider === 'http' ? (
              <label className="settings-field wide" htmlFor="tts-endpoint-main">
                <span>HTTP Endpoint</span>
                <input
                  id="tts-endpoint-main"
                  value={ttsForm.endpoint}
                  placeholder="http://127.0.0.1:9000/tts"
                  disabled={busy}
                  onChange={(event) => onTtsChange('endpoint', event.target.value)}
                />
              </label>
            ) : null}
            {ttsProvider === 'command' ? (
              <label className="settings-field wide" htmlFor="tts-command-main">
                <span>本地命令</span>
                <input
                  id="tts-command-main"
                  value={ttsForm.command}
                  placeholder="say {text}"
                  disabled={busy}
                  onChange={(event) => onTtsChange('command', event.target.value)}
                />
              </label>
            ) : null}
            {ttsEnabled ? (
              <>
                <label className="settings-field" htmlFor="tts-max-chars-main">
                  <span>播报最大字数</span>
                  <input
                    id="tts-max-chars-main"
                    type="number"
                    min={20}
                    max={240}
                    value={ttsForm.max_chars}
                    disabled={busy}
                    onChange={(event) => onTtsChange('max_chars', Number(event.target.value))}
                  />
                </label>
                <label className="settings-field" htmlFor="tts-timeout-main">
                  <span>超时秒</span>
                  <input
                    id="tts-timeout-main"
                    type="number"
                    min={1}
                    max={120}
                    value={ttsForm.timeout_seconds}
                    disabled={busy}
                    onChange={(event) => onTtsChange('timeout_seconds', Number(event.target.value))}
                  />
                </label>
                <label className="settings-field wide" htmlFor="tts-prompt-main">
                  <span>主动播报提示词</span>
                  <textarea
                    id="tts-prompt-main"
                    value={ttsForm.notification_prompt}
                    rows={3}
                    disabled={busy}
                    onChange={(event) => onTtsChange('notification_prompt', event.target.value)}
                  />
                </label>
              </>
            ) : null}
          </div>
          <div className="hermes-config-footer">
            <span>{ttsEnabled ? '实际播报前仍会硬性截短，避免长回复导致播放过久。' : '选择 HTTP 或本地命令后再配置播报参数。'}</span>
            <button type="submit" className="primary-action" disabled={busy}>
              {busyAction === 'tts-save' ? '保存中...' : '保存 TTS 设置'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function HermesConnectionResult({ result }: { result: HermesConnectionTestResult | HermesImageConnectionTestResult }) {
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
