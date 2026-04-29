import { currentView, routePath, type AppView } from './view';

export type ApiRecord = Record<string, unknown>;
export type LauncherHitRegionRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};
export type LauncherHitRegionPayload = {
  regions: LauncherHitRegionRect[];
  viewport: {
    width: number;
    height: number;
  };
};

declare global {
  interface Window {
    hermesDesktop?: {
      chooseLive2DArchive?: () => Promise<string | null>;
      chooseLive2DModelDirectory?: () => Promise<string | null>;
      copyText?: (text: string) => Promise<void>;
      getBridgeUrl: () => Promise<string>;
      getLauncherPointerState?: (mode: string) => Promise<{ ok?: boolean; x?: number; y?: number; width?: number; height?: number; inside?: boolean; updated_at?: number }>;
      moveLauncherWindow?: (deltaX: number, deltaY: number) => Promise<boolean>;
      openDesktopMode?: (mode?: string) => Promise<void>;
      openExternalUrl?: (url: string) => Promise<void>;
      openLauncherMenu?: (mode?: string) => Promise<void>;
      openPath?: (path: string) => Promise<void>;
      openView?: (view: string, params?: Record<string, string>) => Promise<void>;
      quit: () => Promise<void>;
      restartApp?: () => Promise<void>;
      setLauncherHitRegions?: (mode: string, payload: LauncherHitRegionPayload) => Promise<boolean>;
      setLauncherPointerInteractive?: (mode: string, interactive: boolean) => Promise<boolean>;
    };
  }
}

let cachedBridgeUrl: string | null = null;

export async function bridgeUrl(): Promise<string> {
  if (cachedBridgeUrl) return cachedBridgeUrl;
  const urlFromQuery = new URLSearchParams(window.location.search).get('bridge');
  if (urlFromQuery) {
    cachedBridgeUrl = urlFromQuery.replace(/\/$/, '');
    return cachedBridgeUrl;
  }
  if (window.hermesDesktop?.getBridgeUrl) {
    cachedBridgeUrl = (await window.hermesDesktop.getBridgeUrl()).replace(/\/$/, '');
    return cachedBridgeUrl;
  }
  cachedBridgeUrl = 'http://127.0.0.1:8420';
  return cachedBridgeUrl;
}

