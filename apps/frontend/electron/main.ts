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
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import http, { type IncomingMessage, type RequestOptions } from 'node:http';
import https from 'node:https';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const FRONTEND_DEV_URL = process.env.HERMES_YACHIYO_FRONTEND_DEV_URL || 'http://127.0.0.1:5174';
const BRIDGE_URL_ENV = 'HERMES_YACHIYO_BRIDGE_URL';
const DEV_BRIDGE_URL = 'http://127.0.0.1:8420';
const PACKAGED_BRIDGE_URL = 'http://127.0.0.1:18420';
let bridgeUrl = initialBridgeUrl();
const APP_BUILD_METADATA_FILE = 'hermes-yachiyo-build.json';
const DEFAULT_UPDATE_REPOSITORY = 'kuguya-AI-app-develop/Hermes-Yachiyo';
const BRIDGE_SETTINGS_RETRIES = 40;
const BRIDGE_SETTINGS_RETRY_MS = 250;
const BUBBLE_SCREEN_MARGIN = 24;
const POSITION_SAVE_DEBOUNCE_MS = 260;
const LIVE2D_POINTER_PASSTHROUGH_ENABLED = true;
const TRANSPARENT_WINDOW_BACKGROUND = '#00000000';
const MAX_LAUNCHER_SHAPE_RECTS = 10000;
const MAX_AVATAR_IMAGE_BYTES = 8 * 1024 * 1024;
type IconKind = 'dock' | 'tray' | 'window';

type AppView =
  | 'main'
  | 'chat'
  | 'settings'
  | 'installer'
  | 'provider'
  | 'resources'
  | 'workspace'
  | 'diagnostics'
  | 'tools'
  | 'tools-all'
  | 'activity-all'
  | 'app-update'
  | 'proactive-tts'
  | 'bubble'
  | 'bubble-menu'
  | 'live2d';
type ModeId = 'bubble' | 'live2d';
type DisplayModeId = ModeId | 'none';
type InstallerTerminalTask = 'mac-prerequisites' | 'install-hermes' | 'hermes-setup' | 'update-hermes' | 'update-hermes-backup';

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
};

type AppUpdateDownloadProgress = {
  status: 'starting' | 'downloading' | 'verifying' | 'completed' | 'failed';
  file_name?: string;
  received_bytes?: number;
  total_bytes?: number;
  percent?: number;
  error?: string;
};

