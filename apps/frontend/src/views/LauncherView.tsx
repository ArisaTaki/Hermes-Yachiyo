import { CSSProperties, FormEvent, KeyboardEvent, MouseEvent, PointerEvent, useCallback, useEffect, useRef, useState, type MutableRefObject } from 'react';

import { apiGet, apiPost, bridgeUrl, getLauncherPointerState, moveLauncherWindow, openAppView, openLauncherMenu, setLauncherHitRegions, setLauncherPointerInteractive, type LauncherHitRegionRect } from '../lib/bridge';
import type { AppView } from '../lib/view';

type LauncherPayload = {
  ok?: boolean;
  mode?: 'bubble' | 'live2d';
  chat?: {
    is_processing?: boolean;
    empty?: boolean;
    status_label?: string;
    latest_reply?: string;
    latest_reply_full?: string;
  };
  notification?: {
    has_unread?: boolean;
    latest_message?: { status?: string; content?: string };
  };
  tts?: {
    enabled?: boolean;
    provider?: string;
    ok?: boolean;
    message?: string;
    error?: string;
  };
  proactive?: {
    enabled?: boolean;
    has_attention?: boolean;
    session_id?: string;
    message?: string;
    result?: string;
    attention_text?: string;
    attention_source?: string;
    error?: string;
  };
  launcher?: {
    has_attention?: boolean;
    latest_status?: string;
    status_label?: string;
    latest_reply?: string;
    latest_reply_full?: string;
    avatar_url?: string;
    default_display?: string;
    expand_trigger?: string;
    show_unread_dot?: boolean;
    auto_hide?: boolean;
    opacity?: number;
    suppress_status_dot?: boolean;
    show_reply_bubble?: boolean;
    enable_quick_input?: boolean;
    click_action?: string;
    default_open_behavior?: string;
    position_anchor?: string;
    preview_url?: string;
    scale?: number;
    mouse_follow_enabled?: boolean;
    renderer?: {
      enabled?: boolean;
      model_url?: string;
      reason?: string;
      idle_motion_group?: string;
      enable_expressions?: boolean;
      enable_physics?: boolean;
      expression_mappings?: Record<string, string>;
      expression_keywords?: Record<string, string>;
      expressions?: Array<{ name?: string; file?: string }>;
      motion_groups?: Record<string, Array<Record<string, unknown>>>;
    };
    resource?: {
      available?: boolean;
      state?: string;
      display_name?: string;
      status_label?: string;
      help_text?: string;
      renderer_entry?: string;
    };
  };
};

const ACTIVE_POLL_INTERVAL_MS = 1200;
const IDLE_POLL_INTERVAL_MS = 5000;
const CLICK_DRAG_THRESHOLD_PX = 6;
const LIVE2D_POINTER_PASSTHROUGH_ENABLED = true;
const LIVE2D_GLOBAL_POINTER_POLL_MS = 40;
const LIVE2D_MOUSE_FOLLOW_SMOOTH_MS = 86;
const LIVE2D_MOUSE_FOLLOW_DEADZONE_PX = 0.65;
const LIVE2D_SHAPE_PADDING_PX = 1;
const LIVE2D_MAX_SHAPE_RECTS = 6000;
const LIVE2D_SHAPE_MAX_COLS = 88;
const LIVE2D_SHAPE_MAX_ROWS = 132;
const LIVE2D_MASK_MAX_FILL_RATIO = 0.72;
const LIVE2D_IDLE_MOTION_FIRST_MS = 700;
const LIVE2D_IDLE_MOTION_MIN_MS = 8500;
const LIVE2D_IDLE_MOTION_JITTER_MS = 6500;
type PointerLike = {
  screenX: number;
  screenY: number;
  clientX: number;
  clientY: number;
  preventDefault: () => void;
  stopPropagation: () => void;
};

type LauncherDragState = {
  dragging: boolean;
  lastX: number;
  lastY: number;
  startX: number;
  startY: number;
};

type Live2DGlobalWindow = typeof window & {
  PIXI?: any;
  Live2DCubismCore?: unknown;
  Live2DModel?: any;
  process?: { env?: Record<string, string> };
};

type Live2DRendererState = {
  app?: any;
  model?: any;
  modelKey?: string;
  modelUrl?: string;
  loadToken: number;
};

type Live2DFocusState = {
  active: boolean;
  currentX: number;
  currentY: number;
  lastFrameAt: number;
  targetX: number;
  targetY: number;
};

type Live2DRuntimeScript = {
  id: string;
  source?: string;
  url: string;
};

type Live2DRuntimePayload = {
  ok?: boolean;
  ready?: boolean;
  error?: string;
  scripts?: Live2DRuntimeScript[];
};

type Live2DHitRegion = {
  kind: 'alpha_mask' | 'ellipse' | 'live2d' | 'model' | 'rect';
  x: number;
  y: number;
  width: number;
  height: number;
  cols?: number;
  rows?: number;
  mask?: string;
};

const LIVE2D_RUNTIME_CDN_SCRIPTS: Live2DRuntimeScript[] = [
  { id: 'pixi_js', source: 'cdn', url: 'https://cdn.jsdelivr.net/npm/pixi.js@6/dist/browser/pixi.min.js' },
  { id: 'live2d_cubism_core', source: 'cdn', url: 'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js' },
  { id: 'pixi_live2d_display', source: 'cdn', url: 'https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta/dist/cubism4.min.js' },
];

let live2dRuntimePromise: Promise<void> | null = null;

export function LauncherView({ view }: { view: AppView }) {
  const mode = view === 'live2d' ? 'live2d' : 'bubble';
  const launcher = useLauncher(mode);

  useEffect(() => {
    document.body.classList.add('desktop-mode-body');
    return () => document.body.classList.remove('desktop-mode-body');
  }, []);

  if (mode === 'live2d') return <Live2DLauncher data={launcher.data} refresh={launcher.refresh} />;
  return <BubbleLauncher data={launcher.data} />;
}