export async function apiGet<T = ApiRecord>(path: string): Promise<T> {
  const baseUrl = await bridgeUrl();
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`);
  } catch {
    throw new Error(`无法连接本地 Bridge：${baseUrl}`);
  }
  return parseResponse<T>(response);
}

export async function apiPost<T = ApiRecord>(path: string, body?: unknown): Promise<T> {
  const baseUrl = await bridgeUrl();
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`无法连接本地 Bridge：${baseUrl}`);
  }
  return parseResponse<T>(response);
}

export async function openAppView(
  view: string,
  params: Record<string, string> = {},
): Promise<void> {
  if (window.hermesDesktop?.openView) {
    await window.hermesDesktop.openView(view, params);
    return;
  }
  const targetUrl = appViewUrl(view, params);
  if (isLauncherView()) {
    const opened = window.open(targetUrl, '_blank');
    if (!opened && !navigator.userAgent.includes('Electron')) {
      location.assign(targetUrl);
    }
    return;
  }
  location.assign(targetUrl);
}

function appViewUrl(view: string, params: Record<string, string> = {}): string {
  const route = isAppView(view) ? routePath(view, params) : routePath('main');
  return `${window.location.pathname}${window.location.search}${route}`;
}

function isLauncherView(): boolean {
  const view = currentView();
  return view === 'bubble' || view === 'bubble-menu' || view === 'live2d';
}

function isAppView(value: string): value is AppView {
  return ['main', 'chat', 'settings', 'installer', 'bubble', 'bubble-menu', 'live2d'].includes(value);
}

export async function openDesktopMode(mode?: string): Promise<void> {
  if (window.hermesDesktop?.openDesktopMode) {
    await window.hermesDesktop.openDesktopMode(mode);
    return;
  }
  if (mode === 'live2d' || mode === 'bubble') location.assign(appViewUrl(mode));
}

export async function openLauncherMenu(mode?: string): Promise<void> {
  if (window.hermesDesktop?.openLauncherMenu) {
    await window.hermesDesktop.openLauncherMenu(mode);
  }
}

export async function moveLauncherWindow(deltaX: number, deltaY: number): Promise<void> {
  if (window.hermesDesktop?.moveLauncherWindow) {
    await window.hermesDesktop.moveLauncherWindow(deltaX, deltaY);
  }
}

export async function getLauncherPointerState(
  mode: string,
): Promise<{ ok?: boolean; x?: number; y?: number; width?: number; height?: number; inside?: boolean; updated_at?: number }> {
  if (window.hermesDesktop?.getLauncherPointerState) {
    return window.hermesDesktop.getLauncherPointerState(mode);
  }
  return { ok: false, inside: false, x: 0, y: 0 };
}

export async function chooseLive2DModelDirectory(): Promise<string | null> {
  if (!window.hermesDesktop?.chooseLive2DModelDirectory) {
    throw new Error('当前环境没有桌面文件选择器入口，请在页面中输入模型目录路径');
  }
  return window.hermesDesktop.chooseLive2DModelDirectory();
}

export async function chooseLive2DArchive(): Promise<string | null> {
  if (!window.hermesDesktop?.chooseLive2DArchive) {
    throw new Error('当前环境没有桌面文件选择器入口，请在页面中输入 ZIP 路径');
  }
  return window.hermesDesktop.chooseLive2DArchive();
}

export function hasDesktopFilePicker(): boolean {
  return Boolean(window.hermesDesktop?.chooseLive2DArchive && window.hermesDesktop?.chooseLive2DModelDirectory);
}

export async function openPath(path: string): Promise<void> {
  if (!window.hermesDesktop?.openPath) {
    throw new Error('当前环境没有桌面文件管理器入口');
  }
  await window.hermesDesktop.openPath(path);
}

export async function openExternalUrl(url: string): Promise<void> {
  if (window.hermesDesktop?.openExternalUrl) {
    await window.hermesDesktop.openExternalUrl(url);
    return;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

export async function setLauncherPointerInteractive(
  mode: string,
  interactive: boolean,
): Promise<void> {
  if (window.hermesDesktop?.setLauncherPointerInteractive) {
    await window.hermesDesktop.setLauncherPointerInteractive(mode, interactive);
  }
}

export async function setLauncherHitRegions(
  mode: string,
  regions: LauncherHitRegionRect[],
): Promise<boolean> {
  if (window.hermesDesktop?.setLauncherHitRegions) {
    return window.hermesDesktop.setLauncherHitRegions(mode, {
      regions,
      viewport: {
        width: Math.max(window.innerWidth || 1, 1),
        height: Math.max(window.innerHeight || 1, 1),
      },
    });
  }
  return false;
}

export async function copyText(text: string): Promise<void> {
  if (window.hermesDesktop?.copyText) {
    await window.hermesDesktop.copyText(text);
    return;
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.left = '-9999px';
  document.body.appendChild(area);
  area.focus();
  area.select();
  const ok = document.execCommand('copy');
  document.body.removeChild(area);
  if (!ok) throw new Error('复制失败');
}

export async function quitApp(): Promise<void> {
  if (window.hermesDesktop?.quit) {
    await window.hermesDesktop.quit();
    return;
  }
  window.close();
}

export async function restartApp(): Promise<void> {
  if (window.hermesDesktop?.restartApp) {
    await window.hermesDesktop.restartApp();
    return;
  }
  window.location.reload();
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const message = typeof data?.detail === 'string'
      ? data.detail
      : typeof data?.error === 'string'
        ? data.error
        : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data as T;
}
