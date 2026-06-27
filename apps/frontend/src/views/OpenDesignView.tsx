import { Suspense, createContext, lazy, FormEvent, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type FocusEvent as ReactFocusEvent, type PointerEvent as ReactPointerEvent } from 'react';

import logoUrl from '../../../../docs/open-design/logo.png';
import { useConfirmDialog } from '../components/ConfirmDialog';
import { UiIcon, type UiIconName } from '../components/UiIcon';
import { LauncherAgentTaskLight } from '../features/yachiyo-chat/components/LauncherAgentTaskLight';
import {
  approveYachiyoTask,
  cancelYachiyoTask,
  getYachiyoTask,
  listYachiyoTasks,
  rejectYachiyoTask,
  startYachiyoTask,
} from '../features/yachiyo-chat/api';
import {
  LAUNCHER_MAIN_AGENT_ID,
  launcherAgentTaskFromPublicTasks,
  launcherAgentTaskIsActive,
  refreshLauncherAgentTaskAfterAction,
  launcherTaskConversationId,
  launcherTaskTitle,
} from '../features/yachiyo-chat/launcherTasks';
import type { AgentTaskSnapshot, ApprovalCardSnapshot } from '../features/yachiyo-chat/types';
import {
  runtimeToolRecoveryActionPrompt,
  runtimeToolRecoveryActionTaskMetadata,
  type RuntimeToolRecoveryAction,
} from '../features/runtime-shared/toolRecoveryActions';
import { studioRunClearParams, studioRunRouteParams } from '../features/runtime-shared/studioLinks';
import { AssistantProfileSeedContext, type AssistantProfileSeed } from '../lib/assistantProfileSeed';
import { apiDelete, apiGet, apiPost, checkAppUpdate, openDesktopMode, openExternalUrl, openPath, quitApp } from '../lib/bridge';
import { type AppView, currentParam, navigateTo } from '../lib/view';
import type { LauncherPayload } from './launcherTypes';

const Live2DPreviewStage = lazy(() =>
  import('./Live2DPreviewStage').then((module) => ({ default: module.Live2DPreviewStage })),
);

type NativeRuntimeStatus = {
  status?: string;
  version?: string;
  platform?: string;
  command_exists?: boolean;
  ready?: boolean;
  readiness_level?: string;
  limited_tools?: string[];
  doctor_issues_count?: number;
};

type DashboardData = {
  app?: { uptime_seconds?: number; version?: string; running?: boolean };
  bridge?: { state?: string; status?: string; running?: string; url?: string; config_dirty?: boolean };
  activities?: ActivityEvent[];
  chat?: {
    status_label?: string;
    is_processing?: boolean;
    recent_sessions?: Array<{
      session_id?: string;
      title?: string;
      message_count?: number;
      is_current?: boolean;
      latest_role?: string;
      latest_status?: string;
      updated_at?: string;
    }>;
  };
  assistant?: {
    agent_name?: string;
    agent_nickname?: string;
    agent_avatar_url?: string;
  };
  native_agent?: NativeRuntimeStatus;
  integrations?: {
    astrbot?: StatusRecord;
    hapi?: StatusRecord;
  };
  modes?: { current?: string; items?: Array<{ id: string; name?: string; label?: string; description?: string }> };
  tasks?: { pending?: number; running?: number; completed?: number };
  workspace?: { path?: string; initialized?: boolean; created_at?: string; dirs?: Record<string, string> };
};

type ActivityEvent = {
  event_id?: string;
  trace_event_ids?: string[];
  session_id?: string;
  task_id?: string;
  tool_name?: string;
  phase?: string;
  title?: string;
  detail?: string;
  status?: string;
  raw_status?: string;
  duration_seconds?: number | null;
  created_at?: string;
  metadata?: Record<string, unknown>;
};
type LauncherModeStartTaskOptions = {
  metadata?: Record<string, unknown>;
  title?: string | null;
};
type LauncherModeStartTask = (
  prompt: string,
  options?: LauncherModeStartTaskOptions,
) => Promise<AgentTaskSnapshot | null>;

type ActivityPayload = {
  ok?: boolean;
  error?: string;
  events?: ActivityEvent[];
  tools?: string[];
  phases?: string[];
  statuses?: string[];
  total?: number;
};

type ActivityDetailPayload = {
  ok?: boolean;
  error?: string;
  event?: ActivityEvent | null;
  trace?: ActivityEvent[];
  scope?: string;
  total?: number;
};

type StatusRecord = {
  status?: string;
  label?: string;
  description?: string;
  blockers?: string[];
};

type NativeProviderOption = {
  id: string;
  label?: string;
  base_url?: string;
  default_model?: string;
  default_vision_model?: string;
  models?: string[];
  vision_models?: string[];
  api_key_name?: string;
  api_key_configured?: boolean;
  auth_type?: string;
  source?: string;
};

type NativeVisualConfig = {
  ok?: boolean;
  error?: string;
  command_exists?: boolean;
  config_path?: string;
  env_path?: string;
  model?: { provider?: string; default?: string; base_url?: string };
  provider_options?: NativeProviderOption[];
  api_key?: { name?: string; configured?: boolean; display?: string };
  connection_validation?: {
    verified?: boolean;
    success?: boolean;
    provider?: string;
    model?: string;
    base_url?: string;
    message?: string;
    error?: string;
    reason?: string;
    tested_at?: string;
    verified_at?: string;
  };
  vision?: {
    configured?: boolean;
    provider?: string;
    model?: string;
    base_url?: string;
    api_key_configured?: boolean;
  };
  image_input?: {
    can_attach_images?: boolean;
    mode?: string;
    route?: string;
    label?: string;
    reason?: string;
  };
};