function useLauncher(mode: 'bubble' | 'live2d') {
  const [data, setData] = useState<LauncherPayload | null>(null);

  const refresh = useCallback(async () => {
    try {
      const payload = await apiGet<LauncherPayload>(`/ui/launcher?mode=${mode}`);
      if (payload.ok !== false) setData(payload);
    } catch {
      setData((current) => current || { ok: false, mode });
    }
  }, [mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const processing = Boolean(data?.chat?.is_processing);
    const timer = window.setInterval(refresh, processing ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [data?.chat?.is_processing, refresh]);

  return { data, refresh };
}

async function acknowledgeAndOpenChat(mode: 'bubble' | 'live2d') {
  let sessionId = '';
  try {
    const result = await apiPost<{ session_id?: string }>('/ui/launcher/ack', { mode });
    sessionId = result.session_id || '';
  } catch {}
  await openAppView('chat', sessionId ? { session_id: sessionId } : {});
}

function openSettings(mode: 'bubble' | 'live2d') {
  return openAppView('settings', { mode });
}

function handleContextMenu(event: MouseEvent, mode: 'bubble' | 'live2d') {
  event.preventDefault();
  void openLauncherMenu(mode);
}

function BubbleLauncher({ data }: { data: LauncherPayload | null }) {
  const launcher = data?.launcher || {};
  const proactive = data?.proactive || {};
  const dragStateRef = useRef<LauncherDragState | null>(null);
  const clickSuppressedRef = useRef(false);
  const status = launcher.latest_status || (data?.chat?.is_processing ? 'processing' : 'empty');
  const showDot = launcher.show_unread_dot !== false && !launcher.suppress_status_dot;
  const proactiveAttention = Boolean(proactive.has_attention);
  const hasAttention = showDot && Boolean(launcher.has_attention || proactiveAttention);
  const unreadStatus = String(data?.notification?.latest_message?.status || '');
  const dotClass = bubbleDotClass(showDot, hasAttention, status, unreadStatus, proactiveAttention);
  const opacity = Math.max(0.2, Math.min(1, Number(launcher.opacity || 0.92)));
  const idleHidden = Boolean(launcher.auto_hide && !data?.chat?.is_processing && !launcher.has_attention && !proactive.has_attention);
  const displayMode = launcher.default_display || 'summary';
  const statusLabel = normalizedStatusLabel(data?.chat);
  const title = bubbleTitle(displayMode, hasAttention, statusLabel, proactive);
  const ariaLabel = displayMode === 'icon'
    ? 'Yachiyo Bubble'
    : `Yachiyo Bubble - ${hasAttention ? '有新消息' : statusLabel}`;
  const style = {
    opacity: idleHidden ? Math.max(0.24, opacity * 0.52) : opacity,
    '--bubble-avatar': `url(${launcher.avatar_url || ''})`,
  } as CSSProperties;

  function clearPointerState() {
    dragStateRef.current = null;
  }

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button === 2) {
      clearPointerState();
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = newDragState(event);
    clickSuppressedRef.current = false;
  }

  function handlePointerMove(event: PointerEvent<HTMLButtonElement>) {
    if (dragLauncherWindow(event, dragStateRef)) clickSuppressedRef.current = true;
  }

  function handlePointerUp(event: PointerEvent<HTMLButtonElement>) {
    if (dragStateRef.current?.dragging || pointerMovedPastThreshold(event, dragStateRef.current)) {
      clickSuppressedRef.current = true;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    clearPointerState();
  }

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    const ignore = clickSuppressedRef.current;
    clearPointerState();
    if (ignore) {
      event.preventDefault();
      event.stopPropagation();
      clickSuppressedRef.current = false;
      return;
    }
    clickSuppressedRef.current = false;
    void acknowledgeAndOpenChat('bubble');
  }

  return (
    <main className="launcher-shell bubble-shell" onContextMenu={(event) => handleContextMenu(event, 'bubble')}>
      <button
        className={`bubble-launcher ${hasAttention ? 'has-unread' : ''} ${proactiveAttention ? 'has-proactive' : ''} ${idleHidden ? 'auto-hidden' : ''}`}
        style={style}
        type="button"
        title={title}
        aria-label={title}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={clearPointerState}
        onBlur={clearPointerState}
        onClick={handleClick}
      >
        <span className="portrait" aria-hidden="true"><span className="mouth" /></span>
        <span className={dotClass} aria-hidden="true" />
        <span className="bubble-summary hidden" aria-hidden="true" />
      </button>
    </main>
  );
}

function normalizedStatusLabel(chat: LauncherPayload['chat']) {
  const label = String(chat?.status_label || '').trim();
  if (!label || label === '就绪' || label === '暂无对话') return '';
  return label;
}

function bubbleDotClass(showDot: boolean, hasAttention: boolean, status: string, unreadStatus: string, proactiveAttention: boolean) {
  let className = 'status-dot';
  if (hasAttention) {
    if (proactiveAttention) className += ' visible proactive';
    else if (unreadStatus === 'failed') className += ' visible failed';
    else if (unreadStatus === 'completed') className += ' visible completed';
    else className += ' visible attention';
  } else if (showDot && status === 'processing') {
    className += ' visible processing';
  } else {
    className += ` ${status}`;
  }
  return className;
}

function bubbleTitle(
  displayMode: string,
  hasAttention: boolean,
  statusLabel: string,
  proactive: NonNullable<LauncherPayload['proactive']>,
) {
  const titleParts = [
    displayMode === 'icon'
      ? 'Yachiyo - 头像图标'
      : `Yachiyo - ${hasAttention ? '有新消息，点击查看' : (statusLabel || '点击展开对话')}`,
  ];
  if (proactive.error) titleParts.push(`主动关怀：${proactive.error}`);
  else if (proactive.has_attention) titleParts.push(`主动关怀：${proactive.attention_text || proactive.message || '有新的观察结果'}`);
  else if (proactive.enabled && proactive.message) titleParts.push(`主动关怀：${proactive.message}`);
  return titleParts.join('\n');
}

function Live2DLauncher({ data, refresh }: { data: LauncherPayload | null; refresh: () => Promise<void> }) {
  const launcher = data?.launcher || {};
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const characterRef = useRef<HTMLDivElement | null>(null);
  const previewRef = useRef<HTMLImageElement | null>(null);
  const resourceHintRef = useRef<HTMLDivElement | null>(null);
  const replyRef = useRef<HTMLButtonElement | null>(null);
  const quickInputRef = useRef<HTMLFormElement | null>(null);
  const quickInputComposingRef = useRef(false);
  const dragStateRef = useRef<LauncherDragState | null>(null);
  const pointerActivationRef = useRef(false);
  const clickSuppressedRef = useRef(false);
  const hitRegionRef = useRef<Live2DHitRegion | null>(null);
  const uiRegionsRef = useRef<Live2DHitRegion[]>([]);
  const shapeAppliedRef = useRef(false);
  const shapeSignatureRef = useRef('');
  const rendererStateRef = useRef<Live2DRendererState>({ loadToken: 0 });
  const focusStateRef = useRef<Live2DFocusState>({
    active: false,
    currentX: 0,
    currentY: 0,
    lastFrameAt: 0,
    targetX: 0,
    targetY: 0,
  });
  const lastReactionKeyRef = useRef('');
  const lastStatusExpressionKeyRef = useRef('');
  const [quickText, setQuickText] = useState('');
  const [replyHidden, setReplyHidden] = useState(false);
  const [quickInputVisible, setQuickInputVisible] = useState(launcher.default_open_behavior === 'chat_input');
  const [dismissedHintKey, setDismissedHintKey] = useState('');
  const [rendererLoading, setRendererLoading] = useState(false);
  const [rendererReady, setRendererReady] = useState(false);
  const [rendererError, setRendererError] = useState('');
  const latestReply = latestAssistantText(data?.chat, launcher);
  const status = launcher.latest_status || (data?.chat?.is_processing ? 'processing' : 'empty');
  const hasAttention = Boolean(data?.notification?.has_unread);
  const proactiveAttention = Boolean(data?.proactive?.has_attention);
  const isProcessing = Boolean(data?.chat?.is_processing);
  const unreadStatus = String(data?.notification?.latest_message?.status || '');
  const resource = launcher.resource;
  const renderer = launcher.renderer;
  const rendererMotionSignature = live2dMotionGroupSignature(renderer?.motion_groups);
  const rendererExpressionKeywordSignature = live2dStringRecordSignature(renderer?.expression_keywords);
  const rendererExpressionMappingSignature = live2dStringRecordSignature(renderer?.expression_mappings);
  const replyText = proactiveAttention
    ? (data?.proactive?.attention_text || data?.proactive?.message || '有新的主动桌面观察结果')
    : hasAttention && !isProcessing
        ? latestReply
        : '';
  const replyCue = live2dReplyCue({ proactiveAttention, status: unreadStatus });
  const showReply = Boolean(launcher.show_reply_bubble !== false && (proactiveAttention || !replyHidden) && replyText && !isProcessing);
  const stageTitle = live2dStageTitle(resource, launcher, data, hasAttention, proactiveAttention);
  const positionAnchor = normalizeLive2DPositionAnchor(launcher.position_anchor);
  const characterClass = live2dCharacterClass(data, hasAttention, proactiveAttention, unreadStatus, rendererReady);
  const hintKey = [resource?.state || '', resource?.status_label || '', resource?.help_text || '', resource?.renderer_entry || ''].join('|');
  const hintTone = resource?.state === 'path_valid' || resource?.state === 'loaded' ? 'ok' : 'warn';
  const showResourceHint = Boolean(resource && hintTone !== 'ok' && hintKey !== dismissedHintKey);
  const previewStyle = {
    '--live2d-preview-scale': String(Math.max(0.4, Math.min(2.0, Number(launcher.scale || 1)))),
    '--live2d-object-position': live2dObjectPosition(positionAnchor),
    '--live2d-transform-origin': live2dTransformOrigin(positionAnchor),
  } as CSSProperties;

  useEffect(() => {
    setQuickInputVisible(launcher.default_open_behavior === 'chat_input');
    setReplyHidden(launcher.default_open_behavior === 'stage' || launcher.default_open_behavior === 'chat_input');
  }, [launcher.default_open_behavior]);

  useEffect(() => {
    let disposed = false;
    void ensureLive2DRenderer({
      canvas: canvasRef.current,
      character: characterRef.current,
      renderer,
      scale: launcher.scale,
      positionAnchor,
      state: rendererStateRef.current,
      onError: (value) => {
        if (!disposed) setRendererError(value);
      },
      onLoading: (value) => {
        if (!disposed) setRendererLoading(value);
      },
      onReady: (value) => {
        if (!disposed) setRendererReady(value);
      },
    });
    return () => {
      disposed = true;
    };
  }, [renderer?.enabled, renderer?.model_url, renderer?.reason, renderer?.enable_physics, launcher.scale, positionAnchor]);

  useEffect(() => {
    const rendererState = rendererStateRef.current;
    void setLauncherPointerInteractive('live2d', true);
    return () => {
      destroyLive2DRenderer(rendererState);
      void setLauncherPointerInteractive('live2d', true);
    };
  }, []);

  useEffect(() => {
    let frame = 0;
    const scheduleReport = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        reportLive2DRegions({
          canvas: canvasRef.current,
          character: characterRef.current,
          preview: previewRef.current,
          quickInput: quickInputRef.current,
          rendererReady,
          reply: replyRef.current,
          resourceHint: resourceHintRef.current,
          hitRegionRef,
          shapeAppliedRef,
          shapeSignatureRef,
          uiRegionsRef,
        });
      });
    };
    scheduleReport();
    const timers = [80, 180, 360, 720].map((delay) => window.setTimeout(scheduleReport, delay));
    window.addEventListener('resize', scheduleReport);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      timers.forEach((timer) => window.clearTimeout(timer));
      window.removeEventListener('resize', scheduleReport);
    };
  }, [rendererReady, rendererLoading, renderer?.model_url, launcher.preview_url, launcher.scale, positionAnchor, showReply, quickInputVisible, showResourceHint, dismissedHintKey]);

  useEffect(() => {
    return () => {
      shapeAppliedRef.current = false;
      shapeSignatureRef.current = '';
    };
  }, []);

  useEffect(() => {
    if (!rendererReady) return;
    return startLive2DIdleMotionLoop(rendererStateRef.current, renderer);
  }, [rendererReady, renderer?.idle_motion_group, rendererMotionSignature]);

  useEffect(() => {
    if (!rendererReady || launcher.mouse_follow_enabled === false) return;
    focusStateRef.current.active = false;
    return startLive2DFocusLoop(rendererStateRef.current, focusStateRef);
  }, [rendererReady, launcher.mouse_follow_enabled]);

  useEffect(() => {
    let pending = false;
    const refreshPointerState = () => {
      if (pending) return;
      pending = true;
      void refreshGlobalPointerState({
        character: characterRef.current,
        focusState: focusStateRef,
        followMouse: launcher.mouse_follow_enabled !== false,
        hitRegion: hitRegionRef.current,
        uiRegions: uiRegionsRef.current,
      }).finally(() => {
        pending = false;
      });
    };
    refreshPointerState();
    const timer = window.setInterval(refreshPointerState, LIVE2D_GLOBAL_POINTER_POLL_MS);
    return () => window.clearInterval(timer);
  }, [launcher.mouse_follow_enabled]);

  useEffect(() => {
    if (!rendererReady || !hasAttention) return;
    const reactionKey = latestReply || data?.notification?.latest_message?.content || '';
    if (!reactionKey || reactionKey === lastReactionKeyRef.current) return;
    lastReactionKeyRef.current = reactionKey;
    playLive2DReaction(rendererStateRef.current, renderer, reactionKey);
  }, [rendererReady, hasAttention, latestReply, data?.notification?.latest_message?.content, renderer?.enable_expressions, renderer?.idle_motion_group, rendererExpressionMappingSignature, rendererExpressionKeywordSignature]);

  useEffect(() => {
    if (!rendererReady) return;
    const expressionText = latestReply || data?.notification?.latest_message?.content || data?.proactive?.attention_text || data?.proactive?.message || '';
    const expressionKey = live2dStatusExpressionKey({
      hasAttention,
      isProcessing,
      proactiveAttention,
      unreadStatus: String(data?.notification?.latest_message?.status || ''),
    });
    if (!expressionKey) {
      if (lastStatusExpressionKeyRef.current) resetLive2DExpression(rendererStateRef.current);
      lastStatusExpressionKeyRef.current = '';
      return;
    }
    const statusExpressionKey = `${expressionKey}:${expressionText}:${rendererExpressionMappingSignature}:${rendererExpressionKeywordSignature}`;
    if (statusExpressionKey === lastStatusExpressionKeyRef.current) return;
    lastStatusExpressionKeyRef.current = statusExpressionKey;
    playLive2DStatusExpression(rendererStateRef.current, renderer, expressionKey, expressionText);
  }, [rendererReady, hasAttention, isProcessing, proactiveAttention, latestReply, data?.notification?.latest_message?.content, data?.notification?.latest_message?.status, data?.proactive?.attention_text, data?.proactive?.message, renderer?.expressions, rendererExpressionMappingSignature, rendererExpressionKeywordSignature]);

  function handleWindowPointerDown(event: PointerEvent<HTMLElement>) {
    pointerActivationRef.current = false;
    if (event.button === 2 || live2dInteractiveTarget(event.target)) return;
    if (LIVE2D_POINTER_PASSTHROUGH_ENABLED && !shapeAppliedRef.current && !live2dPointerInteractive(event.clientX, event.clientY, hitRegionRef.current, uiRegionsRef.current)) {
      void setLauncherPointerInteractive('live2d', false);
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = newDragState(event);
    pointerActivationRef.current = true;
    clickSuppressedRef.current = false;
  }

  function handleWindowPointerMove(event: PointerEvent<HTMLElement>) {
    if (dragLauncherWindow(event, dragStateRef)) {
      clickSuppressedRef.current = true;
      return;
    }
    const interactive = live2dPointerInteractive(event.clientX, event.clientY, hitRegionRef.current, uiRegionsRef.current);
    void setLauncherPointerInteractive('live2d', LIVE2D_POINTER_PASSTHROUGH_ENABLED ? interactive : true);
    if (interactive && launcher.mouse_follow_enabled !== false) {
      setLive2DFocusTargetFromWindowPoint(focusStateRef, characterRef.current, event.clientX, event.clientY);
    }
  }

  function handleWindowPointerUp(event: PointerEvent<HTMLElement>) {
    const moved = Boolean(dragStateRef.current?.dragging || pointerMovedPastThreshold(event, dragStateRef.current));
    const shouldActivate = pointerActivationRef.current
      && !moved
      && !live2dInteractiveTarget(event.target)
      && live2dPointerInteractive(event.clientX, event.clientY, hitRegionRef.current, uiRegionsRef.current);
    if (moved) {
      clickSuppressedRef.current = true;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragStateRef.current = null;
    pointerActivationRef.current = false;
    if (shouldActivate) {
      clickSuppressedRef.current = true;
      event.preventDefault();
      event.stopPropagation();
      void activateLive2DStage();
    }
  }

  function handleWindowPointerCancel() {
    dragStateRef.current = null;
    pointerActivationRef.current = false;
    clickSuppressedRef.current = false;
  }

  function handleWindowPointerLeave() {
    pointerActivationRef.current = false;
    if (LIVE2D_POINTER_PASSTHROUGH_ENABLED) void setLauncherPointerInteractive('live2d', false);
    if (launcher.mouse_follow_enabled === false) return;
    setLive2DFocusTargetAtCenter(focusStateRef, characterRef.current);
  }

  async function activateLive2DStage() {
    if (launcher.click_action === 'toggle_reply') {
      resetLive2DExpression(rendererStateRef.current);
      lastStatusExpressionKeyRef.current = '';
      setReplyHidden((value) => !value);
      try {
        await apiPost('/ui/launcher/ack', { mode: 'live2d' });
      } catch {}
      return;
    }
    if (launcher.click_action === 'focus_stage') {
      return;
    }
    resetLive2DExpression(rendererStateRef.current);
    lastStatusExpressionKeyRef.current = '';
    await acknowledgeAndOpenChat('live2d');
  }

  async function handleStageClick(event?: MouseEvent<HTMLElement>) {
    if (clickSuppressedRef.current) {
      clickSuppressedRef.current = false;
      return;
    }
    if (
      LIVE2D_POINTER_PASSTHROUGH_ENABLED
      && !shapeAppliedRef.current
      && event
      && !live2dPointerInteractive(event.clientX, event.clientY, hitRegionRef.current, uiRegionsRef.current)
    ) {
      void setLauncherPointerInteractive('live2d', false);
      return;
    }
    await activateLive2DStage();
  }

  async function sendQuickMessage(event: FormEvent) {
    event.preventDefault();
    if (quickInputComposingRef.current) return;
    const text = quickText.trim();
    if (!text) return;
    setQuickText('');
    await apiPost('/ui/launcher/quick-message', {
      text,
      mode: data?.mode || 'live2d',
      session_id: proactiveAttention ? String(data?.proactive?.session_id || '') : '',
    });
    setReplyHidden(false);
    setQuickInputVisible(false);
    await refresh();
  }

  return (
    <main
      className={`launcher-shell live2d-shell live2d-anchor-${positionAnchor}`}
      style={previewStyle}
      onContextMenu={(event) => handleContextMenu(event, 'live2d')}
      onPointerDown={handleWindowPointerDown}
      onPointerMove={handleWindowPointerMove}
      onPointerUp={handleWindowPointerUp}
      onPointerCancel={handleWindowPointerCancel}
      onPointerLeave={handleWindowPointerLeave}
    >
      <div
        className="live2d-stage"
        role="button"
        tabIndex={0}
        title={stageTitle}
        aria-label={stageTitle}
        onClick={(event) => void handleStageClick(event)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') void handleStageClick();
        }}
      >
        <div ref={characterRef} className={characterClass} aria-label="Yachiyo Live2D 角色舞台">
          <canvas ref={canvasRef} className={`live2d-canvas ${rendererReady ? 'active' : ''}`} aria-hidden="true" />
          {launcher.preview_url ? (
            <img
              ref={previewRef}
              className={`live2d-preview-fallback ${rendererReady ? 'hidden' : ''}`}
              src={launcher.preview_url}
              alt=""
              onLoad={() => reportLive2DRegions({
                canvas: canvasRef.current,
                character: characterRef.current,
                preview: previewRef.current,
                quickInput: quickInputRef.current,
                rendererReady,
                reply: replyRef.current,
                resourceHint: resourceHintRef.current,
                hitRegionRef,
                shapeAppliedRef,
                shapeSignatureRef,
                uiRegionsRef,
              })}
            />
          ) : null}
          {showResourceHint ? (
            <div ref={resourceHintRef} className={`live2d-resource-hint ${hintTone}`} onClick={(event) => event.stopPropagation()}>
              <span className="live2d-resource-hint-text">{[resource?.status_label, resource?.help_text].filter(Boolean).join(' ')}</span>
              <button
                className="live2d-resource-hint-close"
                type="button"
                aria-label="关闭资源提示"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setDismissedHintKey(hintKey || '__dismissed__');
                }}
              >×</button>
            </div>
          ) : null}
          {rendererLoading ? <div className="live2d-loading">Live2D 模型加载中...</div> : null}
          {rendererError || (!rendererReady ? renderer?.reason : '') ? <div className="live2d-error">{rendererError || renderer?.reason}</div> : null}
        </div>
      </div>

      {showReply ? (
        <button
          ref={replyRef}
          className={`live2d-reply ${proactiveAttention ? 'proactive' : ''} ${hasAttention ? 'attention' : ''} ${replyCue.tone}`}
          type="button"
          aria-label={replyCue.label}
          onClick={() => {
            resetLive2DExpression(rendererStateRef.current);
            lastStatusExpressionKeyRef.current = '';
            if (proactiveAttention) void acknowledgeAndOpenChat('live2d');
            else setReplyHidden(true);
          }}
        >
          <span aria-hidden="true">{replyCue.symbol}</span>
        </button>
      ) : null}

      {launcher.enable_quick_input !== false && quickInputVisible ? (
        <form ref={quickInputRef} className="live2d-quick-input" onSubmit={sendQuickMessage} onClick={(event) => event.stopPropagation()}>
          <input
            value={quickText}
            onChange={(event) => setQuickText(event.target.value)}
            onCompositionEnd={() => {
              quickInputComposingRef.current = false;
            }}
            onCompositionStart={() => {
              quickInputComposingRef.current = true;
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && isImeComposingKey(event, quickInputComposingRef.current)) {
                event.preventDefault();
              }
            }}
            placeholder="和八千代说点什么…"
          />
          <button type="submit" disabled={!quickText.trim()}>发送</button>
        </form>
      ) : null}
    </main>
  );
}

