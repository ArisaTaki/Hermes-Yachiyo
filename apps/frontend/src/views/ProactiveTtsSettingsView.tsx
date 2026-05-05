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
    live2d?: { config?: { tts?: TtsSettings } };
    bubble?: { config?: { tts?: TtsSettings } };
  };
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
  platform_supported?: boolean;
  plist_path_display?: string;
  tools?: Record<string, boolean>;
  logs?: { stdout?: string; stderr?: string };
};

type TtsVoiceImportResult = SettingsUpdateResult & {
  imported_path?: string;
  imported_path_display?: string;
  tts_settings?: TtsSettings;
  resource?: TtsVoiceResource;
  message?: string;
};

export function ProactiveTtsSettingsView() {
  const [form, setForm] = useState<TtsForm>(emptyTtsForm());
  const [savedForm, setSavedForm] = useState<TtsForm>(emptyTtsForm());
  const [testText, setTestText] = useState('八千代语音测试成功。主动关怀播报已经可以正常调用。');
  const [testResult, setTestResult] = useState<TtsTestResult | null>(null);
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
        if (!disposed) {
          setForm(next);
          setSavedForm(next);
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
    setStatus('正在导入八千代语音包...');
    try {
      const selectedPath = hasDesktopFilePicker()
        ? await chooseLive2DArchive()
        : manualVoiceArchivePath.trim();
      if (!selectedPath) {
        setStatus(hasDesktopFilePicker() ? '已取消导入语音包' : '请输入语音包 ZIP 路径');
        return;
      }
      const result = await apiPost<TtsVoiceImportResult>('/ui/tts/voice-resource/import', { path: selectedPath });
      if (result.ok === false) throw new Error(result.error || '导入语音包失败');
      const next = formFromTtsSettings(result.tts_settings || {});
      setForm((current) => ({
        ...current,
        ...next,
        gsv_base_url: current.gsv_base_url || next.gsv_base_url,
      }));
      setVoiceResource(result.resource || voiceResource);
      setTestResult(null);
      const displayPath = result.imported_path_display ? `：${result.imported_path_display}` : '';
      setStatus(`${result.message || '语音包已导入，等待保存 TTS 设置'}${displayPath}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '导入语音包失败');
    } finally {
      setResourceBusy(false);
    }
  }

  async function openVoiceAssetsDir() {
    const root = voiceResource?.default_assets_root || '';
    if (!root) {
      setStatus('未找到语音包导入目录');
      return;
    }
    try {
      await openPath(root);
      setStatus(`已打开语音包导入目录：${voiceResource?.default_assets_root_display || root}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开语音包导入目录失败');
    }
  }

  async function openVoiceReleases() {
    const url = voiceResource?.voice_package_url || voiceResource?.releases_url || '';
    if (!url) {
      setStatus('未配置语音包下载地址');
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
  const filePickerAvailable = hasDesktopFilePicker();
  const busy = Boolean(busyAction);
  const interactionBusy = busy || loading || resourceBusy;

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

      <section className="dashboard-workbench single-column">
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
                      <strong>八千代语音包</strong>
                      <p>{voiceResource?.help_text || '可从 Releases 下载八千代 GPT-SoVITS 语音包 ZIP 并导入。'}</p>
                      <span>默认导入目录：{voiceResource?.default_assets_root_display || '—'}</span>
                    </div>
                    <div className="settings-resource-actions compact-actions">
                      <button
                        type="button"
                        className={resourceBusy ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void importVoiceArchive()}
                      >
                        {resourceBusy ? '导入中...' : filePickerAvailable ? '导入语音包 ZIP' : '按路径导入 ZIP'}
                      </button>
                      <button type="button" disabled={interactionBusy} onClick={() => void openVoiceAssetsDir()}>打开导入目录</button>
                      <button type="button" disabled={interactionBusy || !(voiceResource?.voice_package_url || voiceResource?.releases_url)} onClick={() => void openVoiceReleases()}>下载语音包</button>
                    </div>
                    {!filePickerAvailable ? (
                      <label className="settings-field wide" htmlFor="tts-voice-archive-path-page">
                        <span>语音包 ZIP 路径</span>
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
                      <p>{voiceResource?.service_help_text || '语音包只负责音色文件；本地 GPT-SoVITS API 服务需要单独运行。'}</p>
                      <span>{gsvServiceStatusText(serviceStatus)}</span>
                    </div>
                    <div className="settings-resource-actions compact-actions">
                      <button
                        type="button"
                        className={busyAction === 'service-setup' ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void openGsvSetupTerminal()}
                      >
                        {busyAction === 'service-setup' ? '部署中...' : '部署本地依赖'}
                      </button>
                      <button
                        type="button"
                        className={busyAction === 'service' ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void openGsvServiceTerminal()}
                      >
                        {busyAction === 'service' ? '打开中...' : '打开调试终端'}
                      </button>
                      <button
                        type="button"
                        className={busyAction === 'service-install' ? 'loading-button' : undefined}
                        disabled={interactionBusy}
                        onClick={() => void installGsvLaunchAgent()}
                      >
                        {busyAction === 'service-install' ? '启动中...' : '启动本地后台/自启'}
                      </button>
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
                    <p className="capability-note wide-form-note">
                      本地依赖部署只准备 Python 环境；调试终端是前台临时运行；本地后台/自启会使用 macOS LaunchAgent 管理服务。
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
                          <span>本地自启</span>
                          <strong>{serviceStatus.launch_agent_installed ? (serviceStatus.launch_agent_running ? '已安装并运行' : '已安装，待启动') : '未安装'}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>LaunchAgent</span>
                          <strong>{serviceStatus.plist_path_display || '—'}</strong>
                        </div>
                        <div className="settings-meta-row">
                          <span>依赖检查</span>
                          <strong>{formatGsvTools(serviceStatus.tools)}</strong>
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

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, "'\\''")}'`;
}

function homePlaceholder(): string {
  return '$HOME';
}

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
    'echo "此流程会克隆 GPT-SoVITS、创建 .venv 并安装依赖；不会直接启动本地 API。"',
    'echo "下载体积可能较大；脚本会优先准备 Homebrew python@3.11、ffmpeg 与 mecab。"',
    'printf "继续执行部署？[y/N] "',
    'read answer',
    'case "$answer" in [yY]|[yY][eE][sS]) ;; *) echo "已取消。"; exit 1 ;; esac',
    'set -e',
    'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'if command -v brew >/dev/null 2>&1; then',
    '  echo "检查 Homebrew 依赖：git ffmpeg mecab python@3.11"',
    '  brew list git >/dev/null 2>&1 || brew install git',
    '  brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg',
    '  brew list mecab >/dev/null 2>&1 || brew install mecab',
    '  brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11',
    '  if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    '  if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'fi',
    'if ! command -v git >/dev/null 2>&1; then echo "未找到 git，请先安装 Git。"; exit 1; fi',
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
    `SERVICE_COMMAND=${shellQuote(configuredCommand)}`,
    'echo "本地依赖部署完成。"',
    'echo "如果需要前台调试，可回到设置页点击“打开调试终端”，或手动运行：$SERVICE_COMMAND"',
    'echo "如果需要后台运行，请回到设置页点击“启动本地后台/自启”。"',
  ].join('\n');
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
  ];
  return items.map(([label, ok]) => `${label} ${ok ? '可用' : '缺失'}`).join(' / ');
}
