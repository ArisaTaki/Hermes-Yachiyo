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
const AGENT_ID = 'chat-public-task-smoke-agent';
const AGENT_NAME = 'Public Task Smoke Agent';
const TASK_ID = 'task-chat-public-task-ui-smoke';
const RUN_ID = 'run-chat-public-task-ui-smoke';
const SESSION_ID = 'session-chat-public-task-ui-smoke';
const PROMPT = 'Draft a public task status card';
const COMPOSER_TEXT = `@"${AGENT_NAME}" ${PROMPT}`;
const TASK_TITLE = 'Public Task Smoke Agent Task';
const TASK_STEP = 'Public runtime events are visible in Chat.';
const TASK_SUMMARY = 'Chat accepted a public Agent task through /yachiyo/tasks.';
const now = new Date().toISOString();

const bridgeState = {
  legacyMessagePayloads: [],
  legacyRunnableCatalogHits: 0,
  messagesRequested: 0,
  requestLog: [],
  runnableCatalogHits: 0,
  taskEventsRequested: 0,
  taskRequest: null,
};

const publicAgent = {
  runnable_id: AGENT_ID,
  agent_id: AGENT_ID,
  kind: 'agent',
  name: AGENT_NAME,
  nickname: AGENT_NAME,
  description: 'Smoke agent exposed through the Yachiyo public runnable catalog.',
  enabled: true,
  output_contract: 'report',
  tool_capabilities: ['workspace.read'],
  approval_required_tools: ['workspace.write'],
};

const taskEvents = [
  {
    event_id: 'event-chat-public-task-smoke-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'agent.run.started',
    title: 'Agent run started',
    detail: 'Public task entered the shared runtime.',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { task_id: TASK_ID, agent_id: AGENT_ID, prompt: PROMPT },
    created_at: now,
  },
  {
    event_id: 'event-chat-public-task-smoke-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'agent.tool.call',
    title: 'workspace.read',
    detail: 'The shared runtime exposes tool calls in the Chat task card.',
    actor: 'tool',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { tool: 'workspace.read', status: 'completed' },
    created_at: now,
  },
];

function log(message) {
  process.stdout.write(`[chat-public-task-ui-smoke] ${message}\n`);
}

function publicTaskSnapshot() {
  return {
    task_id: TASK_ID,
    conversation_id: SESSION_ID,
    title: TASK_TITLE,
    status: 'running',
    summary: TASK_SUMMARY,
    current_step: TASK_STEP,
    progress_text: TASK_STEP,
    needs_user_action: false,
    pending_approvals: [],
    recent_events: taskEvents,
    artifacts: [],
    open_in_studio_url: `#/agents?run=${encodeURIComponent(RUN_ID)}`,
    created_at: now,
    updated_at: now,
  };
}

function runTimelineSnapshot() {
  return {
    run_id: RUN_ID,
    task_id: TASK_ID,
    title: TASK_TITLE,
    status: 'running',
    summary: TASK_SUMMARY,
    events: taskEvents,
    tool_calls: [],
    pending_approvals: [],
    artifacts: [],
    children: [],
    created_at: now,
    updated_at: now,
  };
}

function chatMessages() {
  if (!bridgeState.taskRequest) return [];
  return [
    {
      id: 'chat-public-task-user-message',
      role: 'user',
      content: PROMPT,
      status: 'completed',
      created_at: now,
      metadata: {
        runnable_id: AGENT_ID,
        runnable_kind: 'agent',
        source: 'chat',
      },
    },
    {
      id: 'chat-public-task-assistant-message',
      role: 'assistant',
      content: 'Public Agent task accepted.',
      status: 'processing',
      task_id: TASK_ID,
      created_at: now,
      metadata: {
        task_id: TASK_ID,
        run_id: RUN_ID,
        run_status: 'running',
        runnable_id: AGENT_ID,
        runnable_kind: 'agent',
        source: 'chat',
      },
    },
  ];
}

function sessionsPayload() {
  return {
    ok: true,
    current_session_id: SESSION_ID,
    sessions: [
      {
        session_id: SESSION_ID,
        title: 'Chat public task smoke',
        conversation_kind: 'main',
        message_count: chatMessages().length,
        token_count: 0,
        is_processing: Boolean(bridgeState.taskRequest),
        processing_count: bridgeState.taskRequest ? 1 : 0,
        updated_at: now,
      },
    ],
  };
}

function messagesPayload() {
  return {
    ok: true,
    session_id: SESSION_ID,
    messages: chatMessages(),
    session_context: { conversation_kind: 'main' },
    is_processing: Boolean(bridgeState.taskRequest),
    processing_count: bridgeState.taskRequest ? 1 : 0,
    approval_count: 0,
    token_count: 0,
  };
}

