import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  screen,
  shell,
  Tray,
  type IpcMainInvokeEvent,
  type OpenDialogOptions,
  type Rectangle,
} from 'electron';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DEV_URL = process.env.HERMES_YACHIYO_FRONTEND_DEV_URL || 'http://127.0.0.1:5174';
const BRIDGE_URL = process.env.HERMES_YACHIYO_BRIDGE_URL || 'http://127.0.0.1:8420';
const BRIDGE_SETTINGS_RETRIES = 40;
const BRIDGE_SETTINGS_RETRY_MS = 250;
const BUBBLE_SCREEN_MARGIN = 24;
const POSITION_SAVE_DEBOUNCE_MS = 260;
const LIVE2D_POINTER_PASSTHROUGH_ENABLED = true;
const MAX_LAUNCHER_SHAPE_RECTS = 10000;

type AppView = 'main' | 'chat' | 'settings' | 'installer' | 'bubble' | 'bubble-menu' | 'live2d';
type ModeId = 'bubble' | 'live2d';

type ModeSettings = {
  config?: Record<string, unknown>;
};

type UiSettings = {
  app?: {
    start_minimized?: boolean;
    tray_enabled?: boolean;
  };
  display?: { current_mode?: string };
  mode_settings?: Record<string, ModeSettings>;
  window_mode?: {
    width?: number;
    height?: number;
    open_chat_on_start?: boolean;
  };
};

type InstallInfoPayload = {
  hermes_ready?: boolean;
  install_info?: {
    status?: string;
  } | null;
};

let backendProcess: ChildProcessWithoutNullStreams | null = null;
let mainWindow: BrowserWindow | null = null;
let chatWindow: BrowserWindow | null = null;
let modeWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let activeMode: ModeId | null = null;
let activeModeConfig: Record<string, unknown> = {};
let activeModeConfigSignature = '';
let positionSaveTimer: NodeJS.Timeout | null = null;
let modeWindowIgnoringMouse = false;
let modeWindowShapeApplied = false;
let modeWindowTopSuppressed = false;
let lastInstallReady: boolean | null = null;
let lastUiSettings: UiSettings | null = null;

type MainWindowOptions = {
  respectStartMinimized?: boolean;
  focusOnReady?: boolean;
};

showMacDockIcon();

function projectRoot(): string {
  return path.resolve(__dirname, '..', '..', '..');
}

function startBackend(): void {
  if (process.env.HERMES_YACHIYO_SKIP_BACKEND === '1') return;
  if (backendProcess) return;

  const python = process.env.HERMES_YACHIYO_PYTHON || 'python3';
  backendProcess = spawn(python, ['-m', 'apps.desktop_backend.app'], {
    cwd: projectRoot(),
    env: {
      ...process.env,
      PYTHONPATH: projectRoot(),
    },
  });

  backendProcess.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
  backendProcess.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
  backendProcess.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code ?? 'null'} signal=${signal ?? 'null'}`);
    backendProcess = null;
  });
}

function stopBackend(): void {
  if (!backendProcess) return;
  backendProcess.kill('SIGTERM');
  backendProcess = null;
}

function rendererUrl(params: Record<string, string> = {}): string {
  const query = new URLSearchParams({ bridge: BRIDGE_URL });
  Object.entries(params)
    .filter(([key]) => key !== 'view' && key !== 'mode')
    .forEach(([key, value]) => query.set(key, value));
  const route = routeHash(params);
  if (!app.isPackaged) return `${FRONTEND_DEV_URL}?${query.toString()}${route}`;
  const indexHtml = path.resolve(__dirname, '..', 'dist', 'index.html');
  return `${pathToFileURL(indexHtml).toString()}?${query.toString()}${route}`;
}

function routeHash(params: Record<string, string> = {}): string {
  const view = normalizeView(params.view);
  if (view === 'main') return '#/';
  if (view === 'settings' && params.mode) return `#/settings/${encodeURIComponent(params.mode)}`;
  return `#/${encodeURIComponent(view)}`;
}

function mainWindowBounds(settings: UiSettings | null = lastUiSettings): { width: number; height: number } {
  const windowMode = settings?.window_mode || {};
  return {
    width: Math.round(clamp(numberFromConfig(windowMode.width, 1120), 860, 1920)),
    height: Math.round(clamp(numberFromConfig(windowMode.height, 760), 580, 1400)),
  };
}

