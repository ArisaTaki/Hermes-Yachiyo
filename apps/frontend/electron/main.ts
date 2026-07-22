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
  type WebContents,
  type IpcMainInvokeEvent,
  type OpenDialogOptions,
  type Rectangle,
} from 'electron';
import * as nodePty from 'node-pty';
import type { IPty } from 'node-pty';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import fs from 'node:fs';
import http, { type IncomingMessage, type RequestOptions, type ServerResponse } from 'node:http';
import https from 'node:https';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  buildMacAppUpdateInstallerScript,
  isVerifiedDownloadedUpdate,
  normalizeSha256,
  OFFICIAL_APP_BUNDLE_ID,
  OFFICIAL_UPDATE_REPOSITORY,
  trustedUpdateTarget,
  validateTrustedLatestMetadata,
} from './appUpdaterPolicy.js';
import { CuaMcpBridge } from './cuaMcpBridge.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const FRONTEND_DEV_URL = process.env.OHA_YACHIYO_FRONTEND_DEV_URL || 'http://127.0.0.1:5174';
const BRIDGE_URL_ENV = 'OHA_YACHIYO_BRIDGE_URL';
const BRIDGE_TOKEN_ENV = 'OHA_YACHIYO_BRIDGE_TOKEN';
const ELECTRON_NATIVE_URL_ENV = 'OHA_YACHIYO_ELECTRON_NATIVE_URL';
const ELECTRON_NATIVE_TOKEN_ENV = 'OHA_YACHIYO_ELECTRON_NATIVE_TOKEN';
const ELECTRON_NATIVE_BRIDGE_SMOKE_ENV = 'OHA_YACHIYO_ELECTRON_NATIVE_BRIDGE_SMOKE';
const ELECTRON_NATIVE_BRIDGE_SMOKE_APP_ENV = 'OHA_YACHIYO_ELECTRON_NATIVE_BRIDGE_SMOKE_APP';
const DESKTOP_SMOKE_MODE_ENV = 'OHA_YACHIYO_DESKTOP_SMOKE_MODE';
const ELECTRON_PROCESS_SMOKE_ROOT_ENV = 'OHA_YACHIYO_ELECTRON_SMOKE_ROOT';
const ELECTRON_PROCESS_SMOKE_LEDGER_ENV = 'OHA_YACHIYO_ELECTRON_SMOKE_LEDGER';
const ELECTRON_PARENT_PID_ENV = 'OHA_YACHIYO_ELECTRON_PARENT_PID';
const ELECTRON_PARENT_TOKEN_ENV = 'OHA_YACHIYO_ELECTRON_PARENT_TOKEN';
const CUA_DRIVER_PATH_ENV = 'OHA_YACHIYO_CUA_DRIVER_PATH';
const CUA_DRIVER_COMMAND_ENV = 'OHA_YACHIYO_CUA_DRIVER_COMMAND';
const CUA_HOST_BUNDLE_ID_ENV = 'OHA_YACHIYO_CUA_HOST_BUNDLE_ID';
const CUA_MCP_TRANSPORT_ENV = 'OHA_YACHIYO_CUA_MCP_TRANSPORT';
const CUA_MCP_BRIDGE_URL_ENV = 'OHA_YACHIYO_CUA_MCP_BRIDGE_URL';
const CUA_MCP_BRIDGE_TOKEN_ENV = 'OHA_YACHIYO_CUA_MCP_BRIDGE_TOKEN';
const CUA_MCP_BRIDGE_GENERATION_ENV = 'OHA_YACHIYO_CUA_MCP_BRIDGE_GENERATION';
const CUA_MCP_ELECTRON_BRIDGE_TRANSPORT = 'electron-bridge-v1';
const CHAT_IMAGE_PICKER_SMOKE_PATHS_ENV = 'OHA_YACHIYO_CHAT_IMAGE_PICKER_SMOKE_PATHS';
const DEV_BRIDGE_URL = 'http://127.0.0.1:8420';
const PACKAGED_BRIDGE_URL = 'http://127.0.0.1:18420';
let bridgeUrl = initialBridgeUrl();
let bridgeSessionToken = process.env[BRIDGE_TOKEN_ENV] || randomBytes(32).toString('hex');
const APP_BUILD_METADATA_FILE = 'oha-yachiyo-build.json';
const DEFAULT_UPDATE_REPOSITORY = OFFICIAL_UPDATE_REPOSITORY;
const TRUSTED_UPDATE_NETWORK_HOSTS = new Set([
  'github.com',
  'api.github.com',
  'release-assets.githubusercontent.com',
  'objects.githubusercontent.com',
  'github-releases.githubusercontent.com',
]);
const GITHUB_COMPARE_COMMIT_LIMIT = 100;
const CHANGELOG_CATEGORY_ORDER = [
  '新增/改进',
  '修复',
  '工程/发布',
  '文档',
  '测试',
  '重构/优化',
  '其他',
];
const CHANGELOG_CATEGORY_BY_KIND: Record<string, string> = {
  add: '新增/改进',
  feat: '新增/改进',
  feature: '新增/改进',
  fix: '修复',
  hotfix: '修复',
  bugfix: '修复',
  ci: '工程/发布',
  build: '工程/发布',
  chore: '工程/发布',
  release: '工程/发布',
  docs: '文档',
  doc: '文档',
  test: '测试',
  tests: '测试',
  refactor: '重构/优化',
  perf: '重构/优化',
  style: '重构/优化',
};
const BRIDGE_SETTINGS_RETRIES = 40;
const BRIDGE_SETTINGS_RETRY_MS = 250;
const BUBBLE_SCREEN_MARGIN = 24;
const BUBBLE_MIN_WINDOW_SIZE = 112;
const BUBBLE_DEFAULT_WINDOW_SIZE = 112;
const BUBBLE_MAX_WINDOW_SIZE = 192;
const POSITION_SAVE_DEBOUNCE_MS = 260;
const LIVE2D_POINTER_PASSTHROUGH_ENABLED = true;
const TRANSPARENT_WINDOW_BACKGROUND = '#00000000';
const MIN_APP_WINDOW_WIDTH = 1250;
const MIN_APP_WINDOW_HEIGHT = 860;
const UI_RENDER_REVISION = 'open-design-v4-moon-bubble-scrollbar-gutter-v3-20260512';
const MAX_LAUNCHER_SHAPE_RECTS = 10000;
const MAX_AVATAR_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_CHAT_IMAGE_BYTES = 8 * 1024 * 1024;
type IconKind = 'dock' | 'tray' | 'window';

type AppView =
  | 'main'
  | 'chat'
  | 'agents'
  | 'settings'
  | 'provider'
  | 'resources'
  | 'workspace'
  | 'diagnostics'
  | 'tools'
  | 'tools-all'
  | 'activity-all'
  | 'activity-detail'
  | 'app-update'
  | 'proactive-tts'
  | 'bubble'
  | 'bubble-menu'
  | 'live2d';
type ModeId = 'bubble' | 'live2d';
type DisplayModeId = ModeId | 'none';
type DesktopTerminalTask = 'mac-prerequisites';
type MainRoute = { view: AppView; params: Record<string, string> };

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

type NativeCommandResult = {
  exitCode: number | null;
  signal: NodeJS.Signals | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
};

type NativeFocusSnapshot = {
  app_name: string;
  focus_verified: boolean;
  focus_status: 'frontmost' | 'not_frontmost';
  frontmost_app: string;
  process_visible?: boolean;
  window_count?: number;
  system_events_reported_frontmost?: boolean;
  appkit_reported_active?: boolean;
  appkit_activate_result?: string;
  launchservices_returncode?: number;
  blocking_condition?: string;
  retryable?: boolean;
  native_bridge: 'electron_main';
  native_attempts: Array<Record<string, unknown>>;
};

type NativeToolResult = {
  ok: boolean;
  action: string;
  summary: string;
  data: Record<string, unknown>;
  error?: string;
  blocking_condition?: string;
  retryable?: boolean;
  missing_permissions?: string[];
  permission_targets?: string[];
  recovery_hints?: string[];
  permission_error: boolean;
  fallback_used: boolean;
};

type AppBuildMetadata = {
  name: string;
  channel: string;
  branch: string;
  version: string;
  base_version?: string;
  commit: string;
  short_commit?: string;
  build_number?: number;
  repository: string;
  latest_json_url: string;
  built_at?: string;
};

type ReleaseChangelogCommit = {
  commit?: string;
  short_commit?: string;
  author?: string;
  authored_at?: string;
  subject?: string;
  category?: string;
  url?: string | null;
};

type ReleaseChangelogSection = {
  title?: string;
  items?: ReleaseChangelogCommit[];
};

type ReleaseChangelog = {
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

type GitHubCompareCommit = {
  sha?: string;
  html_url?: string;
  commit?: {
    author?: {
      name?: string;
      date?: string;
    };
    message?: string;
  };
};

type GitHubCompareResponse = {
  html_url?: string;
  total_commits?: number;
  commits?: GitHubCompareCommit[];
};

type LatestReleaseMetadata = {
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
  dirty?: boolean;
  release_publishable?: boolean;
  source_tree_fingerprint?: string;
  published_at?: string;
  changelog?: ReleaseChangelog;
};

type AppUpdateInfo = {
  supported: boolean;
  packaged: boolean;
  current: AppBuildMetadata;
  latest_json_url: string;
  app_bundle_path?: string;
  downloaded_dmg_path?: string;
  downloaded_update?: AppUpdateDownloadResult;
  error?: string;
};

type AppUpdateCheckResult = AppUpdateInfo & {
  ok: boolean;
  update_available: boolean;
  latest?: LatestReleaseMetadata;
  reason?: string;
};

type AppUpdateDownloadResult = {
  ok: boolean;
  path?: string;
  file_name?: string;
  sha256?: string;
  verified?: boolean;
  latest?: LatestReleaseMetadata;
  error?: string;
  cancelled?: boolean;
};

type AppUpdateDownloadProgress = {
  status: 'starting' | 'downloading' | 'verifying' | 'completed' | 'failed' | 'cancelled';
  file_name?: string;
  received_bytes?: number;
  total_bytes?: number;
  percent?: number;
  error?: string;
};

type AppUpdateDownloadTask = {
  controller: AbortController;
  destination?: string;
  tmpDestination?: string;
  fileName?: string;
  onProgress?: (progress: AppUpdateDownloadProgress) => void;
};

type AvatarImageSelection = {
  path: string;
  data_url: string;
  file_name: string;
};

type ChatImageSelection = AvatarImageSelection & {
  mime_type: string;
  size: number;
  width?: number;
  height?: number;
};

let backendProcess: ChildProcessWithoutNullStreams | null = null;
let cuaMcpBridge: CuaMcpBridge | null = null;
let cuaMcpBridgeUrl = '';
let cuaMcpBridgeToken = randomBytes(32).toString('hex');
let cuaMcpBridgeGeneration = randomBytes(12).toString('hex');
let nativeRuntimeServer: http.Server | null = null;
let nativeRuntimeUrl = '';
let mainWindow: BrowserWindow | null = null;
let chatWindow: BrowserWindow | null = null;
let modeWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let activeMode: ModeId | null = null;
let activeModeConfig: Record<string, unknown> = {};
let activeModeConfigSignature = '';
let positionSaveTimer: NodeJS.Timeout | null = null;
let positionSaveSuppressedUntil = 0;
let modeWindowIgnoringMouse = false;
let modeWindowShapeApplied = false;
let modeWindowTopSuppressed = false;
let lastUiSettings: UiSettings | null = null;
let lastMainWindowRoute: MainRoute | null = null;
let hasEnteredMainExperience = false;
let backendRestartPromise: Promise<{ success: boolean; bridgeUrl?: string; error?: string }> | null = null;
let lastDownloadedAppUpdate: AppUpdateDownloadResult | null = null;
let activeAppUpdateDownload: AppUpdateDownloadTask | null = null;
let appUpdateQuitConfirmed = false;
let appShutdownRequested = false;
let backendShutdownBeforeQuit = false;
let backendShutdownPromise: Promise<void> | null = null;
let backendTerminationPromise: Promise<void> | null = null;
let electronProcessSmokeLedgerPath = '';
const electronProcessToken = randomBytes(16).toString('hex');
const appUpdateCloseConfirmedWindows = new WeakSet<BrowserWindow>();
const enforcedWindowTitles = new WeakMap<BrowserWindow, string>();
const titleHandlersInstalled = new WeakSet<BrowserWindow>();
const terminalSessions = new Map<string, {
  ownerId: number;
  pty: IPty;
  sender: WebContents;
  task: DesktopTerminalTask;
}>();

type MainWindowOptions = {
  respectStartMinimized?: boolean;
  focusOnReady?: boolean;
};

app.setName('Oha-Yachiyo');
try {
  configureElectronProcessSmoke();
} catch {
  console.error('[electron-process-smoke] configuration rejected');
  app.exit(1);
  process.exit(1);
}
showMacDockIcon();

function configureElectronProcessSmoke(): void {
  if (process.env[DESKTOP_SMOKE_MODE_ENV] !== '1') return;
  const configuredRoot = process.env[ELECTRON_PROCESS_SMOKE_ROOT_ENV]?.trim();
  if (!configuredRoot) return;
  if (!path.isAbsolute(configuredRoot)) {
    throw new Error(`${ELECTRON_PROCESS_SMOKE_ROOT_ENV} must be an absolute path`);
  }
  let smokeRootStat: ReturnType<typeof fs.lstatSync>;
  try {
    smokeRootStat = fs.lstatSync(configuredRoot);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    fs.mkdirSync(configuredRoot, { recursive: true, mode: 0o700 });
    smokeRootStat = fs.lstatSync(configuredRoot);
  }
  if (smokeRootStat.isSymbolicLink() || !smokeRootStat.isDirectory()) {
    throw new Error(`${ELECTRON_PROCESS_SMOKE_ROOT_ENV} must be a real directory`);
  }
  const smokeRoot = fs.realpathSync(configuredRoot);
  const temporaryRoot = fs.realpathSync(os.tmpdir());
  const relativeToTemporaryRoot = path.relative(temporaryRoot, smokeRoot);
  if (
    !relativeToTemporaryRoot
    || relativeToTemporaryRoot === '..'
    || relativeToTemporaryRoot.startsWith(`..${path.sep}`)
    || path.isAbsolute(relativeToTemporaryRoot)
  ) {
    throw new Error(`${ELECTRON_PROCESS_SMOKE_ROOT_ENV} must stay inside the system temporary directory`);
  }
  fs.chmodSync(smokeRoot, 0o700);
  const smokeUserDataPath = path.join(smokeRoot, 'user-data');
  let smokeUserDataStat: ReturnType<typeof fs.lstatSync>;
  try {
    smokeUserDataStat = fs.lstatSync(smokeUserDataPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    fs.mkdirSync(smokeUserDataPath, { recursive: false, mode: 0o700 });
    smokeUserDataStat = fs.lstatSync(smokeUserDataPath);
  }
  if (smokeUserDataStat.isSymbolicLink() || !smokeUserDataStat.isDirectory()) {
    throw new Error('Electron process smoke userData must be a real directory');
  }
  fs.chmodSync(smokeUserDataPath, 0o700);
  app.setPath('userData', smokeUserDataPath);
  electronProcessSmokeLedgerPath = path.join(smokeRoot, 'electron-lifecycle.jsonl');
  if (fs.existsSync(electronProcessSmokeLedgerPath)) {
    const ledgerStat = fs.lstatSync(electronProcessSmokeLedgerPath);
    if (ledgerStat.isSymbolicLink() || !ledgerStat.isFile()) {
      throw new Error('Electron process smoke ledger must be a regular file');
    }
  }
  process.env[ELECTRON_PROCESS_SMOKE_LEDGER_ENV] = electronProcessSmokeLedgerPath;
  recordElectronProcessSmoke('process.configured', {
    smoke_root: smokeRoot,
    user_data: smokeUserDataPath,
  });
}

function recordElectronProcessSmoke(event: string, details: Record<string, unknown> = {}): void {
  if (!electronProcessSmokeLedgerPath) return;
  const payload = {
    event,
    at: new Date().toISOString(),
    electron_pid: process.pid,
    process_token: electronProcessToken,
    recorder: 'electron-main',
    ...details,
  };
  const descriptor = fs.openSync(
    electronProcessSmokeLedgerPath,
    fs.constants.O_WRONLY
      | fs.constants.O_APPEND
      | fs.constants.O_CREAT
      | (fs.constants.O_NOFOLLOW || 0),
    0o600,
  );
  try {
    if (!fs.fstatSync(descriptor).isFile()) {
      throw new Error('Electron process smoke ledger must stay a regular file');
    }
    fs.writeSync(descriptor, `${JSON.stringify(payload)}\n`, null, 'utf8');
  } finally {
    fs.closeSync(descriptor);
  }
}

function recordSecondInstanceWindowFocus(attempt = 0): void {
  if (!electronProcessSmokeLedgerPath) return;
  const targetWindow = mainWindow;
  if (targetWindow && !targetWindow.isDestroyed() && !targetWindow.isFocused()) {
    if (process.platform === 'darwin') app.focus({ steal: true });
    targetWindow.show();
    targetWindow.moveTop();
    targetWindow.focus();
  }
  const focused = Boolean(targetWindow && !targetWindow.isDestroyed() && targetWindow.isFocused());
  recordElectronProcessSmoke('window.focus', {
    source: 'second-instance',
    attempt,
    focused,
    visible: Boolean(targetWindow && !targetWindow.isDestroyed() && targetWindow.isVisible()),
    minimized: Boolean(targetWindow && !targetWindow.isDestroyed() && targetWindow.isMinimized()),
  });
  if (!focused && attempt < 10) {
    setTimeout(() => recordSecondInstanceWindowFocus(attempt + 1), 50);
  }
}

function projectRoot(): string {
  return path.resolve(__dirname, '..', '..', '..');
}

function rootAssetPath(...segments: string[]): string | null {
  const roots = app.isPackaged
    ? [process.resourcesPath, path.join(process.resourcesPath, 'app.asar.unpacked'), projectRoot()]
    : [projectRoot()];
  for (const root of roots) {
    const candidate = path.join(root, ...segments);
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function nativeJsonResponse(response: ServerResponse, statusCode: number, payload: NativeToolResult | Record<string, unknown>): void {
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  response.end(JSON.stringify(payload));
}

function nativeRequestToken(request: IncomingMessage): string {
  const value = request.headers['x-oha-yachiyo-bridge-token'];
  if (Array.isArray(value)) return value[0] || '';
  return typeof value === 'string' ? value : '';
}

function isLoopbackRemoteAddress(value: string | undefined): boolean {
  return value === '127.0.0.1' || value === '::1' || value === '::ffff:127.0.0.1';
}

function nativeBridgeRequestAllowed(request: IncomingMessage): boolean {
  return isLoopbackRemoteAddress(request.socket.remoteAddress) && nativeRequestToken(request) === bridgeSessionToken;
}

function readNativeJsonBody(request: IncomingMessage, maxBytes = 64 * 1024): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let body = '';
    request.on('data', (chunk: Buffer | string) => {
      body += chunk.toString();
      if (Buffer.byteLength(body, 'utf8') > maxBytes) {
        reject(new Error('request_body_too_large'));
        request.destroy();
      }
    });
    request.on('end', () => {
      if (!body.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error('invalid_json'));
      }
    });
    request.on('error', reject);
  });
}

