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
const FOLDER_ID = 'agent-studio-skill-folders-ui-smoke-folder';
const CREATED_FOLDER_NAME = 'Skill Folder Smoke Draft';
const RENAMED_FOLDER_NAME = 'Skill Folder Smoke Renamed';
const now = new Date().toISOString();

let folders = [];
let createFolderRequest = null;
let updateFolderRequest = null;
let deletedFolderPath = '';

function log(message) {
  process.stdout.write(`[agent-studio-skill-folders-ui-smoke] ${message}\n`);
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

function readJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('error', reject);
    request.on('end', () => {
      const body = Buffer.concat(chunks).toString('utf8').trim();
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
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

function folderSpec(name = CREATED_FOLDER_NAME) {
  return {
    folder_id: FOLDER_ID,
    name,
    source_scope: 'all',
    sort_order: 10,
    skill_count: 0,
    installed_count: 0,
    native_count: 0,
    created_at: now,
    updated_at: now,
  };
}

async function startMockBridge() {
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, { agents: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills') {
        sendJson(response, 200, { skills: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills/sources') {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skill-folders') {
        sendJson(response, 200, { folders });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/skill-folders') {
        createFolderRequest = await readJson(request);
        const created = folderSpec(createFolderRequest.name);
        folders = [created];
        sendJson(response, 200, created);
        return;
      }
      if (request.method === 'PATCH' && url.pathname === `/ui/skill-folders/${FOLDER_ID}`) {
        updateFolderRequest = await readJson(request);
        const updated = folderSpec(updateFolderRequest.name || RENAMED_FOLDER_NAME);
        folders = [updated];
        sendJson(response, 200, updated);
        return;
      }
      if (request.method === 'DELETE' && url.pathname === `/ui/skill-folders/${FOLDER_ID}`) {
        deletedFolderPath = `${url.pathname}${url.search}`;
        folders = [];
        sendJson(response, 200, { ok: true, deleted_skill_count: 0 });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, { ok: true, profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, { runnables: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [] });
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
}, 30000);
function waitFor(win, predicate, label, timeout = 15000) {
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
              folders: Array.from(document.querySelectorAll('[data-testid="skill-folder-row"]')).map((node) => ({
                id: node.getAttribute('data-folder-id'),
                name: node.getAttribute('data-folder-name'),
                text: node.textContent,
              })),
              skillFolderPage: document.querySelector('[data-testid="skill-folder-page"]')?.textContent || '',
              skillLibrary: document.querySelector('[data-testid="skill-library"]')?.textContent || '',
              confirm: document.querySelector('[data-testid="confirm-dialog"]')?.textContent || '',
              bodyText: document.body.textContent.slice(-1600),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/skill-groups');
  console.log('[electron-smoke] skill folder page loaded');
  await waitFor(win, () => (
    document.querySelector('[data-testid="skill-folder-page"]')
    && document.querySelector('[data-testid="skill-folder-name-input"]')
    && document.querySelector('[data-testid="skill-folder-list"]')
  ), 'skill folder page');
  await win.webContents.executeJavaScript(\`
  (() => {
    const input = document.querySelector('[data-testid="skill-folder-name-input"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(CREATED_FOLDER_NAME)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('[data-testid="skill-folder-create"]').click();
  })();
  \`, true);
  await waitFor(win, () => {
    const row = document.querySelector('[data-testid="skill-folder-row"][data-folder-id="${FOLDER_ID}"]');
    return row && row.getAttribute('data-folder-name') === ${JSON.stringify(CREATED_FOLDER_NAME)};
  }, 'created folder row');
  console.log('[electron-smoke] folder created');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="skill-folder-row"][data-folder-id="${FOLDER_ID}"] [data-testid="skill-folder-rename"]').click();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="skill-folder-edit-name-input"]')?.value === ${JSON.stringify(CREATED_FOLDER_NAME)}, 'rename input');
  await win.webContents.executeJavaScript(\`
  (() => {
    const input = document.querySelector('[data-testid="skill-folder-edit-name-input"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(RENAMED_FOLDER_NAME)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('[data-testid="skill-folder-save-rename"]').click();
  })();
  \`, true);
  await waitFor(win, () => {
    const row = document.querySelector('[data-testid="skill-folder-row"][data-folder-id="${FOLDER_ID}"]');
    return row && row.getAttribute('data-folder-name') === ${JSON.stringify(RENAMED_FOLDER_NAME)};
  }, 'renamed folder row');
  console.log('[electron-smoke] folder renamed');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="skill-folder-row"][data-folder-id="${FOLDER_ID}"] [data-testid="skill-folder-open"]').click();
  \`, true);
  await waitFor(win, () => (
    window.location.hash === '#/agents/skills'
    && document.querySelector('[data-testid="skill-library"]')
    && document.querySelector('[data-testid="skill-import-folder-select"]')?.value === ${JSON.stringify(FOLDER_ID)}
    && document.querySelector('[data-testid="skill-library-folder-filter"]')?.value === ${JSON.stringify(FOLDER_ID)}
  ), 'opened skill library folder filter');
  console.log('[electron-smoke] folder opened in skill library');
  win.webContents.reload();
  await waitFor(win, () => (
    window.location.hash === '#/agents/skills'
    && document.querySelector('[data-testid="skill-library"]')
  ), 'skill library after reload');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="agent-studio-tab-skill-groups"]').click();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="skill-folder-row"][data-folder-id="${FOLDER_ID}"]')?.getAttribute('data-folder-name') === ${JSON.stringify(RENAMED_FOLDER_NAME)}, 'folder row after reload');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="skill-folder-row"][data-folder-id="${FOLDER_ID}"] [data-testid="skill-folder-delete"]').click();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="confirm-dialog"]')?.textContent.includes('删除文件夹'), 'delete confirm dialog');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="confirm-action"]').click();
  \`, true);
  await waitFor(win, () => document.querySelectorAll('[data-testid="skill-folder-row"]').length === 0, 'folder deleted');
  console.log('[electron-smoke] folder deleted');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-studio-skill-folders-smoke-'));
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
    }, 45_000);
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
  if (!createFolderRequest || createFolderRequest.name !== CREATED_FOLDER_NAME) {
    throw new Error(`unexpected create folder request: ${JSON.stringify(createFolderRequest)}`);
  }
  if (!updateFolderRequest || updateFolderRequest.name !== RENAMED_FOLDER_NAME) {
    throw new Error(`unexpected update folder request: ${JSON.stringify(updateFolderRequest)}`);
  }
  if (deletedFolderPath !== `/ui/skill-folders/${FOLDER_ID}`) {
    throw new Error(`unexpected deleted folder path: ${deletedFolderPath || 'missing delete'}`);
  }
  if (folders.length !== 0) {
    throw new Error(`expected folders to be empty after delete, got ${JSON.stringify(folders)}`);
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