function createMainWindow(
  params: Record<string, string> = {},
  settings: UiSettings | null = lastUiSettings,
  options: MainWindowOptions = {},
): void {
  if (settings) lastUiSettings = settings;
  const bounds = mainWindowBounds(settings);
  const startHidden = Boolean(options.respectStartMinimized && settings?.app?.start_minimized);
  const focusOnReady = options.focusOnReady !== false;
  mainWindow = new BrowserWindow({
    title: 'Hermes-Yachiyo',
    ...bounds,
    minWidth: 860,
    minHeight: 580,
    show: false,
    backgroundColor: '#0e1117',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once('ready-to-show', () => {
    if (!mainWindow || mainWindow.isDestroyed() || startHidden) return;
    showMacDockIcon();
    suppressModeWindowForMainWindow();
    mainWindow.show();
    if (focusOnReady) mainWindow.focus();
  });
  mainWindow.loadURL(rendererUrl({ view: 'main', ...params }));
  mainWindow.on('focus', suppressModeWindowForMainWindow);
  mainWindow.on('blur', restoreModeWindowTopPreference);
  mainWindow.on('minimize', restoreModeWindowTopPreference);
  mainWindow.on('hide', restoreModeWindowTopPreference);
  mainWindow.on('closed', () => {
    mainWindow = null;
    restoreModeWindowTopPreference();
  });
}

function showMainWindow(params: Record<string, string> = {}, settings: UiSettings | null = lastUiSettings): void {
  if (normalizeView(params.view) === 'chat') {
    showChatWindow(params);
    return;
  }
  if (!mainWindow) {
    createMainWindow(params, settings);
    return;
  }
  mainWindow.loadURL(rendererUrl({ view: 'main', ...params }));
  if (mainWindow.isMinimized()) mainWindow.restore();
  showMacDockIcon();
  suppressModeWindowForMainWindow();
  mainWindow.show();
  mainWindow.moveTop();
  mainWindow.focus();
}

function showMainWindowFromAppActivation(): void {
  const params = lastInstallReady === false ? { view: 'installer' } : { view: 'main' };
  showMainWindow(params, lastUiSettings);
  setTimeout(() => showMainWindow(params, lastUiSettings), 90);
}

function trayIcon() {
  const iconPath = path.resolve(projectRoot(), 'apps', 'shell', 'assets', 'avatars', 'yachiyo-default.jpg');
  const image = nativeImage.createFromPath(iconPath);
  if (image.isEmpty()) return image;
  const size = process.platform === 'darwin' ? 18 : 20;
  return image.resize({ width: size, height: size });
}

function trayMenu(): Menu {
  return Menu.buildFromTemplate([
    { label: '主控台', click: () => showMainWindow({ view: 'main' }) },
    { label: '打开对话', click: () => showChatWindow() },
    { label: '打开表现态', click: () => void openConfiguredDesktopMode(undefined, lastUiSettings) },
    { label: '应用设置', click: () => showMainWindow({ view: 'settings' }) },
    { type: 'separator' },
    { label: '退出 Hermes-Yachiyo', click: () => app.quit() },
  ]);
}

function configureTray(settings: UiSettings | null = lastUiSettings): void {
  const enabled = settings?.app?.tray_enabled !== false;
  if (!enabled) {
    if (tray && !tray.isDestroyed()) tray.destroy();
    tray = null;
    return;
  }
  if (!tray || tray.isDestroyed()) {
    tray = new Tray(trayIcon());
    tray.setToolTip('Hermes-Yachiyo');
    tray.on('click', () => showMainWindow({ view: 'main' }));
  }
  tray.setContextMenu(trayMenu());
}

function showMacDockIcon(): void {
  if (process.platform !== 'darwin') return;
  try {
    app.setActivationPolicy('regular');
    app.dock?.show();
  } catch {}
}

function routeForWindow(targetWindow: BrowserWindow | null): { view: AppView; params: Record<string, string> } | null {
  if (!targetWindow || targetWindow.isDestroyed()) return null;
  return routeFromUrl(targetWindow.webContents.getURL());
}

function restoreMainWindowIfPolluted(): void {
  const route = routeForWindow(mainWindow);
  if (!route) return;
  if (route.view === 'chat' || route.view === 'bubble' || route.view === 'bubble-menu' || route.view === 'live2d') {
    mainWindow?.loadURL(rendererUrl({ view: 'main' }));
  }
}

function restoreModeWindowIfPolluted(): void {
  if (!modeWindow || modeWindow.isDestroyed() || !activeMode) return;
  const route = routeForWindow(modeWindow);
  if (!route) return;
  if (route.view !== activeMode && !(activeMode === 'bubble' && route.view === 'bubble-menu')) {
    modeWindow.loadURL(rendererUrl({ view: activeMode }));
  }
}

function createChatWindow(params: Record<string, string> = {}): void {
  chatWindow = new BrowserWindow({
    title: 'Yachiyo - 对话',
    width: 520,
    height: 680,
    minWidth: 420,
    minHeight: 560,
    backgroundColor: '#121622',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  chatWindow.loadURL(rendererUrl({ ...params, view: 'chat' }));
  chatWindow.on('closed', () => {
    chatWindow = null;
  });
  chatWindow.once('ready-to-show', () => {
    showMacDockIcon();
  });
}

function showChatWindow(params: Record<string, string> = {}): void {
  restoreMainWindowIfPolluted();
  restoreModeWindowIfPolluted();
  if (!chatWindow) {
    createChatWindow(params);
    return;
  }
  const route = routeForWindow(chatWindow);
  if (route?.view !== 'chat') {
    chatWindow.loadURL(rendererUrl({ ...params, view: 'chat' }));
  }
  showMacDockIcon();
  chatWindow.show();
  chatWindow.focus();
}

function openAppView(view: AppView, params: Record<string, string> = {}): void {
  if (view === 'chat') {
    showChatWindow(params);
    return;
  }
  if (view === 'bubble' || view === 'bubble-menu' || view === 'live2d') {
    void openConfiguredDesktopMode(normalizeMode(view));
    return;
  }
  showMainWindow({ view, ...params });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeView(value: unknown): AppView {
  const views: AppView[] = ['main', 'chat', 'settings', 'installer', 'bubble', 'bubble-menu', 'live2d'];
  return typeof value === 'string' && views.includes(value as AppView) ? (value as AppView) : 'main';
}

function normalizeParams(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, entry]) => typeof entry === 'string')
      .map(([key, entry]) => [key, entry as string]),
  );
}

function normalizeMode(value: unknown): ModeId {
  return value === 'live2d' ? 'live2d' : 'bubble';
}

function routeFromUrl(rawUrl: string): { view: AppView; params: Record<string, string> } | null {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return null;
  }
  const params = Object.fromEntries(parsed.searchParams.entries());
  if (parsed.hash.startsWith('#/')) {
    const parts = parsed.hash.slice(2).split('/').filter(Boolean).map((part) => decodeURIComponent(part));
    if (!parts.length) return { view: 'main', params };
    const [rawView, rawMode] = parts;
    const view = normalizeView(rawView);
    if (view === 'settings' && rawMode) params.mode = rawMode;
    return { view, params };
  }
  return { view: normalizeView(parsed.searchParams.get('view')), params };
}