function runNativeCommand(command: string, args: string[], timeoutMs = 5000): Promise<NativeCommandResult> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;
    const timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill('SIGKILL');
      } catch {}
    }, timeoutMs);
    const finish = (exitCode: number | null, signal: NodeJS.Signals | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ exitCode, signal, stdout: stdout.trim(), stderr: stderr.trim(), timedOut });
    };
    child.stdout.on('data', (chunk: Buffer | string) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk: Buffer | string) => {
      stderr += chunk.toString();
    });
    child.once('error', (error) => {
      stderr = stderr ? `${stderr}\n${error.message}` : error.message;
      finish(null, null);
    });
    child.once('exit', finish);
  });
}

function parseNativeBoolean(value: string | undefined): boolean | undefined {
  if (value === 'true') return true;
  if (value === 'false') return false;
  return undefined;
}

function parseNativeInteger(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function compactAppName(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/[\W_]+/gu, '');
}

function nativeFocusAttempt(
  strategy: string,
  result: NativeCommandResult,
): Record<string, unknown> {
  return {
    strategy,
    ok: result.exitCode === 0,
    exit_code: result.exitCode,
    timed_out: result.timedOut,
    stderr: result.stderr || undefined,
  };
}

function nativeSystemEventsFocusScript(): string {
  return `
on run argv
  set appName to item 1 of argv
  try
    tell application appName to activate
  end try
  try
    tell application appName to reopen
  end try
  delay 0.2
  set targetFrontmost to false
  set targetVisible to ""
  set targetWindowCount to ""
  set frontName to ""
  tell application "System Events"
    try
      set targetProc to first application process whose name is appName
      try
        set visible of targetProc to true
      end try
      try
        set frontmost of targetProc to true
        delay 0.1
      end try
      try
        set targetFrontmost to frontmost of targetProc
      end try
      try
        set targetVisible to visible of targetProc
      end try
      try
        set targetWindowCount to count of windows of targetProc
      end try
    end try
    try
      set frontName to name of first application process whose frontmost is true
    end try
  end tell
  return "focused|" & appName & "|" & (targetFrontmost as text) & "|" & frontName & "|" & (targetVisible as text) & "|" & (targetWindowCount as text)
end run
`;
}

function nativeAppKitFocusScript(): string {
  return `
function run(argv) {
  ObjC.import("AppKit");
  const requestedName = String(argv[0] || "");
  const workspace = $.NSWorkspace.sharedWorkspace;
  const apps = workspace.runningApplications;
  let target = null;
  for (let index = 0; index < apps.count; index += 1) {
    const app = apps.objectAtIndex(index);
    const localizedName = app.localizedName ? ObjC.unwrap(app.localizedName) : "";
    if (localizedName === requestedName) {
      target = app;
      break;
    }
  }
  const frontBefore = workspace.frontmostApplication;
  const frontBeforeName = frontBefore && frontBefore.localizedName ? ObjC.unwrap(frontBefore.localizedName) : "";
  if (!target) {
    return "appkit|" + requestedName + "|missing|false|" + frontBeforeName;
  }
  const activateResult = target.activateWithOptions(
    $.NSApplicationActivateAllWindows | $.NSApplicationActivateIgnoringOtherApps
  );
  delay(0.2);
  const frontAfter = workspace.frontmostApplication;
  const frontAfterName = frontAfter && frontAfter.localizedName ? ObjC.unwrap(frontAfter.localizedName) : "";
  return "appkit|" + requestedName + "|" + activateResult + "|" + target.active + "|" + frontAfterName;
}
`;
}

function parseNativeFocusSnapshot(
  value: string,
  fallbackAppName: string,
  nativeAttempts: Array<Record<string, unknown>>,
): NativeFocusSnapshot {
  const parts = value.trim().split('|', 6);
  const appName = parts[1] || fallbackAppName;
  const frontmostText = parts[2] || '';
  const frontmostApp = parts[3] || '';
  const focusVerified = Boolean(appName && frontmostApp && compactAppName(appName) === compactAppName(frontmostApp));
  const snapshot: NativeFocusSnapshot = {
    app_name: appName,
    focus_verified: focusVerified,
    focus_status: focusVerified ? 'frontmost' : 'not_frontmost',
    frontmost_app: frontmostApp,
    native_bridge: 'electron_main',
    native_attempts: nativeAttempts,
  };
  const systemEventsReportedFrontmost = parseNativeBoolean(frontmostText);
  if (systemEventsReportedFrontmost !== undefined) {
    snapshot.system_events_reported_frontmost = systemEventsReportedFrontmost;
  }
  const processVisible = parseNativeBoolean(parts[4]);
  if (processVisible !== undefined) snapshot.process_visible = processVisible;
  const windowCount = parseNativeInteger(parts[5]);
  if (windowCount !== undefined) snapshot.window_count = windowCount;
  return snapshot;
}

function parseNativeAppKitFocusSnapshot(
  value: string,
  fallbackAppName: string,
  nativeAttempts: Array<Record<string, unknown>>,
): NativeFocusSnapshot {
  const parts = value.trim().split('|', 5);
  const appName = parts[1] || fallbackAppName;
  const activateResult = parts[2] || '';
  const activeText = parts[3] || '';
  const frontmostApp = parts[4] || '';
  const focusVerified = Boolean(appName && frontmostApp && compactAppName(appName) === compactAppName(frontmostApp));
  const snapshot: NativeFocusSnapshot = {
    app_name: appName,
    focus_verified: focusVerified,
    focus_status: focusVerified ? 'frontmost' : 'not_frontmost',
    frontmost_app: frontmostApp,
    appkit_activate_result: activateResult,
    native_bridge: 'electron_main',
    native_attempts: nativeAttempts,
  };
  const appKitReportedActive = parseNativeBoolean(activeText);
  if (appKitReportedActive !== undefined) {
    snapshot.appkit_reported_active = appKitReportedActive;
  }
  return snapshot;
}

function nativeFocusToolResult(snapshot: NativeFocusSnapshot): NativeToolResult {
  if (snapshot.focus_verified) {
    return {
      ok: true,
      action: 'electron.native.desktop.focus',
      summary: `Focused ${snapshot.app_name} via Electron native bridge`,
      data: snapshot,
      permission_error: false,
      fallback_used: snapshot.native_attempts.length > 2,
    };
  }
  const data = {
    ...snapshot,
    blocking_condition: 'foreground_focus_unavailable',
    retryable: true,
  };
  return {
    ok: false,
    action: 'electron.native.desktop.focus',
    summary: `Could not verify ${snapshot.app_name} is foreground via Electron native bridge`,
    error: 'app_focus_not_verified',
    blocking_condition: 'foreground_focus_unavailable',
    retryable: true,
    data,
    missing_permissions: ['foreground_focus'],
    permission_targets: ['foreground_focus'],
    recovery_hints: [
      'Allow the current Oha-Yachiyo runtime to bring target apps to the foreground. Check Automation and Accessibility permissions in macOS System Settings > Privacy & Security.',
    ],
    permission_error: false,
    fallback_used: snapshot.native_attempts.length > 2,
  };
}

const NATIVE_FOCUS_OPEN_TIMEOUT_MS = 700;
const NATIVE_FOCUS_SYSTEM_EVENTS_TIMEOUT_MS = 1300;
const NATIVE_FOCUS_APPKIT_TIMEOUT_MS = 1100;

async function electronNativeFocusApp(appName: string): Promise<NativeToolResult> {
  if (process.platform !== 'darwin') {
    return {
      ok: false,
      action: 'electron.native.desktop.focus',
      summary: 'electron.native.desktop.focus is not supported on this platform yet.',
      error: 'unsupported_platform',
      data: { platform: process.platform },
      permission_error: false,
      fallback_used: false,
    };
  }
  const cleanAppName = appName.trim();
  if (!cleanAppName) {
    return {
      ok: false,
      action: 'electron.native.desktop.focus',
      summary: 'electron.native.desktop.focus failed',
      error: 'app_name_required',
      data: {},
      permission_error: false,
      fallback_used: false,
    };
  }
  const attempts: Array<Record<string, unknown>> = [];
  const openResult = await runNativeCommand(
    '/usr/bin/open',
    ['-a', cleanAppName],
    NATIVE_FOCUS_OPEN_TIMEOUT_MS,
  );
  attempts.push(nativeFocusAttempt('electron_open_a', openResult));
  const verifyScript = nativeSystemEventsFocusScript();
  const verifyResult = await runNativeCommand(
    '/usr/bin/osascript',
    ['-e', verifyScript, cleanAppName],
    NATIVE_FOCUS_SYSTEM_EVENTS_TIMEOUT_MS,
  );
  attempts.push(nativeFocusAttempt('electron_system_events_verify', verifyResult));
  let latestSnapshot: NativeFocusSnapshot = {
    app_name: cleanAppName,
    focus_verified: false,
    focus_status: 'not_frontmost',
    frontmost_app: '',
    native_bridge: 'electron_main',
    native_attempts: attempts,
  };
  if (verifyResult.exitCode === 0) {
    latestSnapshot = parseNativeFocusSnapshot(verifyResult.stdout, cleanAppName, attempts);
    if (latestSnapshot.focus_verified) return nativeFocusToolResult(latestSnapshot);
  }

  const appKitResult = await runNativeCommand(
    '/usr/bin/osascript',
    ['-l', 'JavaScript', '-e', nativeAppKitFocusScript(), cleanAppName],
    NATIVE_FOCUS_APPKIT_TIMEOUT_MS,
  );
  attempts.push(nativeFocusAttempt('electron_appkit_nsrunningapplication', appKitResult));
  if (appKitResult.exitCode === 0) {
    latestSnapshot = parseNativeAppKitFocusSnapshot(appKitResult.stdout, cleanAppName, attempts);
    if (latestSnapshot.focus_verified) return nativeFocusToolResult(latestSnapshot);
  }

  const launchServicesResult = await runNativeCommand(
    '/usr/bin/open',
    ['-a', cleanAppName],
    NATIVE_FOCUS_OPEN_TIMEOUT_MS,
  );
  attempts.push(nativeFocusAttempt('electron_launchservices_open_a', launchServicesResult));
  const launchVerifyResult = await runNativeCommand(
    '/usr/bin/osascript',
    ['-e', verifyScript, cleanAppName],
    NATIVE_FOCUS_SYSTEM_EVENTS_TIMEOUT_MS,
  );
  attempts.push(nativeFocusAttempt('electron_launchservices_verify', launchVerifyResult));
  if (launchVerifyResult.exitCode === 0) {
    latestSnapshot = parseNativeFocusSnapshot(launchVerifyResult.stdout, cleanAppName, attempts);
    latestSnapshot.launchservices_returncode = launchServicesResult.exitCode ?? undefined;
  }
  return nativeFocusToolResult(latestSnapshot);
}

async function handleNativeRuntimeRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
  if (!nativeBridgeRequestAllowed(request)) {
    nativeJsonResponse(response, 403, {
      ok: false,
      error: 'invalid_native_bridge_token',
      summary: 'native runtime bridge request rejected',
    });
    return;
  }
  const url = new URL(request.url || '/', nativeRuntimeUrl || 'http://127.0.0.1');
  if (request.method === 'GET' && url.pathname === '/status') {
    nativeJsonResponse(response, 200, {
      ok: true,
      service: 'oha-yachiyo-electron-native-runtime',
      platform: process.platform,
    });
    return;
  }
  if (request.method === 'POST' && url.pathname === '/native/desktop/focus') {
    try {
      const body = await readNativeJsonBody(request);
      const appName = typeof body === 'object' && body && 'app_name' in body
        ? String((body as { app_name?: unknown }).app_name || '')
        : '';
      const result = await electronNativeFocusApp(appName);
      nativeJsonResponse(response, result.ok ? 200 : 409, result);
    } catch (error) {
      nativeJsonResponse(response, 400, {
        ok: false,
        action: 'electron.native.desktop.focus',
        summary: 'electron.native.desktop.focus failed',
        error: error instanceof Error ? error.message : String(error),
        data: {},
        permission_error: false,
        fallback_used: false,
      });
    }
    return;
  }
  nativeJsonResponse(response, 404, {
    ok: false,
    error: 'native_bridge_route_not_found',
    summary: 'native runtime bridge route not found',
  });
}

function startNativeRuntimeServer(): Promise<void> {
  if (nativeRuntimeServer) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const server = http.createServer((request, response) => {
      void handleNativeRuntimeRequest(request, response);
    });
    server.once('error', reject);
    server.once('listening', () => {
      const address = server.address();
      const port = typeof address === 'object' && address && 'port' in address ? address.port : null;
      if (!port) {
        server.close();
        reject(new Error('Could not allocate native runtime bridge port'));
        return;
      }
      nativeRuntimeServer = server;
      nativeRuntimeUrl = `http://127.0.0.1:${port}`;
      resolve();
    });
    server.listen({ host: '127.0.0.1', port: 0 });
  });
}

function closeNativeRuntimeServer(): void {
  const server = nativeRuntimeServer;
  nativeRuntimeServer = null;
  nativeRuntimeUrl = '';
  if (!server) return;
  try {
    server.close();
  } catch {}
}

function requestNativeBridgeJson(
  method: string,
  routePath: string,
  token: string,
  body?: Record<string, unknown>,
): Promise<{ statusCode: number; payload: Record<string, unknown>; rawBody: string }> {
  return new Promise((resolve, reject) => {
    if (!nativeRuntimeUrl) {
      reject(new Error('native_runtime_bridge_not_started'));
      return;
    }
    const target = new URL(routePath, nativeRuntimeUrl);
    const rawBody = body === undefined ? '' : JSON.stringify(body);
    const request = http.request(
      {
        hostname: target.hostname,
        port: Number(target.port),
        path: `${target.pathname}${target.search}`,
        method,
        headers: {
          ...(token ? { 'x-oha-yachiyo-bridge-token': token } : {}),
          ...(rawBody ? {
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(rawBody),
          } : {}),
        },
        timeout: 7000,
      },
      (response) => {
        let responseBody = '';
        response.on('data', (chunk: Buffer | string) => {
          responseBody += chunk.toString();
        });
        response.on('end', () => {
          let payload: Record<string, unknown> = {};
          try {
            payload = responseBody.trim() ? JSON.parse(responseBody) as Record<string, unknown> : {};
          } catch {
            payload = { ok: false, error: 'invalid_json', raw_body: responseBody };
          }
          resolve({
            statusCode: response.statusCode || 0,
            payload,
            rawBody: responseBody,
          });
        });
      },
    );
    request.on('timeout', () => {
      request.destroy(new Error('native_bridge_request_timeout'));
    });
    request.on('error', reject);
    if (rawBody) request.write(rawBody);
    request.end();
  });
}

