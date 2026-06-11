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
export type DesktopTerminalTask = 'mac-prerequisites';
export type DesktopTerminalStartResult = {
  success?: boolean;
  id?: string;
  task?: DesktopTerminalTask;
  title?: string;
  error?: string;
};
export type DesktopTerminalDataPayload = { id: string; data: string };
export type DesktopTerminalExitPayload = { id: string; exitCode: number; signal?: number; task?: DesktopTerminalTask };
export type AppBuildMetadata = {
  name?: string;
  channel?: string;
  branch?: string;
  version?: string;
  base_version?: string;
  commit?: string;
  short_commit?: string;
  build_number?: number;
  repository?: string;
  latest_json_url?: string;
  built_at?: string;
};
export type ReleaseChangelogCommit = {
  commit?: string;
  short_commit?: string;
  author?: string;
  authored_at?: string;
  subject?: string;
  category?: string;
  url?: string | null;
};
export type ReleaseChangelogSection = {
  title?: string;
  items?: ReleaseChangelogCommit[];
};
export type ReleaseChangelog = {
  generated_from?: string;
  previous_tag?: string | null;
  previous_commit?: string | null;
  current_tag?: string;
  compare_url?: string | null;
  commit_count?: number;
  commits?: ReleaseChangelogCommit[];
  sections?: ReleaseChangelogSection[];
  summary?: string[];
};
export type LatestReleaseMetadata = {
  name?: string;
  channel?: string;
  branch?: string;
  source_branch?: string;
  version?: string;
  base_version?: string;
  commit?: string;
  short_commit?: string;
  build_number?: number;
  run_number?: number;
  tag?: string;
  signing?: string;
  dmg_name?: string;
  sha256?: string;
  download_url?: string;
  latest_json_url?: string;
  published_at?: string;
  changelog?: ReleaseChangelog;
};
export type AppUpdateInfo = {
  supported?: boolean;
  packaged?: boolean;
  current?: AppBuildMetadata;
  latest_json_url?: string;
  app_bundle_path?: string;
  downloaded_dmg_path?: string;
  downloaded_update?: AppUpdateDownloadResult;
  error?: string;
};
export type AppUpdateCheckResult = AppUpdateInfo & {
  ok?: boolean;
  update_available?: boolean;
  latest?: LatestReleaseMetadata;
  reason?: string;
};
export type AppUpdateDownloadResult = {
  ok?: boolean;
  path?: string;
  file_name?: string;
  sha256?: string;
  verified?: boolean;
  latest?: LatestReleaseMetadata;
  error?: string;
  cancelled?: boolean;
};
export type AppUpdateInstallResult = {
  success?: boolean;
  appBundlePath?: string;
  dmgPath?: string;
  error?: string;
};
export type AppUpdateDownloadProgress = {
  status?: 'starting' | 'downloading' | 'verifying' | 'completed' | 'failed' | string;
  file_name?: string;
  received_bytes?: number;
  total_bytes?: number;
  percent?: number;
  error?: string;
};
export type AvatarImageSelection = {
  path?: string;
  data_url?: string;
  file_name?: string;
};

