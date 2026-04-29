import { CSSProperties, FormEvent, MouseEvent, PointerEvent, useCallback, useEffect, useRef, useState, type MutableRefObject } from 'react';

import { apiGet, apiPost, bridgeUrl, moveLauncherWindow, openAppView, openLauncherMenu, setLauncherPointerInteractive } from '../lib/bridge';
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
  proactive?: {
    enabled?: boolean;
    has_attention?: boolean;
    message?: string;
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
    preview_url?: string;
    scale?: number;
    mouse_follow_enabled?: boolean;
    renderer?: {
      enabled?: boolean;
      model_url?: string;
      reason?: string;
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
const LIVE2D_POINTER_PASSTHROUGH_ENABLED = false;

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
  modelUrl?: string;
  loadToken: number;
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
  try {
    await apiPost('/ui/launcher/ack', { mode });
  } catch {}
  await openAppView('chat');
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
  const hasAttention = showDot && Boolean(launcher.has_attention);
  const unreadStatus = String(data?.notification?.latest_message?.status || '');
  const dotClass = bubbleDotClass(showDot, hasAttention, status, unreadStatus);
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
        className={`bubble-launcher ${hasAttention ? 'has-unread' : ''} ${idleHidden ? 'auto-hidden' : ''}`}
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

function bubbleDotClass(showDot: boolean, hasAttention: boolean, status: string, unreadStatus: string) {
  let className = 'status-dot';
  if (hasAttention) {
    if (unreadStatus === 'failed') className += ' visible failed';
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
  if (proactive.error) titleParts.push(`主动对话：${proactive.error}`);
  else if (proactive.has_attention) titleParts.push('主动对话：有新的观察结果');
  else if (proactive.enabled && proactive.message) titleParts.push(`主动对话：${proactive.message}`);
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
  const dragStateRef = useRef<LauncherDragState | null>(null);
  const clickSuppressedRef = useRef(false);
  const hitRegionRef = useRef<Live2DHitRegion | null>(null);
  const uiRegionsRef = useRef<Live2DHitRegion[]>([]);
  const rendererStateRef = useRef<Live2DRendererState>({ loadToken: 0 });
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
  const resource = launcher.resource;
  const renderer = launcher.renderer;
  const replyText = proactiveAttention
    ? (data?.proactive?.message || '有新的主动桌面观察结果')
    : data?.chat?.is_processing
      ? '正在思考回复...'
      : hasAttention
        ? latestReply
        : '';
  const showReply = Boolean(launcher.show_reply_bubble !== false && !replyHidden && replyText);
  const stageTitle = live2dStageTitle(resource, launcher, data, hasAttention, proactiveAttention);
  const characterClass = live2dCharacterClass(data, hasAttention, String(data?.notification?.latest_message?.status || ''));
  const hintKey = [resource?.state || '', resource?.status_label || '', resource?.help_text || '', resource?.renderer_entry || ''].join('|');
  const showResourceHint = Boolean(resource && hintKey !== dismissedHintKey);
  const hintTone = resource?.state === 'path_valid' || resource?.state === 'loaded' ? 'ok' : 'warn';
  const previewStyle = {
    '--live2d-preview-scale': String(Math.max(0.4, Math.min(2.0, Number(launcher.scale || 1)))),
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
  }, [renderer?.enabled, renderer?.model_url, renderer?.reason, launcher.scale]);

  useEffect(() => {
    const rendererState = rendererStateRef.current;
    return () => {
      destroyLive2DRenderer(rendererState);
      void setLauncherPointerInteractive('live2d', true);
    };
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      reportLive2DRegions({
        canvas: canvasRef.current,
        character: characterRef.current,
        preview: previewRef.current,
        quickInput: quickInputRef.current,
        rendererReady,
        reply: replyRef.current,
        resourceHint: resourceHintRef.current,
        hitRegionRef,
        uiRegionsRef,
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [rendererReady, rendererLoading, launcher.preview_url, showReply, quickInputVisible, showResourceHint, dismissedHintKey]);

  function handleWindowPointerDown(event: PointerEvent<HTMLElement>) {
    if (event.button === 2 || live2dInteractiveTarget(event.target)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = newDragState(event);
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
      focusLive2DRenderer(rendererStateRef.current, event.clientX, event.clientY, false);
    }
  }

  function handleWindowPointerUp(event: PointerEvent<HTMLElement>) {
    if (dragStateRef.current?.dragging || pointerMovedPastThreshold(event, dragStateRef.current)) {
      clickSuppressedRef.current = true;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragStateRef.current = null;
  }

  function handleWindowPointerCancel() {
    dragStateRef.current = null;
    clickSuppressedRef.current = false;
  }

  function handleWindowPointerLeave() {
    if (LIVE2D_POINTER_PASSTHROUGH_ENABLED) void setLauncherPointerInteractive('live2d', false);
    if (launcher.mouse_follow_enabled === false) return;
    focusLive2DRendererAtCenter(rendererStateRef.current, characterRef.current);
  }

  async function handleStageClick() {
    if (clickSuppressedRef.current) {
      clickSuppressedRef.current = false;
      return;
    }
    if (launcher.click_action === 'toggle_reply') {
      setReplyHidden((value) => !value);
      try {
        await apiPost('/ui/launcher/ack', { mode: 'live2d' });
      } catch {}
      return;
    }
    if (launcher.click_action === 'focus_stage') {
      return;
    }
    await acknowledgeAndOpenChat('live2d');
  }

  async function sendQuickMessage(event: FormEvent) {
    event.preventDefault();
    const text = quickText.trim();
    if (!text) return;
    setQuickText('');
    await apiPost('/ui/launcher/quick-message', { text });
    setReplyHidden(false);
    setQuickInputVisible(false);
    await refresh();
  }

  return (
    <main
      className="launcher-shell live2d-shell"
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
        onClick={() => void handleStageClick()}
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
              style={previewStyle}
              onLoad={() => reportLive2DRegions({
                canvas: canvasRef.current,
                character: characterRef.current,
                preview: previewRef.current,
                quickInput: quickInputRef.current,
                rendererReady,
                reply: replyRef.current,
                resourceHint: resourceHintRef.current,
                hitRegionRef,
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
        <button ref={replyRef} className={`live2d-reply ${proactiveAttention ? 'proactive' : ''} ${hasAttention ? 'attention' : ''}`} type="button" onClick={() => setReplyHidden(true)}>
          {replyText}
        </button>
      ) : null}

      {launcher.enable_quick_input !== false && quickInputVisible ? (
        <form ref={quickInputRef} className="live2d-quick-input" onSubmit={sendQuickMessage} onClick={(event) => event.stopPropagation()}>
          <input value={quickText} onChange={(event) => setQuickText(event.target.value)} placeholder="和八千代说点什么…" />
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

function live2dCharacterClass(data: LauncherPayload | null, hasAttention: boolean, unreadStatus: string) {
  const classes = ['live2d-character'];
  if (data?.chat?.is_processing) classes.push('processing');
  else if (hasAttention && unreadStatus === 'failed') classes.push('failed');
  else if (hasAttention) classes.push('has-message');
  return classes.join(' ');
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

async function ensureLive2DRenderer({
  canvas,
  character,
  renderer,
  scale,
  state,
  onError,
  onLoading,
  onReady,
}: {
  canvas: HTMLCanvasElement | null;
  character: HTMLDivElement | null;
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'];
  scale?: number;
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

  try {
    await ensureLive2DRuntimeScripts();
    if (!rendererAvailable()) {
      throw new Error(`Live2D 渲染依赖未加载，已回退到静态预览 ${rendererDiagnostics()}`);
    }

    if (state.model && state.modelUrl === renderer.model_url) {
      fitLive2DModel(state, character, scale);
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
    destroyLive2DRenderer(state, { keepToken: true });

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
    state.modelUrl = renderer.model_url;
    state.model.interactive = false;
    app.stage.addChild(model);
    fitLive2DModel(state, character, scale);
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
  if (rendererAvailable()) return;
  if (!live2dRuntimePromise) {
    live2dRuntimePromise = loadLive2DRuntimeScripts().catch((error) => {
      live2dRuntimePromise = null;
      throw error;
    });
  }
  await live2dRuntimePromise;
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
    resizeTo: character,
    resolution: window.devicePixelRatio || 1,
  });
  return state.app;
}

function fitLive2DModel(
  state: Live2DRendererState,
  character: HTMLDivElement,
  scale?: number,
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
  if (state.model.anchor?.set) state.model.anchor.set(0.5, 1.0);
  if (state.model.scale?.set) state.model.scale.set(finalScale);
  state.model.x = width / 2;
  state.model.y = height - 6;
}

function destroyLive2DRenderer(
  state: Live2DRendererState,
  options: { keepToken?: boolean } = {},
) {
  if (!options.keepToken) state.loadToken += 1;
  if (state.model && state.app?.stage && typeof state.app.stage.removeChild === 'function') {
    state.app.stage.removeChild(state.model);
  }
  if (state.model && typeof state.model.destroy === 'function') state.model.destroy();
  state.model = undefined;
  state.modelUrl = '';
  if (state.app && typeof state.app.destroy === 'function') {
    state.app.destroy(false, { children: true, texture: false, baseTexture: false });
  }
  state.app = undefined;
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

function formatRendererError(error: unknown) {
  if (error instanceof Error && error.message) return compactRendererDetail(error.message);
  return compactRendererDetail(String(error || 'unknown error'));
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
  uiRegionsRef: MutableRefObject<Live2DHitRegion[]>;
}) {
  const hitRegion = rendererReady && canvas
    ? live2DCanvasHitRegion(canvas)
    : preview
      ? live2DPreviewHitRegion(preview)
      : character
        ? normalizedRegionFromRect(character.getBoundingClientRect(), 'live2d')
        : null;
  hitRegionRef.current = hitRegion;
  uiRegionsRef.current = [resourceHint, reply, quickInput]
    .map((element) => elementRegion(element))
    .filter((region): region is Live2DHitRegion => Boolean(region));
}

function live2DCanvasHitRegion(canvas: HTMLCanvasElement) {
  const rect = canvas.getBoundingClientRect();
  return buildAlphaMaskRegion({
    rect,
    draw: (context, cols, rows) => {
      context.drawImage(canvas, 0, 0, Math.max(1, canvas.width), Math.max(1, canvas.height), 0, 0, cols, rows);
    },
  }) || normalizedRegionFromRect(rect, 'live2d');
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
  }) || normalizedRegionFromRect(rect, 'live2d');
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
  return DOMRect.fromRect({
    x: rect.left + (rect.width - width) / 2,
    y: rect.top + (rect.height - height) / 2,
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
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const alpha = imageData[((row * cols) + col) * 4 + 3];
        if (alpha >= 48) bits[(row * cols) + col] = '1';
      }
    }
    return trimMaskRegion(bits, cols, rows, rect);
  } catch {
    return null;
  }
}

function alphaMaskGridSize(rect: DOMRect) {
  const cols = Math.max(24, Math.min(96, Math.round(rect.width / 8)));
  const rows = Math.max(28, Math.min(128, Math.round((rect.height / Math.max(rect.width, 1)) * cols)));
  return { cols, rows };
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
  if (!hitRegion) return true;
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
