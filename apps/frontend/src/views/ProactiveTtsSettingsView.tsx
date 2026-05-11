import { useEffect, useState } from 'react';

import {
  apiGet,
  apiPost,
  chooseLive2DArchive,
  hasDesktopFilePicker,
  openAppView,
  openExternalUrl,
  openPath,
} from '../lib/bridge';
import { navigateTo } from '../lib/view';
import {
  emptyTtsForm,
  formFromTtsSettings,
  ttsProviderLabel,
  ttsSettingsChanges,
  type TtsForm,
  type TtsSettings,
} from '../lib/ttsSettings';

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
  desktop_watch_enabled: boolean;
  interval_seconds: string;
  trigger_probability_percent: string;
  target_mode: 'live2d' | 'bubble';
};

type SettingsUpdateResult = {
  ok?: boolean;
  error?: string;
  app_state?: SettingsData;
};

type TtsTestResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  provider?: string;
  spoken_text?: string;
  skipped?: boolean;
};

type TtsRuntimeStatus = TtsTestResult & {
  tool?: string;
  source?: string;
  scheduled?: boolean;
  pending_audio?: boolean;
  audio_ready?: boolean;
  attention_key?: string;
};

type TtsVoiceResource = {
  default_assets_root?: string;
  default_assets_root_display?: string;
  releases_url?: string;
  voice_package_url?: string;
  help_text?: string;
  service_help_text?: string;
  service_project_url?: string;
  default_service_workdir?: string;
  default_service_workdir_display?: string;
  default_service_command?: string;
};

type GptSovitsServiceStatus = {
  reachable?: boolean;
  reachable_error?: string;
  workdir_display?: string;
  workdir_exists?: boolean;
  command_configured?: boolean;
  launch_agent_installed?: boolean;
  launch_agent_running?: boolean;
  api_process?: {
    running?: boolean;
    pid?: number;
    ppid?: number;
    command?: string;
    port?: number;
  };
  related_launch_agents?: Array<{
    label?: string;
    path_display?: string;
    working_directory?: string;
    managed_by_hermes?: boolean;
    running?: boolean;
  }>;
  platform_supported?: boolean;
  plist_path_display?: string;
  tools?: Record<string, boolean>;
  models?: Record<string, boolean>;
  missing_model_files?: string[];
  logs?: { stdout?: string; stderr?: string };
};

type TtsVoiceImportResult = SettingsUpdateResult & {
  imported_path?: string;
  imported_path_display?: string;
  tts_settings?: TtsSettings;
  resource?: TtsVoiceResource;
  message?: string;
};

type ProactiveActionResult = {
  ok?: boolean;
  allowed?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  mode?: string;
  prompt?: string;
  response?: string;
};

const MIN_PROACTIVE_INTERVAL_SECONDS = 300;

