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
const AGENT_ID = 'chat-agent-progress-ui-smoke-agent';
const RUN_ID = 'chat_agent_progress_ui_smoke_run';
const TASK_ID = 'task-chat-agent-progress-ui-smoke';
const SESSION_ID = 'session-chat-agent-progress-ui-smoke';
const RUN_GROUP_ID = 'group-chat-agent-progress-ui-smoke';
const RUN_GOAL = 'Open running Chat Agent progress Run Detail from Electron UI smoke';
const PROGRESS_TITLE = 'Chat Agent progress smoke is running';
const PROGRESS_DETAIL = 'Native Run is still active for the Chat progress card.';
const now = new Date().toISOString();

const agent = {
  agent_id: AGENT_ID,
  name: 'Chat Agent Progress Smoke Agent',
  model_mode: 'follow_main',
  execution_backend: 'native_profile',
  model_config: {},
  enabled: true,
  editable: true,
  deletable: true,
};

const run = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'main_chat',
  task_id: TASK_ID,
  session_id: SESSION_ID,
  task_run_link_run_status: 'running',
  task_run_link_last_event_sequence: 1,
  kind: 'agent_run',
  runnable_id: AGENT_ID,
  runnable_name: 'Chat Agent Progress Smoke Agent',
  status: 'running',
  user_goal: RUN_GOAL,
  result: '',
  timeline: [{ event: 'agent.run.started', status: 'running', task_id: TASK_ID }],
  artifacts: [],
  created_at: now,
  updated_at: now,
};

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Chat Agent Progress Smoke',
  source: 'main_chat',
  status: 'running',
  summary: 'Running main Chat Native Run',
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

const runEvents = [
  {
    event_id: 'event-chat-agent-progress-smoke-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'agent.run.started',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { task_id: TASK_ID, goal: RUN_GOAL },
    created_at: now,
  },
];

const messages = [
  {
    id: 'user-chat-agent-progress-message',
    role: 'user',
    content: RUN_GOAL,
    status: 'completed',
    task_id: TASK_ID,
    created_at: now,
    metadata: { task_id: TASK_ID },
  },
  {
    id: 'assistant-chat-agent-progress-message',
    role: 'assistant',
    content: '',
    status: 'processing',
    task_id: TASK_ID,
    created_at: now,
    metadata: {
      task_id: TASK_ID,
      run_id: RUN_ID,
      run_status: 'running',
      runnable_id: AGENT_ID,
      runnable_kind: 'agent',
      run_group_id: RUN_GROUP_ID,
      run_progress_title: PROGRESS_TITLE,
      run_progress_detail: PROGRESS_DETAIL,
      source: 'main_chat',
    },
  },
];