function redirectDesktopModeNavigation(targetUrl: string, launcherMode: ModeId): boolean {
  const route = routeFromUrl(targetUrl);
  if (!route) return false;
  if (route.view === launcherMode || (launcherMode === 'bubble' && route.view === 'bubble-menu')) return false;
  openAppView(route.view, route.params);
  return true;
}

function numberFromConfig(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function booleanFromConfig(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function workAreaForBounds(bounds: Rectangle): Rectangle {
  return screen.getDisplayMatching(bounds).workArea;
}

function snapBubbleBounds(bounds: Rectangle): Rectangle {
  const display = workAreaForBounds(bounds);
  const left = display.x + BUBBLE_SCREEN_MARGIN;
  const right = display.x + display.width - bounds.width - BUBBLE_SCREEN_MARGIN;
  const top = display.y + BUBBLE_SCREEN_MARGIN;
  const bottom = display.y + display.height - bounds.height - BUBBLE_SCREEN_MARGIN;
  let x = clamp(bounds.x, left, right);
  let y = clamp(bounds.y, top, bottom);
  const distances = {
    left: Math.abs(x - left),
    right: Math.abs(x - right),
    top: Math.abs(y - top),
    bottom: Math.abs(y - bottom),
  };
  const edge = Object.entries(distances).sort((first, second) => first[1] - second[1])[0][0];
  if (edge === 'left') x = left;
  else if (edge === 'right') x = right;
  else if (edge === 'top') y = top;
  else y = bottom;
  return { ...bounds, x: Math.round(x), y: Math.round(y) };
}

function boundsChanged(first: Rectangle, second: Rectangle): boolean {
  return first.x !== second.x || first.y !== second.y || first.width !== second.width || first.height !== second.height;
}

async function saveLauncherPosition(mode: ModeId, bounds: Rectangle): Promise<void> {
  const workArea = workAreaForBounds(bounds);
  try {
    const response = await fetch(`${BRIDGE_URL}/ui/launcher/position`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode,
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        work_area: {
          x: workArea.x,
          y: workArea.y,
          width: workArea.width,
          height: workArea.height,
        },
      }),
    });
    if (!response.ok) console.warn(`[launcher] 保存表现态位置失败: HTTP ${response.status}`);
  } catch (error) {
    console.warn('[launcher] 保存表现态位置失败:', error);
  }
}