export function ProactiveTtsSettingsView() {
  const [form, setForm] = useState<TtsForm>(emptyTtsForm());
  const [savedForm, setSavedForm] = useState<TtsForm>(emptyTtsForm());
  const [proactiveForm, setProactiveForm] = useState<ProactiveForm>(emptyProactiveForm());
  const [savedProactiveForm, setSavedProactiveForm] = useState<ProactiveForm>(emptyProactiveForm());
  const [proactiveResult, setProactiveResult] = useState<ProactiveActionResult | null>(null);
  const [testText, setTestText] = useState('八千代语音测试成功。主动关怀播报已经可以正常调用。');
  const [testResult, setTestResult] = useState<TtsTestResult | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<TtsRuntimeStatus | null>(null);
  const [voiceResource, setVoiceResource] = useState<TtsVoiceResource | null>(null);
  const [serviceStatus, setServiceStatus] = useState<GptSovitsServiceStatus | null>(null);
  const [manualVoiceArchivePath, setManualVoiceArchivePath] = useState('');
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [resourceBusy, setResourceBusy] = useState(false);
  const [status, setStatus] = useState('');
  const provider = form.provider || 'none';

  useEffect(() => {
    let disposed = false;
    async function load() {
      setLoading(true);
      try {
        const data = await apiGet<SettingsData>('/ui/settings');
        const next = formFromTtsSettings(ttsFromSettings(data));
        const nextProactive = formFromProactiveSettings(proactiveFromSettings(data));
        if (!disposed) {
          setForm(next);
          setSavedForm(next);
          setProactiveForm(nextProactive);
          setSavedProactiveForm(nextProactive);
          setStatus('');
        }
      } catch (err) {
        if (!disposed) setStatus(err instanceof Error ? err.message : '读取 TTS 设置失败');
      } finally {
        if (!disposed) setLoading(false);
      }
    }
    void load();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    async function refreshRuntimeStatus() {
      try {
        const data = await apiGet<TtsRuntimeStatus>('/ui/tts/status');
        if (!disposed) setRuntimeStatus(data);
      } catch {
        if (!disposed) setRuntimeStatus(null);
      }
    }
    void refreshRuntimeStatus();
    const timer = window.setInterval(() => {
      void refreshRuntimeStatus();
    }, 5000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    apiGet<TtsVoiceResource>('/ui/tts/voice-resource')
      .then((data) => {
        if (!disposed) setVoiceResource(data);
      })
      .catch(() => {
        if (!disposed) setVoiceResource(null);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (provider !== 'gpt-sovits') return undefined;
    let disposed = false;
    void refreshGsvServiceStatus(() => disposed);
    return () => {
      disposed = true;
    };
  }, [provider]);

  function updateField(field: keyof TtsForm, value: string | boolean | number) {
    setForm((current) => {
      const next = { ...current, [field]: value };
      if (field === 'provider') {
        next.enabled = value !== 'none';
      }
      if (field === 'enabled' && value === true && next.provider === 'none') {
        next.provider = 'gpt-sovits';
      }
      return next;
    });
    setTestResult(null);
    if (status && /保存|TTS|语音/.test(status)) setStatus('');
  }

  function updateProactiveField(field: keyof ProactiveForm, value: string | boolean) {
    setProactiveForm((current) => ({ ...current, [field]: value }));
    setProactiveResult(null);
    if (status && /主动关怀|权限|测试/.test(status)) setStatus('');
  }

  async function saveProactiveSettings() {
    if (interactionBusy) return;
    setBusyAction('proactive-save');
    setProactiveResult(null);
    setStatus('正在保存主动关怀设置...');
    try {
      const interval = normalizeProactiveInterval(proactiveForm.interval_seconds);
      const probability = clampProbability(Number(proactiveForm.trigger_probability_percent) / 100);
      const enabled = Boolean(proactiveForm.enabled);
      const desktopWatch = Boolean(proactiveForm.desktop_watch_enabled);
      const result = await apiPost<SettingsUpdateResult>('/ui/settings', {
        changes: {
          'bubble_mode.proactive_enabled': enabled,
          'bubble_mode.proactive_desktop_watch_enabled': desktopWatch,
          'bubble_mode.proactive_interval_seconds': interval,
          'bubble_mode.proactive_trigger_probability': probability,
          'live2d_mode.proactive_enabled': enabled,
          'live2d_mode.proactive_desktop_watch_enabled': desktopWatch,
          'live2d_mode.proactive_interval_seconds': interval,
          'live2d_mode.proactive_trigger_probability': probability,
        },
      });
      if (result.ok === false) throw new Error(result.error || '保存主动关怀设置失败');
      const next = result.app_state
        ? formFromProactiveSettings(proactiveFromSettings(result.app_state))
        : {
          ...proactiveForm,
          interval_seconds: String(interval),
          trigger_probability_percent: String(Math.round(probability * 100)),
        };
      setProactiveForm(next);
      setSavedProactiveForm(next);
      setStatus('主动关怀设置已保存');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存主动关怀设置失败');
    } finally {
      setBusyAction('');
    }
  }

  async function checkScreenPermission() {
    if (interactionBusy) return;
    setBusyAction('proactive-permission');
    setProactiveResult(null);
    setStatus('正在检查屏幕录制权限...');
    try {
      const result = await apiPost<ProactiveActionResult>('/ui/proactive/screen-permission/check', { open_settings: true });
      setProactiveResult(result);
      setStatus(result.allowed || result.ok ? result.message || '屏幕观察权限可用' : result.error || result.message || '屏幕观察权限未就绪');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '检查屏幕权限失败');
    } finally {
      setBusyAction('');
    }
  }

  async function runProactiveTest() {
    if (interactionBusy) return;
    setBusyAction('proactive-test');
    setProactiveResult(null);
    setStatus('正在触发主动关怀测试...');
    try {
      const result = await apiPost<ProactiveActionResult>('/ui/proactive/test', {
        mode: proactiveForm.target_mode || 'live2d',
      });
      setProactiveResult(result);
      setStatus(result.success || result.ok ? result.message || '主动关怀测试已触发' : result.error || result.message || '主动关怀测试失败');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '主动关怀测试失败');
    } finally {
      setBusyAction('');
    }
  }

  async function persistSettings(successMessage: string): Promise<TtsForm> {
    const result = await apiPost<SettingsUpdateResult>('/ui/settings', {
      changes: ttsSettingsChanges(form),
    });
    if (result.ok === false) throw new Error(result.error || '保存主动关怀语音设置失败');
    const next = result.app_state ? formFromTtsSettings(ttsFromSettings(result.app_state)) : form;
    setForm(next);
    setSavedForm(next);
    if (successMessage) setStatus(successMessage);
    return next;
  }

  async function saveSettings() {
    setBusyAction('save');
    setStatus('正在保存主动关怀语音设置...');
    try {
      await persistSettings('主动关怀语音设置已保存');
      window.setTimeout(() => void openAppView('main'), 700);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存主动关怀语音设置失败');
    } finally {
      setBusyAction('');
    }
  }

  async function saveAndTestSettings() {
    setBusyAction('test');
    setTestResult(null);
    setStatus('正在保存设置并播放测试语音...');
    try {
      const next = await persistSettings('');
      if (!next.enabled || next.provider === 'none') {
        const result = {
          ok: false,
          success: false,
          provider: next.provider,
          skipped: true,
          message: '请先启用主动关怀 TTS 并选择 Provider',
        };
        setTestResult(result);
        setStatus(result.message);
        return;
      }
      setStatus('设置已保存，正在调用 TTS Provider...');
      const result = await apiPost<TtsTestResult>('/ui/tts/test', { text: testText });
      setTestResult(result);
      setRuntimeStatus(result);
      setStatus(result.success ? result.message || '测试语音已完成' : result.error || result.message || '测试语音失败');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存并测试主动关怀语音失败');
    } finally {
      setBusyAction('');
    }
  }

  function resetDraft() {
    setForm(savedForm);
    setStatus('已恢复到上次保存的语音设置');
    setTestResult(null);
  }

  async function importVoiceArchive() {
    if (busy || loading || resourceBusy) return;
    setResourceBusy(true);
    setStatus('正在导入八千代音色包...');
    try {
      const selectedPath = hasDesktopFilePicker()
        ? await chooseLive2DArchive()
        : manualVoiceArchivePath.trim();
      if (!selectedPath) {
        setStatus(hasDesktopFilePicker() ? '已取消导入音色包' : '请输入音色包 ZIP 路径');
        return;
      }
      const result = await apiPost<TtsVoiceImportResult>('/ui/tts/voice-resource/import', { path: selectedPath });
      if (result.ok === false) throw new Error(result.error || '导入音色包失败');
      const next = formFromTtsSettings(result.tts_settings || {});
      setForm((current) => ({
        ...current,
        ...next,
        gsv_base_url: current.gsv_base_url || next.gsv_base_url,
      }));
      setVoiceResource(result.resource || voiceResource);
      setTestResult(null);
      const displayPath = result.imported_path_display ? `：${result.imported_path_display}` : '';
      setStatus(`${result.message || '音色包已导入，等待保存 TTS 设置'}${displayPath}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '导入音色包失败');
    } finally {
      setResourceBusy(false);
    }
  }

  async function openVoiceAssetsDir() {
    const root = voiceResource?.default_assets_root || '';
    if (!root) {
      setStatus('未找到音色包导入目录');
      return;
    }
    try {
      await openPath(root);
      setStatus(`已打开音色包导入目录：${voiceResource?.default_assets_root_display || root}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开音色包导入目录失败');
    }
  }

  async function openVoiceReleases() {
    const url = voiceResource?.voice_package_url || voiceResource?.releases_url || '';
    if (!url) {
      setStatus('未配置音色包下载地址');
      return;
    }
    await openExternalUrl(url);
  }

  async function refreshGsvServiceStatus(
    isDisposed: () => boolean = () => false,
    draft: { base_url?: string; workdir?: string; command?: string } = {},
  ) {
    try {
      const data = await apiPost<GptSovitsServiceStatus>('/ui/tts/gpt-sovits/service-status', {
        base_url: draft.base_url ?? form.gsv_base_url,
        workdir: draft.workdir ?? form.gsv_service_workdir,
        command: draft.command ?? form.gsv_service_command,
      });
      if (!isDisposed()) setServiceStatus(data);
    } catch {
      if (!isDisposed()) setServiceStatus(null);
    }
  }

  async function installGsvLaunchAgent() {
    if (interactionBusy) return;
    setBusyAction('service-install');
    setStatus('正在启动 GPT-SoVITS 后台服务并安装开机自启...');
    try {
      await persistSettings('');
      const result = await apiPost<{ ok?: boolean; error?: string; message?: string; status?: GptSovitsServiceStatus }>('/ui/tts/gpt-sovits/service/install');
      if (result.ok === false) throw new Error(result.error || '启动 GPT-SoVITS 后台服务失败');
      setServiceStatus(result.status || null);
      setStatus(result.message || 'GPT-SoVITS 后台服务已启动，并会随登录自动运行');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '启动 GPT-SoVITS 后台服务失败');
    } finally {
      setBusyAction('');
    }
  }

  async function useExistingGsvService() {
    if (interactionBusy) return;
    setBusyAction('service-use-existing');
    setStatus('正在保存现有 GPT-SoVITS 服务配置...');
    try {
      const next = await persistSettings('');
      await refreshGsvServiceStatus(() => false, {
        base_url: next.gsv_base_url,
        workdir: next.gsv_service_workdir,
        command: next.gsv_service_command,
      });
      setStatus('已保留现有 GPT-SoVITS 服务，Yachiyo 将复用当前 API，不接管自启。');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存现有 GPT-SoVITS 服务配置失败');
    } finally {
      setBusyAction('');
    }
  }

  async function adoptGsvLaunchAgent() {
    if (interactionBusy) return;
    const agent = firstExternalGsvLaunchAgent(serviceStatus);
    const label = agent?.label || '外部 GPT-SoVITS 服务';
    const confirmed = window.confirm(
      `将停用外部 GPT-SoVITS LaunchAgent（${label}），保留服务目录和模型文件，并安装 Hermes-Yachiyo 自己的后台/自启。继续吗？`,
    );
    if (!confirmed) return;
    setBusyAction('service-adopt');
    setStatus('正在接管 GPT-SoVITS 后台服务...');
    try {
      await persistSettings('');
      const result = await apiPost<{
        ok?: boolean;
        error?: string;
        message?: string;
        status?: GptSovitsServiceStatus;
      }>('/ui/tts/gpt-sovits/service/adopt');
      if (result.ok === false) throw new Error(result.error || '接管 GPT-SoVITS 后台服务失败');
      setServiceStatus(result.status || null);
      setStatus(result.message || 'GPT-SoVITS 后台服务已交由 Hermes-Yachiyo 管理');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '接管 GPT-SoVITS 后台服务失败');
    } finally {
      setBusyAction('');
    }
  }

  async function uninstallGsvLaunchAgent() {
    if (interactionBusy) return;
    if (!window.confirm('将停止并移除 GPT-SoVITS 开机自启服务，不会删除模型文件。继续吗？')) return;
    setBusyAction('service-uninstall');
    setStatus('正在停止 GPT-SoVITS 后台服务并移除开机自启...');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; message?: string; status?: GptSovitsServiceStatus }>('/ui/tts/gpt-sovits/service/uninstall');
      if (result.ok === false) throw new Error(result.error || '停止 GPT-SoVITS 后台服务失败');
      setServiceStatus(result.status || null);
      setStatus(result.message || 'GPT-SoVITS 后台服务已停止');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '停止 GPT-SoVITS 后台服务失败');
    } finally {
      setBusyAction('');
    }
  }

  async function openGsvServiceTerminal() {
    if (interactionBusy) return;
    if (!form.gsv_service_workdir.trim()) {
      setStatus('请先填写 GPT-SoVITS 服务目录，再打开调试终端');
      return;
    }
    if (!form.gsv_service_command.trim()) {
      setStatus('请先填写 GPT-SoVITS 启动命令');
      return;
    }
    setBusyAction('service');
    setStatus('正在打开 GPT-SoVITS 调试终端...');
    try {
      const result = await apiPost<{ success?: boolean; error?: string }>('/ui/hermes/terminal-command', {
        command: buildGsvServiceTerminalCommand(form),
      });
      if (!result.success) throw new Error(result.error || '无法打开 GPT-SoVITS 调试终端');
      setStatus('已打开 GPT-SoVITS 调试终端；这是前台运行方式，本地后台服务已占用端口时请先停止后台服务');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开 GPT-SoVITS 调试终端失败');
    } finally {
      setBusyAction('');
    }
  }

  async function openGsvSetupTerminal() {
    if (interactionBusy) return;
    if (!window.confirm(
      '将打开系统终端并尝试克隆 GPT-SoVITS、创建本地 Python 3.11 环境并安装依赖。部署完成后不会直接占用 9880 端口；需要运行服务时请使用本地后台服务或调试终端。继续吗？',
    )) return;
    setBusyAction('service-setup');
    setStatus('正在打开 GPT-SoVITS 本地依赖部署终端...');
    try {
      const defaultWorkdir = voiceResource?.default_service_workdir_display || voiceResource?.default_service_workdir || `${homePlaceholder()}/AI/GPT-SoVITS`;
      const workdir = form.gsv_service_workdir.trim() || defaultWorkdir;
      if (!form.gsv_service_workdir.trim()) {
        updateField('gsv_service_workdir', workdir);
      }
      const command = form.gsv_service_command.trim() || voiceResource?.default_service_command || 'python api_v2.py -a 127.0.0.1 -p 9880';
      if (!form.gsv_service_command.trim()) {
        updateField('gsv_service_command', command);
      }
      const result = await apiPost<{ success?: boolean; error?: string }>('/ui/hermes/terminal-command', {
        command: buildGsvSetupTerminalCommand(workdir, command, voiceResource?.service_project_url),
      });
      if (!result.success) throw new Error(result.error || '无法打开 GPT-SoVITS 本地依赖部署终端');
      setStatus('已打开 GPT-SoVITS 本地依赖部署终端；依赖装好后可启动本地后台服务或调试终端');
      window.setTimeout(() => void refreshGsvServiceStatus(
        () => false,
        { base_url: form.gsv_base_url, workdir, command },
      ), 500);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开 GPT-SoVITS 本地依赖部署终端失败');
    } finally {
      setBusyAction('');
    }
  }

  const enabled = Boolean(form.enabled && provider !== 'none');
  const isGsvProvider = provider === 'gpt-sovits';
  const isDirty = JSON.stringify(form) !== JSON.stringify(savedForm);
  const proactiveDirty = JSON.stringify(proactiveForm) !== JSON.stringify(savedProactiveForm);
  const filePickerAvailable = hasDesktopFilePicker();
  const busy = Boolean(busyAction);
  const interactionBusy = busy || loading || resourceBusy;
  const externalGsvServiceDetected = hasExternalGsvService(serviceStatus);
  const externalGsvAgent = firstExternalGsvLaunchAgent(serviceStatus);

  return (
    <main className="app-shell">
      <header className="topbar dashboard-topbar">
        <div>
          <h1>主动关怀语音</h1>
          <p>只在主动桌面观察触发关怀提醒时播报；普通聊天回复不会自动转语音。</p>
        </div>
        <div className="topbar-actions">
          <button type="button" onClick={() => navigateTo('main')}>返回主控台</button>
          <button type="button" onClick={() => void openAppView('tools')}>工具中心</button>
        </div>
      </header>

      {status ? <div className={`notice ${/失败|错误/.test(status) ? 'danger' : ''}`}>{status}</div> : null}
      {shouldShowRuntimeStatus(runtimeStatus) ? (
        <div className={`notice ${ttsRuntimeStatusTone(runtimeStatus)}`}>
          <strong>{ttsRuntimeStatusTitle(runtimeStatus)}</strong>
          <span>{ttsRuntimeStatusDetail(runtimeStatus)}</span>
        </div>
      ) : null}

      <section className="dashboard-workbench single-column">
        <article className="panel">
          <div className="section-heading-row">
            <div>
              <h2>主动关怀</h2>
              <p className="section-caption">
                统一控制 Bubble 与 Live2D 的主动观察触发；具体单模式细节也可以在对应模式设置页单独微调。
              </p>
            </div>
            <span>{loading ? '读取中' : proactiveForm.enabled ? '已启用' : '已关闭'}</span>
          </div>

          <div className="tts-settings-form">
            <div className="hermes-config-form-grid">
              <label className="settings-check wide" htmlFor="proactive-enabled-page">
                <input
                  id="proactive-enabled-page"
                  type="checkbox"
                  checked={proactiveForm.enabled}
                  disabled={interactionBusy}
                  onChange={(event) => updateProactiveField('enabled', event.target.checked)}
                />
                <span>启用主动关怀</span>
              </label>
              <label className="settings-check wide" htmlFor="proactive-desktop-watch-page">
                <input
                  id="proactive-desktop-watch-page"
                  type="checkbox"
                  checked={proactiveForm.desktop_watch_enabled}
                  disabled={interactionBusy}
                  onChange={(event) => updateProactiveField('desktop_watch_enabled', event.target.checked)}
                />
                <span>允许桌面观察触发</span>
              </label>
              <label className="settings-field" htmlFor="proactive-interval-page">
                <span>触发间隔秒</span>
                <input
                  id="proactive-interval-page"
                  type="number"
                  min={MIN_PROACTIVE_INTERVAL_SECONDS}
                  max={3600}
                  value={proactiveForm.interval_seconds}
                  disabled={interactionBusy}
                  onChange={(event) => updateProactiveField('interval_seconds', event.target.value)}
                />
              </label>
              <label className="settings-field" htmlFor="proactive-probability-page">
                <span>触发概率 %</span>
                <input
                  id="proactive-probability-page"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={proactiveForm.trigger_probability_percent}
                  disabled={interactionBusy}
                  onChange={(event) => updateProactiveField('trigger_probability_percent', event.target.value)}
                />
              </label>
              <label className="settings-field" htmlFor="proactive-target-mode-page">
                <span>立即测试目标</span>
                <select
                  id="proactive-target-mode-page"
                  value={proactiveForm.target_mode}
                  disabled={interactionBusy}
                  onChange={(event) => updateProactiveField('target_mode', event.target.value as ProactiveForm['target_mode'])}
                >
                  <option value="live2d">Live2D</option>
                  <option value="bubble">Bubble</option>
                </select>
              </label>
              <p className="capability-note wide-form-note">
                保存会同时写入 bubble_mode 与 live2d_mode 的 proactive 字段；不会修改 TTS Provider 或其它模式行为。
              </p>
            </div>

            {proactiveResult ? (
              <div className={`hermes-test-result ${proactiveResult.success || proactiveResult.ok || proactiveResult.allowed ? 'success' : 'danger'}`}>
                <strong>{proactiveResult.error || proactiveResult.message || (proactiveResult.allowed ? '权限可用' : '主动关怀已触发')}</strong>
                <span>{proactiveResult.mode || proactiveForm.target_mode}</span>
                {proactiveResult.response || proactiveResult.prompt ? <pre>{proactiveResult.response || proactiveResult.prompt}</pre> : null}
              </div>
            ) : null}

            <div className="settings-savebar">
              <span>{proactiveDirty ? '有未保存的主动关怀设置' : '主动关怀设置已同步'}</span>
              <button type="button" disabled={interactionBusy} onClick={() => void checkScreenPermission()}>
                {busyAction === 'proactive-permission' ? '检查中...' : '检查屏幕权限'}
              </button>
              <button type="button" disabled={interactionBusy} onClick={() => void runProactiveTest()}>
                {busyAction === 'proactive-test' ? '测试中...' : '立即测试'}
              </button>
              <button
                type="button"
                className={busyAction === 'proactive-save' ? 'primary-action loading-button' : 'primary-action'}
                disabled={interactionBusy || !proactiveDirty}
                onClick={() => void saveProactiveSettings()}
              >
                {busyAction === 'proactive-save' ? '保存中...' : '保存主动关怀'}
              </button>
            </div>
          </div>
        </article>

        <article className="panel">
          <div className="section-heading-row">
            <div>
              <h2>语音开关</h2>
              <p className="section-caption">
                这里配置的是 Yachiyo 主动关怀播报链路；Tools 里的“文本转语音”是 Hermes Agent 自己的工具能力，二者互不覆盖。
              </p>
            </div>
            <span>{loading ? '读取中' : enabled ? `已启用：${ttsProviderLabel(provider)}` : '只发文本'}</span>
          </div>

          <form
            className="tts-settings-form"
            onSubmit={(event) => {
              event.preventDefault();
              void saveSettings();
            }}
          >
            <div className="hermes-config-form-grid">
              <label className="settings-check wide" htmlFor="proactive-tts-enabled">
                <input
                  id="proactive-tts-enabled"
                  type="checkbox"
                  checked={form.enabled}
                  disabled={interactionBusy}
                  onChange={(event) => updateField('enabled', event.target.checked)}
                />
                <span>启用主动关怀 TTS 语音</span>
              </label>
              <label className="settings-field wide" htmlFor="proactive-tts-provider">
                <span>TTS Provider</span>
                <select
                  id="proactive-tts-provider"
                  value={provider}
                  disabled={interactionBusy}
                  onChange={(event) => updateField('provider', event.target.value)}
                >
                  <option value="none">none（关闭，主动关怀只发文本）</option>
                  <option value="gpt-sovits">GPT-SoVITS 本地服务</option>
                  <option value="http">HTTP POST</option>
                  <option value="command">本地命令</option>
                </select>
              </label>
              {provider === 'none' ? (
                <p className="capability-note wide-form-note">
                  当前不会播放语音。主动关怀仍会生成文本提醒，并继续显示在 Bubble 或 Live2D 对话气泡里。
                </p>
              ) : null}

              {provider === 'http' ? (
                <>
                  <label className="settings-field wide" htmlFor="tts-endpoint-page">
                    <span>HTTP Endpoint</span>
                    <input
                      id="tts-endpoint-page"
                      value={form.endpoint}
                      placeholder="http://127.0.0.1:9000/tts"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('endpoint', event.target.value)}
                    />
                  </label>
                  <label className="settings-field" htmlFor="tts-http-voice-page">
                    <span>音色</span>
                    <input
                      id="tts-http-voice-page"
                      value={form.voice}
                      placeholder="可选"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('voice', event.target.value)}
                    />
                  </label>
                </>
              ) : null}

              {provider === 'command' ? (
                <>
                  <label className="settings-field wide" htmlFor="tts-command-page">
                    <span>本地命令</span>
                    <input
                      id="tts-command-page"
                      value={form.command}
                      placeholder="say {text}"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('command', event.target.value)}
                    />
                  </label>
                  <label className="settings-field" htmlFor="tts-command-voice-page">
                    <span>音色</span>
                    <input
                      id="tts-command-voice-page"
                      value={form.voice}
                      placeholder="{voice}"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('voice', event.target.value)}
                    />
                  </label>
                </>
              ) : null}

              {isGsvProvider ? (
                <>
                  <div className="settings-resource-panel wide">
                    <div>
                      <strong>八千代音色包</strong>
                      <p>{voiceResource?.help_text || '可从 Releases 下载八千代 GPT-SoVITS 音色包 ZIP 并导入。'}</p>
                      <span>默认导入目录：{voiceResource?.default_assets_root_display || '—'}</span>
                    </div>
                    <div className="settings-resource-actions compact-actions">
                      <button
                        type="button"
                        className={resourceBusy ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void importVoiceArchive()}
                      >
                        {resourceBusy ? '导入中...' : filePickerAvailable ? '导入音色包 ZIP' : '按路径导入 ZIP'}
                      </button>
                      <button type="button" disabled={interactionBusy} onClick={() => void openVoiceAssetsDir()}>打开导入目录</button>
                      <button type="button" disabled={interactionBusy || !(voiceResource?.voice_package_url || voiceResource?.releases_url)} onClick={() => void openVoiceReleases()}>下载音色包</button>
                    </div>
                    {!filePickerAvailable ? (
                      <label className="settings-field wide" htmlFor="tts-voice-archive-path-page">
                        <span>音色包 ZIP 路径</span>
                        <input
                          id="tts-voice-archive-path-page"
                          value={manualVoiceArchivePath}
                          placeholder="~/Downloads/Hermes-Yachiyo-yachiyo-gpt-sovits-v4.zip"
                          disabled={interactionBusy}
                          onChange={(event) => setManualVoiceArchivePath(event.target.value)}
                        />
                      </label>
                    ) : null}
                  </div>
                  <div className="settings-resource-panel wide">
                    <div>
                      <strong>GPT-SoVITS 本地服务</strong>
                      <p>{voiceResource?.service_help_text || '音色包不包含 GPT-SoVITS 基础预训练模型与运行时；本地 API 服务需要单独部署并启动。'}</p>
                      <span>{gsvServiceStatusText(serviceStatus)}</span>
                    </div>
                    <div className="settings-resource-actions compact-actions">
                      <button
                        type="button"
                        className={busyAction === 'service-setup' ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void openGsvSetupTerminal()}
                      >
                        {busyAction === 'service-setup' ? '部署中...' : '部署运行时/基础模型'}
                      </button>
                      <button
                        type="button"
                        className={busyAction === 'service' ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void openGsvServiceTerminal()}
                      >
                        {busyAction === 'service' ? '打开中...' : '打开调试终端'}
                      </button>
                      {!externalGsvServiceDetected ? (
                        <button
                          type="button"
                          className={busyAction === 'service-install' ? 'loading-button' : undefined}
                          disabled={interactionBusy}
                          onClick={() => void installGsvLaunchAgent()}
                        >
                          {busyAction === 'service-install' ? '启动中...' : '启动本地后台/自启'}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className={busyAction === 'service-uninstall' ? 'loading-button danger-action' : 'danger-action'}
                        disabled={interactionBusy || !serviceStatus?.launch_agent_installed}
                        onClick={() => void uninstallGsvLaunchAgent()}
                      >
                        {busyAction === 'service-uninstall' ? '停止中...' : '停止本地后台'}
                      </button>
                      <button type="button" disabled={interactionBusy} onClick={() => void refreshGsvServiceStatus()}>刷新状态</button>
                    </div>
                    {externalGsvServiceDetected ? (
                      <div className="settings-resource-fallback">
                        <p className="settings-note">
                          检测到外部 GPT-SoVITS 服务：{externalGsvAgent?.label || '未知 LaunchAgent'}。
                          复用会保留原服务；接管会停用该自启项并改由 Hermes-Yachiyo 管理。
                        </p>
                        <button
                          type="button"
                          className={busyAction === 'service-use-existing' ? 'loading-button' : undefined}
                          disabled={interactionBusy}
                          onClick={() => void useExistingGsvService()}
                        >
                          {busyAction === 'service-use-existing' ? '保存中...' : '使用现有服务'}
                        </button>
                        <button
                          type="button"
                          className={busyAction === 'service-adopt' ? 'loading-button' : undefined}
                          disabled={interactionBusy}
                          onClick={() => void adoptGsvLaunchAgent()}
                        >
                          {busyAction === 'service-adopt' ? '接管中...' : '交由 Yachiyo 管理'}
                        </button>
                      </div>
                    ) : null}
                    <p className="capability-note wide-form-note">
                      运行时部署会准备 Python 环境和 GPT-SoVITS 基础预训练模型；调试终端是前台临时运行；本地后台/自启会使用 macOS LaunchAgent 管理服务。
                    </p>
                    <label className="settings-field wide" htmlFor="tts-gsv-service-workdir-page">
                      <span>GPT-SoVITS 服务目录</span>
                      <input
                        id="tts-gsv-service-workdir-page"
                        value={form.gsv_service_workdir}
                        placeholder={voiceResource?.default_service_workdir_display || '~/AI/GPT-SoVITS'}
                        disabled={interactionBusy}
                        onChange={(event) => updateField('gsv_service_workdir', event.target.value)}
                      />
                    </label>
                    <label className="settings-field wide" htmlFor="tts-gsv-service-command-page">
                      <span>服务启动命令</span>
                      <input
                        id="tts-gsv-service-command-page"
                        value={form.gsv_service_command}
                        placeholder="python api_v2.py -a 127.0.0.1 -p 9880"
                        disabled={interactionBusy}
                        onChange={(event) => updateField('gsv_service_command', event.target.value)}
                      />
                    </label>
                    {serviceStatus ? (
                      <div className="settings-meta-list wide">
                        <div className="settings-meta-row">
                          <span>API 可达</span>
                          <strong className={serviceStatus.reachable ? 'ok' : 'warn'}>{serviceStatus.reachable ? '可达' : serviceStatus.reachable_error || '不可达'}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>服务目录</span>
                          <strong className={serviceStatus.workdir_exists ? 'ok' : 'warn'}>{serviceStatus.workdir_exists ? serviceStatus.workdir_display || '已配置' : '未配置或不存在'}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>API 进程</span>
                          <strong className={serviceStatus.api_process?.running ? 'ok' : 'warn'}>{formatGsvApiProcess(serviceStatus.api_process)}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>自启管理</span>
                          <strong>{formatGsvLaunchAgentStatus(serviceStatus)}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>LaunchAgent</span>
                          <strong>{serviceStatus.plist_path_display || '—'}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>依赖检查</span>
                          <strong>{formatGsvTools(serviceStatus.tools)}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>模型检查</span>
                          <strong>{formatGsvModels(serviceStatus.models)}</strong>
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <label className="settings-field wide" htmlFor="tts-gsv-base-url-page">
                    <span>API Base URL</span>
                    <input
                      id="tts-gsv-base-url-page"
                      value={form.gsv_base_url}
                      placeholder="http://127.0.0.1:9880"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_base_url', event.target.value)}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-gsv-gpt-weights-page">
                    <span>GPT 模型文件路径</span>
                    <input
                      id="tts-gsv-gpt-weights-page"
                      value={form.gsv_gpt_weights_path}
                      placeholder="/Users/.../GPT_weights_v4/yachiyo.ckpt"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_gpt_weights_path', event.target.value)}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-gsv-sovits-weights-page">
                    <span>SoVITS 模型文件路径</span>
                    <input
                      id="tts-gsv-sovits-weights-page"
                      value={form.gsv_sovits_weights_path}
                      placeholder="/Users/.../SoVITS_weights_v4/yachiyo.pth"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_sovits_weights_path', event.target.value)}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-gsv-ref-audio-page">
                    <span>参考音频文件路径</span>
                    <input
                      id="tts-gsv-ref-audio-page"
                      value={form.gsv_ref_audio_path}
                      placeholder="/Users/.../yachiyo_ref.wav"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_ref_audio_path', event.target.value)}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-gsv-ref-text-page">
                    <span>参考音频文本</span>
                    <input
                      id="tts-gsv-ref-text-page"
                      value={form.gsv_ref_audio_text}
                      placeholder="参考音频中说出的文本"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_ref_audio_text', event.target.value)}
                    />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-ref-lang-page">
                    <span>参考文本语言</span>
                    <input
                      id="tts-gsv-ref-lang-page"
                      value={form.gsv_ref_audio_language}
                      placeholder="ja"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_ref_audio_language', event.target.value)}
                    />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-text-lang-page">
                    <span>播报文本语言</span>
                    <input
                      id="tts-gsv-text-lang-page"
                      value={form.gsv_text_language}
                      placeholder="zh"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_text_language', event.target.value)}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-gsv-aux-ref-page">
                    <span>辅助参考音频路径</span>
                    <input
                      id="tts-gsv-aux-ref-page"
                      value={form.gsv_aux_ref_audio_path}
                      placeholder="可选"
                      disabled={interactionBusy}
                      onChange={(event) => updateField('gsv_aux_ref_audio_path', event.target.value)}
                    />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-top-k-page">
                    <span>多样性 Top K</span>
                    <input id="tts-gsv-top-k-page" type="number" min={1} max={100} value={form.gsv_top_k} disabled={interactionBusy} onChange={(event) => updateField('gsv_top_k', Number(event.target.value))} />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-top-p-page">
                    <span>核采样阈值</span>
                    <input id="tts-gsv-top-p-page" type="number" min={0} max={2} step="0.01" value={form.gsv_top_p} disabled={interactionBusy} onChange={(event) => updateField('gsv_top_p', Number(event.target.value))} />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-temperature-page">
                    <span>随机性</span>
                    <input id="tts-gsv-temperature-page" type="number" min={0} max={2} step="0.01" value={form.gsv_temperature} disabled={interactionBusy} onChange={(event) => updateField('gsv_temperature', Number(event.target.value))} />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-cut-page">
                    <span>切分文本方法</span>
                    <select id="tts-gsv-cut-page" value={form.gsv_text_split_method} disabled={interactionBusy} onChange={(event) => updateField('gsv_text_split_method', event.target.value)}>
                      <option value="cut0">cut0 不切分</option>
                      <option value="cut1">cut1 四句一切</option>
                      <option value="cut2">cut2 50字一切</option>
                      <option value="cut3">cut3 中文句号</option>
                      <option value="cut4">cut4 英文句号</option>
                      <option value="cut5">cut5 标点符号</option>
                    </select>
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-batch-size-page">
                    <span>批处理大小</span>
                    <input id="tts-gsv-batch-size-page" type="number" min={1} max={64} value={form.gsv_batch_size} disabled={interactionBusy} onChange={(event) => updateField('gsv_batch_size', Number(event.target.value))} />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-batch-threshold-page">
                    <span>批处理阈值</span>
                    <input id="tts-gsv-batch-threshold-page" type="number" min={0} max={1} step="0.01" value={form.gsv_batch_threshold} disabled={interactionBusy} onChange={(event) => updateField('gsv_batch_threshold', Number(event.target.value))} />
                  </label>
                  <label className="settings-check wide" htmlFor="tts-gsv-split-bucket-page">
                    <input id="tts-gsv-split-bucket-page" type="checkbox" checked={form.gsv_split_bucket} disabled={interactionBusy} onChange={(event) => updateField('gsv_split_bucket', event.target.checked)} />
                    <span>将文本分到桶中处理</span>
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-speed-page">
                    <span>语音播放速度</span>
                    <input id="tts-gsv-speed-page" type="number" min={0.25} max={4} step="0.05" value={form.gsv_speed_factor} disabled={interactionBusy} onChange={(event) => updateField('gsv_speed_factor', Number(event.target.value))} />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-fragment-page">
                    <span>片段间隔秒</span>
                    <input id="tts-gsv-fragment-page" type="number" min={0} max={10} step="0.1" value={form.gsv_fragment_interval} disabled={interactionBusy} onChange={(event) => updateField('gsv_fragment_interval', Number(event.target.value))} />
                  </label>
                  <label className="settings-check wide" htmlFor="tts-gsv-stream-page">
                    <input id="tts-gsv-stream-page" type="checkbox" checked={form.gsv_streaming_mode} disabled={interactionBusy} onChange={(event) => updateField('gsv_streaming_mode', event.target.checked)} />
                    <span>启用流模式</span>
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-seed-page">
                    <span>随机种子</span>
                    <input id="tts-gsv-seed-page" type="number" min={-1} value={form.gsv_seed} disabled={interactionBusy} onChange={(event) => updateField('gsv_seed', Number(event.target.value))} />
                  </label>
                  <label className="settings-check wide" htmlFor="tts-gsv-parallel-page">
                    <input id="tts-gsv-parallel-page" type="checkbox" checked={form.gsv_parallel_infer} disabled={interactionBusy} onChange={(event) => updateField('gsv_parallel_infer', event.target.checked)} />
                    <span>并行执行推理</span>
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-repetition-page">
                    <span>重复惩罚因子</span>
                    <input id="tts-gsv-repetition-page" type="number" min={0.1} max={5} step="0.01" value={form.gsv_repetition_penalty} disabled={interactionBusy} onChange={(event) => updateField('gsv_repetition_penalty', Number(event.target.value))} />
                  </label>
                  <label className="settings-field" htmlFor="tts-gsv-media-page">
                    <span>输出媒体类型</span>
                    <select id="tts-gsv-media-page" value={form.gsv_media_type} disabled={interactionBusy} onChange={(event) => updateField('gsv_media_type', event.target.value)}>
                      <option value="wav">wav</option>
                      <option value="mp3">mp3</option>
                      <option value="ogg">ogg</option>
                      <option value="flac">flac</option>
                    </select>
                  </label>
                </>
              ) : null}

              {provider !== 'none' ? (
                <>
                  <label className="settings-field" htmlFor="tts-max-chars-page">
                    <span>播报最大字数</span>
                    <input
                      id="tts-max-chars-page"
                      type="number"
                      min={20}
                      max={240}
                      value={form.max_chars}
                      disabled={interactionBusy}
                      onChange={(event) => updateField('max_chars', Number(event.target.value))}
                    />
                  </label>
                  <label className="settings-field" htmlFor="tts-timeout-page">
                    <span>超时秒</span>
                    <input
                      id="tts-timeout-page"
                      type="number"
                      min={1}
                      max={600}
                      value={form.timeout_seconds}
                      disabled={interactionBusy}
                      onChange={(event) => updateField('timeout_seconds', Number(event.target.value))}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-prompt-page">
                    <span>主动播报提示词</span>
                    <textarea
                      id="tts-prompt-page"
                      value={form.notification_prompt}
                      rows={3}
                      disabled={interactionBusy}
                      onChange={(event) => updateField('notification_prompt', event.target.value)}
                    />
                  </label>
                  <label className="settings-field wide" htmlFor="tts-test-text-page">
                    <span>测试文本</span>
                    <input
                      id="tts-test-text-page"
                      value={testText}
                      disabled={interactionBusy}
                      onChange={(event) => {
                        setTestText(event.target.value);
                        setTestResult(null);
                      }}
                    />
                  </label>
                </>
              ) : null}
            </div>

            {testResult ? (
              <div className={`hermes-test-result ${testResult.success ? 'success' : 'danger'}`}>
                <strong>{testResult.success ? testResult.message || '测试语音已完成' : testResult.error || testResult.message || '测试语音失败'}</strong>
                <span>{testResult.provider ? `Provider: ${ttsProviderLabel(testResult.provider)}` : '—'}</span>
                {testResult.spoken_text ? <pre>{testResult.spoken_text}</pre> : null}
              </div>
            ) : null}

            <div className="settings-savebar">
              <span>{isDirty ? '有未保存的语音设置' : enabled ? '语音设置已同步' : '主动关怀将只发送文字'}</span>
              <button type="button" disabled={interactionBusy || !isDirty} onClick={resetDraft}>重置草稿</button>
              <button
                type="button"
                className={busyAction === 'test' ? 'loading-button' : undefined}
                disabled={interactionBusy || provider === 'none'}
                onClick={() => void saveAndTestSettings()}
              >
                {busyAction === 'test' ? '测试中...' : '保存并测试'}
              </button>
              <button
                type="submit"
                className={busyAction === 'save' ? 'primary-action loading-button' : 'primary-action'}
                disabled={interactionBusy}
              >
                {busyAction === 'save' ? '保存中...' : '保存语音设置'}
              </button>
            </div>
          </form>
        </article>
      </section>
    </main>
  );
}

function ttsFromSettings(settings: SettingsData | null): TtsSettings | undefined {
  return settings?.tts || settings?.mode_settings?.live2d?.config?.tts || settings?.mode_settings?.bubble?.config?.tts;
}

function emptyProactiveForm(): ProactiveForm {
  return {
    enabled: false,
    desktop_watch_enabled: false,
    interval_seconds: String(MIN_PROACTIVE_INTERVAL_SECONDS),
    trigger_probability_percent: '60',
    target_mode: 'live2d',
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
    proactive_interval_seconds: Number(live2d?.proactive_interval_seconds || bubble?.proactive_interval_seconds || MIN_PROACTIVE_INTERVAL_SECONDS),
    proactive_trigger_probability: Number(live2d?.proactive_trigger_probability ?? bubble?.proactive_trigger_probability ?? 0.6),
  };
}

function formFromProactiveSettings(settings: ModeProactiveSettings | undefined): ProactiveForm {
  const probability = clampProbability(Number(settings?.proactive_trigger_probability ?? 0.6));
  return {
    enabled: Boolean(settings?.proactive_enabled),
    desktop_watch_enabled: Boolean(settings?.proactive_desktop_watch_enabled),
    interval_seconds: String(normalizeProactiveInterval(settings?.proactive_interval_seconds || MIN_PROACTIVE_INTERVAL_SECONDS)),
    trigger_probability_percent: String(Math.round(probability * 100)),
    target_mode: 'live2d',
  };
}

function normalizeProactiveInterval(value: string | number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return MIN_PROACTIVE_INTERVAL_SECONDS;
  return Math.max(MIN_PROACTIVE_INTERVAL_SECONDS, Math.min(3600, Math.round(parsed)));
}

function clampProbability(value: number): number {
  if (!Number.isFinite(value)) return 0.6;
  return Math.max(0, Math.min(1, value));
}

function shouldShowRuntimeStatus(status: TtsRuntimeStatus | null): status is TtsRuntimeStatus {
  if (!status) return false;
  if (status.error || status.pending_audio || status.audio_ready || status.scheduled) return true;
  const message = String(status.message || '').trim();
  return Boolean(message && !/待触发|未启用|配置不存在/.test(message));
}

function ttsRuntimeStatusTone(status: TtsRuntimeStatus) {
  if (status.ok === false || status.success === false || status.error) return 'danger';
  if (status.pending_audio || status.scheduled) return 'warn';
  return '';
}

function ttsRuntimeStatusTitle(status: TtsRuntimeStatus) {
  if (status.pending_audio || status.scheduled) return '最近一次主动播报正在生成语音';
  if (status.ok === false || status.success === false || status.error) return '最近一次主动播报语音失败';
  if (status.audio_ready || status.success || status.ok) return '最近一次主动播报语音已完成';
  return '最近一次主动播报语音状态';
}

function ttsRuntimeStatusDetail(status: TtsRuntimeStatus) {
  const provider = status.provider ? ttsProviderLabel(status.provider) : '未知 Provider';
  const message = status.error || status.message || '暂无详细信息';
  const spoken = status.spoken_text ? `；播报文本：${status.spoken_text}` : '';
  return `${provider}：${message}${spoken}`;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, "'\\''")}'`;
}