function pointerPoint(event: PointerLike) {
  return {
    x: Number.isFinite(event.screenX) ? event.screenX : event.clientX,
    y: Number.isFinite(event.screenY) ? event.screenY : event.clientY,
  };
}

function isImeComposingKey(event: KeyboardEvent<HTMLElement>, fallback = false) {
  const nativeEvent = event.nativeEvent as globalThis.KeyboardEvent & { isComposing?: boolean };
  return Boolean(fallback || nativeEvent.isComposing || nativeEvent.keyCode === 229);
}

function newDragState(event: PointerLike): LauncherDragState {
  const point = pointerPoint(event);
  return {
    dragging: false,
    lastX: point.x,
    lastY: point.y,
    startX: point.x,
    startY: point.y,
  };
}

function pointerMovedPastThreshold(event: PointerLike, state: LauncherDragState | null) {
  if (!state) return false;
  const point = pointerPoint(event);
  return Math.abs(point.x - state.startX) > CLICK_DRAG_THRESHOLD_PX
    || Math.abs(point.y - state.startY) > CLICK_DRAG_THRESHOLD_PX;
}

function dragLauncherWindow(
  event: PointerLike,
  dragStateRef: MutableRefObject<LauncherDragState | null>,
) {
  const state = dragStateRef.current;
  if (!state) return false;
  const point = pointerPoint(event);
  if (!state.dragging && pointerMovedPastThreshold(event, state)) state.dragging = true;
  if (!state.dragging) return false;
  const deltaX = point.x - state.lastX;
  const deltaY = point.y - state.lastY;
  state.lastX = point.x;
  state.lastY = point.y;
  event.preventDefault();
  event.stopPropagation();
  if (deltaX || deltaY) void moveLauncherWindow(deltaX, deltaY);
  return true;
}