async function runElectronNativeBridgeSmoke(): Promise<Record<string, unknown>> {
  const startedAt = new Date().toISOString();
  await startNativeRuntimeServer();
  const unauthenticatedStatus = await requestNativeBridgeJson('GET', '/status', '');
  const authenticatedStatus = await requestNativeBridgeJson('GET', '/status', bridgeSessionToken);
  const focusApp = String(process.env[ELECTRON_NATIVE_BRIDGE_SMOKE_APP_ENV] || '').trim();
  let focusResult: Record<string, unknown> | null = null;
  if (focusApp) {
    const response = await requestNativeBridgeJson(
      'POST',
      '/native/desktop/focus',
      bridgeSessionToken,
      { app_name: focusApp },
    );
    focusResult = {
      status_code: response.statusCode,
      payload: response.payload,
    };
  }
  const focusPayload = (
    focusResult?.payload
    && typeof focusResult.payload === 'object'
  ) ? focusResult.payload as Record<string, unknown> : {};
  const focusData = (
    focusPayload
    && typeof focusPayload === 'object'
    && 'data' in focusPayload
    && typeof focusPayload.data === 'object'
    && focusPayload.data
  ) ? focusPayload.data as Record<string, unknown> : {};
  const focusVerified = Boolean(
    focusApp
    && focusPayload?.ok === true
    && focusData.focus_verified === true
  );
  const ok = (
    unauthenticatedStatus.statusCode === 403
    && unauthenticatedStatus.payload.error === 'invalid_native_bridge_token'
    && authenticatedStatus.statusCode === 200
    && authenticatedStatus.payload.ok === true
    && authenticatedStatus.payload.service === 'oha-yachiyo-electron-native-runtime'
    && (!focusApp || focusVerified)
  );
  return {
    ok,
    mode: 'electron_native_bridge_smoke',
    started_at: startedAt,
    platform: process.platform,
    native_runtime_url: nativeRuntimeUrl,
    authenticated_status: {
      status_code: authenticatedStatus.statusCode,
      payload: authenticatedStatus.payload,
    },
    unauthenticated_status: {
      status_code: unauthenticatedStatus.statusCode,
      payload: unauthenticatedStatus.payload,
    },
    focus_app: focusApp || '',
    ...(focusResult ? { focus_result: focusResult } : {}),
    checks: {
      native_bridge_started: Boolean(nativeRuntimeUrl),
      unauthenticated_rejected: unauthenticatedStatus.statusCode === 403,
      authenticated_status_ok: authenticatedStatus.statusCode === 200 && authenticatedStatus.payload.ok === true,
      auth_value_not_printed: true,
      focus_attempted: Boolean(focusApp),
      ...(focusApp ? { focus_verified: focusVerified } : {}),
    },
  };
}

function defaultLatestJsonUrl(branch = 'oha-develop'): string {
  const latestBranch = branch === 'main' ? 'main' : branch === 'alpha' ? 'alpha' : 'oha-develop';
  return `https://github.com/${DEFAULT_UPDATE_REPOSITORY}/releases/download/${latestBranch}-latest/Oha-Yachiyo-${latestBranch}-latest.json`;
}

function defaultAppBuildMetadata(): AppBuildMetadata {
  return {
    name: 'Oha-Yachiyo',
    channel: 'experimental',
    branch: 'oha-develop',
    version: app.getVersion() || '0.0.0-dev',
    commit: 'dev',
    short_commit: 'dev',
    build_number: 0,
    repository: DEFAULT_UPDATE_REPOSITORY,
    latest_json_url: defaultLatestJsonUrl('develop'),
    built_at: 'dev',
  };
}

function readJsonFile<T>(filePath: string): T | null {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8')) as T;
  } catch {
    return null;
  }
}

function readAppBuildMetadata(): AppBuildMetadata {
  const fallback = defaultAppBuildMetadata();
  const candidates = [
    path.resolve(__dirname, '..', 'dist', APP_BUILD_METADATA_FILE),
    rootAssetPath('apps', 'frontend', 'public', APP_BUILD_METADATA_FILE),
    rootAssetPath('dist', APP_BUILD_METADATA_FILE),
  ].filter((candidate): candidate is string => Boolean(candidate));
  for (const candidate of candidates) {
    const data = readJsonFile<Partial<AppBuildMetadata>>(candidate);
    if (!data) continue;
    const branch = typeof data.branch === 'string' && data.branch.trim() ? data.branch.trim() : fallback.branch;
    const repository = typeof data.repository === 'string' && data.repository.trim() ? data.repository.trim() : fallback.repository;
    return {
      ...fallback,
      ...data,
      name: typeof data.name === 'string' && data.name.trim() ? data.name.trim() : fallback.name,
      channel: typeof data.channel === 'string' && data.channel.trim() ? data.channel.trim() : fallback.channel,
      branch,
      version: typeof data.version === 'string' && data.version.trim() ? data.version.trim() : fallback.version,
      commit: typeof data.commit === 'string' && data.commit.trim() ? data.commit.trim() : fallback.commit,
      repository,
      latest_json_url: typeof data.latest_json_url === 'string' && data.latest_json_url.trim()
        ? data.latest_json_url.trim()
        : defaultLatestJsonUrl(branch),
      build_number: numericBuildNumber(data.build_number) ?? fallback.build_number,
    };
  }
  return fallback;
}

function numericBuildNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.trunc(parsed);
  }
  return undefined;
}

function compareVersionStrings(left: unknown, right: unknown): number {
  if (typeof left !== 'string' || typeof right !== 'string') return 0;
  const leftParts = left.split(/[.-]/).map((part) => Number.parseInt(part, 10));
  const rightParts = right.split(/[.-]/).map((part) => Number.parseInt(part, 10));
  const maxLength = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < maxLength; index += 1) {
    const leftValue = Number.isFinite(leftParts[index]) ? leftParts[index] : 0;
    const rightValue = Number.isFinite(rightParts[index]) ? rightParts[index] : 0;
    if (leftValue > rightValue) return 1;
    if (leftValue < rightValue) return -1;
  }
  return 0;
}

function updateDownloadsDir(): string {
  return path.join(app.getPath('userData'), 'updates');
}

function updateDownloadRecordPath(): string {
  return path.join(updateDownloadsDir(), 'downloaded-update.json');
}

function normalizedUpdateDownloadPath(value: unknown, expectedFileName: string): string | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  if (!/^Oha-Yachiyo-(?:main|alpha|oha-develop)-latest\.dmg$/.test(expectedFileName)) return null;
  const resolved = path.resolve(value.trim());
  const downloads = path.resolve(updateDownloadsDir());
  const relative = path.relative(downloads, resolved);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) return null;
  if (path.basename(resolved) !== expectedFileName) return null;
  try {
    const stat = fs.lstatSync(resolved);
    if (stat.isSymbolicLink() || !stat.isFile()) return null;
  } catch {
    return null;
  }
  return resolved;
}

function downloadedUpdateIsForDifferentBuild(
  current: AppBuildMetadata,
  download: AppUpdateDownloadResult | null | undefined,
): download is AppUpdateDownloadResult {
  if (!download || !isVerifiedDownloadedUpdate(download)) return false;
  const latest = download.latest || {};
  if (compareVersionStrings(latest.version, current.version) > 0) return true;
  const currentBuild = numericBuildNumber(current.build_number);
  const latestBuild = numericBuildNumber(latest.build_number ?? latest.run_number);
  if (currentBuild !== undefined && latestBuild !== undefined && latestBuild > currentBuild) return true;
  const currentCommit = typeof current.commit === 'string' ? current.commit.trim() : '';
  const latestCommit = typeof latest.commit === 'string' ? latest.commit.trim() : '';
  return Boolean(currentCommit && latestCommit && currentCommit !== 'dev' && latestCommit !== currentCommit);
}

function downloadedUpdateMatchesLatest(download: AppUpdateDownloadResult | null | undefined, latest: LatestReleaseMetadata): download is AppUpdateDownloadResult {
  if (!isVerifiedDownloadedUpdate(download, latest)) return false;
  const expectedFileName = typeof latest.dmg_name === 'string' ? latest.dmg_name.trim() : '';
  if (!download?.path || download.file_name !== expectedFileName) return false;
  return normalizedUpdateDownloadPath(download.path, expectedFileName) !== null;
}

function validatedPersistedAppUpdate(
  current: AppBuildMetadata,
  record: AppUpdateDownloadResult | null | undefined,
): AppUpdateDownloadResult | null {
  if (!record || !isVerifiedDownloadedUpdate(record)) return null;
  let latest: LatestReleaseMetadata;
  try {
    latest = validateTrustedLatestMetadata<LatestReleaseMetadata>(current, record.latest);
  } catch {
    return null;
  }
  if (!isVerifiedDownloadedUpdate(record, latest)) return null;
  const expectedFileName = latest.dmg_name || '';
  if (record.file_name !== expectedFileName) return null;
  const normalizedPath = normalizedUpdateDownloadPath(record.path, expectedFileName);
  if (!normalizedPath) return null;
  const normalizedSha256 = normalizeSha256(record.sha256);
  if (!normalizedSha256) return null;
  const normalized = {
    ...record,
    path: normalizedPath,
    sha256: normalizedSha256,
    verified: true,
    latest,
  };
  return downloadedUpdateIsForDifferentBuild(current, normalized) ? normalized : null;
}

function readDownloadedAppUpdate(current: AppBuildMetadata): AppUpdateDownloadResult | null {
  const cached = validatedPersistedAppUpdate(current, lastDownloadedAppUpdate);
  if (cached) return cached;
  const record = readJsonFile<AppUpdateDownloadResult>(updateDownloadRecordPath());
  const validated = validatedPersistedAppUpdate(current, record);
  if (!validated) {
    if (lastDownloadedAppUpdate || record) clearDownloadedAppUpdate();
    return null;
  }
  lastDownloadedAppUpdate = validated;
  return validated;
}

function writeDownloadedAppUpdate(record: AppUpdateDownloadResult): boolean {
  if (!isVerifiedDownloadedUpdate(record)) return false;
  const recordPath = updateDownloadRecordPath();
  const temporaryPath = `${recordPath}.tmp-${process.pid}-${randomBytes(6).toString('hex')}`;
  try {
    fs.mkdirSync(updateDownloadsDir(), { recursive: true, mode: 0o700 });
    fs.writeFileSync(temporaryPath, JSON.stringify(record, null, 2), {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    fs.renameSync(temporaryPath, recordPath);
    fs.chmodSync(recordPath, 0o600);
    return true;
  } catch (error) {
    console.warn('[updater] failed to persist downloaded update:', error);
    try {
      fs.rmSync(temporaryPath, { force: true });
    } catch {}
    return false;
  }
}

function clearDownloadedAppUpdate(): void {
  lastDownloadedAppUpdate = null;
  try {
    fs.rmSync(updateDownloadRecordPath(), { force: true });
  } catch {}
}

class AppUpdateDownloadCancelledError extends Error {
  constructor(message = '应用更新下载已取消') {
    super(message);
    this.name = 'AppUpdateDownloadCancelledError';
  }
}

function isAppUpdateDownloadCancelledError(error: unknown): boolean {
  return error instanceof AppUpdateDownloadCancelledError
    || (error instanceof Error && error.name === 'AbortError');
}

function cleanupActiveAppUpdateDownloadFiles(task: AppUpdateDownloadTask): void {
  if (task.tmpDestination) {
    try {
      fs.rmSync(task.tmpDestination, { force: true });
    } catch {}
  }
  if (task.destination) {
    try {
      fs.rmSync(task.destination, { force: true });
    } catch {}
  }
  clearDownloadedAppUpdate();
}

function cancelActiveAppUpdateDownload(reason = '应用更新下载已取消'): { ok: boolean; cancelled: boolean; error?: string } {
  const task = activeAppUpdateDownload;
  if (!task) return { ok: true, cancelled: false };
  cleanupActiveAppUpdateDownloadFiles(task);
  task.onProgress?.({
    status: 'cancelled',
    file_name: task.fileName,
    received_bytes: 0,
    percent: 0,
    error: reason,
  });
  task.controller.abort(new AppUpdateDownloadCancelledError(reason));
  return { ok: true, cancelled: true, error: reason };
}

function confirmCancelAppUpdateDownload(parentWindow: BrowserWindow | null, actionLabel: string): boolean {
  if (!activeAppUpdateDownload) return true;
  const options = {
    type: 'warning' as const,
    buttons: ['继续下载', actionLabel],
    defaultId: 0,
    cancelId: 0,
    title: '应用更新正在下载',
    message: '应用更新仍在下载中',
    detail: '离开或退出会取消本次下载，并清空当前进度；下次启动会重新检查更新。',
  };
  const choice = parentWindow
    ? dialog.showMessageBoxSync(parentWindow, options)
    : dialog.showMessageBoxSync(options);
  if (choice !== 1) return false;
  cancelActiveAppUpdateDownload(`${actionLabel}，已取消本次更新下载`);
  return true;
}

function appUpdateInfo(): AppUpdateInfo {
  const current = readAppBuildMetadata();
  const appBundlePath = currentAppBundlePath() || undefined;
  const downloadedUpdate = readDownloadedAppUpdate(current) || undefined;
  return {
    supported: process.platform === 'darwin' && app.isPackaged && Boolean(appBundlePath),
    packaged: app.isPackaged,
    current,
    latest_json_url: current.latest_json_url || defaultLatestJsonUrl(current.branch),
    app_bundle_path: appBundlePath,
    downloaded_dmg_path: downloadedUpdate?.path,
    downloaded_update: downloadedUpdate,
  };
}

function updateAvailableReason(current: AppBuildMetadata, latest: LatestReleaseMetadata): { available: boolean; reason: string } {
  const versionComparison = compareVersionStrings(latest.version, current.version);
  if (versionComparison > 0) return { available: true, reason: `发现版本 ${latest.version}` };
  const currentBuild = numericBuildNumber(current.build_number);
  const latestBuild = numericBuildNumber(latest.build_number ?? latest.run_number);
  if (currentBuild !== undefined && latestBuild !== undefined) {
    if (latestBuild > currentBuild) return { available: true, reason: `发现构建 ${latestBuild}` };
  }
  if (versionComparison < 0) return { available: false, reason: '当前版本高于该渠道 latest' };
  if (currentBuild !== undefined && latestBuild !== undefined && latestBuild < currentBuild) {
    return { available: false, reason: '当前构建高于该渠道 latest' };
  }
  const currentCommit = typeof current.commit === 'string' ? current.commit.trim() : '';
  const latestCommit = typeof latest.commit === 'string' ? latest.commit.trim() : '';
  if (currentCommit && latestCommit && currentCommit !== 'dev' && latestCommit !== currentCommit) {
    return { available: true, reason: `发现提交 ${latest.short_commit || latestCommit.slice(0, 7)}` };
  }
  return { available: false, reason: '当前已是该渠道最新版本' };
}

function httpRequest(
  url: URL,
  options: RequestOptions,
  callback: (response: IncomingMessage) => void,
) {
  if (url.protocol !== 'https:') throw new Error('应用更新仅支持 HTTPS 链接');
  if (url.username || url.password || url.port || !TRUSTED_UPDATE_NETWORK_HOSTS.has(url.hostname)) {
    throw new Error('应用更新链接未通过 GitHub 信任边界');
  }
  return https.get(url, options, callback);
}

function redirectedUrl(location: string, baseUrl: URL): URL {
  return new URL(location, baseUrl);
}

function cacheBustedUrl(url: string): string {
  const parsed = new URL(url);
  parsed.searchParams.set('_yachiyo_update_check', `${Date.now()}`);
  return parsed.toString();
}

function fetchJson<T>(url: string, redirects = 5): Promise<T> {
  return new Promise((resolve, reject) => {
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      reject(new Error('更新元数据链接无效'));
      return;
    }
    const request = httpRequest(parsed, {
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-cache',
        Pragma: 'no-cache',
        'User-Agent': 'Oha-Yachiyo-Updater',
      },
    }, (response) => {
      const status = response.statusCode || 0;
      const location = response.headers.location;
      if ([301, 302, 303, 307, 308].includes(status) && location && redirects > 0) {
        response.resume();
        resolve(fetchJson<T>(redirectedUrl(location, parsed).toString(), redirects - 1));
        return;
      }
      if (status < 200 || status >= 300) {
        response.resume();
        reject(new Error(`更新元数据请求失败：HTTP ${status}`));
        return;
      }
      const chunks: Buffer[] = [];
      response.on('data', (chunk: Buffer | string) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
      response.on('end', () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')) as T);
        } catch {
          reject(new Error('更新元数据不是有效 JSON'));
        }
      });
    });
    request.setTimeout(20000, () => request.destroy(new Error('更新元数据请求超时')));
    request.on('error', reject);
  });
}

function updateMetadataString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function meaningfulUpdateRef(value: unknown): string {
  const ref = updateMetadataString(value);
  if (!ref || ref === 'dev' || ref === 'unknown') return '';
  return ref;
}

function shortUpdateRef(value: unknown): string {
  const ref = meaningfulUpdateRef(value);
  return ref.length > 7 ? ref.slice(0, 7) : ref;
}

function normalizeGitHubRepository(value: unknown): string {
  const repository = updateMetadataString(value) || DEFAULT_UPDATE_REPOSITORY;
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository) ? repository : DEFAULT_UPDATE_REPOSITORY;
}

function githubCompareUrl(repository: string, baseRef: string, headRef: string): string {
  return `https://github.com/${repository}/compare/${encodeURIComponent(baseRef)}...${encodeURIComponent(headRef)}`;
}

