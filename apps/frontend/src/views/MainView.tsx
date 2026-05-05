import { useEffect, useRef, useState } from 'react';

import { apiGet, apiPost, openAppView, openDesktopMode, quitApp } from '../lib/bridge';
import { navigateTo } from '../lib/view';
import {
  emptyTtsForm,
  formFromTtsSettings,
  ttsProviderLabel,
  type TtsForm,
  type TtsSettings,
} from '../lib/ttsSettings';

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

type SettingsData = {
  tts?: TtsSettings;
  mode_settings?: {
    live2d?: { config?: ModeProactiveSettings & { tts?: TtsSettings } };
    bubble?: { config?: ModeProactiveSettings & { tts?: TtsSettings } };
  };
};

type ModeProactiveSettings = {
  proactive_enabled?: boolean;
  proactive_desktop_watch_enabled?: boolean;
  proactive_interval_seconds?: number;
  proactive_trigger_probability?: number;
};

type ProactiveForm = {
  enabled: boolean;
  interval_seconds: string;
  trigger_probability: number;
};

type ProactiveSaveOutcome = {
  enabled: boolean;
  message: string;
};

type ProactiveTestResult = {
  ok?: boolean;
  status?: string;
  error?: string;
  message?: string;
  task_id?: string;
  mode?: string;
};