function live2dInteractiveTarget(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest('.live2d-resource-hint, .live2d-reply, .live2d-quick-input'));
}

function latestAssistantText(chat: LauncherPayload['chat'], launcher: NonNullable<LauncherPayload['launcher']>) {
  return launcher.latest_reply || chat?.latest_reply || launcher.latest_reply_full || chat?.latest_reply_full || '';
}

function live2dCharacterClass(
  data: LauncherPayload | null,
  hasAttention: boolean,
  proactiveAttention: boolean,
  unreadStatus: string,
  rendererReady = false,
) {
  const classes = ['live2d-character'];
  if (rendererReady) classes.push('renderer-ready');
  if (data?.chat?.is_processing) classes.push('processing');
  else if (hasAttention && unreadStatus === 'failed') classes.push('failed');
  else if (proactiveAttention) classes.push('has-proactive-attention');
  else if (hasAttention) classes.push('has-message');
  return classes.join(' ');
}

function normalizeLive2DPositionAnchor(value: unknown): 'left-bottom' | 'right-bottom' | 'custom' {
  if (value === 'left_bottom') return 'left-bottom';
  if (value === 'custom') return 'custom';
  return 'right-bottom';
}

function live2dObjectPosition(anchor: 'left-bottom' | 'right-bottom' | 'custom') {
  if (anchor === 'left-bottom') return 'left bottom';
  if (anchor === 'right-bottom') return 'right bottom';
  return 'center bottom';
}

function live2dTransformOrigin(anchor: 'left-bottom' | 'right-bottom' | 'custom') {
  if (anchor === 'left-bottom') return 'left bottom';
  if (anchor === 'right-bottom') return 'right bottom';
  return 'center bottom';
}

function live2dStageTitle(
  resource: NonNullable<LauncherPayload['launcher']>['resource'],
  launcher: NonNullable<LauncherPayload['launcher']>,
  data: LauncherPayload | null,
  hasAttention: boolean,
  proactiveAttention: boolean,
) {
  const messageHint = proactiveAttention
    ? '，有新的桌面观察结果'
    : data?.chat?.is_processing
      ? '，正在回复'
      : hasAttention
        ? '，有新消息'
        : '';
  return `${resource?.status_label || 'Yachiyo Live2D'}${messageHint}，点击行为：${launcher.click_action || 'open_chat'}`;
}

function live2dStatusExpressionKey({
  hasAttention,
  isProcessing,
  proactiveAttention,
  unreadStatus,
}: {
  hasAttention: boolean;
  isProcessing: boolean;
  proactiveAttention: boolean;
  unreadStatus: string;
}) {
  if (isProcessing) return 'thinking';
  if (hasAttention && unreadStatus === 'failed') return 'failed';
  if (proactiveAttention) return 'attention';
  if (hasAttention) return 'message';
  return '';
}

function live2dReplyCue({
  proactiveAttention,
  status,
}: {
  proactiveAttention: boolean;
  status: string;
}) {
  if (status === 'failed') return { label: '回复失败，点击打开对话', symbol: '!', tone: 'failed' };
  if (proactiveAttention) return { label: '新的主动关怀，点击打开对话', symbol: '!', tone: 'proactive-cue' };
  return { label: '新的回复，点击隐藏提示', symbol: '!', tone: 'message-cue' };
}

async function ensureLive2DRenderer({
  canvas,
  character,
  renderer,
  scale,
  positionAnchor,
  state,
  onError,
  onLoading,
  onReady,
}: {
  canvas: HTMLCanvasElement | null;
  character: HTMLDivElement | null;
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'];
  scale?: number;
  positionAnchor: 'left-bottom' | 'right-bottom' | 'custom';
  state: Live2DRendererState;
  onError: (value: string) => void;
  onLoading: (value: boolean) => void;
  onReady: (value: boolean) => void;
}) {
  if (!renderer?.enabled || !renderer.model_url) {
    destroyLive2DRenderer(state);
    onLoading(false);
    onReady(false);
    onError('');
    return;
  }
  if (!canvas || !character) {
    onLoading(false);
    onReady(false);
    onError('Live2D 舞台尚未就绪，已回退到静态预览');
    return;
  }
  const modelKey = `${renderer.model_url}|physics:${renderer.enable_physics === true ? '1' : '0'}`;

  try {
    await ensureLive2DRuntimeScripts();
    if (!rendererAvailable()) {
      throw new Error(`Live2D 渲染依赖未加载，已回退到静态预览 ${rendererDiagnostics()}`);
    }

    if (state.model && state.modelUrl === renderer.model_url && state.modelKey === modelKey) {
      fitLive2DModel(state, character, scale, positionAnchor);
      onLoading(false);
      onReady(true);
      onError('');
      return;
    }

    const loadToken = state.loadToken + 1;
    state.loadToken = loadToken;
    onLoading(true);
    onReady(false);
    onError('');
    destroyLive2DRenderer(state, { keepApp: true, keepToken: true });

    const app = ensurePixiApp(state, canvas, character);
    const Live2DModelCtor = getLive2DModelCtor();
    if (!Live2DModelCtor || typeof Live2DModelCtor.from !== 'function') {
      throw new Error('Live2DModel.from 不可用');
    }
    const model = await Live2DModelCtor.from(renderer.model_url, { autoInteract: false });
    if (state.loadToken !== loadToken) {
      if (model && typeof model.destroy === 'function') model.destroy();
      return;
    }
    state.model = model;
    state.modelKey = modelKey;
    state.modelUrl = renderer.model_url;
    state.model.interactive = false;
    app.stage.addChild(model);
    fitLive2DModel(state, character, scale, positionAnchor);
    onReady(true);
    onError('');
  } catch (error) {
    destroyLive2DRenderer(state);
    onReady(false);
    onError(`Live2D 模型加载失败，已回退到静态预览\n${formatRendererError(error)}`);
  } finally {
    onLoading(false);
  }
}

function installLive2DRuntimeEnvShim() {
  const globalWindow = window as Live2DGlobalWindow;
  globalWindow.process = globalWindow.process || {};
  globalWindow.process.env = globalWindow.process.env || {};
  if (!globalWindow.process.env.NODE_ENV) globalWindow.process.env.NODE_ENV = 'production';
}

async function ensureLive2DRuntimeScripts() {
  installLive2DRuntimeEnvShim();
  if (rendererAvailable()) {
    configurePixiForElectronLive2D();
    return;
  }
  if (!live2dRuntimePromise) {
    live2dRuntimePromise = loadLive2DRuntimeScripts().catch((error) => {
      live2dRuntimePromise = null;
      throw error;
    });
  }
  await live2dRuntimePromise;
  configurePixiForElectronLive2D();
}

function configurePixiForElectronLive2D() {
  const globalWindow = window as Live2DGlobalWindow;
  const PIXI = globalWindow.PIXI;
  if (!PIXI?.settings) return;
  try {
    PIXI.settings.FAIL_IF_MAJOR_PERFORMANCE_CAVEAT = false;
    if (PIXI.ENV?.WEBGL !== undefined) PIXI.settings.PREFER_ENV = PIXI.ENV.WEBGL;
  } catch {}
}