declare global {
  interface Window {
    ohaDesktop?: {
      cancelAppUpdateDownload?: () => Promise<{ ok?: boolean; cancelled?: boolean; error?: string }>;
      chooseAvatarImage?: () => Promise<AvatarImageSelection | string | null>;
      chooseLive2DArchive?: () => Promise<string | null>;
      chooseLive2DModelDirectory?: () => Promise<string | null>;
      chooseTtsVoiceArchive?: () => Promise<string | null>;
      chooseSkillSources?: () => Promise<string[]>;
      checkAppUpdate?: () => Promise<AppUpdateCheckResult>;
      copyText?: (text: string) => Promise<void>;
      downloadAppUpdate?: () => Promise<AppUpdateDownloadResult>;
      getAppUpdateInfo?: () => Promise<AppUpdateInfo>;
      getBridgeUrl: () => Promise<string>;
      getBridgeToken?: () => Promise<string>;
      installAppUpdate?: (dmgPath?: string) => Promise<AppUpdateInstallResult>;
      getLauncherPointerState?: (mode: string) => Promise<{ ok?: boolean; x?: number; y?: number; width?: number; height?: number; inside?: boolean; updated_at?: number }>;
      moveLauncherWindow?: (deltaX: number, deltaY: number) => Promise<boolean>;
      openDesktopMode?: (mode?: string) => Promise<void>;
      openExternalUrl?: (url: string) => Promise<void>;
      openLauncherMenu?: (mode?: string) => Promise<void>;
      openPath?: (path: string) => Promise<void>;
      openView?: (view: string, params?: Record<string, string>) => Promise<void>;
      quit: () => Promise<void>;
      removeAppBundleAndQuit?: () => Promise<{ success?: boolean; appBundlePath?: string; error?: string }>;
      restartApp?: () => Promise<void>;
      restartBackend?: (options?: { bridgeUrl?: string }) => Promise<{ success?: boolean; bridgeUrl?: string; error?: string }>;
      setLauncherHitRegions?: (mode: string, payload: LauncherHitRegionPayload) => Promise<boolean>;
      setLauncherPointerInteractive?: (mode: string, interactive: boolean) => Promise<boolean>;
      terminalKill?: (id: string) => Promise<boolean>;
      terminalResize?: (id: string, cols: number, rows: number) => Promise<boolean>;
      terminalStart?: (task: string, cols: number, rows: number) => Promise<DesktopTerminalStartResult>;
      terminalWrite?: (id: string, data: string) => Promise<boolean>;
      onTerminalData?: (callback: (payload: DesktopTerminalDataPayload) => void) => () => void;
      onTerminalExit?: (callback: (payload: DesktopTerminalExitPayload) => void) => () => void;
      onAppUpdateDownloadProgress?: (callback: (payload: AppUpdateDownloadProgress) => void) => () => void;
    };
  }
}

let cachedBridgeUrl: string | null = null;
let cachedBridgeToken: string | null = null;

export async function bridgeUrl(): Promise<string> {
  if (cachedBridgeUrl) return cachedBridgeUrl;
  const urlFromQuery = new URLSearchParams(window.location.search).get('bridge');
  if (urlFromQuery) {
    cachedBridgeUrl = urlFromQuery.replace(/\/$/, '');
    return cachedBridgeUrl;
  }
  if (window.ohaDesktop?.getBridgeUrl) {
    cachedBridgeUrl = (await window.ohaDesktop.getBridgeUrl()).replace(/\/$/, '');
    return cachedBridgeUrl;
  }
  cachedBridgeUrl = 'http://127.0.0.1:8420';
  return cachedBridgeUrl;
}

async function bridgeToken(): Promise<string> {
  if (cachedBridgeToken !== null) return cachedBridgeToken;
  cachedBridgeToken = window.ohaDesktop?.getBridgeToken
    ? await window.ohaDesktop.getBridgeToken()
    : '';
  return cachedBridgeToken;
}

async function bridgeJsonHeaders(): Promise<Record<string, string>> {
  const token = await bridgeToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'X-Oha-Yachiyo-Bridge-Token': token } : {}),
  };
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
  const headers = await bridgeJsonHeaders();
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`无法连接本地 Bridge：${baseUrl}`);
  }
  return parseResponse<T>(response);
}

export async function apiPatch<T = ApiRecord>(path: string, body?: unknown): Promise<T> {
  const baseUrl = await bridgeUrl();
  const headers = await bridgeJsonHeaders();
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'PATCH',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`无法连接本地 Bridge：${baseUrl}`);
  }
  return parseResponse<T>(response);
}

