import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { createPortal } from 'react-dom';

import {
  apiGet,
  apiPatch,
  apiPost,
  checkAppUpdate,
  chooseAvatarImage,
  chooseLive2DArchive,
  chooseLive2DModelDirectory,
  hasDesktopAvatarPicker,
  hasDesktopFilePicker,
  openExternalUrl,
  openDesktopMode,
  openPath,
  removeAppBundleAndQuit,
  restartDesktopBridge,
  type AvatarImageSelection,
} from '../lib/bridge';
import {
  listModelProfiles,
  syncHermesProfileDefault,
  updateModelProfileDefaults,
  type ModelProfile,
  type ModelProfileDefaults,
} from '../lib/modelProfiles';
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
  assistant?: {
    agent_name?: string;
    agent_nickname?: string;
    agent_avatar_path?: string;
    agent_avatar_url?: string;
    persona_prompt?: string;
    user_address?: string;
    user_name?: string;
    user_avatar_path?: string;
    user_avatar_url?: string;
    user_profile?: string;
    user_preferences?: string;
  };
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
  display?: {
    current_mode?: string;
    configured_mode?: string;
    available_modes?: Array<{ id: string; name?: string; label?: string; description?: string }>;
  };
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
  agent_name?: string;
  agent_nickname?: string;
  agent_avatar_path?: string;
  agent_avatar_url?: string;
  persona_prompt?: string;
  user_address?: string;
  user_name?: string;
  user_avatar_path?: string;
  user_avatar_url?: string;
  user_profile?: string;
  user_preferences?: string;
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

type HermesSettingsConfig = {
  model?: { provider?: string; default?: string; base_url?: string };
  provider_options?: Array<{ id: string; label?: string; api_key_configured?: boolean; auth_type?: string }>;
  api_key?: { configured?: boolean; display?: string };
  vision?: { effective_provider?: string; model?: string; base_url_configured?: boolean; api_key_configured?: boolean };
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
  start_minimized: boolean;
  tray_enabled: boolean;
  backup_auto_cleanup_enabled: boolean;
  backup_retention_count: string;
};

type AssistantDraft = {
  agent_name: string;
  agent_nickname: string;
  agent_avatar_path: string;
  persona_prompt: string;
  user_address: string;
  user_name: string;
  user_avatar_path: string;
  user_profile: string;
  user_preferences: string;
};
type AvatarTarget = 'agent' | 'user';
type AvatarEditorState = {
  target: AvatarTarget;
  dataUrl: string;
  fileName: string;
  zoom: number;
  offsetX: number;
  offsetY: number;
};

export function ModeSettingsView() {
  const mode = currentParam('mode');
  if (mode === 'system') return <SystemSettingsView />;
  return mode ? <SpecificModeSettingsView mode={mode} /> : <ReferenceSettingsHome />;
}

function emptyAssistantDraft(): AssistantDraft {
  return {
    agent_name: '月見八千代',
    agent_nickname: '月夜',
    agent_avatar_path: '',
    persona_prompt: '',
    user_address: '',
    user_name: '',
    user_avatar_path: '',
    user_profile: '',
    user_preferences: '',
  };
}

function assistantDraftFromProfile(profile?: AssistantProfilePayload | null): AssistantDraft {
  return {
    agent_name: profile?.agent_name || '月見八千代',
    agent_nickname: profile?.agent_nickname || '月夜',
    agent_avatar_path: profile?.agent_avatar_path || '',
    persona_prompt: profile?.persona_prompt || '',
    user_address: profile?.user_address || '',
    user_name: profile?.user_name || '',
    user_avatar_path: profile?.user_avatar_path || '',
    user_profile: profile?.user_profile || '',
    user_preferences: profile?.user_preferences || '',
  };
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('读取图片失败'));
    reader.readAsDataURL(file);
  });
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('头像图片无法预览'));
    image.src = src;
  });
}

async function cropAvatarDataUrl(editor: AvatarEditorState): Promise<string> {
  const image = await loadImageElement(editor.dataUrl);
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('当前环境无法裁剪头像');
  const naturalWidth = image.naturalWidth || image.width;
  const naturalHeight = image.naturalHeight || image.height;
  if (!naturalWidth || !naturalHeight) throw new Error('头像图片尺寸无效');
  const baseScale = Math.max(size / naturalWidth, size / naturalHeight);
  const scale = baseScale * Math.max(1, editor.zoom);
  const drawWidth = naturalWidth * scale;
  const drawHeight = naturalHeight * scale;
  const drawX = (size - drawWidth) / 2 + editor.offsetX * size;
  const drawY = (size - drawHeight) / 2 + editor.offsetY * size;
  context.clearRect(0, 0, size, size);
  context.drawImage(image, drawX, drawY, drawWidth, drawHeight);
  return canvas.toDataURL('image/png');
}