function githubCompareApiUrl(repository: string, baseRef: string, headRef: string): string {
  return `https://api.github.com/repos/${repository}/compare/${encodeURIComponent(baseRef)}...${encodeURIComponent(headRef)}?per_page=${GITHUB_COMPARE_COMMIT_LIMIT}`;
}

function currentBuildChangelogLabel(current: AppBuildMetadata): string {
  const parts = [
    updateMetadataString(current.version),
    current.build_number !== undefined ? `#${current.build_number}` : '',
    updateMetadataString(current.short_commit) || shortUpdateRef(current.commit),
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '当前安装版本';
}

function latestBuildChangelogLabel(latest: LatestReleaseMetadata, headRef: string): string {
  const parts = [
    updateMetadataString(latest.version) || updateMetadataString(latest.tag),
    numericBuildNumber(latest.build_number ?? latest.run_number) !== undefined
      ? `#${numericBuildNumber(latest.build_number ?? latest.run_number)}`
      : '',
    updateMetadataString(latest.short_commit) || shortUpdateRef(headRef),
  ].filter(Boolean);
  return updateMetadataString(latest.tag) || (parts.length ? parts.join(' / ') : '最新版本');
}

function changelogCategory(subject: string): string {
  const match = subject.trim().match(/^([A-Za-z]+)(?:\([^)]+\))?[：:]/);
  if (!match) return '其他';
  return CHANGELOG_CATEGORY_BY_KIND[match[1].toLowerCase()] || '其他';
}

function releaseCommitFromGitHub(item: GitHubCompareCommit): ReleaseChangelogCommit | null {
  const commit = meaningfulUpdateRef(item.sha);
  const message = updateMetadataString(item.commit?.message);
  const subject = updateMetadataString(message.split(/\r?\n/, 1)[0]) || shortUpdateRef(commit);
  if (!commit && !subject) return null;
  return {
    commit: commit || undefined,
    short_commit: shortUpdateRef(commit) || undefined,
    author: updateMetadataString(item.commit?.author?.name) || undefined,
    authored_at: updateMetadataString(item.commit?.author?.date) || undefined,
    subject: subject || undefined,
    category: changelogCategory(subject),
    url: updateMetadataString(item.html_url) || null,
  };
}

function buildChangelogSections(commits: ReleaseChangelogCommit[]): ReleaseChangelogSection[] {
  const grouped = new Map<string, ReleaseChangelogCommit[]>(
    CHANGELOG_CATEGORY_ORDER.map((category) => [category, []]),
  );
  for (const commit of commits) {
    const category = updateMetadataString(commit.category) || '其他';
    const items = grouped.get(category) || [];
    items.push({
      commit: commit.commit,
      short_commit: commit.short_commit,
      subject: commit.subject,
      url: commit.url,
    });
    grouped.set(category, items);
  }
  return CHANGELOG_CATEGORY_ORDER
    .map((title) => ({ title, items: grouped.get(title) || [] }))
    .filter((section) => section.items.length > 0);
}

async function buildCurrentInstallChangelog(
  current: AppBuildMetadata,
  latest: LatestReleaseMetadata,
): Promise<ReleaseChangelog | null> {
  const repository = normalizeGitHubRepository(current.repository);
  const baseRef = meaningfulUpdateRef(current.commit) || meaningfulUpdateRef(current.short_commit);
  const headRef = meaningfulUpdateRef(latest.commit)
    || meaningfulUpdateRef(latest.tag)
    || meaningfulUpdateRef(latest.changelog?.current_tag)
    || meaningfulUpdateRef(latest.short_commit);
  if (!baseRef || !headRef || baseRef === headRef) return null;

  const compare = await fetchJson<GitHubCompareResponse>(
    cacheBustedUrl(githubCompareApiUrl(repository, baseRef, headRef)),
  );
  const commits = (Array.isArray(compare.commits) ? compare.commits : [])
    .slice()
    .reverse()
    .map(releaseCommitFromGitHub)
    .filter((commit): commit is ReleaseChangelogCommit => Boolean(commit));
  const totalCommits = Number.isFinite(compare.total_commits)
    ? Math.max(0, Math.trunc(compare.total_commits as number))
    : commits.length;
  if (totalCommits <= 0 && commits.length === 0) return null;

  const compareUrl = updateMetadataString(compare.html_url) || githubCompareUrl(repository, baseRef, headRef);
  return {
    generated_from: 'github_compare_current_install',
    previous_tag: currentBuildChangelogLabel(current),
    previous_commit: baseRef,
    current_tag: latestBuildChangelogLabel(latest, headRef),
    compare_url: compareUrl,
    commit_count: totalCommits || commits.length,
    commits,
    sections: buildChangelogSections(commits),
    summary: commits.slice(0, 8).map((commit) => commit.subject || commit.short_commit || '').filter(Boolean),
  };
}

async function latestWithCurrentInstallChangelog(
  current: AppBuildMetadata,
  latest: LatestReleaseMetadata,
  updateAvailable: boolean,
): Promise<LatestReleaseMetadata> {
  if (!updateAvailable) return latest;
  try {
    const changelog = await buildCurrentInstallChangelog(current, latest);
    return changelog ? { ...latest, changelog } : latest;
  } catch (error) {
    console.warn('[updater] failed to build current install changelog:', error);
    return latest;
  }
}

function downloadFile(
  url: string,
  destination: string,
  onProgress?: (progress: AppUpdateDownloadProgress) => void,
  signal?: AbortSignal,
  redirects = 5,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new AppUpdateDownloadCancelledError());
      return;
    }
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      reject(new Error('DMG 下载链接无效'));
      return;
    }
    const tmpDestination = `${destination}.part`;
    let settled = false;
    let request: ReturnType<typeof httpRequest> | null = null;
    let output: fs.WriteStream | null = null;
    const finish = (error?: unknown) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', abortDownload);
      if (error) {
        fs.rm(tmpDestination, { force: true }, () => reject(error));
        return;
      }
      resolve();
    };
    const abortDownload = () => {
      const reason = signal?.reason instanceof Error
        ? signal.reason
        : new AppUpdateDownloadCancelledError();
      request?.destroy(reason);
      output?.destroy(reason);
      finish(reason);
    };
    signal?.addEventListener('abort', abortDownload, { once: true });
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    onProgress?.({ status: 'starting', file_name: path.basename(destination), received_bytes: 0 });
    request = httpRequest(parsed, {
      headers: {
        Accept: 'application/octet-stream',
        'User-Agent': 'Oha-Yachiyo-Updater',
      },
    }, (response) => {
      if (signal?.aborted) {
        response.destroy(signal.reason instanceof Error ? signal.reason : new AppUpdateDownloadCancelledError());
        abortDownload();
        return;
      }
      const status = response.statusCode || 0;
      const location = response.headers.location;
      if ([301, 302, 303, 307, 308].includes(status) && location && redirects > 0) {
        response.resume();
        signal?.removeEventListener('abort', abortDownload);
        downloadFile(redirectedUrl(location, parsed).toString(), destination, onProgress, signal, redirects - 1).then(resolve, reject);
        return;
      }
      if (status < 200 || status >= 300) {
        response.resume();
        finish(new Error(`DMG 下载失败：HTTP ${status}`));
        return;
      }
      const totalBytes = Number(response.headers['content-length']) || undefined;
      let receivedBytes = 0;
      const progressStream = new Transform({
        transform(chunk: Buffer, _encoding, callback) {
          receivedBytes += chunk.length;
          onProgress?.({
            status: 'downloading',
            file_name: path.basename(destination),
            received_bytes: receivedBytes,
            total_bytes: totalBytes,
            percent: totalBytes ? Math.min(100, Math.round((receivedBytes / totalBytes) * 1000) / 10) : undefined,
          });
          callback(null, chunk);
        },
      });
      output = fs.createWriteStream(tmpDestination);
      pipeline(response, progressStream, output)
        .then(() => fs.promises.rename(tmpDestination, destination))
        .then(() => finish(), finish);
    });
    request.setTimeout(120000, () => request?.destroy(new Error('DMG 下载超时')));
    request.on('error', (error) => {
      finish(error);
    });
  });
}