export async function apiDelete<T = ApiRecord>(path: string, body?: unknown): Promise<T> {
  const baseUrl = await bridgeUrl();
  const token = await bridgeToken();
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'DELETE',
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { 'X-Oha-Yachiyo-Bridge-Token': token } : {}),
      },
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
  if (window.ohaDesktop?.openView) {
    await window.ohaDesktop.openView(view, params);
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
  const query = new URLSearchParams(window.location.search);
  Object.entries(params)
    .filter(([key]) => key !== 'view' && key !== 'mode' && key !== 'restore')
    .forEach(([key, value]) => {
      if (value) query.set(key, value);
      else query.delete(key);
    });
  const search = query.toString();
  return `${window.location.pathname}${search ? `?${search}` : ''}${route}`;
}

function isLauncherView(): boolean {
  const view = currentView();
  return view === 'bubble' || view === 'bubble-menu' || view === 'live2d';
}

function isAppView(value: string): value is AppView {
  return [
    'main',
    'chat',
    'agents',
    'settings',
    'provider',
    'resources',
    'workspace',
    'diagnostics',
    'tools',
    'tools-all',
    'activity-all',
    'activity-detail',
    'app-update',
    'proactive-tts',
    'bubble',
    'bubble-menu',
    'live2d',
  ].includes(value);
}

export async function openDesktopMode(mode?: string): Promise<void> {
  if (window.ohaDesktop?.openDesktopMode) {
    await window.ohaDesktop.openDesktopMode(mode);
    return;
  }
  if (mode === 'live2d' || mode === 'bubble') location.assign(appViewUrl(mode));
}

export async function openLauncherMenu(mode?: string): Promise<void> {
  if (window.ohaDesktop?.openLauncherMenu) {
    await window.ohaDesktop.openLauncherMenu(mode);
  }
}

export async function moveLauncherWindow(deltaX: number, deltaY: number): Promise<void> {
  if (window.ohaDesktop?.moveLauncherWindow) {
    await window.ohaDesktop.moveLauncherWindow(deltaX, deltaY);
  }
}

export async function getLauncherPointerState(
  mode: string,
): Promise<{ ok?: boolean; x?: number; y?: number; width?: number; height?: number; inside?: boolean; updated_at?: number }> {
  if (window.ohaDesktop?.getLauncherPointerState) {
    return window.ohaDesktop.getLauncherPointerState(mode);
  }
  return { ok: false, inside: false, x: 0, y: 0 };
}

export async function chooseLive2DModelDirectory(): Promise<string | null> {
  if (!window.ohaDesktop?.chooseLive2DModelDirectory) {
    throw new Error('当前环境没有桌面文件选择器入口，请在页面中输入模型目录路径');
  }
  return window.ohaDesktop.chooseLive2DModelDirectory();
}

export async function chooseAvatarImage(): Promise<AvatarImageSelection | string | null> {
  if (!window.ohaDesktop?.chooseAvatarImage) {
    throw new Error('当前环境没有桌面图片选择器入口');
  }
  return window.ohaDesktop.chooseAvatarImage();
}

export async function chooseLive2DArchive(): Promise<string | null> {
  if (!window.ohaDesktop?.chooseLive2DArchive) {
    throw new Error('当前环境没有桌面文件选择器入口，请在页面中输入 ZIP 路径');
  }
  return window.ohaDesktop.chooseLive2DArchive();
}

export async function chooseTtsVoiceArchive(): Promise<string | null> {
  if (!window.ohaDesktop?.chooseTtsVoiceArchive) {
    throw new Error('当前环境没有桌面文件选择器入口，请在页面中输入音色包 ZIP 路径');
  }
  return window.ohaDesktop.chooseTtsVoiceArchive();
}

export async function chooseSkillSources(): Promise<string[]> {
  if (!window.ohaDesktop?.chooseSkillSources) {
    throw new Error('当前环境没有桌面文件选择器入口，请在页面中输入 Skill 目录或 ZIP 路径');
  }
  return window.ohaDesktop.chooseSkillSources();
}

export function hasDesktopAvatarPicker(): boolean {
  return Boolean(window.ohaDesktop?.chooseAvatarImage);
}