function homePlaceholder(): string {
  return '$HOME';
}

const GSV_PRETRAINED_MODEL_URLS = [
  'https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master/pretrained_models.zip',
  'https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip',
  'https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip',
];

const GSV_G2PW_MODEL_URLS = [
  'https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master/G2PWModel.zip',
  'https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip',
  'https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip',
];

function buildGsvServiceTerminalCommand(form: TtsForm): string {
  const workdirAssignment = buildShellPathAssignment('WORKDIR', form.gsv_service_workdir.trim());
  const serviceCommand = form.gsv_service_command.trim();
  return [
    'echo "Hermes-Yachiyo GPT-SoVITS 服务启动"',
    workdirAssignment,
    'cd "$WORKDIR"',
    'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi',
    'if [ -f venv/bin/activate ]; then source venv/bin/activate; fi',
    serviceCommand,
  ].join('\n');
}

function buildGsvSetupTerminalCommand(workdir: string, serviceCommand: string, projectUrl?: string): string {
  const workdirAssignment = buildShellPathAssignment('WORKDIR', workdir.trim() || '$HOME/AI/GPT-SoVITS');
  const quotedProjectUrl = shellQuote(projectUrl || 'https://github.com/RVC-Boss/GPT-SoVITS');
  const configuredCommand = serviceCommand.trim() || 'python api_v2.py -a 127.0.0.1 -p 9880';
  return [
    'echo "Hermes-Yachiyo GPT-SoVITS 一键部署"',
    'echo "此流程会克隆 GPT-SoVITS、创建 .venv、安装依赖并准备预训练模型；不会直接启动本地 API。"',
    'echo "下载体积可能较大；脚本会优先准备 Homebrew python@3.11、ffmpeg、mecab 与 unzip。"',
    'printf "继续执行部署？[y/N] "',
    'read answer',
    'case "$answer" in [yY]|[yY][eE][sS]) ;; *) echo "已取消。"; exit 1 ;; esac',
    'set -e',
    'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'if command -v brew >/dev/null 2>&1; then',
    '  echo "检查 Homebrew 依赖：git ffmpeg mecab python@3.11 unzip"',
    '  brew list git >/dev/null 2>&1 || brew install git',
    '  brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg',
    '  brew list mecab >/dev/null 2>&1 || brew install mecab',
    '  brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11',
    '  brew list unzip >/dev/null 2>&1 || brew install unzip',
    '  if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    '  if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'fi',
    'if ! command -v git >/dev/null 2>&1; then echo "未找到 git，请先安装 Git。"; exit 1; fi',
    'if ! command -v unzip >/dev/null 2>&1; then echo "未找到 unzip，请先安装 unzip。"; exit 1; fi',
    'if ! command -v mecab-config >/dev/null 2>&1; then echo "未找到 mecab-config。请先执行：brew install mecab"; exit 1; fi',
    'PYTHON_BIN=""',
    'for candidate in python3.11 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do',
    '  if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$(command -v "$candidate")"; break; fi',
    '  if [ -x "$candidate" ]; then PYTHON_BIN="$candidate"; break; fi',
    'done',
    'if [ -z "$PYTHON_BIN" ]; then echo "未找到 Python 3.11。请先执行：brew install python@3.11"; exit 1; fi',
    'PY_VERSION="$("$PYTHON_BIN" -V 2>&1 | awk \'{print $2}\' | cut -d. -f1,2)"',
    'if [ "$PY_VERSION" != "3.11" ]; then echo "当前 Python 版本为 $PY_VERSION，GPT-SoVITS 本地部署需要 Python 3.11。"; exit 1; fi',
    workdirAssignment,
    `PROJECT_URL=${quotedProjectUrl}`,
    'mkdir -p "$(dirname "$WORKDIR")"',
    'if [ ! -d "$WORKDIR/.git" ]; then',
    '  echo "克隆 GPT-SoVITS 到 $WORKDIR"',
    '  git clone "$PROJECT_URL" "$WORKDIR"',
    'fi',
    'cd "$WORKDIR"',
    ...buildGsvPretrainedModelSetupLines(),
    ...buildGsvG2pwModelSetupLines(),
    'if [ -x .venv/bin/python ]; then',
    '  VENV_VERSION="$(.venv/bin/python -V 2>&1 | awk \'{print $2}\' | cut -d. -f1,2)"',
    '  if [ "$VENV_VERSION" != "3.11" ]; then',
    '    echo "检测到现有 .venv 使用 Python $VENV_VERSION，将重建为 Python 3.11"',
    '    rm -rf .venv',
    '  fi',
    'fi',
    'if [ ! -d .venv ]; then',
    '  "$PYTHON_BIN" -m venv .venv',
    'fi',
    'source .venv/bin/activate',
    'python -V',
    'python -m pip install --upgrade pip wheel setuptools',
    'if [ -f requirements.txt ]; then',
    '  python -m pip install -r requirements.txt',
    'else',
    '  echo "未找到 requirements.txt，跳过依赖安装。"',
    'fi',
    'python -m pip install torchcodec',
    'python -c "import torchcodec"',
    `SERVICE_COMMAND=${shellQuote(configuredCommand)}`,
    'echo "本地依赖部署完成。"',
    'echo "如果需要前台调试，可回到设置页点击“打开调试终端”，或手动运行：$SERVICE_COMMAND"',
    'echo "如果需要后台运行，请回到设置页点击“启动本地后台/自启”。"',
  ].join('\n');
}

