#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FRONTEND = path.join(ROOT, 'apps', 'frontend');
const ELECTRON = path.join(FRONTEND, 'node_modules', '.bin', process.platform === 'win32' ? 'electron.cmd' : 'electron');
const VITE = path.join(FRONTEND, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite');
const ARCHIVE_PATH = '/tmp/oha-live2d-settings-smoke.zip';
const MODEL_PATH = '/tmp/oha-live2d-settings-smoke-model';
const IMPORTED_MODEL_PATH = '/tmp/oha-live2d-imported/model.model3.json';

const bridgeState = {
  currentModelPath: '',
  importedArchives: [],
  preparedModelPaths: [],
  settingsPayloads: [],
};

function log(message) {
  process.stdout.write(`[live2d-settings-ui-smoke] ${message}\n`);
}

function live2dConfig() {
  const modelPath = bridgeState.currentModelPath;
  const displayPath = modelPath || '未配置';
  return {
    scale: 1,
    model_name: 'Smoke Live2D',
    model_path: modelPath,
    model_path_display: displayPath,
    model_state: modelPath ? 'path_valid' : 'not_configured',
    width: 420,
    height: 620,
    position_anchor: 'right_bottom',
    position_x: 24,
    position_y: 32,
    window_on_top: true,
    show_on_all_spaces: true,
    show_reply_bubble: true,
    default_open_behavior: 'chat_input',
    click_action: 'toggle_reply',
    enable_quick_input: true,
    auto_open_chat_window: false,
    mouse_follow_enabled: true,
    idle_motion_group: 'Idle',
    enable_expressions: true,
    enable_physics: true,
    render_quality_preset: 'balanced',
    render_fps: 24,
    render_resolution: 1.25,
    hit_region_precision: 'medium',
    expression_keywords: { smile: '开心,高兴' },
    proactive_enabled: true,
    proactive_desktop_watch_enabled: true,
    proactive_interval_seconds: 600,
    proactive_trigger_probability: 0.5,
    resource: {
      state: modelPath ? 'path_valid' : 'not_configured',
      source_label: modelPath ? 'Smoke model path' : 'No model path',
      configured_path_display: displayPath,
      effective_model_path_display: displayPath,
      default_assets_root: '/tmp/oha-live2d-assets',
      default_assets_root_display: '~/Library/Application Support/Oha-Yachiyo/live2d',
      releases_url: 'https://example.test/oha-yachiyo/live2d',
      help_text: 'Live2D settings smoke resource help.',
    },
    summary: {
      renderer_entry: modelPath,
      renderer_entry_display: displayPath,
      expressions: [{ name: 'smile', file: 'smile.exp3.json' }],
      motion_groups: { Idle: [{ file: 'idle.motion3.json' }] },
    },
  };
}

function modeSettingsPayload() {
  return {
    mode: {
      id: 'live2d',
      name: 'Live2D',
      icon: 'live2d',
      settings_title: 'Live2D 设置',
      settings_description: 'Live2D settings smoke page',
    },
    settings: {
      summary: bridgeState.currentModelPath ? 'Live2D resource smoke ready' : 'Live2D resource missing',
      config: live2dConfig(),
    },
  };
}

function readRequestJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      if (!chunks.length) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (error) {
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function pickPort() {
  return new Promise((resolve, reject) => {
    const server = http.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === 'string') reject(new Error('could not allocate local port'));
        else resolve(address.port);
      });
    });
  });
}

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'content-type,x-oha-yachiyo-bridge-token',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS,PATCH,DELETE',
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