export function hasDesktopFilePicker(): boolean {
  return Boolean(window.ohaDesktop?.chooseLive2DArchive && window.ohaDesktop?.chooseLive2DModelDirectory);
}

export function hasDesktopTtsVoiceArchivePicker(): boolean {
  return Boolean(window.ohaDesktop?.chooseTtsVoiceArchive);
}

export async function openPath(path: string): Promise<void> {
  if (!window.ohaDesktop?.openPath) {
    throw new Error('当前环境没有桌面文件管理器入口');
  }
  await window.ohaDesktop.openPath(path);
}

export async function openExternalUrl(url: string): Promise<void> {
  if (window.ohaDesktop?.openExternalUrl) {
    await window.ohaDesktop.openExternalUrl(url);
    return;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

export async function setLauncherPointerInteractive(
  mode: string,
  interactive: boolean,
): Promise<void> {
  if (window.ohaDesktop?.setLauncherPointerInteractive) {
    await window.ohaDesktop.setLauncherPointerInteractive(mode, interactive);
  }
}

export async function setLauncherHitRegions(
  mode: string,
  regions: LauncherHitRegionRect[],
): Promise<boolean> {
  if (window.ohaDesktop?.setLauncherHitRegions) {
    return window.ohaDesktop.setLauncherHitRegions(mode, {
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
  const errors: string[] = [];
  if (window.ohaDesktop?.copyText) {
    try {
      await window.ohaDesktop.copyText(text);
      return;
    } catch (error) {
      errors.push(error instanceof Error ? error.message : 'desktop clipboard failed');
    }
  }
  try {
    copyTextWithSelection(text);
    return;
  } catch (error) {
    errors.push(error instanceof Error ? error.message : 'fallback copy failed');
  }
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (error) {
      errors.push(error instanceof Error ? error.message : 'web clipboard failed');
    }
  }
  try {
    const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/clipboard', { text });
    if (result.ok === false) throw new Error(result.error || 'bridge clipboard failed');
    return;
  } catch (error) {
    errors.push(error instanceof Error ? error.message : 'bridge clipboard failed');
  }
  const detail = errors.filter(Boolean).join('；');
  throw new Error(detail ? `复制失败：${detail}` : '复制失败');
}

function copyTextWithSelection(text: string): void {
  const area = document.createElement('textarea');
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.left = '-9999px';
  area.style.top = '0';
  area.style.opacity = '0';
  document.body.appendChild(area);
  try {
    window.focus();
    area.focus();
    area.select();
    area.setSelectionRange(0, area.value.length);
    if (typeof document.execCommand !== 'function' || !document.execCommand('copy')) {
      throw new Error('fallback copy failed');
    }
  } finally {
    document.body.removeChild(area);
    try {
      activeElement?.focus({ preventScroll: true });
    } catch {
      // Restoring focus is best-effort after the browser has accepted the copy command.
    }
  }
}

export async function quitApp(): Promise<void> {
  if (window.ohaDesktop?.quit) {
    await window.ohaDesktop.quit();
    return;
  }
  window.close();
}

export async function removeAppBundleAndQuit(): Promise<{ success?: boolean; appBundlePath?: string; error?: string }> {
  if (!window.ohaDesktop?.removeAppBundleAndQuit) {
    throw new Error('当前环境无法自动删除应用本体');
  }
  return window.ohaDesktop.removeAppBundleAndQuit();
}

export async function restartApp(): Promise<void> {
  if (window.ohaDesktop?.restartApp) {
    await window.ohaDesktop.restartApp();
    return;
  }
  window.location.reload();
}

export async function getAppUpdateInfo(): Promise<AppUpdateInfo> {
  if (!window.ohaDesktop?.getAppUpdateInfo) {
    return { supported: false, packaged: false, error: '当前环境不支持应用更新' };
  }
  return window.ohaDesktop.getAppUpdateInfo();
}

export async function checkAppUpdate(): Promise<AppUpdateCheckResult> {
  if (!window.ohaDesktop?.checkAppUpdate) {
    return { ok: false, supported: false, packaged: false, update_available: false, error: '当前环境不支持应用更新' };
  }
  return window.ohaDesktop.checkAppUpdate();
}

export async function downloadAppUpdate(): Promise<AppUpdateDownloadResult> {
  if (!window.ohaDesktop?.downloadAppUpdate) {
    return { ok: false, error: '当前环境不支持应用更新' };
  }
  return window.ohaDesktop.downloadAppUpdate();
}

export async function cancelAppUpdateDownload(): Promise<{ ok?: boolean; cancelled?: boolean; error?: string }> {
  if (!window.ohaDesktop?.cancelAppUpdateDownload) {
    return { ok: false, cancelled: false, error: '当前环境不支持取消应用更新下载' };
  }
  return window.ohaDesktop.cancelAppUpdateDownload();
}

export async function installAppUpdate(dmgPath?: string): Promise<AppUpdateInstallResult> {
  if (!window.ohaDesktop?.installAppUpdate) {
    return { success: false, error: '当前环境不支持应用更新' };
  }
  return window.ohaDesktop.installAppUpdate(dmgPath);
}

export function onAppUpdateDownloadProgress(callback: (payload: AppUpdateDownloadProgress) => void): () => void {
  return window.ohaDesktop?.onAppUpdateDownloadProgress?.(callback) || (() => {});
}

export async function restartDesktopBridge(bridgeUrl?: string): Promise<{ success?: boolean; bridgeUrl?: string; error?: string }> {
  if (!window.ohaDesktop?.restartBackend) {
    return { success: false, error: '当前环境不支持自动重启 Bridge，请重启 Oha-Yachiyo' };
  }
  const result = await window.ohaDesktop.restartBackend({ bridgeUrl });
  cachedBridgeToken = null;
  if (result.bridgeUrl) cachedBridgeUrl = result.bridgeUrl.replace(/\/$/, '');
  return result;
}

export function hasEmbeddedTerminal(): boolean {
  return Boolean(
    window.ohaDesktop?.terminalStart
    && window.ohaDesktop?.terminalWrite
    && window.ohaDesktop?.terminalResize
    && window.ohaDesktop?.terminalKill
    && window.ohaDesktop?.onTerminalData
    && window.ohaDesktop?.onTerminalExit,
  );
}

export async function startDesktopTerminal(
  task: DesktopTerminalTask,
  cols: number,
  rows: number,
): Promise<DesktopTerminalStartResult> {
  if (!window.ohaDesktop?.terminalStart) throw new Error('当前环境不支持内置终端');
  return window.ohaDesktop.terminalStart(task, cols, rows);
}

export async function writeDesktopTerminal(id: string, data: string): Promise<void> {
  if (!window.ohaDesktop?.terminalWrite) return;
  await window.ohaDesktop.terminalWrite(id, data);
}

export async function resizeDesktopTerminal(id: string, cols: number, rows: number): Promise<void> {
  if (!window.ohaDesktop?.terminalResize) return;
  await window.ohaDesktop.terminalResize(id, cols, rows);
}

export async function killDesktopTerminal(id: string): Promise<void> {
  if (!window.ohaDesktop?.terminalKill) return;
  await window.ohaDesktop.terminalKill(id);
}

export function onDesktopTerminalData(callback: (payload: DesktopTerminalDataPayload) => void): () => void {
  return window.ohaDesktop?.onTerminalData?.(callback) || (() => {});
}

export function onDesktopTerminalExit(callback: (payload: DesktopTerminalExitPayload) => void): () => void {
  return window.ohaDesktop?.onTerminalExit?.(callback) || (() => {});
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string'
      ? detail
      : typeof detail?.message === 'string'
        ? detail.message
        : typeof detail?.error === 'string'
          ? detail.error
          : typeof data?.error === 'string'
            ? data.error
            : `HTTP ${response.status}`;
    throw new Error(message.includes(`HTTP ${response.status}`) ? message : `HTTP ${response.status}: ${message}`);
  }
  return data as T;
}