async function loadLive2DRuntimeScripts() {
  const scripts = await getLive2DRuntimeScripts();
  for (const script of scripts) {
    await loadClassicScript(script);
  }
}

async function getLive2DRuntimeScripts(): Promise<Live2DRuntimeScript[]> {
  try {
    const baseUrl = await bridgeUrl();
    const payload = await apiGet<Live2DRuntimePayload>('/live2d/runtime');
    const scripts = payload.scripts?.length ? payload.scripts : LIVE2D_RUNTIME_CDN_SCRIPTS;
    return scripts.map((script) => ({
      ...script,
      url: resolveLive2DScriptUrl(script.url, baseUrl),
    }));
  } catch {
    return LIVE2D_RUNTIME_CDN_SCRIPTS;
  }
}

function resolveLive2DScriptUrl(value: string, baseUrl: string) {
  if (/^https?:\/\//i.test(value)) return value;
  return new URL(value, `${baseUrl}/`).toString();
}

function loadClassicScript(script: Live2DRuntimeScript) {
  if (document.querySelector(`script[data-hermes-live2d="${script.id}"][data-loaded="1"]`)) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    const node = document.createElement('script');
    node.src = script.url;
    node.async = false;
    node.dataset.hermesLive2d = script.id;
    node.onload = () => {
      node.dataset.loaded = '1';
      resolve();
    };
    node.onerror = () => reject(new Error(`Live2D runtime script failed: ${script.id}`));
    document.head.appendChild(node);
  });
}

function rendererAvailable() {
  const globalWindow = window as Live2DGlobalWindow;
  return Boolean(
    globalWindow.PIXI
      && globalWindow.PIXI.Application
      && globalWindow.PIXI.live2d
      && getLive2DModelCtor()
      && globalWindow.Live2DCubismCore,
  );
}

function getLive2DModelCtor() {
  const globalWindow = window as Live2DGlobalWindow;
  const live2dNamespace = globalWindow.PIXI?.live2d;
  return live2dNamespace?.Live2DModel
    || live2dNamespace?.default?.Live2DModel
    || globalWindow.PIXI?.Live2DModel
    || globalWindow.Live2DModel
    || null;
}

function rendererDiagnostics() {
  const globalWindow = window as Live2DGlobalWindow;
  const diagnostics = {
    hasPixi: Boolean(globalWindow.PIXI),
    hasPixiApplication: Boolean(globalWindow.PIXI?.Application),
    hasPixiLive2D: Boolean(globalWindow.PIXI?.live2d),
    hasLive2DModel: Boolean(getLive2DModelCtor()),
    hasCubismCore: Boolean(globalWindow.Live2DCubismCore),
  };
  return Object.entries(diagnostics)
    .map(([key, value]) => `${key}=${value ? '1' : '0'}`)
    .join(' ');
}

function ensurePixiApp(
  state: Live2DRendererState,
  canvas: HTMLCanvasElement,
  character: HTMLDivElement,
) {
  if (state.app) return state.app;
  const globalWindow = window as Live2DGlobalWindow;
  state.app = new globalWindow.PIXI.Application({
    view: canvas,
    autoStart: true,
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    preserveDrawingBuffer: true,
    resizeTo: character,
    resolution: window.devicePixelRatio || 1,
  });
  return state.app;
}

function fitLive2DModel(
  state: Live2DRendererState,
  character: HTMLDivElement,
  scale?: number,
  positionAnchor: 'left-bottom' | 'right-bottom' | 'custom' = 'custom',
) {
  if (!state.model || !state.app) return;
  const width = Math.max(character.clientWidth, 1);
  const height = Math.max(character.clientHeight, 1);
  state.app.renderer.resize(width, height);
  const bounds = typeof state.model.getLocalBounds === 'function'
    ? state.model.getLocalBounds()
    : { width: 0, height: 0 };
  if (!bounds.width || !bounds.height) return;
  const fitScale = Math.min(width / bounds.width, height / bounds.height) * 0.92;
  const finalScale = fitScale * Math.max(0.4, Math.min(2.0, Number(scale || 1)));
  const horizontalAnchor = positionAnchor === 'left-bottom'
    ? 0
    : positionAnchor === 'right-bottom'
      ? 1
      : 0.5;
  if (state.model.anchor?.set) state.model.anchor.set(horizontalAnchor, 1.0);
  if (state.model.scale?.set) state.model.scale.set(finalScale);
  state.model.x = positionAnchor === 'left-bottom'
    ? 0
    : positionAnchor === 'right-bottom'
      ? width
      : width / 2;
  state.model.y = height;
}

function destroyLive2DRenderer(
  state: Live2DRendererState,
  options: { keepApp?: boolean; keepToken?: boolean } = {},
) {
  if (!options.keepToken) state.loadToken += 1;
  if (state.model && state.app?.stage && typeof state.app.stage.removeChild === 'function') {
    state.app.stage.removeChild(state.model);
  }
  if (state.model && typeof state.model.destroy === 'function') state.model.destroy();
  state.model = undefined;
  state.modelKey = '';
  state.modelUrl = '';
  if (!options.keepApp && state.app && typeof state.app.destroy === 'function') {
    state.app.destroy(false, { children: true, texture: false, baseTexture: false });
  }
  if (!options.keepApp) state.app = undefined;
}

function focusLive2DRenderer(
  state: Live2DRendererState,
  localX: number,
  localY: number,
  immediate: boolean,
) {
  if (!state.model || typeof state.model.focus !== 'function') return;
  try {
    state.model.focus(localX, localY, immediate);
  } catch {}
}

function focusLive2DRendererAtCenter(state: Live2DRendererState, character: HTMLDivElement | null) {
  if (!character) return;
  const rect = character.getBoundingClientRect();
  focusLive2DRenderer(state, rect.width / 2, rect.height * 0.44, true);
}

function setLive2DFocusTargetAtCenter(
  focusStateRef: MutableRefObject<Live2DFocusState>,
  character: HTMLDivElement | null,
  immediate = false,
) {
  if (!character) return;
  const rect = character.getBoundingClientRect();
  setLive2DFocusTarget(focusStateRef, rect.width / 2, rect.height * 0.44, immediate);
}

function setLive2DFocusTargetFromWindowPoint(
  focusStateRef: MutableRefObject<Live2DFocusState>,
  character: HTMLDivElement | null,
  windowX: number,
  windowY: number,
) {
  if (!character) return;
  const rect = character.getBoundingClientRect();
  const paddedX = rect.width * 0.65;
  const paddedY = rect.height * 0.5;
  const localX = clampValue(windowX - rect.left, -paddedX, rect.width + paddedX);
  const localY = clampValue(windowY - rect.top, -paddedY, rect.height + paddedY);
  setLive2DFocusTarget(focusStateRef, localX, localY);
}

function setLive2DFocusTarget(
  focusStateRef: MutableRefObject<Live2DFocusState>,
  localX: number,
  localY: number,
  immediate = false,
) {
  const focusState = focusStateRef.current;
  focusState.targetX = localX;
  focusState.targetY = localY;
  if (!focusState.active || immediate) {
    focusState.currentX = localX;
    focusState.currentY = localY;
    focusState.active = true;
  }
}

function startLive2DFocusLoop(
  state: Live2DRendererState,
  focusStateRef: MutableRefObject<Live2DFocusState>,
) {
  let frame = 0;
  const tick = (timestamp: number) => {
    frame = window.requestAnimationFrame(tick);
    const focusState = focusStateRef.current;
    if (!focusState.active || !state.model) {
      focusState.lastFrameAt = timestamp;
      return;
    }
    const delta = Math.max(1, Math.min(64, timestamp - (focusState.lastFrameAt || timestamp)));
    focusState.lastFrameAt = timestamp;
    const alpha = 1 - Math.exp(-delta / LIVE2D_MOUSE_FOLLOW_SMOOTH_MS);
    const dx = focusState.targetX - focusState.currentX;
    const dy = focusState.targetY - focusState.currentY;
    if (Math.hypot(dx, dy) <= LIVE2D_MOUSE_FOLLOW_DEADZONE_PX) {
      focusState.currentX = focusState.targetX;
      focusState.currentY = focusState.targetY;
      return;
    }
    focusState.currentX += dx * alpha;
    focusState.currentY += dy * alpha;
    focusLive2DRenderer(state, focusState.currentX, focusState.currentY, false);
  };
  frame = window.requestAnimationFrame(tick);
  return () => {
    window.cancelAnimationFrame(frame);
  };
}