function buildGsvPretrainedModelSetupLines(): string[] {
  const urls = `PRETRAINED_MODEL_URLS=(${GSV_PRETRAINED_MODEL_URLS.map(shellQuote).join(' ')})`;
  return [
    'PRETRAINED_DIR="GPT_SoVITS/pretrained_models"',
    'MISSING_PRETRAINED=0',
    'for required_model in "$PRETRAINED_DIR/s1v3.ckpt" "$PRETRAINED_DIR/gsv-v4-pretrained/s2Gv4.pth" "$PRETRAINED_DIR/gsv-v4-pretrained/vocoder.pth"; do',
    '  if [ ! -s "$required_model" ]; then MISSING_PRETRAINED=1; fi',
    'done',
    'if [ ! -s "$PRETRAINED_DIR/chinese-roberta-wwm-ext-large/pytorch_model.bin" ] && [ ! -s "$PRETRAINED_DIR/chinese-roberta-wwm-ext-large/model.safetensors" ]; then MISSING_PRETRAINED=1; fi',
    'if [ ! -s "$PRETRAINED_DIR/chinese-hubert-base/pytorch_model.bin" ] && [ ! -s "$PRETRAINED_DIR/chinese-hubert-base/model.safetensors" ]; then MISSING_PRETRAINED=1; fi',
    'if [ "$MISSING_PRETRAINED" -eq 1 ]; then',
    '  echo "检测到 GPT-SoVITS 预训练模型不完整，开始下载 pretrained_models.zip"',
    urls,
    '  PRETRAINED_ZIP="$(mktemp "${TMPDIR:-/tmp}/hermes-gsv-pretrained.XXXXXX")"',
    '  DOWNLOAD_OK=0',
    '  for PRETRAINED_URL in "${PRETRAINED_MODEL_URLS[@]}"; do',
    '    echo "下载：$PRETRAINED_URL"',
    '    if command -v curl >/dev/null 2>&1; then',
    '      if curl -L --fail --retry 5 --connect-timeout 20 -o "$PRETRAINED_ZIP" "$PRETRAINED_URL"; then DOWNLOAD_OK=1; break; fi',
    '    else',
    "      if \"$PYTHON_BIN\" -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \"$PRETRAINED_URL\" \"$PRETRAINED_ZIP\"; then DOWNLOAD_OK=1; break; fi",
    '    fi',
    '  done',
    '  if [ "$DOWNLOAD_OK" -ne 1 ]; then echo "预训练模型下载失败，请检查网络后重试。"; rm -f "$PRETRAINED_ZIP"; exit 1; fi',
    '  unzip -q -o "$PRETRAINED_ZIP" -d GPT_SoVITS',
    '  rm -f "$PRETRAINED_ZIP"',
    '  echo "GPT-SoVITS 预训练模型已准备完成"',
    'else',
    '  echo "GPT-SoVITS 预训练模型已存在，跳过下载"',
    'fi',
  ];
}

