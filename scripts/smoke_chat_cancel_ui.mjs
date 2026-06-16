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
const SESSION_ID = 'chat_cancel_ui_smoke_session';
const TASK_ID = 'task-chat-cancel-ui-smoke';
const RUN_ID = 'main_chat_run_cancel_ui_smoke';
const RUN_GROUP_ID = 'group-chat-cancel-ui-smoke';
const RUN_GOAL = 'Start a cancellable Chat UI smoke task.';
const RUN_RESULT = 'Cancelled by user from Chat UI smoke.';
const now = new Date().toISOString();

const bridgeState = {
  cancelled: false,
  cancelCalls: 0,
};

function log(message) {
  process.stdout.write(`[chat-cancel-ui-smoke] ${message}\n`);
}

function fail(message) {
  throw new Error(message);
}

function resetConversation() {
  bridgeState.cancelled = false;
}

function messagesPayload(extra = {}) {
  const isProcessing = !bridgeState.cancelled;
  const assistant = bridgeState.cancelled
    ? {
        id: 'assistant-cancel-ui-smoke-cancelled',
        role: 'assistant',
        content: RUN_RESULT,
        status: 'failed',
        error: RUN_RESULT,
        created_at: now,
        metadata: {
          task_id: TASK_ID,
          run_id: RUN_ID,
          run_group_id: RUN_GROUP_ID,
          run_status: 'cancelled',
        },
      }
    : {
        id: 'assistant-cancel-ui-smoke-processing',
        role: 'assistant',
        content: 'Still running cancel smoke.',
        status: 'processing',
        created_at: now,
        metadata: {
          task_id: TASK_ID,
          run_id: RUN_ID,
          run_status: 'running',
        },
      };
  return {
    ok: true,
    session_id: SESSION_ID,
    messages: [
      {
        id: 'user-cancel-ui-smoke',
        role: 'user',
        content: RUN_GOAL,
        status: 'completed',
        created_at: now,
        metadata: { task_id: TASK_ID },
      },
      assistant,
    ],
    session_context: { conversation_kind: 'main' },
    is_processing: isProcessing,
    processing_count: isProcessing ? 1 : 0,
    approval_count: 0,
    token_count: 0,
    ...extra,
  };
}

function runPayload() {
  return {
    run_id: RUN_ID,
    run_group_id: RUN_GROUP_ID,
    run_group_source: 'main_chat',
    task_id: TASK_ID,
    session_id: SESSION_ID,
    task_run_link_run_status: bridgeState.cancelled ? 'cancelled' : 'running',
    task_run_link_last_event_sequence: bridgeState.cancelled ? 2 : 1,
    kind: 'main_chat_run',
    runnable_id: 'builtin:yachiyo-main',
    runnable_name: 'Oha-Yachiyo',
    status: bridgeState.cancelled ? 'cancelled' : 'running',
    user_goal: RUN_GOAL,
    result: bridgeState.cancelled ? RUN_RESULT : '',
    timeline: bridgeState.cancelled
      ? [
          { event: 'run.started', status: 'running', task_id: TASK_ID },
          { event: 'run.cancelled', status: 'cancelled', result: RUN_RESULT },
        ]
      : [{ event: 'run.started', status: 'running', task_id: TASK_ID }],
    artifacts: [],
    created_at: now,
    updated_at: now,
  };
}

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Chat Cancel UI Smoke',
  source: 'main_chat',
  status: 'cancelled',
  summary: RUN_RESULT,
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

function runEventsPage(url) {
  const events = [
    {
      event_id: 'event-chat-cancel-smoke-1',
      run_id: RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'run.started',
      actor: 'runtime',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { task_id: TASK_ID, goal: RUN_GOAL },
      created_at: now,
    },
    ...(bridgeState.cancelled
      ? [{
          event_id: 'event-chat-cancel-smoke-2',
          run_id: RUN_ID,
          sequence: 2,
          schema_version: 1,
          event_type: 'run.cancelled',
          actor: 'runtime',
          visibility: 'user',
          sensitivity: 'normal',
          payload: { result: RUN_RESULT },
          created_at: now,
        }]
      : []),
  ];
  const afterSequence = Math.max(0, Number(url.searchParams.get('after_sequence') || '0'));
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  return {
    run_id: RUN_ID,
    after_sequence: afterSequence,
    limit,
    events: events.filter((event) => event.sequence > afterSequence).slice(0, limit),
  };
}