function scheduleModeWindowPositionSave(mode: ModeId, config: Record<string, unknown>): void {
  if (positionSaveTimer) clearTimeout(positionSaveTimer);
  positionSaveTimer = setTimeout(() => {
    if (!modeWindow || modeWindow.isDestroyed() || activeMode !== mode) return;
    let bounds = modeWindow.getBounds();
    if (mode === 'bubble' && booleanFromConfig(config.edge_snap, true)) {
      const snapped = snapBubbleBounds(bounds);
      if (boundsChanged(bounds, snapped)) {
        modeWindow.setBounds(snapped, false);
        bounds = snapped;
      }
    }
    void saveLauncherPosition(mode, bounds);
  }, POSITION_SAVE_DEBOUNCE_MS);
}

function desktopModeBounds(mode: ModeId, config: Record<string, unknown>) {
  if (mode === 'live2d') {
    return {
      width: Math.round(clamp(numberFromConfig(config.width, 420), 300, 760)),
      height: Math.round(clamp(numberFromConfig(config.height, 680), 420, 900)),
      x: Math.round(numberFromConfig(config.position_x, 48)),
      y: Math.round(numberFromConfig(config.position_y, 48)),
    };
  }

  const display = screen.getPrimaryDisplay().workArea;
  const width = Math.round(clamp(numberFromConfig(config.width, 112), 80, 192));
  const height = Math.round(clamp(numberFromConfig(config.height, 112), 80, 192));
  const xPercent = clamp(numberFromConfig(config.position_x_percent, 1), 0, 1);
  const yPercent = clamp(numberFromConfig(config.position_y_percent, 1), 0, 1);
  const margin = 24;
  const x = Math.round(display.x + margin + (display.width - width - margin * 2) * xPercent);
  const y = Math.round(display.y + margin + (display.height - height - margin * 2) * yPercent);
  return { width, height, x, y };
}

function modeConfigSignature(config: Record<string, unknown>): string {
  return JSON.stringify(Object.entries(config).sort(([first], [second]) => first.localeCompare(second)));
}

function configuredModeWindowAlwaysOnTop(mode: ModeId | null = activeMode, config: Record<string, unknown> = activeModeConfig): boolean {
  if (!mode) return false;
  return mode === 'live2d'
    ? booleanFromConfig(config.window_on_top, true)
    : booleanFromConfig(config.always_on_top, true);
}

function applyModeWindowTopPreference(): void {
  if (!modeWindow || modeWindow.isDestroyed() || !activeMode) return;
  modeWindow.setAlwaysOnTop(!modeWindowTopSuppressed && configuredModeWindowAlwaysOnTop(), 'floating');
}

function suppressModeWindowForMainWindow(): void {
  if (!modeWindow || modeWindow.isDestroyed()) return;
  modeWindowTopSuppressed = true;
  applyModeWindowTopPreference();
}