function buildGsvG2pwModelSetupLines(): string[] {
  const urls = `G2PW_MODEL_URLS=(${GSV_G2PW_MODEL_URLS.map(shellQuote).join(' ')})`;
  return [
    'G2PW_DIR="GPT_SoVITS/text/G2PWModel"',
    'if [ ! -s "$G2PW_DIR/g2pW.onnx" ]; then',
    '  echo "检测到中文 G2PW 模型不完整，开始下载 G2PWModel.zip"',
    urls,
    '  G2PW_ZIP="$(mktemp "${TMPDIR:-/tmp}/hermes-gsv-g2pw.XXXXXX")"',
    '  DOWNLOAD_OK=0',
    '  for G2PW_URL in "${G2PW_MODEL_URLS[@]}"; do',
    '    echo "下载：$G2PW_URL"',
    '    if command -v curl >/dev/null 2>&1; then',
    '      if curl -L --fail --retry 5 --connect-timeout 20 -o "$G2PW_ZIP" "$G2PW_URL"; then DOWNLOAD_OK=1; break; fi',
    '    else',
    "      if \"$PYTHON_BIN\" -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \"$G2PW_URL\" \"$G2PW_ZIP\"; then DOWNLOAD_OK=1; break; fi",
    '    fi',
    '  done',
    '  if [ "$DOWNLOAD_OK" -ne 1 ]; then echo "G2PW 模型下载失败，请检查网络后重试。"; rm -f "$G2PW_ZIP"; exit 1; fi',
    '  rm -rf "$G2PW_DIR"',
    '  unzip -q -o "$G2PW_ZIP" -d GPT_SoVITS/text',
    '  rm -f "$G2PW_ZIP"',
    '  if [ ! -s "$G2PW_DIR/g2pW.onnx" ]; then echo "G2PW 模型解压后仍缺少 g2pW.onnx。"; exit 1; fi',
    '  echo "中文 G2PW 模型已准备完成"',
    'else',
    '  echo "中文 G2PW 模型已存在，跳过下载"',
    'fi',
  ];
}