function clampValue(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

async function refreshGlobalPointerState({
  character,
  focusState,
  followMouse,
  hitRegion,
  uiRegions,
}: {
  character: HTMLDivElement | null;
  focusState: MutableRefObject<Live2DFocusState>;
  followMouse: boolean;
  hitRegion: Live2DHitRegion | null;
  uiRegions: Live2DHitRegion[];
}) {
  const pointer = await getLauncherPointerState('live2d');
  if (!pointer.ok) return;
  const localX = scaleLauncherPointerCoordinate(Number(pointer.x || 0), Number(pointer.width || 0), window.innerWidth);
  const localY = scaleLauncherPointerCoordinate(Number(pointer.y || 0), Number(pointer.height || 0), window.innerHeight);
  const interactive = Boolean(pointer.inside) && live2dPointerInteractive(localX, localY, hitRegion, uiRegions);
  void setLauncherPointerInteractive('live2d', LIVE2D_POINTER_PASSTHROUGH_ENABLED ? interactive : true);
  if (followMouse) setLive2DFocusTargetFromWindowPoint(focusState, character, localX, localY);
}

function scaleLauncherPointerCoordinate(value: number, sourceSize: number, targetSize: number) {
  if (!Number.isFinite(value)) return 0;
  if (!Number.isFinite(sourceSize) || sourceSize <= 0) return value;
  return value * (Math.max(targetSize || 1, 1) / sourceSize);
}

function startLive2DIdleMotionLoop(
  state: Live2DRendererState,
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'],
) {
  const group = selectLive2DIdleMotionGroup(renderer);
  if (!group) return undefined;
  let stopped = false;
  let timer = 0;
  const run = () => {
    if (stopped) return;
    const motionCount = live2dMotionCount(renderer?.motion_groups?.[group]);
    playLive2DMotion(state, group, motionCount > 0 ? Math.floor(Math.random() * motionCount) : undefined);
    timer = window.setTimeout(run, LIVE2D_IDLE_MOTION_MIN_MS + Math.random() * LIVE2D_IDLE_MOTION_JITTER_MS);
  };
  timer = window.setTimeout(run, LIVE2D_IDLE_MOTION_FIRST_MS);
  return () => {
    stopped = true;
    if (timer) window.clearTimeout(timer);
  };
}

function playLive2DReaction(
  state: Live2DRendererState,
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'],
  text = '',
) {
  const group = selectLive2DIdleMotionGroup(renderer);
  const motionCount = live2dMotionCount(renderer?.motion_groups?.[group]);
  if (group) playLive2DMotion(state, group, motionCount > 0 ? Math.floor(Math.random() * motionCount) : undefined);
  playLive2DStatusExpression(state, renderer, 'message', text);
}

function selectLive2DIdleMotionGroup(renderer: NonNullable<LauncherPayload['launcher']>['renderer']) {
  const configured = String(renderer?.idle_motion_group || 'Idle').trim();
  const groups = renderer?.motion_groups || {};
  const groupNames = Object.keys(groups).filter((group) => live2dMotionCount(groups[group]) > 0);
  if (configured) {
    const exact = groupNames.find((group) => group === configured);
    if (exact) return exact;
    const normalizedConfigured = configured.toLowerCase();
    const caseMatch = groupNames.find((group) => group.toLowerCase() === normalizedConfigured);
    if (caseMatch) return caseMatch;
    if (normalizedConfigured === 'idle' && groupNames.length) return groupNames[0];
    return configured;
  }
  return groupNames[0] || 'Idle';
}

function live2dMotionGroupSignature(groups: NonNullable<NonNullable<LauncherPayload['launcher']>['renderer']>['motion_groups']) {
  return Object.entries(groups || {})
    .map(([group, items]) => `${group}:${(items || []).map((item) => String(item.file || item.File || '')).join(',')}`)
    .sort()
    .join('|');
}

function live2dStringRecordSignature(value: Record<string, string> | undefined) {
  return Object.entries(value || {})
    .map(([key, item]) => `${key}:${item}`)
    .sort()
    .join('|');
}

function live2dMotionCount(items: Array<Record<string, unknown>> | undefined) {
  return Array.isArray(items) ? items.length : 0;
}

function playLive2DStatusExpression(
  state: Live2DRendererState,
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'],
  stateKey: string,
  text = '',
) {
  if (renderer?.enable_expressions !== true) {
    resetLive2DExpression(state);
    return;
  }
  const expressionName = selectLive2DExpression(renderer, stateKey, text);
  if (expressionName) playLive2DExpression(state, expressionName);
  else resetLive2DExpression(state);
}

function selectLive2DExpression(
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'],
  stateKey: string,
  text = '',
) {
  const expressions = renderer?.expressions;
  const items = expressions || [];
  if (!items.length) return '';
  const configured = String(renderer?.expression_mappings?.[stateKey] || '').trim();
  if (configured) {
    const configuredMatch = matchLive2DExpression(items, configured);
    return configuredMatch ? live2dExpressionIdentifier(configuredMatch) : configured;
  }
  if (stateKey === 'thinking' || !String(text || '').trim()) return '';
  const emotionTokens = live2dReplyEmotionTokens(text, stateKey);
  for (const expression of items) {
    const expressionId = live2dExpressionIdentifier(expression);
    const rawRule = String(renderer?.expression_keywords?.[expressionId] || '').trim();
    if (!rawRule) continue;
    if (live2dExpressionRuleMatches(rawRule, text, emotionTokens)) return expressionId;
  }
  return '';
}

function live2dExpressionIdentifier(expression?: { name?: string; file?: string }) {
  return String(expression?.name || expression?.file || '').trim();
}

function matchLive2DExpression(
  expressions: NonNullable<NonNullable<LauncherPayload['launcher']>['renderer']>['expressions'],
  target: string,
) {
  const normalizedTarget = normalizeExpressionToken(target);
  if (!normalizedTarget) return null;
  return (expressions || []).find((expression) => {
    const name = String(expression?.name || '').trim();
    const file = String(expression?.file || '').trim();
    const haystack = `${normalizeExpressionToken(name)} ${normalizeExpressionToken(file)}`;
    return haystack.includes(normalizedTarget);
  }) || null;
}

function normalizeExpressionToken(value: string) {
  return value
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/[_\-\s]+/g, '')
    .toLowerCase();
}

function live2dExpressionRuleMatches(rule: string, text: string, emotionTokens: Set<string>) {
  const normalizedText = normalizeExpressionRuleText(text);
  const tokens = splitExpressionRuleTokens(rule);
  return tokens.some((token) => {
    const normalized = normalizeExpressionRuleText(token);
    return Boolean(normalized && (normalizedText.includes(normalized) || emotionTokens.has(normalized)));
  });
}