function ReferenceSettingsHome() {
  const [payload, setPayload] = useState<GeneralSettingsPayload | null>(null);
  const [assistantProfile, setAssistantProfile] = useState<AssistantProfilePayload | null>(null);
  const [assistantDraft, setAssistantDraft] = useState<AssistantDraft>(() => emptyAssistantDraft());
  const [assistantSaving, setAssistantSaving] = useState(false);
  const [avatarImporting, setAvatarImporting] = useState<AvatarTarget | ''>('');
  const [avatarEditor, setAvatarEditor] = useState<AvatarEditorState | null>(null);
  const [assistantStatus, setAssistantStatus] = useState('');
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [modelLoading, setModelLoading] = useState(true);
  const [assistantLoading, setAssistantLoading] = useState(true);
  const [hermesConfig, setHermesConfig] = useState<HermesSettingsConfig | null>(null);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [modelDefaults, setModelDefaults] = useState<ModelProfileDefaults>({});
  const [modelProfileStatus, setModelProfileStatus] = useState('');
  const [profileApplying, setProfileApplying] = useState<'chat' | 'vision' | ''>('');
  const [connectionTestResult, setConnectionTestResult] = useState<{ success?: boolean; ok?: boolean; error?: string; message?: string } | null>(null);
  const [connectionTesting, setConnectionTesting] = useState(false);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateResult, setUpdateResult] = useState<{ checked?: boolean; update_available?: boolean; reason?: string } | null>(null);
  const agentAvatarFileRef = useRef<HTMLInputElement>(null);
  const userAvatarFileRef = useRef<HTMLInputElement>(null);

  const FALLBACK_PROVIDER_OPTIONS: Array<{ id: string; label: string; api_key_configured?: boolean }> = [
    { id: 'openai', label: 'OpenAI' },
    { id: 'anthropic', label: 'Anthropic' },
    { id: 'local', label: '本地模型' },
  ];

  useEffect(() => {
    let disposed = false;
    void Promise.allSettled([
      apiGet<GeneralSettingsPayload>('/ui/settings'),
      apiGet<HermesSettingsConfig>('/ui/hermes/config'),
      apiGet<AssistantProfilePayload>('/assistant/profile'),
      listModelProfiles(),
    ]).then(([settingsResult, configResult, profileResult, modelProfileResult]) => {
      if (disposed) return;
      if (settingsResult.status === 'fulfilled') setPayload(settingsResult.value);
      if (configResult.status === 'fulfilled') {
        setHermesConfig(configResult.value);
      }
      if (profileResult.status === 'fulfilled') {
        setAssistantProfile(profileResult.value);
        setAssistantDraft(assistantDraftFromProfile(profileResult.value));
      }
      if (modelProfileResult.status === 'fulfilled') {
        setModelProfiles(modelProfileResult.value.profiles || []);
        setModelDefaults(modelProfileResult.value.defaults || {});
      }
      setSettingsLoading(false);
      setModelLoading(false);
      setAssistantLoading(false);
    });
    return () => { disposed = true; };
  }, []);

  async function saveAssistantProfile() {
    if (assistantSaving) return;
    setAssistantSaving(true);
    setAssistantStatus('正在保存助手资料...');
    try {
      const result = await apiPatch<AssistantProfilePayload>('/assistant/profile', {
        agent_name: assistantDraft.agent_name,
        agent_nickname: assistantDraft.agent_nickname,
        agent_avatar_path: assistantDraft.agent_avatar_path,
        user_address: assistantDraft.user_address,
        user_name: assistantDraft.user_name,
        user_avatar_path: assistantDraft.user_avatar_path,
        user_profile: assistantDraft.user_profile,
        user_preferences: assistantDraft.user_preferences,
        persona_prompt: assistantDraft.persona_prompt,
      });
      if (result.ok === false) throw new Error(result.message || '保存助手资料失败');
      setAssistantProfile(result);
      setAssistantDraft(assistantDraftFromProfile(result));
      setPayload((current) => current ? {
        ...current,
        assistant: {
          ...(current.assistant || {}),
          agent_name: result.agent_name || '',
          agent_nickname: result.agent_nickname || '',
          agent_avatar_path: result.agent_avatar_path || '',
          agent_avatar_url: result.agent_avatar_url || '',
          user_address: result.user_address || '',
          user_name: result.user_name || '',
          user_avatar_path: result.user_avatar_path || '',
          user_avatar_url: result.user_avatar_url || '',
          user_profile: result.user_profile || '',
          user_preferences: result.user_preferences || '',
          persona_prompt: result.persona_prompt || '',
        },
      } : current);
      setAssistantStatus(result.message || '助手资料已保存');
      window.dispatchEvent(new CustomEvent('hermes-assistant-profile-updated'));
    } catch (err) {
      setAssistantStatus(err instanceof Error ? err.message : '保存助手资料失败');
    } finally {
      setAssistantSaving(false);
    }
  }

  function applyImportedAvatar(target: AvatarTarget, result: AssistantProfilePayload) {
    setAssistantProfile(result);
    setAssistantDraft((current) => ({
      ...current,
      agent_avatar_path: target === 'agent' ? result.agent_avatar_path || '' : current.agent_avatar_path,
      user_avatar_path: target === 'user' ? result.user_avatar_path || '' : current.user_avatar_path,
    }));
    setPayload((current) => current ? {
      ...current,
      assistant: {
        ...(current.assistant || {}),
        agent_avatar_path: result.agent_avatar_path || current.assistant?.agent_avatar_path || '',
        agent_avatar_url: result.agent_avatar_url || current.assistant?.agent_avatar_url || '',
        user_avatar_path: result.user_avatar_path || current.assistant?.user_avatar_path || '',
        user_avatar_url: result.user_avatar_url || current.assistant?.user_avatar_url || '',
      },
    } : current);
    setAssistantStatus(result.message || '头像已更新');
    window.dispatchEvent(new CustomEvent('hermes-assistant-profile-updated'));
  }

  function openAvatarEditor(target: AvatarTarget, selection: AvatarImageSelection) {
    if (!selection.data_url) {
      setAssistantStatus('头像预览读取失败，请重新选择图片');
      return;
    }
    setAvatarEditor({
      target,
      dataUrl: selection.data_url,
      fileName: selection.file_name || `${target}-avatar.png`,
      zoom: 1,
      offsetX: 0,
      offsetY: 0,
    });
    setAssistantStatus('');
  }

  async function importAvatarFromPath(target: AvatarTarget) {
    if (avatarImporting || assistantSaving) return;
    if (!hasDesktopAvatarPicker()) {
      (target === 'agent' ? agentAvatarFileRef : userAvatarFileRef).current?.click();
      return;
    }
    setAssistantStatus('正在读取头像图片...');
    try {
      const selectedPath = await chooseAvatarImage();
      if (!selectedPath) {
        setAssistantStatus('已取消选择头像');
        return;
      }
      if (typeof selectedPath === 'string') {
        setAvatarImporting(target);
        const result = await apiPost<AssistantProfilePayload>('/assistant/profile/avatar/import', { target, path: selectedPath });
        applyImportedAvatar(target, result);
        setAvatarImporting('');
        setAssistantStatus('头像已更新；重启应用后可使用裁剪预览');
        return;
      }
      openAvatarEditor(target, selectedPath);
    } catch (err) {
      setAvatarImporting('');
      setAssistantStatus(err instanceof Error ? err.message : '读取头像失败');
    }
  }

  async function importAvatarFromFile(target: AvatarTarget, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || avatarImporting || assistantSaving) return;
    if (!file.type.startsWith('image/')) {
      setAssistantStatus('请选择图片文件');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setAssistantStatus('头像图片不能超过 5 MB');
      return;
    }
    setAssistantStatus('正在读取头像图片...');
    try {
      const dataUrl = await readFileAsDataUrl(file);
      openAvatarEditor(target, {
        data_url: dataUrl,
        file_name: file.name,
      });
    } catch (err) {
      setAssistantStatus(err instanceof Error ? err.message : '读取图片失败');
    }
  }

  function updateAvatarEditor(changes: Partial<AvatarEditorState>) {
    setAvatarEditor((current) => current ? { ...current, ...changes } : current);
  }

  async function applyAvatarEditor() {
    if (!avatarEditor || avatarImporting || assistantSaving) return;
    setAvatarImporting(avatarEditor.target);
    setAssistantStatus(avatarEditor.target === 'agent' ? '正在应用 Agent 头像...' : '正在应用用户头像...');
    try {
      const croppedDataUrl = await cropAvatarDataUrl(avatarEditor);
      const result = await apiPost<AssistantProfilePayload>('/assistant/profile/avatar/import', {
        target: avatarEditor.target,
        data_url: croppedDataUrl,
        file_name: avatarEditor.fileName || `${avatarEditor.target}-avatar.png`,
      });
      if (result.ok === false) throw new Error(result.message || '导入头像失败');
      applyImportedAvatar(avatarEditor.target, result);
      setAvatarEditor(null);
    } catch (err) {
      setAssistantStatus(err instanceof Error ? err.message : '应用头像失败');
    } finally {
      setAvatarImporting('');
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

  async function applyModelProfileDefault(capability: 'chat' | 'vision', profileId: string) {
    if (!profileId || profileApplying) return;
    setProfileApplying(capability);
    setModelProfileStatus(capability === 'chat' ? '正在同步主模型...' : '正在同步图片识别模型...');
    try {
      const sync = await syncHermesProfileDefault(capability, profileId);
      if (sync.ok === false) throw new Error(sync.error || sync.message || '同步 Hermes 配置失败');
      const defaults = await updateModelProfileDefaults({ [capability]: profileId });
      setModelDefaults(defaults.defaults || {});
      const [nextConfig, nextProfiles] = await Promise.all([
        apiGet<HermesSettingsConfig>('/ui/hermes/config'),
        listModelProfiles(),
      ]);
      setHermesConfig(nextConfig);
      setModelProfiles(nextProfiles.profiles || []);
      setModelProfileStatus(capability === 'chat' ? '主模型已同步' : '图片识别模型已同步');
    } catch (err) {
      setModelProfileStatus(err instanceof Error ? err.message : '模型配置同步失败');
    } finally {
      setProfileApplying('');
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
        if (result.update_available) {
          window.setTimeout(() => navigateTo('app-update'), 250);
        }
      }
    } catch (err) {
      setUpdateResult({ checked: true, update_available: false, reason: err instanceof Error ? err.message : '检查更新失败' });
    } finally {
      setUpdateChecking(false);
    }
  }

  const appVersion = payload?.app?.version || '0.1.0';
  const trayEnabled = payload?.app?.tray_enabled !== false;
  const startMinimized = Boolean(payload?.app?.start_minimized);
  const providerOptions = hermesConfig?.provider_options?.length ? hermesConfig.provider_options : FALLBACK_PROVIDER_OPTIONS;
  const realProvider = hermesConfig?.model?.provider || '';
  const currentProvider = realProvider || providerOptions[0]?.id || 'openai';
  const currentProviderOption = providerOptions.find((opt) => opt.id === currentProvider);
  const apiKeyConfigured = currentProviderOption?.api_key_configured ?? hermesConfig?.api_key?.configured ?? false;
  const apiKeyDisplay = hermesConfig?.api_key?.display || '';
  const availableChatProfiles = modelProfiles.filter((profile) => profile.capability === 'chat' && profile.status === 'available' && profile.enabled !== false);
  const availableVisionProfiles = modelProfiles.filter((profile) => profile.capability === 'vision' && profile.status === 'available' && profile.enabled !== false);
  const selectedChatProfileId = modelDefaults.chat || '';
  const selectedVisionProfileId = modelDefaults.vision || '';
  const selectedChatProfile = availableChatProfiles.find((profile) => profile.profile_id === selectedChatProfileId);
  const selectedVisionProfile = availableVisionProfiles.find((profile) => profile.profile_id === selectedVisionProfileId);

  const connectionTestOk = connectionTestResult?.success ?? connectionTestResult?.ok;
  const connectionTestMessage = connectionTestResult?.error || connectionTestResult?.message || '连接失败，请检查模型配置';

  const updateDescription = updateResult?.checked
    ? (updateResult.update_available ? (updateResult.reason || '发现可用更新') : (updateResult.reason || '当前已是最新版本'))
    : `Hermes Yachiyo v${appVersion}`;
  const avatarEditorModal = avatarEditor ? (
    <AvatarEditorModal
      editor={avatarEditor}
      importing={avatarImporting === avatarEditor.target}
      onApply={() => void applyAvatarEditor()}
      onClose={() => setAvatarEditor(null)}
      onUpdate={updateAvatarEditor}
    />
  ) : null;
  const avatarEditorPortalTarget = typeof document !== 'undefined'
    ? document.querySelector('.hy-shell') || document.body
    : null;

  return (
    <main className="app-shell settings-page">
      <div className="settings-page-header">
        <div className="settings-page-title">设置</div>
        <div className="settings-page-subtitle">配置 Hermes Yachiyo 的各项参数</div>
      </div>

      <SettingsSection title="通用">
        <SettingsItem label="高级设置" description={settingsLoading ? '正在读取系统偏好...' : `启动${startMinimized ? '最小化' : '显示窗口'} · 托盘${trayEnabled ? '已启用' : '已禁用'} · Bridge 与维护`}>
          <SettingsActionButton disabled={settingsLoading} loading={settingsLoading} onClick={() => navigateTo('settings', { mode: 'system' })}>
            {settingsLoading ? '读取中…' : '打开'}
          </SettingsActionButton>
        </SettingsItem>
      </SettingsSection>

      <SettingsSection title="Agent 与 Prompt">
        {assistantLoading ? (
          <SettingsLoadingRows count={5} />
        ) : (
          <>
            <SettingsItem
              label="主 Agent 信息"
              description="侧边栏、待机状态和对话头像使用这里的资料"
              wide
            >
              <div className="settings-profile-grid">
                <label>
                  <span>全称</span>
                  <input
                    className="settings-input"
                    value={assistantDraft.agent_name}
                    maxLength={80}
                    placeholder="月見八千代"
                    disabled={assistantSaving}
                    onChange={(event) => {
                      setAssistantDraft((current) => ({ ...current, agent_name: event.target.value }));
                      if (assistantStatus) setAssistantStatus('');
                    }}
                  />
                </label>
                <label>
                  <span>昵称</span>
                  <input
                    className="settings-input"
                    value={assistantDraft.agent_nickname}
                    maxLength={40}
                    placeholder="月夜"
                    disabled={assistantSaving}
                    onChange={(event) => {
                      setAssistantDraft((current) => ({ ...current, agent_nickname: event.target.value }));
                      if (assistantStatus) setAssistantStatus('');
                    }}
                  />
                </label>
                <label className="settings-profile-grid-wide">
                  <span>头像</span>
                  <div className="settings-avatar-field">
                    <span className="settings-avatar-preview">
                      {assistantProfile?.agent_avatar_url ? <img src={assistantProfile.agent_avatar_url} alt="" /> : '月'}
                    </span>
                    <div className="settings-avatar-actions">
                      <SettingsActionButton
                        disabled={assistantSaving || Boolean(avatarImporting)}
                        loading={avatarImporting === 'agent'}
                        onClick={() => void importAvatarFromPath('agent')}
                      >
                        {avatarImporting === 'agent' ? '导入中…' : '选择图片'}
                      </SettingsActionButton>
                      <span>{assistantDraft.agent_avatar_path ? '已导入自定义头像' : '使用默认头像'}</span>
                    </div>
                    <input
                      ref={agentAvatarFileRef}
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      hidden
                      onChange={(event) => void importAvatarFromFile('agent', event)}
                    />
                  </div>
                </label>
              </div>
            </SettingsItem>
            <SettingsItem
              label="人格 Prompt"
              description="用于塑造 Agent 的语气、边界与任务优先级"
              wide
            >
              <textarea
                className="settings-textarea settings-persona-textarea"
                value={assistantDraft.persona_prompt}
                maxLength={12000}
                rows={12}
                placeholder="输入八千代的人格、语气和边界设定"
                disabled={assistantSaving}
                onChange={(event) => {
                  setAssistantDraft((current) => ({ ...current, persona_prompt: event.target.value }));
                  if (assistantStatus) setAssistantStatus('');
                }}
              />
            </SettingsItem>
            <SettingsItem
              label="用户资料"
              description="除头像外会写入 Prompt，影响后续回复"
              wide
            >
              <div className="settings-profile-grid">
                <label>
                  <span>称呼</span>
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
                </label>
                <label>
                  <span>用户名称</span>
                  <input
                    className="settings-input"
                    value={assistantDraft.user_name}
                    maxLength={80}
                    placeholder="可选"
                    disabled={assistantSaving}
                    onChange={(event) => {
                      setAssistantDraft((current) => ({ ...current, user_name: event.target.value }));
                      if (assistantStatus) setAssistantStatus('');
                    }}
                  />
                </label>
                <label className="settings-profile-grid-wide">
                  <span>用户头像</span>
                  <div className="settings-avatar-field">
                    <span className="settings-avatar-preview user">
                      {assistantProfile?.user_avatar_url ? <img src={assistantProfile.user_avatar_url} alt="" /> : '你'}
                    </span>
                    <div className="settings-avatar-actions">
                      <SettingsActionButton
                        disabled={assistantSaving || Boolean(avatarImporting)}
                        loading={avatarImporting === 'user'}
                        onClick={() => void importAvatarFromPath('user')}
                      >
                        {avatarImporting === 'user' ? '导入中…' : '选择图片'}
                      </SettingsActionButton>
                      <span>{assistantDraft.user_avatar_path ? '已导入自定义头像' : '未设置用户头像'}</span>
                    </div>
                    <input
                      ref={userAvatarFileRef}
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      hidden
                      onChange={(event) => void importAvatarFromFile('user', event)}
                    />
                  </div>
                </label>
                <label className="settings-profile-grid-wide">
                  <span>基本信息</span>
                  <textarea
                    className="settings-textarea"
                    value={assistantDraft.user_profile}
                    maxLength={2000}
                    rows={4}
                    placeholder="例如：职业、常用语言、工作习惯"
                    disabled={assistantSaving}
                    onChange={(event) => {
                      setAssistantDraft((current) => ({ ...current, user_profile: event.target.value }));
                      if (assistantStatus) setAssistantStatus('');
                    }}
                  />
                </label>
                <label className="settings-profile-grid-wide">
                  <span>偏好</span>
                  <textarea
                    className="settings-textarea"
                    value={assistantDraft.user_preferences}
                    maxLength={2000}
                    rows={4}
                    placeholder="例如：回答风格、代码偏好、提醒方式"
                    disabled={assistantSaving}
                    onChange={(event) => {
                      setAssistantDraft((current) => ({ ...current, user_preferences: event.target.value }));
                      if (assistantStatus) setAssistantStatus('');
                    }}
                  />
                </label>
              </div>
            </SettingsItem>
            <SettingsItem
              label="资料同步"
              description={`记忆范围：${assistantProfile?.memory_enabled ? '已启用' : '暂未启用'} · ${assistantProfile?.memory_scope || 'local_only'}`}
            >
              <span className={`status-pill ${/失败|错误/.test(assistantStatus) ? 'warn' : assistantStatus ? 'ok' : 'warn'}`}>
                {assistantStatus || '读取自 Bridge'}
              </span>
              <SettingsActionButton
                loading={assistantSaving}
                onClick={() => void saveAssistantProfile()}
              >
                {assistantSaving ? '保存中…' : '保存资料'}
              </SettingsActionButton>
            </SettingsItem>
          </>
        )}
      </SettingsSection>

      <SettingsSection title="模型">
        {modelLoading ? (
          <SettingsLoadingRows count={3} />
        ) : (
          <>
            <SettingsItem label="模型组管理" description="统一保存、测试并复用文本、图片识别和 TTS 模型配置">
              <SettingsActionButton onClick={() => navigateTo('provider')}>打开新版模型配置</SettingsActionButton>
            </SettingsItem>
            <SettingsItem
              label="当前主模型"
              description={selectedChatProfile ? `${selectedChatProfile.name} · ${selectedChatProfile.model || '未记录模型 ID'}` : `${currentProviderOption?.label || currentProvider || '未读取到模型配置'} · ${apiKeyConfigured ? `密钥已配置${apiKeyDisplay ? `：${apiKeyDisplay}` : ''}` : '密钥未配置'}`}
            >
              <select
                className="settings-select settings-profile-select"
                value={selectedChatProfileId}
                disabled={profileApplying === 'chat'}
                onChange={(event) => void applyModelProfileDefault('chat', event.target.value)}
              >
                <option value="">选择已测试主模型</option>
                {availableChatProfiles.map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>{profile.name} · {profile.model}</option>
                ))}
              </select>
              <SettingsActionButton onClick={() => navigateTo('provider')}>管理</SettingsActionButton>
            </SettingsItem>
            <SettingsItem
              label="图片识别模型"
              description={selectedVisionProfile ? `${selectedVisionProfile.name} · ${selectedVisionProfile.model || '未记录模型 ID'}` : hermesConfig?.vision?.model ? `${hermesConfig.vision.effective_provider || 'vision'} · ${hermesConfig.vision.model}` : '选择已通过多模态测试的 vision Profile'}
            >
              <select
                className="settings-select settings-profile-select"
                value={selectedVisionProfileId}
                disabled={profileApplying === 'vision'}
                onChange={(event) => void applyModelProfileDefault('vision', event.target.value)}
              >
                <option value="">选择已测试视觉模型</option>
                {availableVisionProfiles.map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>{profile.name} · {profile.model}</option>
                ))}
              </select>
              <SettingsActionButton onClick={() => navigateTo('provider')}>管理</SettingsActionButton>
            </SettingsItem>
            <SettingsItem label="Agent 模型" description="Agent Studio 只引用已验证的文本与图片识别模型组，不再在每个 Agent 里重复保存 API Key">
              <SettingsActionButton onClick={() => navigateTo('agents')}>打开 Agent Studio</SettingsActionButton>
            </SettingsItem>
            {modelProfileStatus ? (
              <SettingsItem label="模型同步状态" description={modelProfileStatus}>
                <span className={`status-pill ${/失败|错误|不能为空|不存在/.test(modelProfileStatus) ? 'warn' : 'ok'}`}>
                  {profileApplying ? '同步中' : '完成'}
                </span>
              </SettingsItem>
            ) : null}
          </>
        )}
      </SettingsSection>

      <SettingsSection title="关于">
        <SettingsItem label="版本" description={updateDescription}>
          <SettingsActionButton
            loading={updateChecking}
            onClick={() => updateResult?.update_available ? navigateTo('app-update') : void runUpdateCheck()}
          >
            {updateChecking ? '检查中…' : updateResult?.update_available ? '前往更新' : '检查更新'}
          </SettingsActionButton>
        </SettingsItem>
        <SettingsItem label="Hermes Agent 更新" description="更新 Hermes 后会刷新工具清单、Doctor 结果和 Yachiyo 的工具配置入口">
          <SettingsActionButton onClick={() => navigateTo('tools')}>打开工具中心</SettingsActionButton>
        </SettingsItem>
        <SettingsItem label="项目主页" description="github.com/kuguya-AI-app-develop/Hermes-Yachiyo">
          <SettingsActionButton onClick={() => void openExternalUrl('https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo')}>打开</SettingsActionButton>
        </SettingsItem>
      </SettingsSection>

      {avatarEditorModal && avatarEditorPortalTarget
        ? createPortal(avatarEditorModal, avatarEditorPortalTarget)
        : avatarEditorModal}
    </main>
  );
}