async function startMockBridge() {
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/modes/live2d/settings') {
        sendJson(response, 200, modeSettingsPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/live2d/archive/import') {
        const body = await readRequestJson(request);
        bridgeState.importedArchives.push(body);
        sendJson(response, 200, {
          ok: true,
          message: 'Live2D ZIP imported by UI smoke',
          model_path_display: IMPORTED_MODEL_PATH,
          draft_changes: { 'live2d_mode.model_path': IMPORTED_MODEL_PATH },
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/live2d/model-path/prepare') {
        const body = await readRequestJson(request);
        bridgeState.preparedModelPaths.push(body);
        sendJson(response, 200, {
          ok: true,
          message: 'Live2D model path prepared by UI smoke',
          model_path_display: body.path || MODEL_PATH,
          draft_changes: { 'live2d_mode.model_path': body.path || MODEL_PATH },
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/settings') {
        const body = await readRequestJson(request);
        bridgeState.settingsPayloads.push(body);
        const modelPath = body?.changes?.['live2d_mode.model_path'];
        if (typeof modelPath === 'string') bridgeState.currentModelPath = modelPath;
        sendJson(response, 200, {
          ok: true,
          effects: { hint: 'Live2D settings smoke saved' },
          target_display_mode: body?.changes?.display_mode || 'live2d',
        });
        return;
      }
      sendJson(response, 404, { ok: false, error: `not found: ${request.method} ${url.pathname}` });
    } catch (error) {
      sendJson(response, 500, { ok: false, error: error instanceof Error ? error.message : String(error) });
    }
  });
  const port = await pickPort();
  await new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  return { server, url: `http://127.0.0.1:${port}` };
}

function waitForHttp(url, timeoutMs = 15_000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      http.get(url, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
        } else if (Date.now() - started > timeoutMs) {
          reject(new Error(`timed out waiting for ${url}`));
        } else {
          setTimeout(attempt, 250);
        }
      }).on('error', (error) => {
        if (Date.now() - started > timeoutMs) reject(error);
        else setTimeout(attempt, 250);
      });
    };
    attempt();
  });
}

function startVite(port) {
  const child = spawn(VITE, ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: FRONTEND,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, FORCE_COLOR: '0' },
  });
  child.stdout.on('data', (chunk) => process.stdout.write(chunk));
  child.stderr.on('data', (chunk) => process.stderr.write(chunk));
  return child;
}

function killProcess(child) {
  if (!child || child.killed) return;
  child.kill('SIGTERM');
}