type NativeConfigForm = {
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

type NativeConnectionTestResult = {
  ok?: boolean;
  success?: boolean;
  error?: string;
  message?: string;
  elapsed_seconds?: number;
  output_preview?: string;
  stderr_preview?: string;
};

type SettingsData = {
  app?: { version?: string; log_level?: string; start_minimized?: boolean; tray_enabled?: boolean };
  assistant?: { persona_prompt?: string; user_address?: string };
  backup?: { auto_cleanup_enabled?: boolean; retention_count?: number };
  display?: { current_mode?: string; available_modes?: Array<{ id: string; name?: string; label?: string }> };
  native_agent?: DashboardData['native_agent'];
  mode_settings?: Record<string, { id?: string; title?: string; summary?: string; config?: Record<string, unknown> }>;
  workspace?: { path?: string; initialized?: boolean; created_at?: string; dirs?: Record<string, string> };
};

type BackupStatus = {
  ok?: boolean;
  error?: string;
  count?: number;
  total_size_display?: string;
  latest?: { display_path?: string; path?: string; created_at?: string; size_display?: string } | null;
};

type TtsVoiceResource = {
  default_assets_root_display?: string;
  voice_package_url?: string;
  help_text?: string;
  service_help_text?: string;
  default_service_workdir_display?: string;
};

type ResourceFile = {
  icon: string;
  name: string;
  meta: string;
  badge: string;
  tone: 'success' | 'warning' | 'info';
  categories: string[];
  actionLabel?: string;
  onAction?: () => void;
};

const launcherPayloadCache: Partial<Record<'bubble' | 'live2d', LauncherPayload>> = {};
const LAUNCHER_PAGE_ACTIVE_POLL_INTERVAL_MS = 1200;
const LAUNCHER_PAGE_IDLE_POLL_INTERVAL_MS = 5000;

const NAV_GROUPS: Array<{
  label: string;
  items: Array<{ view: AppView; label: string; icon: UiIconName; badge?: string; mode?: string }>;
}> = [
    {
      label: '启动',
      items: [
        { view: 'main', label: '主控台', icon: 'dashboard' },
        { view: 'provider', label: '模型配置', icon: 'provider' },
      ],
    },
    {
      label: '日常桌面',
      items: [
        { view: 'chat', label: '对话', icon: 'chat' },
        { view: 'tasks', label: '任务', icon: 'activity' },
        { view: 'agents', label: 'Agent Studio', icon: 'model' },
        { view: 'memories', label: '记忆', icon: 'sparkle' },
        { view: 'skills', label: 'Skills', icon: 'resources' },
        { view: 'bubble', label: '气泡模式', icon: 'bubble' },
        { view: 'live2d', label: 'Live2D 模式', icon: 'live2d' },
        { view: 'proactive-tts', label: '主动关怀', icon: 'voice' },
      ],
    },
    {
      label: '资源',
      items: [
        { view: 'resources', label: '资源管理', icon: 'resources' },
        { view: 'workspace', label: '工作区', icon: 'workspace' },
      ],
    },
    {
      label: '维护',
      items: [
        { view: 'tools', label: '能力中心', icon: 'resources' },
        { view: 'diagnostics', label: '诊断详情', icon: 'diagnostics' },
        { view: 'settings', label: '设置', icon: 'settings' },
      ],
    },
  ];

type ToolStatusTone = 'ready' | 'pending' | 'error';

type SidebarTooltip = {
  text: string;
  top: number;
  left: number;
};

type ToolCard = {
  view: AppView;
  icon: UiIconName;
  title: string;
  detail: string;
  status: string;
  statusTone: ToolStatusTone;
};

const TOOL_CARD_DEFS: Array<Omit<ToolCard, 'status' | 'statusTone'> & { status?: string; statusTone?: ToolStatusTone }> = [
  { view: 'chat' as AppView, icon: 'chat', title: '对话', detail: '与八千代对话，支持文本和图片输入。' },
  { view: 'bubble' as AppView, icon: 'bubble', title: '气泡模式', detail: '桌面悬浮气泡，随时对话，支持拖拽和边缘吸附。', status: '就绪', statusTone: 'ready' },
  { view: 'live2d' as AppView, icon: 'live2d', title: 'Live2D 模式', detail: '虚拟形象互动，口型同步，表情动作。' },
  { view: 'proactive-tts' as AppView, icon: 'voice', title: '主动关怀', detail: '桌面观察、提醒触发和语音播报设置。', status: '就绪', statusTone: 'ready' },
];

const TWEAK_ACCENTS = [
  { value: 'pink', label: '八千代粉' },
  { value: 'gold', label: '月光金' },
  { value: 'cyan', label: '星蓝' },
  { value: 'teal', label: '青瓷' },
  { value: 'violet', label: '紫藤' },
];

const PARTICLES = Array.from({ length: 80 }, (_, index) => {
  const colors = ['gold', 'cyan', 'pink', 'silver'];
  const modes = ['', 'flicker', 'orbit'];
  return {
    id: index,
    className: `hy-moon-particle ${modes[index % modes.length]}`,
    style: {
      '--particle-x': `${(index * 29) % 100}%`,
      '--particle-size': `${1.1 + (index % 7) * 0.5}px`,
      '--particle-delay': `${(index % 12) * -0.95}s`,
      '--particle-duration': `${7 + (index % 10)}s`,
      '--particle-drift': `${index % 2 ? '-' : ''}${36 + (index % 6) * 20}px`,
      '--particle-opacity': `${0.12 + (index % 5) * 0.055}`,
      '--particle-color': `var(--hy-particle-${colors[index % colors.length]})`,
    } as CSSProperties,
  };
});
const ACTIVITY_LOG_CHANGED_EVENT = 'oha-activity-log-changed';
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'oha.shell.sidebarCollapsed';
const ASSISTANT_PROFILE_UPDATED_EVENT = 'oha-assistant-profile-updated';

let bridgeBootReady = false;
let bootDashboardCache: DashboardData | null = null;
let bootLauncherCache: LauncherPayload | null = null;
let bootDashboardReady = false;

const DASHBOARD_ACTIVITY_POLL_INTERVAL_MS = 1500;

const PageLoadingContext = createContext<((loading: boolean) => void) | null>(null);

export function usePageLoading(loading: boolean) {
  const setPageLoading = useContext(PageLoadingContext);
  const loadingRef = useRef(loading);
  useEffect(() => {
    loadingRef.current = loading;
    setPageLoading?.(loading);
  }, [loading, setPageLoading]);
  useEffect(() => {
    return () => { setPageLoading?.(false); };
  }, [setPageLoading]);
}

export function signalDashboardReady() {
  bootDashboardReady = true;
}

function storedSidebarCollapsed() {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === '1';
}

export function OpenDesignShell({ activeView, children }: { activeView: AppView; children: ReactNode }) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [pageLoadingCount, setPageLoadingCount] = useState(0);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [accent, setAccent] = useState('pink');
  const [particleDensity, setParticleDensity] = useState(35);
  const [moonlightIntensity, setMoonlightIntensity] = useState(100);
  const [animationSpeed, setAnimationSpeed] = useState(100);
  const [fontSize, setFontSize] = useState(13);
  const [particlesEnabled, setParticlesEnabled] = useState(true);
  const [glowEnabled, setGlowEnabled] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => storedSidebarCollapsed());
  const [sidebarSwitching, setSidebarSwitching] = useState(false);
  const [sidebarTooltip, setSidebarTooltip] = useState<SidebarTooltip | null>(null);
  const [toasts, setToasts] = useState<Array<{ id: number; message: string; type: 'info' | 'success' | 'warning' | 'error' }>>([]);
  const [bootPhase, setBootPhase] = useState<'loading' | 'ready'>(() => (bridgeBootReady ? 'ready' : 'loading'));
  const [bootSlow, setBootSlow] = useState(false);
  const [routeSettling, setRouteSettling] = useState(true);
  const settingsMode = activeView === 'settings' ? currentParam('mode') : '';
  const activeLabel = routeTitle(activeView, settingsMode);
  const agentName = dashboard?.assistant?.agent_name?.trim() || '月見八千代';
  const agentNickname = dashboard?.assistant?.agent_nickname?.trim() || agentName;
  const agentAvatarUrl = dashboard?.assistant?.agent_avatar_url || logoUrl;
  const assistantProfileSeed = useMemo<AssistantProfileSeed | null>(() => (
    dashboard?.assistant ? {
      agent_name: dashboard.assistant.agent_name,
      agent_nickname: dashboard.assistant.agent_nickname,
      agent_avatar_url: dashboard.assistant.agent_avatar_url,
    } : null
  ), [dashboard?.assistant?.agent_avatar_url, dashboard?.assistant?.agent_name, dashboard?.assistant?.agent_nickname]);
  const loadingHidden = bootPhase !== 'loading';
  const accentLabel = TWEAK_ACCENTS.find((item) => item.value === accent)?.label || '八千代粉';
  const [shimmerActive, setShimmerActive] = useState(false);
  const shimmerActiveRef = useRef(false);
  const shimmerKey = useRef(0);
  const sidebarSwitchTimerRef = useRef<number | null>(null);

  const handlePageLoading = useCallback((loading: boolean) => {
    setPageLoadingCount((prev) => {
      const next = loading ? prev + 1 : Math.max(0, prev - 1);
      if (loading && !shimmerActiveRef.current) {
        shimmerKey.current += 1;
        shimmerActiveRef.current = true;
        setShimmerActive(true);
      }
      if (next === 0 && shimmerActiveRef.current) {
        shimmerActiveRef.current = false;
        setShimmerActive(false);
      }
      return next;
    });
  }, []);
  const shellClasses = [
    'hy-shell',
    `hy-accent-${accent}`,
    particlesEnabled ? '' : 'hy-particles-off',
    glowEnabled ? 'hy-glow-on' : '',
    sidebarCollapsed ? 'hy-sidebar-collapsed' : '',
    sidebarSwitching ? 'hy-sidebar-switching' : '',
  ].filter(Boolean).join(' ');
  const moonlightFactor = moonlightIntensity / 100;
  const normalizedMoonlight = Math.max(moonlightFactor, 0);
  const shellStyle = {
    '--hy-moonlight-opacity': String(Math.min(normalizedMoonlight, 1)),
    '--hy-kv-moon-opacity': String(Math.min(normalizedMoonlight, 1)),
    '--hy-kv-moon-brightness': String(0.72 + normalizedMoonlight * 0.34),
    '--hy-anim-factor': String(100 / Math.max(animationSpeed, 1)),
    '--hy-font-size-base': `${fontSize}px`,
  } as CSSProperties;

  useEffect(() => {
    setRouteSettling(true);
    const timer = window.setTimeout(() => setRouteSettling(false), 560);
    return () => window.clearTimeout(timer);
  }, [activeView, settingsMode]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, sidebarCollapsed ? '1' : '0');
    setSidebarTooltip(null);
  }, [sidebarCollapsed]);

  useEffect(() => {
    return () => {
      if (sidebarSwitchTimerRef.current !== null) window.clearTimeout(sidebarSwitchTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (bridgeBootReady) return undefined;
    let disposed = false;
    let retryTimer = 0;
    const showSlowTimer = window.setTimeout(() => {
      if (!disposed && !bridgeBootReady) setBootSlow(true);
    }, 7_500);

    async function probeBridge() {
      try {
        const [data, launcher] = await Promise.all([
          apiGet<DashboardData>('/ui/dashboard'),
          apiGet<LauncherPayload>('/ui/launcher?mode=live2d').catch(() => null),
        ]);
        if (disposed) return;
        bootDashboardCache = data;
        bootLauncherCache = launcher;
        bridgeBootReady = true;
        setDashboard(data);
        setBootSlow(false);
        setBootPhase('ready');
      } catch {
        if (disposed) return;
        retryTimer = window.setTimeout(() => void probeBridge(), 650);
      }
    }

    void probeBridge();

    return () => {
      disposed = true;
      window.clearTimeout(showSlowTimer);
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, []);

  useEffect(() => {
    if (!bridgeBootReady) return undefined;
    let disposed = false;
    apiGet<DashboardData>('/ui/dashboard')
      .then((data) => {
        if (!disposed) setDashboard(data);
      })
      .catch(() => {
        if (!disposed) setDashboard(null);
      });
    return () => {
      disposed = true;
    };
  }, [activeView]);

  useEffect(() => {
    let disposed = false;
    const refreshDashboard = () => {
      apiGet<DashboardData>('/ui/dashboard')
        .then((data) => {
          if (!disposed) setDashboard(data);
        })
        .catch(() => {
          if (!disposed) setDashboard(null);
        });
    };
    window.addEventListener(ASSISTANT_PROFILE_UPDATED_EVENT, refreshDashboard);
    return () => {
      disposed = true;
      window.removeEventListener(ASSISTANT_PROFILE_UPDATED_EVENT, refreshDashboard);
    };
  }, []);

  function showToast(message: string, type: 'info' | 'success' | 'warning' | 'error' = 'info') {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, message, type }].slice(-4));
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 2700);
  }

  function toggleSidebar() {
    if (sidebarSwitchTimerRef.current !== null) window.clearTimeout(sidebarSwitchTimerRef.current);
    setSidebarTooltip(null);
    setSidebarSwitching(true);
    setSidebarCollapsed((value) => !value);
    sidebarSwitchTimerRef.current = window.setTimeout(() => {
      setSidebarSwitching(false);
      sidebarSwitchTimerRef.current = null;
    }, 420);
  }

  function showSidebarTooltip(text: string, target: HTMLElement) {
    if (!sidebarCollapsed) return;
    const rect = target.getBoundingClientRect();
    setSidebarTooltip({
      text,
      top: Math.round(rect.top + rect.height / 2),
      left: Math.round(rect.right + 12),
    });
  }

  function sidebarTooltipProps(text: string) {
    return {
      'data-tooltip': text,
      onBlur: () => setSidebarTooltip(null),
      onFocus: (event: ReactFocusEvent<HTMLElement>) => showSidebarTooltip(text, event.currentTarget),
      onPointerEnter: (event: ReactPointerEvent<HTMLElement>) => showSidebarTooltip(text, event.currentTarget),
      onPointerLeave: () => setSidebarTooltip(null),
    };
  }

  async function checkForAppUpdate() {
    showToast('正在检查应用更新...', 'info');
    try {
      const result = await checkAppUpdate();
      if (result.update_available) {
        showToast(result.reason || '发现可用更新', 'success');
        navigateTo('app-update');
        return;
      }
      showToast(result.error || result.reason || '当前已是最新版本', result.ok === false ? 'warning' : 'info');
    } catch (err) {
      showToast(err instanceof Error ? err.message : '检查更新失败', 'error');
    }
  }

  return (
    <div className={shellClasses} style={shellStyle}>
      <div className="hy-toast-container" aria-live="polite">
        {toasts.map((toast) => (
          <div className={`hy-toast hy-toast-${toast.type}`} key={toast.id}>{toast.message}</div>
        ))}
      </div>
      {sidebarTooltip ? (
        <div
          className="hy-sidebar-tooltip"
          role="tooltip"
          style={{ left: `${sidebarTooltip.left}px`, top: `${sidebarTooltip.top}px` }}
        >
          {sidebarTooltip.text}
        </div>
      ) : null}
      <div className="hy-moonlight-bg" aria-hidden>
        {PARTICLES.slice(0, particleDensity).map((particle) => (
          <span className={particle.className} key={particle.id} style={particle.style} />
        ))}
      </div>
      <div className="hy-shimmer-sweep" key={shimmerKey.current} style={shimmerActive ? undefined : { display: 'none' }} />
      <BootLoadingOverlay hidden={loadingHidden} slow={bootSlow} />

      <header className="hy-titlebar">
        <div className="hy-traffic" aria-hidden>
          <span className="close" />
          <span className="minimize" />
          <span className="maximize" />
        </div>
        <div className="hy-titlebar-center">
          <span className="hy-titlebar-mark" aria-hidden="true">
            <img src={logoUrl} alt="" className="hy-titlebar-logo" />
          </span>
          <span>{activeLabel}</span>
        </div>
        <div className="hy-titlebar-actions">
          <button type="button" className={tweaksOpen ? 'hy-icon-btn active' : 'hy-icon-btn'} onClick={() => setTweaksOpen((value) => !value)} title="视觉调试"><UiIcon name="settings" /></button>
          <button type="button" className="hy-icon-btn" onClick={() => navigateTo('diagnostics')} title="诊断"><UiIcon name="diagnostics" /></button>
          <button type="button" className="hy-icon-btn" onClick={quitApp} title="退出"><UiIcon name="close" /></button>
        </div>
      </header>

      <aside className="hy-sidebar">
        <div className="hy-sidebar-header">
          <div className="hy-sidebar-header-row">
            <button type="button" className="hy-brand" onClick={() => navigateTo('main')} aria-label="返回主控台" title="返回主控台" {...sidebarTooltipProps('返回主控台')}>
              <span className="hy-brand-mark" aria-hidden="true">
                <img src={logoUrl} alt="" className="hy-brand-logo" />
              </span>
              <span>Oha Yachiyo</span>
            </button>
            <button
              type="button"
              className="hy-sidebar-toggle"
              aria-label={sidebarCollapsed ? '展开菜单栏' : '收起菜单栏'}
              aria-pressed={sidebarCollapsed}
              title={sidebarCollapsed ? '展开菜单栏' : '收起菜单栏'}
              onClick={toggleSidebar}
              {...sidebarTooltipProps(sidebarCollapsed ? '展开菜单栏' : '收起菜单栏')}
            >
              <UiIcon name="sidebar" />
            </button>
          </div>
        </div>

        <section className="hy-character" {...sidebarTooltipProps(`${agentName} · ${dashboard?.chat?.is_processing ? '处理中' : '待机中'}`)}>
          <div className="hy-avatar-ring">
            <img src={agentAvatarUrl} alt={agentName} />
          </div>
          <div>
            <strong>{agentName}</strong>
            <span><i />{dashboard?.chat?.is_processing ? `${agentNickname}处理中` : `${agentNickname}待机中`}</span>
          </div>
        </section>

        <nav className="hy-nav" aria-label="主要导航">
          {NAV_GROUPS.map((group) => (
            <div className="hy-nav-group" key={group.label}>
              <div className="hy-nav-label">{group.label}</div>
              {group.items.map((item) => {
                const active = isNavActive(activeView, settingsMode, item.view);
                return (
                  <button
                    type="button"
                    className={active ? 'hy-nav-item active' : 'hy-nav-item'}
                    aria-current={active ? 'page' : undefined}
                    key={`${group.label}-${item.view}`}
                    onClick={() => navigateTo(item.view)}
                    title={item.label}
                    {...sidebarTooltipProps(item.label)}
                  >
                    <span className="hy-nav-icon"><UiIcon name={item.icon} /></span>
                    <span>{item.label}</span>
                    {navBadge(item.view, dashboard) ? <em>{navBadge(item.view, dashboard)}</em> : null}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <footer className="hy-sidebar-footer">
          <button type="button" onClick={() => void checkForAppUpdate()} title="检查更新" aria-label="检查更新" {...sidebarTooltipProps('检查更新')}>
            <UiIcon name="retry" />
            <span>检查更新</span>
          </button>
          <button type="button" onClick={() => void openExternalUrl('https://www.oha-yachiyo.dev/guide/')} title="帮助" aria-label="帮助" {...sidebarTooltipProps('帮助')}>
            <UiIcon name="help" />
            <span>帮助</span>
          </button>
        </footer>
      </aside>

      {tweaksOpen ? (
        <aside className="hy-tweaks" aria-label="视觉调试">
          <header>
            <strong>快速调整</strong>
            <button type="button" onClick={() => setTweaksOpen(false)}>×</button>
          </header>
          <div className="hy-tweak-row">
            <div className="hy-tweak-label">主题色调 <span>{accentLabel}</span></div>
          </div>
          <div className="hy-swatch-row">
            {TWEAK_ACCENTS.map(({ value, label }) => (
              <button
                type="button"
                className={`hy-swatch ${value} ${accent === value ? 'active' : ''}`}
                key={value}
                onClick={() => setAccent(value)}
                title={label}
              />
            ))}
          </div>
          <div className="hy-tweak-divider" />
          <label>
            <span>粒子密度 <em>{particleDensity}</em></span>
            <input type="range" min="0" max="80" value={particleDensity} onChange={(event) => setParticleDensity(Number(event.target.value))} />
          </label>
          <label>
            <span>月光强度 <em>{moonlightIntensity}%</em></span>
            <input type="range" min="0" max="200" value={moonlightIntensity} onChange={(event) => setMoonlightIntensity(Number(event.target.value))} />
          </label>
          <label>
            <span>动画速度 <em>{(animationSpeed / 100).toFixed(1)}×</em></span>
            <input type="range" min="20" max="300" value={animationSpeed} onChange={(event) => setAnimationSpeed(Number(event.target.value))} />
          </label>
          <div className="hy-tweak-divider" />
          <label>
            <span>字体大小 <em>{fontSize}px</em></span>
            <input type="range" min="11" max="17" value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} />
          </label>
          <div className="hy-tweak-toggle-row">
            <span>粒子动画</span>
            <button type="button" className={particlesEnabled ? 'hy-tweak-toggle on' : 'hy-tweak-toggle'} onClick={() => setParticlesEnabled((value) => !value)} aria-pressed={particlesEnabled} />
          </div>
          <div className="hy-tweak-toggle-row">
            <span>呼吸光效</span>
            <button type="button" className={glowEnabled ? 'hy-tweak-toggle on' : 'hy-tweak-toggle'} onClick={() => setGlowEnabled((value) => !value)} aria-pressed={glowEnabled} />
          </div>
        </aside>
      ) : null}

      <main className={[
        'hy-content',
        pageLoadingCount > 0 ? 'is-loading-page' : '',
        routeSettling ? 'is-route-settling' : '',
      ].filter(Boolean).join(' ')}>
        <AssistantProfileSeedContext.Provider value={assistantProfileSeed}>
          <PageLoadingContext.Provider value={handlePageLoading}>
            {children}
          </PageLoadingContext.Provider>
        </AssistantProfileSeedContext.Provider>
      </main>
    </div>
  );
}

function BootLoadingOverlay({ hidden, slow }: { hidden: boolean; slow: boolean }) {
  return (
    <div className={hidden ? 'hy-loading-overlay hidden' : 'hy-loading-overlay'} aria-hidden={hidden}>
      <img src={logoUrl} alt="" className="hy-loading-logo" />
      <div className="hy-loading-copy">
        <div className="hy-loading-text">OHA YACHIYO</div>
        <div className="hy-loading-subtext">
          {slow ? 'Bridge 启动时间较长，仍在等待本机服务。' : '正在唤醒 Native Bridge'}
        </div>
      </div>
      <div className="hy-loading-bar">
        <span />
      </div>
    </div>
  );
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(bootDashboardCache);
  const [recentActivityEvents, setRecentActivityEvents] = useState<ActivityEvent[] | null>(bootDashboardCache?.activities || null);
  const [live2dLauncher, setLive2dLauncher] = useState<LauncherPayload | null>(bootLauncherCache);
  const [error, setError] = useState('');
  const [initialLoading, setInitialLoading] = useState(!bootDashboardCache);
  const dataRef = useRef<DashboardData | null>(bootDashboardCache);
  usePageLoading(initialLoading);

  useEffect(() => {
    let disposed = false;
    let retryTimer = 0;

    function scheduleBridgeRetry() {
      if (retryTimer) return;
      retryTimer = window.setTimeout(() => {
        retryTimer = 0;
        void load();
      }, 650);
    }

    async function load() {
      try {
        const payload = await apiGet<DashboardData>('/ui/dashboard');
        const launcherPayload = await apiGet<LauncherPayload>('/ui/launcher?mode=live2d').catch(() => null);
        if (!disposed) {
          if (retryTimer) {
            window.clearTimeout(retryTimer);
            retryTimer = 0;
          }
          dataRef.current = payload;
          setData(payload);
          setRecentActivityEvents(payload.activities || []);
          setLive2dLauncher(launcherPayload);
          setError('');
          setInitialLoading(false);
          signalDashboardReady();
        }
      } catch (err) {
        if (!disposed) {
          const message = err instanceof Error ? err.message : '无法读取主控台状态';
          if (isBridgeUnavailableMessage(message)) {
            if (!dataRef.current) {
              setError('');
              setInitialLoading(true);
              scheduleBridgeRetry();
            }
            return;
          }
          setError(message);
          setInitialLoading(false);
          signalDashboardReady();
        }
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 8000);
    return () => {
      disposed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    async function loadActivities() {
      try {
        const payload = await apiGet<ActivityPayload>('/ui/activity?limit=8');
        if (!disposed && payload.ok !== false) {
          setRecentActivityEvents(payload.events || []);
        }
      } catch {
        // Keep the last successful dashboard/activity payload visible.
      }
    }
    void loadActivities();
    const refreshActivities = () => void loadActivities();
    const timer = window.setInterval(() => void loadActivities(), DASHBOARD_ACTIVITY_POLL_INTERVAL_MS);
    window.addEventListener(ACTIVITY_LOG_CHANGED_EVENT, refreshActivities);
    return () => {
      disposed = true;
      window.removeEventListener(ACTIVITY_LOG_CHANGED_EVENT, refreshActivities);
      window.clearInterval(timer);
    };
  }, []);

  const bridge = bridgeState(data);
  const nativeAgent = dashboardNativeAgent(data);
  const modelReady = Boolean(nativeAgent?.ready || nativeAgent?.command_exists);
  const workspaceReady = Boolean(data?.workspace?.initialized);
  const dataLoaded = data !== null;
  const activityData = data ? { ...data, activities: recentActivityEvents ?? data.activities } : data;
  const activities = recentActivities(activityData);
  const modelLabel = nativeAgent?.version || (modelReady ? 'Native · 文本+视觉' : 'Native 待检测');
  const toolCards = dashboardToolCards(data, live2dLauncher);

  return (
    <section className="hy-route-page hy-dashboard-page">
      {error && !dataLoaded ? <div className="notice danger">{error}</div> : null}
      <section className="hy-kv-hero">
        <div className="hy-kv-copy">
          <span className="hy-eyebrow">月夜見 · 管理员在线</span>
          <h1>月見八千代<br />正在守望你的世界</h1>
          <p>8000 岁的 AI 歌姬，虚拟空间「月夜見」的管理员。她用歌声跨越了八千年的孤独，只为与你相遇在这个月夜。</p>
          <div className="hy-kv-meta">
            <span><i />Bridge {bridge} · {data?.bridge?.url || '127.0.0.1 本机桥接'}</span>
            <span><i />✨ {modelLabel}</span>
          </div>
        </div>
      </section>

      <header className="hy-page-header hy-stagger">
        <div>
          <h2>主控台</h2>
          <p>当前桌面 Agent 的运行状态、常用入口和最近活动。</p>
        </div>
      </header>

      <section className="hy-status-grid hy-stagger">
        <StatusCard tone="success" label="Bridge 状态" value={bridge} detail={data?.bridge?.url || '127.0.0.1 本机桥接'} icon="activity" />
        <StatusCard tone={!dataLoaded ? 'info' : modelReady ? 'info' : 'warning'} label="模型连接" value={!dataLoaded ? '加载中' : modelReady ? '已连接' : '待配置'} detail={!dataLoaded ? '正在读取状态' : nativeReadinessLabel(nativeAgent?.readiness_level)} icon="model" />
        <StatusCard tone={!dataLoaded ? 'info' : workspaceReady ? 'success' : 'warning'} label="工作区" value={!dataLoaded ? '加载中' : workspaceReady ? '已初始化' : '待初始化'} detail={data?.workspace?.path || '~/Oha-Yachiyo/workspace'} icon="folder" />
      </section>

      <section className="hy-section hy-stagger">
        <div className="hy-section-header">
          <h2>桌面工具</h2>
          <button type="button" onClick={() => navigateTo('tools-all')}>查看全部 →</button>
        </div>
        <div className="hy-tools-grid">
          {toolCards.map((tool) => (
            <button
              type="button"
              className="hy-tool-card"
              key={tool.title}
              onClick={() => navigateTo(tool.view)}
            >
              <span><UiIcon name={tool.icon} /></span>
              <strong>{tool.title}</strong>
              <small>{tool.detail}</small>
              <em className={`hy-tool-status hy-tool-status-${tool.statusTone}`}><i />{tool.status}</em>
            </button>
          ))}
        </div>
      </section>

      <section className="hy-section hy-stagger">
        <div className="hy-section-header">
          <h2>最近活动</h2>
          <button type="button" onClick={() => navigateTo('activity-all')}>查看全部 →</button>
        </div>
        <div className="hy-activity-list">
          {activities.length ? activities.map((activity) => (
            <ActivityRow key={`${activity.title}-${activity.time}`} {...activity} />
          )) : (
            <div className="inline-empty">暂无活动记录</div>
          )}
        </div>
      </section>
    </section>
  );
}

function dashboardToolCards(data: DashboardData | null, live2dLauncher: LauncherPayload | null): ToolCard[] {
  return TOOL_CARD_DEFS.map((tool) => {
    if (tool.view === 'chat') {
      return { ...tool, ...chatToolStatus(data) };
    }
    if (tool.view === 'live2d') {
      return { ...tool, ...live2dToolStatus(live2dLauncher) };
    }
    if (tool.view === 'bubble') {
      return {
        ...tool,
        status: data?.modes?.current === 'bubble' ? '使用中' : (tool.status || '就绪'),
        statusTone: tool.statusTone || 'ready',
      };
    }
    return { ...tool, status: tool.status || '就绪', statusTone: tool.statusTone || 'ready' };
  });
}

function dashboardNativeAgent(data: DashboardData | null | undefined): NativeRuntimeStatus | undefined {
  return data?.native_agent;
}

function chatToolStatus(data: DashboardData | null): Pick<ToolCard, 'status' | 'statusTone'> {
  if (data?.chat?.is_processing) return { status: '处理中', statusTone: 'pending' };
  if (data?.chat?.recent_sessions?.length) return { status: '就绪', statusTone: 'ready' };
  return { status: '待开始', statusTone: 'pending' };
}

function live2dToolStatus(payload: LauncherPayload | null): Pick<ToolCard, 'status' | 'statusTone'> {
  const resource = payload?.launcher?.resource;
  if (!payload) return { status: '检测中', statusTone: 'pending' };
  if (isLive2DResourceReady(resource)) {
    return { status: resource?.status_label || '已导入', statusTone: 'ready' };
  }
  return { status: resource?.status_label || '待导入', statusTone: 'pending' };
}

function isLive2DResourceReady(resource?: NonNullable<LauncherPayload['launcher']>['resource']): boolean {
  const state = String(resource?.state || '').toLowerCase();
  return Boolean(resource?.available || ['ready', 'loaded', 'valid', 'path_valid', 'ok'].includes(state));
}

function live2dRenderPresetLabel(value?: string): string {
  if (value === 'battery') return '省电';
  if (value === 'quality') return '高清';
  if (value === 'custom') return '自定义';
  return '均衡';
}

export function ProviderPage() {
  const [config, setConfig] = useState<NativeVisualConfig | null>(null);
  const [form, setForm] = useState<NativeConfigForm>(() => emptyNativeForm());
  const [status, setStatus] = useState('正在读取模型配置...');
  const [busy, setBusy] = useState('');
  const [testResult, setTestResult] = useState<NativeConnectionTestResult | null>(null);
  const [imageTestResult, setImageTestResult] = useState<NativeConnectionTestResult | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  usePageLoading(initialLoading || !!busy);

  useEffect(() => {
    let disposed = false;
    async function load() {
      try {
        const payload = await apiGet<NativeVisualConfig>('/ui/native-agent/config');
        if (!disposed) {
          setConfig(payload);
          setForm(formFromNativeConfig(payload));
          setStatus(payload.ok === false ? payload.error || '读取配置失败' : '');
          setInitialLoading(false);
        }
      } catch (err) {
        if (!disposed) {
          setStatus(err instanceof Error ? err.message : '读取配置失败');
          setInitialLoading(false);
        }
      }
    }
    void load();
    return () => {
      disposed = true;
    };
  }, []);

  const providerOptions = config?.provider_options || [];
  const provider = providerOptionById(config, form.provider);
  const visionProvider = form.vision_provider ? providerOptionById(config, form.vision_provider) : undefined;
  const effectiveVisionProvider = visionProvider || provider;
  const modelOptions = textModelOptions(provider, form.model);
  const visionModelOptions = visionModelSelectOptions(effectiveVisionProvider, form.vision_model);
  const apiKeyLabel = provider?.api_key_name || config?.api_key?.name || 'API Key';
  const apiKeyConfigured = provider?.api_key_configured ?? config?.api_key?.configured;
  const visionApiKeyLabel = visionProvider?.api_key_name || provider?.api_key_name || config?.api_key?.name || 'Vision API Key';
  const visionApiKeyConfigured = visionProvider?.api_key_configured ?? config?.vision?.api_key_configured;

  function updateTextProvider(providerId: string) {
    setTestResult(null);
    setImageTestResult(null);
    setForm((current) => {
      const next = applyTextProviderPreset(config, current, providerId);
      return current.vision_provider ? next : { ...next, vision_model: '', vision_base_url: '', vision_api_key: '' };
    });
  }

  function updateVisionProvider(providerId: string) {
    setImageTestResult(null);
    setForm((current) => applyVisionProviderPreset(config, current, providerId));
  }

  async function persistNativeConfig() {
    if (!form.provider.trim() || !form.model.trim()) {
      throw new Error('Provider 和模型名称不能为空');
    }
    const result = await apiPost<{ ok?: boolean; error?: string; configuration?: NativeVisualConfig }>('/ui/native-agent/config', form);
    if (result.ok === false) throw new Error(result.error || '保存配置失败');
    if (result.configuration) {
      setConfig(result.configuration);
      setForm(formFromNativeConfig(result.configuration));
    }
  }

  async function saveConfig(event: FormEvent) {
    event.preventDefault();
    setBusy('save');
    setTestResult(null);
    setImageTestResult(null);
    setStatus('正在保存配置...');
    try {
      await persistNativeConfig();
      setStatus('模型配置已保存');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '保存配置失败');
    } finally {
      setBusy('');
    }
  }

  async function runTextConnectionTest() {
    if (busy) return;
    setBusy('text-test');
    setTestResult(null);
    setStatus('正在保存配置并测试文本模型...');
    try {
      await persistNativeConfig();
      const test = await apiPost<NativeConnectionTestResult>('/ui/native-agent/connection-test');
      setTestResult(test);
      setStatus(test.success ? test.message || '模型连接测试通过' : test.error || '模型连接测试失败');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '文本模型连接测试失败');
    } finally {
      setBusy('');
    }
  }

  async function runImageConnectionTest() {
    if (busy) return;
    setBusy('image-test');
    setImageTestResult(null);
    setStatus('正在保存配置并测试图片链路...');
    try {
      await persistNativeConfig();
      const test = await apiPost<NativeConnectionTestResult>('/ui/native-agent/image-connection-test');
      setImageTestResult(test);
      setStatus(test.success ? test.message || '图片链路测试通过' : test.error || '图片链路测试失败');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '图片链路测试失败');
    } finally {
      setBusy('');
    }
  }

  return (
    <section className="hy-route-page hy-provider-page">
      <header className="hy-page-header hy-stagger">
        <div>
          <span className="hy-eyebrow">Provider</span>
          <h2>模型配置</h2>
          <p>配置 AI 模型提供商、API Key 和高级参数。</p>
        </div>
        <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('main')}>返回主控台</button>
      </header>

      {status ? <div className={/失败|错误|无法|不能为空/.test(status) ? 'notice danger' : 'notice'}>{status}</div> : null}

      <section className="hy-provider-settings">
        <form className="hy-provider-form-sections hy-stagger" onSubmit={saveConfig}>
          <section className="hy-settings-section">
            <div className="hy-settings-card">
              <div className="hy-settings-item">
                <span>
                  <strong>保存全部配置</strong>
                  <small>写入文本与 Vision provider、模型、Base URL 和密钥变更</small>
                </span>
                <button type="submit" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)}>{busy === 'save' ? '保存中...' : '保存配置'}</button>
              </div>
            </div>
          </section>
          <section className="hy-settings-section">
            <div className="hy-section-title-row">
              <h3>文本提供商</h3>
              <span>Text Model</span>
            </div>
            <div className="hy-settings-card">
              <label className="hy-settings-item">
                <span>
                  <strong>模型提供商</strong>
                  <small>{provider?.base_url || '切换后自动应用厂商默认模型和 Base URL'}</small>
                </span>
                <select className="hy-select" value={form.provider} disabled={Boolean(busy)} onChange={(event) => updateTextProvider(event.target.value)}>
                  {providerOptions.length ? providerOptions.map((option) => (
                    <option key={option.id} value={option.id}>{providerLabel(option)}</option>
                  )) : <option value={form.provider}>{form.provider || '读取中'}</option>}
                </select>
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>模型</strong>
                  <small>{provider?.default_model ? `默认 ${provider.default_model}` : '当前使用的文本模型'}</small>
                </span>
                {modelOptions.length ? (
                  <select className="hy-select" value={form.model} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))}>
                    {modelOptions.map((model) => <option value={model} key={model}>{model}</option>)}
                  </select>
                ) : (
                  <input className="hy-input" value={form.model} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))} />
                )}
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>Base URL</strong>
                  <small>{config?.config_path || 'Native 配置路径待读取'}</small>
                </span>
                <input className="hy-input" value={form.base_url} placeholder={provider?.base_url || 'https://api.openai.com/v1'} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, base_url: event.target.value }))} />
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>{apiKeyLabel}</strong>
                  <small>{apiKeyConfigured ? '已配置，留空则不修改' : '密钥仅存储在本地'}</small>
                </span>
                <input className="hy-input" type="password" value={form.api_key} placeholder={apiKeyConfigured ? 'sk-••••••••••••••••' : `输入 ${apiKeyLabel}`} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, api_key: event.target.value }))} />
              </label>
              <div className="hy-settings-item">
                <span>
                  <strong>文本连接测试</strong>
                  <small>保存当前文本配置后调用 `/ui/native-agent/connection-test`</small>
                </span>
                <button type="button" className="hy-btn hy-btn-ghost" disabled={Boolean(busy)} onClick={() => void runTextConnectionTest()}>{busy === 'text-test' ? '测试中...' : '测试文本'}</button>
              </div>
            </div>
            {testResult ? <ConnectionResult result={testResult} /> : null}
          </section>

          <section className="hy-settings-section">
            <div className="hy-section-title-row">
              <h3>Vision 提供商</h3>
              <span>Image Understanding</span>
            </div>
            <div className="hy-settings-card">
              <label className="hy-settings-item">
                <span>
                  <strong>图片输入模式</strong>
                  <small>{config?.image_input?.reason || config?.image_input?.label || '选择图片如何进入 Native'}</small>
                </span>
                <select className="hy-select" value={form.image_input_mode} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, image_input_mode: event.target.value }))}>
                  <option value="auto">自动选择</option>
                  <option value="text">Vision 模型识图</option>
                  <option value="native">原生图片输入（兼容）</option>
                </select>
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>Vision Provider</strong>
                  <small>{visionProvider?.base_url || (form.vision_provider ? '切换后自动应用视觉模型预设' : '跟随文本提供商的预设')}</small>
                </span>
                <select className="hy-select" value={form.vision_provider} disabled={Boolean(busy)} onChange={(event) => updateVisionProvider(event.target.value)}>
                  <option value="">跟随文本模型</option>
                  {providerOptions.map((option) => (
                    <option key={option.id} value={option.id}>{providerLabel(option)}</option>
                  ))}
                </select>
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>Vision 模型</strong>
                  <small>{effectiveVisionProvider?.default_vision_model || effectiveVisionProvider?.default_model || '支持图片理解的模型名称'}</small>
                </span>
                {visionModelOptions.length ? (
                  <select className="hy-select" value={form.vision_model} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, vision_model: event.target.value }))}>
                    <option value="">跟随 Provider 默认</option>
                    {visionModelOptions.map((model) => <option value={model} key={model}>{model}</option>)}
                  </select>
                ) : (
                  <input className="hy-input" value={form.vision_model} placeholder="例如 gpt-4o-mini" disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, vision_model: event.target.value }))} />
                )}
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>Vision Base URL</strong>
                  <small>{form.vision_provider ? '切换 Vision Provider 时自动填入厂商默认地址' : '留空则跟随文本模型 Base URL'}</small>
                </span>
                <input className="hy-input" value={form.vision_base_url} placeholder={effectiveVisionProvider?.base_url || form.base_url || 'https://api.openai.com/v1'} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, vision_base_url: event.target.value }))} />
              </label>
              <label className="hy-settings-item">
                <span>
                  <strong>{visionApiKeyLabel}</strong>
                  <small>{visionApiKeyConfigured ? '已配置，留空则不修改' : '可与文本密钥分开配置'}</small>
                </span>
                <input className="hy-input" type="password" value={form.vision_api_key} placeholder={visionApiKeyConfigured ? 'sk-••••••••••••••••' : `输入 ${visionApiKeyLabel}`} disabled={Boolean(busy)} onChange={(event) => setForm((current) => ({ ...current, vision_api_key: event.target.value }))} />
              </label>
              <div className="hy-settings-item">
                <span>
                  <strong>Vision 连接测试</strong>
                  <small>保存当前视觉配置后调用 `/ui/native-agent/image-connection-test`</small>
                </span>
                <button type="button" className="hy-btn hy-btn-primary" disabled={Boolean(busy)} onClick={() => void runImageConnectionTest()}>{busy === 'image-test' ? '测试中...' : '测试图片'}</button>
              </div>
            </div>
            {imageTestResult ? <ConnectionResult result={imageTestResult} /> : null}
          </section>
        </form>

        <section className="hy-settings-section hy-stagger">
          <h3>TTS 语音合成</h3>
          <div className="hy-settings-card">
            <div className="hy-settings-item">
              <span><strong>语音链路</strong><small>主动关怀语音、GPT-SoVITS 服务和音色包在专门页面配置</small></span>
              <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('proactive-tts')}>打开语音设置</button>
            </div>
          </div>
        </section>
      </section>
    </section>
  );
}