function splitExpressionRuleTokens(value: string) {
  return String(value || '')
    .split(/[,，、;；\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeExpressionRuleText(value: string) {
  return String(value || '')
    .replace(/[_\-\s"'“”‘’`~～。.!！?？,，、;；:：()[\]{}<>《》【】]/g, '')
    .toLowerCase();
}

function live2dReplyEmotionTokens(text: string, stateKey: string) {
  const normalized = normalizeExpressionRuleText(text);
  const tokens = new Set<string>();
  const add = (...items: string[]) => {
    items.map(normalizeExpressionRuleText).filter(Boolean).forEach((item) => tokens.add(item));
  };
  if (stateKey === 'failed') add('失败', '错误', '抱歉', '悲伤', '难过', 'sad', 'error', 'failed');
  if (stateKey === 'attention') add('提醒', '注意', '发现', '关怀', 'notice', 'attention');
  if (/(开心|高兴|太好了|好耶|哈哈|嘿嘿|成功|完成|通过|不错|喜欢|漂亮|顺利|可以|ok|success|great|happy|smile|thanks|thank)/i.test(normalized)) {
    add('开心', '高兴', '喜悦', '成功', '笑', 'happy', 'joy', 'smile');
  }
  if (/(抱歉|对不起|不好意思|失败|错误|没办法|无法|遗憾|难过|哭|sad|sorry|failed|error)/i.test(normalized)) {
    add('悲伤', '难过', '失败', '抱歉', 'sad', 'cry', 'sorry', 'failed');
  }
  if (/(惊讶|竟然|真的假的|哇|诶|欸|wow|surprise)/i.test(normalized)) {
    add('惊讶', '意外', 'surprise', 'wow');
  }
  if (/(生气|气死|讨厌|不爽|怒|angry)/i.test(normalized)) {
    add('生气', '愤怒', 'angry');
  }
  if (/(思考|想想|分析|可能|也许|检查|确认|thinking|think)/i.test(normalized)) {
    add('思考', '困惑', 'thinking', 'think');
  }
  return tokens;
}

function playLive2DMotion(state: Live2DRendererState, group: string, index?: number) {
  const model = state.model;
  if (!model || typeof model.motion !== 'function') return;
  try {
    const result = index === undefined ? model.motion(group) : model.motion(group, index);
    if (result && typeof result.catch === 'function') result.catch(() => {});
  } catch {}
}

function playLive2DExpression(state: Live2DRendererState, name: string) {
  const model = state.model;
  if (!model || typeof model.expression !== 'function') return;
  for (const candidate of live2dExpressionCallCandidates(name)) {
    try {
      const result = model.expression(candidate);
      if (result && typeof result.catch === 'function') result.catch(() => {});
    } catch {}
  }
}

function resetLive2DExpression(state: Live2DRendererState) {
  const model = state.model;
  if (!model) return;
  const candidates = [
    model.internalModel?.motionManager?.expressionManager,
    model.internalModel?.motionManager?.expressionManager?.manager,
    model.internalModel?.expressionManager,
  ];
  for (const candidate of candidates) {
    for (const method of ['resetExpression', 'restoreExpression', 'reset', 'stopAllMotions']) {
      try {
        if (candidate && typeof candidate[method] === 'function') {
          candidate[method]();
          return;
        }
      } catch {}
    }
  }
}

function live2dExpressionCallCandidates(name: string) {
  const raw = String(name || '').trim();
  if (!raw) return [];
  const fileName = raw.split(/[\\/]/).pop() || raw;
  const withoutJson = fileName.replace(/\.json$/i, '');
  const withoutExp = withoutJson.replace(/\.exp3$/i, '');
  return Array.from(new Set([raw, fileName, withoutJson, withoutExp].filter(Boolean)));
}

function formatRendererError(error: unknown) {
  const detail = error instanceof Error && error.message ? error.message : String(error || 'unknown error');
  if (/checkMaxIfStatementsInShader|invalid value of ['"`]?0['"`]?/i.test(detail)) {
    return '当前 WebGL 环境没有返回可用的 shader 条件分支上限，已回退静态预览。请重新打开 Live2D；如果只在启用物理时出现，先关闭物理模拟再试。';
  }
  return compactRendererDetail(detail);
}

function compactRendererDetail(value: string, limit = 240) {
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length > limit) return `${text.slice(0, limit - 1)}…`;
  return text || 'unknown error';
}

function reportLive2DRegions({
  canvas,
  character,
  preview,
  quickInput,
  rendererReady,
  reply,
  resourceHint,
  hitRegionRef,
  shapeAppliedRef,
  shapeSignatureRef,
  uiRegionsRef,
}: {
  canvas: HTMLCanvasElement | null;
  character: HTMLDivElement | null;
  preview: HTMLImageElement | null;
  quickInput: HTMLFormElement | null;
  rendererReady: boolean;
  reply: HTMLButtonElement | null;
  resourceHint: HTMLDivElement | null;
  hitRegionRef: MutableRefObject<Live2DHitRegion | null>;
  shapeAppliedRef: MutableRefObject<boolean>;
  shapeSignatureRef: MutableRefObject<string>;
  uiRegionsRef: MutableRefObject<Live2DHitRegion[]>;
}) {
  const canvasRegion = rendererReady && canvas ? live2DCanvasHitRegion(canvas) : null;
  const previewRegion = preview ? live2DPreviewHitRegion(preview) : null;
  const hitRegion = canvasRegion || previewRegion || null;
  positionLive2DReply(reply, hitRegion);
  const uiRegions = [resourceHint, reply, quickInput]
    .map((element) => elementRegion(element))
    .filter((region): region is Live2DHitRegion => Boolean(region));
  hitRegionRef.current = hitRegion;
  uiRegionsRef.current = uiRegions;
  syncLive2DHitRegions(hitRegion, uiRegions, shapeAppliedRef, shapeSignatureRef);
}

function positionLive2DReply(reply: HTMLButtonElement | null, hitRegion: Live2DHitRegion | null) {
  if (!reply || !hitRegion) {
    if (reply) {
      reply.style.left = '';
      reply.style.top = '';
      reply.style.bottom = '';
    }
    return;
  }
  const bounds = normalizedRegionBounds(hitRegion);
  const width = Math.max(reply.offsetWidth || 0, 44);
  const height = Math.max(reply.offsetHeight || 0, 44);
  const viewportWidth = Math.max(window.innerWidth || 1, 1);
  const viewportHeight = Math.max(window.innerHeight || 1, 1);
  const left = clampValue(bounds.left + bounds.width * 0.58, 8, viewportWidth - width - 8);
  const top = clampValue(bounds.top - height * 0.24, 8, viewportHeight - height - 8);
  reply.style.left = `${Math.round(left)}px`;
  reply.style.top = `${Math.round(top)}px`;
  reply.style.bottom = 'auto';
}

function syncLive2DHitRegions(
  hitRegion: Live2DHitRegion | null,
  uiRegions: Live2DHitRegion[],
  shapeAppliedRef: MutableRefObject<boolean>,
  shapeSignatureRef: MutableRefObject<string>,
) {
  const shapeRects = live2dShapeRects(hitRegion, uiRegions);
  const signature = shapeRectSignature(shapeRects);
  if (signature === shapeSignatureRef.current) return;
  shapeSignatureRef.current = signature;
  if (!shapeRects.length) {
    shapeAppliedRef.current = false;
    return;
  }
  void setLauncherHitRegions('live2d', shapeRects).then((applied) => {
    shapeAppliedRef.current = applied;
    if (!applied) shapeSignatureRef.current = '';
  }).catch(() => {
    shapeAppliedRef.current = false;
    shapeSignatureRef.current = '';
  });
}

function live2dShapeRects(
  hitRegion: Live2DHitRegion | null,
  uiRegions: Live2DHitRegion[],
): LauncherHitRegionRect[] {
  const rects = [
    ...(hitRegion ? shapeRectsFromRegion(hitRegion, LIVE2D_SHAPE_PADDING_PX) : []),
    ...uiRegions.flatMap((region) => shapeRectsFromRegion(region, LIVE2D_SHAPE_PADDING_PX)),
  ];
  return mergeVerticalShapeRects(rects).slice(0, LIVE2D_MAX_SHAPE_RECTS);
}

function shapeRectsFromRegion(region: Live2DHitRegion, padding: number): LauncherHitRegionRect[] {
  if (region.kind === 'alpha_mask') return alphaMaskShapeRects(region, padding);
  if (region.kind === 'ellipse') return ellipseShapeRects(region, padding);
  const rect = shapeRectFromNormalizedBounds(normalizedRegionBounds(region), padding);
  return rect ? [rect] : [];
}

function alphaMaskShapeRects(region: Live2DHitRegion, padding: number): LauncherHitRegionRect[] {
  const cols = Math.max(1, Math.round(Number(region.cols || 0)));
  const rows = Math.max(1, Math.round(Number(region.rows || 0)));
  const mask = String(region.mask || '');
  if (mask.length < cols * rows) {
    const rect = shapeRectFromNormalizedBounds(normalizedRegionBounds(region), padding);
    return rect ? [rect] : [];
  }

  const bounds = normalizedRegionBounds(region);
  const shapeCols = Math.min(cols, LIVE2D_SHAPE_MAX_COLS);
  const shapeRows = Math.min(rows, LIVE2D_SHAPE_MAX_ROWS);
  const cellWidth = bounds.width / shapeCols;
  const cellHeight = bounds.height / shapeRows;
  const rects: LauncherHitRegionRect[] = [];
  for (let row = 0; row < shapeRows; row += 1) {
    let col = 0;
    while (col < shapeCols) {
      while (col < shapeCols && !alphaMaskCellHasPixels(mask, cols, rows, shapeCols, shapeRows, col, row)) col += 1;
      if (col >= shapeCols) break;
      const startCol = col;
      while (col < shapeCols && alphaMaskCellHasPixels(mask, cols, rows, shapeCols, shapeRows, col, row)) col += 1;
      const rect = shapeRectFromBounds(
        bounds.left + (startCol * cellWidth),
        bounds.top + (row * cellHeight),
        bounds.left + (col * cellWidth),
        bounds.top + ((row + 1) * cellHeight),
        padding,
      );
      if (rect) rects.push(rect);
    }
  }
  return rects;
}

function alphaMaskCellHasPixels(
  mask: string,
  sourceCols: number,
  sourceRows: number,
  shapeCols: number,
  shapeRows: number,
  shapeCol: number,
  shapeRow: number,
) {
  const startCol = Math.floor((shapeCol / shapeCols) * sourceCols);
  const endCol = Math.min(sourceCols, Math.ceil(((shapeCol + 1) / shapeCols) * sourceCols));
  const startRow = Math.floor((shapeRow / shapeRows) * sourceRows);
  const endRow = Math.min(sourceRows, Math.ceil(((shapeRow + 1) / shapeRows) * sourceRows));
  for (let row = startRow; row < endRow; row += 1) {
    for (let col = startCol; col < endCol; col += 1) {
      if (mask[(row * sourceCols) + col] === '1') return true;
    }
  }
  return false;
}

function ellipseShapeRects(region: Live2DHitRegion, padding: number): LauncherHitRegionRect[] {
  const bounds = normalizedRegionBounds(region);
  const slices = 28;
  const rects: LauncherHitRegionRect[] = [];
  for (let row = 0; row < slices; row += 1) {
    const y = (((row + 0.5) / slices) * 2) - 1;
    const halfWidth = Math.sqrt(Math.max(0, 1 - (y * y))) * (bounds.width / 2);
    const centerX = bounds.left + (bounds.width / 2);
    const rect = shapeRectFromBounds(
      centerX - halfWidth,
      bounds.top + ((row / slices) * bounds.height),
      centerX + halfWidth,
      bounds.top + (((row + 1) / slices) * bounds.height),
      padding,
    );
    if (rect) rects.push(rect);
  }
  return rects;
}

function normalizedRegionBounds(region: Live2DHitRegion) {
  const viewportWidth = Math.max(window.innerWidth || 1, 1);
  const viewportHeight = Math.max(window.innerHeight || 1, 1);
  const left = Number(region.x || 0) * viewportWidth;
  const top = Number(region.y || 0) * viewportHeight;
  const width = Number(region.width || 0) * viewportWidth;
  const height = Number(region.height || 0) * viewportHeight;
  return { left, top, width, height, right: left + width, bottom: top + height };
}

function shapeRectFromNormalizedBounds(bounds: ReturnType<typeof normalizedRegionBounds>, padding: number) {
  return shapeRectFromBounds(bounds.left, bounds.top, bounds.right, bounds.bottom, padding);
}

function shapeRectFromBounds(
  left: number,
  top: number,
  right: number,
  bottom: number,
  padding: number,
): LauncherHitRegionRect | null {
  const viewportWidth = Math.max(window.innerWidth || 1, 1);
  const viewportHeight = Math.max(window.innerHeight || 1, 1);
  const x1 = Math.max(0, Math.floor(left - padding));
  const y1 = Math.max(0, Math.floor(top - padding));
  const x2 = Math.min(viewportWidth, Math.ceil(right + padding));
  const y2 = Math.min(viewportHeight, Math.ceil(bottom + padding));
  if (x2 <= x1 || y2 <= y1) return null;
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

function mergeVerticalShapeRects(rects: LauncherHitRegionRect[]) {
  const merged: LauncherHitRegionRect[] = [];
  const activeByColumn = new Map<string, LauncherHitRegionRect>();
  [...rects]
    .sort((left, right) => (left.y - right.y) || (left.x - right.x) || (left.width - right.width))
    .forEach((rect) => {
      const key = `${rect.x}:${rect.width}`;
      const active = activeByColumn.get(key);
      if (active && rect.y <= active.y + active.height + 1) {
        const bottom = Math.max(active.y + active.height, rect.y + rect.height);
        active.height = bottom - active.y;
        return;
      }
      const next = { ...rect };
      activeByColumn.set(key, next);
      merged.push(next);
    });
  return merged;
}

function shapeRectSignature(rects: LauncherHitRegionRect[]) {
  let hash = 2166136261;
  for (const rect of rects) {
    hash = hashShapeNumber(hash, rect.x);
    hash = hashShapeNumber(hash, rect.y);
    hash = hashShapeNumber(hash, rect.width);
    hash = hashShapeNumber(hash, rect.height);
  }
  return `${window.innerWidth}x${window.innerHeight}:${rects.length}:${hash >>> 0}`;
}

function hashShapeNumber(hash: number, value: number) {
  return Math.imul(hash ^ Math.round(value), 16777619);
}

function live2DCanvasHitRegion(canvas: HTMLCanvasElement) {
  const rect = canvas.getBoundingClientRect();
  return buildAlphaMaskRegion({
    rect,
    draw: (context, cols, rows) => {
      context.drawImage(canvas, 0, 0, Math.max(1, canvas.width), Math.max(1, canvas.height), 0, 0, cols, rows);
    },
  });
}

function live2DPreviewHitRegion(preview: HTMLImageElement) {
  const rect = containedImageRect(preview);
  return buildAlphaMaskRegion({
    rect,
    draw: (context, cols, rows) => {
      const naturalWidth = Number(preview.naturalWidth || cols || 1);
      const naturalHeight = Number(preview.naturalHeight || rows || 1);
      context.drawImage(preview, 0, 0, naturalWidth, naturalHeight, 0, 0, cols, rows);
    },
  });
}

function elementRegion(element: Element | null) {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 1 || rect.height <= 1) return null;
  return normalizedRegionFromRect(rect, 'rect');
}

function normalizedRegionFromRect(rect: DOMRect, kind: Live2DHitRegion['kind']): Live2DHitRegion {
  const viewportWidth = Math.max(window.innerWidth || 1, 1);
  const viewportHeight = Math.max(window.innerHeight || 1, 1);
  return {
    kind,
    x: rect.left / viewportWidth,
    y: rect.top / viewportHeight,
    width: rect.width / viewportWidth,
    height: rect.height / viewportHeight,
  };
}

function containedImageRect(image: HTMLImageElement): DOMRect {
  const rect = image.getBoundingClientRect();
  const naturalWidth = Number(image.naturalWidth || rect.width || 1);
  const naturalHeight = Number(image.naturalHeight || rect.height || 1);
  const scale = Math.min(rect.width / naturalWidth, rect.height / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  const objectPosition = window.getComputedStyle(image).objectPosition || 'center bottom';
  const alignX = objectPosition.includes('left')
    ? 0
    : objectPosition.includes('right')
      ? 1
      : 0.5;
  const alignY = objectPosition.includes('top')
    ? 0
    : objectPosition.includes('bottom')
      ? 1
      : 0.5;
  return DOMRect.fromRect({
    x: rect.left + (rect.width - width) * alignX,
    y: rect.top + (rect.height - height) * alignY,
    width,
    height,
  });
}

function buildAlphaMaskRegion({
  rect,
  draw,
}: {
  rect: DOMRect;
  draw: (context: CanvasRenderingContext2D, cols: number, rows: number) => void;
}): Live2DHitRegion | null {
  try {
    if (rect.width <= 1 || rect.height <= 1) return null;
    const { cols, rows } = alphaMaskGridSize(rect);
    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = cols;
    maskCanvas.height = rows;
    const context = maskCanvas.getContext('2d', { willReadFrequently: true });
    if (!context) return null;
    context.clearRect(0, 0, cols, rows);
    draw(context, cols, rows);
    const imageData = context.getImageData(0, 0, cols, rows).data;
    const bits = new Array<string>(cols * rows).fill('0');
    let fillCount = 0;
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const alpha = imageData[((row * cols) + col) * 4 + 3];
        if (alpha >= 28) {
          bits[(row * cols) + col] = '1';
          fillCount += 1;
        }
      }
    }
    if (fillCount <= 0) return null;
    if (fillCount / (cols * rows) > LIVE2D_MASK_MAX_FILL_RATIO) return null;
    return trimMaskRegion(expandMaskBits(bits, cols, rows, 1), cols, rows, rect);
  } catch {
    return null;
  }
}

function alphaMaskGridSize(rect: DOMRect) {
  const cols = Math.max(48, Math.min(160, Math.round(rect.width / 3)));
  const rows = Math.max(56, Math.min(224, Math.round((rect.height / Math.max(rect.width, 1)) * cols)));
  return { cols, rows };
}

function expandMaskBits(maskBits: string[], cols: number, rows: number, radius: number) {
  if (radius <= 0) return maskBits;
  const expanded = [...maskBits];
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      if (maskBits[(row * cols) + col] !== '1') continue;
      for (let dy = -radius; dy <= radius; dy += 1) {
        for (let dx = -radius; dx <= radius; dx += 1) {
          const nextCol = col + dx;
          const nextRow = row + dy;
          if (nextCol < 0 || nextRow < 0 || nextCol >= cols || nextRow >= rows) continue;
          expanded[(nextRow * cols) + nextCol] = '1';
        }
      }
    }
  }
  return expanded;
}

function trimMaskRegion(maskBits: string[], cols: number, rows: number, rect: DOMRect) {
  let minCol = cols;
  let minRow = rows;
  let maxCol = -1;
  let maxRow = -1;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      if (maskBits[(row * cols) + col] !== '1') continue;
      if (col < minCol) minCol = col;
      if (row < minRow) minRow = row;
      if (col > maxCol) maxCol = col;
      if (row > maxRow) maxRow = row;
    }
  }
  if (maxCol < minCol || maxRow < minRow) return null;

  const cellWidth = rect.width / cols;
  const cellHeight = rect.height / rows;
  let trimmedMask = '';
  for (let row = minRow; row <= maxRow; row += 1) {
    for (let col = minCol; col <= maxCol; col += 1) {
      trimmedMask += maskBits[(row * cols) + col];
    }
  }
  const viewportWidth = Math.max(window.innerWidth || 1, 1);
  const viewportHeight = Math.max(window.innerHeight || 1, 1);
  return {
    kind: 'alpha_mask' as const,
    x: (rect.left + (minCol * cellWidth)) / viewportWidth,
    y: (rect.top + (minRow * cellHeight)) / viewportHeight,
    width: ((maxCol - minCol + 1) * cellWidth) / viewportWidth,
    height: ((maxRow - minRow + 1) * cellHeight) / viewportHeight,
    cols: maxCol - minCol + 1,
    rows: maxRow - minRow + 1,
    mask: trimmedMask,
  };
}