type ScreenPermissionResult = {
  ok?: boolean;
  allowed?: boolean;
  permission_denied?: boolean;
  settings_opened?: boolean;
  error?: string;
  message?: string;
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

const BACKGROUND_VALIDATION_MIN_INTERVAL_MS = 30 * 60 * 1000;
const BACKGROUND_VALIDATION_REFRESH_AFTER_MS = 12 * 60 * 60 * 1000;
const MIN_PROACTIVE_INTERVAL_SECONDS = 300;

function clampProbability(value: number): number {
  if (!Number.isFinite(value)) return 0.6;
  return Math.max(0, Math.min(1, value));
}

function normalizeProactiveInterval(value: string | number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return MIN_PROACTIVE_INTERVAL_SECONDS;
  return Math.max(MIN_PROACTIVE_INTERVAL_SECONDS, Math.min(3600, Math.round(parsed)));
}

export function MainView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [actionStatus, setActionStatus] = useState('');
  const [busyAction, setBusyAction] = useState('');
  const [hermesTestResult, setHermesTestResult] = useState<HermesConnectionTestResult | null>(null);
  const [hermesImageTestResult, setHermesImageTestResult] = useState<HermesImageConnectionTestResult | null>(null);
  const [hermesConfig, setHermesConfig] = useState<HermesVisualConfig | null>(null);
  const [configForm, setConfigForm] = useState<HermesConfigForm>(emptyHermesConfigForm());
  const [proactiveForm, setProactiveForm] = useState<ProactiveForm>(emptyProactiveForm());
  const [ttsForm, setTtsForm] = useState<TtsForm>(emptyTtsForm());
  const busyActionRef = useRef('');
  const configFormDirtyRef = useRef(false);
  const proactiveFormDirtyRef = useRef(false);
  const ttsFormDirtyRef = useRef(false);
  const hermesConfigLoadedRef = useRef(false);
  const hermesConfigLoadingRef = useRef(false);
  const settingsLoadingRef = useRef(false);
  const providerDraftsRef = useRef<Record<string, HermesProviderDraft>>({});
  const backgroundValidationRef = useRef({ connection: 0, image: 0 });
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
          if (!ttsFormDirtyRef.current || !proactiveFormDirtyRef.current) void loadSettings();
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
        void maybeRefreshValidationInBackground(result);
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
      const proactive = proactiveFromSettings(result);
      if (mountedRef.current && (options.forceFormSync || !proactiveFormDirtyRef.current)) {
        setProactiveForm(formFromProactiveSettings(proactive));
      }
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
      image_input_mode: 'text',
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
    if (
      field === 'provider'
      || field === 'model'
      || field === 'base_url'
      || field === 'image_input_mode'
      || field === 'vision_provider'
      || field === 'vision_model'
      || field === 'vision_base_url'
    ) {
      setHermesImageTestResult(null);
    }
  }

  function updateTtsField(field: keyof TtsForm, value: string | boolean | number) {
    ttsFormDirtyRef.current = true;
    setTtsForm((current) => {
      const next = { ...current, [field]: value };
      if (field === 'enabled' && value === true && next.provider === 'none') {
        next.provider = 'gpt-sovits';
      }
      return next;
    });
    if (actionStatus && /TTS|播报/.test(actionStatus)) setActionStatus('');
  }

  function updateProactiveField(field: keyof ProactiveForm, value: boolean | string | number) {
    proactiveFormDirtyRef.current = true;
    setProactiveForm((current) => ({ ...current, [field]: value }));
    if (actionStatus && /主动关怀|桌面观察/.test(actionStatus)) setActionStatus('');
  }

  function setProactiveEnabledDraft(enabled: boolean) {
    proactiveFormDirtyRef.current = true;
    setProactiveForm((current) => ({ ...current, enabled }));
  }

  async function checkScreenPermission(openSettings = true): Promise<ScreenPermissionResult> {
    return apiPost<ScreenPermissionResult>('/ui/proactive/screen-permission/check', {
      open_settings: openSettings,
    });
  }

  function screenPermissionMessage(result: ScreenPermissionResult): string {
    if (result.allowed || result.ok) return '屏幕录制权限已确认';
    if (result.permission_denied) {
      return result.settings_opened
        ? '无法启用主动关怀：尚未授予屏幕录制权限，已打开 macOS 隐私设置。请允许 Hermes-Yachiyo / Electron 或后端进程后再开启。'
        : '无法启用主动关怀：尚未授予屏幕录制权限。';
    }
    return result.error || result.message || '无法确认屏幕录制权限，主动关怀已保持关闭';
  }

  async function requestEnableProactive() {
    if (proactiveForm.enabled) return;
    const action = 'proactive-permission';
    if (!beginHermesAction(action)) return;
    setActionStatus('正在确认 macOS 屏幕录制权限...');
    try {
      const result = await checkScreenPermission(true);
      if (result.allowed || result.ok) {
        setProactiveEnabledDraft(true);
        setActionStatus('屏幕录制权限已确认；保存后会启用主动关怀');
      } else {
        setProactiveEnabledDraft(false);
        setActionStatus(screenPermissionMessage(result));
      }
    } catch (err) {
      setProactiveEnabledDraft(false);
      setActionStatus(err instanceof Error ? err.message : '无法确认屏幕录制权限，主动关怀已保持关闭');
    } finally {
      finishHermesAction(action);
    }
  }

  async function saveAndTestHermesConfig() {
    const action = 'config-save-test';
    if (!beginHermesAction(action)) return;
    setHermesTestResult(null);
    setActionStatus('正在保存 Hermes 配置...');
    try {
      await persistHermesConfigDraft('保存 Hermes 配置失败');
      setActionStatus('配置已保存，正在测试模型连接...');
      const result = await runHermesConnectionTest();
      setActionStatus(result.success ? result.message || 'Hermes 配置已保存，模型连接测试通过' : result.error || 'Hermes 模型连接测试失败');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '保存并测试 Hermes 配置失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function persistHermesConfigDraft(errorMessage: string) {
    if (!configForm.provider.trim()) throw new Error('Provider 不能为空');
    if (!configForm.model.trim()) throw new Error('模型名称不能为空');
    const result = await apiPost<{ ok?: boolean; error?: string; message?: string; configuration?: HermesVisualConfig }>('/ui/hermes/config', {
      ...configForm,
      image_input_mode: 'text',
    });
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

  async function persistProactiveSettings(): Promise<ProactiveSaveOutcome> {
    let enabled = Boolean(proactiveForm.enabled);
    let permissionFailureMessage = '';
    const interval = normalizeProactiveInterval(proactiveForm.interval_seconds);
    const triggerProbability = clampProbability(Number(proactiveForm.trigger_probability));
    setProactiveForm((current) => ({
      ...current,
      interval_seconds: String(interval),
      trigger_probability: triggerProbability,
    }));
    try {
      if (enabled) {
        setActionStatus('正在确认 macOS 屏幕录制权限...');
        const permission = await checkScreenPermission(true);
        if (!permission.allowed && !permission.ok) {
          enabled = false;
          permissionFailureMessage = screenPermissionMessage(permission);
          setProactiveEnabledDraft(false);
          setActionStatus(permissionFailureMessage);
        }
      }
      const result = await apiPost<{ ok?: boolean; error?: string; app_state?: SettingsData }>('/ui/settings', {
        changes: {
          'bubble_mode.proactive_enabled': enabled,
          'bubble_mode.proactive_desktop_watch_enabled': enabled,
          'bubble_mode.proactive_interval_seconds': interval,
          'bubble_mode.proactive_trigger_probability': triggerProbability,
          'live2d_mode.proactive_enabled': enabled,
          'live2d_mode.proactive_desktop_watch_enabled': enabled,
          'live2d_mode.proactive_interval_seconds': interval,
          'live2d_mode.proactive_trigger_probability': triggerProbability,
          'tts.enabled': Boolean(ttsForm.enabled && ttsForm.provider !== 'none'),
        },
      });
      if (result.ok === false) throw new Error(result.error || '保存主动关怀设置失败');
      proactiveFormDirtyRef.current = false;
      ttsFormDirtyRef.current = false;
      if (result.app_state) {
        setProactiveForm(formFromProactiveSettings(proactiveFromSettings(result.app_state)));
        if (result.app_state.tts) setTtsForm(formFromTtsSettings(result.app_state.tts));
      } else {
        await loadSettings({ forceFormSync: true });
      }
      return {
        enabled,
        message: enabled ? '主动关怀设置已保存' : permissionFailureMessage || '主动关怀已保持关闭；请授予屏幕录制权限后再开启',
      };
    } catch (err) {
      throw err instanceof Error ? err : new Error('保存主动关怀设置失败');
    }
  }

  async function saveProactiveSettings() {
    const action = 'proactive-save';
    if (!beginHermesAction(action)) return;
    setActionStatus('正在保存主动关怀设置...');
    try {
      const outcome = await persistProactiveSettings();
      setActionStatus(outcome.message);
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '保存主动关怀设置失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function saveAndTestProactiveNow() {
    const action = 'proactive-test';
    if (!beginHermesAction(action)) return;
    setActionStatus('正在保存主动关怀设置...');
    try {
      const outcome = await persistProactiveSettings();
      if (!outcome.enabled) {
        setActionStatus(outcome.message);
        return;
      }
      setActionStatus('正在立即触发主动桌面观察...');
      const result = await apiPost<ProactiveTestResult>('/ui/proactive/test', {
        mode: data?.modes?.current || 'bubble',
      });
      if (result.ok === false || result.status === 'blocked' || result.status === 'failed') {
        throw new Error(result.error || result.message || '主动关怀测试触发失败');
      }
      setActionStatus(result.message || '已立即安排主动桌面观察；稍后可在对话窗口查看结果');
      await refreshDashboardData();
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '主动关怀测试触发失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function runHermesConnectionTest() {
    const result = await apiPost<HermesConnectionTestResult>('/ui/hermes/connection-test');
    setHermesTestResult(result);
    if (result.connection_validation) {
      setHermesConfig((current) => (
        current ? { ...current, connection_validation: result.connection_validation } : current
      ));
    }
    await refreshDashboardData();
    await loadHermesConfig();
    return result;
  }

  async function saveAndTestHermesImageConnection() {
    const action = 'image-save-test';
    if (!beginHermesAction(action)) return;
    setHermesImageTestResult(null);
    setActionStatus('正在保存图片链路配置...');
    try {
      await persistHermesConfigDraft('保存图片链路配置失败');
      setActionStatus('图片链路配置已保存，正在测试...');
      const result = await runHermesImageConnectionTest();
      setActionStatus(result.success ? result.message || '图片链路配置已保存，测试通过' : result.error || 'Yachiyo 图片链路测试失败');
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : '保存并测试图片链路失败');
    } finally {
      finishHermesAction(action);
    }
  }

  async function runHermesImageConnectionTest() {
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
    await loadHermesConfig();
    return result;
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

  async function maybeRefreshValidationInBackground(config: HermesVisualConfig) {
    if (!mountedRef.current || busyActionRef.current || configFormDirtyRef.current) return;
    const now = Date.now();
    const connectionAge = validationAgeMs(config.connection_validation);
    if (
      config.connection_validation?.verified
      && connectionAge !== null
      && connectionAge > BACKGROUND_VALIDATION_REFRESH_AFTER_MS
      && now - backgroundValidationRef.current.connection > BACKGROUND_VALIDATION_MIN_INTERVAL_MS
    ) {
      backgroundValidationRef.current.connection = now;
      try {
        const result = await apiPost<HermesConnectionTestResult>('/ui/hermes/connection-test');
        if (result.connection_validation && mountedRef.current) {
          setHermesConfig((current) => (
            current ? { ...current, connection_validation: result.connection_validation } : current
          ));
        }
      } catch {
        // Silent refresh keeps cached checks fresh without interrupting the user.
      }
    }

    const imageInput = config.image_input;
    const imageValidation = config.image_connection_validation || imageInput?.validation;
    const imageAge = validationAgeMs(imageValidation);
    if (
      imageInput?.can_attach_images
      && imageValidation?.verified
      && imageAge !== null
      && imageAge > BACKGROUND_VALIDATION_REFRESH_AFTER_MS
      && now - backgroundValidationRef.current.image > BACKGROUND_VALIDATION_MIN_INTERVAL_MS
    ) {
      backgroundValidationRef.current.image = now;
      try {
        const result = await apiPost<HermesImageConnectionTestResult>('/ui/hermes/image-connection-test');
        if ((result.image_connection_validation || result.image_input) && mountedRef.current) {
          setHermesConfig((current) => {
            if (!current) return current;
            const validation = result.image_connection_validation || current.image_connection_validation;
            return {
              ...current,
              image_input: {
                ...(current.image_input || {}),
                ...(result.image_input || {}),
                validation,
              },
              image_connection_validation: validation,
            };
          });
        }
      } catch {
        // Silent refresh keeps cached checks fresh without interrupting the user.
      }
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
              proactiveForm={proactiveForm}
              ttsForm={ttsForm}
              onConfigChange={updateHermesConfigField}
              onProactiveChange={updateProactiveField}
              onProactiveEnableRequest={requestEnableProactive}
              onTtsChange={updateTtsField}
              onRecheck={recheckHermes}
              onSaveConfig={saveAndTestHermesConfig}
              onSaveImageConfig={saveAndTestHermesImageConnection}
              onSaveProactive={saveProactiveSettings}
              onTestProactive={saveAndTestProactiveNow}
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
    image_input_mode: 'text',
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
    image_input_mode: 'text',
    vision_provider: config?.vision?.provider || '',
    vision_model: config?.vision?.configured ? (config?.vision?.effective_model || config?.vision?.model || '') : (config?.vision?.model || ''),
    vision_base_url: config?.vision?.base_url || '',
    vision_api_key: '',
  };
}

function emptyProactiveForm(): ProactiveForm {
  return {
    enabled: false,
    interval_seconds: '300',
    trigger_probability: 0.6,
  };
}

function proactiveFromSettings(settings: SettingsData | null): ModeProactiveSettings | undefined {
  const bubble = settings?.mode_settings?.bubble?.config;
  const live2d = settings?.mode_settings?.live2d?.config;
  if (!bubble && !live2d) return undefined;
  return {
    proactive_enabled: Boolean(bubble?.proactive_enabled || live2d?.proactive_enabled),
    proactive_desktop_watch_enabled: Boolean(
      bubble?.proactive_desktop_watch_enabled || live2d?.proactive_desktop_watch_enabled,
    ),
    proactive_interval_seconds: Number(
      live2d?.proactive_interval_seconds
      || bubble?.proactive_interval_seconds
      || 300,
    ),
    proactive_trigger_probability: Number(
      live2d?.proactive_trigger_probability
      ?? bubble?.proactive_trigger_probability
      ?? settings?.tts?.trigger_probability
      ?? 0.6,
    ),
  };
}

function formFromProactiveSettings(settings: ModeProactiveSettings | undefined): ProactiveForm {
  const enabled = Boolean(settings?.proactive_enabled && settings?.proactive_desktop_watch_enabled);
  return {
    enabled,
    interval_seconds: String(normalizeProactiveInterval(settings?.proactive_interval_seconds || 300)),
    trigger_probability: clampProbability(Number(settings?.proactive_trigger_probability ?? 0.6)),
  };
}

function ttsFromSettings(settings: SettingsData | null): TtsSettings | undefined {
  return settings?.tts || settings?.mode_settings?.live2d?.config?.tts || settings?.mode_settings?.bubble?.config?.tts;
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
      detail: '检测到 provider、模型或 Base URL 变化，请保存并测试配置。',
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
    detail: '基础状态 ready 只代表 Hermes 命令、setup 和 Yachiyo 工作空间通过检查；API Key 是否能调用模型需要点击“保存并测试配置”。',
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
      detail: testResult.error || '请检查 Yachiyo vision provider、Base URL 和 API Key。',
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
      detail: '检测到 provider、模型或 Base URL 变化，请保存并测试图片链路。',
    };
  }
  if (imageInput.requires_vision_pipeline) {
    return {
      kind: 'warn',
      title: '图片需要单独验证',
      detail: '当前配置会先用 Yachiyo vision 识图，再把分析结果交给 Hermes 主模型；主模型测试只验证文字请求。',
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
  const readiness = data?.hermes?.readiness_level || (data?.hermes?.ready ? 'basic_ready' : 'unknown');
  return `${version} / ${hermesReadinessLevelLabel(readiness)}`;
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
  proactiveForm,
  ttsForm,
  onConfigChange,
  onProactiveChange,
  onProactiveEnableRequest,
  onTtsChange,
  onRecheck,
  onSaveConfig,
  onSaveImageConfig,
  onSaveProactive,
  onTestProactive,
}: {
  hermes?: DashboardData['hermes'];
  config: HermesVisualConfig | null;
  form: HermesConfigForm;
  busyAction: string;
  testResult: HermesConnectionTestResult | null;
  imageTestResult: HermesImageConnectionTestResult | null;
  proactiveForm: ProactiveForm;
  ttsForm: TtsForm;
  onConfigChange: (field: keyof HermesConfigForm, value: string) => void;
  onProactiveChange: (field: keyof ProactiveForm, value: boolean | string | number) => void;
  onProactiveEnableRequest: () => Promise<void>;
  onTtsChange: (field: keyof TtsForm, value: string | boolean | number) => void;
  onRecheck: () => Promise<void>;
  onSaveConfig: () => Promise<void>;
  onSaveImageConfig: () => Promise<void>;
  onSaveProactive: () => Promise<void>;
  onTestProactive: () => Promise<void>;
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
  const ttsProvider = ttsForm.provider || 'none';
  const ttsReady = Boolean(ttsForm.enabled && ttsProvider !== 'none');
  const imageSaveTestDisabled = busy || !hermes?.command_exists;
  const updateProactiveIntervalDraft = (value: string) => {
    onProactiveChange('interval_seconds', value.replace(/[^\d]/g, ''));
  };
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
          className={busyAction === 'recheck' ? 'attention-action loading-button' : undefined}
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
              type="submit"
              className={busyAction === 'config-save-test' ? 'primary-action loading-button' : 'primary-action'}
              disabled={busy || !hermes?.command_exists}
            >
              {busyAction === 'config-save-test' ? '保存并测试中...' : '保存并测试配置'}
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
            void onSaveImageConfig();
          }}
        >
          <div className="hermes-subsection-title">
            <strong>图片识别链路</strong>
            <span>{config?.image_input?.label || '未检测'}</span>
          </div>
          <p className="capability-note">
            图片一律先由 Yachiyo vision 预分析，再把文本结果交给 Hermes 主模型；不再走 Hermes 原生图片输入或 Hermes vision 工具。
          </p>
          <div className="hermes-config-form-grid compact">
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
                  placeholder="留空则由 Yachiyo 自动选择"
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
          </div>
          <div className="hermes-config-footer">
            <span>图片会先由 Yachiyo vision 识别，再把结果交给主模型。</span>
            <div className="hermes-form-actions">
              <button
                type="submit"
                className={busyAction === 'image-save-test' ? 'primary-action loading-button' : 'primary-action'}
                disabled={imageSaveTestDisabled}
              >
                {busyAction === 'image-save-test' ? '保存并测试中...' : '保存并测试图片链路'}
              </button>
            </div>
          </div>
          {imageTestResult ? <HermesConnectionResult result={imageTestResult} /> : null}
        </form>
        <form
          className="hermes-visual-config capability-config-card"
          onSubmit={(event) => {
            event.preventDefault();
            void onSaveProactive();
          }}
        >
          <div className="hermes-subsection-title">
            <strong>主动关怀</strong>
            <span>{proactiveForm.enabled ? '已启用' : '未启用'}</span>
          </div>
          <p className="capability-note">
            主动关怀会定期读取桌面截图并用视觉模型判断是否需要搭话；Bubble 和 Live2D 共用这一套设置。
          </p>
          <div className="hermes-config-form-grid proactive-settings-grid">
            <label className="settings-check wide" htmlFor="proactive-enabled-main">
              <input
                id="proactive-enabled-main"
                type="checkbox"
                checked={proactiveForm.enabled}
                disabled={busy}
                onChange={(event) => {
                  if (event.target.checked) void onProactiveEnableRequest();
                  else onProactiveChange('enabled', false);
                }}
              />
              <span>启用主动桌面观察</span>
            </label>
            <label className="settings-field wide" htmlFor="proactive-interval-main">
              <span>观察间隔秒</span>
              <input
                id="proactive-interval-main"
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="off"
                value={proactiveForm.interval_seconds}
                disabled={busy || !proactiveForm.enabled}
                onChange={(event) => updateProactiveIntervalDraft(event.target.value)}
                onBlur={(event) => onProactiveChange('interval_seconds', String(normalizeProactiveInterval(event.target.value)))}
              />
              <small>启动或重新开启后先等待完整间隔；失焦或保存时小于 300 秒会自动调整到 300 秒。</small>
            </label>
            <label className="settings-field wide" htmlFor="proactive-trigger-probability-main">
              <span>主动关怀触发概率</span>
              <input
                id="proactive-trigger-probability-main"
                type="number"
                min={0}
                max={1}
                step="0.05"
                value={proactiveForm.trigger_probability}
                disabled={busy || !proactiveForm.enabled}
                onChange={(event) => onProactiveChange('trigger_probability', clampProbability(Number(event.target.value)))}
              />
              <small>这个概率控制整条主动关怀链路是否触发：0 到点也不截图，1 每次到点都截图识图。</small>
            </label>
            <label className="settings-check wide" htmlFor="proactive-tts-enabled-main">
              <input
                id="proactive-tts-enabled-main"
                type="checkbox"
                checked={ttsReady}
                disabled={busy || ttsProvider === 'none'}
                onChange={(event) => onTtsChange('enabled', event.target.checked)}
              />
              <span>启用 TTS 语音</span>
            </label>
            <p className="capability-note wide-form-note">
              {ttsProvider === 'none'
                ? '未配置语音 Provider。主动关怀会先以文本方式提示；需要语音时进入设置页选择 GPT-SoVITS、HTTP 或本地命令。'
                : `${ttsReady ? '语音已启用' : '语音已关闭'}，当前 Provider：${ttsProviderLabel(ttsProvider)}。关闭语音不会清空已填写的 GPT-SoVITS 路径和参数。`}
            </p>
          </div>
          <div className="hermes-config-footer">
            <span>{proactiveForm.enabled ? '保存后会同步到 Bubble 和 Live2D；未开启语音时会以文本提醒。' : '关闭后不会创建主动桌面观察任务。'}</span>
            <div className="hermes-form-actions">
              <button type="button" disabled={busy} onClick={() => navigateTo('proactive-tts')}>
                {ttsProvider === 'none' ? '启用并配置语音' : '配置语音'}
              </button>
              <button
                type="button"
                className={busyAction === 'proactive-test' ? 'loading-button' : ''}
                disabled={busy || !proactiveForm.enabled}
                onClick={() => void onTestProactive()}
              >
                {busyAction === 'proactive-test' ? '测试中...' : '保存并立即测试'}
              </button>
              <button
                type="submit"
                className={busyAction === 'proactive-save' ? 'primary-action loading-button' : 'primary-action'}
                disabled={busy}
              >
                {busyAction === 'proactive-save' ? '保存中...' : '保存主动关怀设置'}
              </button>
            </div>
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

function validationAgeMs(validation?: Pick<HermesConnectionValidation, 'verified_at' | 'tested_at'>): number | null {
  const value = validation?.verified_at || validation?.tested_at;
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return Date.now() - date.getTime();
}

function formatUptime(seconds?: number) {
  if (typeof seconds !== 'number') return '读取中';
  if (seconds < 60) return `${Math.floor(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 小时 ${minutes} 分钟`;
}
