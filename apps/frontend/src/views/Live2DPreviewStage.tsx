import { useEffect, useRef, useState, type CSSProperties } from 'react';

import { apiGet, bridgeUrl } from '../lib/bridge';
import type { LauncherPayload } from './launcherTypes';

export const LIVE2D_DEFAULT_RENDER_FPS = 24;
const LIVE2D_DEFAULT_RENDER_RESOLUTION = 1.25;

export type Live2DPositionAnchor = 'left-bottom' | 'right-bottom' | 'custom';

export type Live2DRenderSettings = {
  fps: number;
  resolution: number;
  hitRegionPrecision: 'low' | 'medium' | 'high';
};

export type Live2DRendererState = {
  app?: any;
  model?: any;
  modelKey?: string;
  modelUrl?: string;
  loadToken: number;
};

type Live2DGlobalWindow = typeof window & {
  PIXI?: any;
  Live2DCubismCore?: unknown;
  Live2DModel?: any;
  process?: { env?: Record<string, string> };
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

const LIVE2D_RUNTIME_CDN_SCRIPTS: Live2DRuntimeScript[] = [
  { id: 'pixi_js', source: 'cdn', url: 'https://cdn.jsdelivr.net/npm/pixi.js@6/dist/browser/pixi.min.js' },
  { id: 'live2d_cubism_core', source: 'cdn', url: 'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js' },
  { id: 'pixi_live2d_display', source: 'cdn', url: 'https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta/dist/cubism4.min.js' },
];

let live2dRuntimePromise: Promise<void> | null = null;

const live2DPreviewModelWarmCache = new Set<string>();

export function live2DPreviewModelIsWarm(modelUrl?: string): boolean {
  return Boolean(modelUrl && live2DPreviewModelWarmCache.has(modelUrl));
}

export function markLive2DPreviewModelWarm(modelUrl?: string) {
  if (modelUrl) live2DPreviewModelWarmCache.add(modelUrl);
}

export function normalizeLive2DPositionAnchor(value: unknown): Live2DPositionAnchor {
  if (value === 'left_bottom') return 'left-bottom';
  if (value === 'custom') return 'custom';
  return 'right-bottom';
}

export function live2dObjectPosition(anchor: Live2DPositionAnchor) {
  if (anchor === 'left-bottom') return 'left bottom';
  if (anchor === 'right-bottom') return 'right bottom';
  return 'center bottom';
}

export function live2dTransformOrigin(anchor: Live2DPositionAnchor) {
  if (anchor === 'left-bottom') return 'left bottom';
  if (anchor === 'right-bottom') return 'right bottom';
  return 'center bottom';
}

export function live2dRenderSettings(
  launcher: NonNullable<LauncherPayload['launcher']>,
): Live2DRenderSettings {
  const preset = String(launcher.render_quality_preset || 'balanced');
  const presetValues: Record<string, Live2DRenderSettings> = {
    battery: { fps: 15, resolution: 0.75, hitRegionPrecision: 'low' },
    balanced: { fps: 24, resolution: 1.25, hitRegionPrecision: 'medium' },
    quality: { fps: 30, resolution: 1.5, hitRegionPrecision: 'high' },
  };
  if (preset !== 'custom' && presetValues[preset]) return presetValues[preset];
  return {
    fps: clampInteger(Number(launcher.render_fps || LIVE2D_DEFAULT_RENDER_FPS), 12, 60),
    resolution: clampValue(Number(launcher.render_resolution || LIVE2D_DEFAULT_RENDER_RESOLUTION), 0.5, 2.0),
    hitRegionPrecision: live2dHitRegionPrecision(launcher.hit_region_precision),
  };
}

export async function ensureLive2DRenderer({
  canvas,
  character,
  renderSettings,
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
  renderSettings: Live2DRenderSettings;
  renderer: NonNullable<LauncherPayload['launcher']>['renderer'];
  scale?: number;
  positionAnchor: Live2DPositionAnchor;
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
  const modelKey = [
    renderer.model_url,
    `physics:${renderer.enable_physics === true ? '1' : '0'}`,
    `fps:${renderSettings.fps}`,
    `resolution:${renderSettings.resolution}`,
  ].join('|');

  try {
    await ensureLive2DRuntimeScripts(renderSettings.fps);
    if (!rendererAvailable()) {
      throw new Error(`Live2D 渲染依赖未加载，已回退到静态预览 ${rendererDiagnostics()}`);
    }

    if (state.model && state.modelUrl === renderer.model_url && state.modelKey === modelKey) {
      fitLive2DModel(state, character, scale, positionAnchor);
      markLive2DPreviewModelWarm(renderer.model_url);
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

    const app = ensurePixiApp(state, canvas, character, renderSettings);
    const Live2DModelCtor = getLive2DModelCtor();
    if (!Live2DModelCtor || typeof Live2DModelCtor.from !== 'function') {
      throw new Error('Live2DModel.from 不可用');
    }
    const model = await Live2DModelCtor.from(renderer.model_url, { autoFocus: false, autoHitTest: false });
    if (state.loadToken !== loadToken) {
      if (model && typeof model.destroy === 'function') model.destroy();
      return;
    }
    state.model = model;
    state.modelKey = modelKey;
    state.modelUrl = renderer.model_url;
    markLive2DPreviewModelWarm(renderer.model_url);
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

export function fitLive2DModel(
  state: Live2DRendererState,
  character: HTMLDivElement,
  scale?: number,
  positionAnchor: Live2DPositionAnchor = 'custom',
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

export function fitLive2DPreviewModel(
  state: Live2DRendererState,
  character: HTMLDivElement | null,
  positionAnchor: Live2DPositionAnchor,
  scale = 1,
) {
  if (!state.model || !state.app || !character) return;
  fitLive2DModel(state, character, scale, positionAnchor);
  try {
    state.app.renderer.render(state.app.stage);
  } catch {}
}

export function destroyLive2DRenderer(
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

export function Live2DPreviewStage({ active = true, data }: { active?: boolean; data: LauncherPayload | null }) {
  const launcher = data?.launcher || {};
  const renderer = launcher.renderer;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const characterRef = useRef<HTMLDivElement | null>(null);
  const rendererStateRef = useRef<Live2DRendererState>({ loadToken: 0 });
  const [rendererLoading, setRendererLoading] = useState(false);
  const [rendererReady, setRendererReady] = useState(false);
  const [rendererError, setRendererError] = useState('');
  const positionAnchor = normalizeLive2DPositionAnchor(launcher.position_anchor);
  const renderSettings = live2dRenderSettings(launcher);
  const previewRenderSettings = {
    ...renderSettings,
    resolution: Math.max(renderSettings.resolution, 2),
  };
  const previewRendererScale = 1;
  const previewStyle = {
    '--live2d-object-position': live2dObjectPosition(positionAnchor),
    '--live2d-transform-origin': live2dTransformOrigin(positionAnchor),
  } as CSSProperties;

  useEffect(() => {
    let disposed = false;
    void ensureLive2DRenderer({
      canvas: canvasRef.current,
      character: characterRef.current,
      renderer,
      renderSettings: previewRenderSettings,
      scale: previewRendererScale,
      positionAnchor,
      state: rendererStateRef.current,
      onError: (value) => {
        if (!disposed) setRendererError(value);
      },
      onLoading: (value) => {
        if (!disposed) setRendererLoading(value && !live2DPreviewModelIsWarm(renderer?.model_url));
      },
      onReady: (value) => {
        if (!disposed) setRendererReady(value);
      },
    });
    return () => {
      disposed = true;
    };
  }, [renderer?.enabled, renderer?.model_url, renderer?.reason, renderer?.enable_physics, launcher.scale, positionAnchor, previewRenderSettings.fps, previewRenderSettings.resolution]);

  useEffect(() => {
    const rendererState = rendererStateRef.current;
    return () => destroyLive2DRenderer(rendererState);
  }, []);

  useEffect(() => {
    if (!active || !rendererReady) return;
    let frame = 0;
    const updatePreviewFit = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        fitLive2DPreviewModel(rendererStateRef.current, characterRef.current, positionAnchor, previewRendererScale);
      });
    };
    updatePreviewFit();
    const timers = [120, 360, 820].map((delay) => window.setTimeout(updatePreviewFit, delay));
    window.addEventListener('resize', updatePreviewFit);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      timers.forEach((timer) => window.clearTimeout(timer));
      window.removeEventListener('resize', updatePreviewFit);
    };
  }, [active, rendererReady, renderer?.model_url, positionAnchor, previewRenderSettings.resolution, previewRendererScale]);

  return (
    <div className="live2d-stage live2d-preview-stage" style={previewStyle} aria-label="Live2D 模型预览">
      <div ref={characterRef} className={`live2d-character ${rendererReady ? 'renderer-ready' : ''}`}>
        <canvas ref={canvasRef} className={`live2d-canvas ${rendererReady ? 'active' : ''}`} aria-hidden="true" />
        {launcher.preview_url ? (
          <img
            className={`live2d-preview-fallback ${rendererReady ? 'hidden' : ''}`}
            src={launcher.preview_url}
            alt=""
          />
        ) : null}
      </div>
      {rendererLoading ? <div className="live2d-loading">Live2D 模型加载中...</div> : null}
      {rendererError || (!rendererReady ? renderer?.reason : '') ? (
        <div className="live2d-error">{rendererError || renderer?.reason || 'Live2D 模型暂不可预览'}</div>
      ) : null}
    </div>
  );
}

function live2dHitRegionPrecision(value: unknown): Live2DRenderSettings['hitRegionPrecision'] {
  return value === 'low' || value === 'high' ? value : 'medium';
}

function clampInteger(value: number, min: number, max: number) {
  return Math.round(clampValue(Number.isFinite(value) ? value : min, min, max));
}

function clampValue(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function installLive2DRuntimeEnvShim() {
  const globalWindow = window as Live2DGlobalWindow;
  globalWindow.process = globalWindow.process || {};
  globalWindow.process.env = globalWindow.process.env || {};
  if (!globalWindow.process.env.NODE_ENV) globalWindow.process.env.NODE_ENV = 'production';
}

async function ensureLive2DRuntimeScripts(renderFps = LIVE2D_DEFAULT_RENDER_FPS) {
  installLive2DRuntimeEnvShim();
  if (rendererAvailable()) {
    configurePixiForElectronLive2D(renderFps);
    return;
  }
  if (!live2dRuntimePromise) {
    live2dRuntimePromise = loadLive2DRuntimeScripts().catch((error) => {
      live2dRuntimePromise = null;
      throw error;
    });
  }
  await live2dRuntimePromise;
  configurePixiForElectronLive2D(renderFps);
}

function configurePixiForElectronLive2D(renderFps = LIVE2D_DEFAULT_RENDER_FPS) {
  const globalWindow = window as Live2DGlobalWindow;
  const PIXI = globalWindow.PIXI;
  if (!PIXI?.settings) return;
  try {
    PIXI.settings.FAIL_IF_MAJOR_PERFORMANCE_CAVEAT = false;
    if (PIXI.ENV?.WEBGL !== undefined) PIXI.settings.PREFER_ENV = PIXI.ENV.WEBGL;
  } catch {}
  try {
    if (PIXI.Ticker?.shared) {
      PIXI.Ticker.shared.maxFPS = renderFps;
      PIXI.Ticker.shared.minFPS = 0;
    }
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
  renderSettings: Live2DRenderSettings,
) {
  if (state.app) {
    configureTransparentPixiRenderer(state.app, canvas, renderSettings.fps);
    return state.app;
  }
  const globalWindow = window as Live2DGlobalWindow;
  state.app = new globalWindow.PIXI.Application({
    view: canvas,
    autoStart: true,
    transparent: true,
    backgroundAlpha: 0,
    backgroundColor: 0x000000,
    antialias: false,
    autoDensity: true,
    clearBeforeRender: true,
    preserveDrawingBuffer: false,
    resizeTo: character,
    resolution: clampValue(renderSettings.resolution, 0.5, 2.0),
    useContextAlpha: true,
  });
  configureTransparentPixiRenderer(state.app, canvas, renderSettings.fps);
  return state.app;
}

function configureTransparentPixiRenderer(app: any, canvas: HTMLCanvasElement, renderFps = LIVE2D_DEFAULT_RENDER_FPS) {
  canvas.style.background = 'transparent';
  try {
    app.renderer.background.alpha = 0;
  } catch {}
  try {
    app.renderer.backgroundColor = 0x000000;
  } catch {}
  try {
    app.renderer.transparent = true;
  } catch {}
  try {
    app.renderer.gl.clearColor(0, 0, 0, 0);
    app.renderer.gl.clear(app.renderer.gl.COLOR_BUFFER_BIT);
  } catch {}
  try {
    app.ticker.maxFPS = renderFps;
    app.ticker.minFPS = 0;
  } catch {}
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
  if (text.length > limit) return `${text.slice(0, limit - 1)}...`;
  return text || 'unknown error';
}