function AvatarEditorModal({
  editor,
  importing,
  onApply,
  onClose,
  onUpdate,
}: {
  editor: AvatarEditorState;
  importing: boolean;
  onApply: () => void;
  onClose: () => void;
  onUpdate: (changes: Partial<AvatarEditorState>) => void;
}) {
  const targetLabel = editor.target === 'agent' ? 'Agent 头像' : '用户头像';
  const imageStyle = {
    transform: `translate(-50%, -50%) translate(${editor.offsetX * 220}px, ${editor.offsetY * 220}px) scale(${editor.zoom})`,
  };
  return (
    <div className="avatar-editor-backdrop" role="presentation">
      <section className="avatar-editor-modal" role="dialog" aria-modal="true" aria-label={`${targetLabel}裁剪`}>
        <div className="avatar-editor-head">
          <div>
            <strong>{targetLabel}</strong>
            <span>预览裁剪结果，确认后会立即应用到界面和配置。</span>
          </div>
          <button type="button" className="avatar-editor-close" aria-label="关闭头像裁剪" onClick={onClose}>×</button>
        </div>
        <div className="avatar-editor-body">
          <div className="avatar-crop-stage">
            <div className="avatar-crop-frame">
              <img src={editor.dataUrl} alt="" style={imageStyle} />
            </div>
          </div>
          <div className="avatar-editor-controls">
            <label>
              <span>缩放</span>
              <input
                type="range"
                min="1"
                max="3"
                step="0.01"
                value={editor.zoom}
                onChange={(event) => onUpdate({ zoom: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>水平位置</span>
              <input
                type="range"
                min="-0.45"
                max="0.45"
                step="0.01"
                value={editor.offsetX}
                onChange={(event) => onUpdate({ offsetX: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>垂直位置</span>
              <input
                type="range"
                min="-0.45"
                max="0.45"
                step="0.01"
                value={editor.offsetY}
                onChange={(event) => onUpdate({ offsetY: Number(event.target.value) })}
              />
            </label>
          </div>
        </div>
        <div className="avatar-editor-actions">
          <SettingsActionButton disabled={importing} onClick={onClose}>取消</SettingsActionButton>
          <SettingsActionButton variant="primary" loading={importing} onClick={onApply}>
            {importing ? '应用中…' : '应用头像'}
          </SettingsActionButton>
        </div>
      </section>
    </div>
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
      setStatus(settingsSaveErrorMessage(err));
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

function SettingsLoadingRows({ count = 2 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div className="settings-item settings-item-loading" aria-hidden="true" key={index}>
          <div className="settings-item-info">
            <div className="settings-skeleton-line title" />
            <div className="settings-skeleton-line detail" />
          </div>
          <div className="settings-skeleton-control" />
        </div>
      ))}
    </>
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
    setStatus(modeId === configuredDisplayMode(payload)
      ? `当前已选择 ${modeLabel(modeId)}`
      : `已选择 ${modeLabel(modeId)}，保存后生效`);
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
        setStatus(targetMode === 'none' ? '已保存，已关闭常驻表现态' : `已保存，表现态已切换到 ${modeLabel(targetMode)}`);
      } else if (result.effects?.has_restart_bridge) {
        setStatus('已保存；Bridge 配置需要点击“应用配置并重启 Bridge”后生效');
      } else if (result.effects?.has_restart_app) {
        setStatus(`已保存，${result.effects.hint || '部分配置将在下次启动后生效'}`);
      } else {
        setStatus(result.effects?.hint ? `已保存，${result.effects.hint}` : '已保存');
      }
    } catch (err) {
      setStatus(settingsSaveErrorMessage(err));
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
        <button type="button" className="page-back-link" onClick={() => navigateTo('settings', {}, ['mode', 'reason'])}>← 返回设置</button>
        <div className="settings-page-title">系统设置</div>
        <div className="settings-page-subtitle">高级配置和系统维护</div>
      </div>

      {status ? <div className={statusClassName(status)}>{status}</div> : null}

      <form onSubmit={submitSettings} noValidate>
        <SettingsSection title="通用">
          <SettingsItem label="启动时最小化" description="下次启动应用时先进入后台，不主动弹出主窗口">
            <SettingsToggle
              checked={form.start_minimized}
              onChange={(next) => setForm((current) => ({ ...current, start_minimized: next }))}
            />
          </SettingsItem>
          <SettingsItem label="最小化到托盘" description="关闭窗口时最小化到系统托盘">
            <SettingsToggle
              checked={form.tray_enabled}
              onChange={(next) => setForm((current) => ({ ...current, tray_enabled: next }))}
            />
          </SettingsItem>
        </SettingsSection>

        <SettingsSection title="显示模式">
          <SettingsItem label="常驻表现态" description={displayModeDescription(form.display_mode, payload)}>
            <div className="segmented-list">
              {displayModeOptions(payload).map((item) => (
                <button
                  className={item.id === form.display_mode ? 'selected' : ''}
                  type="button"
                  aria-pressed={item.id === form.display_mode}
                  key={item.id}
                  onClick={() => void selectDisplayMode(item.id)}
                >
                  {item.name || item.label || item.id}
                </button>
              ))}
            </div>
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
          <SettingsItem label="应用更新" description={`Hermes Yachiyo v${payload?.app?.version || '0.1.0'} · 下载进度和版本差异在更新页处理`}>
            <SettingsActionButton onClick={() => navigateTo('app-update')}>打开更新页</SettingsActionButton>
          </SettingsItem>
          <SettingsItem label="Hermes Agent 更新" description="Hermes 自身功能、toolset 和 provider 能力在工具中心更新并重新同步">
            <SettingsActionButton onClick={() => navigateTo('tools')}>打开工具中心</SettingsActionButton>
          </SettingsItem>
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

function modeLabel(mode: string) {
  if (mode === 'none') return '不显示表现态';
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
    start_minimized: false,
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
    display_mode: configuredDisplayMode(payload),
    start_minimized: Boolean(payload.app?.start_minimized),
    tray_enabled: payload.app?.tray_enabled !== false,
    backup_auto_cleanup_enabled: payload.backup?.auto_cleanup_enabled !== false,
    backup_retention_count: String(payload.backup?.retention_count || 10),
  };
}

function configuredDisplayMode(payload: GeneralSettingsPayload | null): string {
  return payload?.display?.configured_mode || payload?.display?.current_mode || 'bubble';
}

function displayModeDescription(mode: string, payload: GeneralSettingsPayload | null): string {
  const configured = configuredDisplayMode(payload);
  if (mode === 'none') return configured === 'none' ? '关闭常驻 Bubble / Live2D，仅保留主控台' : '保存后关闭常驻表现态';
  if (mode === 'live2d') return mode === configured ? '当前常驻 Live2D' : '保存后切换到 Live2D';
  return mode === configured ? '当前常驻 Bubble' : '保存后切换到 Bubble';
}

function displayModeOptions(payload: GeneralSettingsPayload | null): Array<{ id: string; name?: string; label?: string; description?: string }> {
  const options = payload?.display?.available_modes || [];
  if (options.some((item) => item.id === 'none')) return options;
  return [
    { id: 'none', name: '不显示表现态', description: '不打开常驻 Bubble 或 Live2D，只保留主控台' },
    ...options,
  ];
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
  if (configuredDisplayMode(payload) !== form.display_mode) count += 1;
  if (Boolean(payload.app?.start_minimized) !== form.start_minimized) count += 1;
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
  if (configuredDisplayMode(payload) !== form.display_mode) {
    changes.display_mode = form.display_mode;
  }
  if (Boolean(payload.app?.start_minimized) !== form.start_minimized) {
    changes.start_minimized = form.start_minimized;
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

function settingsSaveErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : '保存失败';
  if (message.includes('start_minimized') || message.includes('tray_enabled')) {
    return 'Bridge 还在运行旧设置模型，请重启 Bridge 或应用后再保存系统启动设置';
  }
  return message;
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