type AvatarImageSelection = {
  path: string;
  data_url: string;
  file_name: string;
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
let positionSaveSuppressedUntil = 0;
let modeWindowIgnoringMouse = false;
let modeWindowShapeApplied = false;
let modeWindowTopSuppressed = false;
let lastInstallReady: boolean | null = null;
let lastUiSettings: UiSettings | null = null;
let hasEnteredMainExperience = false;
let backendRestartPromise: Promise<{ success: boolean; bridgeUrl?: string; error?: string }> | null = null;
let lastDownloadedAppUpdate: AppUpdateDownloadResult | null = null;
const enforcedWindowTitles = new WeakMap<BrowserWindow, string>();
const titleHandlersInstalled = new WeakSet<BrowserWindow>();
const terminalSessions = new Map<string, {
  ownerId: number;
  pty: IPty;
  sender: WebContents;
  task: InstallerTerminalTask;
}>();

type MainWindowOptions = {
  respectStartMinimized?: boolean;
  focusOnReady?: boolean;
};

app.setName('Hermes-Yachiyo');
showMacDockIcon();

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

function defaultLatestJsonUrl(branch = 'develop', repository = DEFAULT_UPDATE_REPOSITORY): string {
  const latestBranch = branch === 'main' ? 'main' : 'develop';
  return `https://github.com/${repository}/releases/download/${latestBranch}-latest/Hermes-Yachiyo-${latestBranch}-latest.json`;
}

function defaultAppBuildMetadata(): AppBuildMetadata {
  return {
    name: 'Hermes-Yachiyo',
    channel: 'experimental',
    branch: 'develop',
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
        : defaultLatestJsonUrl(branch, repository),
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

function safeDmgFileName(value: unknown, branch: string): string {
  const fallback = `Hermes-Yachiyo-${branch === 'main' ? 'main' : 'develop'}-latest.dmg`;
  if (typeof value !== 'string' || !value.trim()) return fallback;
  const name = path.basename(value.trim());
  return /^[A-Za-z0-9._-]+\.dmg$/.test(name) ? name : fallback;
}

function downloadedUpdateIsForDifferentBuild(
  current: AppBuildMetadata,
  download: AppUpdateDownloadResult | null | undefined,
): download is AppUpdateDownloadResult {
  if (!download?.ok || !download.path || !fs.existsSync(download.path)) return false;
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
  if (!download?.ok || !download.path || !fs.existsSync(download.path)) return false;
  const expectedSha = typeof latest.sha256 === 'string' ? latest.sha256.trim().toLowerCase() : '';
  if (expectedSha && download.sha256?.toLowerCase() === expectedSha) return true;
  const downloadLatest = download.latest || {};
  if (latest.commit && downloadLatest.commit && latest.commit === downloadLatest.commit) return true;
  if (latest.version && downloadLatest.version && latest.version === downloadLatest.version) {
    return numericBuildNumber(latest.build_number ?? latest.run_number) === numericBuildNumber(downloadLatest.build_number ?? downloadLatest.run_number);
  }
  return false;
}

function readDownloadedAppUpdate(current?: AppBuildMetadata): AppUpdateDownloadResult | null {
  if (lastDownloadedAppUpdate?.ok && (!current || downloadedUpdateIsForDifferentBuild(current, lastDownloadedAppUpdate))) {
    return lastDownloadedAppUpdate;
  }
  const record = readJsonFile<AppUpdateDownloadResult>(updateDownloadRecordPath());
  if (!record?.ok || !record.path || !fs.existsSync(record.path)) return null;
  if (current && !downloadedUpdateIsForDifferentBuild(current, record)) return null;
  lastDownloadedAppUpdate = record;
  return record;
}

function writeDownloadedAppUpdate(record: AppUpdateDownloadResult): void {
  try {
    fs.mkdirSync(updateDownloadsDir(), { recursive: true });
    fs.writeFileSync(updateDownloadRecordPath(), JSON.stringify(record, null, 2), 'utf8');
  } catch (error) {
    console.warn('[updater] failed to persist downloaded update:', error);
  }
}

function clearDownloadedAppUpdate(): void {
  lastDownloadedAppUpdate = null;
  try {
    fs.rmSync(updateDownloadRecordPath(), { force: true });
  } catch {}
}

function appUpdateInfo(): AppUpdateInfo {
  const current = readAppBuildMetadata();
  const appBundlePath = currentAppBundlePath() || undefined;
  const downloadedUpdate = readDownloadedAppUpdate(current) || undefined;
  return {
    supported: process.platform === 'darwin' && app.isPackaged && Boolean(appBundlePath),
    packaged: app.isPackaged,
    current,
    latest_json_url: current.latest_json_url || defaultLatestJsonUrl(current.branch, current.repository),
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
  if (url.protocol === 'https:') return https.get(url, options, callback);
  if (url.protocol === 'http:') return http.get(url, options, callback);
  throw new Error('仅支持 http(s) 更新链接');
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
        'User-Agent': 'Hermes-Yachiyo-Updater',
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

function downloadFile(
  url: string,
  destination: string,
  onProgress?: (progress: AppUpdateDownloadProgress) => void,
  redirects = 5,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      reject(new Error('DMG 下载链接无效'));
      return;
    }
    const tmpDestination = `${destination}.part`;
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    onProgress?.({ status: 'starting', file_name: path.basename(destination), received_bytes: 0 });
    const request = httpRequest(parsed, {
      headers: {
        Accept: 'application/octet-stream',
        'User-Agent': 'Hermes-Yachiyo-Updater',
      },
    }, (response) => {
      const status = response.statusCode || 0;
      const location = response.headers.location;
      if ([301, 302, 303, 307, 308].includes(status) && location && redirects > 0) {
        response.resume();
        downloadFile(redirectedUrl(location, parsed).toString(), destination, onProgress, redirects - 1).then(resolve, reject);
        return;
      }
      if (status < 200 || status >= 300) {
        response.resume();
        reject(new Error(`DMG 下载失败：HTTP ${status}`));
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
      const output = fs.createWriteStream(tmpDestination);
      pipeline(response, progressStream, output)
        .then(() => fs.promises.rename(tmpDestination, destination))
        .then(() => resolve(), reject);
    });
    request.setTimeout(120000, () => request.destroy(new Error('DMG 下载超时')));
    request.on('error', (error) => {
      fs.rm(tmpDestination, { force: true }, () => reject(error));
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
    const latest = await fetchJson<LatestReleaseMetadata>(cacheBustedUrl(info.latest_json_url));
    const decision = updateAvailableReason(info.current, latest);
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
  const check = await checkAppUpdate();
  if (!check.ok || !check.latest) {
    return { ok: false, error: check.error || '无法读取更新元数据' };
  }
  if (downloadedUpdateMatchesLatest(check.downloaded_update, check.latest)) {
    return check.downloaded_update;
  }
  const downloadUrl = typeof check.latest.download_url === 'string' ? check.latest.download_url.trim() : '';
  if (!downloadUrl) return { ok: false, latest: check.latest, error: '更新元数据缺少 DMG 下载链接' };

  const fileName = safeDmgFileName(check.latest.dmg_name || downloadUrl, check.current.branch);
  const destination = path.join(updateDownloadsDir(), fileName);
  try {
    await downloadFile(downloadUrl, destination, onProgress);
    onProgress?.({ status: 'verifying', file_name: fileName });
    const actualSha256 = await sha256File(destination);
    const expectedSha256 = typeof check.latest.sha256 === 'string' ? check.latest.sha256.trim().toLowerCase() : '';
    if (expectedSha256 && actualSha256.toLowerCase() !== expectedSha256) {
      await fs.promises.rm(destination, { force: true });
      clearDownloadedAppUpdate();
      return {
        ok: false,
        latest: check.latest,
        error: 'DMG SHA256 校验失败，已删除下载文件',
      };
    }
    lastDownloadedAppUpdate = {
      ok: true,
      path: destination,
      file_name: fileName,
      sha256: actualSha256,
      verified: Boolean(expectedSha256),
      latest: check.latest,
    };
    writeDownloadedAppUpdate(lastDownloadedAppUpdate);
    onProgress?.({ status: 'completed', file_name: fileName, percent: 100 });
    return lastDownloadedAppUpdate;
  } catch (error) {
    onProgress?.({
      status: 'failed',
      file_name: fileName,
      error: error instanceof Error ? error.message : String(error),
    });
    return {
      ok: false,
      latest: check.latest,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function normalizedDownloadedDmgPath(value: unknown): string | null {
  const candidate = typeof value === 'string' && value.trim()
    ? value.trim()
    : lastDownloadedAppUpdate?.path || '';
  if (!candidate) return null;
  const resolved = path.resolve(candidate);
  const downloads = path.resolve(updateDownloadsDir());
  if (!resolved.startsWith(`${downloads}${path.sep}`)) return null;
  if (!resolved.endsWith('.dmg')) return null;
  return fs.existsSync(resolved) ? resolved : null;
}

function installDownloadedAppUpdate(rawPath: unknown): { success: boolean; appBundlePath?: string; dmgPath?: string; error?: string } {
  if (process.platform !== 'darwin') return { success: false, error: '应用更新安装仅支持 macOS' };
  if (!app.isPackaged) return { success: false, error: '开发环境不支持覆盖安装，请使用已打包的 DMG 版本' };
  const appBundlePath = currentAppBundlePath();
  if (!appBundlePath) return { success: false, error: '当前运行环境不是可更新的 macOS .app 包' };
  const dmgPath = normalizedDownloadedDmgPath(rawPath);
  if (!dmgPath) return { success: false, appBundlePath, error: '未找到已下载的更新 DMG' };
  const appName = path.basename(appBundlePath);
  if (!/^Hermes-Yachiyo.*\.app$/.test(appName)) {
    return { success: false, appBundlePath, dmgPath, error: `拒绝覆盖非 Hermes-Yachiyo 应用包：${appName}` };
  }
  const script = [
    'set -euo pipefail',
    'app_path="$1"',
    'dmg_path="$2"',
    'app_name="$3"',
    'app_pid="$4"',
    'while kill -0 "$app_pid" >/dev/null 2>&1; do sleep 0.25; done',
    'mount_dir="$(mktemp -d "${TMPDIR:-/tmp}/hermes-yachiyo-update.XXXXXX")"',
    'cleanup() { /usr/bin/hdiutil detach "$mount_dir" -quiet >/dev/null 2>&1 || true; rmdir "$mount_dir" >/dev/null 2>&1 || true; }',
    'trap cleanup EXIT',
    '/usr/bin/hdiutil attach "$dmg_path" -nobrowse -readonly -mountpoint "$mount_dir" -quiet',
    'source_app="$mount_dir/$app_name"',
    'if [[ ! -d "$source_app" ]]; then source_app="$(/usr/bin/find "$mount_dir" -maxdepth 2 -type d -name "$app_name" -print -quit)"; fi',
    'if [[ ! -d "$source_app" ]]; then echo "Cannot find $app_name in DMG" >&2; exit 1; fi',
    'parent_dir="$(dirname "$app_path")"',
    'tmp_app="$parent_dir/.$app_name.updating.$$"',
    'rm -rf "$tmp_app"',
    '/usr/bin/ditto "$source_app" "$tmp_app"',
    'rm -rf "$app_path"',
    'mv "$tmp_app" "$app_path"',
    '/usr/bin/open "$app_path"',
  ].join('\n');
  try {
    spawn('/bin/zsh', ['-lc', script, 'hermes-yachiyo-update', appBundlePath, dmgPath, appName, String(process.pid)], {
      detached: true,
      stdio: 'ignore',
    }).unref();
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

function iconCandidates(kind: IconKind): string[] {
  return kind === 'tray' ? ['icon.png', 'icon.icns'] : ['icon.icns', 'icon.png'];
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
  for (const name of preferred) {
    const candidate = rootAssetPath('assets', name);
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
  if (view === 'installer') return 'Hermes-Yachiyo 安装向导';
  if (view === 'provider') return 'Hermes-Yachiyo 模型配置';
  if (view === 'resources') return 'Hermes-Yachiyo 资源管理';
  if (view === 'workspace') return 'Hermes-Yachiyo 工作区';
  if (view === 'settings') return params.mode === 'live2d'
    ? 'Hermes-Yachiyo Live2D 设置'
    : params.mode === 'bubble'
      ? 'Hermes-Yachiyo Bubble 设置'
      : 'Hermes-Yachiyo 应用设置';
  if (view === 'diagnostics') return 'Hermes-Yachiyo 诊断工具';
  if (view === 'tools') return 'Hermes-Yachiyo 工具中心';
  if (view === 'tools-all') return 'Hermes-Yachiyo 桌面工具';
  if (view === 'activity-all') return 'Hermes-Yachiyo 活动日志';
  if (view === 'proactive-tts') return 'Hermes-Yachiyo 主动关怀语音';
  if (view === 'chat') return 'Hermes-Yachiyo 对话';
  return 'Hermes-Yachiyo 主控台';
}

function modeWindowTitle(mode: ModeId): string {
  return mode === 'live2d' ? 'Hermes-Yachiyo Live2D' : 'Hermes-Yachiyo Bubble';
}

function macOSPrerequisiteCommand(): string {
  return [
    'echo "Hermes-Yachiyo macOS 基础工具检查"',
    'if ! xcode-select -p >/dev/null 2>&1; then echo "将打开 Xcode Command Line Tools 安装器"; xcode-select --install || true; else echo "Xcode Command Line Tools 已安装"; fi',
    'if ! command -v brew >/dev/null 2>&1; then echo "正在安装 Homebrew"; /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; fi',
    'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
    'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
    'if command -v brew >/dev/null 2>&1; then brew update && brew install git curl; else echo "未检测到 brew，请根据终端提示完成 Homebrew 安装后重新运行"; fi',
    'echo "基础工具准备完成。请回到 Hermes-Yachiyo 点击重新检测或安装 Hermes Agent。"',
  ].join('\n');
}

function hermesInstallCommand(): string {
  return [
    'echo "Hermes Agent 安装开始"',
    'set -o pipefail',
    'install_script="$(mktemp -t hermes-agent-install.XXXXXX)" || exit 1',
    'target_dir="${HERMES_AGENT_INSTALL_DIR:-$HOME/.hermes/hermes-agent}"',
    'install_lock_dir="${HERMES_AGENT_INSTALL_LOCK_DIR:-$HOME/.hermes/.hermes-agent-install.lock}"',
    'mkdir -p "$(dirname "$install_lock_dir")" || exit $?',
    'if ! mkdir "$install_lock_dir" 2>/dev/null; then',
    '  echo "Hermes Agent 正在被另一个 Hermes-Yachiyo 进程安装或更新，请稍后重试。"',
    '  exit 75',
    'fi',
    'shim_path="$HOME/.local/bin/hermes"',
    'target_bin="$target_dir/venv/bin/hermes"',
    'if [ -L "$shim_path" ]; then',
    '  shim_target="$(readlink "$shim_path" 2>/dev/null || true)"',
    '  case "$shim_target" in',
    '    "$target_bin"|*/.hermes/hermes-agent/venv/bin/hermes)',
    '      rm -f "$shim_path"',
    '      ;;',
    '  esac',
    'fi',
    'if [ -f "$target_bin" ] && grep -Fq "exec \\"$target_bin\\"" "$target_bin" 2>/dev/null; then',
    '  printf "检测到损坏的 Hermes 启动脚本，正在清理后重新安装...\\n"',
    '  rm -rf "$target_dir"',
    'fi',
    'target_existed=0',
    '[ -e "$target_dir" ] && target_existed=1',
    'trap \'rm -rf "$install_lock_dir"; rm -f "$install_script"\' EXIT',
    'curl --retry 3 --retry-delay 2 --connect-timeout 20 -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh -o "$install_script"',
    'curl_exit_code=$?',
    'if [ "$curl_exit_code" -ne 0 ]; then printf "\\nHermes Agent 安装脚本下载失败，退出码：%s\\n" "$curl_exit_code"; exit "$curl_exit_code"; fi',
    'export GIT_CONFIG_COUNT=3',
    'export GIT_CONFIG_KEY_0=http.version',
    'export GIT_CONFIG_VALUE_0=HTTP/1.1',
    'export GIT_CONFIG_KEY_1=http.postBuffer',
    'export GIT_CONFIG_VALUE_1=524288000',
    'export GIT_CONFIG_KEY_2=http.lowSpeedTime',
    'export GIT_CONFIG_VALUE_2=60',
    'last_exit=0',
    'for attempt in 1 2 3; do',
    '  printf "\\nHermes Agent 安装尝试 %s/3\\n" "$attempt"',
    '  bash "$install_script" --skip-setup',
    '  last_exit=$?',
    '  if [ "$last_exit" -eq 0 ]; then break; fi',
    '  if [ "$attempt" -lt 3 ]; then',
    '    printf "Hermes Agent 安装尝试 %s/3 失败，退出码：%s；即将重试...\\n" "$attempt" "$last_exit"',
    '    if [ "$target_existed" -eq 0 ] && [ -d "$target_dir" ] && [ ! -x "$target_dir/venv/bin/hermes" ]; then rm -rf "$target_dir"; fi',
    '    sleep $((attempt * 2))',
    '  fi',
    'done',
    'hermes_install_exit_code="$last_exit"',
    'printf "\\nHermes Agent 安装命令已结束，退出码：%s\\n" "$hermes_install_exit_code"',
    'exit "$hermes_install_exit_code"',
  ].join('\n');
}

function hermesUpdateCommand(fullBackup = false): string {
  const backupFlag = fullBackup ? '--backup' : '--no-backup';
  const updateArgs = `--gateway --yes ${backupFlag}`;
  const backupNote = fullBackup
    ? '说明：已启用完整 pre-update backup。Hermes 会压缩整个 ~/.hermes，目录较大时可能长时间停在 Creating pre-update backup；--yes 会自动确认更新过程中的 stash 恢复等提示。'
    : '说明：Yachiyo 默认跳过完整 pre-update backup；Hermes 原生完整备份会压缩整个 ~/.hermes，目录较大时可能长时间停在 Creating pre-update backup；--yes 会自动确认更新过程中的 stash 恢复等提示。';
  return [
    'echo "Hermes Agent 更新开始"',
    'set -o pipefail',
    'if ! command -v hermes >/dev/null 2>&1; then echo "未找到 hermes 命令，请先完成 Hermes Agent 安装或刷新 PATH。"; exit 127; fi',
    'install_lock_dir="${HERMES_AGENT_INSTALL_LOCK_DIR:-$HOME/.hermes/.hermes-agent-install.lock}"',
    'mkdir -p "$(dirname "$install_lock_dir")" || exit $?',
    'if ! mkdir "$install_lock_dir" 2>/dev/null; then echo "Hermes Agent 正在被另一个 Hermes-Yachiyo 进程安装或更新，请稍后重试。"; exit 75; fi',
    'trap \'rm -rf "$install_lock_dir"\' EXIT',
    'echo "当前版本："',
    'version_output="$(hermes version 2>&1 || true)"',
    'printf "%s\\n" "$version_output"',
    'project_path="$(printf "%s\\n" "$version_output" | awk -F": " \'/^Project:/ {print $2; exit}\')"',
    'if [ -n "$project_path" ] && [ -d "$project_path/.git" ]; then origin_url="$(git -C "$project_path" remote get-url origin 2>/dev/null || true)"; if [ -n "$origin_url" ]; then echo "更新来源：$origin_url / origin/main"; fi; fi',
    'echo ""',
    `echo "运行：hermes update ${updateArgs}"`,
    `echo "${backupNote}"`,
    `hermes update ${updateArgs}`,
    'hermes_update_exit_code=$?',
    'printf "\\nHermes Agent 更新命令已结束，退出码：%s\\n" "$hermes_update_exit_code"',
    'if [ "$hermes_update_exit_code" -eq 0 ]; then echo "更新完成。Hermes-Yachiyo 将刷新工具清单。"; fi',
    'exit "$hermes_update_exit_code"',
  ].join('\n');
}

function terminalTaskCommand(task: InstallerTerminalTask): { title: string; command: string } {
  if (task === 'mac-prerequisites') {
    return { title: '准备 macOS 基础工具', command: macOSPrerequisiteCommand() };
  }
  if (task === 'install-hermes') {
    return { title: '安装 Hermes Agent', command: hermesInstallCommand() };
  }
  if (task === 'update-hermes') {
    return { title: '更新 Hermes Agent', command: hermesUpdateCommand(false) };
  }
  if (task === 'update-hermes-backup') {
    return { title: '更新 Hermes Agent（完整备份）', command: hermesUpdateCommand(true) };
  }
  return { title: '配置 Hermes Agent', command: 'hermes setup' };
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
  const binaryName = process.platform === 'win32' ? 'hermes-yachiyo-backend.exe' : 'hermes-yachiyo-backend';
  const candidate = path.join(process.resourcesPath, 'backend', binaryName);
  return app.isPackaged && fs.existsSync(candidate) ? candidate : null;
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
  if (process.env.HERMES_YACHIYO_SKIP_BACKEND === '1') return;
  if (backendProcess) return;

  const backendBinary = packagedBackendPath();
  const command = backendBinary || process.env.HERMES_YACHIYO_PYTHON || 'python3';
  const args = backendBinary ? [] : ['-m', 'apps.desktop_backend.app'];
  backendProcess = spawn(command, args, {
    cwd: backendBinary ? process.resourcesPath : projectRoot(),
    env: {
      ...process.env,
      PYTHONPATH: projectRoot(),
      HERMES_YACHIYO_DESKTOP_BACKEND: '1',
      [BRIDGE_URL_ENV]: bridgeUrl,
    },
  });

  backendProcess.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
  backendProcess.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
  backendProcess.on('error', (error) => {
    console.error(`[backend] failed to start: ${error.message}`);
    backendProcess = null;
  });
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

function terminateBackend(timeoutMs = 5000): Promise<void> {
  const processToStop = backendProcess;
  if (!processToStop) return Promise.resolve();
  backendProcess = null;
  return new Promise((resolve) => {
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
  });
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
  if (backendRestartPromise) return backendRestartPromise;
  backendRestartPromise = (async () => {
    const nextBridgeUrl = normalizeBridgeUrl(targetBridgeUrl) || bridgeUrl;
    const previousBridgeUrl = bridgeUrl;
    bridgeUrl = nextBridgeUrl;
    await terminateBackend();
    startBackend();
    const settings = await waitForUiSettings();
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
  Object.entries(params)
    .filter(([key]) => key !== 'view' && key !== 'mode' && key !== 'restore')
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

function chatWindowBounds(settings: UiSettings | null = lastUiSettings, workArea: Rectangle = screen.getPrimaryDisplay().workArea): { width: number; height: number } {
  const base = mainWindowBounds(settings);
  const maxWidth = Math.max(860, Math.min(1440, workArea.width));
  const maxHeight = Math.max(580, Math.min(1000, workArea.height));
  return {
    width: Math.round(clamp(Math.max(base.width, 1120), 860, maxWidth)),
    height: Math.round(clamp(Math.max(base.height, 760), 580, maxHeight)),
  };
}

function chatWindowMinSize(settings: UiSettings | null = lastUiSettings, workArea: Rectangle = screen.getPrimaryDisplay().workArea): { width: number; height: number } {
  const bounds = chatWindowBounds(settings, workArea);
  return {
    width: Math.min(1080, bounds.width),
    height: Math.min(720, bounds.height),
  };
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
  if (normalizeView(params.view) !== 'installer') {
    hasEnteredMainExperience = true;
    configureTray(settings || lastUiSettings);
  }
  const bounds = mainWindowBounds(settings);
  const startHidden = Boolean(options.respectStartMinimized && settings?.app?.start_minimized);
  const focusOnReady = options.focusOnReady !== false;
  const title = mainWindowTitle(params);
  mainWindow = new BrowserWindow({
    title,
    ...bounds,
    icon: appIconPath('window'),
    minWidth: 860,
    minHeight: 580,
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
  if (normalizeView(params.view) !== 'installer') {
    hasEnteredMainExperience = true;
    configureTray(settings || lastUiSettings);
  }
  enforceWindowTitle(mainWindow, mainWindowTitle(params));
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

function showMainWindowFromAppActivation(): void {
  void (async () => {
    const installInfo = await waitForInstallInfo();
    if (installInfo) {
      const readyNow = installReady(installInfo);
      if (readyNow) {
        lastInstallReady = true;
        hasEnteredMainExperience = true;
      } else if (!hasEnteredMainExperience && lastInstallReady !== true) {
        lastInstallReady = false;
      }
    }
    const currentRoute = routeForWindow(mainWindow);
    const shouldShowInstaller = lastInstallReady === false
      && !hasEnteredMainExperience
      && currentRoute?.view !== 'main';
    const params = shouldShowInstaller ? { view: 'installer' } : mainActivationRouteParams(currentRoute);
    showMainWindow(params, lastUiSettings);
    if (!shouldShowInstaller && params.view === 'main') {
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
    if (aboutIcon) app.setAboutPanelOptions({ applicationName: 'Hermes-Yachiyo', iconPath: aboutIcon });
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
    title: 'Hermes-Yachiyo 对话',
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
  enforceWindowTitle(chatWindow, 'Hermes-Yachiyo 对话');

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
    `window.history.pushState(null, '', ${JSON.stringify(route)}); window.dispatchEvent(new Event('hermes-route-change'));`,
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
  const route = routeForWindow(mainWindow);
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
    'settings',
    'installer',
    'provider',
    'resources',
    'workspace',
    'diagnostics',
    'tools',
    'tools-all',
    'activity-all',
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
    return { view, params };
  }
  const view = normalizeView(parsed.searchParams.get('view'));
  return { view, params };
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

async function saveLauncherPosition(mode: ModeId, bounds: Rectangle): Promise<void> {
  const workArea = workAreaForBounds(bounds);
  try {
    const response = await fetch(`${bridgeUrl}/ui/launcher/position`, {
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
  if (Date.now() < positionSaveSuppressedUntil) return;
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
    }
    const route = routeForWindow(modeWindow);
    if (route?.view !== mode && !(mode === 'bubble' && route?.view === 'bubble-menu')) {
      modeWindow.loadURL(rendererUrl({ view: mode, surface: 'desktop' }));
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

async function fetchInstallInfo(): Promise<InstallInfoPayload> {
  const response = await fetch(`${bridgeUrl}/hermes/install-info`);
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
  if (!/^Hermes-Yachiyo.*\.app$/.test(bundleName)) {
    return { success: false, appBundlePath, error: `拒绝删除非 Hermes-Yachiyo 应用包：${bundleName}` };
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
    spawn('/bin/zsh', ['-lc', script, 'hermes-yachiyo-uninstall', appBundlePath], {
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

function imageMimeTypeForPath(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  if (ext === '.gif') return 'image/gif';
  return 'application/octet-stream';
}

async function readAvatarImageSelection(filePath: string | null): Promise<AvatarImageSelection | null> {
  if (!filePath) return null;
  const stats = await fs.promises.stat(filePath);
  if (!stats.isFile()) throw new Error('请选择图片文件');
  if (stats.size > MAX_AVATAR_IMAGE_BYTES) throw new Error('头像图片不能超过 8 MB');
  const data = await fs.promises.readFile(filePath);
  const mimeType = imageMimeTypeForPath(filePath);
  if (!mimeType.startsWith('image/')) throw new Error('仅支持 PNG、JPG、WEBP 或 GIF 图片');
  return {
    path: filePath,
    file_name: path.basename(filePath),
    data_url: `data:${mimeType};base64,${data.toString('base64')}`,
  };
}

function normalizeTerminalTask(value: unknown): InstallerTerminalTask | null {
  return value === 'mac-prerequisites' || value === 'install-hermes' || value === 'hermes-setup' || value === 'update-hermes' || value === 'update-hermes-backup'
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
): { success: boolean; id?: string; task?: InstallerTerminalTask; title?: string; error?: string } {
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
      event.sender.send('hermes:terminalData', terminalPayload(id, { data }));
    }
  });
  pty.onExit(({ exitCode, signal }) => {
    terminalSessions.delete(id);
    if (!event.sender.isDestroyed()) {
      event.sender.send('hermes:terminalExit', terminalPayload(id, { exitCode, signal, task }));
    }
  });
  event.sender.once('destroyed', () => cleanupTerminalsForOwner(event.sender.id));
  return { success: true, id, task, title };
}

ipcMain.handle('hermes:getBridgeUrl', () => bridgeUrl);
ipcMain.handle('hermes:quit', () => {
  app.quit();
});
ipcMain.handle('hermes:restartApp', () => {
  app.relaunch();
  app.quit();
});
ipcMain.handle('hermes:removeAppBundleAndQuit', () => removeCurrentAppBundleAndQuit());
ipcMain.handle('hermes:getAppUpdateInfo', () => appUpdateInfo());
ipcMain.handle('hermes:checkAppUpdate', () => checkAppUpdate());
ipcMain.handle('hermes:downloadAppUpdate', (event) => downloadAppUpdate((progress) => {
  if (!event.sender.isDestroyed()) event.sender.send('hermes:appUpdateDownloadProgress', progress);
}));
ipcMain.handle('hermes:installAppUpdate', (_event, dmgPath: unknown) => installDownloadedAppUpdate(dmgPath));
ipcMain.handle('hermes:restartBackend', (_event, options: unknown) => {
  const targetBridgeUrl = isRecord(options) ? options.bridgeUrl : undefined;
  return restartBackendProcess(targetBridgeUrl);
});
ipcMain.handle('hermes:copyText', (_event, value: unknown) => {
  clipboard.writeText(typeof value === 'string' ? value : '');
});
ipcMain.handle('hermes:chooseAvatarImage', async (event) => {
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
ipcMain.handle('hermes:openDesktopMode', (_event, mode: unknown) => openConfiguredDesktopMode(normalizePreferredDisplayMode(mode)));
ipcMain.handle('hermes:moveLauncherWindow', moveLauncherWindow);
ipcMain.handle('hermes:getLauncherPointerState', (_event, mode: unknown) => launcherPointerState(mode));
ipcMain.handle('hermes:terminalStart', startInstallerTerminal);
ipcMain.handle('hermes:terminalWrite', (_event, rawId: unknown, rawData: unknown) => {
  const id = typeof rawId === 'string' ? rawId : '';
  const session = terminalSessions.get(id);
  if (!session || session.sender.id !== _event.sender.id) return false;
  session.pty.write(typeof rawData === 'string' ? rawData : '');
  return true;
});
ipcMain.handle('hermes:terminalResize', (_event, rawId: unknown, rawCols: unknown, rawRows: unknown) => {
  const id = typeof rawId === 'string' ? rawId : '';
  const session = terminalSessions.get(id);
  if (!session || session.sender.id !== _event.sender.id) return false;
  session.pty.resize(safeTerminalSize(rawCols, session.pty.cols, 40, 240), safeTerminalSize(rawRows, session.pty.rows, 10, 80));
  return true;
});
ipcMain.handle('hermes:terminalKill', (_event, rawId: unknown) => {
  const id = typeof rawId === 'string' ? rawId : '';
  const session = terminalSessions.get(id);
  if (!session || session.sender.id !== _event.sender.id) return false;
  cleanupTerminalSession(id);
  return true;
});
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
    { label: '退出 Hermes-Yachiyo', click: () => app.quit() },
  ]);
  menu.popup({ window: targetWindow });
});

app.whenReady().then(() => {
  showMacDockIcon();
  void (async () => {
    await prepareBridgeUrlForPackagedBackend();
    startBackend();
    createMainWindow({ view: 'main' }, lastUiSettings, { focusOnReady: false });
    const installInfo = await waitForInstallInfo();
    lastInstallReady = installReady(installInfo);
    if (!lastInstallReady) {
      showMainWindow({ view: 'installer' }, lastUiSettings, { focusOnReady: false });
      return;
    }
    hasEnteredMainExperience = true;
    const settings = await waitForUiSettings();
    if (settings) lastUiSettings = settings;
    configureTray(settings);
    showMainWindow({}, settings, { focusOnReady: false });
    await openConfiguredDesktopMode(undefined, settings);
    if (settings?.window_mode?.open_chat_on_start) showChatWindow();
  })();

  app.on('activate', showMainWindowFromAppActivation);
});

app.on('before-quit', () => {
  cleanupAllTerminalSessions();
  stopBackend();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