function runEventPage(url) {
  const afterSequence = Math.max(0, Number(url.searchParams.get('after_sequence') || '0'));
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  const events = taskEvents.filter((event) => event.sequence > afterSequence).slice(0, limit);
  return {
    run_id: RUN_ID,
    after_sequence: afterSequence,
    limit,
    next_after_sequence: events.length ? events[events.length - 1].sequence : afterSequence,
    has_more: false,
    events,
  };
}

function publicState() {
  return {
    legacyMessagePayloads: bridgeState.legacyMessagePayloads,
    legacyRunnableCatalogHits: bridgeState.legacyRunnableCatalogHits,
    messagesRequested: bridgeState.messagesRequested,
    requestLog: bridgeState.requestLog,
    runnableCatalogHits: bridgeState.runnableCatalogHits,
    taskEventsRequested: bridgeState.taskEventsRequested,
    taskRequest: bridgeState.taskRequest,
  };
}

function assertPublicTaskContract() {
  const { taskRequest } = bridgeState;
  if (!taskRequest) throw new Error('/yachiyo/tasks was not called');
  if (bridgeState.legacyMessagePayloads.length !== 0) {
    throw new Error(`Chat public task fell back to /ui/chat/messages: ${JSON.stringify(bridgeState.legacyMessagePayloads)}`);
  }
  if (taskRequest.prompt !== PROMPT) {
    throw new Error(`public task prompt mismatch: ${JSON.stringify(taskRequest.prompt)}`);
  }
  if (taskRequest.agent_id !== AGENT_ID) {
    throw new Error(`public task agent_id mismatch: ${JSON.stringify(taskRequest.agent_id)}`);
  }
  if (taskRequest.conversation_id !== SESSION_ID) {
    throw new Error(`public task conversation_id mismatch: ${JSON.stringify(taskRequest.conversation_id)}`);
  }
  if (taskRequest.metadata?.source !== 'chat') {
    throw new Error(`public task source metadata mismatch: ${JSON.stringify(taskRequest.metadata)}`);
  }
  if (taskRequest.metadata?.runnable_kind !== 'agent') {
    throw new Error(`public task runnable_kind metadata mismatch: ${JSON.stringify(taskRequest.metadata)}`);
  }
  if (!taskRequest.metadata?.client_message_id) {
    throw new Error(`public task missing client_message_id metadata: ${JSON.stringify(taskRequest.metadata)}`);
  }
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
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (url.pathname !== '/__smoke/state') {
        bridgeState.requestLog.push(`${request.method} ${url.pathname}`);
        bridgeState.requestLog = bridgeState.requestLog.slice(-80);
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/state') {
        sendJson(response, 200, publicState());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/executor') {
        sendJson(response, 200, {
          executor: 'NativeAgentExecutor',
          available: true,
          image_input: { can_attach_images: true, label: 'Add image' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/assistant/profile') {
        sendJson(response, 200, {
          ok: true,
          agent_name: 'Oha-Yachiyo',
          agent_nickname: 'Yachiyo',
          user_avatar_url: '',
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        bridgeState.messagesRequested += 1;
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/runnables') {
        bridgeState.runnableCatalogHits += 1;
        sendJson(response, 200, { agents: [publicAgent], workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        bridgeState.legacyRunnableCatalogHits += 1;
        sendJson(response, 200, {
          runnables: [{
            id: AGENT_ID,
            name: AGENT_NAME,
            nickname: AGENT_NAME,
            kind: 'agent',
            enabled: true,
            output_contract: 'report',
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/tasks') {
        sendJson(response, 200, { tasks: bridgeState.taskRequest ? [publicTaskSnapshot()] : [] });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/yachiyo/tasks') {
        bridgeState.taskRequest = await readRequestJson(request);
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}`) {
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}/timeline`) {
        sendJson(response, 200, runTimelineSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}/events`) {
        bridgeState.taskEventsRequested += 1;
        sendJson(response, 200, runEventPage(url));
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages') {
        const body = await readRequestJson(request);
        bridgeState.legacyMessagePayloads.push(body);
        sendJson(response, 200, { ok: true, task_id: 'legacy-chat-public-task-fallback' });
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
            "(async () => JSON.stringify({" +
              "hash: window.location.hash," +
              "card: document.querySelector('[data-testid=\"yachiyo-agent-task-card\"]')?.outerHTML || ''," +
              "studio: document.querySelector('[data-testid=\"yachiyo-agent-task-open-studio\"]')?.outerHTML || ''," +
              "messages: Array.from(document.querySelectorAll('.message')).map((node) => node.textContent).slice(-4)," +
              "smokeState: await fetch(" + JSON.stringify(bridgeUrl + '/__smoke/state') + ").then((response) => response.json()).catch((error) => ({ error: String(error) }))," +
              "bodyText: document.body.textContent.slice(-1800)" +
            "}))()",
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
    agentId: process.env.OHA_YACHIYO_SMOKE_AGENT_ID,
    bridgeUrl,
    composerText: process.env.OHA_YACHIYO_SMOKE_COMPOSER_TEXT,
    prompt: process.env.OHA_YACHIYO_SMOKE_PROMPT,
    runId: process.env.OHA_YACHIYO_SMOKE_RUN_ID,
    taskId: process.env.OHA_YACHIYO_SMOKE_TASK_ID,
    taskTitle: process.env.OHA_YACHIYO_SMOKE_TASK_TITLE,
  }), true);
  console.log('[electron-smoke] chat loaded');
  await waitFor(win, () => Boolean(document.querySelector('[data-testid="chat-composer-input"]')), 'Chat composer');
  await waitFor(win, () => {
    const empty = document.querySelector('.empty-state');
    return Boolean(empty?.textContent.includes('发送消息开始对话'))
      && !document.querySelector('.chat-loading-state');
  }, 'initial empty Chat session');
  await win.webContents.executeJavaScript(
    "const input = document.querySelector('[data-testid=\"chat-composer-input\"]');" +
      "const send = document.querySelector('[data-testid=\"chat-composer-send\"]');" +
      "const smoke = window.__ohaSmoke || {};" +
      "if (!input || !send) throw new Error('missing Chat composer controls');" +
      "const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;" +
      "setter.call(input, smoke.composerText);" +
      "input.dispatchEvent(new Event('input', { bubbles: true }));" +
      "input.dispatchEvent(new Event('change', { bubbles: true }));" +
      "input.focus();" +
      "send.click();",
    true
  );
  await waitFor(win, async () => {
    const smoke = window.__ohaSmoke || {};
    const response = await fetch(smoke.bridgeUrl + '/__smoke/state');
    const state = await response.json();
    return Boolean(state.taskRequest) && state.legacyMessagePayloads.length === 0;
  }, 'public /yachiyo/tasks request');
  await waitFor(win, () => {
    const smoke = window.__ohaSmoke || {};
    const card = document.querySelector('[data-testid="yachiyo-agent-task-card"]');
    const timeline = document.querySelector('[data-testid="yachiyo-agent-task-timeline"]');
    const studio = document.querySelector('[data-testid="yachiyo-agent-task-open-studio"]');
    const tool = document.querySelector('[data-testid="yachiyo-agent-task-tool-summary-item"][data-tool-name="workspace.read"]');
    return Boolean(card)
      && card.getAttribute('data-task-id') === smoke.taskId
      && card.getAttribute('data-run-id') === smoke.runId
      && card.getAttribute('data-task-status') === 'running'
      && card.textContent.includes(smoke.taskTitle)
      && Boolean(tool)
      && Boolean(timeline)
      && studio?.getAttribute('data-run-id') === smoke.runId
      && studio?.getAttribute('data-studio-url')?.includes(smoke.runId)
      && studio.textContent.includes('Agent Studio');
  }, 'Chat public task card rendered');
  await waitFor(win, async () => {
    const smoke = window.__ohaSmoke || {};
    const response = await fetch(smoke.bridgeUrl + '/__smoke/state');
    const state = await response.json();
    return state.taskEventsRequested > 0;
  }, 'public task event replay');
  console.log('[electron-smoke] Chat public task card rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-public-task-smoke-'));
  const mainPath = path.join(tempDir, 'main.cjs');
  fs.writeFileSync(mainPath, script, 'utf8');
  return new Promise((resolve, reject) => {
    const child = spawn(ELECTRON, [mainPath], {
      cwd: FRONTEND,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        ELECTRON_ENABLE_LOGGING: '1',
        OHA_YACHIYO_SMOKE_AGENT_ID: AGENT_ID,
        OHA_YACHIYO_SMOKE_COMPOSER_TEXT: COMPOSER_TEXT,
        OHA_YACHIYO_SMOKE_DEV_URL: devUrl,
        OHA_YACHIYO_SMOKE_BRIDGE_URL: bridgeUrl,
        OHA_YACHIYO_SMOKE_PROMPT: PROMPT,
        OHA_YACHIYO_SMOKE_RUN_ID: RUN_ID,
        OHA_YACHIYO_SMOKE_TASK_ID: TASK_ID,
        OHA_YACHIYO_SMOKE_TASK_TITLE: TASK_TITLE,
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
    assertPublicTaskContract();
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
