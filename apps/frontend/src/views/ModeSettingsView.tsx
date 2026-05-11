import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
  type AppUpdateCheckResult,
  type AppUpdateDownloadResult,
  type AppUpdateDownloadProgress,
  type AppUpdateInfo,
  type ReleaseChangelog,
  type ReleaseChangelogCommit,
  apiGet,
  apiPatch,
  apiPost,
  checkAppUpdate,
  chooseLive2DArchive,
  chooseLive2DModelDirectory,
  downloadAppUpdate,
  getAppUpdateInfo,
  hasDesktopFilePicker,
  installAppUpdate,
  onAppUpdateDownloadProgress,
  openExternalUrl,
  openDesktopMode,
  openPath,
  removeAppBundleAndQuit,
  restartDesktopBridge,
} from '../lib/bridge';
import { currentParam, navigateTo } from '../lib/view';

type SettingsPayload = {
  mode?: { id?: string; name?: string; icon?: string; settings_title?: string; settings_description?: string };
  settings?: { summary?: string; config?: ModeConfig };
};

type ModeConfig = Record<string, unknown>;
type ModeFormValue = string | boolean;
type ModeForm = Record<string, ModeFormValue>;
type ModeParsedValue = string | number | boolean | Record<string, string>;
type ModeFieldKind = 'text' | 'textarea' | 'number' | 'checkbox' | 'select' | 'percent' | 'expressionRules';
type ModeFieldOption = { value: string; label: string };
type Live2DExpressionItem = { name?: string; file?: string };
type ModeFieldSpec = {
  key: string;
  sourceKey?: string;
  label: string;
  kind: ModeFieldKind;
  min?: number;
  max?: number;
  step?: string;
  integer?: boolean;
  wide?: boolean;
  options?: ModeFieldOption[];
  allowCustom?: boolean;
  expressions?: Live2DExpressionItem[];
};
type ModeFieldSection = { title: string; note?: string; fields: ModeFieldSpec[] };
type SettingsUpdateResult = {
  ok?: boolean;
  error?: string;
  errors?: string[];
  effects?: {
    hint?: string;
    has_restart_mode?: boolean;
    has_restart_bridge?: boolean;
    has_restart_app?: boolean;
  };
  mode_switch_scheduled?: boolean;
  target_display_mode?: string;
  redirect?: {
    view?: string;
    mode?: string;
    reason?: string;
  };
  restart_scheduled?: boolean;
};
type Live2DResourceActionResult = SettingsUpdateResult & {
  message?: string;
  draft_changes?: Record<string, unknown>;
  model_path_display?: string;
};

type GeneralSettingsPayload = {
  app?: { version?: string; log_level?: string; start_minimized?: boolean; tray_enabled?: boolean };
  assistant?: { persona_prompt?: string; user_address?: string };
  backup?: { auto_cleanup_enabled?: boolean; retention_count?: number };
  bridge?: {
    state?: string;
    enabled?: boolean;
    host?: string;
    port?: number;
    url?: string;
    config_dirty?: boolean;
    drift_details?: string[];
    boot_config?: { enabled?: boolean; host?: string; port?: number; url?: string };
  };
  display?: { current_mode?: string; available_modes?: Array<{ id: string; name?: string; label?: string; description?: string }> };
  hermes?: {
    status?: string;
    version?: string;
    platform?: string;
    ready?: boolean;
    readiness_level?: string;
    command_exists?: boolean;
    hermes_home?: string;
    limited_tools?: string[];
    doctor_issues_count?: number;
  };
  integrations?: { astrbot?: StatusRecord; hapi?: StatusRecord };
  mode_settings?: Record<string, { id?: string; title?: string; summary?: string; config?: ModeConfig }>;
  workspace?: { path?: string; initialized?: boolean; created_at?: string; dirs?: Record<string, string> };
};

type AssistantProfilePayload = {
  ok?: boolean;
  persona_prompt?: string;
  user_address?: string;
  memory_enabled?: boolean;
  memory_scope?: string;
  prompt_order?: string[];
  message?: string;
};

type StatusRecord = {
  status?: string;
  label?: string;
  description?: string;
  blockers?: string[];
};

type BackupInfo = {
  path?: string;
  display_path?: string;
  created_at?: string;
  size_display?: string;
  valid?: boolean;
  error?: string;
};

type BackupStatus = {
  ok?: boolean;
  error?: string;
  backups?: BackupInfo[];
  latest?: BackupInfo | null;
  has_backup?: boolean;
  count?: number;
  total_size_display?: string;
};

type UninstallTarget = {
  id?: string;
  label?: string;
  display_path?: string;
  path?: string;
  exists?: boolean;
  removable?: boolean;
  reason?: string;
};

type UninstallPlan = {
  scope?: string;
  keep_config_snapshot?: boolean;
  confirm_phrase?: string;
  existing_count?: number;
  removable_count?: number;
  targets?: UninstallTarget[];
  warnings?: string[];
  backup?: { enabled?: boolean; note?: string; backup_root_display?: string };
};

type UninstallPreviewResult = { ok?: boolean; error?: string; plan?: UninstallPlan };
const LIVE2D_ACTIVATION_DRAFT_KEY = 'hermes-yachiyo-live2d-activation-draft';

type GeneralSettingsForm = {
  persona_prompt: string;
  user_address: string;
  bridge_enabled: boolean;
  bridge_host: string;
  bridge_port: string;
  display_mode: string;
  tray_enabled: boolean;
  backup_auto_cleanup_enabled: boolean;
  backup_retention_count: string;
};

export function ModeSettingsView() {
  const mode = currentParam('mode');
  if (mode === 'system') return <SystemSettingsView />;
  return mode ? <SpecificModeSettingsView mode={mode} /> : <ReferenceSettingsHome />;
}

function ReferenceSettingsHome() {
  const [payload, setPayload] = useState<GeneralSettingsPayload | null>(null);
  const [assistantProfile, setAssistantProfile] = useState<AssistantProfilePayload | null>(null);
  const [assistantDraft, setAssistantDraft] = useState({ user_address: '', persona_prompt: '' });
  const [assistantSaving, setAssistantSaving] = useState(false);
  const [assistantStatus, setAssistantStatus] = useState('');
  const [hermesConfig, setHermesConfig] = useState<{
    model?: { provider?: string };
    provider_options?: Array<{ id: string; label?: string; api_key_configured?: boolean; auth_type?: string }>;
    api_key?: { configured?: boolean; display?: string };
  } | null>(null);
  const [startupEnabled, setStartupEnabled] = useState(true);
  const [animationsEnabled, setAnimationsEnabled] = useState(true);
  const [language, setLanguage] = useState('zh-CN');
  const [theme, setTheme] = useState('dark');
  const [fontSize, setFontSize] = useState('normal');
  const [providerDraft, setProviderDraft] = useState('');
  const [connectionTestResult, setConnectionTestResult] = useState<{ success?: boolean; ok?: boolean; error?: string; message?: string } | null>(null);
  const [connectionTesting, setConnectionTesting] = useState(false);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateResult, setUpdateResult] = useState<{ checked?: boolean; update_available?: boolean; reason?: string } | null>(null);

  const FALLBACK_PROVIDER_OPTIONS: Array<{ id: string; label: string; api_key_configured?: boolean }> = [
    { id: 'openai', label: 'OpenAI' },
    { id: 'anthropic', label: 'Anthropic' },
    { id: 'local', label: '本地模型' },
  ];

  useEffect(() => {
    let disposed = false;
    void Promise.allSettled([
      apiGet<GeneralSettingsPayload>('/ui/settings'),
      apiGet<{ model?: { provider?: string }; provider_options?: Array<{ id: string; label?: string; api_key_configured?: boolean; auth_type?: string }>; api_key?: { configured?: boolean; display?: string } }>('/ui/hermes/config'),
      apiGet<AssistantProfilePayload>('/assistant/profile'),
    ]).then(([settingsResult, configResult, profileResult]) => {
      if (disposed) return;
      if (settingsResult.status === 'fulfilled') setPayload(settingsResult.value);
      if (configResult.status === 'fulfilled') {
        setHermesConfig(configResult.value);
        setProviderDraft(configResult.value.model?.provider || '');
      }
      if (profileResult.status === 'fulfilled') {
        setAssistantProfile(profileResult.value);
        setAssistantDraft({
          user_address: profileResult.value.user_address || '',
          persona_prompt: profileResult.value.persona_prompt || '',
        });
      }
    });
    return () => { disposed = true; };
  }, []);

  async function saveAssistantProfile() {
    if (assistantSaving) return;
    setAssistantSaving(true);
    setAssistantStatus('正在保存助手资料...');
    try {
      const result = await apiPatch<AssistantProfilePayload>('/assistant/profile', {
        user_address: assistantDraft.user_address,
        persona_prompt: assistantDraft.persona_prompt,
      });
      if (result.ok === false) throw new Error(result.message || '保存助手资料失败');
      setAssistantProfile(result);
      setAssistantDraft({
        user_address: result.user_address || '',
        persona_prompt: result.persona_prompt || '',
      });
      setPayload((current) => current ? {
        ...current,
        assistant: {
          ...(current.assistant || {}),
          user_address: result.user_address || '',
          persona_prompt: result.persona_prompt || '',
        },
      } : current);
      setAssistantStatus(result.message || '助手资料已保存');
    } catch (err) {
      setAssistantStatus(err instanceof Error ? err.message : '保存助手资料失败');
    } finally {
      setAssistantSaving(false);
    }
  }

  async function runConnectionTest() {
    if (connectionTesting) return;
    setConnectionTesting(true);
    setConnectionTestResult(null);
    try {
      const result = await apiPost<{ success?: boolean; ok?: boolean; error?: string; message?: string }>('/ui/hermes/connection-test', {});
      setConnectionTestResult(result);
    } catch (err) {
      setConnectionTestResult({ success: false, error: err instanceof Error ? err.message : '连接失败，请检查模型配置' });
    } finally {
      setConnectionTesting(false);
    }
  }

  async function runUpdateCheck() {
    if (updateChecking) return;
    setUpdateChecking(true);
    setUpdateResult(null);
    try {
      const result = await checkAppUpdate();
      if (result.ok === false || result.error) {
        setUpdateResult({ checked: true, update_available: false, reason: result.error || result.reason || '当前环境不支持应用更新' });
      } else {
        setUpdateResult({ checked: true, update_available: result.update_available, reason: result.reason });
      }
    } catch (err) {
      setUpdateResult({ checked: true, update_available: false, reason: err instanceof Error ? err.message : '检查更新失败' });
    } finally {
      setUpdateChecking(false);
    }
  }

  const appVersion = payload?.app?.version || '0.1.0';
  const trayEnabled = payload?.app?.tray_enabled !== false;
  const providerOptions = hermesConfig?.provider_options?.length ? hermesConfig.provider_options : FALLBACK_PROVIDER_OPTIONS;
  const realProvider = hermesConfig?.model?.provider || '';
  const currentProvider = providerDraft || realProvider || providerOptions[0]?.id || 'openai';
  const currentProviderOption = providerOptions.find((opt) => opt.id === currentProvider);
  const apiKeyConfigured = currentProviderOption?.api_key_configured ?? hermesConfig?.api_key?.configured ?? false;
  const apiKeyDisplay = hermesConfig?.api_key?.display || '';
  const providerDraftDirty = providerDraft && realProvider && providerDraft !== realProvider;

  const connectionTestOk = connectionTestResult?.success ?? connectionTestResult?.ok;
  const connectionTestMessage = connectionTestResult?.error || connectionTestResult?.message || '连接失败，请检查模型配置';

  const updateDescription = updateResult?.checked
    ? (updateResult.update_available ? (updateResult.reason || '发现可用更新') : (updateResult.reason || '当前已是最新版本'))
    : `Hermes Yachiyo v${appVersion}`;

  return (
    <main className="app-shell settings-page">
      <div className="settings-page-header">
        <div className="settings-page-title">设置</div>
        <div className="settings-page-subtitle">配置 Hermes Yachiyo 的各项参数</div>
      </div>

      <SettingsSection title="通用">
        <SettingsItem label="开机自启" description="系统启动时自动运行 Hermes Yachiyo">
          <SettingsToggle checked={startupEnabled} onChange={setStartupEnabled} />
        </SettingsItem>
        <SettingsItem label="最小化到托盘" description={trayEnabled ? '已启用，前往系统设置可修改' : '已禁用，前往系统设置可修改'}>
          <SettingsToggle checked={trayEnabled} onChange={() => navigateTo('settings', { mode: 'system' })} />
        </SettingsItem>
        <SettingsItem label="语言" description="界面显示语言">
          <select className="settings-select" value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="zh-CN">简体中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
          </select>
        </SettingsItem>
      </SettingsSection>

      <SettingsSection title="外观">
        <SettingsItem label="主题" description="选择界面主题风格">
          <select className="settings-select" value={theme} onChange={(e) => setTheme(e.target.value)}>
            <option value="dark">月夜深蓝</option>
            <option value="light">极简白</option>
            <option value="system">跟随系统</option>
          </select>
        </SettingsItem>
        <SettingsItem label="动画效果" description="启用粒子、流光、呼吸等动画">
          <SettingsToggle checked={animationsEnabled} onChange={setAnimationsEnabled} />
        </SettingsItem>
        <SettingsItem label="字体大小" description="调整界面文字大小">
          <select className="settings-select" value={fontSize} onChange={(e) => setFontSize(e.target.value)}>
            <option value="small">小</option>
            <option value="normal">标准</option>
            <option value="large">大</option>
          </select>
        </SettingsItem>
      </SettingsSection>

      <SettingsSection title="助手与 Prompt">
        <SettingsItem
          label="称呼"
          description="写入 /assistant/profile 的 user_address，系统设置页会同步显示"
        >
          <input
            className="settings-input"
            value={assistantDraft.user_address}
            maxLength={80}
            placeholder="例如：彩叶"
            disabled={assistantSaving}
            onChange={(event) => {
              setAssistantDraft((current) => ({ ...current, user_address: event.target.value }));
              if (assistantStatus) setAssistantStatus('');
            }}
          />
        </SettingsItem>
        <SettingsItem
          label="人格 Prompt"
          description="共享助手资料，不改变后端 executor 注入逻辑"
        >
          <textarea
            className="settings-textarea compact"
            value={assistantDraft.persona_prompt}
            maxLength={4000}
            rows={4}
            placeholder="输入八千代的人格、语气和边界设定"
            disabled={assistantSaving}
            onChange={(event) => {
              setAssistantDraft((current) => ({ ...current, persona_prompt: event.target.value }));
              if (assistantStatus) setAssistantStatus('');
            }}
          />
        </SettingsItem>
        <SettingsItem
          label="Prompt 顺序"
          description={(assistantProfile?.prompt_order || []).join(' → ') || 'persona → user_address → relevant_memory → current_session → request'}
        >
          <SettingsActionButton
            loading={assistantSaving}
            onClick={() => void saveAssistantProfile()}
          >
            {assistantSaving ? '保存中…' : '保存'}
          </SettingsActionButton>
        </SettingsItem>
        <SettingsItem
          label="记忆范围"
          description={`${assistantProfile?.memory_enabled ? '已启用' : '暂未启用'} · ${assistantProfile?.memory_scope || 'local_only'}`}
        >
          <span className={`status-pill ${/失败|错误/.test(assistantStatus) ? 'warn' : assistantStatus ? 'ok' : 'warn'}`}>
            {assistantStatus || '读取自 Bridge'}
          </span>
        </SettingsItem>
      </SettingsSection>

      <SettingsSection title="模型">
        <SettingsItem label="模型提供商" description={providerDraftDirty ? '已切换，前往模型配置可保存' : '选择 AI 模型服务'}>
          <select className="settings-select" value={currentProvider} onChange={(e) => setProviderDraft(e.target.value)}>
            {providerOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>{opt.label || opt.id}</option>
            ))}
          </select>
        </SettingsItem>
        <SettingsItem label="API Key" description={apiKeyConfigured ? `已配置${apiKeyDisplay ? `：${apiKeyDisplay}` : ''}` : '未配置，前往模型配置可设置'}>
          <SettingsActionButton onClick={() => navigateTo('provider')}>{apiKeyConfigured ? '查看' : '配置'}</SettingsActionButton>
        </SettingsItem>
        <SettingsItem
          label="连接测试"
          description={connectionTestResult ? (connectionTestOk ? '连接正常' : `连接失败：${connectionTestMessage}`) : '测试模型服务连接状态'}
        >
          <SettingsActionButton
            loading={connectionTesting}
            onClick={() => void runConnectionTest()}
          >
            {connectionTesting ? '测试中…' : '测试连接'}
          </SettingsActionButton>
        </SettingsItem>
      </SettingsSection>

      <SettingsSection title="关于">
        <SettingsItem label="版本" description={updateDescription}>
          <SettingsActionButton
            loading={updateChecking}
            onClick={() => void runUpdateCheck()}
          >
            {updateChecking ? '检查中…' : updateResult?.update_available ? '前往更新' : '检查更新'}
          </SettingsActionButton>
        </SettingsItem>
        <SettingsItem label="项目主页" description="github.com/kuguya-AI-app-develop/Hermes-Yachiyo">
          <SettingsActionButton onClick={() => void openExternalUrl('https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo')}>打开</SettingsActionButton>
        </SettingsItem>
      </SettingsSection>
    </main>
  );
}

