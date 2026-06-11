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
const RUN_ID = 'agent_run_detail_ui_smoke';
const RUN_GROUP_ID = 'run_group_detail_ui_smoke';
const ARTIFACT_PATH = 'summary.md';
const ARTIFACT_CONTENT = '# Run Detail UI Smoke\n\nArtifact preview loaded from mock Bridge.';
const now = new Date().toISOString();

const run = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'agent',
  task_id: 'task-run-detail-ui-smoke',
  session_id: 'session-run-detail-ui-smoke',
  task_run_link_run_status: 'completed',
  task_run_link_last_event_sequence: 201,
  kind: 'agent_run',
  runnable_id: 'agent-run-detail-smoke',
  runnable_name: 'Run Detail Smoke Agent',
  status: 'completed',
  user_goal: 'Inspect Native RunEvent replay from Agent Studio smoke',
  result: 'Run Detail UI smoke completed through replay facts',
  timeline: [],
  artifacts: [{
    path: ARTIFACT_PATH,
    kind: 'markdown',
    source_run_id: RUN_ID,
    source_runnable_name: 'Run Detail Smoke Agent',
  }],
  created_at: now,
  updated_at: now,
  agent_run_id: RUN_ID,
};

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Run Detail UI Smoke',
  source: 'agent',
  status: 'completed',
  summary: 'One completed Agent Run',
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

const runEvents = [
  {
    event_id: 'event-run-detail-smoke-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'agent.run.started',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { goal: run.user_goal },
    created_at: now,
  },
  {
    event_id: 'event-run-detail-smoke-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'agent.tool.call',
    actor: 'tool',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { tool: 'workspace.read', path: 'README.md' },
    created_at: now,
  },
  ...Array.from({ length: 198 }, (_, index) => {
    const sequence = index + 3;
    return {
      event_id: `event-run-detail-smoke-${sequence}`,
      run_id: RUN_ID,
      sequence,
      schema_version: 1,
      event_type: 'model.output.completed',
      actor: 'model',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { chunk: sequence, content: `Replay page smoke event ${sequence}` },
      created_at: now,
    };
  }),
  {
    event_id: 'event-run-detail-smoke-201',
    run_id: RUN_ID,
    sequence: 201,
    schema_version: 1,
    event_type: 'agent.run.completed',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: run.result },
    created_at: now,
  },
];

function log(message) {
  process.stdout.write(`[agent-run-detail-ui-smoke] ${message}\n`);
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
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
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
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, {
          agents: [{
            agent_id: 'agent-run-detail-smoke',
            name: 'Run Detail Smoke Agent',
            model_mode: 'follow_main',
            execution_backend: 'native_profile',
            model_config: {},
            enabled: true,
            editable: true,
            deletable: true,
          }],
        });
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
        sendJson(response, 200, { ok: true, profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [{
            id: 'agent-run-detail-smoke',
            name: 'Run Detail Smoke Agent',
            kind: 'agent',
            enabled: true,
            output_contract: 'report',
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [run] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, run);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}/artifacts/${ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          path: ARTIFACT_PATH,
          content: ARTIFACT_CONTENT,
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [runGroup] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/runs/${RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: runEvents.filter((event) => event.sequence > afterSequence).slice(0, limit),
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
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const runId = ${JSON.stringify(RUN_ID)};
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
              detail: document.querySelector('[data-testid="agent-run-detail"]')?.textContent || '',
              events: Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]')).map((node) => ({
                type: node.getAttribute('data-run-event'),
                sequence: node.getAttribute('data-run-event-sequence'),
                runId: node.getAttribute('data-run-event-run-id'),
                text: node.textContent,
              })),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(runId));
  console.log('[electron-smoke] run detail loaded');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}, 'run detail article');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes('Inspect Native RunEvent replay'), 'run task block');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes('Run Detail UI smoke completed through replay facts'), 'run result block');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return events.length === 200
      && eventTypes.includes('agent.run.started')
      && eventTypes.includes('agent.tool.call')
      && !eventTypes.includes('agent.run.completed')
      && sequences[0] === '1'
      && sequences[199] === '200'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && document.querySelector('[data-testid="agent-run-detail-load-more-events"]');
  }, 'initial run event replay page');
  console.log('[electron-smoke] initial replay page rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-load-more-events\\"]').click()", true);
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return events.length === 201
      && eventTypes.includes('agent.run.completed')
      && sequences[200] === '201'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && !document.querySelector('[data-testid="agent-run-detail-load-more-events"]');
  }, 'loaded more run event replay page');
  console.log('[electron-smoke] replay pagination loaded');
  await waitFor(win, () => {
    const artifact = document.querySelector('[data-testid="agent-run-detail-artifact"]');
    return artifact
      && artifact.getAttribute('data-artifact-path') === ${JSON.stringify(ARTIFACT_PATH)}
      && artifact.getAttribute('data-artifact-source-run-id') === ${JSON.stringify(RUN_ID)};
  }, 'run detail artifact item');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-artifact\\"]').click()", true);
  await waitFor(win, () => {
    const preview = document.querySelector('[data-testid="agent-run-detail-artifact-preview"]');
    return preview
      && preview.textContent.includes(${JSON.stringify(ARTIFACT_PATH)})
      && preview.textContent.includes('Artifact preview loaded from mock Bridge.');
  }, 'run detail artifact preview');
  console.log('[electron-smoke] artifact preview rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-run-detail-smoke-'));
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

async function main() {
  const bridge = await startMockBridge();
  const vitePort = await pickPort();
  const vite = startVite(vitePort);
  try {
    const devUrl = `http://127.0.0.1:${vitePort}`;
    await waitForHttp(devUrl);
    await runElectronSmoke(devUrl, bridge.url);
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
