import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
  apiGet,
  apiPost,
  chooseLive2DArchive,
  chooseLive2DModelDirectory,
  hasDesktopFilePicker,
  openExternalUrl,
  openDesktopMode,
  openPath,
  quitApp,
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
type ModeFieldKind = 'text' | 'textarea' | 'number' | 'checkbox' | 'select' | 'percent';
type ModeFieldOption = { value: string; label: string };
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
  return mode ? <SpecificModeSettingsView mode={mode} /> : <GeneralSettingsView />;
}

function SpecificModeSettingsView({ mode }: { mode: string }) {
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [form, setForm] = useState<ModeForm>({});
  const [manualModelPath, setManualModelPath] = useState('');
  const [manualArchivePath, setManualArchivePath] = useState('~/Downloads/hermes-yachiyo-live2d-yachiyo-20260423.zip');
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);

  const sections = useMemo(() => modeFieldSections(mode, payload), [mode, payload]);
  const specs = useMemo(() => sections.flatMap((section) => section.fields), [sections]);
  const pendingCount = useMemo(() => countModePendingChanges(payload, form, specs), [payload, form, specs]);
  const hasChanges = pendingCount > 0;
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
    setForm((current) => ({ ...current, [key]: value }));
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
    if (!Object.keys(nextChanges).length) {
      setStatus('没有待保存的更改');
      return;
    }
    setSaving(true);
    setStatus('保存中…');
    try {
      const result = await apiPost<SettingsUpdateResult>('/ui/settings', { changes: nextChanges });
      if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '保存失败');
      const data = await apiGet<SettingsPayload>(`/ui/modes/${mode}/settings`);
      setPayload(data);
      setForm(formFromModeSettings(data, specs));
      const hint = result.effects?.hint ? `，${result.effects.hint}` : '';
      if (result.effects?.has_restart_mode) {
        await openDesktopMode(mode);
        setStatus(`已保存，并已重新打开 ${modeLabel(mode)} 表现态`);
      } else {
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
    <main className="app-shell settings-shell">
      <header className="topbar compact">
        <div>
          <h1>{payload?.mode?.settings_title || '模式设置'}</h1>
          <p>{payload?.mode?.settings_description || '读取中…'}</p>
        </div>
        <button type="button" className="ghost-button" onClick={() => navigateTo('settings', {}, ['mode'])}>通用设置</button>
      </header>

      {status ? <div className={statusClassName(status)}>{status}</div> : null}
      <section className="panel">
        <h2>当前状态</h2>
        <p>{payload?.settings?.summary || '读取中…'}</p>
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
      </section>

      <form className="settings-form" onSubmit={submitModeSettings} noValidate>
        {sections.map((section) => (
          <ModeFieldPanel
            key={section.title}
            section={section}
            form={form}
            onChange={updateField}
          />
        ))}

        <div className="settings-savebar">
          <span>{hasChanges ? `${pendingCount} 项待保存` : '设置已同步'}</span>
          <div className="settings-save-actions">
            <button type="button" disabled={!hasChanges || saving} onClick={resetDraft}>重置草稿</button>
            <button type="submit" disabled={!hasChanges || saving}>{saving ? '保存中…' : '保存更改'}</button>
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
        />
        {field.kind === 'percent' ? <span>%</span> : null}
      </div>
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
          <strong><a href={releasesUrl} target="_blank" rel="noreferrer">GitHub Releases</a></strong>
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

function GeneralSettingsView() {
  const [payload, setPayload] = useState<GeneralSettingsPayload | null>(null);
  const [form, setForm] = useState<GeneralSettingsForm>(emptyGeneralSettingsForm());
  const [backupStatus, setBackupStatus] = useState<BackupStatus | null>(null);
  const [backupManagerOpen, setBackupManagerOpen] = useState(false);
  const [uninstallScope, setUninstallScope] = useState('yachiyo_only');
  const [uninstallKeepConfig, setUninstallKeepConfig] = useState(true);
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
    const query = new URLSearchParams({ scope: uninstallScope, keep_config: String(uninstallKeepConfig) });
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
  }, [uninstallScope, uninstallKeepConfig]);

  useEffect(() => {
    if (status === 'Bridge 端口必须是整数' && Number.isInteger(Number(form.bridge_port))) {
      setStatus('');
    }
    if (status === 'Bridge Host 不能为空' && form.bridge_host.trim()) {
      setStatus('');
    }
  }, [form.bridge_host, form.bridge_port, status]);

  async function selectDisplayMode(modeId: string) {
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

  async function createBackup(overwriteLatest = false) {
    if (overwriteLatest && !window.confirm('将生成新备份并替换最近一次备份，继续吗？')) return;
    setStatus('正在生成备份…');
    const result = await apiPost<{ ok?: boolean; error?: string; status?: BackupStatus }>('/ui/backup/create', { overwrite_latest: overwriteLatest });
    if (result.ok === false) throw new Error(result.error || '生成备份失败');
    setBackupStatus(result.status || null);
    await refreshBackupStatus('备份已生成');
  }

  async function restoreBackup(backupPath = '') {
    if (!window.confirm('恢复备份会覆盖当前本地资料并安排应用重启，继续吗？')) return;
    setStatus('正在恢复备份…');
    const result = await apiPost<{ ok?: boolean; errors?: string[]; error?: string }>('/ui/backup/restore', { backup_path: backupPath });
    if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '恢复备份失败');
    setStatus('备份已恢复，应用将按需要重启');
  }

  async function deleteBackup(backupPath: string) {
    if (!backupPath || !window.confirm('确认删除这份备份吗？')) return;
    const result = await apiPost<{ ok?: boolean; error?: string; status?: BackupStatus }>('/ui/backup/delete', { backup_path: backupPath });
    if (result.ok === false) throw new Error(result.error || '删除备份失败');
    setBackupStatus(result.status || null);
    await refreshBackupStatus('备份已删除');
  }

  async function openBackupLocation(backupPath = '') {
    const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/backup/open-location', { backup_path: backupPath });
    setStatus(result.ok === false ? result.error || '打开备份位置失败' : '已打开备份位置');
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
        confirm_text: uninstallConfirmText,
      });
      if (result.ok === false) throw new Error(result.error || result.errors?.join('；') || '卸载失败');
      const backupText = result.backup_path_display ? `备份已保存到 ${result.backup_path_display}。` : '';
      setStatus(`卸载已执行。${backupText} 应用正在退出…`);
      if (result.desktop_quit_required || result.exit_scheduled) {
        window.setTimeout(() => {
          void quitApp();
        }, 250);
        return;
      }
      setUninstallRunning(false);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '卸载失败');
      setUninstallRunning(false);
    }
  }

  async function refreshUninstallPreview() {
    const query = new URLSearchParams({ scope: uninstallScope, keep_config: String(uninstallKeepConfig) });
    const data = await apiGet<UninstallPreviewResult>(`/ui/uninstall/preview?${query.toString()}`);
    if (data.ok === false) throw new Error(data.error || '生成卸载清单失败');
    setUninstallPreview(data.plan || null);
    setStatus('卸载清单已刷新');
  }

  return (
    <main className="app-shell settings-shell">
      <header className="topbar compact">
        <div>
          <h1>通用设置</h1>
          <p>{payload?.workspace?.path || '读取中…'}</p>
        </div>
        <button type="button" className="ghost-button" onClick={() => navigateTo('main', {}, ['mode'])}>主控台</button>
      </header>

      {status ? <div className="notice">{status}</div> : null}

      <section className="settings-grid expanded-settings-grid">
        <article className="panel setting-card">
          <span>Hermes</span>
          <strong>{payload?.hermes?.status || '读取中'}</strong>
          <small>{payload?.hermes?.ready ? '能力就绪' : payload?.hermes?.readiness_level || '待检测'}</small>
        </article>
        <article className="panel setting-card">
          <span>Bridge</span>
          <strong>{payload?.bridge?.state || '—'}</strong>
          <small>{payload?.bridge?.url || `${payload?.bridge?.host || '127.0.0.1'}:${payload?.bridge?.port || 8420}`}</small>
        </article>
        <article className="panel setting-card">
          <span>Application</span>
          <strong>{payload?.app?.version || '0.1.0'}</strong>
          <small>{payload?.app?.log_level || 'INFO'}</small>
        </article>
      </section>

      <section className="settings-detail-grid">
        <article className="panel settings-section">
          <div className="section-heading-row">
            <h2>Hermes Agent</h2>
            <span>{payload?.hermes?.ready ? 'ready' : payload?.hermes?.readiness_level || 'unknown'}</span>
          </div>
          <SettingsRows rows={[
            ['安装状态', payload?.hermes?.status],
            ['能力就绪', payload?.hermes?.ready ? '是' : '否'],
            ['版本', payload?.hermes?.version],
            ['平台', payload?.hermes?.platform],
            ['命令可用', payload?.hermes?.command_exists ? '是' : '否'],
            ['Hermes Home', payload?.hermes?.hermes_home],
            ['受限工具', listValue(payload?.hermes?.limited_tools)],
            ['诊断提示', payload?.hermes?.doctor_issues_count ? `${payload.hermes.doctor_issues_count} 项` : '无'],
          ]} />
          <div className="settings-action-strip">
            <button type="button" className="primary-action" onClick={() => navigateTo('main', {}, ['mode'])}>打开主控台配置中心</button>
          </div>
        </article>

        <article className="panel settings-section">
          <div className="section-heading-row">
            <h2>Yachiyo 工作空间</h2>
            <span>{payload?.workspace?.initialized ? '已初始化' : '未初始化'}</span>
          </div>
          <SettingsRows rows={[
            ['路径', payload?.workspace?.path],
            ['创建时间', formatSettingsDate(payload?.workspace?.created_at)],
            ['目录', workspaceDirs(payload?.workspace?.dirs)],
          ]} />
        </article>
      </section>

      <form className="settings-form" onSubmit={submitSettings} noValidate>
        <section className="panel settings-section">
          <div className="section-heading-row">
            <h2>显示模式</h2>
            <span>{form.display_mode === payload?.display?.current_mode ? '当前' : '待切换'}</span>
          </div>
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
        </section>

        <section className="panel settings-section settings-form-grid">
          <div className="settings-field wide">
            <label htmlFor="assistant-address">助手称呼</label>
            <input
              id="assistant-address"
              value={form.user_address}
              onChange={(event) => setForm((current) => ({ ...current, user_address: event.target.value }))}
            />
          </div>
          <div className="settings-field wide">
            <label htmlFor="assistant-persona">助手人设</label>
            <textarea
              id="assistant-persona"
              rows={8}
              value={form.persona_prompt}
              onChange={(event) => setForm((current) => ({ ...current, persona_prompt: event.target.value }))}
            />
          </div>
        </section>

        <section className="panel settings-section settings-form-grid">
          <label className="settings-check wide" htmlFor="bridge-enabled">
            <input
              id="bridge-enabled"
              type="checkbox"
              checked={form.bridge_enabled}
              onChange={(event) => setForm((current) => ({ ...current, bridge_enabled: event.target.checked }))}
            />
            <span>启用 Bridge</span>
          </label>
          <div className="settings-field">
            <label htmlFor="bridge-host">Bridge Host</label>
            <input
              id="bridge-host"
              value={form.bridge_host}
              onChange={(event) => setForm((current) => ({ ...current, bridge_host: event.target.value }))}
            />
          </div>
          <div className="settings-field">
            <label htmlFor="bridge-port">Bridge Port</label>
            <input
              id="bridge-port"
              inputMode="numeric"
              value={form.bridge_port}
              onChange={(event) => setForm((current) => ({ ...current, bridge_port: event.target.value }))}
            />
          </div>
          <label className="settings-check wide" htmlFor="tray-enabled">
            <input
              id="tray-enabled"
              type="checkbox"
              checked={form.tray_enabled}
              onChange={(event) => setForm((current) => ({ ...current, tray_enabled: event.target.checked }))}
            />
            <span>启用托盘入口</span>
          </label>
          <div className="settings-meta-row wide-meta">
            <span>启动最小化</span>
            <strong>{payload?.app?.start_minimized ? '是' : '否'}</strong>
          </div>
        </section>

        <section className="panel settings-section settings-form-grid">
          <div className="section-heading-row wide-heading">
            <h2>备份策略</h2>
            <span>配置、工作空间、聊天数据库、缓存、日志和导入资源</span>
          </div>
          <label className="settings-check wide" htmlFor="backup-auto-cleanup">
            <input
              id="backup-auto-cleanup"
              type="checkbox"
              checked={form.backup_auto_cleanup_enabled}
              onChange={(event) => setForm((current) => ({ ...current, backup_auto_cleanup_enabled: event.target.checked }))}
            />
            <span>自动清理旧备份</span>
          </label>
          <div className="settings-field">
            <label htmlFor="backup-retention-count">保留最近</label>
            <input
              id="backup-retention-count"
              inputMode="numeric"
              value={form.backup_retention_count}
              onChange={(event) => setForm((current) => ({ ...current, backup_retention_count: event.target.value }))}
            />
          </div>
        </section>

        <div className="settings-savebar">
          <span>{hasChanges ? `${pendingCount} 项待保存` : '设置已同步'}</span>
          <button type="submit" disabled={!hasChanges || saving}>{saving ? '保存中…' : '保存更改'}</button>
        </div>
      </form>

      <section className="panel settings-section">
        <h2>模式配置</h2>
        <div className="mode-summary-list">
          {Object.entries(payload?.mode_settings || {}).map(([modeId, item]) => (
            <button type="button" key={modeId} onClick={() => navigateTo('settings', { mode: modeId })}>
              <strong>{item.title || modeId}</strong>
              <span>{item.summary || '—'}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="settings-detail-grid">
        <article className="panel settings-section">
          <div className="section-heading-row">
            <h2>Bridge / 内部通信</h2>
            <span>{payload?.bridge?.config_dirty ? '需重启' : '已对齐'}</span>
          </div>
          <SettingsRows rows={[
            ['运行状态', payload?.bridge?.state],
            ['保存地址', payload?.bridge?.url],
            ['运行地址', payload?.bridge?.boot_config?.url],
            ['配置漂移', payload?.bridge?.config_dirty ? listValue(payload.bridge.drift_details) : '无'],
          ]} />
          <div className="settings-action-strip">
            <button type="button" disabled={bridgeRestarting || saving} onClick={() => void restartBridge()}>
              {bridgeRestarting ? '重启中…' : '应用配置并重启 Bridge'}
            </button>
          </div>
        </article>

        <article className="panel settings-section">
          <div className="section-heading-row">
            <h2>集成服务</h2>
          </div>
          <IntegrationRows title="AstrBot / QQ" item={payload?.integrations?.astrbot} />
          <IntegrationRows title="Hapi / Codex" item={payload?.integrations?.hapi} />
          <p className="settings-note">AstrBot 是通过 QQ 远程控制 Yachiyo 的桥接入口，依赖 Bridge 运行。</p>
        </article>
      </section>

      <section className="panel settings-section">
        <div className="section-heading-row">
          <h2>备份</h2>
          <span>{backupStatus?.has_backup ? `${backupStatus.count || 0} 份 / ${backupStatus.total_size_display || '0 B'}` : '暂无备份'}</span>
        </div>
        <SettingsRows rows={[
          ['最近备份', backupSummary(backupStatus?.latest || null)],
          ['备份状态', backupStatus?.ok === false ? backupStatus.error : '正常'],
        ]} />
        <div className="settings-action-strip">
          <button type="button" onClick={() => void createBackup(false)}>立即生成备份</button>
          <button type="button" onClick={() => void createBackup(true)}>覆盖最近一次备份</button>
          <button type="button" onClick={() => void restoreBackup()}>恢复最近备份</button>
          <button type="button" onClick={() => void openBackupLocation()}>打开备份目录</button>
          <button type="button" onClick={() => setBackupManagerOpen((open) => !open)}>{backupManagerOpen ? '收起管理器' : '管理备份'}</button>
        </div>
        {backupManagerOpen ? (
          <div className="backup-manager visible">
            {(backupStatus?.backups || []).length ? (backupStatus?.backups || []).map((item) => (
              <div className="backup-item" key={item.path || item.display_path}>
                <div>
                  <div className="name">{backupFileName(item)}</div>
                  <div className="meta">{formatSettingsDate(item.created_at)} · {item.size_display || '未知大小'}</div>
                  {!item.valid ? <div className="meta warn-text">{item.error || '备份无效'}</div> : null}
                </div>
                <div className="actions">
                  <button type="button" onClick={() => void restoreBackup(item.path || '')}>恢复此版本</button>
                  <button type="button" onClick={() => void openBackupLocation(item.path || '')}>打开位置</button>
                  <button type="button" onClick={() => void deleteBackup(item.path || '')}>删除</button>
                </div>
              </div>
            )) : <div className="empty-state inline-empty">暂无可管理备份</div>}
          </div>
        ) : null}
      </section>

      <section className="panel settings-section danger-section-react">
        <div className="section-heading-row">
          <h2>卸载</h2>
          <span>{uninstallPreview ? `${uninstallPreview.removable_count || 0}/${uninstallPreview.existing_count || 0} 可删除` : '生成清单中'}</span>
        </div>
        <p className="settings-note">卸载会删除所选范围内的本地资料；如选择同时卸载 Hermes Agent，会额外删除可识别且安全范围内的 Hermes Home 与命令。</p>
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
        </div>
        <div className="uninstall-preview-react">
          {(uninstallPreview?.targets || []).map((target) => (
            <div className="uninstall-target-react" key={target.id || target.path}>
              <div>
                <strong>{target.label || target.id}</strong>
                <span>{target.display_path || target.path || '—'}</span>
              </div>
              <small>{target.exists ? (target.removable ? '将删除' : target.reason || '跳过') : '不存在'}</small>
            </div>
          ))}
          {uninstallPreview?.warnings?.length ? <p className="warn-text">{uninstallPreview.warnings.join('；')}</p> : null}
        </div>
        <div className="settings-field uninstall-confirm-field">
          <label htmlFor="uninstall-confirm-text">输入 {uninstallConfirmPhrase} 确认</label>
          <input
            id="uninstall-confirm-text"
            value={uninstallConfirmText}
            disabled={uninstallRunning}
            onChange={(event) => setUninstallConfirmText(event.target.value)}
          />
        </div>
        <div className="settings-action-strip">
          <button type="button" disabled={uninstallRunning} onClick={() => void refreshUninstallPreview()}>刷新清单</button>
          <button type="button" className="danger-action" disabled={uninstallRunning || !uninstallConfirmValid} onClick={() => void runUninstall()}>{uninstallRunning ? '正在卸载' : '卸载'}</button>
        </div>
      </section>
    </main>
  );
}

function SettingsRows({ rows }: { rows: Array<[string, string | number | undefined | null]> }) {
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

function IntegrationRows({ title, item }: { title: string; item?: StatusRecord }) {
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

function listValue(items?: string[]): string {
  return items?.length ? items.join('、') : '—';
}

function modeLabel(mode: string) {
  return mode === 'live2d' ? 'Live2D' : 'Bubble';
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
): Record<string, string | number | boolean> {
  const config = payload.settings?.config || {};
  const changes: Record<string, string | number | boolean> = {};
  specs.forEach((spec) => {
    const parsed = parseModeFieldValue(form[spec.key], spec);
    const current = modeConfigValue(config, spec);
    if (!sameModeConfigValue(current, parsed, spec)) {
      changes[spec.key] = parsed;
    }
  });
  return changes;
}

function validateModeForm(form: ModeForm, specs: ModeFieldSpec[]): string {
  for (const spec of specs) {
    const raw = form[spec.key];
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

function parseModeFieldValue(value: ModeFormValue | undefined, spec: ModeFieldSpec): string | number | boolean {
  if (spec.kind === 'checkbox') return Boolean(value);
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
  if (spec.kind === 'percent') return formatNumber(Number(value || 0) * 100);
  if (spec.kind === 'number') return value === undefined || value === null ? '' : formatNumber(Number(value));
  return String(value ?? '');
}

function sameModeConfigValue(current: unknown, next: string | number | boolean, spec: ModeFieldSpec): boolean {
  if (spec.kind === 'checkbox') return Boolean(current) === next;
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

function fieldId(key: string): string {
  return key.replace(/[^a-zA-Z0-9_-]+/g, '-');
}

function asRecord(value: unknown): ModeConfig {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ModeConfig : {};
}

function stringValue(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
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

function live2dExpressionSummary(summary: ModeConfig): string {
  const expressions = Array.isArray(summary.expressions) ? summary.expressions : [];
  if (!expressions.length) return '当前模型未声明可选表情';
  return expressions.map((item) => stringValue(asRecord(item).name || asRecord(item).file || '未命名表情')).join(' / ');
}

function live2dExpressionOptions(payload?: SettingsPayload | null): ModeFieldOption[] {
  const config = payload?.settings?.config || {};
  const summary = asRecord(config.summary);
  const expressions = Array.isArray(summary.expressions) ? summary.expressions : [];
  const options: ModeFieldOption[] = [{ value: '', label: '自动匹配' }];
  const seen = new Set(['']);
  for (const item of expressions) {
    const record = asRecord(item);
    const value = stringValue(record.name || record.file).trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    const file = stringValue(record.file).trim();
    options.push({
      value,
      label: file && file !== value ? `${value} · ${file}` : value,
    });
  }
  return options;
}

function live2dFieldSections(payload?: SettingsPayload | null): ModeFieldSection[] {
  const expressionOptions = live2dExpressionOptions(payload);
  return LIVE2D_FIELD_SECTIONS.map((section) => ({
    ...section,
    fields: section.fields.map((field) => (
      field.key.endsWith('_expression')
        ? { ...field, options: expressionOptions }
        : field
    )),
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
    note: '启动初始表现只控制回复气泡和快捷输入，不会自动打开聊天窗口。',
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
          { value: 'open_chat', label: '打开/切换聊天窗口' },
          { value: 'toggle_reply', label: '切换回复气泡' },
          { value: 'focus_stage', label: '仅聚焦角色窗口' },
        ],
      },
      { key: 'live2d_mode.enable_quick_input', sourceKey: 'enable_quick_input', label: '显示快捷输入入口', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.auto_open_chat_window', sourceKey: 'auto_open_chat_window', label: '启动时打开聊天窗口', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.mouse_follow_enabled', sourceKey: 'mouse_follow_enabled', label: '鼠标跟随', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.idle_motion_group', sourceKey: 'idle_motion_group', label: '待机动作组', kind: 'text' },
      { key: 'live2d_mode.enable_expressions', sourceKey: 'enable_expressions', label: '启用表情系统', kind: 'checkbox', wide: true },
      { key: 'live2d_mode.enable_physics', sourceKey: 'enable_physics', label: '启用物理模拟', kind: 'checkbox', wide: true },
    ],
  },
  {
    title: '表情映射',
    note: '选项来自当前 model3.json 的 Expressions；留空时按表情名称自动匹配。',
    fields: [
      {
        key: 'live2d_mode.thinking_expression',
        sourceKey: 'thinking_expression',
        label: '思考时表情',
        kind: 'select',
        options: [{ value: '', label: '自动匹配' }],
        allowCustom: true,
      },
      {
        key: 'live2d_mode.message_expression',
        sourceKey: 'message_expression',
        label: '收到回复表情',
        kind: 'select',
        options: [{ value: '', label: '自动匹配' }],
        allowCustom: true,
      },
      {
        key: 'live2d_mode.failed_expression',
        sourceKey: 'failed_expression',
        label: '失败时表情',
        kind: 'select',
        options: [{ value: '', label: '自动匹配' }],
        allowCustom: true,
      },
      {
        key: 'live2d_mode.attention_expression',
        sourceKey: 'attention_expression',
        label: '提醒时表情',
        kind: 'select',
        options: [{ value: '', label: '自动匹配' }],
        allowCustom: true,
      },
    ],
  },
];