function sha256File(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (chunk: Buffer) => hash.update(chunk));
    stream.on('error', reject);
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function checkAppUpdate(): Promise<AppUpdateCheckResult> {
  const info = appUpdateInfo();
  try {
    const target = trustedUpdateTarget(info.current);
    const rawMetadata = await fetchJson<unknown>(target.metadataUrl);
    const latestMetadata = validateTrustedLatestMetadata<LatestReleaseMetadata>(info.current, rawMetadata);
    const decision = updateAvailableReason(info.current, latestMetadata);
    const latest = await latestWithCurrentInstallChangelog(info.current, latestMetadata, decision.available);
    const downloadedUpdate = downloadedUpdateMatchesLatest(info.downloaded_update, latest)
      ? info.downloaded_update
      : undefined;
    return {
      ...info,
      downloaded_dmg_path: downloadedUpdate?.path,
      downloaded_update: downloadedUpdate,
      ok: true,
      update_available: decision.available,
      latest,
      reason: decision.reason,
    };
  } catch (error) {
    return {
      ...info,
      ok: false,
      update_available: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

async function downloadAppUpdate(
  onProgress?: (progress: AppUpdateDownloadProgress) => void,
): Promise<AppUpdateDownloadResult> {
  if (activeAppUpdateDownload) {
    return { ok: false, error: '已有应用更新下载正在进行' };
  }
  const check = await checkAppUpdate();
  if (!check.ok || !check.latest) {
    return { ok: false, error: check.error || '无法读取更新元数据' };
  }
  if (!check.update_available) {
    return { ok: false, latest: check.latest, error: check.reason || '当前没有可下载的应用更新' };
  }
  let latest: LatestReleaseMetadata;
  let target: ReturnType<typeof trustedUpdateTarget>;
  try {
    target = trustedUpdateTarget(check.current);
    latest = validateTrustedLatestMetadata<LatestReleaseMetadata>(check.current, check.latest);
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
  if (downloadedUpdateMatchesLatest(check.downloaded_update, check.latest)) {
    return check.downloaded_update;
  }
  const expectedSha256 = normalizeSha256(latest.sha256);
  if (!expectedSha256) return { ok: false, latest, error: '更新元数据缺少合法的 SHA256' };
  const downloadUrl = target.downloadUrl;
  const fileName = target.dmgFileName;
  const destination = path.join(updateDownloadsDir(), fileName);
  const controller = new AbortController();
  activeAppUpdateDownload = {
    controller,
    destination,
    tmpDestination: `${destination}.part`,
    fileName,
    onProgress,
  };
  try {
    await downloadFile(downloadUrl, destination, onProgress, controller.signal);
    onProgress?.({ status: 'verifying', file_name: fileName });
    if (controller.signal.aborted) throw controller.signal.reason || new AppUpdateDownloadCancelledError();
    const actualSha256 = await sha256File(destination);
    if (controller.signal.aborted) throw controller.signal.reason || new AppUpdateDownloadCancelledError();
    if (actualSha256.toLowerCase() !== expectedSha256) {
      await fs.promises.rm(destination, { force: true });
      clearDownloadedAppUpdate();
      return {
        ok: false,
        latest,
        error: 'DMG SHA256 校验失败，已删除下载文件',
      };
    }
    lastDownloadedAppUpdate = {
      ok: true,
      path: destination,
      file_name: fileName,
      sha256: actualSha256,
      verified: true,
      latest,
    };
    if (!writeDownloadedAppUpdate(lastDownloadedAppUpdate)) {
      await fs.promises.rm(destination, { force: true });
      clearDownloadedAppUpdate();
      return { ok: false, latest, error: '无法安全保存已验证的更新记录，已删除下载文件' };
    }
    onProgress?.({ status: 'completed', file_name: fileName, percent: 100 });
    return lastDownloadedAppUpdate;
  } catch (error) {
    const cancelled = isAppUpdateDownloadCancelledError(error);
    if (cancelled) {
      cleanupActiveAppUpdateDownloadFiles(activeAppUpdateDownload || { controller, destination, tmpDestination: `${destination}.part`, fileName });
      onProgress?.({
        status: 'cancelled',
        file_name: fileName,
        received_bytes: 0,
        percent: 0,
        error: error instanceof Error ? error.message : '应用更新下载已取消',
      });
      return {
        ok: false,
        latest,
        cancelled: true,
        error: error instanceof Error ? error.message : '应用更新下载已取消',
      };
    }
    onProgress?.({
      status: 'failed',
      file_name: fileName,
      error: error instanceof Error ? error.message : String(error),
    });
    try {
      await fs.promises.rm(`${destination}.part`, { force: true });
      await fs.promises.rm(destination, { force: true });
    } catch {}
    clearDownloadedAppUpdate();
    return {
      ok: false,
      latest,
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    if (activeAppUpdateDownload?.controller === controller) activeAppUpdateDownload = null;
  }
}

async function installDownloadedAppUpdate(
  rawPath: unknown,
): Promise<{ success: boolean; appBundlePath?: string; dmgPath?: string; error?: string }> {
  if (process.platform !== 'darwin') return { success: false, error: '应用更新安装仅支持 macOS' };
  if (!app.isPackaged) return { success: false, error: '开发环境不支持覆盖安装，请使用已打包的 DMG 版本' };
  const appBundlePath = currentAppBundlePath();
  if (!appBundlePath) return { success: false, error: '当前运行环境不是可更新的 macOS .app 包' };
  if (appBundlePath.startsWith('/Volumes/') || appBundlePath.includes('/AppTranslocation/')) {
    return { success: false, appBundlePath, error: '请先把 Oha-Yachiyo 移到“应用程序”目录后再更新' };
  }
  try {
    fs.accessSync(path.dirname(appBundlePath), fs.constants.W_OK);
  } catch {
    return { success: false, appBundlePath, error: '当前应用目录不可写，无法安全替换应用' };
  }
  const check = await checkAppUpdate();
  if (!check.ok || !check.update_available || !check.latest || !check.downloaded_update) {
    return {
      success: false,
      appBundlePath,
      error: check.error || '无法从官方更新元数据重新确认已下载的更新，请联网后重试',
    };
  }
  const current = check.current;
  const download = check.downloaded_update;
  if (!isVerifiedDownloadedUpdate(download, check.latest)) {
    return { success: false, appBundlePath, error: '未找到与官方元数据匹配的已验证更新 DMG，请重新下载' };
  }
  let latest: LatestReleaseMetadata;
  let target: ReturnType<typeof trustedUpdateTarget>;
  try {
    target = trustedUpdateTarget(current);
    latest = validateTrustedLatestMetadata<LatestReleaseMetadata>(current, download.latest);
  } catch (error) {
    return {
      success: false,
      appBundlePath,
      error: error instanceof Error ? error.message : String(error),
    };
  }
  if (!isVerifiedDownloadedUpdate(download, latest)) {
    return { success: false, appBundlePath, error: '更新下载记录未通过 SHA256 身份校验，请重新下载' };
  }
  const dmgPath = normalizedUpdateDownloadPath(download.path, target.dmgFileName);
  if (!dmgPath || download.file_name !== target.dmgFileName) {
    return { success: false, appBundlePath, error: '已下载更新的路径或文件名不可信，请重新下载' };
  }
  if (typeof rawPath === 'string' && rawPath.trim() && path.resolve(rawPath.trim()) !== dmgPath) {
    return { success: false, appBundlePath, dmgPath, error: '安装请求与已验证的更新记录不匹配' };
  }
  const expectedSha256 = normalizeSha256(latest.sha256);
  if (!expectedSha256) {
    return { success: false, appBundlePath, dmgPath, error: '更新元数据缺少合法的 SHA256' };
  }
  let actualSha256: string;
  try {
    actualSha256 = await sha256File(dmgPath);
  } catch (error) {
    return {
      success: false,
      appBundlePath,
      dmgPath,
      error: `无法重新校验更新 DMG：${error instanceof Error ? error.message : String(error)}`,
    };
  }
  if (actualSha256.toLowerCase() !== expectedSha256) {
    try {
      fs.rmSync(dmgPath, { force: true });
    } catch {}
    clearDownloadedAppUpdate();
    return { success: false, appBundlePath, dmgPath, error: '更新 DMG 在安装前发生变化，已删除并拒绝安装' };
  }
  const appName = path.basename(appBundlePath);
  if (!/^Oha-Yachiyo.*\.app$/.test(appName)) {
    return { success: false, appBundlePath, dmgPath, error: `拒绝覆盖非 Oha-Yachiyo 应用包：${appName}` };
  }
  const script = buildMacAppUpdateInstallerScript();
  try {
    const installer = spawn('/bin/zsh', [
      '-lc',
      script,
      'oha-yachiyo-update',
      appBundlePath,
      dmgPath,
      appName,
      String(process.pid),
      expectedSha256,
      OFFICIAL_APP_BUNDLE_ID,
      typeof latest.version === 'string' ? latest.version.trim() : '',
      updateDownloadRecordPath(),
    ], {
      detached: true,
      stdio: 'ignore',
    });
    await new Promise<void>((resolve, reject) => {
      installer.once('spawn', () => {
        installer.unref();
        resolve();
      });
      installer.once('error', reject);
    });
    appUpdateQuitConfirmed = true;
    app.quit();
    return { success: true, appBundlePath, dmgPath };
  } catch (error) {
    return {
      success: false,
      appBundlePath,
      dmgPath,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function iconCandidates(kind: IconKind): string[][] {
  if (kind === 'tray') {
    return [
      ['assets', 'icon.png'],
      ['icon.icns'],
    ];
  }
  return [
    ['icon.icns'],
    ['assets', 'icon.png'],
  ];
}

function isLoadableIcon(candidate: string): boolean {
  try {
    return !nativeImage.createFromPath(candidate).isEmpty();
  } catch {
    return false;
  }
}

function appIconPath(kind: IconKind = 'window'): string | undefined {
  const preferred = iconCandidates(kind);
  for (const segments of preferred) {
    const candidate = rootAssetPath(...segments);
    if (candidate && isLoadableIcon(candidate)) return candidate;
  }
  const fallback = rootAssetPath('apps', 'shell', 'assets', 'avatars', 'yachiyo-default.jpg');
  return fallback && isLoadableIcon(fallback) ? fallback : undefined;
}

function appIconImage(
  kind: IconKind = 'window',
  size?: number,
): ReturnType<typeof nativeImage.createEmpty> {
  const iconPath = appIconPath(kind);
  const image = iconPath ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
  if (!size || image.isEmpty()) return image;
  return image.resize({ width: size, height: size });
}

function enforceWindowTitle(targetWindow: BrowserWindow, title: string): void {
  // TODO: if macOS still collapses frameless launcher windows in the Dock menu,
  // replace the default Dock menu with explicit main/chat/mode window actions.
  enforcedWindowTitles.set(targetWindow, title);
  targetWindow.setTitle(title);
  if (titleHandlersInstalled.has(targetWindow)) return;
  titleHandlersInstalled.add(targetWindow);
  targetWindow.webContents.on('page-title-updated', (event) => {
    const enforcedTitle = enforcedWindowTitles.get(targetWindow);
    if (!enforcedTitle) return;
    event.preventDefault();
    targetWindow.setTitle(enforcedTitle);
  });
}

function mainWindowTitle(params: Record<string, string> = {}): string {
  const view = normalizeView(params.view);
  if (view === 'provider') return 'Oha-Yachiyo 模型配置';
  if (view === 'agents') return 'Oha-Yachiyo 代理工作台';
  if (view === 'resources') return 'Oha-Yachiyo 资源管理';
  if (view === 'workspace') return 'Oha-Yachiyo 工作区';
  if (view === 'settings') return params.mode === 'live2d'
    ? 'Oha-Yachiyo Live2D 设置'
    : params.mode === 'bubble'
      ? 'Oha-Yachiyo Bubble 设置'
      : 'Oha-Yachiyo 应用设置';
  if (view === 'diagnostics') return 'Oha-Yachiyo 诊断工具';
  if (view === 'tools') return 'Oha-Yachiyo 工具中心';
  if (view === 'tools-all') return 'Oha-Yachiyo 桌面工具';
  if (view === 'activity-all') return 'Oha-Yachiyo 活动日志';
  if (view === 'activity-detail') return 'Oha-Yachiyo 活动详情';
  if (view === 'app-update') return 'Oha-Yachiyo 应用更新';
  if (view === 'proactive-tts') return 'Oha-Yachiyo 主动关怀语音';
  if (view === 'chat') return 'Oha-Yachiyo 对话';
  return 'Oha-Yachiyo 主控台';
}

function modeWindowTitle(mode: ModeId): string {
  return mode === 'live2d' ? 'Oha-Yachiyo Live2D' : 'Oha-Yachiyo Bubble';
}

function macOSPrerequisiteCommand(): string {
  return [
    'echo "Oha-Yachiyo macOS 基础工具检查"',
    'if ! xcode-select -p >/dev/null 2>&1; then echo "将打开 Xcode Command Line Tools 安装器"; xcode-select --install || true; else echo "Xcode Command Line Tools 已安装"; fi',
    'if ! command -v brew >/dev/null 2>&1; then echo "正在安装 Homebrew"; /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; fi',
    'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'if command -v brew >/dev/null 2>&1; then brew update && brew install git curl; else echo "未检测到 brew，请根据终端提示完成 Homebrew 安装后重新运行"; fi',
    'echo "基础工具准备完成。请回到 Oha-Yachiyo 继续配置模型。"',
  ].join('\n');
}

function terminalTaskCommand(task: DesktopTerminalTask): { title: string; command: string } {
  if (task === 'mac-prerequisites') {
    return { title: '准备 macOS 基础工具', command: macOSPrerequisiteCommand() };
  }
  return { title: '准备 macOS 基础工具', command: macOSPrerequisiteCommand() };
}

function ensureNodePtySpawnHelperExecutable(): void {
  if (process.platform !== 'darwin' && process.platform !== 'linux') return;
  try {
    const entryPath = require.resolve('node-pty');
    const packageRoot = path.resolve(path.dirname(entryPath), '..');
    const helperCandidates = [
      path.join(packageRoot, 'prebuilds', `${process.platform}-${process.arch}`, 'spawn-helper'),
      path.join(packageRoot.replace('app.asar', 'app.asar.unpacked'), 'prebuilds', `${process.platform}-${process.arch}`, 'spawn-helper'),
    ];
    for (const helperPath of helperCandidates) {
      if (!fs.existsSync(helperPath)) continue;
      const mode = fs.statSync(helperPath).mode;
      if ((mode & 0o111) === 0) fs.chmodSync(helperPath, mode | 0o755);
    }
  } catch (error) {
    console.warn('[terminal] failed to prepare node-pty spawn-helper:', error);
  }
}

function packagedBackendPath(): string | null {
  const binaryName = process.platform === 'win32' ? 'oha-yachiyo-backend.exe' : 'oha-yachiyo-backend';
  const candidate = path.join(process.resourcesPath, 'backend', binaryName);
  return app.isPackaged && fs.existsSync(candidate) ? candidate : null;
}

function developmentBackendPythonPath(): string {
  const configured = process.env.OHA_YACHIYO_PYTHON?.trim();
  if (configured) return configured;
  const candidates = process.platform === 'win32'
    ? [path.join(projectRoot(), '.venv', 'Scripts', 'python.exe')]
    : [
        path.join(projectRoot(), '.venv', 'bin', 'python'),
        path.join(projectRoot(), '.venv', 'bin', 'python3'),
      ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || 'python3';
}

function packagedCuaDriverPath(): string {
  return path.join(
    process.resourcesPath,
    'computer-use',
    'macos',
    'OhaCuaDriver.app',
    'Contents',
    'MacOS',
    'cua-driver',
  );
}

function usesPackagedCuaMcpBridge(): boolean {
  return app.isPackaged && process.platform === 'darwin';
}

async function startPackagedCuaMcpBridge(): Promise<void> {
  if (appShutdownRequested || !usesPackagedCuaMcpBridge() || cuaMcpBridge) return;
  const nextBridge = new CuaMcpBridge({
    driverPath: packagedCuaDriverPath(),
    hostBundleId: OFFICIAL_APP_BUNDLE_ID,
    token: cuaMcpBridgeToken,
    generation: cuaMcpBridgeGeneration,
  });
  cuaMcpBridge = nextBridge;
  try {
    const nextBridgeUrl = await nextBridge.start();
    if (appShutdownRequested || cuaMcpBridge !== nextBridge) {
      await nextBridge.close();
      if (cuaMcpBridge === nextBridge) cuaMcpBridge = null;
      return;
    }
    cuaMcpBridgeUrl = nextBridgeUrl;
  } catch (error) {
    if (cuaMcpBridge === nextBridge) cuaMcpBridge = null;
    cuaMcpBridgeUrl = '';
    await nextBridge.close();
    throw error;
  }
}

async function rotatePackagedCuaMcpBridge(): Promise<void> {
  cuaMcpBridgeToken = randomBytes(32).toString('hex');
  cuaMcpBridgeGeneration = randomBytes(12).toString('hex');
  const bridge = cuaMcpBridge;
  if (bridge) {
    await bridge.rotate({
      token: cuaMcpBridgeToken,
      generation: cuaMcpBridgeGeneration,
    });
  }
}

async function closePackagedCuaMcpBridge(): Promise<void> {
  const bridge = cuaMcpBridge;
  cuaMcpBridge = null;
  cuaMcpBridgeUrl = '';
  if (bridge) await bridge.close();
}

function initialBridgeUrl(): string {
  const envBridgeUrl = normalizeBridgeUrl(process.env[BRIDGE_URL_ENV]);
  if (packagedBackendPath()) return envBridgeUrl || PACKAGED_BRIDGE_URL;
  if (!envBridgeUrl) return DEV_BRIDGE_URL;
  const endpoint = bridgeEndpoint(envBridgeUrl);
  if (endpoint?.port === 18420) return DEV_BRIDGE_URL;
  return envBridgeUrl;
}

function bridgeEndpoint(url: string): { host: string; port: number } | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'http:') return null;
    if (!parsed.port) return null;
    const port = Number(parsed.port);
    if (!Number.isInteger(port) || port <= 0 || port > 65535) return null;
    return { host: parsed.hostname || '127.0.0.1', port };
  } catch {
    return null;
  }
}

function isLocalBridgeHost(host: string): boolean {
  return host === '127.0.0.1' || host === 'localhost' || host === '::1';
}

function normalizedLocalBridgeHost(host: string): string {
  return host === '::1' || host === 'localhost' ? '127.0.0.1' : host;
}

function isTcpPortAvailable(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = createServer();
    let settled = false;
    const finish = (available: boolean) => {
      if (settled) return;
      settled = true;
      resolve(available);
    };
    server.once('error', () => finish(false));
    server.once('listening', () => {
      server.close(() => finish(true));
    });
    server.listen({ host, port });
  });
}

function allocateLocalBridgeUrl(host: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.once('listening', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : null;
      server.close(() => {
        if (!port) {
          reject(new Error('Could not allocate a local bridge port'));
          return;
        }
        resolve(`http://${host}:${port}`);
      });
    });
    server.listen({ host, port: 0 });
  });
}

async function prepareBridgeUrlForPackagedBackend(): Promise<void> {
  if (!packagedBackendPath() || process.env[BRIDGE_URL_ENV]) return;
  const endpoint = bridgeEndpoint(bridgeUrl);
  if (!endpoint || !isLocalBridgeHost(endpoint.host)) return;

  const host = normalizedLocalBridgeHost(endpoint.host);
  if (await isTcpPortAvailable(host, endpoint.port)) return;

  const previousBridgeUrl = bridgeUrl;
  bridgeUrl = await allocateLocalBridgeUrl(host);
  console.warn(`[backend] ${previousBridgeUrl} is already in use; using ${bridgeUrl} for this app session.`);
}

function startBackend(): void {
  if (appShutdownRequested) return;
  if (process.env.OHA_YACHIYO_SKIP_BACKEND === '1') return;
  if (backendProcess) return;

  const backendBinary = packagedBackendPath();
  const command = backendBinary || developmentBackendPythonPath();
  const args = backendBinary ? [] : ['-m', 'apps.desktop_backend.app'];
  const backendParentToken = randomBytes(24).toString('hex');
  const backendEnvironment: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONPATH: projectRoot(),
    OHA_YACHIYO_DESKTOP_BACKEND: '1',
    [ELECTRON_PARENT_PID_ENV]: String(process.pid),
    [ELECTRON_PARENT_TOKEN_ENV]: backendParentToken,
    [BRIDGE_URL_ENV]: bridgeUrl,
    [BRIDGE_TOKEN_ENV]: bridgeSessionToken,
    [ELECTRON_NATIVE_URL_ENV]: nativeRuntimeUrl,
    [ELECTRON_NATIVE_TOKEN_ENV]: bridgeSessionToken,
  };
  if (usesPackagedCuaMcpBridge()) {
    // A packaged build is authoritative: only the authenticated Electron-owned
    // bridge may launch Cua Driver. Empty bridge state must fail closed instead
    // of falling back to a PATH or user-supplied subprocess command.
    delete backendEnvironment[CUA_DRIVER_PATH_ENV];
    delete backendEnvironment[CUA_DRIVER_COMMAND_ENV];
    delete backendEnvironment[CUA_HOST_BUNDLE_ID_ENV];
    backendEnvironment[CUA_MCP_TRANSPORT_ENV] = CUA_MCP_ELECTRON_BRIDGE_TRANSPORT;
    backendEnvironment[CUA_MCP_BRIDGE_URL_ENV] = cuaMcpBridgeUrl;
    backendEnvironment[CUA_MCP_BRIDGE_TOKEN_ENV] = cuaMcpBridgeToken;
    backendEnvironment[CUA_MCP_BRIDGE_GENERATION_ENV] = cuaMcpBridgeGeneration;
  } else {
    delete backendEnvironment[CUA_MCP_TRANSPORT_ENV];
    delete backendEnvironment[CUA_MCP_BRIDGE_URL_ENV];
    delete backendEnvironment[CUA_MCP_BRIDGE_TOKEN_ENV];
    delete backendEnvironment[CUA_MCP_BRIDGE_GENERATION_ENV];
  }
  const spawnedBackend = spawn(command, args, {
    cwd: backendBinary ? process.resourcesPath : projectRoot(),
    env: backendEnvironment,
  });
  backendProcess = spawnedBackend;
  recordElectronProcessSmoke('backend.spawn', {
    backend_pid: spawnedBackend.pid ?? null,
    parent_token_hash: createHash('sha256').update(backendParentToken).digest('hex').slice(0, 16),
  });

  spawnedBackend.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
  spawnedBackend.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
  spawnedBackend.on('error', (error) => {
    console.error(`[backend] failed to start: ${error.message}`);
    recordElectronProcessSmoke('backend.exit', {
      backend_pid: spawnedBackend.pid ?? null,
      error: error.message,
    });
    if (backendProcess === spawnedBackend) {
      backendProcess = null;
      void cuaMcpBridge?.endActiveSession();
    }
  });
  spawnedBackend.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code ?? 'null'} signal=${signal ?? 'null'}`);
    recordElectronProcessSmoke('backend.exit', {
      backend_pid: spawnedBackend.pid ?? null,
      code,
      signal,
    });
    if (backendProcess === spawnedBackend) {
      backendProcess = null;
      void cuaMcpBridge?.endActiveSession();
    }
  });
}

function stopBackend(): void {
  if (!backendProcess) return;
  backendProcess.kill('SIGTERM');
  backendProcess = null;
}

function terminateBackend(timeoutMs = 5000): Promise<void> {
  if (backendTerminationPromise) return backendTerminationPromise;
  const processToStop = backendProcess;
  if (!processToStop) return Promise.resolve();
  backendProcess = null;
  let trackedTermination: Promise<void>;
  trackedTermination = new Promise<void>((resolve) => {
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      resolve();
    };
    processToStop.once('exit', finish);
    processToStop.once('error', finish);
    try {
      processToStop.kill('SIGTERM');
    } catch {
      finish();
      return;
    }
    setTimeout(() => {
      if (!finished) {
        try {
          processToStop.kill('SIGKILL');
        } catch {}
        finish();
      }
    }, timeoutMs);
  }).finally(() => {
    if (backendTerminationPromise === trackedTermination) {
      backendTerminationPromise = null;
    }
  });
  backendTerminationPromise = trackedTermination;
  return trackedTermination;
}

function normalizeBridgeUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const parsed = new URL(value.trim());
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return parsed.origin.replace(/\/$/, '');
  } catch {
    return null;
  }
}

function reloadWindowWithCurrentRoute(targetWindow: BrowserWindow | null): void {
  if (!targetWindow || targetWindow.isDestroyed()) return;
  const route = routeForWindow(targetWindow);
  if (!route) return;
  targetWindow.loadURL(rendererUrl({ view: route.view, ...route.params }));
}

function reloadRendererWindows(): void {
  reloadWindowWithCurrentRoute(mainWindow);
  reloadWindowWithCurrentRoute(chatWindow);
  reloadWindowWithCurrentRoute(modeWindow);
}

async function restartBackendProcess(targetBridgeUrl?: unknown): Promise<{ success: boolean; bridgeUrl?: string; error?: string }> {
  if (appShutdownRequested) {
    return { success: false, bridgeUrl, error: '应用正在退出，不能重启后台服务' };
  }
  if (backendRestartPromise) return backendRestartPromise;
  backendRestartPromise = (async () => {
    const nextBridgeUrl = normalizeBridgeUrl(targetBridgeUrl) || bridgeUrl;
    const previousBridgeUrl = bridgeUrl;
    bridgeUrl = nextBridgeUrl;
    bridgeSessionToken = randomBytes(32).toString('hex');
    await rotatePackagedCuaMcpBridge();
    if (appShutdownRequested) {
      return { success: false, bridgeUrl, error: '应用正在退出，已取消后台服务重启' };
    }
    await terminateBackend();
    if (appShutdownRequested) {
      return { success: false, bridgeUrl, error: '应用正在退出，已取消后台服务重启' };
    }
    try {
      await startPackagedCuaMcpBridge();
    } catch (error) {
      console.warn('[cua-mcp-bridge] listener unavailable; packaged backend will fail closed:', error);
    }
    startBackend();
    const settings = await waitForUiSettings();
    if (appShutdownRequested) {
      return { success: false, bridgeUrl, error: '应用正在退出，已取消后台服务重启' };
    }
    if (!settings) {
      return {
        success: false,
        bridgeUrl,
        error: `Bridge 重启后仍无法连接：${bridgeUrl}`,
      };
    }
    lastUiSettings = settings;
    configureTray(settings);
    if (bridgeUrl !== previousBridgeUrl) {
      setTimeout(reloadRendererWindows, 120);
    }
    return { success: true, bridgeUrl };
  })().finally(() => {
    backendRestartPromise = null;
  });
  return backendRestartPromise;
}

function rendererUrl(params: Record<string, string> = {}): string {
  const query = new URLSearchParams({ bridge: bridgeUrl });
  query.set('_hy_ui_rev', UI_RENDER_REVISION);
  Object.entries(params)
    .filter(([key]) => key !== 'view' && key !== 'mode' && key !== 'restore')
    .forEach(([key, value]) => query.set(key, value));
  const route = routeHash(params);
  if (!app.isPackaged) return `${FRONTEND_DEV_URL}?${query.toString()}${route}`;
  const indexHtml = path.resolve(__dirname, '..', 'dist', 'index.html');
  return `${pathToFileURL(indexHtml).toString()}?${query.toString()}${route}`;
}

function bridgeJsonHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Oha-Yachiyo-Bridge-Token': bridgeSessionToken,
  };
}

function routeHash(params: Record<string, string> = {}): string {
  const view = normalizeView(params.view);
  if (view === 'main') return '#/';
  if (view === 'settings' && params.mode) return `#/settings/${encodeURIComponent(params.mode)}`;
  if (view === 'tools' && params.tool) return `#/tools/${encodeURIComponent(params.tool)}`;
  if (view === 'agents' && params.run) return `#/agents/${encodeURIComponent(params.run)}`;
  if (view === 'agents' && isAgentStudioTab(params.tab) && params.tab !== 'agents') {
    return `#/agents/${encodeURIComponent(params.tab)}`;
  }
  if (view === 'provider' && params.capability) return `#/provider/${encodeURIComponent(params.capability)}`;
  if (view === 'activity-detail' && params.event_id) return `#/activity-detail/${encodeURIComponent(params.event_id)}`;
  return `#/${encodeURIComponent(view)}`;
}

