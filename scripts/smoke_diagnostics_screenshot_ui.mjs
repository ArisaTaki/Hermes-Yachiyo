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
const SCREENSHOT_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';
const SCREENSHOT_WIDTH = 320;
const SCREENSHOT_HEIGHT = 200;

const bridgeState = {
  screenRequests: 0,
};

function log(message) {
  process.stdout.write(`[diagnostics-screenshot-ui-smoke] ${message}\n`);
}

function dashboardPayload() {
  return {
    bridge: { state: 'running', url: 'http://127.0.0.1:8420' },
    native_agent: {
      ready: true,
      command_exists: true,
      readiness_level: 'ready',
      platform: 'macOS',
      available_tools: ['file', 'terminal'],
      limited_tools: [],
      limited_tool_details: {},
      doctor_issues_count: 0,
    },
    workspace: { initialized: true, path: '~/oha-yachiyo' },
  };
}

function settingsPayload() {
  return {
    tts: { enabled: true, provider: 'gpt-sovits' },
    mode_settings: {
      bubble: { id: 'bubble', title: 'Bubble', config: {} },
      live2d: { id: 'live2d', title: 'Live2D', config: {} },
    },
  };
}

function runtimeStatusPayload() {
  return {
    service: 'oha-yachiyo-bridge',
    version: '0.5.0',
    uptime_seconds: 12,
    native_agent_ready: true,
    task_counts: { pending: 0, running: 0, completed: 1 },
  };
}

function toolsConfigPayload() {
  return {
    ok: true,
    command_exists: true,
    needs_env_refresh: false,
    native_toolsets: [
      { id: 'file', canonical_id: 'file', enabled: true },
      { id: 'terminal', canonical_id: 'terminal', enabled: true },
    ],
    tools: [],
  };
}

function diagnosticCachePayload() {
  return {
    stale: false,
    updated_at: new Date().toISOString(),
    commands: {},
  };
}

function screenshotPayload() {
  return {
    image_base64: SCREENSHOT_BASE64,
    mime_type: 'image/png',
    format: 'png',
    width: SCREENSHOT_WIDTH,
    height: SCREENSHOT_HEIGHT,
    captured_at: new Date().toISOString(),
  };
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
  const server = http.createServer((request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/dashboard') {
        sendJson(response, 200, dashboardPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/settings') {
        sendJson(response, 200, settingsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/status') {
        sendJson(response, 200, runtimeStatusPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/tasks') {
        sendJson(response, 200, { tasks: [], total: 0 });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/native-agent/tools/config') {
        sendJson(response, 200, toolsConfigPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/native-agent/diagnostics/cache') {
        sendJson(response, 200, diagnosticCachePayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/screen/current') {
        bridgeState.screenRequests += 1;
        sendJson(response, 200, screenshotPayload());
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
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
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
              status: document.querySelector('[data-testid="diagnostics-status"]')?.textContent || '',
              button: document.querySelector('[data-testid="diagnostics-screen-probe"]')?.outerHTML || '',
              summary: document.querySelector('[data-testid="diagnostics-screen-probe-summary"]')?.textContent || '',
              card: document.querySelector('[data-testid="diagnostics-screen-probe-card"]')?.outerHTML || '',
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
    },
  });
  win.webContents.on('console-message', (_event, level, message) => {
    if (level >= 2) console.error('[renderer]', message);
  });
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/diagnostics');
  await waitFor(win, () => {
    const button = document.querySelector('[data-testid="diagnostics-screen-probe"]');
    const card = document.querySelector('[data-testid="diagnostics-screen-probe-card"]');
    const summary = document.querySelector('[data-testid="diagnostics-screen-probe-summary"]');
    return button && !button.disabled && card && summary?.textContent.includes('未探测');
  }, 'diagnostics screenshot controls');
  console.log('[electron-smoke] diagnostics screenshot controls loaded');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"diagnostics-screen-probe\\"]').click()", true);
  await waitFor(win, () => {
    const status = document.querySelector('[data-testid="diagnostics-status"]');
    const summary = document.querySelector('[data-testid="diagnostics-screen-probe-summary"]');
    const image = document.querySelector('[data-testid="diagnostics-screen-probe-image"]');
    return status?.textContent.includes(${JSON.stringify(`已获取屏幕截图摘要：${SCREENSHOT_WIDTH}×${SCREENSHOT_HEIGHT}`)})
      && summary?.textContent.includes(${JSON.stringify(`${SCREENSHOT_WIDTH}×${SCREENSHOT_HEIGHT} · png`)})
      && image?.getAttribute('src')?.startsWith('data:image/png;base64,')
      && image.complete
      && image.naturalWidth > 0;
  }, 'diagnostics screenshot preview');
  console.log('[electron-smoke] diagnostics screenshot preview verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-diagnostics-screenshot-ui-smoke-'));
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
  if (bridgeState.screenRequests !== 1) {
    throw new Error(`expected exactly one /screen/current request, got ${bridgeState.screenRequests}`);
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