function log(message) {
  process.stdout.write(`[chat-agent-progress-ui-smoke] ${message}\n`);
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

function runEventsPage(url) {
  const afterSequence = Math.max(0, Number(url.searchParams.get('after_sequence') || '0'));
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  return {
    run_id: RUN_ID,
    after_sequence: afterSequence,
    limit,
    events: runEvents.filter((event) => event.sequence > afterSequence).slice(0, limit),
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
      if (request.method === 'GET' && url.pathname === '/ui/chat/executor') {
        sendJson(response, 200, {
          executor: 'NativeAgentExecutor',
          available: true,
          image_input: { can_attach_images: true, label: '添加图片附件' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/assistant/profile') {
        sendJson(response, 200, { ok: true, agent_name: 'Oha-Yachiyo', user_avatar_url: '' });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, {
          ok: true,
          current_session_id: SESSION_ID,
          sessions: [
            {
              session_id: SESSION_ID,
              title: 'Chat Agent progress',
              conversation_kind: 'main',
            },
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        sendJson(response, 200, {
          ok: true,
          session_id: SESSION_ID,
          messages,
          session_context: { conversation_kind: 'main' },
          is_processing: true,
          processing_count: 1,
          approval_count: 0,
          token_count: 0,
        });
        return;
      }
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
            profile_id: 'profile-chat-agent-progress-smoke',
            name: 'Chat Agent Progress Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: 'profile-chat-agent-progress-smoke' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [
            { id: AGENT_ID, name: agent.name, kind: 'agent', enabled: true, output_contract: 'chat' },
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/workflows') {
        sendJson(response, 200, { workflows: [] });
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
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [runGroup] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/runs/${RUN_ID}/events`) {
        sendJson(response, 200, runEventsPage(url));
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
const runId = process.env.OHA_YACHIYO_SMOKE_RUN_ID;
const taskId = process.env.OHA_YACHIYO_SMOKE_TASK_ID;
const sessionId = process.env.OHA_YACHIYO_SMOKE_SESSION_ID;
const runGroupId = process.env.OHA_YACHIYO_SMOKE_RUN_GROUP_ID;
const runGoal = process.env.OHA_YACHIYO_SMOKE_RUN_GOAL;
const progressTitle = process.env.OHA_YACHIYO_SMOKE_PROGRESS_TITLE;
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
              "progress: document.querySelector('[data-testid=\"chat-agent-run-progress-card\"]')?.outerHTML || ''," +
              "detail: document.querySelector('[data-testid=\"agent-run-detail\"]')?.outerHTML || ''," +
              "task: document.querySelector('[data-testid=\"agent-run-detail-task\"]')?.textContent || ''," +
              "events: Array.from(document.querySelectorAll('[data-testid=\"agent-run-detail-execution-event\"]')).map((node) => ({type: node.getAttribute('data-run-event'), sequence: node.getAttribute('data-run-event-sequence'), runId: node.getAttribute('data-run-event-run-id'), text: node.textContent}))," +
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat');
  await win.webContents.executeJavaScript('window.__ohaSmoke = ' + JSON.stringify({
    runId,
    taskId,
    sessionId,
    runGroupId,
    runGoal,
    progressTitle,
  }), true);
  console.log('[electron-smoke] chat loaded');
  await waitFor(win, () => {
    const smoke = window.__ohaSmoke || {};
    const card = document.querySelector('[data-testid="chat-agent-run-progress-card"]');
    const button = document.querySelector('[data-testid="chat-agent-run-progress-open-run-detail"]');
    return Boolean(card)
      && card.getAttribute('data-run-id') === smoke.runId
      && card.getAttribute('data-run-status') === 'processing'
      && card.getAttribute('data-run-group-id') === smoke.runGroupId
      && card.textContent.includes(smoke.progressTitle)
      && Boolean(button);
  }, 'Chat Agent progress card');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\"chat-agent-run-progress-open-run-detail\"]').click()", true);
  await waitFor(win, () => (
    (() => {
      const smoke = window.__ohaSmoke || {};
      return (
    window.location.hash.includes('/agents')
    && window.location.hash.includes(smoke.runId)
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === smoke.runId
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-status') === 'running'
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-task-id') === smoke.taskId
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-session-id') === smoke.sessionId
    && document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes(smoke.runGoal)
      );
    })()
  ), 'running Run Detail handoff');
  await waitFor(win, () => {
    const smoke = window.__ohaSmoke || {};
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const startedEvent = events[0];
    return events.length === 1
      && startedEvent.getAttribute('data-run-event') === 'agent.run.started'
      && startedEvent.getAttribute('data-run-event-sequence') === '1'
      && startedEvent.getAttribute('data-run-event-run-id') === smoke.runId
      && startedEvent.textContent.includes(smoke.taskId)
      && startedEvent.textContent.includes(smoke.runGoal);
  }, 'running Run Detail replay events');
  console.log('[electron-smoke] Chat Agent progress opened matching running Run Detail');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-agent-progress-smoke-'));
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
        OHA_YACHIYO_SMOKE_RUN_ID: RUN_ID,
        OHA_YACHIYO_SMOKE_TASK_ID: TASK_ID,
        OHA_YACHIYO_SMOKE_SESSION_ID: SESSION_ID,
        OHA_YACHIYO_SMOKE_RUN_GROUP_ID: RUN_GROUP_ID,
        OHA_YACHIYO_SMOKE_RUN_GOAL: RUN_GOAL,
        OHA_YACHIYO_SMOKE_PROGRESS_TITLE: PROGRESS_TITLE,
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
