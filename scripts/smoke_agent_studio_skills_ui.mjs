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
const SKILL_ID = 'agent-studio-skills-ui-smoke-skill';
const FOLDER_A_ID = 'agent-studio-skills-smoke-folder-a';
const FOLDER_B_ID = 'agent-studio-skills-smoke-folder-b';
const INSTALL_COMMAND = 'owner/repo --skill agent-studio-smoke';
const now = new Date().toISOString();

let skills = [];
let syncRequestCount = 0;
let installSkillRequest = null;
const updateSkillRequests = [];
let deletedSkillId = '';

const folders = [
  {
    folder_id: FOLDER_A_ID,
    name: 'Smoke Intake',
    source_scope: 'all',
    skill_count: 0,
    installed_count: 0,
    native_count: 0,
    created_at: now,
    updated_at: now,
  },
  {
    folder_id: FOLDER_B_ID,
    name: 'Smoke Verified',
    source_scope: 'all',
    skill_count: 0,
    installed_count: 0,
    native_count: 0,
    created_at: now,
    updated_at: now,
  },
];

function log(message) {
  process.stdout.write(`[agent-studio-skills-ui-smoke] ${message}\n`);
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

function installedSkillSpec(request = {}) {
  const folderId = request.folder_id || '';
  const folder = folders.find((item) => item.folder_id === folderId);
  return {
    skill_id: SKILL_ID,
    name: 'Installed Skill UI Smoke',
    description: 'Installed through Agent Studio Skill Library Electron smoke',
    source_path: INSTALL_COMMAND,
    local_path: '/tmp/oha-yachiyo/skills/agent-studio-smoke',
    folder_id: folderId,
    folder_name: folder?.name || '',
    source_type: 'installed',
    source_ref: INSTALL_COMMAND,
    content_hash: 'skill-ui-smoke-hash',
    last_synced_at: now,
    sync_status: 'synced',
    content_summary: 'Skill Library smoke summary',
    skill_markdown: '# Installed Skill UI Smoke\\n\\nExercise Skill Library install/update/delete paths.',
    asset_paths: [],
    enabled: request.enabled !== false,
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
        sendJson(response, 200, { skills });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills/sources') {
        sendJson(response, 200, {
          roots: [{
            path: '/tmp/oha-yachiyo/native-skill-library',
            source_type: 'native',
            library: 'native',
            exists: true,
            skill_count: syncRequestCount ? 1 : 0,
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skill-folders') {
        sendJson(response, 200, { folders });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/skills/sync') {
        syncRequestCount += 1;
        sendJson(response, 200, {
          ok: true,
          roots: [{
            path: '/tmp/oha-yachiyo/native-skill-library',
            source_type: 'native',
            library: 'native',
            exists: true,
            skill_count: 1,
          }],
          results: [{
            source: '/tmp/oha-yachiyo/native-skill-library/native-smoke',
            source_type: 'native',
            status: 'updated',
            skill_id: 'native-agent-studio-skills-smoke',
            name: 'Native Smoke Skill',
            message: 'Native Smoke Skill synced',
          }],
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/skills/install') {
        installSkillRequest = await readJson(request);
        const installed = installedSkillSpec({ folder_id: installSkillRequest.folder_id || '' });
        skills = [installed];
        sendJson(response, 200, {
          ok: true,
          installer: 'skills',
          command: ['skills', 'add', installSkillRequest.command],
          returncode: 0,
          stdout: 'installed',
          stderr: '',
          sync: {
            ok: true,
            results: [{
              source: installSkillRequest.command,
              source_type: 'installed',
              status: 'imported',
              skill_id: SKILL_ID,
              name: installed.name,
              message: 'Installed Skill UI Smoke imported',
            }],
          },
        });
        return;
      }
      if (request.method === 'PATCH' && url.pathname === `/ui/skills/${SKILL_ID}`) {
        const update = await readJson(request);
        updateSkillRequests.push(update);
        const current = skills.find((skill) => skill.skill_id === SKILL_ID) || installedSkillSpec(installSkillRequest || {});
        const folderId = Object.prototype.hasOwnProperty.call(update, 'folder_id') ? update.folder_id || '' : current.folder_id || '';
        const folder = folders.find((item) => item.folder_id === folderId);
        const updated = {
          ...current,
          ...update,
          folder_id: folderId,
          folder_name: folder?.name || '',
          updated_at: now,
        };
        skills = [updated];
        sendJson(response, 200, updated);
        return;
      }
      if (request.method === 'DELETE' && url.pathname === `/ui/skills/${SKILL_ID}`) {
        deletedSkillId = SKILL_ID;
        skills = [];
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, { ok: true, profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/workflows') {
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
const skillId = ${JSON.stringify(SKILL_ID)};
const folderA = ${JSON.stringify(FOLDER_A_ID)};
const folderB = ${JSON.stringify(FOLDER_B_ID)};
const installCommand = ${JSON.stringify(INSTALL_COMMAND)};
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
              skills: Array.from(document.querySelectorAll('[data-testid="skill-card"]')).map((node) => ({
                id: node.getAttribute('data-skill-id'),
                enabled: node.getAttribute('data-skill-enabled'),
                folder: node.getAttribute('data-skill-folder-id'),
                text: node.textContent,
              })),
              results: document.querySelector('[data-testid="skill-import-results"]')?.textContent || '',
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
    width: 1360,
    height: 920,
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/skills');
  console.log('[electron-smoke] skill library loaded');
  await waitFor(win, () => (
    document.querySelector('[data-testid="skill-library"]')
    && document.querySelector('[data-testid="skill-install-command-input"]')
    && document.querySelector('[data-testid="skill-native-sync"]')
    && document.querySelector('[data-testid="skill-list"]')
  ), 'skill library');
  await waitFor(win, () => document.querySelectorAll('[data-testid="skill-card"]').length === 0, 'initial empty skill list');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="skill-native-sync"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="skill-import-result"]')?.textContent.includes('Native Smoke Skill')
    && document.querySelector('[data-testid="skill-source-root"]')?.textContent.includes('1 skills')
  ), 'native skill sync result');
  console.log('[electron-smoke] native sync rendered');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const setSelectValue = (element, value) => {
      element.value = value;
      element.dispatchEvent(new Event('change', { bubbles: true }));
    };
    setSelectValue(document.querySelector('[data-testid="skill-import-folder-select"]'), ${JSON.stringify(FOLDER_A_ID)});
    setNativeValue(document.querySelector('[data-testid="skill-install-command-input"]'), ${JSON.stringify(INSTALL_COMMAND)});
    document.querySelector('[data-testid="skill-install-command-submit"]').click();
  })();
  \`, true);
  await waitFor(win, () => {
    const card = document.querySelector('[data-testid="skill-card"]');
    return card
      && card.getAttribute('data-skill-id') === ${JSON.stringify(SKILL_ID)}
      && card.getAttribute('data-skill-enabled') === 'true'
      && card.getAttribute('data-skill-folder-id') === ${JSON.stringify(FOLDER_A_ID)}
      && card.textContent.includes('Installed Skill UI Smoke');
  }, 'installed skill card');
  console.log('[electron-smoke] installed skill rendered');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="skill-card-enabled-toggle"]').click();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="skill-card"]')?.getAttribute('data-skill-enabled') === 'false', 'disabled skill card');
  await win.webContents.executeJavaScript(\`
  (() => {
    const folder = document.querySelector('[data-testid="skill-card-folder-select"]');
    folder.value = ${JSON.stringify(FOLDER_B_ID)};
    folder.dispatchEvent(new Event('change', { bubbles: true }));
  })();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="skill-card"]')?.getAttribute('data-skill-folder-id') === ${JSON.stringify(FOLDER_B_ID)}, 'moved skill folder');
  console.log('[electron-smoke] installed skill updated');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="skill-card-delete"]').click();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="confirm-dialog"]')?.textContent.includes('删除 Skill'), 'delete confirm dialog');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="confirm-action"]').click();
  \`, true);
  await waitFor(win, () => document.querySelectorAll('[data-testid="skill-card"]').length === 0, 'skill deleted');
  console.log('[electron-smoke] installed skill deleted');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-studio-skills-smoke-'));
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
  if (syncRequestCount !== 1) throw new Error(`expected one native skill sync request, got ${syncRequestCount}`);
  if (!installSkillRequest) throw new Error('skill install was not requested');
  if (installSkillRequest.command !== INSTALL_COMMAND) {
    throw new Error(`unexpected install command: ${installSkillRequest.command}`);
  }
  if (installSkillRequest.folder_id !== FOLDER_A_ID) {
    throw new Error(`unexpected install folder: ${installSkillRequest.folder_id}`);
  }
  if (!updateSkillRequests.some((request) => request.enabled === false)) {
    throw new Error('skill enabled=false update was not requested');
  }
  if (!updateSkillRequests.some((request) => request.folder_id === FOLDER_B_ID)) {
    throw new Error('skill folder move update was not requested');
  }
  if (deletedSkillId !== SKILL_ID) throw new Error(`skill was not deleted: ${deletedSkillId || 'missing delete'}`);
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