function useLauncherModePayload(mode: 'bubble' | 'live2d', active = true) {
  const [data, setData] = useState<LauncherPayload | null>(() => launcherPayloadCache[mode] || null);
  const [publicAgentTask, setPublicAgentTask] = useState<AgentTaskSnapshot | null>(null);
  const [loading, setLoading] = useState(() => !launcherPayloadCache[mode]);
  const canUpdateRef = useRef(active);

  useEffect(() => {
    canUpdateRef.current = active;
    return () => {
      canUpdateRef.current = false;
    };
  }, [active]);

  const refresh = useCallback(async () => {
    try {
      const payload = await apiGet<LauncherPayload>(`/ui/launcher?mode=${mode}`);
      launcherPayloadCache[mode] = payload;
      if (!canUpdateRef.current) return;
      setData(payload);
      try {
        const tasks = await listYachiyoTasks();
        if (!canUpdateRef.current) return;
        setPublicAgentTask(launcherAgentTaskFromPublicTasks(tasks, payload.chat?.agent_task || null));
      } catch {
        if (!canUpdateRef.current) return;
        setPublicAgentTask((current) => payload.chat?.agent_task || current || null);
      }
    } catch {
      if (!canUpdateRef.current) return;
      if (!launcherPayloadCache[mode]) setData(null);
      if (!launcherPayloadCache[mode]) setPublicAgentTask(null);
    } finally {
      if (!canUpdateRef.current) return;
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    if (!active) return undefined;
    void refresh();
    return undefined;
  }, [active, refresh]);

  useEffect(() => {
    if (!active) return undefined;
    const processing = Boolean(
      data?.chat?.is_processing
      || launcherAgentTaskIsActive(publicAgentTask || data?.chat?.agent_task)
      || launcherPayloadHasActiveTask(data),
    );
    const timer = window.setInterval(
      () => void refresh(),
      processing ? LAUNCHER_PAGE_ACTIVE_POLL_INTERVAL_MS : LAUNCHER_PAGE_IDLE_POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [active, data?.chat?.agent_task, data?.chat?.is_processing, publicAgentTask, refresh]);

  const resolveAgentTaskApproval = useCallback(async (
    task: AgentTaskSnapshot,
    approval: ApprovalCardSnapshot,
    approved: boolean,
  ) => {
    const taskId = String(task.task_id || '').trim();
    if (!taskId) return null;
    const approvalId = String(approval.approval_id || '').trim() || undefined;
    const nextTask = approved
      ? await approveYachiyoTask(taskId, approvalId)
      : await rejectYachiyoTask(taskId, approvalId, 'Rejected from launcher mode page');
    return refreshLauncherAgentTaskAfterAction({
      loadTask: getYachiyoTask,
      refresh,
      rememberTask: setPublicAgentTask,
      shouldContinue: () => canUpdateRef.current,
      task: nextTask,
    });
  }, [refresh]);

  const approveAgentTaskApproval = useCallback((
    task: AgentTaskSnapshot,
    approval: ApprovalCardSnapshot,
  ) => resolveAgentTaskApproval(task, approval, true), [resolveAgentTaskApproval]);

  const rejectAgentTaskApproval = useCallback((
    task: AgentTaskSnapshot,
    approval: ApprovalCardSnapshot,
  ) => resolveAgentTaskApproval(task, approval, false), [resolveAgentTaskApproval]);

  const cancelAgentTask = useCallback(async (task: AgentTaskSnapshot) => {
    const taskId = String(task.task_id || '').trim();
    if (!taskId) return null;
    const nextTask = await cancelYachiyoTask(taskId);
    setPublicAgentTask(nextTask);
    await refresh();
    return nextTask;
  }, [refresh]);

  const startAgentTask = useCallback(async (
    prompt: string,
    options: LauncherModeStartTaskOptions = {},
  ) => {
    const text = prompt.trim();
    if (!text) return null;
    const task = await startYachiyoTask({
      prompt: text,
      agent_id: LAUNCHER_MAIN_AGENT_ID,
      conversation_id: launcherTaskConversationId(mode, data),
      title: options.title || launcherTaskTitle(text),
      metadata: {
        source: 'launcher',
        launcher_mode: mode,
        runnable_kind: 'main',
        launcher_surface: 'mode_page',
        planner_entrypoint: `${mode}_mode_page`,
        ...(options.metadata || {}),
      },
    });
    setPublicAgentTask(task);
    await refresh();
    return task;
  }, [data, mode, refresh]);

  return {
    agentTask: publicAgentTask || data?.chat?.agent_task || null,
    approveAgentTaskApproval,
    cancelAgentTask,
    data,
    loading,
    refresh,
    rejectAgentTaskApproval,
    startAgentTask,
  };
}

function launcherPayloadHasActiveTask(data: LauncherPayload | null) {
  return ['queued', 'running', 'waiting_approval'].includes(String(data?.chat?.agent_task?.status || ''));
}

function runLauncherModeRecoveryAction(
  startAgentTask: LauncherModeStartTask,
  task: AgentTaskSnapshot,
  action: RuntimeToolRecoveryAction,
  surface: string,
) {
  const prompt = runtimeToolRecoveryActionPrompt(action);
  return startAgentTask(prompt, {
    title: action.label || prompt,
    metadata: runtimeToolRecoveryActionTaskMetadata(action, {
      launcher_recovery: true,
      launcher_recovery_surface: surface,
      source_task_id: task.task_id || '',
      source_task_title: task.title || '',
    }),
  });
}

export function BubbleModePage() {
  const {
    agentTask,
    approveAgentTaskApproval,
    cancelAgentTask,
    data,
    loading,
    rejectAgentTaskApproval,
    startAgentTask,
  } = useLauncherModePayload('bubble');
  usePageLoading(loading && !data);

  return (
    <section className="hy-route-page hy-stage-page">
      <header className="hy-page-header">
        <div>
          <span className="hy-eyebrow">Bubble</span>
          <h2>气泡模式</h2>
          <p>轻量桌面入口，同步聊天处理、未读、最新回复和主动关怀状态。</p>
        </div>
        <button type="button" className="hy-btn hy-btn-primary" onClick={() => void openDesktopMode('bubble')}>打开桌面气泡</button>
      </header>
      <div className="hy-bubble-layout">
        <div className="hy-bubble-demo hy-stagger corner-frame">
          <div className="corner-frame-inner" />
          <header className="hy-bubble-demo-header">
            <div className="hy-bubble-demo-avatar">
              <img src={data?.launcher?.avatar_url || logoUrl} alt="" />
            </div>
            <div>
              <strong>月見八千代</strong>
              <span><i />{data?.chat?.status_label || '本机 Bridge 监听中'}</span>
            </div>
          </header>
          <div className="hy-bubble-demo-body">
            <p className="agent">今晚的月光很安静，要一起整理工作区吗？</p>
            <p className="user">帮我看一下最近的状态。</p>
            <p className="agent">{data?.chat?.latest_reply || data?.launcher?.latest_reply || 'Bridge、模型和工作区状态都在主控台同步。'}</p>
          </div>
          <button type="button" className="hy-floating-bubble" onClick={() => void openDesktopMode('bubble')} aria-label="打开桌面气泡">
            <img src={data?.launcher?.avatar_url || logoUrl} alt="" />
          </button>
        </div>
        <div className="hy-mode-info hy-stagger">
          <h3>气泡模式</h3>
          <p>桌面悬浮气泡，随时与八千代对话。支持拖拽、双击展开聊天、边缘吸附等功能。</p>
          <LauncherAgentTaskLight
            mode="bubble"
            onApproveApproval={approveAgentTaskApproval}
            onCancelTask={cancelAgentTask}
            onRejectApproval={rejectAgentTaskApproval}
            onRunRecoveryAction={(task, action) => void runLauncherModeRecoveryAction(startAgentTask, task, action, 'bubble-mode-page')}
            task={agentTask}
            testIdPrefix="bubble-mode"
            variant="panel"
          />
          <LauncherModeTaskComposer mode="bubble" startAgentTask={startAgentTask} />
          <div className="hy-feature-pills">
            {[
              ['💬', '随时对话'],
              ['🎯', '边缘吸附'],
              ['✨', '透明度调节'],
              ['🔔', '消息提醒'],
            ].map(([icon, item]) => (
              <span key={item}><i>{icon}</i>{item}</span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function Live2DModePage({ active = true }: { active?: boolean } = {}) {
  const {
    agentTask,
    approveAgentTaskApproval,
    cancelAgentTask,
    data,
    loading,
    rejectAgentTaskApproval,
    startAgentTask,
  } = useLauncherModePayload('live2d', active);
  usePageLoading(active && loading && !data);

  const resource = data?.launcher?.resource;
  const renderer = data?.launcher?.renderer;
  const resourceReady = isLive2DResourceReady(resource);
  const previewReady = Boolean(resourceReady && renderer?.enabled && renderer?.model_url);
  const expressionCount = renderer?.expressions?.length || 0;
  const motionGroups = renderer?.motion_groups || {};
  const motionGroupCount = Object.keys(motionGroups).length;
  const motionCount = Object.values(motionGroups).reduce((total, items) => total + (Array.isArray(items) ? items.length : 0), 0);
  const renderLabel = live2dRenderPresetLabel(data?.launcher?.render_quality_preset);

  return (
    <section className="hy-route-page hy-stage-page">
      <header className="hy-page-header">
        <div>
          <span className="hy-eyebrow">Live2D</span>
          <h2>Live2D 模式</h2>
          <p>模型舞台、口型同步、表情动作、语音合成和月光舞台状态。</p>
        </div>
        <div className="hy-action-row">
          <button type="button" className="hy-btn hy-btn-ghost" onClick={() => navigateTo('settings', { mode: 'live2d' })}>资源设置</button>
          <button type="button" className="hy-btn hy-btn-primary" onClick={() => void openDesktopMode('live2d')}>打开 Live2D</button>
        </div>
      </header>
      <div className="hy-live2d-layout">
        <div className={`hy-live2d-stage hy-stagger corner-frame ${previewReady ? 'has-preview' : ''}`}>
          <div className="corner-frame-inner" />
          {previewReady ? (
            <Suspense fallback={<div className="live2d-stage live2d-preview-stage"><div className="live2d-loading">Live2D 预览加载中...</div></div>}>
              <Live2DPreviewStage data={data} active={active} />
            </Suspense>
          ) : (
            <div className="hy-live2d-placeholder">
              <div className="hy-live2d-placeholder-icon"><img src={logoUrl} alt="" /></div>
              <strong>{resource?.display_name || 'Live2D 模型待导入'}</strong>
              <span>{resource?.status_label || (resource?.available ? '资源已就绪' : '支持 .model3.json 格式')}</span>
              <button type="button" className="hy-btn hy-btn-primary" onClick={() => navigateTo('settings', { mode: 'live2d' })}>导入 Live2D 模型</button>
            </div>
          )}
        </div>
        <div className="hy-mode-info hy-stagger">
          <h3>Live2D 模式</h3>
          <p>虚拟形象互动，让八千代在你的桌面上活起来。支持口型同步、表情动作、语音合成等功能。</p>
          <LauncherAgentTaskLight
            mode="live2d"
            onApproveApproval={approveAgentTaskApproval}
            onCancelTask={cancelAgentTask}
            onRejectApproval={rejectAgentTaskApproval}
            onRunRecoveryAction={(task, action) => void runLauncherModeRecoveryAction(startAgentTask, task, action, 'live2d-mode-page')}
            task={agentTask}
            testIdPrefix="live2d-mode"
            variant="panel"
          />
          <LauncherModeTaskComposer mode="live2d" startAgentTask={startAgentTask} />
          <div className="hy-feature-pills">
            {[
              ['🎤', data?.tts?.enabled ? '口型同步' : '口型同步'],
              ['😊', expressionCount ? `${expressionCount} 个表情` : '表情动作'],
              ['🎞️', motionCount ? `${motionGroupCount} 组动作 · ${motionCount} 条` : '动作摘要'],
              ['🎵', data?.tts?.provider ? '语音合成' : '语音合成'],
              ['⚙️', `${renderLabel} · ${data?.launcher?.render_fps || 24} FPS`],
              ['🌙', data?.proactive?.enabled ? '月光舞台' : '月光舞台'],
            ].map(([icon, item]) => (
              <span key={item}><i>{icon}</i>{item}</span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function LauncherModeTaskComposer({
  mode,
  startAgentTask,
}: {
  mode: 'bubble' | 'live2d';
  startAgentTask: LauncherModeStartTask;
}) {
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const composingRef = useRef(false);

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (composingRef.current) return;
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setPrompt('');
    try {
      await startAgentTask(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="launcher-mode-task-composer" data-testid={`${mode}-mode-task-composer`} onSubmit={submitTask}>
      <input
        aria-label="委派任务给八千代"
        className="hy-input"
        data-testid={`${mode}-mode-task-input`}
        disabled={busy}
        onChange={(event) => setPrompt(event.target.value)}
        onCompositionEnd={() => {
          composingRef.current = false;
        }}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        placeholder="委派一个任务给八千代"
        value={prompt}
      />
      <button
        className="hy-btn hy-btn-primary"
        data-testid={`${mode}-mode-task-submit`}
        disabled={!prompt.trim() || busy}
        type="submit"
      >
        {busy ? '委派中' : '委派任务'}
      </button>
    </form>
  );
}

export function ResourcesPage() {
  const [live2d, setLive2d] = useState<LauncherPayload | null>(null);
  const [ttsResource, setTtsResource] = useState<TtsVoiceResource | null>(null);
  const [activeTab, setActiveTab] = useState('全部');

  useEffect(() => {
    let disposed = false;
    void Promise.allSettled([
      apiGet<LauncherPayload>('/ui/launcher?mode=live2d'),
      apiGet<TtsVoiceResource>('/ui/tts/voice-resource'),
    ]).then(([live2dResult, ttsResult]) => {
      if (disposed) return;
      setLive2d(live2dResult.status === 'fulfilled' ? live2dResult.value : null);
      setTtsResource(ttsResult.status === 'fulfilled' ? ttsResult.value : null);
    });
    return () => {
      disposed = true;
    };
  }, []);

  const resource = live2d?.launcher?.resource;
  const files: ResourceFile[] = [
    {
      icon: '🎭',
      name: resource?.display_name || '八千代 - 默认模型',
      meta: `Live2D · ${resource?.default_assets_root_display || 'assets/live2d/'}`,
      badge: resource?.available ? '使用中' : '待导入',
      tone: resource?.available ? 'success' : 'warning',
      categories: ['模型', 'Live2D'],
      actionLabel: '导入',
      onAction: resource?.available ? undefined : () => navigateTo('settings', { mode: 'live2d' }),
    },
    {
      icon: '🎭',
      name: 'Live2D 默认资源目录',
      meta: `Live2D · ${resource?.status_label || '等待模型配置'}`,
      badge: resource?.available ? '已加载' : '缺失',
      tone: resource?.available ? 'info' : 'warning',
      categories: ['模型', 'Live2D'],
      actionLabel: '设置',
      onAction: () => navigateTo('settings', { mode: 'live2d' }),
    },
    {
      icon: '🎵',
      name: '八千代音色模型',
      meta: `GPT-SoVITS · ${ttsResource?.default_assets_root_display || 'voice assets'}`,
      badge: ttsResource ? '可导入' : '待检测',
      tone: ttsResource ? 'success' : 'info',
      categories: ['语音'],
      actionLabel: '配置',
      onAction: ttsResource ? undefined : () => navigateTo('proactive-tts'),
    },
    {
      icon: '🎵',
      name: '语音服务工作区',
      meta: `GPT-SoVITS · ${ttsResource?.default_service_workdir_display || 'service workspace'}`,
      badge: ttsResource?.service_help_text ? '提示' : '就绪',
      tone: ttsResource?.service_help_text ? 'warning' : 'info',
      categories: ['语音'],
      actionLabel: '设置',
      onAction: () => navigateTo('proactive-tts'),
    },
    {
      icon: '🖼',
      name: '月夜背景',
      meta: '壁纸 · docs/open-design/bg-reference.png',
      badge: '参考',
      tone: 'info',
      categories: ['壁纸'],
    },
    {
      icon: '🖼',
      name: 'Oha Yachiyo Logo',
      meta: '壁纸 · docs/open-design/logo.png',
      badge: '已加载',
      tone: 'info',
      categories: ['壁纸'],
    },
  ];
  const tabs = ['全部', '模型', '语音', '壁纸', 'Live2D'];
  const visibleFiles = activeTab === '全部'
    ? files
    : files.filter((file) => file.categories.includes(activeTab));
  const live2dCount = resource?.available ? '1' : '0';

  return (
    <section className="hy-route-page resources-layout">
      <header className="resources-header hy-stagger">
        <h2 className="resources-title">资源管理</h2>
        <p className="resources-subtitle">管理 Live2D 模型、语音、壁纸等资源文件</p>
      </header>

      <div className="resources-tabs hy-stagger" role="tablist" aria-label="资源分类">
        {tabs.map((tab) => (
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            className={`resources-tab ${activeTab === tab ? 'active' : ''}`}
            key={tab}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <section className="resources-stats hy-stagger">
        <article className="resource-stat">
          <div className="resource-stat-value">{files.length}</div>
          <div className="resource-stat-label">总文件数</div>
        </article>
        <article className="resource-stat">
          <div className="resource-stat-value">本地</div>
          <div className="resource-stat-label">总大小</div>
        </article>
        <article className="resource-stat">
          <div className="resource-stat-value">{live2dCount}</div>
          <div className="resource-stat-label">Live2D 模型</div>
        </article>
      </section>

      <div className="resources-list hy-stagger">
        {visibleFiles.map((file) => <ResourceRow key={file.name} file={file} />)}
        {visibleFiles.length === 0 ? <div className="empty-state inline-empty">暂无资源</div> : null}
      </div>
    </section>
  );
}

export function WorkspacePage() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [backup, setBackup] = useState<BackupStatus | null>(null);
  const [status, setStatus] = useState('');
  const [backupBusy, setBackupBusy] = useState(false);

  useEffect(() => {
    let disposed = false;
    async function loadWorkspace() {
      const [settingsResult, backupResult] = await Promise.allSettled([
        apiGet<SettingsData>('/ui/settings'),
        apiGet<BackupStatus>('/ui/backup/status'),
      ]);
      if (disposed) return;
      setSettings(settingsResult.status === 'fulfilled' ? settingsResult.value : null);
      setBackup(backupResult.status === 'fulfilled' ? backupResult.value : null);
    }
    void loadWorkspace();
    return () => {
      disposed = true;
    };
  }, []);

  const workspacePath = settings?.workspace?.path || '~/.oha-yachiyo';
  const dirs = settings?.workspace?.dirs || {};
  const resourcesPath = dirs.assets || `${workspacePath}/assets`;
  const latestBackup = backup?.latest?.display_path || backup?.latest?.path || '暂无备份';
  const workspaceFiles = [
    { icon: '📁', name: workspacePath, meta: '工作区根目录', nested: false },
    { icon: '💬', name: dirs.conversations || dirs.sessions || 'conversations/', meta: '对话记录 · 本地会话数据', nested: true },
    { icon: '🎭', name: 'live2d/', meta: `Live2D 模型 · ${dirs.assets || 'assets/'}`, nested: true },
    { icon: '🎵', name: 'audio/', meta: `音频文件 · ${dirs.attachments || 'attachments/'}`, nested: true },
    { icon: '⚙', name: 'config.json', meta: settings?.workspace?.initialized ? '配置文件 · 已初始化' : '配置文件 · 等待初始化', nested: true },
    { icon: '📦', name: 'backups/', meta: `备份 · ${backup?.total_size_display || `${backup?.count || 0} 份`}`, nested: true },
  ];

  async function openWorkspace() {
    try {
      await openPath(workspacePath);
      setStatus(`已打开工作区：${workspacePath}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开工作区失败');
    }
  }

  async function openResourcesDir() {
    try {
      await openPath(resourcesPath);
      setStatus(`已打开资源目录：${resourcesPath}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '打开资源目录失败');
    }
  }

  async function createBackup() {
    if (backupBusy) return;
    setBackupBusy(true);
    setStatus('正在生成工作区备份...');
    try {
      const result = await apiPost<{ ok?: boolean; error?: string; status?: BackupStatus }>('/ui/backup/create', { overwrite_latest: false });
      if (result.ok === false) throw new Error(result.error || '生成备份失败');
      const nextBackup = result.status || await apiGet<BackupStatus>('/ui/backup/status');
      setBackup(nextBackup);
      setStatus('工作区备份已生成');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : '生成备份失败');
    } finally {
      setBackupBusy(false);
    }
  }

  return (
    <section className="hy-route-page workspace-page settings-layout">
      <header className="settings-header hy-stagger">
        <div className="settings-title">工作区</div>
        <div className="settings-subtitle">管理对话记录、项目文件和工作区配置</div>
      </header>

      {status ? <div className={/失败|错误|无法/.test(status) ? 'notice danger' : 'notice'}>{status}</div> : null}

      <section className="settings-section hy-stagger">
        <div className="settings-section-title">对话与备份</div>
        <div className="settings-card">
          <WorkspaceSettingItem
            label="会话列表"
            description="进入真实聊天会话列表，不在这里伪造导入/导出能力"
            action={<button type="button" className="btn btn--ghost" onClick={() => navigateTo('chat')}>打开</button>}
          />
          <WorkspaceSettingItem
            label="立即备份"
            description={latestBackup}
            action={<button type="button" className="btn btn--primary" disabled={backupBusy} onClick={() => void createBackup()}>{backupBusy ? '备份中...' : '创建备份'}</button>}
          />
          <WorkspaceSettingItem
            label="系统备份管理"
            description="恢复、删除备份等高风险操作在系统设置页处理"
            action={<button type="button" className="btn btn--ghost" onClick={() => navigateTo('settings', { mode: 'system' })}>进入</button>}
          />
        </div>
      </section>

      <section className="settings-section hy-stagger">
        <div className="settings-section-title">工作区路径</div>
        <div className="settings-card">
          <WorkspaceSettingItem
            label="工作区目录"
            description={workspacePath}
            mono
            action={<button type="button" className="btn btn--ghost" onClick={() => void openWorkspace()}>打开</button>}
          />
          <WorkspaceSettingItem
            label="资源目录"
            description={resourcesPath}
            mono
            action={<button type="button" className="btn btn--ghost" onClick={() => void openResourcesDir()}>打开</button>}
          />
          <WorkspaceSettingItem
            label="备份工作区"
            description={latestBackup}
            action={<button type="button" className="btn btn--primary" disabled={backupBusy} onClick={() => void createBackup()}>{backupBusy ? '备份中...' : '立即备份'}</button>}
          />
        </div>
      </section>

      <section className="settings-section hy-stagger">
        <div className="settings-section-title">项目文件</div>
        <div className="workspace-files">
          {workspaceFiles.map((file) => (
            <WorkspaceFileRow key={`${file.name}-${file.meta}`} {...file} />
          ))}
        </div>
      </section>
    </section>
  );
}

export function ToolsAllPage() {
  const [live2dLauncher, setLive2dLauncher] = useState<LauncherPayload | null>(null);

  useEffect(() => {
    let disposed = false;
    apiGet<LauncherPayload>('/ui/launcher?mode=live2d')
      .then((payload) => {
        if (!disposed) setLive2dLauncher(payload);
      })
      .catch(() => {
        if (!disposed) setLive2dLauncher(null);
      });
    return () => {
      disposed = true;
    };
  }, []);

  const live2dStatus = live2dToolStatus(live2dLauncher);
  const allTools = [
    { view: 'bubble' as AppView, icon: 'bubble' as UiIconName, title: '气泡模式', detail: '桌面悬浮气泡，随时对话，支持拖拽和边缘吸附。', status: '就绪', statusTone: 'ready' },
    { view: 'live2d' as AppView, icon: 'live2d' as UiIconName, title: 'Live2D 模式', detail: '虚拟形象互动，口型同步，表情动作。', ...live2dStatus },
    { view: 'proactive-tts' as AppView, icon: 'voice' as UiIconName, title: '主动关怀', detail: '桌面观察、提醒触发和语音播报设置。', status: '就绪', statusTone: 'ready' },
    { view: 'resources' as AppView, icon: 'resources' as UiIconName, title: '资源管理', detail: '管理 Live2D 模型、语音、壁纸等资源文件。', status: '就绪', statusTone: 'ready' },
    { view: 'workspace' as AppView, icon: 'workspace' as UiIconName, title: '工作区', detail: '管理对话记录、项目文件和工作区配置。', status: '已初始化', statusTone: 'ready' },
    { view: 'diagnostics' as AppView, icon: 'diagnostics' as UiIconName, title: '诊断详情', detail: 'Doctor 输出、运行时日志和本地能力探测。', status: '就绪', statusTone: 'ready' },
    { view: 'provider' as AppView, icon: 'provider' as UiIconName, title: '模型配置', detail: '配置 AI 模型提供商和 API Key。', status: '就绪', statusTone: 'ready' },
    { view: 'chat' as AppView, icon: 'chat' as UiIconName, title: '对话', detail: '与八千代对话，支持文本和图片输入。', status: '就绪', statusTone: 'ready' },
  ];

  return (
    <section className="hy-route-page">
      <header className="hy-page-header">
        <button type="button" className="page-back-link" onClick={() => navigateTo('main')}>← 返回主控台</button>
        <div>
          <h2>桌面工具</h2>
          <p>所有可用的桌面工具和交互模式</p>
        </div>
      </header>
      <div className="hy-tools-grid tools-grid-full">
        {allTools.map((tool) => (
          <button type="button" className="hy-tool-card" key={tool.title} onClick={() => navigateTo(tool.view)}>
            <span><UiIcon name={tool.icon} /></span>
            <strong>{tool.title}</strong>
            <small>{tool.detail}</small>
            <em className={`hy-tool-status hy-tool-status-${tool.statusTone}`}><i />{tool.status}</em>
          </button>
        ))}
      </div>
    </section>
  );
}

export function ActivityAllPage() {
  const [activity, setActivity] = useState<ActivityPayload | null>(null);
  const [activityLoading, setActivityLoading] = useState(true);
  const [activityError, setActivityError] = useState('');
  const [activityQuery, setActivityQuery] = useState('');
  const [activityStatus, setActivityStatus] = useState('');
  const [activityPhase, setActivityPhase] = useState('');
  const [availableStatuses, setAvailableStatuses] = useState<string[]>([]);
  const [availablePhases, setAvailablePhases] = useState<string[]>([]);
  const [selectedActivityIds, setSelectedActivityIds] = useState<Set<string>>(() => new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const { confirmDialog, requestConfirm } = useConfirmDialog();

  async function reloadActivityList(shouldApply: () => boolean = () => true) {
    setActivityLoading(true);
    const query = new URLSearchParams();
    query.set('limit', '100');
    if (activityQuery.trim()) query.set('query', activityQuery.trim());
    if (activityStatus) query.set('status', activityStatus);
    if (activityPhase) query.set('phase', activityPhase);
    try {
      const payload = await apiGet<ActivityPayload>(`/ui/activity?${query.toString()}`);
      if (!shouldApply()) return;
      if (payload.ok === false) throw new Error(payload.error || '读取活动失败');
      setActivity(payload);
      setActivityError('');
      if (!activityQuery.trim() && !activityStatus && !activityPhase) {
        setAvailableStatuses(payload.statuses || []);
        setAvailablePhases(payload.phases || []);
      }
    } finally {
      if (shouldApply()) setActivityLoading(false);
    }
  }

  useEffect(() => {
    let disposed = false;
    reloadActivityList(() => !disposed)
      .catch((error) => {
        if (disposed) return;
        setActivity(null);
        setActivityError(error instanceof Error ? error.message : '读取活动失败');
      });
    return () => {
      disposed = true;
    };
  }, [activityQuery, activityStatus, activityPhase]);

  usePageLoading(activityLoading && !activity);

  const rows: ActivityRowData[] = [
    ...(activity?.events || []).map((event) => activityEventRow(event, true)),
  ];

  const selectableActivityIds = rows
    .map((row) => row.eventId || '')
    .filter(Boolean);
  const selectableActivityKey = selectableActivityIds.join('|');
  const selectedCount = selectedActivityIds.size;
  const allVisibleSelected = selectableActivityIds.length > 0
    && selectableActivityIds.every((eventId) => selectedActivityIds.has(eventId));
  const grouped = groupActivitiesByDay(rows);

  useEffect(() => {
    const validIds = new Set(selectableActivityIds);
    setSelectedActivityIds((current) => {
      const next = new Set([...current].filter((eventId) => validIds.has(eventId)));
      return next.size === current.size ? current : next;
    });
  }, [selectableActivityKey]);

  function toggleActivitySelection(eventId: string, selected: boolean) {
    setSelectedActivityIds((current) => {
      const next = new Set(current);
      if (selected) next.add(eventId);
      else next.delete(eventId);
      return next;
    });
  }

  function toggleSelectAllVisible() {
    setSelectedActivityIds((current) => {
      if (allVisibleSelected) return new Set();
      const next = new Set(current);
      selectableActivityIds.forEach((eventId) => next.add(eventId));
      return next;
    });
  }

  async function deleteSelectedActivities() {
    const ids = [...selectedActivityIds];
    if (!ids.length || bulkDeleting) return;
    setBulkDeleting(true);
    try {
      const result = await apiDelete<{ ok?: boolean; error?: string; deleted?: number }>('/ui/activity', {
        event_ids: ids,
      });
      if (result.ok === false) throw new Error(result.error || '删除活动日志失败');
      setSelectedActivityIds(new Set());
      window.dispatchEvent(new Event(ACTIVITY_LOG_CHANGED_EVENT));
      await reloadActivityList();
    } catch (deleteError) {
      setActivityError(deleteError instanceof Error ? deleteError.message : '删除活动日志失败');
    } finally {
      setBulkDeleting(false);
    }
  }

  function requestDeleteSelectedActivities() {
    const ids = [...selectedActivityIds];
    if (!ids.length || bulkDeleting) return;
    requestConfirm({
      title: `删除选中的 ${ids.length} 条活动日志？`,
      description: '这些活动日志会从本机记录中删除，此操作不可恢复。',
      confirmLabel: '删除日志',
      variant: 'danger',
      onConfirm: () => void deleteSelectedActivities(),
    });
  }

  return (
    <section className="hy-route-page" data-testid="activity-feed">
      <header className="hy-page-header">
        <button type="button" className="page-back-link" onClick={() => navigateTo('main')}>← 返回主控台</button>
        <div>
          <h2>活动日志</h2>
          <p>Agent、脚本、工具调用与系统活动的完整记录</p>
        </div>
      </header>
      <div className="activity-controls">
        <div className="activity-filter-bar">
          <input
            data-testid="activity-search-input"
            type="search"
            value={activityQuery}
            onChange={(event) => setActivityQuery(event.target.value)}
            placeholder="搜索日志、Session ID、任务 ID、工具或详情"
            aria-label="搜索活动"
          />
          <select data-testid="activity-status-filter" value={activityStatus} onChange={(event) => setActivityStatus(event.target.value)} aria-label="按状态筛选">
            <option value="">全部状态</option>
            {availableStatuses.map((status) => (
              <option value={status} key={status}>{activityStatusLabel(status)}</option>
            ))}
          </select>
          <select data-testid="activity-phase-filter" value={activityPhase} onChange={(event) => setActivityPhase(event.target.value)} aria-label="按类型筛选">
            <option value="">全部类型</option>
            {availablePhases.map((phase) => (
              <option value={phase} key={phase}>{activityPhaseLabel(phase)}</option>
            ))}
          </select>
        </div>
        <div className="activity-bulk-bar">
          <button
            type="button"
            className="hy-btn hy-btn-ghost"
            data-testid="activity-select-all"
            disabled={!selectableActivityIds.length}
            onClick={toggleSelectAllVisible}
          >
            {allVisibleSelected ? '取消全选' : '全选当前结果'}
          </button>
          <span>{selectedCount ? `已选择 ${selectedCount} 条` : `当前可选 ${selectableActivityIds.length} 条`}</span>
          <button
            type="button"
            className="hy-btn activity-danger-btn"
            data-testid="activity-delete-selected"
            disabled={!selectedCount || bulkDeleting}
            onClick={requestDeleteSelectedActivities}
          >
            {bulkDeleting ? '删除中...' : '删除选中日志'}
          </button>
        </div>
      </div>
      {activityError ? <div className="notice danger">{activityError}</div> : null}
      <div className="activity-list-full" data-testid="activity-list">
        {activityLoading ? (
          <ActivityListSkeleton />
        ) : grouped.map((group) => (
          <div key={group.label}>
            <div className="activity-day-label">{group.label}</div>
            {group.items.map((row, index) => (
              <ActivityRow
                key={row.eventId || `${row.title}-${index}`}
                {...row}
                selectable={Boolean(row.eventId)}
                selected={Boolean(row.eventId && selectedActivityIds.has(row.eventId))}
                onSelectionChange={toggleActivitySelection}
                highlightQuery={activityQuery}
              />
            ))}
          </div>
        ))}
        {!activityLoading && !grouped.length ? (
          <div className="inline-empty">暂无活动记录</div>
        ) : null}
      </div>
      {confirmDialog}
    </section>
  );
}

export function ActivityDetailPage() {
  const eventId = currentParam('event_id').trim();
  const [payload, setPayload] = useState<ActivityDetailPayload | null>(null);
  const [error, setError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const { confirmDialog, requestConfirm } = useConfirmDialog();
  const [expandedTraceIds, setExpandedTraceIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (!eventId) {
      setPayload(null);
      setError('缺少活动日志 ID');
      return undefined;
    }
    let disposed = false;
    apiGet<ActivityDetailPayload>(`/ui/activity/${encodeURIComponent(eventId)}?limit=200`)
      .then((result) => {
        if (disposed) return;
        if (result.ok === false) throw new Error(result.error || '读取活动详情失败');
        setPayload(result);
        setError('');
      })
      .catch((fetchError) => {
        if (disposed) return;
        setPayload(null);
        setError(fetchError instanceof Error ? fetchError.message : '读取活动详情失败');
      });
    return () => {
      disposed = true;
    };
  }, [eventId]);

  useEffect(() => {
    setExpandedTraceIds(new Set());
  }, [eventId]);

  const event = payload?.event || null;
  const trace = compactActivityTrace(activityTraceSource(payload?.trace || [], event));
  const metadataText = formatMetadata(event?.metadata);
  const activityRunId = metadataString(event?.metadata, 'run_id');
  const detailLoading = !error && !payload;
  usePageLoading(detailLoading);

  useEffect(() => {
    if (!payload || !eventId) return undefined;
    const timer = window.setTimeout(() => {
      document.getElementById(activityTraceDomId(eventId))?.scrollIntoView({
        block: 'center',
        behavior: 'smooth',
      });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [payload, eventId]);

  function returnFromActivityDetail() {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    navigateTo('activity-all');
  }

  async function deleteCurrentEvent() {
    if (!eventId || deleting) return;
    setDeleting(true);
    try {
      const result = await apiDelete<{ ok?: boolean; error?: string }>(`/ui/activity/${encodeURIComponent(eventId)}`);
      if (result.ok === false) throw new Error(result.error || '删除活动日志失败');
      window.dispatchEvent(new Event(ACTIVITY_LOG_CHANGED_EVENT));
      returnFromActivityDetail();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '删除活动日志失败');
    } finally {
      setDeleting(false);
    }
  }

  function requestDeleteCurrentEvent() {
    if (!eventId || deleting) return;
    requestConfirm({
      title: '删除这条活动日志？',
      description: '这条活动日志会从本机记录中删除，此操作不可恢复。',
      confirmLabel: '删除日志',
      variant: 'danger',
      onConfirm: () => void deleteCurrentEvent(),
    });
  }

  function toggleTraceExpanded(traceId: string) {
    setExpandedTraceIds((current) => {
      const next = new Set(current);
      if (next.has(traceId)) next.delete(traceId);
      else next.add(traceId);
      return next;
    });
  }

  return (
    <section
      className="hy-route-page activity-detail-page"
      data-activity-event-id={eventId}
      data-run-id={activityRunId}
      data-session-id={event?.session_id || ''}
      data-task-id={event?.task_id || ''}
      data-testid="activity-detail-page"
    >
      <header className="hy-page-header activity-detail-header">
        <div className="activity-detail-titlebar">
          <button type="button" className="page-back-link" onClick={returnFromActivityDetail}>← 返回上一页</button>
          {detailLoading ? (
            <div className="activity-detail-title-skeleton" aria-hidden="true">
              <span />
              <i />
            </div>
          ) : (
            <div>
              <h2>{event?.title || '活动详情'}</h2>
              <p>{event ? activityDetail(event) : '查看单条日志与同任务完整过程'}</p>
            </div>
          )}
        </div>
        {event ? (
          <button
            type="button"
            className="hy-btn hy-btn-ghost activity-delete-btn danger-action"
            data-testid="activity-detail-delete"
            disabled={deleting}
            onClick={requestDeleteCurrentEvent}
          >
            {deleting ? '删除中...' : '删除日志'}
          </button>
        ) : null}
      </header>

      {error ? <div className="notice danger">{error}</div> : null}
      {detailLoading ? <ActivityDetailSkeleton /> : null}

      {event ? (
        <>
          <section className="activity-detail-summary" data-testid="activity-detail-summary">
            <div>
              <span>状态</span>
              <strong>{activityStatusLabel(event.status) || '未标记'}</strong>
            </div>
            <div>
              <span>类型</span>
              <strong>{activityPhaseLabel(event.phase)}</strong>
            </div>
            <div>
              <span>工具</span>
              <strong>{event.tool_name || 'Native'}</strong>
            </div>
            <div>
              <span>时间</span>
              <strong>{formatFullDateTime(event.created_at)}</strong>
            </div>
            {activityRunId ? (
              <div>
                <span>Run</span>
                <button
                  type="button"
                  className="hy-btn hy-btn-ghost activity-run-link"
                  data-run-id={activityRunId}
                  data-run-status={event.status || ''}
                  data-testid="activity-detail-open-run"
                  onClick={() => navigateTo('agents', studioRunRouteParams(activityRunId) || {}, studioRunClearParams)}
                >
                  打开 Run
                </button>
              </div>
            ) : null}
          </section>

          <section className="activity-detail-body" data-testid="activity-detail-body">
            <h3>详细内容</h3>
            <dl>
              <div>
                <dt>事件 ID</dt>
                <dd>{event.event_id || eventId}</dd>
              </div>
              <div>
                <dt>任务 ID</dt>
                <dd>{event.task_id || '无'}</dd>
              </div>
              <div>
                <dt>会话 ID</dt>
                <dd>{event.session_id || '无'}</dd>
              </div>
              <div>
                <dt>摘要</dt>
                <dd>{event.detail || '无详细摘要'}</dd>
              </div>
            </dl>
            {metadataText ? (
              <pre className="activity-metadata">{metadataText}</pre>
            ) : null}
          </section>

          <section className="activity-detail-body" data-testid="activity-trace">
            <h3>完整过程</h3>
            <div className="activity-trace-list">
              {trace.length ? trace.map((item, index) => {
                const traceId = activityTraceKey(item, index);
                const itemMetadataText = formatMetadata(item.metadata);
                const canExpand = Boolean(item.detail || itemMetadataText);
                const expanded = expandedTraceIds.has(traceId);
                const focused = activityTraceContainsEvent(item, eventId);
                return (
                  <article
                    id={focused ? activityTraceDomId(eventId) : item.event_id ? activityTraceDomId(item.event_id) : undefined}
                    className={`activity-trace-row activity-item-${activityTone(item.status)}${expanded ? ' expanded' : ''}${focused ? ' focused' : ''}`}
                    data-activity-event-id={item.event_id || ''}
                    data-testid="activity-trace-row"
                    key={traceId}
                  >
                    <span className="activity-icon">{activityIcon(item)}</span>
                    <div className="activity-content">
                      <div className="activity-trace-heading">
                        <strong>{item.title || item.tool_name || 'Native 活动'}</strong>
                        {canExpand ? (
                          <button
                            type="button"
                            className="activity-trace-expand"
                            data-testid="activity-trace-expand"
                            title={expanded ? '收起全文' : '查看全文'}
                            aria-label={expanded ? '收起全文' : '查看全文'}
                            onClick={() => toggleTraceExpanded(traceId)}
                          >
                            <UiIcon name={expanded ? 'close' : 'plus'} />
                            <span>{expanded ? '收起' : '全文'}</span>
                          </button>
                        ) : null}
                      </div>
                      <small>{compactActivityDetail(item)}</small>
                      {expanded ? (
                        <div className="activity-trace-expanded">
                          {item.detail ? (
                            <div>
                              <span>完整摘要</span>
                              <p>{item.detail}</p>
                            </div>
                          ) : null}
                          {itemMetadataText ? (
                            <pre>{itemMetadataText}</pre>
                          ) : null}
                        </div>
                      ) : null}
                      <em>{activityPhaseLabel(item.phase)}</em>
                    </div>
                    <time className="activity-time">{formatFullDateTime(item.created_at)}</time>
                  </article>
                );
              }) : (
                <div className="inline-empty">暂无同任务过程</div>
              )}
            </div>
          </section>
        </>
      ) : null}
      {confirmDialog}
    </section>
  );
}

function ActivityListSkeleton() {
  return (
    <div className="activity-list-skeleton" aria-label="正在加载活动日志">
      <div className="activity-day-label skeleton-label" />
      {Array.from({ length: 6 }).map((_, index) => (
        <article className="activity-item activity-skeleton-row" key={index}>
          <span className="activity-skeleton-checkbox" />
          <span className="activity-icon activity-skeleton-block" />
          <div className="activity-content">
            <span className="activity-skeleton-line title" />
            <span className="activity-skeleton-line detail" />
            <span className="activity-skeleton-line tag" />
          </div>
          <span className="activity-skeleton-time" />
        </article>
      ))}
    </div>
  );
}

function ActivityDetailSkeleton() {
  return (
    <>
      <section className="activity-detail-summary activity-detail-summary-skeleton" aria-label="正在加载日志摘要">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index}>
            <span className="activity-skeleton-line label" />
            <strong className="activity-skeleton-line value" />
          </div>
        ))}
      </section>
      <section className="activity-detail-body activity-detail-body-skeleton" aria-label="正在加载日志详情">
        <span className="activity-skeleton-line heading" />
        <span className="activity-skeleton-line detail long" />
        <span className="activity-skeleton-line detail" />
        <span className="activity-skeleton-line detail short" />
      </section>
      <section className="activity-detail-body activity-detail-body-skeleton" aria-label="正在加载完整过程">
        <span className="activity-skeleton-line heading" />
        <div className="activity-trace-list">
          {Array.from({ length: 4 }).map((_, index) => (
            <article className="activity-trace-row activity-skeleton-row" key={index}>
              <span className="activity-icon activity-skeleton-block" />
              <div className="activity-content">
                <span className="activity-skeleton-line title" />
                <span className="activity-skeleton-line detail" />
              </div>
              <span className="activity-skeleton-time" />
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function StatusCard({ tone, label, value, detail, icon }: { tone: 'success' | 'warning' | 'info'; label: string; value: string; detail: string; icon: UiIconName }) {
  return (
    <article className={`hy-status-card hy-status-card-${tone} corner-frame`}>
      <div className="corner-frame-inner" />
      <header>
        <span>{label}</span>
        <i><UiIcon name={icon} /></i>
      </header>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function ActivityRow({
  icon,
  title,
  detail,
  time,
  tone = 'system',
  eventId,
  phase,
  selectable = false,
  selected = false,
  onSelectionChange,
  highlightQuery = '',
}: ActivityRowData & {
  selectable?: boolean;
  selected?: boolean;
  onSelectionChange?: (eventId: string, selected: boolean) => void;
  highlightQuery?: string;
}) {
  const className = `activity-item activity-item-${tone}${eventId ? ' activity-item-clickable' : ''}`;
  const content = (
    <>
      <span className="activity-icon">{icon}</span>
      <div className="activity-content">
        <strong><HighlightedInline text={title} query={highlightQuery} /></strong>
        <small><HighlightedInline text={detail} query={highlightQuery} /></small>
        {phase ? <em>{activityPhaseLabel(phase)}</em> : null}
      </div>
      <time className="activity-time">{time}</time>
    </>
  );
  if (eventId && selectable) {
    return (
      <article className={className} data-activity-event-id={eventId} data-testid="activity-row">
        <label className="activity-select">
          <input
            data-testid="activity-select-checkbox"
            type="checkbox"
            checked={selected}
            aria-label={`选择日志：${title}`}
            onChange={(event) => onSelectionChange?.(eventId, event.target.checked)}
          />
        </label>
        <button type="button" className="activity-row-main" data-testid="activity-row-open" onClick={() => navigateTo('activity-detail', { event_id: eventId })}>
          {content}
        </button>
      </article>
    );
  }
  if (eventId) {
    return (
      <button type="button" className={className} data-activity-event-id={eventId} data-testid="activity-row" onClick={() => navigateTo('activity-detail', { event_id: eventId })}>
        {content}
      </button>
    );
  }
  return (
    <article className={className}>
      {content}
    </article>
  );
}

function HighlightedInline({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const lowerText = text.toLowerCase();
  const lowerNeedle = needle.toLowerCase();
  const index = lowerText.indexOf(lowerNeedle);
  if (index < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + needle.length)}</mark>
      {text.slice(index + needle.length)}
    </>
  );
}

function FileRow({ icon, name, meta, badge, tone }: { icon: string; name: string; meta: string; badge: string; tone: string }) {
  return (
    <article className="hy-file-row">
      <span>{icon}</span>
      <div>
        <strong>{name}</strong>
        <small>{meta}</small>
      </div>
      <em className={`hy-badge hy-badge-${tone}`}>{badge}</em>
    </article>
  );
}

function ResourceRow({ file }: { file: ResourceFile }) {
  return (
    <article className="resource-item">
      <div className="resource-icon">{file.icon}</div>
      <div className="resource-info">
        <div className="resource-name">{file.name}</div>
        <div className="resource-meta">{file.meta}</div>
      </div>
      <div className="resource-status">
        {file.onAction ? (
          <button type="button" className="resource-action-btn" onClick={file.onAction}>
            {file.actionLabel || '打开'}
          </button>
        ) : (
          <span className={`resource-badge resource-badge--${file.tone}`}>{file.badge}</span>
        )}
      </div>
    </article>
  );
}

function WorkspaceSettingItem({ label, description, action, mono = false }: { label: string; description: string; action: ReactNode; mono?: boolean }) {
  return (
    <div className="settings-item">
      <div className="settings-item-info">
        <div className="settings-item-label">{label}</div>
        <div className={`settings-item-desc ${mono ? 'mono' : ''}`}>{description}</div>
      </div>
      <div className="settings-item-control">{action}</div>
    </div>
  );
}

function WorkspaceFileRow({ icon, name, meta, nested }: { icon: string; name: string; meta: string; nested?: boolean }) {
  return (
    <div className={`workspace-file ${nested ? 'nested' : ''}`}>
      <div className="file-icon">{icon}</div>
      <div className="file-info">
        <div className="file-name">{name}</div>
        <div className="file-meta">{meta}</div>
      </div>
    </div>
  );
}

function InfoPanel({ title, rows, action }: { title: string; rows: Array<[string, string]>; action?: { label: string; view: AppView } }) {
  return (
    <article className="hy-card hy-info-panel">
      <header>
        <h3>{title}</h3>
        {action ? <button type="button" onClick={() => navigateTo(action.view)}>{action.label}</button> : null}
      </header>
      {rows.map(([label, value]) => (
        <div className="hy-info-row" key={label}>
          <span>{label}</span>
          <strong>{value || '—'}</strong>
        </div>
      ))}
    </article>
  );
}

function ConnectionResult({ result }: { result: NativeConnectionTestResult }) {
  const preview = result.output_preview || result.stderr_preview || '';
  const success = result.success ?? result.ok;
  return (
    <div className={`hy-connection-result ${success ? 'success' : 'danger'}`}>
      <strong>{success ? result.message || '连接测试通过' : result.error || result.message || '连接测试失败'}</strong>
      <span>{result.elapsed_seconds !== undefined ? `${result.elapsed_seconds}s` : '—'}</span>
      {preview ? <pre>{preview}</pre> : null}
    </div>
  );
}

function emptyNativeForm(): NativeConfigForm {
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

function formFromNativeConfig(config: NativeVisualConfig | null): NativeConfigForm {
  const providerId = config?.model?.provider || config?.provider_options?.[0]?.id || '';
  const provider = providerOptionById(config, providerId);
  const visionProviderId = config?.vision?.provider || '';
  const visionProvider = providerOptionById(config, visionProviderId);
  return {
    provider: providerId,
    model: config?.model?.default || defaultTextModel(provider),
    base_url: config?.model?.base_url || provider?.base_url || '',
    api_key: '',
    image_input_mode: normalizeImageInputMode(config?.image_input?.mode),
    vision_provider: visionProviderId,
    vision_model: config?.vision?.model || (visionProviderId ? defaultVisionModel(visionProvider) : ''),
    vision_base_url: config?.vision?.base_url || (visionProviderId ? visionProvider?.base_url || '' : ''),
    vision_api_key: '',
  };
}

function normalizeImageInputMode(mode?: string): string {
  const normalized = String(mode || 'auto').trim().toLowerCase();
  if (normalized === 'vision' || normalized === 'yachiyo_vision') return 'text';
  if (normalized === 'auto' || normalized === 'native' || normalized === 'text') return normalized;
  return 'auto';
}

function providerOptionById(config: NativeVisualConfig | null, provider: string): NativeProviderOption | undefined {
  return config?.provider_options?.find((option) => option.id === provider);
}

function defaultTextModel(option: NativeProviderOption | undefined): string {
  return option?.default_model || option?.models?.[0] || '';
}

function defaultVisionModel(option: NativeProviderOption | undefined): string {
  return option?.default_vision_model || option?.vision_models?.[0] || option?.default_model || option?.models?.[0] || '';
}

function textModelOptions(option: NativeProviderOption | undefined, currentModel: string): string[] {
  return uniqueOptions([currentModel, defaultTextModel(option), ...(option?.models || [])]);
}

function visionModelSelectOptions(option: NativeProviderOption | undefined, currentModel: string): string[] {
  const models = option?.vision_models?.length ? option.vision_models : option?.models || [];
  return uniqueOptions([currentModel, defaultVisionModel(option), ...models]);
}

function applyTextProviderPreset(config: NativeVisualConfig | null, current: NativeConfigForm, providerId: string): NativeConfigForm {
  const option = providerOptionById(config, providerId);
  return {
    ...current,
    provider: providerId,
    model: defaultTextModel(option),
    base_url: option?.base_url || '',
    api_key: '',
  };
}

function applyVisionProviderPreset(config: NativeVisualConfig | null, current: NativeConfigForm, providerId: string): NativeConfigForm {
  if (!providerId) {
    return {
      ...current,
      vision_provider: '',
      vision_model: '',
      vision_base_url: '',
      vision_api_key: '',
    };
  }
  const option = providerOptionById(config, providerId);
  return {
    ...current,
    vision_provider: providerId,
    vision_model: defaultVisionModel(option),
    vision_base_url: option?.base_url || '',
    vision_api_key: '',
  };
}

function bridgeState(data: DashboardData | null): string {
  return data?.bridge?.state || data?.bridge?.status || data?.bridge?.running || '—';
}

function isBridgeUnavailableMessage(message: string): boolean {
  return /无法连接本地 Bridge|本地 Bridge 正在启动|Failed to fetch|fetch failed|NetworkError|Load failed/i.test(message);
}

function nativeReadinessLabel(level?: string): string {
  if (level === 'full_ready') return '完整就绪';
  if (level === 'basic_ready') return '基础可用';
  if (level === 'unknown') return '等待 Doctor 分级';
  return level || '等待连接测试';
}

function providerLabel(option: NativeProviderOption): string {
  const state = option.api_key_configured ? '已配置' : option.auth_type && option.auth_type !== 'api_key' ? '外部授权' : '未配置';
  return `${option.label || option.id} (${option.id}) · ${state}`;
}

function uniqueOptions(values: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  return values
    .map((value) => value?.trim() || '')
    .filter((value) => {
      if (!value || seen.has(value)) return false;
      seen.add(value);
      return true;
    });
}

function recentActivities(data: DashboardData | null) {
  const activityRows = (data?.activities || [])
    .map((event) => activityEventRow(event, false))
    .sort((a, b) => timestampMs(b.timestamp) - timestampMs(a.timestamp))
    .slice(0, 6);
  return activityRows;
}

function timestampMs(value?: string) {
  if (!value) return 0;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function formatShortDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatFullDateTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function activityEventRow(event: ActivityEvent, fullTime: boolean): ActivityRowData {
  return {
    icon: activityIcon(event),
    title: event.title || event.tool_name || 'Native 活动',
    detail: activityDetail(event),
    time: fullTime ? formatFullDateTime(event.created_at) : formatShortDateTime(event.created_at),
    tone: activityTone(event.status),
    timestamp: event.created_at,
    eventId: event.event_id,
    sessionId: event.session_id,
    taskId: event.task_id,
    phase: event.phase,
  };
}

function activityTraceKey(event: ActivityEvent, index: number) {
  return event.event_id || `${event.created_at || 'trace'}-${event.title || event.tool_name || 'activity'}-${index}`;
}

function activityTraceDomId(eventId: string) {
  return `activity-trace-${eventId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

function activityTraceIds(event: ActivityEvent) {
  const ids = event.trace_event_ids || [];
  if (!event.event_id) return ids;
  return ids.includes(event.event_id) ? ids : [event.event_id, ...ids];
}

function activityTraceContainsEvent(event: ActivityEvent, eventId: string) {
  return Boolean(eventId && activityTraceIds(event).includes(eventId));
}

function activityTraceSource(events: ActivityEvent[], event: ActivityEvent | null) {
  if (!event?.event_id) return events;
  if (events.some((item) => activityTraceContainsEvent(item, event.event_id || ''))) return events;
  const targetTime = activityEventTimestamp(event);
  const next = [...events];
  if (targetTime === null) {
    next.push(event);
    return next;
  }
  const insertAt = next.findIndex((item) => {
    const itemTime = activityEventTimestamp(item);
    return itemTime !== null && itemTime > targetTime;
  });
  if (insertAt === -1) next.push(event);
  else next.splice(insertAt, 0, event);
  return next;
}

function activityEventTimestamp(event: ActivityEvent) {
  const value = Date.parse(event.created_at || '');
  return Number.isFinite(value) ? value : null;
}

function compactActivityTrace(events: ActivityEvent[]) {
  const compacted: ActivityEvent[] = [];
  events.forEach((event) => {
    const last = compacted[compacted.length - 1];
    if (last && shouldMergeTraceEvents(last, event)) {
      last.detail = mergeTraceDetail(last.detail || '', event.detail || '', event.phase || '');
      last.duration_seconds = traceDuration(last.duration_seconds, event.duration_seconds);
      last.trace_event_ids = mergeTraceIds(activityTraceIds(last), activityTraceIds(event));
      return;
    }
    compacted.push({ ...event, trace_event_ids: activityTraceIds(event) });
  });
  return compacted;
}

function mergeTraceIds(previous: string[], next: string[]) {
  return Array.from(new Set([...previous, ...next]));
}

function shouldMergeTraceEvents(previous: ActivityEvent, next: ActivityEvent) {
  const phase = String(next.phase || '');
  if (!['thinking', 'reasoning', 'tool_progress'].includes(phase)) return false;
  return previous.phase === next.phase
    && previous.status === next.status
    && previous.title === next.title
    && previous.tool_name === next.tool_name
    && previous.session_id === next.session_id
    && previous.task_id === next.task_id;
}

function mergeTraceDetail(previous: string, next: string, phase: string) {
  if (!previous) return next;
  if (!next) return previous;
  if (phase === 'thinking' || phase === 'reasoning') return `${previous}${next}`;
  return `${previous}\n${next}`;
}

function traceDuration(previous?: number | null, next?: number | null) {
  const values = [previous, next].filter((value): value is number => typeof value === 'number');
  return values.length ? values.reduce((total, value) => total + value, 0) : previous ?? next ?? null;
}

function compactActivityDetail(event: ActivityEvent, maxLength = 220) {
  const detail = activityDetail(event);
  if (detail.length <= maxLength) return detail;
  return `${detail.slice(0, maxLength - 1).trimEnd()}…`;
}

function activityDetail(event: ActivityEvent) {
  const parts = [
    event.tool_name || '',
    activityPhaseLabel(event.phase),
    activityStatusLabel(event.status),
    event.session_id ? `Session ${event.session_id}` : '',
    typeof event.duration_seconds === 'number' ? `${event.duration_seconds.toFixed(1)}s` : '',
    event.detail || '',
  ].filter(Boolean);
  return parts.join(' · ') || '已记录安全摘要';
}

function activityIcon(event: ActivityEvent) {
  const tool = String(event.tool_name || '').toLowerCase();
  if (tool.includes('browser')) return '⌕';
  if (tool.includes('file') || tool.includes('read') || tool.includes('write')) return '▣';
  if (tool.includes('search')) return '⌘';
  if (tool.includes('script') || tool.includes('shell') || tool.includes('terminal')) return '>';
  if (event.status === 'failed') return '!';
  if (event.status === 'cancelled') return '×';
  if (event.status === 'completed') return '✓';
  return '•';
}

function activityTone(status?: string) {
  if (status === 'failed' || status === 'cancelled') return 'warning';
  if (status === 'running') return 'chat';
  return 'system';
}

function activityStatusLabel(status?: string) {
  if (status === 'running') return '运行中';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return status || '';
}

function activityPhaseLabel(phase?: string) {
  if (phase === 'task_start') return '任务开始';
  if (phase === 'task_complete') return '任务完成';
  if (phase === 'task_failed') return '任务失败';
  if (phase === 'task_cancelled') return '任务取消';
  if (phase === 'tool_start') return '工具开始';
  if (phase === 'tool_complete') return '工具完成';
  if (phase === 'tool_progress') return '工具进度';
  if (phase === 'reasoning') return '推理';
  if (phase === 'thinking') return '思考';
  if (phase === 'subagent') return '子 Agent';
  if (phase === 'status') return '状态';
  return phase || '活动';
}

function formatMetadata(metadata?: Record<string, unknown>) {
  if (!metadata || !Object.keys(metadata).length) return '';
  try {
    return JSON.stringify(metadata, null, 2);
  } catch {
    return '';
  }
}

function metadataString(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

type ActivityRowData = {
  icon: string;
  title: string;
  detail: string;
  time: string;
  tone?: string;
  timestamp?: string;
  eventId?: string;
  sessionId?: string;
  taskId?: string;
  phase?: string;
};

function groupActivitiesByDay(rows: ActivityRowData[]): Array<{ label: string; items: ActivityRowData[] }> {
  if (!rows.length) return [];

  const now = new Date();
  const todayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const yesterdayDate = new Date(now.getTime() - 86400000);
  const yesterdayKey = `${yesterdayDate.getFullYear()}-${String(yesterdayDate.getMonth() + 1).padStart(2, '0')}-${String(yesterdayDate.getDate()).padStart(2, '0')}`;

  function dayKey(ts?: string): string {
    if (!ts) return todayKey;
    if (/^\d+ (分钟|小时)前$/.test(ts) || ts === '刚刚') return todayKey;
    const date = new Date(ts);
    if (Number.isNaN(date.getTime())) return 'other';
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  const groups: Record<string, ActivityRowData[]> = {};
  for (const row of rows) {
    const key = dayKey(row.timestamp);
    if (!groups[key]) groups[key] = [];
    groups[key].push(row);
  }

  const result: Array<{ label: string; items: ActivityRowData[] }> = [];
  if (groups[todayKey]) result.push({ label: '今天', items: groups[todayKey] });
  if (groups[yesterdayKey]) result.push({ label: '昨天', items: groups[yesterdayKey] });
  for (const [key, items] of Object.entries(groups)) {
    if (key === todayKey || key === yesterdayKey) continue;
    result.push({ label: key === 'other' ? '更早' : key, items });
  }
  return result;
}

function routeTitle(view: AppView, settingsMode = ''): string {
  if (view === 'main') return 'Oha Yachiyo — 主控台';
  if (view === 'chat') return 'Oha Yachiyo — 对话';
  if (view === 'tasks') return 'Oha Yachiyo — 任务';
  if (view === 'memories') return 'Oha Yachiyo — 记忆';
  if (view === 'skills') return 'Oha Yachiyo — Skills';
  if (view === 'agents') return 'Oha Yachiyo — Agent Studio';
  if (view === 'provider') return 'Oha Yachiyo — 模型配置';
  if (view === 'bubble') return 'Oha Yachiyo — 气泡模式';
  if (view === 'live2d') return 'Oha Yachiyo — Live2D 模式';
  if (view === 'resources') return 'Oha Yachiyo — 资源管理';
  if (view === 'workspace') return 'Oha Yachiyo — 工作区';
  if (view === 'tools-all') return 'Oha Yachiyo — 桌面工具';
  if (view === 'activity-all') return 'Oha Yachiyo — 活动日志';
  if (view === 'activity-detail') return 'Oha Yachiyo — 活动详情';
  if (view === 'app-update') return 'Oha Yachiyo — 应用更新';
  if (view === 'proactive-tts') return 'Oha Yachiyo — 主动关怀';
  if (view === 'settings' && settingsMode === 'live2d') return 'Oha Yachiyo — Live2D 设置';
  if (view === 'settings' && settingsMode === 'bubble') return 'Oha Yachiyo — 气泡设置';
  return 'Oha Yachiyo';
}

function isNavActive(activeView: AppView, settingsMode: string, itemView: AppView): boolean {
  const studioTab = activeView === 'agents' ? currentParam('tab') : '';
  if (itemView === 'memories') return activeView === 'memories' || studioTab === 'memory';
  if (itemView === 'skills') return activeView === 'skills' || studioTab === 'skills' || studioTab === 'skill-groups';
  if (itemView === 'agents' && activeView === 'agents') return !['memory', 'skills', 'skill-groups'].includes(studioTab);
  if (activeView === itemView) return true;
  if (itemView === 'bubble' && activeView === 'settings' && settingsMode === 'bubble') return true;
  if (itemView === 'live2d' && activeView === 'settings' && settingsMode === 'live2d') return true;
  return false;
}

function navBadge(view: AppView, data: DashboardData | null): string {
  if (view === 'tasks') {
    const activeTasks = Number(data?.tasks?.pending || 0) + Number(data?.tasks?.running || 0);
    return activeTasks > 0 ? String(activeTasks) : '';
  }
  if (view === 'workspace' && data?.workspace?.initialized) return 'ok';
  if (view === 'provider' && dashboardNativeAgent(data)?.ready) return 'ok';
  return '';
}