function mainWindowBounds(settings: UiSettings | null = lastUiSettings): { width: number; height: number } {
  const windowMode = settings?.window_mode || {};
  return {
    width: Math.round(clamp(numberFromConfig(windowMode.width, MIN_APP_WINDOW_WIDTH), MIN_APP_WINDOW_WIDTH, 1920)),
    height: Math.round(clamp(numberFromConfig(windowMode.height, MIN_APP_WINDOW_HEIGHT), MIN_APP_WINDOW_HEIGHT, 1400)),
  };
}

function chatWindowBounds(settings: UiSettings | null = lastUiSettings, workArea: Rectangle = screen.getPrimaryDisplay().workArea): { width: number; height: number } {
  const base = mainWindowBounds(settings);
  const maxWidth = Math.max(MIN_APP_WINDOW_WIDTH, Math.min(1440, workArea.width));
  const maxHeight = Math.max(MIN_APP_WINDOW_HEIGHT, Math.min(1000, workArea.height));
  return {
    width: Math.round(clamp(Math.max(base.width, MIN_APP_WINDOW_WIDTH), MIN_APP_WINDOW_WIDTH, maxWidth)),
    height: Math.round(clamp(Math.max(base.height, MIN_APP_WINDOW_HEIGHT), MIN_APP_WINDOW_HEIGHT, maxHeight)),
  };
}

function chatWindowMinSize(settings: UiSettings | null = lastUiSettings, workArea: Rectangle = screen.getPrimaryDisplay().workArea): { width: number; height: number } {
  const bounds = chatWindowBounds(settings, workArea);
  return {
    width: Math.min(MIN_APP_WINDOW_WIDTH, bounds.width),
    height: Math.min(MIN_APP_WINDOW_HEIGHT, bounds.height),
  };
}

function ensureMainWindowUsableBounds(settings: UiSettings | null = lastUiSettings): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const current = mainWindow.getBounds();
  const workArea = screen.getDisplayMatching(current).workArea;
  const target = mainWindowBounds(settings);
  mainWindow.setMinimumSize(MIN_APP_WINDOW_WIDTH, MIN_APP_WINDOW_HEIGHT);
  if (current.width >= MIN_APP_WINDOW_WIDTH && current.height >= MIN_APP_WINDOW_HEIGHT) return;
  const width = Math.max(current.width, target.width);
  const height = Math.max(current.height, target.height);
  const x = width >= workArea.width
    ? workArea.x
    : Math.round(clamp(current.x, workArea.x, workArea.x + workArea.width - width));
  const y = height >= workArea.height
    ? workArea.y
    : Math.round(clamp(current.y, workArea.y, workArea.y + workArea.height - height));
  mainWindow.setBounds({ x, y, width, height }, false);
}

function ensureChatWindowUsableBounds(settings: UiSettings | null = lastUiSettings): void {
  if (!chatWindow || chatWindow.isDestroyed()) return;
  const current = chatWindow.getBounds();
  const workArea = screen.getDisplayMatching(current).workArea;
  const target = chatWindowBounds(settings, workArea);
  const minimum = chatWindowMinSize(settings, workArea);
  chatWindow.setMinimumSize(minimum.width, minimum.height);
  if (current.width >= minimum.width && current.height >= minimum.height) return;
  const width = Math.max(current.width, target.width);
  const height = Math.max(current.height, target.height);
  const x = width >= workArea.width
    ? workArea.x
    : Math.round(clamp(current.x, workArea.x, workArea.x + workArea.width - width));
  const y = height >= workArea.height
    ? workArea.y
    : Math.round(clamp(current.y, workArea.y, workArea.y + workArea.height - height));
  chatWindow.setBounds({ x, y, width, height }, false);
}