function runElectronSmoke(devUrl, bridgeUrl) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-live2d-settings-ui-smoke-'));
  const preloadPath = path.join(tempDir, 'preload.cjs');
  fs.writeFileSync(preloadPath, `
const { contextBridge } = require('electron');
let archiveCalls = 0;
let modelDirectoryCalls = 0;
contextBridge.exposeInMainWorld('ohaDesktop', {
  chooseLive2DArchive: async () => {
    archiveCalls += 1;
    return ${JSON.stringify(ARCHIVE_PATH)};
  },
  chooseLive2DModelDirectory: async () => {
    modelDirectoryCalls += 1;
    return ${JSON.stringify(MODEL_PATH)};
  },
  __live2dPickerCalls: () => ({ archiveCalls, modelDirectoryCalls }),
});
`, 'utf8');
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const preloadPath = ${JSON.stringify(preloadPath)};
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 35000);
function waitFor(win, predicate, label, timeout = 18000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const result = await win.webContents.executeJavaScript('(' + predicate.toString() + ')()', true);
        if (result) {
          resolve(result);
          return;
        }
      } catch {}
      if (Date.now() - started > timeout) {
        let debug = '';
        try {
          debug = await win.webContents.executeJavaScript(\`
            JSON.stringify({
              hash: window.location.hash,
              status: document.querySelector('[data-testid="mode-settings-status"]')?.textContent || '',
              resource: document.querySelector('[data-testid="live2d-resource-settings"]')?.outerHTML || '',
              modelPath: document.querySelector('[data-testid="live2d-manual-model-path"]')?.value || '',
              archivePath: document.querySelector('[data-testid="live2d-manual-archive-path"]')?.value || '',
              configured: document.querySelector('[data-testid="live2d-configured-path"]')?.textContent || '',
              bodyText: document.body.textContent.slice(-1800),
            })
          \`, true);
        } catch {}
        reject(new Error('timeout waiting for ' + label + (debug ? ': ' + debug : '')));
      } else {
        setTimeout(tick, 120);
      }
    };
    tick();
  });
}
async function main() {
  await app.whenReady();
  console.log('[electron-smoke] app ready');
  const win = new BrowserWindow({
    width: 1280,
    height: 900,
    show: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
      preload: preloadPath,
    },
  });
  win.webContents.on('console-message', (_event, level, message) => {
    if (level >= 2) console.error('[renderer]', message);
  });
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/settings/live2d');
  await waitFor(win, () => {
    const resource = document.querySelector('[data-testid="live2d-resource-settings"]');
    return resource && !document.querySelector('[data-testid="live2d-archive-import"]')?.disabled;
  }, 'live2d resource controls');
  console.log('[electron-smoke] live2d resource controls loaded');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"live2d-archive-import\\"]').click()", true);
  await waitFor(win, () => {
    const status = document.querySelector('[data-testid="mode-settings-status"]');
    const save = document.querySelector('[data-testid="mode-settings-save"]');
    return status?.textContent.includes('Live2D ZIP imported by UI smoke')
      && !save?.disabled;
  }, 'live2d archive imported');
  const archivePickerCalls = await win.webContents.executeJavaScript('window.ohaDesktop.__live2dPickerCalls().archiveCalls', true);
  if (archivePickerCalls !== 1) {
    throw new Error('expected Live2D archive picker to be called once, got ' + archivePickerCalls);
  }
  console.log('[electron-smoke] live2d archive import verified');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"live2d-model-path-prepare\\"]').click()", true);
  await waitFor(win, () => {
    const status = document.querySelector('[data-testid="mode-settings-status"]');
    const save = document.querySelector('[data-testid="mode-settings-save"]');
    return status?.textContent.includes('Live2D model path prepared by UI smoke')
      && !save?.disabled;
  }, 'live2d model path prepared');
  const modelPickerCalls = await win.webContents.executeJavaScript('window.ohaDesktop.__live2dPickerCalls().modelDirectoryCalls', true);
  if (modelPickerCalls !== 1) {
    throw new Error('expected Live2D model directory picker to be called once, got ' + modelPickerCalls);
  }
  console.log('[electron-smoke] live2d model path verified');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"mode-settings-save\\"]').click()", true);
  await waitFor(win, () => {
    const status = document.querySelector('[data-testid="mode-settings-status"]');
    const configured = document.querySelector('[data-testid="live2d-configured-path"]');
    const effective = document.querySelector('[data-testid="live2d-effective-path"]');
    const state = document.querySelector('[data-testid="live2d-model-state"]');
    return status?.textContent.includes('已保存')
      && status?.textContent.includes('Live2D settings smoke saved')
      && configured?.textContent.includes(${JSON.stringify(MODEL_PATH)})
      && effective?.textContent.includes(${JSON.stringify(MODEL_PATH)})
      && state?.textContent.includes('资源已就绪');
  }, 'live2d settings saved');
  console.log('[electron-smoke] live2d settings save verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const mainPath = path.join(tempDir, 'main.cjs');
  fs.writeFileSync(mainPath, script, 'utf8');
  return new Promise((resolve, reject) => {
    const child = spawn(ELECTRON, [mainPath], {
      cwd: FRONTEND,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, ELECTRON_ENABLE_LOGGING: '1' },
    });
    const timeout = setTimeout(() => {
      child.kill('SIGTERM');
      reject(new Error('electron smoke child timed out'));
    }, 50_000);
    child.stdout.on('data', (chunk) => process.stdout.write(chunk));
    child.stderr.on('data', (chunk) => process.stderr.write(chunk));
    child.on('error', (error) => {
      clearTimeout(timeout);
      fs.rmSync(tempDir, { recursive: true, force: true });
      reject(error);
    });
    child.on('exit', (code, signal) => {
      clearTimeout(timeout);
      fs.rmSync(tempDir, { recursive: true, force: true });
      if (code === 0) resolve();
      else reject(new Error(`electron smoke failed with code=${code} signal=${signal || ''}`));
    });
  });
}

function assertMockBridgeContract() {
  if (!bridgeState.importedArchives.some((payload) => payload.path === ARCHIVE_PATH)) {
    throw new Error(`Live2D archive import did not use desktop picker ZIP path: ${JSON.stringify(bridgeState.importedArchives)}`);
  }
  if (!bridgeState.preparedModelPaths.some((payload) => payload.path === MODEL_PATH)) {
    throw new Error(`Live2D model prepare did not use desktop picker model path: ${JSON.stringify(bridgeState.preparedModelPaths)}`);
  }
  const settingsPayload = bridgeState.settingsPayloads.at(-1);
  if (!settingsPayload) {
    throw new Error('Live2D settings were not saved');
  }
  const changes = settingsPayload.changes || {};
  if (changes['live2d_mode.model_path'] !== MODEL_PATH) {
    throw new Error(`Live2D save did not include prepared model path: ${JSON.stringify(changes)}`);
  }
  if (changes.display_mode !== 'live2d') {
    throw new Error(`Live2D save did not request display_mode=live2d: ${JSON.stringify(changes)}`);
  }
}

async function main() {
  const bridge = await startMockBridge();
  const vitePort = await pickPort();
  const vite = startVite(vitePort);
  try {
    const devUrl = `http://127.0.0.1:${vitePort}`;
    await waitForHttp(devUrl);
    await runElectronSmoke(devUrl, bridge.url);
    assertMockBridgeContract();
    log('passed');
  } finally {
    killProcess(vite);
    await new Promise((resolve) => bridge.server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