function restoreModeWindowTopPreference(): void {
  if (!modeWindowTopSuppressed) return;
  modeWindowTopSuppressed = false;
  applyModeWindowTopPreference();
}

function createDesktopModeWindow(mode: ModeId, config: Record<string, unknown> = {}): void {
  if (modeWindow && !modeWindow.isDestroyed() && activeMode === mode) {
    const nextSignature = modeConfigSignature(config);
    activeModeConfig = config;
    if (nextSignature !== activeModeConfigSignature) {
      activeModeConfigSignature = nextSignature;
      const bounds = desktopModeBounds(mode, config);
      modeWindow.setBounds(bounds, false);
      applyModeWindowTopPreference();
      if (mode === 'live2d') {
        modeWindow.setVisibleOnAllWorkspaces(booleanFromConfig(config.show_on_all_spaces, true), { visibleOnFullScreen: true });
      }
      modeWindow.loadURL(rendererUrl({ view: mode }));
    }
    const route = routeForWindow(modeWindow);
    if (route?.view !== mode && !(mode === 'bubble' && route?.view === 'bubble-menu')) {
      modeWindow.loadURL(rendererUrl({ view: mode }));
    }
    modeWindow.show();
    modeWindow.focus();
    return;
  }
  if (modeWindow && !modeWindow.isDestroyed()) {
    const previousModeWindow = modeWindow;
    modeWindow = null;
    activeMode = null;
    activeModeConfig = {};
    activeModeConfigSignature = '';
    modeWindowIgnoringMouse = false;
    modeWindowShapeApplied = false;
    modeWindowTopSuppressed = false;
    previousModeWindow.close();
  }

  activeMode = mode;
  activeModeConfig = config;
  activeModeConfigSignature = modeConfigSignature(config);
  modeWindowIgnoringMouse = false;
  modeWindowShapeApplied = false;
  modeWindowTopSuppressed = false;
  const bounds = desktopModeBounds(mode, config);
  const alwaysOnTop = mode === 'live2d'
    ? booleanFromConfig(config.window_on_top, true)
    : booleanFromConfig(config.always_on_top, true);

  const createdModeWindow = new BrowserWindow({
    title: mode === 'live2d' ? 'Hermes-Yachiyo Live2D' : 'Hermes-Yachiyo Bubble',
    ...bounds,
    frame: false,
    transparent: true,
    resizable: mode === 'live2d',
    movable: true,
    skipTaskbar: true,
    alwaysOnTop,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  modeWindow = createdModeWindow;

  if (mode === 'live2d' && booleanFromConfig(config.show_on_all_spaces, true)) {
    createdModeWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }
  applyModeWindowTopPreference();
  createdModeWindow.loadURL(rendererUrl({ view: mode }));
  createdModeWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (redirectDesktopModeNavigation(targetUrl, mode)) event.preventDefault();
  });
  createdModeWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (redirectDesktopModeNavigation(url, mode)) return { action: 'deny' };
    return { action: 'allow' };
  });
  if (mode === 'live2d' && LIVE2D_POINTER_PASSTHROUGH_ENABLED) {
    setTimeout(() => setModeWindowPointerInteractive('live2d', false), 260);
  }
  createdModeWindow.on('focus', restoreModeWindowTopPreference);
  createdModeWindow.on('move', () => scheduleModeWindowPositionSave(mode, config));
  createdModeWindow.on('resize', () => scheduleModeWindowPositionSave(mode, config));
  createdModeWindow.on('closed', () => {
    if (modeWindow !== createdModeWindow) return;
    if (positionSaveTimer) {
      clearTimeout(positionSaveTimer);
      positionSaveTimer = null;
    }
    modeWindowIgnoringMouse = false;
    modeWindowShapeApplied = false;
    modeWindowTopSuppressed = false;
    activeModeConfig = {};
    activeModeConfigSignature = '';
    modeWindow = null;
    activeMode = null;
  });
}