function SpecificModeSettingsView({ mode }: { mode: string }) {
  const [activationPending, setActivationPending] = useState(
    mode === 'live2d'
      && (
        currentParam('reason') === 'live2d-resource-required'
        || window.sessionStorage.getItem(LIVE2D_ACTIVATION_DRAFT_KEY) === '1'
      ),
  );
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [form, setForm] = useState<ModeForm>({});
  const [manualModelPath, setManualModelPath] = useState('');
  const [manualArchivePath, setManualArchivePath] = useState('~/Downloads/hermes-yachiyo-live2d-yachiyo-20260423.zip');
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);

  const sections = useMemo(() => modeFieldSections(mode, payload), [mode, payload]);
  const specs = useMemo(() => sections.flatMap((section) => section.fields), [sections]);
  const pendingCount = useMemo(() => countModePendingChanges(payload, form, specs), [payload, form, specs]);
  const hasChanges = pendingCount > 0 || activationPending;
  const desktopFilePickerAvailable = hasDesktopFilePicker();

  useEffect(() => {
    let disposed = false;
    apiGet<SettingsPayload>(`/ui/modes/${mode}/settings`)
      .then((data) => {
        if (!disposed) {
          setPayload(data);
          setForm(formFromModeSettings(data, modeFieldSpecs(mode)));
        }
      })
      .catch((err) => {
        if (!disposed) setStatus(err instanceof Error ? err.message : '读取设置失败');
      });
    return () => {
      disposed = true;
    };
  }, [mode]);

  function updateField(key: string, value: ModeFormValue) {
    setForm((current) => nextModeFormValue(current, key, value));
    if (status && status !== '保存中…') setStatus('');
  }

  async function submitModeSettings(event: FormEvent) {
    event.preventDefault();
    if (!payload || saving) return;
    const validationError = validateModeForm(form, specs);
    if (validationError) {
      setStatus(validationError);
      return;
    }
    const nextChanges = buildModeSettingsChanges(payload, form, specs);
    if (shouldActivateLive2DAfterSave(mode, nextChanges, activationPending)) {
      nextChanges.display_mode = 'live2d';
    }
    if (!Object.keys(nextChanges).length) {
      setStatus('没有待保存的更改');
      return;
    }
    setSaving(true);
    setStatus('保存中…');
    try {
      const result = await apiPost<SettingsUpdateResult>('/ui/settings', { changes: nextChanges });
      if (result.ok === false) {
        if (result.redirect?.view === 'settings' && result.redirect.mode) {
          window.setTimeout(() => navigateTo('settings', { mode: result.redirect?.mode || '', reason: result.redirect?.reason || '' }), 350);
        }
        throw new Error(result.error || result.errors?.join('；') || '保存失败');
      }
      const data = await apiGet<SettingsPayload>(`/ui/modes/${mode}/settings`);
      setPayload(data);
      setForm(formFromModeSettings(data, specs));
      const hint = result.effects?.hint ? `，${result.effects.hint}` : '';
      if (result.effects?.has_restart_mode) {
        const targetMode = String(result.target_display_mode || nextChanges.display_mode || mode);
        await openDesktopMode(targetMode);
        setActivationPending(false);
        window.sessionStorage.removeItem(LIVE2D_ACTIVATION_DRAFT_KEY);
        setStatus(`已保存，并已重新打开 ${modeLabel(targetMode)} 表现态`);
      } else {
        setActivationPending(false);
        window.sessionStorage.removeItem(LIVE2D_ACTIVATION_DRAFT_KEY);
        setStatus(result.restart_scheduled ? '已保存，正在重启应用…' : `已保存${hint}`);
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  function resetDraft() {
    if (!payload) return;
    setForm(formFromModeSettings(payload, specs));
    setActivationPending(false);
    window.sessionStorage.removeItem(LIVE2D_ACTIVATION_DRAFT_KEY);
    setStatus('已丢弃未保存的修改');
  }

  function applyLive2DResourceDraft(result: Live2DResourceActionResult) {
    if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '资源操作失败');
    const nextPath = result.draft_changes?.['live2d_mode.model_path'];
    if (typeof nextPath === 'string') {
      setForm((current) => ({ ...current, 'live2d_mode.model_path': nextPath }));
    }
    const displayPath = result.model_path_display ? `：${result.model_path_display}` : '';
    setStatus(`${result.message || '资源操作完成，等待保存更改'}${displayPath}`);
  }

  async function chooseLive2DModelPath() {
    if (mode !== 'live2d' || saving) return;
    try {
      const selectedPath = desktopFilePickerAvailable ? await chooseLive2DModelDirectory() : manualModelPath.trim();
      if (!selectedPath) {
        setStatus(desktopFilePickerAvailable ? '已取消选择' : '请输入模型目录路径');
        return;
      }
      setStatus('正在检查模型目录…');
      const result = await apiPost<Live2DResourceActionResult>('/ui/live2d/model-path/prepare', { path: selectedPath });
      applyLive2DResourceDraft(result);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '选择模型目录失败');
    }
  }

  async function importLive2DArchive() {
    if (mode !== 'live2d' || saving) return;
    try {
      const selectedPath = desktopFilePickerAvailable ? await chooseLive2DArchive() : manualArchivePath.trim();
      if (!selectedPath) {
        setStatus(desktopFilePickerAvailable ? '已取消导入' : '请输入 ZIP 路径');
        return;
      }
      setStatus('正在导入资源包…');
      const result = await apiPost<Live2DResourceActionResult>('/ui/live2d/archive/import', { path: selectedPath });
      applyLive2DResourceDraft(result);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '导入资源包失败');
    }
  }

  async function openLive2DAssetsDir() {
    if (mode !== 'live2d') return;
    const config = payload?.settings?.config || {};
    const resource = asRecord(config.resource);
    const assetsRoot = stringValue(resource.default_assets_root || config.default_assets_root);
    const assetsRootDisplay = stringValue(resource.default_assets_root_display || config.default_assets_root_display || assetsRoot);
    if (!assetsRoot) {
      setStatus('未找到默认导入目录');
      return;
    }
    try {
      await openPath(assetsRoot);
      setStatus(`已打开默认导入目录：${assetsRootDisplay}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开导入目录失败');
    }
  }

  async function openLive2DReleases() {
    if (mode !== 'live2d') return;
    const config = payload?.settings?.config || {};
    const resource = asRecord(config.resource);
    const releasesUrl = stringValue(resource.releases_url || config.releases_url);
    if (!releasesUrl) {
      setStatus('未找到 Releases 链接');
      return;
    }
    try {
      await openExternalUrl(releasesUrl);
      setStatus('已打开 GitHub Releases 页面');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开 Releases 页面失败');
    }
  }

  return (
    <main className="app-shell settings-page">
      <div className="settings-page-header">
        <div className="settings-page-title">{payload?.mode?.settings_title || '模式设置'}</div>
        <div className="settings-page-subtitle">{payload?.mode?.settings_description || '读取中…'}</div>
      </div>

      {status ? <div className={statusClassName(status)}>{status}</div> : null}

      <SettingsSection title="当前状态">
        <SettingsItem label="状态摘要" description={payload?.settings?.summary || '读取中…'} />
        {mode === 'live2d' ? (
          <Live2DResourceInfo
            config={payload?.settings?.config || {}}
            disabled={saving}
            desktopFilePickerAvailable={desktopFilePickerAvailable}
            manualModelPath={manualModelPath}
            manualArchivePath={manualArchivePath}
            onManualModelPathChange={setManualModelPath}
            onManualArchivePathChange={setManualArchivePath}
            onChooseModelPath={chooseLive2DModelPath}
            onImportArchive={importLive2DArchive}
            onOpenAssetsDir={openLive2DAssetsDir}
            onOpenReleases={openLive2DReleases}
          />
        ) : <BubbleResourceInfo config={payload?.settings?.config || {}} />}
      </SettingsSection>

      <form onSubmit={submitModeSettings} noValidate>
        {sections.map((section) => (
          <SettingsSection key={section.title} title={section.title}>
            {section.note ? <p className="settings-note" style={{ margin: '-8px 20px 12px' }}>{section.note}</p> : null}
            <div className="settings-form-grid" style={{ padding: '12px 20px 16px' }}>
              {section.fields.map((field) => renderModeField(field, form, updateField))}
            </div>
          </SettingsSection>
        ))}

        <div className="settings-savebar">
          <span className={status ? `settings-savebar-message ${statusToneClassName(status)}` : ''}>
            {status || (hasChanges ? `${pendingCount + (activationPending ? 1 : 0)} 项待保存` : '设置已同步')}
          </span>
          <div className="settings-save-actions">
            <SettingsActionButton disabled={!hasChanges || saving} onClick={resetDraft}>重置草稿</SettingsActionButton>
            <SettingsActionButton
              variant="primary"
              disabled={!hasChanges || saving}
              loading={saving}
              submit
            >
              {saving ? '保存中…' : '保存更改'}
            </SettingsActionButton>
          </div>
        </div>
      </form>
    </main>
  );
}

function ModeFieldPanel({
  section,
  form,
  onChange,
}: {
  section: ModeFieldSection;
  form: ModeForm;
  onChange: (key: string, value: ModeFormValue) => void;
}) {
  return (
    <section className="panel settings-section settings-mode-section">
      <div className="section-heading-row">
        <h2>{section.title}</h2>
      </div>
      {section.note ? <p className="settings-note">{section.note}</p> : null}
      <div className="settings-form-grid">
        {section.fields.map((field) => renderModeField(field, form, onChange))}
      </div>
    </section>
  );
}

function renderModeField(
  field: ModeFieldSpec,
  form: ModeForm,
  onChange: (key: string, value: ModeFormValue) => void,
) {
  const value = form[field.key];
  if (field.kind === 'checkbox') {
    return (
      <label className={`settings-check ${field.wide ? 'wide' : ''}`} htmlFor={fieldId(field.key)} key={field.key}>
        <input
          id={fieldId(field.key)}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(field.key, event.target.checked)}
        />
        <span>{field.label}</span>
      </label>
    );
  }
  if (field.kind === 'select') {
    const options = selectOptionsWithCurrentValue(field.options || [], String(value ?? ''));
    return (
      <div className={`settings-field ${field.wide ? 'wide' : ''}`} key={field.key}>
        <label htmlFor={fieldId(field.key)}>{field.label}</label>
        <select
          id={fieldId(field.key)}
          value={String(value ?? '')}
          onChange={(event) => onChange(field.key, event.target.value)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
    );
  }
  if (field.kind === 'textarea') {
    return (
      <div className={`settings-field ${field.wide ? 'wide' : ''}`} key={field.key}>
        <label htmlFor={fieldId(field.key)}>{field.label}</label>
        <textarea
          id={fieldId(field.key)}
          rows={4}
          value={String(value ?? '')}
          onChange={(event) => onChange(field.key, event.target.value)}
        />
      </div>
    );
  }
  if (field.kind === 'expressionRules') {
    return renderExpressionRulesField(field, value, onChange);
  }
  return (
    <div className={`settings-field ${field.wide ? 'wide' : ''}`} key={field.key}>
      <label htmlFor={fieldId(field.key)}>{field.label}</label>
      <div className={field.kind === 'percent' ? 'settings-input-with-unit' : undefined}>
        <input
          id={fieldId(field.key)}
          type={field.kind === 'text' ? 'text' : 'number'}
          inputMode={field.kind === 'text' ? undefined : 'decimal'}
          min={field.min}
          max={field.max}
          step={field.step}
          value={String(value ?? '')}
          onChange={(event) => onChange(field.key, event.target.value)}
          onBlur={(event) => {
            const normalized = normalizedNumericFieldValue(event.target.value, field);
            if (normalized !== null && normalized !== event.target.value) onChange(field.key, normalized);
          }}
        />
        {field.kind === 'percent' ? <span>%</span> : null}
      </div>
    </div>
  );
}

function nextModeFormValue(current: ModeForm, key: string, value: ModeFormValue): ModeForm {
  const next = { ...current, [key]: value };
  if (key === 'live2d_mode.render_quality_preset') {
    const preset = live2dRenderPresetFormValues(String(value || ''));
    if (preset) return { ...next, ...preset };
    return next;
  }
  if (
    key === 'live2d_mode.render_fps'
    || key === 'live2d_mode.render_resolution'
    || key === 'live2d_mode.hit_region_precision'
  ) {
    next['live2d_mode.render_quality_preset'] = 'custom';
  }
  return next;
}

function live2dRenderPresetFormValues(value: string): ModeForm | null {
  if (value === 'battery') {
    return {
      'live2d_mode.render_fps': '15',
      'live2d_mode.render_resolution': '0.75',
      'live2d_mode.hit_region_precision': 'low',
    };
  }
  if (value === 'balanced') {
    return {
      'live2d_mode.render_fps': '24',
      'live2d_mode.render_resolution': '1.25',
      'live2d_mode.hit_region_precision': 'medium',
    };
  }
  if (value === 'quality') {
    return {
      'live2d_mode.render_fps': '30',
      'live2d_mode.render_resolution': '1.5',
      'live2d_mode.hit_region_precision': 'high',
    };
  }
  return null;
}

function normalizedNumericFieldValue(value: string, field: ModeFieldSpec): string | null {
  if (field.kind !== 'number' && field.kind !== 'percent') return null;
  const trimmed = value.trim();
  if (!trimmed) return value;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return value;
  const min = field.min ?? Number.NEGATIVE_INFINITY;
  const max = field.max ?? Number.POSITIVE_INFINITY;
  const clamped = Math.min(Math.max(parsed, min), max);
  const normalized = field.integer ? String(Math.trunc(clamped)) : formatNumber(clamped);
  return normalized;
}

function renderExpressionRulesField(
  field: ModeFieldSpec,
  value: ModeFormValue | undefined,
  onChange: (key: string, value: ModeFormValue) => void,
) {
  const expressions = field.expressions || [];
  const rules = parseExpressionRulesFormValue(value);
  const updateRule = (expression: Live2DExpressionItem, nextValue: string) => {
    const key = live2dExpressionIdentifier(expression);
    if (!key) return;
    const nextRules = { ...rules };
    const normalized = nextValue.trim();
    if (normalized) nextRules[key] = normalized;
    else delete nextRules[key];
    onChange(field.key, JSON.stringify(sortStringRecord(nextRules)));
  };
  return (
    <div className={`settings-field live2d-expression-rules ${field.wide ? 'wide' : ''}`} key={field.key}>
      <label>{field.label}</label>
      {expressions.length ? (
        <div className="live2d-expression-rule-list">
          {expressions.map((expression) => {
            const key = live2dExpressionIdentifier(expression);
            const file = stringValue(expression.file).trim();
            return (
              <div className="live2d-expression-rule-row" key={key || file}>
                <div>
                  <strong>{stringValue(expression.name || expression.file || '未命名表情')}</strong>
                  {file ? <span>{file}</span> : null}
                </div>
                <input
                  type="text"
                  value={key ? rules[key] || '' : ''}
                  placeholder="例如：开心, 高兴, 成功, happy"
                  onChange={(event) => updateRule(expression, event.target.value)}
                />
              </div>
            );
          })}
        </div>
      ) : (
        <small>当前模型没有声明可配置表情；导入包含 Expressions 或 .exp3.json 的模型后会自动列出。</small>
      )}
    </div>
  );
}

function BubbleResourceInfo({ config }: { config: ModeConfig }) {
  return (
    <div className="settings-meta-list">
      <div className="settings-meta-row">
        <span>展开触发</span>
        <strong>点击打开聊天（固定）</strong>
      </div>
      <div className="settings-meta-row">
        <span>当前头像资源</span>
        <strong>{stringValue(config.avatar_path_display || config.avatar_path || '—')}</strong>
      </div>
    </div>
  );
}

function Live2DResourceInfo({
  config,
  disabled,
  desktopFilePickerAvailable,
  manualModelPath,
  manualArchivePath,
  onManualModelPathChange,
  onManualArchivePathChange,
  onChooseModelPath,
  onImportArchive,
  onOpenAssetsDir,
  onOpenReleases,
}: {
  config: ModeConfig;
  disabled: boolean;
  desktopFilePickerAvailable: boolean;
  manualModelPath: string;
  manualArchivePath: string;
  onManualModelPathChange: (value: string) => void;
  onManualArchivePathChange: (value: string) => void;
  onChooseModelPath: () => void;
  onImportArchive: () => void;
  onOpenAssetsDir: () => void;
  onOpenReleases: () => void;
}) {
  const resource = asRecord(config.resource);
  const summary = asRecord(config.summary);
  const releasesUrl = stringValue(resource.releases_url || config.releases_url || '');
  return (
    <div className="settings-meta-list">
      <div className="settings-resource-actions">
        <button type="button" disabled={disabled} onClick={onChooseModelPath}>{desktopFilePickerAvailable ? '选择模型目录' : '检查模型目录路径'}</button>
        <button type="button" disabled={disabled} onClick={onImportArchive}>{desktopFilePickerAvailable ? '导入资源包 ZIP' : '按路径导入 ZIP'}</button>
        <button type="button" disabled={disabled} onClick={onOpenAssetsDir}>打开导入目录</button>
        <button type="button" disabled={disabled || !releasesUrl} onClick={onOpenReleases}>打开 Releases</button>
      </div>
      {!desktopFilePickerAvailable ? (
        <div className="settings-resource-fallback">
          <p className="settings-note">当前窗口没有桌面文件选择器入口，可直接输入本机路径继续导入。</p>
          <div className="settings-field">
            <label htmlFor="manual-live2d-model-path">模型目录路径</label>
            <input
              id="manual-live2d-model-path"
              value={manualModelPath}
              placeholder="~/Downloads/yachiyo"
              onChange={(event) => onManualModelPathChange(event.target.value)}
            />
          </div>
          <div className="settings-field">
            <label htmlFor="manual-live2d-archive-path">资源包 ZIP 路径</label>
            <input
              id="manual-live2d-archive-path"
              value={manualArchivePath}
              placeholder="~/Downloads/hermes-yachiyo-live2d-yachiyo-20260423.zip"
              onChange={(event) => onManualArchivePathChange(event.target.value)}
            />
          </div>
        </div>
      ) : null}
      <div className="settings-meta-row">
        <span>模型状态</span>
        <strong className={live2dStateClass(stringValue(config.model_state))}>{live2dStateLabel(stringValue(config.model_state))}</strong>
      </div>
      <div className="settings-meta-row">
        <span>模型入口</span>
        <strong>{stringValue(summary.renderer_entry_display || summary.renderer_entry || '—')}</strong>
      </div>
      <div className="settings-meta-row">
        <span>资源来源</span>
        <strong>{stringValue(resource.source_label || config.source_label || '—')}</strong>
      </div>
      <div className="settings-meta-row">
        <span>当前配置路径</span>
        <strong>{stringValue(resource.configured_path_display || config.model_path_display || '—')}</strong>
      </div>
      <div className="settings-meta-row">
        <span>当前生效路径</span>
        <strong>{stringValue(resource.effective_model_path_display || config.effective_model_path_display || '—')}</strong>
      </div>
      <div className="settings-meta-row">
        <span>默认导入目录</span>
        <strong>{stringValue(resource.default_assets_root_display || config.default_assets_root_display || '—')}</strong>
      </div>
      {releasesUrl ? (
        <div className="settings-meta-row">
          <span>资源下载</span>
          <strong>
            <button
              type="button"
              className="inline-link-button"
              disabled={disabled}
              onClick={onOpenReleases}
            >
              GitHub Releases
            </button>
          </strong>
        </div>
      ) : null}
      <p className="settings-note">{stringValue(resource.help_text || config.help_text || '—')}</p>
      <div className="settings-meta-row">
        <span>模型可用表情</span>
        <strong>{live2dExpressionSummary(summary)}</strong>
      </div>
      <div className="settings-meta-row">
        <span>模型可用动作</span>
        <strong>{live2dMotionSummary(summary)}</strong>
      </div>
    </div>
  );
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="settings-group">
      <div className="settings-group-title">{title}</div>
      <div className="settings-card">{children}</div>
    </div>
  );
}

function SettingsItem({
  label,
  description,
  children,
  wide,
}: {
  label: string;
  description?: string;
  children?: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`settings-item${wide ? ' settings-item-wide' : ''}`}>
      <div className="settings-item-info">
        <div className="settings-item-label">{label}</div>
        {description ? <div className="settings-item-desc">{description}</div> : null}
      </div>
      {children ? <div className="settings-item-control">{children}</div> : null}
    </div>
  );
}

function SettingsToggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className="settings-toggle"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
}

function SettingsActionButton({
  children,
  onClick,
  disabled,
  variant,
  loading,
  submit,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: 'primary' | 'danger';
  loading?: boolean;
  submit?: boolean;
}) {
  const className = [
    'settings-action-btn',
    variant === 'primary' ? 'primary' : '',
    variant === 'danger' ? 'danger' : '',
    loading ? 'loading' : '',
  ].filter(Boolean).join(' ');
  return (
    <button type={submit ? 'submit' : 'button'} className={className} disabled={disabled || loading} onClick={onClick}>
      {children}
    </button>
  );
}

function SystemSettingsView() {
  const [payload, setPayload] = useState<GeneralSettingsPayload | null>(null);
  const [form, setForm] = useState<GeneralSettingsForm>(emptyGeneralSettingsForm());
  const [backupStatus, setBackupStatus] = useState<BackupStatus | null>(null);
  const [backupManagerOpen, setBackupManagerOpen] = useState(false);
  const [backupAction, setBackupAction] = useState('');
  const [appUpdateInfo, setAppUpdateInfo] = useState<AppUpdateInfo | null>(null);
  const [appUpdateCheck, setAppUpdateCheck] = useState<AppUpdateCheckResult | null>(null);
  const [appUpdateDownload, setAppUpdateDownload] = useState<AppUpdateDownloadResult | null>(null);
  const [appUpdateProgress, setAppUpdateProgress] = useState<AppUpdateDownloadProgress | null>(null);
  const [appUpdateAction, setAppUpdateAction] = useState('');
  const [uninstallScope, setUninstallScope] = useState('yachiyo_only');
  const [uninstallKeepConfig, setUninstallKeepConfig] = useState(true);
  const [uninstallGptSovits, setUninstallGptSovits] = useState(false);
  const [uninstallPreview, setUninstallPreview] = useState<UninstallPlan | null>(null);
  const [uninstallConfirmText, setUninstallConfirmText] = useState('');
  const [uninstallRunning, setUninstallRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);
  const [bridgeRestarting, setBridgeRestarting] = useState(false);

  const changes = useMemo(() => buildGeneralSettingsChanges(payload, form), [payload, form]);
  const pendingCount = useMemo(() => countGeneralSettingsPendingChanges(payload, form), [payload, form]);
  const hasChanges = pendingCount > 0;
  const uninstallConfirmPhrase = uninstallPreview?.confirm_phrase || 'UNINSTALL';
  const uninstallConfirmValid = uninstallConfirmText.trim() === uninstallConfirmPhrase;
  const backupBusy = Boolean(backupAction);
  const appUpdateBusy = Boolean(appUpdateAction);
  const appUpdateCurrent = appUpdateCheck?.current || appUpdateInfo?.current;
  const appUpdateLatest = appUpdateCheck?.latest || appUpdateDownload?.latest || appUpdateInfo?.downloaded_update?.latest;
  const appUpdateChangelog = appUpdateLatest?.changelog || appUpdateDownload?.latest?.changelog || appUpdateInfo?.downloaded_update?.latest?.changelog;
  const appUpdateSupported = Boolean(appUpdateCheck?.supported ?? appUpdateInfo?.supported);
  const appUpdateDownloaded = appUpdateDownload?.ok ? appUpdateDownload : appUpdateInfo?.downloaded_update;
  const appUpdateDownloadedPath = appUpdateDownloaded?.path || appUpdateInfo?.downloaded_dmg_path || '';

  useEffect(() => {
    let disposed = false;
    async function loadSettings() {
      try {
        const data = await apiGet<GeneralSettingsPayload>('/ui/settings');
        if (!disposed) {
          setPayload(data);
          setForm(formFromGeneralSettings(data));
        }
      } catch (err) {
        if (!disposed) setStatus(err instanceof Error ? err.message : '读取设置失败');
      }
    }
    loadSettings();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    apiGet<BackupStatus>('/ui/backup/status')
      .then((data) => {
        if (!disposed) setBackupStatus(data);
      })
      .catch((err) => {
        if (!disposed) setBackupStatus({ ok: false, error: err instanceof Error ? err.message : '读取备份状态失败' });
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    async function loadAppUpdateInfo() {
      try {
        const info = await getAppUpdateInfo();
        if (disposed) return;
        setAppUpdateInfo(info);
        if (info.downloaded_update?.ok) setAppUpdateDownload(info.downloaded_update);
        const result = await checkAppUpdate();
        if (disposed) return;
        setAppUpdateCheck(result);
        setAppUpdateInfo(result);
        if (result.downloaded_update?.ok) setAppUpdateDownload(result.downloaded_update);
      } catch (err) {
        if (!disposed) {
          setAppUpdateInfo({ supported: false, packaged: false, error: err instanceof Error ? err.message : '读取应用更新信息失败' });
        }
      }
    }
    void loadAppUpdateInfo();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => onAppUpdateDownloadProgress((progress) => {
    setAppUpdateProgress(progress);
  }), []);

  useEffect(() => {
    let disposed = false;
    const query = new URLSearchParams({
      scope: uninstallScope,
      keep_config: String(uninstallKeepConfig),
      include_gpt_sovits: String(uninstallGptSovits),
    });
    apiGet<UninstallPreviewResult>(`/ui/uninstall/preview?${query.toString()}`)
      .then((data) => {
        if (!disposed) setUninstallPreview(data.plan || null);
      })
      .catch((err) => {
        if (!disposed) {
          setUninstallPreview(null);
          setStatus(err instanceof Error ? err.message : '生成卸载清单失败');
        }
      });
    return () => {
      disposed = true;
    };
  }, [uninstallScope, uninstallKeepConfig, uninstallGptSovits]);

  useEffect(() => {
    if (status === 'Bridge 端口必须是整数' && Number.isInteger(Number(form.bridge_port))) {
      setStatus('');
    }
    if (status === 'Bridge Host 不能为空' && form.bridge_host.trim()) {
      setStatus('');
    }
  }, [form.bridge_host, form.bridge_port, status]);

  function selectDisplayMode(modeId: string) {
    if (modeId === 'live2d' && !live2dResourceReady(payload)) {
      window.sessionStorage.setItem(LIVE2D_ACTIVATION_DRAFT_KEY, '1');
      setStatus('Live2D 资源未就绪，请先导入资源包或选择有效模型目录；暂不切换表现态');
      window.setTimeout(() => navigateTo('settings', { mode: 'live2d', reason: 'live2d-resource-required' }), 350);
      return;
    }
    setForm((current) => ({ ...current, display_mode: modeId }));
  }

  async function submitSettings(event: FormEvent) {
    event.preventDefault();
    if (!payload || saving) return;
    const bridgePort = Number(form.bridge_port);
    if (!Number.isInteger(bridgePort)) {
      setStatus('Bridge 端口必须是整数');
      return;
    }
    const nextChanges = buildGeneralSettingsChanges(payload, form);
    if (!Object.keys(nextChanges).length) {
      setStatus('没有待保存的更改');
      return;
    }
    if (!form.bridge_host.trim()) {
      setStatus('Bridge Host 不能为空');
      return;
    }
    const backupRetentionCount = Number(form.backup_retention_count);
    if (!Number.isInteger(backupRetentionCount) || backupRetentionCount < 1 || backupRetentionCount > 100) {
      setStatus('备份保留份数须在 1-100 之间');
      return;
    }
    setStatus('保存中…');
    setSaving(true);
    try {
      const result = await apiPost<SettingsUpdateResult>('/ui/settings', { changes: nextChanges });
      if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '保存失败');
      const data = await apiGet<GeneralSettingsPayload>('/ui/settings');
      setPayload(data);
      setForm(formFromGeneralSettings(data));
      if (result.mode_switch_scheduled || typeof nextChanges.display_mode === 'string') {
        const targetMode = String(result.target_display_mode || nextChanges.display_mode || data.display?.current_mode || 'bubble');
        await openDesktopMode(targetMode);
        setStatus(`已保存，表现态已切换到 ${modeLabel(targetMode)}`);
      } else if (result.effects?.has_restart_bridge) {
        setStatus('已保存；Bridge 配置需要点击“应用配置并重启 Bridge”后生效');
      } else if (result.effects?.has_restart_app) {
        setStatus(`已保存，${result.effects.hint || '部分配置将在下次启动后生效'}`);
      } else {
        setStatus(result.effects?.hint ? `已保存，${result.effects.hint}` : '已保存');
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function refreshGeneralSettings() {
    const data = await apiGet<GeneralSettingsPayload>('/ui/settings');
    setPayload(data);
    setForm(formFromGeneralSettings(data));
  }

  async function refreshBackupStatus(message = '') {
    const data = await apiGet<BackupStatus>('/ui/backup/status');
    setBackupStatus(data);
    if (message) setStatus(message);
  }

  async function restartBridge() {
    if (bridgeRestarting) return;
    if (saving) {
      setStatus('正在保存设置，请稍后再重启 Bridge');
      return;
    }
    if (hasChanges) {
      setStatus('请先保存更改，再重启 Bridge');
      return;
    }
    const bridgePort = Number(form.bridge_port);
    if (!Number.isInteger(bridgePort)) {
      setStatus('Bridge 端口必须是整数');
      return;
    }
    if (!form.bridge_host.trim()) {
      setStatus('Bridge Host 不能为空');
      return;
    }

    setBridgeRestarting(true);
    setStatus('正在重启 Bridge，界面会短暂断开…');
    try {
      const targetBridgeUrl = `http://${form.bridge_host.trim()}:${bridgePort}`;
      const desktopResult = await restartDesktopBridge(targetBridgeUrl);
      if (!desktopResult.success) {
        const result = await apiPost<{ ok?: boolean; error?: string; desktop_restart_backend_required?: boolean }>('/ui/bridge/restart');
        if (result.ok === false) throw new Error(result.error || 'Bridge 重启失败');
        if (result.desktop_restart_backend_required) {
          throw new Error(result.error || desktopResult.error || '当前环境无法自动重启 Bridge，请重启 Hermes-Yachiyo');
        }
      }
      await refreshGeneralSettings();
      setStatus('Bridge 已按当前配置重启');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Bridge 重启失败');
    } finally {
      setBridgeRestarting(false);
    }
  }

  async function runAppUpdateCheck(showMessage = true) {
    if (appUpdateAction) return;
    setAppUpdateAction('check');
    if (showMessage) setStatus('正在检查应用更新…');
    try {
      const result = await checkAppUpdate();
      setAppUpdateCheck(result);
      setAppUpdateInfo(result);
      setAppUpdateDownload(result.downloaded_update?.ok ? result.downloaded_update : null);
      if (showMessage) {
        if (result.ok === false) throw new Error(result.error || '检查应用更新失败');
        setStatus(result.update_available ? result.reason || '发现可用更新' : result.reason || '当前已是最新版本');
      }
    } catch (err) {
      if (showMessage) setStatus(err instanceof Error ? err.message : '检查应用更新失败');
    } finally {
      setAppUpdateAction('');
    }
  }

  async function runAppUpdateDownload() {
    if (appUpdateAction) return;
    setAppUpdateAction('download');
    setAppUpdateProgress({ status: 'starting', file_name: appUpdateLatest?.dmg_name });
    setStatus('正在下载应用更新…');
    try {
      const result = await downloadAppUpdate();
      setAppUpdateDownload(result);
      if (!result.ok) throw new Error(result.error || '下载应用更新失败');
      const info = await getAppUpdateInfo();
      setAppUpdateInfo(info);
      setAppUpdateProgress({ status: 'completed', file_name: result.file_name, percent: 100 });
      setStatus(result.verified ? '更新已下载并通过校验，可安装并重启' : '更新已下载，可安装并重启；当前元数据未提供 SHA256 校验值');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '下载应用更新失败');
    } finally {
      setAppUpdateAction('');
    }
  }

  async function runAppUpdateInstall() {
    if (appUpdateAction) return;
    const dmgPath = appUpdateDownload?.path || appUpdateInfo?.downloaded_dmg_path || '';
    if (!dmgPath) {
      setStatus('请先下载应用更新');
      return;
    }
    if (!window.confirm('将退出 Hermes-Yachiyo，用已下载的 DMG 覆盖当前应用，然后重新打开。继续吗？')) return;
    setAppUpdateAction('install');
    setStatus('正在准备安装更新，应用将退出并重新打开…');
    try {
      const result = await installAppUpdate(dmgPath);
      if (!result.success) throw new Error(result.error || '启动更新安装失败');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '启动更新安装失败');
      setAppUpdateAction('');
    }
  }

  async function createBackup(overwriteLatest = false) {
    if (backupBusy) return;
    if (overwriteLatest && !window.confirm('将生成新备份并替换最近一次备份，继续吗？')) return;
    setBackupAction(overwriteLatest ? 'backup-overwrite' : 'backup-create');
    setStatus(overwriteLatest ? '正在覆盖最近一次备份…' : '正在生成备份…');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; status?: BackupStatus }>('/ui/backup/create', { overwrite_latest: overwriteLatest });
      if (result.ok === false) throw new Error(result.error || '生成备份失败');
      setBackupStatus(result.status || null);
      await refreshBackupStatus(overwriteLatest ? '最近一次备份已覆盖' : '备份已生成');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '生成备份失败');
    } finally {
      setBackupAction('');
    }
  }

  async function restoreBackup(backupPath = '') {
    if (backupBusy) return;
    if (!window.confirm('恢复备份会覆盖当前本地资料并安排应用重启，继续吗？')) return;
    setBackupAction(backupPath ? `backup-restore:${backupPath}` : 'backup-restore');
    setStatus('正在恢复备份…');
    try {
      const result = await apiPost<{ ok?: boolean; errors?: string[]; error?: string }>('/ui/backup/restore', { backup_path: backupPath });
      if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '恢复备份失败');
      setStatus('备份已恢复，应用将按需要重启');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '恢复备份失败');
    } finally {
      setBackupAction('');
    }
  }

  async function deleteBackup(backupPath: string) {
    if (backupBusy) return;
    if (!backupPath || !window.confirm('确认删除这份备份吗？')) return;
    setBackupAction(`backup-delete:${backupPath}`);
    setStatus('正在删除备份…');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; status?: BackupStatus }>('/ui/backup/delete', { backup_path: backupPath });
      if (result.ok === false) throw new Error(result.error || '删除备份失败');
      setBackupStatus(result.status || null);
      await refreshBackupStatus('备份已删除');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '删除备份失败');
    } finally {
      setBackupAction('');
    }
  }

  async function openBackupLocation(backupPath = '') {
    if (backupBusy) return;
    setBackupAction(backupPath ? `backup-open:${backupPath}` : 'backup-open');
    setStatus('正在打开备份位置…');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/backup/open-location', { backup_path: backupPath });
      setStatus(result.ok === false ? result.error || '打开备份位置失败' : '已打开备份位置');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开备份位置失败');
    } finally {
      setBackupAction('');
    }
  }

  async function runUninstall() {
    if (uninstallRunning) return;
    if (!uninstallConfirmValid) {
      setStatus(`请输入确认短语 ${uninstallConfirmPhrase}`);
      return;
    }
    if (!window.confirm('卸载会删除所选本机资料，此操作不可撤销。确认继续吗？')) return;
    setUninstallRunning(true);
    setStatus('正在卸载…');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; errors?: string[]; backup_path_display?: string; desktop_quit_required?: boolean; exit_scheduled?: boolean }>('/ui/uninstall/run', {
        scope: uninstallScope,
        keep_config: uninstallKeepConfig,
        include_gpt_sovits: uninstallGptSovits,
        confirm_text: uninstallConfirmText,
      });
      if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '卸载失败');
      const backupText = result.backup_path_display ? `备份已保存到 ${result.backup_path_display}。` : '';
      setStatus(`卸载已执行。${backupText} 正在删除应用本体并退出…`);
      const removeResult = await removeAppBundleAndQuit();
      if (!removeResult.success) {
        throw new Error(removeResult.error || '本地资料已删除，但无法自动删除应用本体；请从 Applications 中手动移除 Hermes-Yachiyo');
      }
      return;
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '卸载失败');
      setUninstallRunning(false);
    }
  }

  async function refreshUninstallPreview() {
    const query = new URLSearchParams({
      scope: uninstallScope,
      keep_config: String(uninstallKeepConfig),
      include_gpt_sovits: String(uninstallGptSovits),
    });
    const data = await apiGet<UninstallPreviewResult>(`/ui/uninstall/preview?${query.toString()}`);
    if (data.ok === false) throw new Error(data.error || '生成卸载清单失败');
    setUninstallPreview(data.plan || null);
    setStatus('卸载清单已刷新');
  }

  return (
    <main className="app-shell settings-page">
      <div className="settings-page-header">
        <button type="button" className="page-back-link" onClick={() => navigateTo('settings')}>← 返回设置</button>
        <div className="settings-page-title">系统设置</div>
        <div className="settings-page-subtitle">高级配置和系统维护</div>
      </div>

      {status ? <div className={statusClassName(status)}>{status}</div> : null}

      <form onSubmit={submitSettings} noValidate>
        <SettingsSection title="通用">
          <SettingsItem label="最小化到托盘" description="关闭窗口时最小化到系统托盘">
            <SettingsToggle
              checked={form.tray_enabled}
              onChange={(next) => setForm((current) => ({ ...current, tray_enabled: next }))}
            />
          </SettingsItem>
          <SettingsItem label="语言" description="界面显示语言">
            <select className="settings-select" value="zh-CN" onChange={() => {}}>
              <option value="zh-CN">简体中文</option>
              <option value="en">English</option>
              <option value="ja">日本語</option>
            </select>
          </SettingsItem>
        </SettingsSection>

        <SettingsSection title="显示模式">
          <SettingsItem label="显示模式" description={form.display_mode === payload?.display?.current_mode ? '当前表现态' : '待切换'}>
            <div className="segmented-list">
              {(payload?.display?.available_modes || []).map((item) => (
                <button
                  className={item.id === form.display_mode ? 'selected' : ''}
                  type="button"
                  key={item.id}
                  onClick={() => void selectDisplayMode(item.id)}
                >
                  {item.name || item.label || item.id}
                </button>
              ))}
            </div>
          </SettingsItem>
        </SettingsSection>

        <SettingsSection title="助手">
          <SettingsItem label="助手称呼" description="用户对助手的称呼方式">
            <input
              className="settings-input"
              value={form.user_address}
              onChange={(event) => setForm((current) => ({ ...current, user_address: event.target.value }))}
            />
          </SettingsItem>
          <SettingsItem label="助手人设" description="定义助手的性格和行为风格" wide>
            <textarea
              className="settings-textarea"
              rows={6}
              value={form.persona_prompt}
              onChange={(event) => setForm((current) => ({ ...current, persona_prompt: event.target.value }))}
            />
          </SettingsItem>
        </SettingsSection>

        <SettingsSection title="Bridge">
          <SettingsItem label="启用 Bridge" description="内部通信服务">
            <SettingsToggle
              checked={form.bridge_enabled}
              onChange={(next) => setForm((current) => ({ ...current, bridge_enabled: next }))}
            />
          </SettingsItem>
          <SettingsItem label="Bridge Host" description="Bridge 监听地址">
            <input
              className="settings-input"
              value={form.bridge_host}
              onChange={(event) => setForm((current) => ({ ...current, bridge_host: event.target.value }))}
            />
          </SettingsItem>
          <SettingsItem label="Bridge Port" description="Bridge 监听端口">
            <input
              className="settings-input"
              inputMode="numeric"
              value={form.bridge_port}
              onChange={(event) => setForm((current) => ({ ...current, bridge_port: event.target.value }))}
            />
          </SettingsItem>
          <SettingsItem label="重启 Bridge" description={payload?.bridge?.config_dirty ? '配置已变更，需要重启生效' : '按当前配置重启内部通信服务'}>
            <SettingsActionButton
              disabled={bridgeRestarting || saving || hasChanges}
              loading={bridgeRestarting}
              onClick={() => void restartBridge()}
            >
              {bridgeRestarting ? '重启中…' : '应用配置并重启'}
            </SettingsActionButton>
          </SettingsItem>
        </SettingsSection>

        <SettingsSection title="备份">
          <SettingsItem label="自动清理旧备份" description="启用后自动删除超出保留份数的旧备份">
            <SettingsToggle
              checked={form.backup_auto_cleanup_enabled}
              onChange={(next) => setForm((current) => ({ ...current, backup_auto_cleanup_enabled: next }))}
            />
          </SettingsItem>
          <SettingsItem label="备份保留份数" description="自动清理时保留的最近备份份数（1-100）">
            <input
              className="settings-input"
              inputMode="numeric"
              value={form.backup_retention_count}
              onChange={(event) => setForm((current) => ({ ...current, backup_retention_count: event.target.value }))}
            />
          </SettingsItem>
          <SettingsItem label="备份" description={backupStatus?.has_backup ? `${backupStatus.count || 0} 份 / ${backupStatus.total_size_display || '0 B'}` : '暂无备份'}>
            <SettingsActionButton
              disabled={backupBusy}
              loading={backupAction === 'backup-create'}
              onClick={() => void createBackup(false)}
            >
              {backupAction === 'backup-create' ? '生成中…' : '生成备份'}
            </SettingsActionButton>
            <SettingsActionButton
              disabled={backupBusy}
              onClick={() => setBackupManagerOpen((open) => !open)}
            >
              {backupManagerOpen ? '收起' : '管理'}
            </SettingsActionButton>
          </SettingsItem>
          {backupManagerOpen ? (
            <div style={{ gridColumn: '1 / -1' }}>
              <div className="settings-action-strip" style={{ marginBottom: 8 }}>
                <SettingsActionButton
                  disabled={backupBusy}
                  loading={backupAction === 'backup-overwrite'}
                  onClick={() => void createBackup(true)}
                >
                  {backupAction === 'backup-overwrite' ? '覆盖中…' : '覆盖最近一次'}
                </SettingsActionButton>
                <SettingsActionButton
                  disabled={backupBusy}
                  loading={backupAction === 'backup-restore'}
                  onClick={() => void restoreBackup()}
                >
                  {backupAction === 'backup-restore' ? '恢复中…' : '恢复最近备份'}
                </SettingsActionButton>
                <SettingsActionButton
                  disabled={backupBusy}
                  loading={backupAction === 'backup-open'}
                  onClick={() => void openBackupLocation()}
                >
                  {backupAction === 'backup-open' ? '打开中…' : '打开备份目录'}
                </SettingsActionButton>
              </div>
              {(backupStatus?.backups || []).length ? (
                <div className="backup-manager">
                  {(backupStatus?.backups || []).map((item) => (
                    <div className="backup-item" key={item.path || item.display_path}>
                      <div>
                        <div className="name">{backupFileName(item)}</div>
                        <div className="meta">{formatSettingsDate(item.created_at)} · {item.size_display || '未知大小'}</div>
                        {!item.valid ? <div className="meta" style={{ color: '#ffd89a' }}>{item.error || '备份无效'}</div> : null}
                      </div>
                      <div className="actions">
                        <SettingsActionButton
                          disabled={backupBusy}
                          loading={backupAction === `backup-restore:${item.path || ''}`}
                          onClick={() => void restoreBackup(item.path || '')}
                        >
                          {backupAction === `backup-restore:${item.path || ''}` ? '恢复中…' : '恢复'}
                        </SettingsActionButton>
                        <SettingsActionButton
                          disabled={backupBusy}
                          loading={backupAction === `backup-open:${item.path || ''}`}
                          onClick={() => void openBackupLocation(item.path || '')}
                        >
                          {backupAction === `backup-open:${item.path || ''}` ? '打开中…' : '打开位置'}
                        </SettingsActionButton>
                        <SettingsActionButton
                          variant="danger"
                          disabled={backupBusy}
                          loading={backupAction === `backup-delete:${item.path || ''}`}
                          onClick={() => void deleteBackup(item.path || '')}
                        >
                          {backupAction === `backup-delete:${item.path || ''}` ? '删除中…' : '删除'}
                        </SettingsActionButton>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="inline-empty">暂无可管理备份</div>
              )}
            </div>
          ) : null}
        </SettingsSection>

        <SettingsSection title="更新">
          <SettingsItem label="应用版本" description={`Hermes Yachiyo v${payload?.app?.version || '0.1.0'}`}>
            <SettingsActionButton
              disabled={appUpdateBusy || !appUpdateSupported}
              loading={appUpdateAction === 'check'}
              onClick={() => void runAppUpdateCheck()}
            >
              {appUpdateAction === 'check' ? '检查中…' : '检查更新'}
            </SettingsActionButton>
          </SettingsItem>
          {appUpdateDownloadedPath ? (
            <SettingsItem label="安装更新" description={appUpdateStatusLabel(appUpdateInfo, appUpdateCheck)}>
              <SettingsActionButton
                variant="primary"
                disabled={appUpdateBusy}
                loading={appUpdateAction === 'install'}
                onClick={() => void runAppUpdateInstall()}
              >
                {appUpdateAction === 'install' ? '准备中…' : '安装并重启'}
              </SettingsActionButton>
            </SettingsItem>
          ) : appUpdateCheck?.update_available ? (
            <SettingsItem label="下载更新" description={appUpdateStatusLabel(appUpdateInfo, appUpdateCheck)}>
              <SettingsActionButton
                disabled={appUpdateBusy || !appUpdateSupported}
                loading={appUpdateAction === 'download'}
                onClick={() => void runAppUpdateDownload()}
              >
                {appUpdateAction === 'download' ? appUpdateDownloadButtonLabel(appUpdateProgress) : '下载更新'}
              </SettingsActionButton>
            </SettingsItem>
          ) : null}
        </SettingsSection>

        <SettingsSection title="卸载">
          <SettingsItem label="卸载" description="删除本地资料并卸载应用">
            <SettingsActionButton
              variant="danger"
              disabled={uninstallRunning || !uninstallConfirmValid}
              loading={uninstallRunning}
              onClick={() => void runUninstall()}
            >
              {uninstallRunning ? '正在卸载…' : '卸载'}
            </SettingsActionButton>
          </SettingsItem>
          <div style={{ padding: '0 20px 16px' }}>
            <div className="settings-form-grid uninstall-options">
              <div className="settings-field">
                <label htmlFor="uninstall-scope">卸载范围</label>
                <select id="uninstall-scope" value={uninstallScope} onChange={(event) => setUninstallScope(event.target.value)}>
                  <option value="yachiyo_only">仅卸载 Hermes-Yachiyo</option>
                  <option value="include_hermes">也卸载 Hermes Agent 架构</option>
                </select>
              </div>
              <label className="settings-check" htmlFor="uninstall-keep-config">
                <input
                  id="uninstall-keep-config"
                  type="checkbox"
                  checked={uninstallKeepConfig}
                  onChange={(event) => setUninstallKeepConfig(event.target.checked)}
                />
                <span>卸载前生成备份</span>
              </label>
              <label className="settings-check" htmlFor="uninstall-gpt-sovits">
                <input
                  id="uninstall-gpt-sovits"
                  type="checkbox"
                  checked={uninstallGptSovits}
                  onChange={(event) => setUninstallGptSovits(event.target.checked)}
                />
                <span>同时卸载 GPT-SoVITS</span>
              </label>
            </div>
            {uninstallGptSovits ? (
              <p className="warn-text" style={{ marginTop: 8 }}>
                将删除 GPT-SoVITS 服务目录，包括已下载的基础预训练模型、虚拟环境和本地服务文件。
              </p>
            ) : null}
            {uninstallPreview ? (
              <div className="uninstall-preview-react">
                {(uninstallPreview.targets || []).map((target) => (
                  <div className="uninstall-target-react" key={target.id || target.path}>
                    <div>
                      <strong>{target.label || target.id}</strong>
                      <span>{target.display_path || target.path || '—'}</span>
                    </div>
                    <small>{target.exists ? (target.removable ? '将删除' : target.reason || '跳过') : '不存在'}</small>
                  </div>
                ))}
                {uninstallPreview.warnings?.length ? <p className="warn-text">{uninstallPreview.warnings.join('；')}</p> : null}
              </div>
            ) : null}
            <div className="settings-field uninstall-confirm-field">
              <label htmlFor="uninstall-confirm-text">输入 {uninstallConfirmPhrase} 确认</label>
              <input
                id="uninstall-confirm-text"
                value={uninstallConfirmText}
                disabled={uninstallRunning}
                onChange={(event) => setUninstallConfirmText(event.target.value)}
              />
            </div>
          </div>
        </SettingsSection>

        <SettingsSection title="模式配置">
          <div style={{ padding: '4px 0' }}>
            <div className="mode-summary-list">
              {Object.entries(payload?.mode_settings || {}).map(([modeId, item]) => (
                <button type="button" key={modeId} onClick={() => navigateTo('settings', { mode: modeId })}>
                  <strong>{item.title || modeId}</strong>
                  <span>{item.summary || '—'}</span>
                </button>
              ))}
            </div>
          </div>
        </SettingsSection>

        <div className="settings-savebar">
          <span>{hasChanges ? `${pendingCount} 项待保存` : '设置已同步'}</span>
          <SettingsActionButton
            variant="primary"
            disabled={!hasChanges || saving}
            loading={saving}
            submit
          >
            {saving ? '保存中…' : '保存更改'}
          </SettingsActionButton>
        </div>
      </form>
    </main>
  );
}

function listValue(items?: string[]): string {
  return items?.length ? items.join('、') : '—';
}

function appUpdateChannelLabel(channel?: string, branch?: string): string {
  if (channel === 'stable' || branch === 'main') return '正式版 / main';
  if (channel === 'experimental' || branch === 'develop') return '开发版 / develop';
  return channel || branch || '—';
}

function appUpdateBuildLabel(version?: string, buildNumber?: number, shortCommit?: string): string {
  const parts = [
    version || '',
    buildNumber !== undefined ? `#${buildNumber}` : '',
    shortCommit || '',
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '—';
}

function appUpdateStatusLabel(info: AppUpdateInfo | null, check: AppUpdateCheckResult | null): string {
  if (info?.downloaded_update?.ok || check?.downloaded_update?.ok) return '已下载';
  if (check?.ok === false) return '检查失败';
  if (check?.update_available) return '有更新';
  if (check?.ok) return '已是最新';
  if (info?.supported === false) return info.packaged ? '不可更新' : '开发环境';
  return '待检查';
}

function appUpdateVerificationLabel(download: AppUpdateDownloadResult | null): string {
  if (!download) return '—';
  if (download.ok === false) return '失败';
  return download.verified ? 'SHA256 已通过' : '未提供 SHA256';
}

function appUpdateProgressLabel(
  progress: AppUpdateDownloadProgress | null,
  download: AppUpdateDownloadResult | undefined,
): string {
  if (download?.ok) return '已下载';
  if (!progress) return '—';
  if (progress.status === 'verifying') return '校验中';
  if (progress.status === 'completed') return '100%';
  if (progress.status === 'failed') return progress.error || '失败';
  if (typeof progress.percent === 'number') return `${progress.percent.toFixed(progress.percent % 1 ? 1 : 0)}%`;
  if (progress.received_bytes) return formatByteCount(progress.received_bytes);
  if (progress.status === 'starting') return '准备下载';
  return '下载中';
}

function appUpdateDownloadButtonLabel(progress: AppUpdateDownloadProgress | null): string {
  if (progress?.status === 'verifying') return '校验中...';
  if (typeof progress?.percent === 'number') return `下载中 ${progress.percent.toFixed(0)}%`;
  return '下载中...';
}

function formatByteCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function modeLabel(mode: string) {
  return mode === 'live2d' ? 'Live2D' : 'Bubble';
}

function hermesReadinessLabel(level?: string): string {
  const labels: Record<string, string> = {
    full_ready: 'Doctor 完整就绪',
    core_ready: '核心能力就绪',
    basic_ready: '基础就绪，Doctor 未分级',
    limited: '存在受限能力',
    unknown: '未完成 Doctor 分级',
  };
  return labels[level || 'unknown'] || level || '待检测';
}

function workspaceDirs(dirs?: Record<string, string>): string {
  if (!dirs) return '—';
  const parts = Object.entries(dirs).filter(([, value]) => Boolean(value));
  return parts.length ? parts.map(([key, value]) => `${key}: ${value}`).join('；') : '—';
}

function backupSummary(item: BackupInfo | null): string {
  if (!item) return '未检测到备份';
  return `${backupFileName(item)} · ${formatSettingsDate(item.created_at)} · ${item.size_display || '未知大小'}`;
}

function backupFileName(item: BackupInfo): string {
  const source = item.display_path || item.path || '备份文件';
  return source.split(/[\\/]/).pop() || source;
}

function formatSettingsDate(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function emptyGeneralSettingsForm(): GeneralSettingsForm {
  return {
    persona_prompt: '',
    user_address: '',
    bridge_enabled: true,
    bridge_host: '127.0.0.1',
    bridge_port: '8420',
    display_mode: 'bubble',
    tray_enabled: true,
    backup_auto_cleanup_enabled: true,
    backup_retention_count: '10',
  };
}

function formFromGeneralSettings(payload: GeneralSettingsPayload): GeneralSettingsForm {
  return {
    persona_prompt: payload.assistant?.persona_prompt || '',
    user_address: payload.assistant?.user_address || '',
    bridge_enabled: payload.bridge?.enabled !== false,
    bridge_host: payload.bridge?.host || '127.0.0.1',
    bridge_port: String(payload.bridge?.port || 8420),
    display_mode: payload.display?.current_mode || 'bubble',
    tray_enabled: payload.app?.tray_enabled !== false,
    backup_auto_cleanup_enabled: payload.backup?.auto_cleanup_enabled !== false,
    backup_retention_count: String(payload.backup?.retention_count || 10),
  };
}

function countGeneralSettingsPendingChanges(
  payload: GeneralSettingsPayload | null,
  form: GeneralSettingsForm,
): number {
  if (!payload) return 0;
  let count = 0;
  if ((payload.assistant?.persona_prompt || '') !== form.persona_prompt) count += 1;
  if ((payload.assistant?.user_address || '') !== form.user_address) count += 1;
  if ((payload.bridge?.enabled !== false) !== form.bridge_enabled) count += 1;
  if ((payload.bridge?.host || '127.0.0.1') !== form.bridge_host.trim()) count += 1;
  if (String(payload.bridge?.port || 8420) !== form.bridge_port.trim()) count += 1;
  if ((payload.display?.current_mode || 'bubble') !== form.display_mode) count += 1;
  if ((payload.app?.tray_enabled !== false) !== form.tray_enabled) count += 1;
  if ((payload.backup?.auto_cleanup_enabled !== false) !== form.backup_auto_cleanup_enabled) count += 1;
  if (String(payload.backup?.retention_count || 10) !== form.backup_retention_count.trim()) count += 1;
  return count;
}

function buildGeneralSettingsChanges(
  payload: GeneralSettingsPayload | null,
  form: GeneralSettingsForm,
): Record<string, string | number | boolean> {
  if (!payload) return {};
  const changes: Record<string, string | number | boolean> = {};
  const bridgePort = Number(form.bridge_port);
  const currentPort = Number(payload.bridge?.port || 8420);
  const backupRetentionCount = Number(form.backup_retention_count);
  const currentBackupRetentionCount = Number(payload.backup?.retention_count || 10);
  if ((payload.assistant?.persona_prompt || '') !== form.persona_prompt) {
    changes['assistant.persona_prompt'] = form.persona_prompt;
  }
  if ((payload.assistant?.user_address || '') !== form.user_address) {
    changes['assistant.user_address'] = form.user_address;
  }
  if ((payload.bridge?.enabled !== false) !== form.bridge_enabled) {
    changes.bridge_enabled = form.bridge_enabled;
  }
  if ((payload.bridge?.host || '127.0.0.1') !== form.bridge_host.trim()) {
    changes.bridge_host = form.bridge_host.trim();
  }
  if (Number.isFinite(bridgePort) && bridgePort !== currentPort) {
    changes.bridge_port = bridgePort;
  }
  if ((payload.display?.current_mode || 'bubble') !== form.display_mode) {
    changes.display_mode = form.display_mode;
  }
  if ((payload.app?.tray_enabled !== false) !== form.tray_enabled) {
    changes.tray_enabled = form.tray_enabled;
  }
  if ((payload.backup?.auto_cleanup_enabled !== false) !== form.backup_auto_cleanup_enabled) {
    changes['backup.auto_cleanup_enabled'] = form.backup_auto_cleanup_enabled;
  }
  if (Number.isFinite(backupRetentionCount) && backupRetentionCount !== currentBackupRetentionCount) {
    changes['backup.retention_count'] = backupRetentionCount;
  }
  return changes;
}

function modeFieldSections(mode: string, payload?: SettingsPayload | null): ModeFieldSection[] {
  return mode === 'live2d' ? live2dFieldSections(payload) : BUBBLE_FIELD_SECTIONS;
}

function modeFieldSpecs(mode: string): ModeFieldSpec[] {
  return modeFieldSections(mode).flatMap((section) => section.fields);
}

function formFromModeSettings(payload: SettingsPayload, specs: ModeFieldSpec[]): ModeForm {
  const config = payload.settings?.config || {};
  return specs.reduce<ModeForm>((result, spec) => {
    const value = modeConfigValue(config, spec);
    result[spec.key] = modeFormValue(value, spec);
    return result;
  }, {});
}

function countModePendingChanges(
  payload: SettingsPayload | null,
  form: ModeForm,
  specs: ModeFieldSpec[],
): number {
  if (!payload) return 0;
  const saved = formFromModeSettings(payload, specs);
  return specs.reduce((count, spec) => sameFormValue(saved[spec.key], form[spec.key]) ? count : count + 1, 0);
}

function buildModeSettingsChanges(
  payload: SettingsPayload,
  form: ModeForm,
  specs: ModeFieldSpec[],
): Record<string, ModeParsedValue> {
  const config = payload.settings?.config || {};
  const changes: Record<string, ModeParsedValue> = {};
  specs.forEach((spec) => {
    const parsed = parseModeFieldValue(form[spec.key], spec);
    const current = modeConfigValue(config, spec);
    if (!sameModeConfigValue(current, parsed, spec)) {
      changes[spec.key] = parsed;
    }
  });
  return changes;
}

function shouldActivateLive2DAfterSave(
  mode: string,
  changes: Record<string, ModeParsedValue>,
  activationPending: boolean,
): boolean {
  if (mode !== 'live2d') return false;
  if (activationPending) return true;
  const modelPath = changes['live2d_mode.model_path'];
  return typeof modelPath === 'string' && modelPath.trim().length > 0;
}

function validateModeForm(form: ModeForm, specs: ModeFieldSpec[]): string {
  for (const spec of specs) {
    const raw = form[spec.key];
    if (spec.kind === 'expressionRules') continue;
    if (spec.kind === 'checkbox' || spec.kind === 'text' || spec.kind === 'textarea') continue;
    if (spec.kind === 'select') {
      const value = String(raw ?? '');
      if (!spec.allowCustom && !spec.options?.some((option) => option.value === value)) return `${spec.label} 仅支持当前可选项`;
      continue;
    }
    const text = String(raw ?? '').trim();
    if (!text) return `${spec.label} 不能为空`;
    const number = Number(text);
    if (!Number.isFinite(number)) return `${spec.label} 必须是数字`;
    if (spec.integer && !Number.isInteger(number)) return `${spec.label} 必须是整数`;
    if (spec.min !== undefined && number < spec.min) return rangeError(spec);
    if (spec.max !== undefined && number > spec.max) return rangeError(spec);
  }
  return '';
}

function parseModeFieldValue(value: ModeFormValue | undefined, spec: ModeFieldSpec): ModeParsedValue {
  if (spec.kind === 'checkbox') return Boolean(value);
  if (spec.kind === 'expressionRules') return parseExpressionRulesFormValue(value);
  if (spec.kind === 'number') {
    const number = Number(value);
    return spec.integer ? Math.trunc(number) : number;
  }
  if (spec.kind === 'percent') return Number(value) / 100;
  return String(value ?? '');
}

function modeConfigValue(config: ModeConfig, spec: ModeFieldSpec): unknown {
  return config[spec.sourceKey || spec.key.split('.').pop() || spec.key];
}

function modeFormValue(value: unknown, spec: ModeFieldSpec): ModeFormValue {
  if (spec.kind === 'checkbox') return Boolean(value);
  if (spec.kind === 'expressionRules') return JSON.stringify(cleanStringRecord(value));
  if (spec.kind === 'percent') return formatNumber(Number(value || 0) * 100);
  if (spec.kind === 'number') return value === undefined || value === null ? '' : formatNumber(Number(value));
  return String(value ?? '');
}

function sameModeConfigValue(current: unknown, next: ModeParsedValue, spec: ModeFieldSpec): boolean {
  if (spec.kind === 'checkbox') return Boolean(current) === next;
  if (spec.kind === 'expressionRules') {
    return JSON.stringify(sortStringRecord(cleanStringRecord(current))) === JSON.stringify(sortStringRecord(next));
  }
  if (spec.kind === 'number' || spec.kind === 'percent') return nearlyEqual(Number(current), Number(next));
  return String(current ?? '') === String(next);
}

function sameFormValue(left: ModeFormValue | undefined, right: ModeFormValue | undefined): boolean {
  return typeof left === 'boolean' || typeof right === 'boolean'
    ? Boolean(left) === Boolean(right)
    : String(left ?? '') === String(right ?? '');
}

function nearlyEqual(left: number, right: number): boolean {
  return Number.isFinite(left) && Number.isFinite(right) && Math.abs(left - right) < 0.000001;
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '';
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

function rangeError(spec: ModeFieldSpec): string {
  const unit = spec.kind === 'percent' ? '%' : '';
  if (spec.min !== undefined && spec.max !== undefined) return `${spec.label} 须在 ${spec.min}-${spec.max}${unit} 之间`;
  if (spec.min !== undefined) return `${spec.label} 不能小于 ${spec.min}${unit}`;
  return `${spec.label} 不能大于 ${spec.max}${unit}`;
}

function statusClassName(status: string): string {
  return /失败|错误|必须|不能为空|不能|须在|仅支持|无效/.test(status) ? 'notice danger' : 'notice';
}

function statusToneClassName(status: string): string {
  if (/失败|错误|必须|不能为空|不能|须在|仅支持|无效/.test(status)) return 'danger';
  if (/保存中|正在/.test(status)) return 'pending';
  if (/已保存|已丢弃|完成|已打开/.test(status)) return 'success';
  return '';
}

function fieldId(key: string): string {
  return key.replace(/[^a-zA-Z0-9_-]+/g, '-');
}

function asRecord(value: unknown): ModeConfig {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ModeConfig : {};
}

function stringValue(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

function cleanStringRecord(value: unknown): Record<string, string> {
  const record = asRecord(value);
  return Object.fromEntries(
    Object.entries(record)
      .map(([key, item]) => [key.trim(), stringValue(item).trim()])
      .filter(([key, item]) => Boolean(key && item)),
  );
}

function sortStringRecord(value: unknown): Record<string, string> {
  return Object.fromEntries(
    Object.entries(cleanStringRecord(value)).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function parseExpressionRulesFormValue(value: unknown): Record<string, string> {
  if (typeof value !== 'string') return cleanStringRecord(value);
  try {
    return cleanStringRecord(JSON.parse(value));
  } catch {
    return {};
  }
}

function live2dExpressionIdentifier(expression: Live2DExpressionItem): string {
  return stringValue(expression.name || expression.file).trim();
}

function live2dStateLabel(state: string): string {
  const labels: Record<string, string> = {
    not_configured: '未检测到资源',
    path_invalid: '路径不存在',
    path_not_live2d: '目录无有效模型文件',
    path_valid: '资源已就绪',
    loaded: '已加载',
  };
  return labels[state] || state || '—';
}

function live2dStateClass(state: string): string {
  return state === 'path_valid' || state === 'loaded' ? 'ok' : 'warn';
}

function live2dResourceReady(payload: GeneralSettingsPayload | null): boolean {
  const live2dConfig = asRecord(payload?.mode_settings?.live2d?.config);
  const state = stringValue(live2dConfig.model_state || asRecord(live2dConfig.resource).state);
  return state === 'path_valid' || state === 'loaded';
}

function live2dExpressionSummary(summary: ModeConfig): string {
  const expressions = Array.isArray(summary.expressions) ? summary.expressions : [];
  if (!expressions.length) return '当前模型未声明可选表情';
  return expressions.map((item) => stringValue(asRecord(item).name || asRecord(item).file || '未命名表情')).join(' / ');
}

function live2dExpressionOptions(payload?: SettingsPayload | null): ModeFieldOption[] {
  const options: ModeFieldOption[] = [{ value: '', label: '自动匹配' }];
  const seen = new Set(['']);
  for (const expression of live2dExpressions(payload)) {
    const value = live2dExpressionIdentifier(expression);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    const file = stringValue(expression.file).trim();
    options.push({
      value,
      label: file && file !== value ? `${value} · ${file}` : value,
    });
  }
  return options;
}

function live2dExpressions(payload?: SettingsPayload | null): Live2DExpressionItem[] {
  const config = payload?.settings?.config || {};
  const summary = asRecord(config.summary);
  const expressions = Array.isArray(summary.expressions) ? summary.expressions : [];
  return expressions
    .map((item) => {
      const record = asRecord(item);
      return {
        name: stringValue(record.name).trim(),
        file: stringValue(record.file).trim(),
      };
    })
    .filter((item) => Boolean(live2dExpressionIdentifier(item)));
}

function live2dFieldSections(payload?: SettingsPayload | null): ModeFieldSection[] {
  const expressionOptions = live2dExpressionOptions(payload);
  const expressions = live2dExpressions(payload);
  return LIVE2D_FIELD_SECTIONS.map((section) => ({
    ...section,
    fields: section.fields.map((field) => {
      if (field.kind === 'expressionRules') return { ...field, expressions };
      if (field.key.endsWith('_expression')) return { ...field, options: expressionOptions };
      return field;
    }),
  }));
}

function selectOptionsWithCurrentValue(options: ModeFieldOption[], value: string): ModeFieldOption[] {
  if (!value || options.some((option) => option.value === value)) return options;
  return [...options, { value, label: `${value}（当前配置）` }];
}

function live2dMotionSummary(summary: ModeConfig): string {
  const groups = asRecord(summary.motion_groups);
  const parts = Object.entries(groups).map(([name, items]) => `${name} × ${Array.isArray(items) ? items.length : 0}`);
  return parts.length ? parts.join(' / ') : '当前模型未声明可选动作';
}

const BUBBLE_FIELD_SECTIONS: ModeFieldSection[] = [
  {
    title: '窗口与位置',
    note: '尺寸、默认位置、置顶和头像保存后需要重启当前模式生效；默认位置使用屏幕百分比，100% / 100% 表示右下角。',
    fields: [
      { key: 'bubble_mode.width', sourceKey: 'width', label: '气泡宽度', kind: 'number', min: 80, max: 192, integer: true },
      { key: 'bubble_mode.height', sourceKey: 'height', label: '气泡高度', kind: 'number', min: 80, max: 192, integer: true },
      { key: 'bubble_mode.position_x_percent', sourceKey: 'position_x_percent', label: '默认位置 X', kind: 'percent', min: 0, max: 100, step: '1' },
      { key: 'bubble_mode.position_y_percent', sourceKey: 'position_y_percent', label: '默认位置 Y', kind: 'percent', min: 0, max: 100, step: '1' },
      { key: 'bubble_mode.always_on_top', sourceKey: 'always_on_top', label: '窗口置顶', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.edge_snap', sourceKey: 'edge_snap', label: '靠边吸附', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.expanded_on_start', sourceKey: 'expanded_on_start', label: '启动后展开提示', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.avatar_path', sourceKey: 'avatar_path', label: '头像路径', kind: 'text', wide: true },
    ],
  },
  {
    title: '展示与提醒',
    fields: [
      {
        key: 'bubble_mode.default_display',
        sourceKey: 'default_display',
        label: '默认展示',
        kind: 'select',
        options: [
          { value: 'icon', label: '仅头像图标' },
          { value: 'summary', label: '状态摘要' },
          { value: 'recent_reply', label: '最近回复' },
        ],
      },
      { key: 'bubble_mode.summary_count', sourceKey: 'summary_count', label: '状态摘要条数', kind: 'number', min: 1, max: 3, integer: true },
      { key: 'bubble_mode.show_unread_dot', sourceKey: 'show_unread_dot', label: '新消息呼吸灯', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.auto_hide', sourceKey: 'auto_hide', label: '空闲自动淡出', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.opacity', sourceKey: 'opacity', label: '透明度', kind: 'number', min: 0.2, max: 1, step: '0.01' },
    ],
  },
  {
    title: '主动关怀',
    note: '这些字段只影响气泡模式；统一开关可以在 GPT-SoVITS 页面同步写入 Bubble 和 Live2D。',
    fields: [
      { key: 'bubble_mode.proactive_enabled', sourceKey: 'proactive_enabled', label: '启用主动关怀', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.proactive_desktop_watch_enabled', sourceKey: 'proactive_desktop_watch_enabled', label: '启用桌面观察', kind: 'checkbox', wide: true },
      { key: 'bubble_mode.proactive_interval_seconds', sourceKey: 'proactive_interval_seconds', label: '触发间隔秒', kind: 'number', min: 300, max: 3600, integer: true },
      { key: 'bubble_mode.proactive_trigger_probability', sourceKey: 'proactive_trigger_probability', label: '触发概率', kind: 'percent', min: 0, max: 100, step: '1' },
    ],
  },
];

const LIVE2D_FIELD_SECTIONS: ModeFieldSection[] = [
  {
    title: '模型与舞台',
    fields: [
      { key: 'live2d_mode.scale', sourceKey: 'scale', label: '角色缩放', kind: 'number', min: 0.4, max: 2, step: '0.01' },
      { key: 'live2d_mode.model_name', sourceKey: 'model_name', label: '模型名称', kind: 'text' },
      { key: 'live2d_mode.model_path', sourceKey: 'model_path', label: '模型路径', kind: 'text', wide: true },
      { key: 'live2d_mode.width', sourceKey: 'width', label: '窗口宽度', kind: 'number', min: 240, integer: true },
      { key: 'live2d_mode.height', sourceKey: 'height', label: '窗口高度', kind: 'number', min: 240, integer: true },
      {
        key: 'live2d_mode.position_anchor',
        sourceKey: 'position_anchor',
        label: '默认位置',
        kind: 'select',
        options: [
          { value: 'right_bottom', label: '右下角' },
          { value: 'left_bottom', label: '左下角' },
          { value: 'custom', label: '自定义坐标' },
        ],
      },
      { key: 'live2d_mode.position_x', sourceKey: 'position_x', label: '水平边距 / X', kind: 'number', integer: true },
      { key: 'live2d_mode.position_y', sourceKey: 'position_y', label: '底部 / Y', kind: 'number', integer: true },
      { key: 'live2d_mode.window_on_top', sourceKey: 'window_on_top', label: '窗口置顶', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.show_on_all_spaces', sourceKey: 'show_on_all_spaces', label: 'macOS 所有桌面可见', kind: 'checkbox', wide: true },
    ],
  },
  {
    title: '交互行为',
    note: '启动初始表现只控制回复气泡和快捷输入，不会自动展开主控台对话。',
    fields: [
      { key: 'live2d_mode.show_reply_bubble', sourceKey: 'show_reply_bubble', label: '显示回复气泡', kind: 'checkbox', wide: true },
      {
        key: 'live2d_mode.default_open_behavior',
        sourceKey: 'default_open_behavior',
        label: '启动初始表现',
        kind: 'select',
        options: [
          { value: 'stage', label: '仅角色舞台' },
          { value: 'reply_bubble', label: '显示回复气泡' },
          { value: 'chat_input', label: '显示快捷输入' },
        ],
      },
      {
        key: 'live2d_mode.click_action',
        sourceKey: 'click_action',
        label: '点击角色行为',
        kind: 'select',
        options: [
          { value: 'open_chat', label: '打开主控台对话' },
          { value: 'toggle_reply', label: '切换回复气泡' },
          { value: 'focus_stage', label: '仅聚焦角色窗口' },
        ],
      },
      { key: 'live2d_mode.enable_quick_input', sourceKey: 'enable_quick_input', label: '显示快捷输入入口', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.auto_open_chat_window', sourceKey: 'auto_open_chat_window', label: '启动时打开主控台对话', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.mouse_follow_enabled', sourceKey: 'mouse_follow_enabled', label: '鼠标跟随', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.idle_motion_group', sourceKey: 'idle_motion_group', label: '待机动作组', kind: 'text' },
      { key: 'live2d_mode.enable_expressions', sourceKey: 'enable_expressions', label: '启用表情系统', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.enable_physics', sourceKey: 'enable_physics', label: '启用物理模拟', kind: 'checkbox', wide: true },
    ],
  },
  {
    title: '性能与画质',
    note: '画质预设、帧率、清晰度和透明命中精度会在重启当前 Live2D 模式后完全生效。',
    fields: [
      {
        key: 'live2d_mode.render_quality_preset',
        sourceKey: 'render_quality_preset',
        label: '画质预设',
        kind: 'select',
        options: [
          { value: 'battery', label: '省电' },
          { value: 'balanced', label: '均衡' },
          { value: 'quality', label: '高清' },
          { value: 'custom', label: '自定义' },
        ],
      },
      { key: 'live2d_mode.render_fps', sourceKey: 'render_fps', label: '帧率上限', kind: 'number', min: 12, max: 60, integer: true },
      { key: 'live2d_mode.render_resolution', sourceKey: 'render_resolution', label: '清晰度倍率', kind: 'number', min: 0.5, max: 2, step: '0.05' },
      {
        key: 'live2d_mode.hit_region_precision',
        sourceKey: 'hit_region_precision',
        label: '透明命中精度',
        kind: 'select',
        options: [
          { value: 'low', label: '低' },
          { value: 'medium', label: '中' },
          { value: 'high', label: '高' },
        ],
      },
    ],
  },
  {
    title: '表情映射',
    note: '选项来自当前 model3.json 的 Expressions；每行填写会触发该表情的回复情绪或关键词，逗号、空格、顿号都可以分隔。没有命中时保持默认表情。',
    fields: [
      {
        key: 'live2d_mode.expression_keywords',
        sourceKey: 'expression_keywords',
        label: '回复内容表情规则',
        kind: 'expressionRules',
        wide: true,
      },
    ],
  },
  {
    title: '主动关怀',
    note: '这些字段只影响 Live2D 模式；桌面观察权限和立即测试可在 GPT-SoVITS 页面执行。',
    fields: [
      { key: 'live2d_mode.proactive_enabled', sourceKey: 'proactive_enabled', label: '启用主动关怀', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.proactive_desktop_watch_enabled', sourceKey: 'proactive_desktop_watch_enabled', label: '启用桌面观察', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.proactive_interval_seconds', sourceKey: 'proactive_interval_seconds', label: '触发间隔秒', kind: 'number', min: 300, max: 3600, integer: true },
      { key: 'live2d_mode.proactive_trigger_probability', sourceKey: 'proactive_trigger_probability', label: '触发概率', kind: 'percent', min: 0, max: 100, step: '1' },
    ],
  },
];
