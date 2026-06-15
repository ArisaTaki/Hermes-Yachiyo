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
const AGENT_ID = 'workflow-management-ui-smoke-agent';
const WORKFLOW_A_ID = 'workflow_management_ui_smoke_a';
const WORKFLOW_B_ID = 'workflow_management_ui_smoke_b';
const now = new Date().toISOString();

let workflows = [
  workflowSpec(WORKFLOW_A_ID, 'Workflow Management Smoke A'),
  workflowSpec(WORKFLOW_B_ID, 'Workflow Management Smoke B'),
];
let deletedWorkflowIds = [];

const agent = {
  agent_id: AGENT_ID,
  name: 'Workflow Management Smoke Agent',
  model_mode: 'follow_main',
  execution_backend: 'native_profile',
  model_config: {},
  enabled: true,
  editable: true,
  deletable: true,
};

function workflowSpec(workflowId, name) {
  return {
    workflow_id: workflowId,
    name,
    description: `${name} definition`,
    nodes: [
      { id: 'start', type: 'default', position: { x: 0, y: 0 }, data: { kind: 'start', label: 'Start' } },
      {
        id: `agent-${workflowId}`,
        type: 'default',
        position: { x: 240, y: 0 },
        data: { kind: 'agent', label: name, agent_id: AGENT_ID, task: `Run ${name}` },
      },
    ],
    edges: [{ id: `edge-start-agent-${workflowId}`, source: 'start', target: `agent-${workflowId}` }],
    enabled: true,
    created_at: now,
    updated_at: now,
  };
}