function setModeWindowPointerInteractive(mode: ModeId, interactive: boolean): boolean {
  if (!modeWindow || modeWindow.isDestroyed() || activeMode !== mode) return false;
  if (mode === 'live2d' && !LIVE2D_POINTER_PASSTHROUGH_ENABLED && !interactive) return true;
  const shouldIgnore = !interactive;
  if (modeWindowIgnoringMouse === shouldIgnore) return true;
  modeWindow.setIgnoreMouseEvents(shouldIgnore, { forward: true });
  modeWindowIgnoringMouse = shouldIgnore;
  return true;
}

function setModeWindowHitRegions(mode: ModeId, rawRegions: unknown): boolean {
  if (!modeWindow || modeWindow.isDestroyed() || activeMode !== mode) return false;
  const bounds = modeWindow.getBounds();
  const shapePayload = normalizeLauncherShapePayload(rawRegions, bounds);
  const shapeRects = normalizeLauncherShapeRects(shapePayload.regions, bounds, shapePayload.scaleX, shapePayload.scaleY);
  if (!shapeRects.length) return false;
  try {
    modeWindow.setShape(shapeRects);
    modeWindowShapeApplied = true;
    if (modeWindowIgnoringMouse) {
      modeWindow.setIgnoreMouseEvents(false);
      modeWindowIgnoringMouse = false;
    }
    return true;
  } catch (error) {
    modeWindowShapeApplied = false;
    console.warn('[desktop] setShape failed; falling back to pointer passthrough polling.', error);
    return false;
  }
}

function normalizeLauncherShapePayload(rawPayload: unknown, bounds: Rectangle): { regions: unknown; scaleX: number; scaleY: number } {
  if (Array.isArray(rawPayload)) return { regions: rawPayload, scaleX: 1, scaleY: 1 };
  if (!rawPayload || typeof rawPayload !== 'object') return { regions: [], scaleX: 1, scaleY: 1 };
  const payload = rawPayload as Record<string, unknown>;
  const viewport = payload.viewport && typeof payload.viewport === 'object'
    ? payload.viewport as Record<string, unknown>
    : {};
  const viewportWidth = safeShapeNumber(viewport.width);
  const viewportHeight = safeShapeNumber(viewport.height);
  return {
    regions: payload.regions,
    scaleX: viewportWidth && viewportWidth > 0 ? bounds.width / viewportWidth : 1,
    scaleY: viewportHeight && viewportHeight > 0 ? bounds.height / viewportHeight : 1,
  };
}

function normalizeLauncherShapeRects(
  rawRegions: unknown,
  bounds: Rectangle,
  scaleX: number,
  scaleY: number,
): Rectangle[] {
  if (!Array.isArray(rawRegions)) return [];
  return rawRegions
    .slice(0, MAX_LAUNCHER_SHAPE_RECTS)
    .map((region) => normalizeLauncherShapeRect(region, bounds, scaleX, scaleY))
    .filter((region): region is Rectangle => Boolean(region));
}

function normalizeLauncherShapeRect(
  rawRegion: unknown,
  bounds: Rectangle,
  scaleX: number,
  scaleY: number,
): Rectangle | null {
  if (!rawRegion || typeof rawRegion !== 'object') return null;
  const region = rawRegion as Record<string, unknown>;
  const rawLeft = safeShapeNumber(region.x);
  const rawTop = safeShapeNumber(region.y);
  const rawWidth = safeShapeNumber(region.width);
  const rawHeight = safeShapeNumber(region.height);
  const left = rawLeft === null ? null : rawLeft * scaleX;
  const top = rawTop === null ? null : rawTop * scaleY;
  const width = rawWidth === null ? null : rawWidth * scaleX;
  const height = rawHeight === null ? null : rawHeight * scaleY;
  if (left === null || top === null || width === null || height === null) return null;
  if (width <= 0 || height <= 0) return null;

  const x1 = clamp(Math.round(left), 0, bounds.width);
  const y1 = clamp(Math.round(top), 0, bounds.height);
  const x2 = clamp(Math.round(left + width), 0, bounds.width);
  const y2 = clamp(Math.round(top + height), 0, bounds.height);
  if (x2 <= x1 || y2 <= y1) return null;
  return {
    x: x1,
    y: y1,
    width: x2 - x1,
    height: y2 - y1,
  };
}

function safeShapeNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function safeDelta(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(clamp(value, -2000, 2000)) : 0;
}