function sessionsPayload() {
  return {
    ok: true,
    current_session_id: SESSION_ID,
    sessions: [
      {
        session_id: SESSION_ID,
        title: 'Chat cancel UI smoke',
        conversation_kind: 'main',
        message_count: 2,
        token_count: 0,
        is_processing: !bridgeState.cancelled,
        processing_count: bridgeState.cancelled ? 0 : 1,
        latest_message_preview: bridgeState.cancelled
          ? RUN_RESULT
          : 'Still running cancel smoke.',
        latest_message_status: bridgeState.cancelled ? 'failed' : 'processing',
        updated_at: now,
      },
    ],
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
      if (request.method === 'GET' && url.pathname === '/ui/chat/executor') {
        sendJson(response, 200, {
          executor: 'NativeAgentExecutor',
          available: true,
          image_input: { can_attach_images: true, label: 'Add image' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/assistant/profile') {
        sendJson(response, 200, { ok: true, agent_name: 'Oha-Yachiyo', user_avatar_url: '' });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, { runnables: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [runPayload()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, runPayload());
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
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`) {
        sendJson(response, 200, runEventsPage(url));
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/session/cancel') {
        bridgeState.cancelled = true;
        bridgeState.cancelCalls += 1;
        log(`mock bridge cancelled chat session (${bridgeState.cancelCalls})`);
        sendJson(response, 200, messagesPayload({ cancelled_tasks: 1 }));
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/reset') {
        resetConversation();
        sendJson(response, 200, { ok: true });
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
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-cancel-smoke-'));
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const chatUrl = devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat';
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
              status: document.querySelector('.chat-status')?.textContent || '',
              headerDisabled: document.querySelector('[data-testid="chat-header-stop-button"]')?.disabled,
              composerStop: Boolean(document.querySelector('[data-testid="chat-composer-stop-button"]')),
              messages: Array.from(document.querySelectorAll('[data-message-id]')).map((node) => ({
                id: node.getAttribute('data-message-id'),
                className: node.className,
                text: node.textContent.slice(0, 240),
              })),
              bodyText: document.body.textContent.slice(-1200),
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
async function waitForProcessing(win, label) {
  await waitFor(win, () => {
    const header = document.querySelector('[data-testid="chat-header-stop-button"]');
    const composer = document.querySelector('[data-testid="chat-composer-stop-button"]');
    const processingMessage = document.querySelector('[data-message-id="assistant-cancel-ui-smoke-processing"]');
    return document.querySelector('textarea.chat-input')
      && header
      && !header.disabled
      && composer
      && processingMessage?.className.includes('processing')
      && document.body.textContent.includes('Still running cancel smoke.');
  }, label);
}
async function waitForCancelled(win, label) {
  await waitFor(win, () => {
    const header = document.querySelector('[data-testid="chat-header-stop-button"]');
    const composer = document.querySelector('[data-testid="chat-composer-stop-button"]');
    const cancelledMessage = document.querySelector('[data-message-id="assistant-cancel-ui-smoke-cancelled"]');
    const openRun = cancelledMessage?.querySelector('[data-testid="chat-message-open-run-detail"]');
    const status = document.querySelector('.chat-status')?.textContent || '';
    return header
      && header.disabled
      && !composer
      && cancelledMessage?.className.includes('error')
      && openRun?.textContent.includes('Agent Studio')
      && document.body.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && !document.body.textContent.includes('Still running cancel smoke.')
      && status !== '取消失败';
  }, label);
}
async function waitForCancelledRunDetail(win, label) {
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const task = document.querySelector('[data-testid="agent-run-detail-task"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const cancelledEvent = events.find((node) => node.getAttribute('data-run-event') === 'run.cancelled');
    return window.location.hash.includes(${JSON.stringify(RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'main_chat_run'
      && detail?.getAttribute('data-run-status') === 'cancelled'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
      && task?.textContent.includes(${JSON.stringify(RUN_GOAL)})
      && result?.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && eventTypes.includes('run.started')
      && eventTypes.includes('run.cancelled')
      && cancelledEvent?.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(RUN_ID)});
  }, label);
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
  await win.loadURL(chatUrl);
  console.log('[electron-smoke] chat loaded for composer cancel');
  await waitForProcessing(win, 'composer stop button readiness');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-stop-button\\"]').click()", true);
  await waitForCancelled(win, 'composer stop cancellation projection');
  console.log('[electron-smoke] composer stop cancelled chat');

  await win.webContents.executeJavaScript("fetch(" + JSON.stringify(bridgeUrl + '/__smoke/reset') + ", { method: 'POST' })", true);
  await win.loadURL('about:blank');
  await win.loadURL(chatUrl);
  console.log('[electron-smoke] chat loaded for header cancel');
  await waitForProcessing(win, 'header stop button readiness');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-header-stop-button\\"]').click()", true);
  await waitForCancelled(win, 'header stop cancellation projection');
  console.log('[electron-smoke] header stop cancelled chat');
  await win.webContents.executeJavaScript("document.querySelector('[data-message-id=\\"assistant-cancel-ui-smoke-cancelled\\"] [data-testid=\\"chat-message-open-run-detail\\"]').click()", true);
  await waitForCancelledRunDetail(win, 'cancelled message Run Detail replay handoff');
  console.log('[electron-smoke] cancelled message Run Detail replay verified');

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
  if (process.env.CI && process.platform === 'darwin') {
    log('running on CI macOS; Electron may require a display session');
  }
  const bridge = await startMockBridge();
  const vitePort = await pickPort();
  const vite = startVite(vitePort);
  try {
    const devUrl = `http://127.0.0.1:${vitePort}`;
    await waitForHttp(devUrl);
    await runElectronSmoke(devUrl, bridge.url);
    if (bridgeState.cancelCalls !== 2) {
      fail(`expected two chat cancel calls, got ${bridgeState.cancelCalls}`);
    }
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