function live2dPointerInteractive(
  localX: number,
  localY: number,
  hitRegion: Live2DHitRegion | null,
  uiRegions: Live2DHitRegion[],
) {
  for (const region of uiRegions) {
    if (hitRegionContainsLocalPoint(region, localX, localY)) return true;
  }
  if (!hitRegion) return false;
  return hitRegionContainsLocalPoint(hitRegion, localX, localY);
}

function hitRegionContainsLocalPoint(region: Live2DHitRegion, localX: number, localY: number) {
  const viewportWidth = Math.max(window.innerWidth || 1, 1);
  const viewportHeight = Math.max(window.innerHeight || 1, 1);
  const left = Number(region.x || 0) * viewportWidth;
  const top = Number(region.y || 0) * viewportHeight;
  const width = Number(region.width || 0) * viewportWidth;
  const height = Number(region.height || 0) * viewportHeight;
  if (width <= 0 || height <= 0) return false;
  if (localX < left || localX > left + width || localY < top || localY > top + height) return false;

  if (region.kind === 'alpha_mask') {
    const cols = Math.max(1, Number(region.cols || 0));
    const rows = Math.max(1, Number(region.rows || 0));
    const mask = String(region.mask || '');
    if (mask.length < cols * rows) return false;
    const relX = (localX - left) / width;
    const relY = (localY - top) / height;
    const col = Math.min(cols - 1, Math.max(0, Math.floor(relX * cols)));
    const row = Math.min(rows - 1, Math.max(0, Math.floor(relY * rows)));
    return mask[(row * cols) + col] === '1';
  }

  if (region.kind === 'rect') return true;
  const centerX = left + (width / 2);
  const centerY = top + (height / 2);
  const radiusX = width / 2;
  const radiusY = height / 2;
  if (radiusX <= 0 || radiusY <= 0) return false;
  const normalizedX = (localX - centerX) / radiusX;
  const normalizedY = (localY - centerY) / radiusY;
  return (normalizedX * normalizedX) + (normalizedY * normalizedY) <= 1;
}