function log(message) {
  process.stdout.write(`[workflow-management-ui-smoke] ${message}\n`);
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
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, { agents: [agent] });
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
        sendJson(response, 200, { folders: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, {
          ok: true,
          profiles: [{
            profile_id: 'profile-workflow-management-smoke',
            name: 'Workflow Management Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: 'profile-workflow-management-smoke' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows });
        return;
      }
      if (
        request.method === 'DELETE'
        && (
          url.pathname.startsWith('/yachiyo/studio/workflows/')
          || url.pathname.startsWith('/ui/workflows/')
        )
      ) {
        const prefix = url.pathname.startsWith('/yachiyo/studio/workflows/')
          ? '/yachiyo/studio/workflows/'
          : '/ui/workflows/';
        const workflowId = decodeURIComponent(url.pathname.slice(prefix.length));
        if (!workflows.some((workflow) => workflow.workflow_id === workflowId)) {
          sendJson(response, 404, { ok: false, error: `workflow not found: ${workflowId}` });
          return;
        }
        deletedWorkflowIds.push(workflowId);
        workflows = workflows.filter((workflow) => workflow.workflow_id !== workflowId);
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [
            { id: AGENT_ID, name: agent.name, kind: 'agent', enabled: true, output_contract: 'report' },
            ...workflows.map((workflow) => ({
              id: workflow.workflow_id,
              name: workflow.name,
              kind: 'workflow',
              enabled: workflow.enabled,
              output_contract: 'workflow',
            })),
          ],
        });
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
  const script = String.raw`
const { app, BrowserWindow } = require('electron');
const devUrl = process.env.OHA_YACHIYO_SMOKE_DEV_URL;
const bridgeUrl = process.env.OHA_YACHIYO_SMOKE_BRIDGE_URL;
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
          debug = await win.webContents.executeJavaScript(
            "JSON.stringify({" +
              "hash: window.location.hash," +
              "items: Array.from(document.querySelectorAll('[data-testid=\"workflow-list-item\"]')).map((node) => node.textContent)," +
              "bulk: document.querySelector('[data-testid=\"workflow-bulk-actions\"]')?.textContent || ''," +
              "dialog: document.querySelector('[data-testid=\"confirm-dialog\"]')?.textContent || ''," +
              "error: document.querySelector('.agent-error')?.textContent || ''," +
              "bodyText: document.body.textContent.slice(-1600)" +
            "})",
            true
          );
        } catch {}
        reject(new Error('timeout waiting for ' + label + (debug ? ': ' + debug : '')));
      } else {
        setTimeout(tick, 120);
      }
    };
    tick();
  });
}

async function runInPage(win, fn) {
  return win.webContents.executeJavaScript('(' + fn.toString() + ')()', true);
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/workflows');
  console.log('[electron-smoke] workflow studio loaded');
  await waitFor(win, () => {
    const items = Array.from(document.querySelectorAll('[data-testid="workflow-list-item"]'));
    return Boolean(document.querySelector('[data-testid="workflow-studio"]'))
      && Boolean(document.querySelector('[data-testid="workflow-list"]'))
      && items.length === 2
      && items.some((node) => node.textContent.includes('Workflow Management Smoke A'))
      && items.some((node) => node.textContent.includes('Workflow Management Smoke B'));
  }, 'initial workflow list');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-list-manage"]').click();
  });
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="workflow-bulk-actions"]');
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="workflow-list-checkbox"]'));
    return Boolean(bulk) && checkboxes.length === 2 && checkboxes.every((input) => !input.disabled);
  }, 'workflow management mode');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-select-all"]').click();
  });
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="workflow-bulk-actions"]');
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="workflow-list-checkbox"]'));
    const deleteSelected = document.querySelector('[data-testid="workflow-delete-selected"]');
    return Boolean(bulk?.textContent.includes('已选择 2 / 2'))
      && checkboxes.length === 2
      && checkboxes.every((input) => input.checked)
      && Boolean(deleteSelected)
      && !deleteSelected.disabled;
  }, 'workflow select all');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-clear-selection"]').click();
  });
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="workflow-bulk-actions"]');
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="workflow-list-checkbox"]'));
    const deleteSelected = document.querySelector('[data-testid="workflow-delete-selected"]');
    return Boolean(bulk?.textContent.includes('2 workflows'))
      && checkboxes.length === 2
      && checkboxes.every((input) => !input.checked)
      && Boolean(deleteSelected)
      && deleteSelected.disabled;
  }, 'workflow clear selection');
  console.log('[electron-smoke] workflow selection controls verified');
  await runInPage(win, () => {
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="workflow-list-checkbox"]'));
    checkboxes[0].click();
  });
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="workflow-bulk-actions"]');
    const deleteSelected = document.querySelector('[data-testid="workflow-delete-selected"]');
    return Boolean(bulk?.textContent.includes('1 / 2')) && Boolean(deleteSelected) && !deleteSelected.disabled;
  }, 'selected workflow for bulk delete');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-delete-selected"]').click();
  });
  await waitFor(win, () => {
    return document.querySelector('[data-testid="confirm-dialog"]')?.textContent.includes('删除 1 个 Workflow');
  }, 'bulk delete confirmation');
  await runInPage(win, () => {
    document.querySelector('[data-testid="confirm-action"]').click();
  });
  await waitFor(win, () => {
    const items = Array.from(document.querySelectorAll('[data-testid="workflow-list-item"]'));
    const bulk = document.querySelector('[data-testid="workflow-bulk-actions"]');
    return items.length === 1
      && items[0].textContent.includes('Workflow Management Smoke B')
      && !items[0].textContent.includes('Workflow Management Smoke A')
      && Boolean(bulk?.textContent.includes('1 workflows'));
  }, 'bulk delete refreshed list');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-finish-management"]').click();
  });
  await waitFor(win, () => {
    return !document.querySelector('[data-testid="workflow-bulk-actions"]');
  }, 'workflow management finished');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-list-open"]').click();
  });
  await waitFor(win, () => {
    const editor = document.querySelector('[data-testid="workflow-editor"]');
    const nameInput = document.querySelector('[data-testid="workflow-name-input"]');
    const deleteButton = document.querySelector('[data-testid="workflow-delete"]');
    return Boolean(editor)
      && nameInput?.value === 'Workflow Management Smoke B'
      && Boolean(deleteButton)
      && !deleteButton.disabled;
  }, 'remaining workflow opened');
  await runInPage(win, () => {
    document.querySelector('[data-testid="workflow-delete"]').click();
  });
  await waitFor(win, () => {
    return document.querySelector('[data-testid="confirm-dialog"]')?.textContent.includes('删除「Workflow Management Smoke B」');
  }, 'single delete confirmation');
  await runInPage(win, () => {
    document.querySelector('[data-testid="confirm-action"]').click();
  });
  await waitFor(win, () => {
    return document.querySelectorAll('[data-testid="workflow-list-item"]').length === 0
      && !document.querySelector('[data-testid="workflow-delete"]')
      && document.querySelector('[data-testid="workflow-editor"]');
  }, 'single delete refreshed list');
  console.log('[electron-smoke] workflow management delete paths rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-workflow-management-smoke-'));
  const mainPath = path.join(tempDir, 'main.cjs');
  fs.writeFileSync(mainPath, script, 'utf8');
  return new Promise((resolve, reject) => {
    const child = spawn(ELECTRON, [mainPath], {
      cwd: FRONTEND,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        ELECTRON_ENABLE_LOGGING: '1',
        OHA_YACHIYO_SMOKE_DEV_URL: devUrl,
        OHA_YACHIYO_SMOKE_BRIDGE_URL: bridgeUrl,
      },
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
  const expected = [WORKFLOW_A_ID, WORKFLOW_B_ID];
  if (JSON.stringify(deletedWorkflowIds) !== JSON.stringify(expected)) {
    throw new Error(`unexpected deleted workflow ids: ${deletedWorkflowIds.join(',')}`);
  }
  if (workflows.length !== 0) {
    throw new Error(`expected all workflows to be deleted, saw ${workflows.length}`);
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