function createMainWindow(
  params: Record<string, string> = {},
  settings: UiSettings | null = lastUiSettings,
  options: MainWindowOptions = {},
): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    showMainWindow(params, settings, options);
    return;
  }
  if (settings) lastUiSettings = settings;
  hasEnteredMainExperience = true;
  configureTray(settings || lastUiSettings);
  const bounds = mainWindowBounds(settings);
  const startHidden = Boolean(options.respectStartMinimized && settings?.app?.start_minimized);
  const focusOnReady = options.focusOnReady !== false;
  const title = mainWindowTitle(params);
  mainWindow = new BrowserWindow({
    title,
    ...bounds,
    icon: appIconPath('window'),
    minWidth: MIN_APP_WINDOW_WIDTH,
    minHeight: MIN_APP_WINDOW_HEIGHT,
    show: false,
    backgroundColor: '#060913',
    ...(process.platform === 'darwin'
      ? {
          titleBarStyle: 'hiddenInset' as const,
          trafficLightPosition: { x: 16, y: 18 },
        }
      : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  enforceWindowTitle(mainWindow, title);
  recordElectronProcessSmoke('window.created', {
    visible: mainWindow.isVisible(),
    minimized: mainWindow.isMinimized(),
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
  const createdWindow = mainWindow;
  mainWindow.on('close', (event) => {
    const closingRoute = routeForWindow(createdWindow);
    if (closingRoute) lastMainWindowRoute = { view: closingRoute.view, params: { ...closingRoute.params } };
    if (!activeAppUpdateDownload || appUpdateQuitConfirmed || appUpdateCloseConfirmedWindows.has(createdWindow)) return;
    event.preventDefault();
    if (!confirmCancelAppUpdateDownload(createdWindow, '关闭并取消更新')) return;
    appUpdateCloseConfirmedWindows.add(createdWindow);
    setTimeout(() => {
      if (!createdWindow.isDestroyed()) createdWindow.close();
    }, 0);
  });
  mainWindow.on('closed', () => {
    if (mainWindow === createdWindow) mainWindow = null;
    restoreModeWindowTopPreference();
  });
}

function showMainWindow(
  params: Record<string, string> = {},
  settings: UiSettings | null = lastUiSettings,
  options: MainWindowOptions = {},
): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow(params, settings, options);
    return;
  }
  if (settings) lastUiSettings = settings;
  hasEnteredMainExperience = true;
  configureTray(settings || lastUiSettings);
  enforceWindowTitle(mainWindow, mainWindowTitle(params));
  ensureMainWindowUsableBounds(settings);
  mainWindow.loadURL(rendererUrl({ view: 'main', ...params }));
  if (mainWindow.isMinimized()) mainWindow.restore();
  const startHidden = Boolean(options.respectStartMinimized && settings?.app?.start_minimized);
  if (startHidden && !mainWindow.isVisible()) return;
  showMacDockIcon();
  suppressModeWindowForMainWindow();
  mainWindow.show();
  mainWindow.moveTop();
  if (options.focusOnReady !== false) mainWindow.focus();
}

function focusMainWindowWithoutNavigation(
  route: MainRoute | null,
  settings: UiSettings | null = lastUiSettings,
  options: MainWindowOptions = {},
): boolean {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  if (settings) lastUiSettings = settings;
  if (route) {
    lastMainWindowRoute = { view: route.view, params: { ...route.params } };
    enforceWindowTitle(mainWindow, mainWindowTitle({ ...route.params, view: route.view }));
  }
  ensureMainWindowUsableBounds(settings);
  if (mainWindow.isMinimized()) mainWindow.restore();
  const startHidden = Boolean(options.respectStartMinimized && settings?.app?.start_minimized);
  if (startHidden && !mainWindow.isVisible()) return true;
  showMacDockIcon();
  suppressModeWindowForMainWindow();
  mainWindow.show();
  mainWindow.moveTop();
  if (options.focusOnReady !== false) mainWindow.focus();
  return true;
}

function showMainWindowFromAppActivation(): void {
  void (async () => {
    const currentRoute = routeForWindow(mainWindow) || lastMainWindowRoute;
    const activationParams = mainActivationRouteParams(currentRoute);
    const canFocusExistingRoute = !currentRoute || activationParams.view === currentRoute.view;
    if (canFocusExistingRoute && mainWindow && !mainWindow.isDestroyed()) {
      if (focusMainWindowWithoutNavigation(currentRoute, lastUiSettings)) {
        if (currentRoute?.view === 'main' || !currentRoute) {
          setTimeout(() => void openConfiguredDesktopMode(), 180);
        }
        return;
      }
    }
    showMainWindow(activationParams, lastUiSettings);
    if (activationParams.view === 'main') {
      setTimeout(() => void openConfiguredDesktopMode(), 180);
    }
  })();
}

function trayIcon() {
  const size = process.platform === 'darwin' ? 18 : 20;
  return appIconImage('tray', size);
}

function trayMenu(): Menu {
  return Menu.buildFromTemplate([
    { label: '主控台', click: () => showMainWindow({ view: 'main' }) },
    { label: '打开对话', click: () => showChatWindow() },
    { label: '打开表现态', click: () => void openConfiguredDesktopMode(undefined, lastUiSettings) },
    { label: '应用设置', click: () => showMainWindow({ view: 'settings' }) },
    { type: 'separator' },
    { label: '退出 Oha-Yachiyo', click: () => app.quit() },
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
    tray.setToolTip('Oha-Yachiyo');
    tray.on('click', () => showMainWindow({ view: 'main' }));
  } else {
    tray.setImage(trayIcon());
  }
  tray.setContextMenu(trayMenu());
}

function showMacDockIcon(): void {
  if (process.platform !== 'darwin') return;
  try {
    app.setActivationPolicy('regular');
    const icon = appIconImage('dock');
    if (!icon.isEmpty()) app.dock?.setIcon(icon);
    const aboutIcon = appIconPath('dock');
    if (aboutIcon) app.setAboutPanelOptions({ applicationName: 'Oha-Yachiyo', iconPath: aboutIcon });
    app.dock?.show();
  } catch {}
}

function routeForWindow(targetWindow: BrowserWindow | null): { view: AppView; params: Record<string, string> } | null {
  if (!targetWindow || targetWindow.isDestroyed()) return null;
  return routeFromUrl(targetWindow.webContents.getURL());
}

function mainActivationRouteParams(route: { view: AppView; params: Record<string, string> } | null): Record<string, string> {
  if (!route) return { view: 'main' };
  if (route.view === 'bubble' || route.view === 'bubble-menu' || route.view === 'live2d') {
    return { view: 'main' };
  }
  return { ...route.params, view: route.view };
}

function restoreMainWindowIfPolluted(): void {
  const route = routeForWindow(mainWindow);
  if (!route) return;
  if (route.view === 'bubble' || route.view === 'bubble-menu' || route.view === 'live2d') {
    mainWindow?.loadURL(rendererUrl({ view: 'main' }));
  }
}

function restoreModeWindowIfPolluted(): void {
  if (!modeWindow || modeWindow.isDestroyed() || !activeMode) return;
  const route = routeForWindow(modeWindow);
  if (!route) return;
  if (route.view !== activeMode && !(activeMode === 'bubble' && route.view === 'bubble-menu')) {
    modeWindow.loadURL(rendererUrl({ view: activeMode, surface: 'desktop' }));
  }
}

function createChatWindow(params: Record<string, string> = {}): void {
  const bounds = chatWindowBounds();
  const minimum = chatWindowMinSize();
  chatWindow = new BrowserWindow({
    title: 'Oha-Yachiyo 对话',
    ...bounds,
    icon: appIconPath('window'),
    minWidth: minimum.width,
    minHeight: minimum.height,
    backgroundColor: '#060913',
    ...(process.platform === 'darwin'
      ? {
          titleBarStyle: 'hiddenInset' as const,
          trafficLightPosition: { x: 16, y: 18 },
        }
      : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  enforceWindowTitle(chatWindow, 'Oha-Yachiyo 对话');

  chatWindow.loadURL(rendererUrl({ ...params, view: 'chat' }));
  chatWindow.on('closed', () => {
    chatWindow = null;
  });
  chatWindow.once('ready-to-show', () => {
    showMacDockIcon();
  });
}

function navigateMainWindowInPlace(params: Record<string, string>): boolean {
  if (!mainWindow || mainWindow.isDestroyed() || params.session_id) return false;
  const route = routeHash(params);
  mainWindow.webContents.executeJavaScript(
    `window.history.pushState(null, '', ${JSON.stringify(route)}); window.dispatchEvent(new Event('oha-route-change'));`,
  ).catch(() => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(rendererUrl(params));
  });
  return true;
}

function focusMainWindowAsChat(params: Record<string, string> = {}): boolean {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  const route = routeForWindow(mainWindow);
  const nextParams = { ...params, view: 'chat' };
  enforceWindowTitle(mainWindow, mainWindowTitle(nextParams));
  if (route?.view !== 'chat') {
    if (!navigateMainWindowInPlace(nextParams)) mainWindow.loadURL(rendererUrl(nextParams));
  } else if (params.session_id && route.params.session_id !== params.session_id) {
    mainWindow.loadURL(rendererUrl(nextParams));
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  showMacDockIcon();
  mainWindow.show();
  mainWindow.moveTop();
  mainWindow.focus();
  return true;
}

function showChatWindow(params: Record<string, string> = {}): void {
  restoreMainWindowIfPolluted();
  restoreModeWindowIfPolluted();
  restoreModeWindowTopPreference();
  if (focusMainWindowAsChat(params)) return;
  if (!chatWindow || chatWindow.isDestroyed()) {
    createChatWindow(params);
    return;
  }
  enforceWindowTitle(chatWindow, mainWindowTitle({ ...params, view: 'chat' }));
  ensureChatWindowUsableBounds();
  const route = routeForWindow(chatWindow);
  if (route?.view !== 'chat' || (params.session_id && route.params.session_id !== params.session_id)) {
    chatWindow.loadURL(rendererUrl({ ...params, view: 'chat' }));
  }
  if (chatWindow.isMinimized()) chatWindow.restore();
  showMacDockIcon();
  chatWindow.show();
  chatWindow.moveTop();
  chatWindow.focus();
}

function showMainWindowAtLastRoute(params: Record<string, string> = {}): void {
  restoreMainWindowIfPolluted();
  restoreModeWindowIfPolluted();
  const cleanParams = { ...params };
  delete cleanParams.restore;
  const route = routeForWindow(mainWindow) || lastMainWindowRoute;
  showMainWindow({ ...mainActivationRouteParams(route), ...cleanParams });
}

function openAppView(view: AppView, params: Record<string, string> = {}): void {
  if (view === 'chat') {
    showChatWindow(params);
    return;
  }
  if (view === 'main' && params.restore === 'last') {
    showMainWindowAtLastRoute(params);
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
  const views: AppView[] = [
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
  ];
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

function normalizeDisplayMode(value: unknown): DisplayModeId {
  if (value === 'none') return 'none';
  return normalizeMode(value);
}

function normalizePreferredDisplayMode(value: unknown): DisplayModeId | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  return normalizeDisplayMode(value);
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
    if (view === 'tools' && rawMode) params.tool = rawMode;
    if (view === 'agents' && rawMode) {
      if (isAgentStudioTab(rawMode)) {
        if (rawMode !== 'agents') params.tab = rawMode;
      } else {
        params.run = rawMode;
      }
    }
    if (view === 'provider' && rawMode) params.capability = rawMode;
    if (view === 'activity-detail' && rawMode) params.event_id = rawMode;
    return { view, params };
  }
  const view = normalizeView(parsed.searchParams.get('view'));
  return { view, params };
}

function isAgentStudioTab(value?: string): boolean {
  return Boolean(value && ['agents', 'skills', 'skill-groups', 'workflows', 'runs'].includes(value));
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

function stringFromConfig(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
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

function squareBubbleBounds(bounds: Rectangle): Rectangle {
  const workArea = workAreaForBounds(bounds);
  const size = Math.round(clamp(Math.max(bounds.width, bounds.height), BUBBLE_MIN_WINDOW_SIZE, BUBBLE_MAX_WINDOW_SIZE));
  const x = Math.round(clamp(bounds.x, workArea.x, workArea.x + Math.max(0, workArea.width - size)));
  const y = Math.round(clamp(bounds.y, workArea.y, workArea.y + Math.max(0, workArea.height - size)));
  return { ...bounds, x, y, width: size, height: size };
}

async function saveLauncherPosition(mode: ModeId, bounds: Rectangle): Promise<void> {
  const workArea = workAreaForBounds(bounds);
  try {
    const response = await fetch(`${bridgeUrl}/ui/launcher/position`, {
      method: 'POST',
      headers: bridgeJsonHeaders(),
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
  if (Date.now() < positionSaveSuppressedUntil) return;
  if (positionSaveTimer) clearTimeout(positionSaveTimer);
  positionSaveTimer = setTimeout(() => {
    if (!modeWindow || modeWindow.isDestroyed() || activeMode !== mode) return;
    let bounds = modeWindow.getBounds();
    if (mode === 'bubble') {
      const squared = squareBubbleBounds(bounds);
      if (boundsChanged(bounds, squared)) {
        modeWindow.setBounds(squared, false);
        bounds = squared;
      }
    }
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

function suppressModeWindowPositionSave(durationMs = 900): void {
  positionSaveSuppressedUntil = Math.max(positionSaveSuppressedUntil, Date.now() + durationMs);
}

function desktopModeBounds(mode: ModeId, config: Record<string, unknown>) {
  if (mode === 'live2d') {
    const display = screen.getPrimaryDisplay().workArea;
    const width = Math.round(clamp(numberFromConfig(config.width, 420), 300, 760));
    const height = Math.round(clamp(numberFromConfig(config.height, 680), 420, 900));
    const anchor = stringFromConfig(config.position_anchor, 'right_bottom');
    const positionX = Math.round(numberFromConfig(config.position_x, 0));
    const positionY = Math.round(numberFromConfig(config.position_y, 0));
    if (anchor === 'left_bottom' || anchor === 'right_bottom') {
      const maxX = display.x + Math.max(0, display.width - width);
      const maxY = display.y + Math.max(0, display.height - height);
      const anchoredX = anchor === 'right_bottom'
        ? display.x + display.width - width - positionX
        : display.x + positionX;
      return {
        width,
        height,
        x: Math.round(clamp(anchoredX, display.x, maxX)),
        y: Math.round(clamp(display.y + display.height - height - positionY, display.y, maxY)),
      };
    }
    return {
      width,
      height,
      x: positionX,
      y: positionY,
    };
  }

  const display = screen.getPrimaryDisplay().workArea;
  const size = Math.round(clamp(
    Math.max(
      numberFromConfig(config.width, BUBBLE_DEFAULT_WINDOW_SIZE),
      numberFromConfig(config.height, BUBBLE_DEFAULT_WINDOW_SIZE),
    ),
    BUBBLE_MIN_WINDOW_SIZE,
    BUBBLE_MAX_WINDOW_SIZE,
  ));
  const xPercent = clamp(numberFromConfig(config.position_x_percent, 1), 0, 1);
  const yPercent = clamp(numberFromConfig(config.position_y_percent, 1), 0, 1);
  const margin = 24;
  const x = Math.round(display.x + margin + (display.width - size - margin * 2) * xPercent);
  const y = Math.round(display.y + margin + (display.height - size - margin * 2) * yPercent);
  return { width: size, height: size, x, y };
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
  if (activeMode === 'live2d' && configuredModeWindowAlwaysOnTop()) {
    modeWindowTopSuppressed = false;
    applyModeWindowTopPreference();
    return;
  }
  modeWindowTopSuppressed = true;
  applyModeWindowTopPreference();
}

function restoreModeWindowTopPreference(): void {
  if (!modeWindowTopSuppressed) return;
  modeWindowTopSuppressed = false;
  applyModeWindowTopPreference();
}

function repaintTransparentModeWindow(targetWindow: BrowserWindow): void {
  if (targetWindow.isDestroyed()) return;
  targetWindow.setBackgroundColor(TRANSPARENT_WINDOW_BACKGROUND);
  if (process.platform === 'darwin') {
    try {
      targetWindow.invalidateShadow();
    } catch {}
  }
}

function showTransparentModeWindowWhenReady(targetWindow: BrowserWindow): void {
  let shown = false;
  const show = () => {
    if (shown || targetWindow.isDestroyed()) return;
    shown = true;
    repaintTransparentModeWindow(targetWindow);
    targetWindow.showInactive();
  };
  targetWindow.once('ready-to-show', show);
  setTimeout(show, 1200);
}

function createDesktopModeWindow(mode: ModeId, config: Record<string, unknown> = {}): void {
  showMacDockIcon();
  if (modeWindow && !modeWindow.isDestroyed() && activeMode === mode) {
    const nextSignature = modeConfigSignature(config);
    let rendererReloaded = false;
    activeModeConfig = config;
    if (nextSignature !== activeModeConfigSignature) {
      activeModeConfigSignature = nextSignature;
      const bounds = desktopModeBounds(mode, config);
      suppressModeWindowPositionSave();
      modeWindow.setBounds(bounds, false);
      repaintTransparentModeWindow(modeWindow);
      setModeWindowPointerInteractive(mode, false);
      modeWindowShapeApplied = false;
      applyModeWindowTopPreference();
      if (mode === 'live2d') {
        modeWindow.setVisibleOnAllWorkspaces(booleanFromConfig(config.show_on_all_spaces, true), { visibleOnFullScreen: true });
      }
      modeWindow.loadURL(rendererUrl({ view: mode, surface: 'desktop' }));
      rendererReloaded = true;
    }
    if (mode === 'bubble') {
      const currentBounds = modeWindow.getBounds();
      const squaredBounds = squareBubbleBounds(currentBounds);
      if (boundsChanged(currentBounds, squaredBounds)) {
        suppressModeWindowPositionSave();
        modeWindow.setBounds(squaredBounds, false);
        repaintTransparentModeWindow(modeWindow);
        modeWindowShapeApplied = false;
      }
    }
    const route = routeForWindow(modeWindow);
    if (route?.view !== mode && !(mode === 'bubble' && route?.view === 'bubble-menu')) {
      modeWindow.loadURL(rendererUrl({ view: mode, surface: 'desktop' }));
      rendererReloaded = true;
    } else if (mode === 'bubble' && !rendererReloaded) {
      modeWindow.loadURL(rendererUrl({ view: mode, surface: 'desktop', launcher_reload: `${Date.now()}` }));
      rendererReloaded = true;
    }
    repaintTransparentModeWindow(modeWindow);
    setModeWindowPointerInteractive(mode, false);
    modeWindowShapeApplied = false;
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
  suppressModeWindowPositionSave();
  const bounds = desktopModeBounds(mode, config);
  const alwaysOnTop = mode === 'live2d'
    ? booleanFromConfig(config.window_on_top, true)
    : booleanFromConfig(config.always_on_top, true);

  const createdModeWindow = new BrowserWindow({
    title: modeWindowTitle(mode),
    ...bounds,
    icon: appIconPath('window'),
    frame: false,
    transparent: true,
    resizable: mode === 'live2d',
    movable: true,
    skipTaskbar: true,
    show: false,
    paintWhenInitiallyHidden: true,
    alwaysOnTop,
    hasShadow: false,
    backgroundColor: TRANSPARENT_WINDOW_BACKGROUND,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  repaintTransparentModeWindow(createdModeWindow);
  showTransparentModeWindowWhenReady(createdModeWindow);
  modeWindow = createdModeWindow;
  enforceWindowTitle(createdModeWindow, modeWindowTitle(mode));

  if (mode === 'live2d' && booleanFromConfig(config.show_on_all_spaces, true)) {
    createdModeWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }
  applyModeWindowTopPreference();
  createdModeWindow.loadURL(rendererUrl({ view: mode, surface: 'desktop' }));
  createdModeWindow.webContents.on('did-start-loading', () => {
    modeWindowShapeApplied = false;
    setModeWindowPointerInteractive(mode, false);
  });
  createdModeWindow.webContents.on('did-finish-load', () => repaintTransparentModeWindow(createdModeWindow));
  createdModeWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (redirectDesktopModeNavigation(targetUrl, mode)) event.preventDefault();
  });
  createdModeWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (redirectDesktopModeNavigation(url, mode)) return { action: 'deny' };
    return { action: 'allow' };
  });
  if ((mode === 'live2d' || mode === 'bubble') && LIVE2D_POINTER_PASSTHROUGH_ENABLED) {
    setTimeout(() => setModeWindowPointerInteractive(mode, false), 260);
  }
  createdModeWindow.on('focus', restoreModeWindowTopPreference);
  createdModeWindow.on('move', () => scheduleModeWindowPositionSave(mode, config));
  createdModeWindow.on('resize', () => {
    repaintTransparentModeWindow(createdModeWindow);
    modeWindowShapeApplied = false;
    setModeWindowPointerInteractive(mode, false);
    scheduleModeWindowPositionSave(mode, config);
  });
  createdModeWindow.on('closed', () => {
    if (modeWindow !== createdModeWindow) return;
    if (positionSaveTimer) {
      clearTimeout(positionSaveTimer);
      positionSaveTimer = null;
    }
    modeWindowIgnoringMouse = false;
    modeWindowShapeApplied = false;
    modeWindowTopSuppressed = false;
    positionSaveSuppressedUntil = 0;
    activeModeConfig = {};
    activeModeConfigSignature = '';
    modeWindow = null;
    activeMode = null;
  });
}

function setModeWindowPointerInteractive(mode: ModeId, interactive: boolean): boolean {
  if (!modeWindow || modeWindow.isDestroyed() || activeMode !== mode) return false;
  if (mode === 'live2d' && !LIVE2D_POINTER_PASSTHROUGH_ENABLED && !interactive) return true;
  if (interactive && mode === 'live2d') {
    restoreModeWindowTopPreference();
    applyModeWindowTopPreference();
    if (!modeWindow.isVisible()) modeWindow.showInactive();
    if (configuredModeWindowAlwaysOnTop(mode)) modeWindow.moveTop();
  }
  const shouldIgnore = !interactive;
  if (modeWindowIgnoringMouse === shouldIgnore) return true;
  modeWindow.setIgnoreMouseEvents(shouldIgnore, { forward: true });
  modeWindowIgnoringMouse = shouldIgnore;
  return true;
}

function setModeWindowHitRegions(mode: ModeId, rawRegions: unknown): boolean {
  if (!modeWindow || modeWindow.isDestroyed() || activeMode !== mode) return false;
  const bounds = modeWindow.getBounds();
  if (mode === 'bubble') {
    try {
      modeWindow.setShape([{ x: 0, y: 0, width: bounds.width, height: bounds.height }]);
      modeWindowShapeApplied = true;
      return true;
    } catch (error) {
      modeWindowShapeApplied = false;
      console.warn('[desktop] setShape failed; falling back to pointer passthrough polling.', error);
      return false;
    }
  }
  const shapePayload = normalizeLauncherShapePayload(rawRegions, bounds);
  const shapeRects = normalizeLauncherShapeRects(shapePayload.regions, bounds, shapePayload.scaleX, shapePayload.scaleY);
  if (!shapeRects.length) {
    modeWindowShapeApplied = false;
    setModeWindowPointerInteractive(mode, false);
    return false;
  }
  try {
    modeWindow.setShape(shapeRects);
    modeWindowShapeApplied = true;
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
  const response = await fetch(`${bridgeUrl}/ui/settings`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as UiSettings;
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

function live2dResourceReady(settings: UiSettings | null | undefined): boolean {
  const state = settings?.mode_settings?.live2d?.config?.model_state;
  return state === 'path_valid' || state === 'loaded';
}

function openLive2DResourceSettings(settings: UiSettings | null | undefined): void {
  showMacDockIcon();
  showMainWindow(
    {
      view: 'settings',
      mode: 'live2d',
      reason: 'live2d-resource-required',
    },
    settings || lastUiSettings,
  );
}

function closeDesktopModeWindow(): void {
  if (!modeWindow || modeWindow.isDestroyed()) {
    activeMode = null;
    activeModeConfig = {};
    activeModeConfigSignature = '';
    return;
  }
  const windowToClose = modeWindow;
  modeWindow = null;
  activeMode = null;
  activeModeConfig = {};
  activeModeConfigSignature = '';
  modeWindowIgnoringMouse = false;
  modeWindowShapeApplied = false;
  modeWindowTopSuppressed = false;
  windowToClose.close();
}

async function openConfiguredDesktopMode(preferredMode?: DisplayModeId, settingsOverride?: UiSettings | null): Promise<void> {
  const settings = settingsOverride || await waitForUiSettings();
  if (settings) lastUiSettings = settings;
  const mode = preferredMode || normalizeDisplayMode(settings?.display?.current_mode);
  if (mode === 'none') {
    closeDesktopModeWindow();
    return;
  }
  if (mode === 'live2d' && !live2dResourceReady(settings)) {
    if (preferredMode === 'live2d') {
      openLive2DResourceSettings(settings);
      return;
    }
    createDesktopModeWindow('bubble', settings?.mode_settings?.bubble?.config || {});
    return;
  }
  const config = settings?.mode_settings?.[mode]?.config || {};
  createDesktopModeWindow(mode, config);
  restoreModeWindowTopPreference();
}

function currentAppBundlePath(): string | null {
  if (process.platform !== 'darwin') return null;
  let current = app.getPath('exe');
  for (let i = 0; i < 8; i += 1) {
    if (current.endsWith('.app') && fs.existsSync(current)) return current;
    const parent = path.dirname(current);
    if (!parent || parent === current) break;
    current = parent;
  }
  return null;
}

function removeCurrentAppBundleAndQuit(): { success: boolean; appBundlePath?: string; error?: string } {
  const appBundlePath = currentAppBundlePath();
  if (!appBundlePath) return { success: false, error: '当前运行环境不是可删除的 macOS .app 包' };
  if (!appBundlePath.endsWith('.app')) return { success: false, error: '拒绝删除非 .app 路径' };
  const bundleName = path.basename(appBundlePath);
  if (!/^Oha-Yachiyo.*\.app$/.test(bundleName)) {
    return { success: false, appBundlePath, error: `拒绝删除非 Oha-Yachiyo 应用包：${bundleName}` };
  }
  const script = [
    'target="$1"',
    'sleep 2',
    'if [[ "$target" == *.app && -d "$target" ]]; then',
    '  if command -v osascript >/dev/null 2>&1; then',
    '    /usr/bin/osascript - "$target" <<\'OSA\' >/dev/null 2>&1 || true',
    'on run argv',
    '  tell application "Finder" to delete POSIX file (item 1 of argv)',
    'end run',
    'OSA',
    '  fi',
    '  sleep 1',
    '  if [[ -d "$target" ]]; then',
    '    rm -rf "$target" >/dev/null 2>&1 || true',
    '  fi',
    'fi',
  ].join('\n');
  try {
    spawn('/bin/zsh', ['-lc', script, 'oha-yachiyo-uninstall', appBundlePath], {
      detached: true,
      stdio: 'ignore',
    }).unref();
    app.quit();
    return { success: true, appBundlePath };
  } catch (error) {
    return {
      success: false,
      appBundlePath,
      error: error instanceof Error ? error.message : String(error),
    };
  }
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

async function showOpenDialogPathsForSender(
  event: IpcMainInvokeEvent,
  options: OpenDialogOptions,
): Promise<string[]> {
  const parentWindow = BrowserWindow.fromWebContents(event.sender) || mainWindow || undefined;
  const result = parentWindow
    ? await dialog.showOpenDialog(parentWindow, options)
    : await dialog.showOpenDialog(options);
  return result.canceled ? [] : result.filePaths;
}

function chatImagePickerSmokePaths(): string[] | null {
  if (process.env[DESKTOP_SMOKE_MODE_ENV] !== '1') return null;
  const raw = process.env[CHAT_IMAGE_PICKER_SMOKE_PATHS_ENV];
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${CHAT_IMAGE_PICKER_SMOKE_PATHS_ENV} must be a JSON array`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${CHAT_IMAGE_PICKER_SMOKE_PATHS_ENV} must be a JSON array`);
  }
  return parsed
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    .map((value) => path.resolve(value));
}

function imageMimeTypeForPath(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  if (ext === '.gif') return 'image/gif';
  if (ext === '.svg') return 'image/svg+xml';
  return 'application/octet-stream';
}

async function readAvatarImageSelection(filePath: string | null): Promise<AvatarImageSelection | null> {
  if (!filePath) return null;
  const stats = await fs.promises.stat(filePath);
  if (!stats.isFile()) throw new Error('请选择图片文件');
  if (stats.size > MAX_AVATAR_IMAGE_BYTES) throw new Error('头像图片不能超过 8 MB');
  const data = await fs.promises.readFile(filePath);
  const mimeType = imageMimeTypeForPath(filePath);
  if (!mimeType.startsWith('image/')) throw new Error('仅支持 PNG、JPG、WEBP、GIF 或 SVG 图片');
  return {
    path: filePath,
    file_name: path.basename(filePath),
    data_url: `data:${mimeType};base64,${data.toString('base64')}`,
  };
}

async function readChatImageSelection(filePath: string): Promise<ChatImageSelection> {
  const stats = await fs.promises.stat(filePath);
  if (!stats.isFile()) throw new Error('请选择图片文件');
  if (stats.size > MAX_CHAT_IMAGE_BYTES) throw new Error('聊天图片不能超过 8 MB');
  const data = await fs.promises.readFile(filePath);
  const mimeType = imageMimeTypeForPath(filePath);
  if (!mimeType.startsWith('image/')) throw new Error('仅支持 PNG、JPG、WEBP、GIF 或 SVG 图片');
  const image = nativeImage.createFromBuffer(data);
  const size = image.isEmpty() ? { width: 0, height: 0 } : image.getSize();
  return {
    path: filePath,
    file_name: path.basename(filePath),
    mime_type: mimeType,
    size: stats.size,
    width: size.width || undefined,
    height: size.height || undefined,
    data_url: `data:${mimeType};base64,${data.toString('base64')}`,
  };
}

function normalizeTerminalTask(value: unknown): DesktopTerminalTask | null {
  return value === 'mac-prerequisites'
    ? value
    : null;
}

function safeTerminalSize(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.round(clamp(value, min, max))
    : fallback;
}

function terminalShell(): { file: string; argsPrefix: string[] } {
  if (process.platform === 'win32') {
    return { file: process.env.ComSpec || 'cmd.exe', argsPrefix: ['/d', '/s', '/c'] };
  }
  return { file: process.env.SHELL || '/bin/zsh', argsPrefix: ['-lc'] };
}

function terminalSessionId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function activeTerminalForOwner(ownerId: number): string | null {
  for (const [id, session] of terminalSessions.entries()) {
    if (session.ownerId === ownerId) return id;
  }
  return null;
}

function terminalPayload(id: string, payload: Record<string, unknown>): Record<string, unknown> {
  return { id, ...payload };
}

function cleanupTerminalSession(id: string): void {
  const session = terminalSessions.get(id);
  if (!session) return;
  terminalSessions.delete(id);
  try {
    session.pty.kill();
  } catch {}
}

function cleanupTerminalsForOwner(ownerId: number): void {
  for (const [id, session] of terminalSessions.entries()) {
    if (session.ownerId === ownerId) cleanupTerminalSession(id);
  }
}

function cleanupAllTerminalSessions(): void {
  for (const id of Array.from(terminalSessions.keys())) cleanupTerminalSession(id);
}

function startInstallerTerminal(
  event: IpcMainInvokeEvent,
  rawTask: unknown,
  rawCols: unknown,
  rawRows: unknown,
): { success: boolean; id?: string; task?: DesktopTerminalTask; title?: string; error?: string } {
  const targetWindow = BrowserWindow.fromWebContents(event.sender);
  if (!targetWindow || targetWindow !== mainWindow) {
    return { success: false, error: '内置终端只能从主窗口启动' };
  }
  const task = normalizeTerminalTask(rawTask);
  if (!task) return { success: false, error: '不支持的终端任务' };
  if (task === 'mac-prerequisites' && process.platform !== 'darwin') {
    return { success: false, error: 'macOS 基础工具准备仅支持 macOS' };
  }
  const existingId = activeTerminalForOwner(event.sender.id);
  if (existingId) return { success: false, error: '已有终端任务正在运行，请先完成或停止当前任务' };

  const { title, command } = terminalTaskCommand(task);
  const shellInfo = terminalShell();
  const cols = safeTerminalSize(rawCols, 100, 40, 240);
  const rows = safeTerminalSize(rawRows, 28, 10, 80);
  const id = terminalSessionId();
  ensureNodePtySpawnHelperExecutable();
  let pty: IPty;
  try {
    pty = nodePty.spawn(shellInfo.file, [...shellInfo.argsPrefix, command], {
      cols,
      rows,
      cwd: app.getPath('home'),
      env: {
        ...process.env,
        TERM: 'xterm-256color',
        COLORTERM: 'truecolor',
      },
      name: 'xterm-256color',
    });
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : '内置终端启动失败' };
  }
  const session = { ownerId: event.sender.id, pty, sender: event.sender, task };
  terminalSessions.set(id, session);

  pty.onData((data) => {
    if (!event.sender.isDestroyed()) {
      event.sender.send('oha:terminalData', terminalPayload(id, { data }));
    }
  });
  pty.onExit(({ exitCode, signal }) => {
    terminalSessions.delete(id);
    if (!event.sender.isDestroyed()) {
      event.sender.send('oha:terminalExit', terminalPayload(id, { exitCode, signal, task }));
    }
  });
  event.sender.once('destroyed', () => cleanupTerminalsForOwner(event.sender.id));
  return { success: true, id, task, title };
}

ipcMain.handle('oha:getBridgeUrl', () => bridgeUrl);
ipcMain.handle('oha:getBridgeToken', () => bridgeSessionToken);
ipcMain.handle('oha:quit', () => {
  app.quit();
});
ipcMain.handle('oha:restartApp', () => {
  app.relaunch();
  app.quit();
});
ipcMain.handle('oha:removeAppBundleAndQuit', () => removeCurrentAppBundleAndQuit());
ipcMain.handle('oha:getAppUpdateInfo', () => appUpdateInfo());
ipcMain.handle('oha:checkAppUpdate', () => checkAppUpdate());
ipcMain.handle('oha:downloadAppUpdate', async (event) => {
  const sender = event.sender;
  const cancelForDestroyedSender = () => {
    cancelActiveAppUpdateDownload('更新页面已关闭，已取消本次更新下载');
  };
  sender.once('destroyed', cancelForDestroyedSender);
  try {
    return await downloadAppUpdate((progress) => {
      if (!sender.isDestroyed()) sender.send('oha:appUpdateDownloadProgress', progress);
    });
  } finally {
    sender.removeListener('destroyed', cancelForDestroyedSender);
  }
});
ipcMain.handle('oha:cancelAppUpdateDownload', () => cancelActiveAppUpdateDownload('已取消本次更新下载'));
ipcMain.handle('oha:installAppUpdate', (_event, dmgPath: unknown) => installDownloadedAppUpdate(dmgPath));
ipcMain.handle('oha:restartBackend', (_event, options: unknown) => {
  const targetBridgeUrl = isRecord(options) ? options.bridgeUrl : undefined;
  return restartBackendProcess(targetBridgeUrl);
});
ipcMain.handle('oha:copyText', (_event, value: unknown) => {
  clipboard.writeText(typeof value === 'string' ? value : '');
});
ipcMain.handle('oha:chooseAvatarImage', async (event) => {
  const selectedPath = await showOpenDialogForSender(event, {
    title: '选择头像图片',
    defaultPath: app.getPath('pictures') || app.getPath('home'),
    properties: ['openFile'],
    filters: [
      { name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif'] },
    ],
  });
  return readAvatarImageSelection(selectedPath);
});
ipcMain.handle('oha:chooseChatImages', async (event) => {
  const selectedPaths = chatImagePickerSmokePaths() || (await showOpenDialogPathsForSender(
    event,
    {
      title: '选择聊天图片',
      defaultPath: app.getPath('pictures') || app.getPath('home'),
      properties: ['openFile', 'multiSelections'],
      filters: [
        { name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'] },
      ],
    },
  ));
  return Promise.all(selectedPaths.map(readChatImageSelection));
});
ipcMain.handle('oha:chooseLive2DModelDirectory', (event) => showOpenDialogForSender(event, {
  title: '选择 Live2D 模型目录',
  defaultPath: app.getPath('home'),
  properties: ['openDirectory'],
}));
ipcMain.handle('oha:chooseLive2DArchive', (event) => showOpenDialogForSender(event, {
  title: '导入 Live2D 资源包 ZIP',
  defaultPath: app.getPath('home'),
  properties: ['openFile'],
  filters: [
    { name: 'Live2D 资源包', extensions: ['zip'] },
    { name: '压缩包', extensions: ['zip'] },
  ],
}));
ipcMain.handle('oha:chooseTtsVoiceArchive', (event) => showOpenDialogForSender(event, {
  title: '导入 GPT-SoVITS 音色包 ZIP',
  defaultPath: app.getPath('home'),
  properties: ['openFile'],
  filters: [
    { name: 'TTS 音色包', extensions: ['zip'] },
    { name: '压缩包', extensions: ['zip'] },
  ],
}));
ipcMain.handle('oha:chooseSkillSources', (event) => showOpenDialogPathsForSender(event, {
  title: '上传 Skills',
  defaultPath: app.getPath('home'),
  properties: ['openFile', 'openDirectory', 'multiSelections'],
  filters: [
    { name: 'Skill ZIP', extensions: ['zip'] },
    { name: '所有文件', extensions: ['*'] },
  ],
}));
ipcMain.handle('oha:chooseDesktopProviderManifest', (event) => showOpenDialogForSender(event, {
  title: '选择桌面 Provider Manifest',
  defaultPath: app.getPath('home'),
  properties: ['openFile'],
  filters: [
    { name: 'Provider Manifest', extensions: ['json'] },
    { name: '所有文件', extensions: ['*'] },
  ],
}));
ipcMain.handle('oha:openPath', async (_event, value: unknown) => {
  const targetPath = typeof value === 'string' ? value.trim() : '';
  if (!targetPath) throw new Error('路径不能为空');
  const error = await shell.openPath(targetPath);
  if (error) throw new Error(error);
});
ipcMain.handle('oha:openExternalUrl', async (_event, value: unknown) => {
  const targetUrl = typeof value === 'string' ? value.trim() : '';
  if (!/^https?:\/\//.test(targetUrl)) throw new Error('仅支持打开 http(s) 链接');
  await shell.openExternal(targetUrl);
});
ipcMain.handle('oha:openView', (_event, view: unknown, params: unknown) => {
  openAppView(normalizeView(view), normalizeParams(params));
});
ipcMain.handle('oha:openDesktopMode', (_event, mode: unknown) => openConfiguredDesktopMode(normalizePreferredDisplayMode(mode)));
ipcMain.handle('oha:moveLauncherWindow', moveLauncherWindow);
ipcMain.handle('oha:getLauncherPointerState', (_event, mode: unknown) => launcherPointerState(mode));
ipcMain.handle('oha:terminalStart', startInstallerTerminal);
ipcMain.handle('oha:terminalWrite', (_event, rawId: unknown, rawData: unknown) => {
  const id = typeof rawId === 'string' ? rawId : '';
  const session = terminalSessions.get(id);
  if (!session || session.sender.id !== _event.sender.id) return false;
  session.pty.write(typeof rawData === 'string' ? rawData : '');
  return true;
});
ipcMain.handle('oha:terminalResize', (_event, rawId: unknown, rawCols: unknown, rawRows: unknown) => {
  const id = typeof rawId === 'string' ? rawId : '';
  const session = terminalSessions.get(id);
  if (!session || session.sender.id !== _event.sender.id) return false;
  session.pty.resize(safeTerminalSize(rawCols, session.pty.cols, 40, 240), safeTerminalSize(rawRows, session.pty.rows, 10, 80));
  return true;
});
ipcMain.handle('oha:terminalKill', (_event, rawId: unknown) => {
  const id = typeof rawId === 'string' ? rawId : '';
  const session = terminalSessions.get(id);
  if (!session || session.sender.id !== _event.sender.id) return false;
  cleanupTerminalSession(id);
  return true;
});
ipcMain.handle('oha:setLauncherHitRegions', (event, mode: unknown, regions: unknown) => {
  const targetWindow = BrowserWindow.fromWebContents(event.sender);
  if (!targetWindow || targetWindow !== modeWindow) return false;
  return setModeWindowHitRegions(normalizeMode(mode), regions);
});
ipcMain.handle('oha:setLauncherPointerInteractive', (event, mode: unknown, interactive: unknown) => {
  const targetWindow = BrowserWindow.fromWebContents(event.sender);
  if (!targetWindow || targetWindow !== modeWindow) return false;
  return setModeWindowPointerInteractive(normalizeMode(mode), Boolean(interactive));
});
ipcMain.handle('oha:openLauncherMenu', (event, mode: unknown) => {
  const modeId = normalizeMode(mode);
  const targetWindow = BrowserWindow.fromWebContents(event.sender) || undefined;
  const menu = Menu.buildFromTemplate([
    { label: '打开对话', click: () => showChatWindow() },
    { label: '主控台', click: () => showMainWindowAtLastRoute({ restore: 'last' }) },
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
    { label: '退出 Oha-Yachiyo', click: () => app.quit() },
  ]);
  menu.popup({ window: targetWindow });
});

// Electron can otherwise launch two independent backend/runtime owners against
// the same database.  Acquire the application lock before any whenReady startup
// work; a secondary launch only brings the existing assistant to the front.
const hasPrimaryInstanceLock = app.requestSingleInstanceLock();
if (!hasPrimaryInstanceLock) {
  recordElectronProcessSmoke('secondary');
  app.quit();
} else {
  recordElectronProcessSmoke('primary');
  app.on('second-instance', () => {
    recordElectronProcessSmoke('second-instance');
    if (process.platform === 'darwin') app.focus({ steal: true });
    showMainWindowAtLastRoute({ restore: 'last' });
    if (process.platform === 'darwin') app.focus({ steal: true });
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.focus();
    recordSecondInstanceWindowFocus();
  });

  app.whenReady().then(() => {
    showMacDockIcon();
    void (async () => {
      if (process.env[ELECTRON_NATIVE_BRIDGE_SMOKE_ENV] === '1') {
        try {
          const smokeResult = await runElectronNativeBridgeSmoke();
          console.log(`electron-native-bridge-smoke:${JSON.stringify(smokeResult)}`);
          closeNativeRuntimeServer();
          app.exit(smokeResult.ok === true ? 0 : 1);
        } catch (error) {
          const smokeResult = {
            ok: false,
            mode: 'electron_native_bridge_smoke',
            error: error instanceof Error ? error.message : String(error),
          };
          console.log(`electron-native-bridge-smoke:${JSON.stringify(smokeResult)}`);
          closeNativeRuntimeServer();
          app.exit(1);
        }
        return;
      }
      await prepareBridgeUrlForPackagedBackend();
      if (appShutdownRequested) return;
      try {
        await startNativeRuntimeServer();
      } catch (error) {
        console.warn('[native-runtime] failed to start Electron native bridge:', error);
      }
      if (appShutdownRequested) {
        closeNativeRuntimeServer();
        return;
      }
      try {
        await startPackagedCuaMcpBridge();
      } catch (error) {
        console.warn('[cua-mcp-bridge] listener unavailable; packaged backend will fail closed:', error);
      }
      if (appShutdownRequested) return;
      startBackend();
      if (appShutdownRequested) return;
      createMainWindow({ view: 'main' }, lastUiSettings, { focusOnReady: false });
      hasEnteredMainExperience = true;
      const settings = await waitForUiSettings();
      if (appShutdownRequested) return;
      if (settings) lastUiSettings = settings;
      configureTray(settings);
      if (!focusMainWindowWithoutNavigation(
        routeForWindow(mainWindow),
        settings,
        { focusOnReady: false },
      )) {
        createMainWindow({ view: 'main' }, settings, { focusOnReady: false });
      }
      await openConfiguredDesktopMode(undefined, settings);
      if (appShutdownRequested) return;
      if (settings?.window_mode?.open_chat_on_start) showChatWindow();
    })();

    app.on('activate', showMainWindowFromAppActivation);
  });
}

app.on('before-quit', (event) => {
  if (activeAppUpdateDownload && !appUpdateQuitConfirmed) {
    event.preventDefault();
    if (!confirmCancelAppUpdateDownload(mainWindow, '退出并取消更新')) return;
    appUpdateQuitConfirmed = true;
    setTimeout(() => app.quit(), 0);
    return;
  }
  appShutdownRequested = true;
  cleanupAllTerminalSessions();
  if (backendShutdownPromise) {
    event.preventDefault();
    return;
  }
  if (
    !backendShutdownBeforeQuit
    && (backendProcess || backendTerminationPromise || cuaMcpBridge)
  ) {
    event.preventDefault();
    const backendTermination = backendTerminationPromise ?? terminateBackend();
    backendShutdownPromise = Promise.allSettled([
      backendTermination,
      closePackagedCuaMcpBridge(),
    ]).then(() => {
      backendShutdownBeforeQuit = true;
      backendShutdownPromise = null;
      app.quit();
    });
    return;
  }
  stopBackend();
  closeNativeRuntimeServer();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