function moveLauncherWindow(event: IpcMainInvokeEvent, rawDeltaX: unknown, rawDeltaY: unknown): boolean {
  const targetWindow = BrowserWindow.fromWebContents(event.sender);
  if (!targetWindow || targetWindow !== modeWindow || !activeMode || targetWindow.isDestroyed()) return false;
  const deltaX = safeDelta(rawDeltaX);
  const deltaY = safeDelta(rawDeltaY);
  if (deltaX === 0 && deltaY === 0) return true;
  const bounds = targetWindow.getBounds();
  targetWindow.setBounds({ ...bounds, x: bounds.x + deltaX, y: bounds.y + deltaY }, false);
  scheduleModeWindowPositionSave(activeMode, activeModeConfig);
  return true;
}

function launcherPointerState(mode: unknown): { ok: boolean; x: number; y: number; width: number; height: number; inside: boolean; updated_at: number } {
  const modeId = normalizeMode(mode);
  if (!modeWindow || modeWindow.isDestroyed() || activeMode !== modeId) {
    return { ok: false, x: 0, y: 0, width: 0, height: 0, inside: false, updated_at: Date.now() / 1000 };
  }
  const point = screen.getCursorScreenPoint();
  const bounds = modeWindow.getBounds();
  const x = point.x - bounds.x;
  const y = point.y - bounds.y;
  return {
    ok: true,
    x,
    y,
    width: bounds.width,
    height: bounds.height,
    inside: x >= 0 && y >= 0 && x <= bounds.width && y <= bounds.height,
    updated_at: Date.now() / 1000,
  };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function fetchUiSettings(): Promise<UiSettings> {
  const response = await fetch(`${BRIDGE_URL}/ui/settings`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as UiSettings;
}

async function fetchInstallInfo(): Promise<InstallInfoPayload> {
  const response = await fetch(`${BRIDGE_URL}/hermes/install-info`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as InstallInfoPayload;
}

async function waitForUiSettings(): Promise<UiSettings | null> {
  for (let attempt = 0; attempt < BRIDGE_SETTINGS_RETRIES; attempt += 1) {
    try {
      return await fetchUiSettings();
    } catch {
      await delay(BRIDGE_SETTINGS_RETRY_MS);
    }
  }
  return null;
}

async function waitForInstallInfo(): Promise<InstallInfoPayload | null> {
  for (let attempt = 0; attempt < BRIDGE_SETTINGS_RETRIES; attempt += 1) {
    try {
      return await fetchInstallInfo();
    } catch {
      await delay(BRIDGE_SETTINGS_RETRY_MS);
    }
  }
  return null;
}

function installReady(payload: InstallInfoPayload | null): boolean {
  return Boolean(payload?.hermes_ready || payload?.install_info?.status === 'ready');
}

async function openConfiguredDesktopMode(preferredMode?: ModeId, settingsOverride?: UiSettings | null): Promise<void> {
  const settings = settingsOverride || await waitForUiSettings();
  if (settings) lastUiSettings = settings;
  const mode = preferredMode || normalizeMode(settings?.display?.current_mode);
  const config = settings?.mode_settings?.[mode]?.config || {};
  createDesktopModeWindow(mode, config);
}

async function showOpenDialogForSender(
  event: IpcMainInvokeEvent,
  options: OpenDialogOptions,
): Promise<string | null> {
  const parentWindow = BrowserWindow.fromWebContents(event.sender) || mainWindow || undefined;
  const result = parentWindow
    ? await dialog.showOpenDialog(parentWindow, options)
    : await dialog.showOpenDialog(options);
  if (result.canceled) return null;
  return result.filePaths[0] || null;
}

ipcMain.handle('hermes:getBridgeUrl', () => BRIDGE_URL);
ipcMain.handle('hermes:quit', () => {
  app.quit();
});
ipcMain.handle('hermes:restartApp', () => {
  app.relaunch();
  app.quit();
});
ipcMain.handle('hermes:copyText', (_event, value: unknown) => {
  clipboard.writeText(typeof value === 'string' ? value : '');
});
ipcMain.handle('hermes:chooseLive2DModelDirectory', (event) => showOpenDialogForSender(event, {
  title: '选择 Live2D 模型目录',
  defaultPath: app.getPath('home'),
  properties: ['openDirectory'],
}));
ipcMain.handle('hermes:chooseLive2DArchive', (event) => showOpenDialogForSender(event, {
  title: '导入 Live2D 资源包 ZIP',
  defaultPath: app.getPath('home'),
  properties: ['openFile'],
  filters: [
    { name: 'Live2D 资源包', extensions: ['zip'] },
    { name: '压缩包', extensions: ['zip'] },
  ],
}));
ipcMain.handle('hermes:openPath', async (_event, value: unknown) => {
  const targetPath = typeof value === 'string' ? value.trim() : '';
  if (!targetPath) throw new Error('路径不能为空');
  const error = await shell.openPath(targetPath);
  if (error) throw new Error(error);
});
ipcMain.handle('hermes:openExternalUrl', async (_event, value: unknown) => {
  const targetUrl = typeof value === 'string' ? value.trim() : '';
  if (!/^https?:\/\//.test(targetUrl)) throw new Error('仅支持打开 http(s) 链接');
  await shell.openExternal(targetUrl);
});
ipcMain.handle('hermes:openView', (_event, view: unknown, params: unknown) => {
  openAppView(normalizeView(view), normalizeParams(params));
});
ipcMain.handle('hermes:openDesktopMode', (_event, mode: unknown) => openConfiguredDesktopMode(normalizeMode(mode)));
ipcMain.handle('hermes:moveLauncherWindow', moveLauncherWindow);
ipcMain.handle('hermes:getLauncherPointerState', (_event, mode: unknown) => launcherPointerState(mode));
ipcMain.handle('hermes:setLauncherHitRegions', (event, mode: unknown, regions: unknown) => {
  const targetWindow = BrowserWindow.fromWebContents(event.sender);
  if (!targetWindow || targetWindow !== modeWindow) return false;
  return setModeWindowHitRegions(normalizeMode(mode), regions);
});
ipcMain.handle('hermes:setLauncherPointerInteractive', (event, mode: unknown, interactive: unknown) => {
  const targetWindow = BrowserWindow.fromWebContents(event.sender);
  if (!targetWindow || targetWindow !== modeWindow) return false;
  return setModeWindowPointerInteractive(normalizeMode(mode), Boolean(interactive));
});
ipcMain.handle('hermes:openLauncherMenu', (event, mode: unknown) => {
  const modeId = normalizeMode(mode);
  const targetWindow = BrowserWindow.fromWebContents(event.sender) || undefined;
  const menu = Menu.buildFromTemplate([
    { label: '打开对话', click: () => showChatWindow() },
    { label: '主控台', click: () => showMainWindow({ view: 'main' }) },
    { label: `${modeId === 'live2d' ? 'Live2D' : 'Bubble'} 设置`, click: () => showMainWindow({ view: 'settings', mode: modeId }) },
    { type: 'separator' },
    { label: '重新打开表现态', click: () => void openConfiguredDesktopMode(modeId) },
    {
      label: '关闭表现态',
      click: () => {
        const windowToClose = targetWindow === modeWindow ? targetWindow : activeMode === modeId ? modeWindow : null;
        if (windowToClose && !windowToClose.isDestroyed()) windowToClose.close();
      },
    },
    { label: '退出 Hermes-Yachiyo', click: () => app.quit() },
  ]);
  menu.popup({ window: targetWindow });
});

app.whenReady().then(() => {
  showMacDockIcon();
  startBackend();
	  void (async () => {
	    const installInfo = await waitForInstallInfo();
	    lastInstallReady = installReady(installInfo);
	    if (!lastInstallReady) {
	      createMainWindow({ view: 'installer' });
	      return;
	    }
	    const settings = await waitForUiSettings();
	    if (settings) lastUiSettings = settings;
	    configureTray(settings);
	    createMainWindow({}, settings, { respectStartMinimized: true, focusOnReady: false });
	    await openConfiguredDesktopMode(undefined, settings);
	    if (settings?.window_mode?.open_chat_on_start) showChatWindow();
	  })();

	  app.on('activate', showMainWindowFromAppActivation);
});

app.on('before-quit', stopBackend);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