function buildShellPathAssignment(name: string, value: string): string {
  if (value === '$HOME' || value.startsWith('$HOME/')) {
    return `${name}="$HOME${value.slice('$HOME'.length)}"`;
  }
  if (value === '~' || value.startsWith('~/')) {
    return `${name}="$HOME${value.slice(1)}"`;
  }
  return `${name}=${shellQuote(value)}`;
}

function gsvServiceStatusText(status: GptSovitsServiceStatus | null): string {
  if (!status) return '推荐端口：9880；服务启动后再执行保存并测试。';
  if (status.workdir_exists && status.tools?.torchcodec === false) return '缺少 torchcodec，请重新执行“部署运行时/基础模型”后再测试语音。';
  if (status.workdir_exists && status.missing_model_files?.length) return '缺少 GPT-SoVITS 预训练模型，请重新执行“部署运行时/基础模型”后再测试语音。';
  if (status.reachable && status.api_process?.running && !status.launch_agent_installed) {
    const agent = firstExternalGsvLaunchAgent(status);
    if (agent?.label) return `API 已可达；检测到正在运行的服务进程，由其他 LaunchAgent 管理：${agent.label}。`;
    return 'API 已可达；检测到正在运行的服务进程，但不是由 Hermes-Yachiyo 后台服务管理。';
  }
  if (status.reachable) return 'API 已可达；可以保存并测试语音链路。';
  if (!status.workdir_exists) return '请先填写 GPT-SoVITS 服务目录，或先安装 GPT-SoVITS 本体。';
  if (!status.command_configured) return '请先填写服务启动命令。';
  if (status.tools?.python311 === false) return '建议先安装 Python 3.11：brew install python@3.11。';
  if (status.tools?.mecab_config === false) return '缺少 mecab-config，部署前需要：brew install mecab。';
  if (status.launch_agent_installed) return status.launch_agent_running ? 'LaunchAgent 已运行，等待 API 就绪。' : 'LaunchAgent 已安装但未运行，可尝试重新启动后台服务或打开调试终端查看日志。';
  return status.reachable_error || '本地 API 暂不可达，可打开调试终端或启动本地后台服务。';
}

function formatGsvTools(tools?: Record<string, boolean>): string {
  if (!tools) return '—';
  const items: Array<[string, boolean | undefined]> = [
    ['Python 3.11', tools.python311],
    ['git', tools.git],
    ['ffmpeg', tools.ffmpeg],
    ['mecab-config', tools.mecab_config],
    ['torchcodec', tools.torchcodec],
  ];
  return items.map(([label, ok]) => `${label} ${ok ? '可用' : '缺失'}`).join(' / ');
}

function formatGsvApiProcess(process?: GptSovitsServiceStatus['api_process']): string {
  if (!process?.running) return '未检测到监听进程';
  const pid = process.pid ? `PID ${process.pid}` : '运行中';
  const port = process.port ? `:${process.port}` : '';
  const launchd = process.ppid === 1 ? '，launchd 持有' : '';
  return `${pid}${port}${launchd}`;
}

function formatGsvLaunchAgentStatus(status: GptSovitsServiceStatus): string {
  if (status.launch_agent_installed) {
    return status.launch_agent_running ? 'Hermes 已安装并运行' : 'Hermes 已安装，待启动';
  }
  const agent = firstExternalGsvLaunchAgent(status);
  if (agent?.label) {
    return `其他 LaunchAgent：${agent.label}${agent.running ? '（运行中）' : '（未运行）'}`;
  }
  return '未安装';
}

function hasExternalGsvService(status: GptSovitsServiceStatus | null): boolean {
  return Boolean(status?.api_process?.running && !status.launch_agent_installed && firstExternalGsvLaunchAgent(status));
}

function firstExternalGsvLaunchAgent(status: GptSovitsServiceStatus | null | undefined) {
  return status?.related_launch_agents?.find((agent) => !agent.managed_by_hermes);
}

function formatGsvModels(models?: Record<string, boolean>): string {
  if (!models || Object.keys(models).length === 0) return '—';
  const items: Array<[string, boolean | undefined]> = [
    ['s1v3', models.s1v3],
    ['s2Gv4', models.s2Gv4],
    ['vocoder', models.vocoder],
    ['G2PW', models.g2pw],
    ['BERT', models.bert],
    ['CNHuBERT', models.cnhubert],
  ];
  return items.map(([label, ok]) => `${label} ${ok ? '就绪' : '缺失'}`).join(' / ');
}
