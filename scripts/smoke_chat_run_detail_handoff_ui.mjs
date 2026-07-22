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
const AGENT_ID = 'chat-run-detail-handoff-agent';
const RUN_ID = 'chat_run_detail_handoff_ui_smoke_run';
const TASK_ID = 'task-chat-run-detail-handoff-ui-smoke';
const SESSION_ID = 'session-chat-run-detail-handoff-ui-smoke';
const RUN_GROUP_ID = 'group-chat-run-detail-handoff-ui-smoke';
const RUN_GOAL = 'Open completed Chat message Run Detail from Electron UI smoke';
const RUN_RESULT = 'Chat completed message Run Detail handoff smoke completed';
const COMPLETED_MESSAGE_ID = 'assistant-chat-run-detail-handoff-message';
const FAILED_RUN_ID = 'chat_run_detail_handoff_ui_smoke_failed_run';
const FAILED_TASK_ID = 'task-chat-run-detail-handoff-ui-smoke-failed';
const FAILED_RUN_GROUP_ID = 'group-chat-run-detail-handoff-ui-smoke-failed';
const FAILED_USER_MESSAGE_ID = 'user-chat-run-detail-handoff-failed-message';
const FAILED_MESSAGE_ID = 'assistant-chat-run-detail-handoff-failed-message';
const FAILED_ORIGINAL_CLIENT_MESSAGE_ID = 'client-chat-run-detail-handoff-failed-original';
const FAILED_RUN_GOAL = 'Open failed Chat message Run Detail from Electron UI smoke';
const FAILED_USER_PROMPT = 'Retry the original failed desktop request from Chat.';
const FAILED_RUN_ERROR = 'Chat failed message mapped NativeRunEngine failure.';
const RETRY_DRAFT = 'Keep this composer draft while retrying';
const CODE_BLOCK = "console.log('oha code copy smoke');";
const ASSISTANT_CONTENT = `${RUN_RESULT}\n\n\`\`\`js\n${CODE_BLOCK}\n\`\`\``;
const now = new Date().toISOString();

const bridgeState = {
  publicTaskPayloads: [],
  retryPayloads: [],
};

const agent = {
  agent_id: AGENT_ID,
  name: 'Chat Run Detail Handoff Agent',
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
  task_run_link_run_status: 'completed',
  task_run_link_last_event_sequence: 3,
  kind: 'agent_run',
  runnable_id: AGENT_ID,
  runnable_name: 'Chat Run Detail Handoff Agent',
  status: 'completed',
  user_goal: RUN_GOAL,
  result: RUN_RESULT,
  timeline: [
    { event: 'agent.run.started', status: 'running', task_id: TASK_ID },
    { event: 'model.output.completed', status: 'completed', output: RUN_RESULT },
    { event: 'agent.run.completed', status: 'completed', result: RUN_RESULT },
  ],
  artifacts: [],
  created_at: now,
  updated_at: now,
};

const failedRun = {
  run_id: FAILED_RUN_ID,
  run_group_id: FAILED_RUN_GROUP_ID,
  run_group_source: 'main_chat',
  task_id: FAILED_TASK_ID,
  session_id: SESSION_ID,
  task_run_link_run_status: 'failed',
  task_run_link_last_event_sequence: 3,
  kind: 'agent_run',
  runnable_id: AGENT_ID,
  runnable_name: 'Chat Run Detail Handoff Agent',
  status: 'failed',
  user_goal: FAILED_RUN_GOAL,
  result: FAILED_RUN_ERROR,
  timeline: [
    { event: 'agent.run.started', status: 'running', task_id: FAILED_TASK_ID },
    { event: 'model.request.failed', status: 'failed', error: FAILED_RUN_ERROR },
    { event: 'agent.run.failed', status: 'failed', error: FAILED_RUN_ERROR },
  ],
  artifacts: [],
  created_at: now,
  updated_at: now,
};

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Chat Run Detail Handoff',
  source: 'main_chat',
  status: 'completed',
  summary: 'Completed main Chat Native Run',
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

const failedRunGroup = {
  run_group_id: FAILED_RUN_GROUP_ID,
  title: 'Chat Run Detail Handoff Failed',
  source: 'main_chat',
  status: 'failed',
  summary: FAILED_RUN_ERROR,
  child_run_ids: [FAILED_RUN_ID],
  created_at: now,
  updated_at: now,
};

const runEvents = [
  {
    event_id: 'event-chat-handoff-smoke-1',
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
  {
    event_id: 'event-chat-handoff-smoke-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'model.output.completed',
    actor: 'model',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { output: RUN_RESULT },
    created_at: now,
  },
  {
    event_id: 'event-chat-handoff-smoke-3',
    run_id: RUN_ID,
    sequence: 3,
    schema_version: 1,
    event_type: 'agent.run.completed',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: RUN_RESULT },
    created_at: now,
  },
];

const messages = [
  {
    id: 'user-chat-run-detail-handoff-message',
    role: 'user',
    content: RUN_GOAL,
    status: 'completed',
    task_id: TASK_ID,
    created_at: now,
    metadata: { task_id: TASK_ID },
  },
  {
    id: COMPLETED_MESSAGE_ID,
    role: 'assistant',
    content: ASSISTANT_CONTENT,
    status: 'completed',
    task_id: TASK_ID,
    created_at: now,
    activity_events: [{
      event_id: 'activity-chat-run-detail-handoff-completed',
      tool_name: 'workspace.read',
      status: 'completed',
      detail: 'Read the completed run workspace.',
    }],
    metadata: {
      task_id: TASK_ID,
      run_id: RUN_ID,
      run_status: 'completed',
      runnable_id: AGENT_ID,
      runnable_kind: 'agent',
      source: 'main_chat',
    },
  },
  {
    id: FAILED_USER_MESSAGE_ID,
    role: 'user',
    content: FAILED_USER_PROMPT,
    status: 'completed',
    task_id: FAILED_TASK_ID,
    created_at: now,
    metadata: {
      task_id: FAILED_TASK_ID,
      client_message_id: FAILED_ORIGINAL_CLIENT_MESSAGE_ID,
    },
  },
  {
    id: FAILED_MESSAGE_ID,
    role: 'assistant',
    content: FAILED_RUN_ERROR,
    error: FAILED_RUN_ERROR,
    status: 'failed',
    task_id: FAILED_TASK_ID,
    created_at: now,
    activity_events: [{
      event_id: 'activity-chat-run-detail-handoff-failed',
      tool_name: 'desktop.active_window',
      status: 'failed',
      detail: 'Desktop observation failed before the retry.',
    }],
    metadata: {
      task_id: FAILED_TASK_ID,
      run_id: FAILED_RUN_ID,
      run_status: 'failed',
      runnable_id: AGENT_ID,
      runnable_kind: 'agent',
      source: 'main_chat',
    },
  },
];

const failedRunEvents = [
  {
    event_id: 'event-chat-handoff-failed-smoke-1',
    run_id: FAILED_RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'agent.run.started',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { task_id: FAILED_TASK_ID, goal: FAILED_RUN_GOAL },
    created_at: now,
  },
  {
    event_id: 'event-chat-handoff-failed-smoke-2',
    run_id: FAILED_RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'model.request.failed',
    actor: 'model',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { error: FAILED_RUN_ERROR },
    created_at: now,
  },
  {
    event_id: 'event-chat-handoff-failed-smoke-3',
    run_id: FAILED_RUN_ID,
    sequence: 3,
    schema_version: 1,
    event_type: 'agent.run.failed',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { error: FAILED_RUN_ERROR },
    created_at: now,
  },
];

function log(message) {
  process.stdout.write(`[chat-run-detail-handoff-ui-smoke] ${message}\n`);
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

function runEventsPage(url, runId) {
  const afterSequence = Math.max(0, Number(url.searchParams.get('after_sequence') || '0'));
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  const events = runId === FAILED_RUN_ID ? failedRunEvents : runEvents;
  return {
    run_id: runId,
    after_sequence: afterSequence,
    limit,
    events: events.filter((event) => event.sequence > afterSequence).slice(0, limit),
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
              title: 'Chat Run Detail handoff',
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
          is_processing: false,
          processing_count: 0,
          approval_count: 0,
          token_count: 0,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/state') {
        sendJson(response, 200, bridgeState);
        return;
      }
      if (request.method === 'POST' && url.pathname === '/yachiyo/tasks') {
        const body = await readRequestJson(request);
        bridgeState.publicTaskPayloads.push(body);
        await new Promise((resolve) => setTimeout(resolve, 180));
        sendJson(response, 503, { ok: false, error: 'force legacy retry fallback' });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages/retry') {
        const body = await readRequestJson(request);
        bridgeState.retryPayloads.push(body);
        await new Promise((resolve) => setTimeout(resolve, 180));
        if (bridgeState.retryPayloads.length === 1) {
          sendJson(response, 200, {
            ok: false,
            committed: false,
            delivery_state: 'not_committed',
            error: 'forced failed-message retry rejection',
          });
          return;
        }
        sendJson(response, 200, {
          ok: true,
          task_id: 'task-chat-run-detail-handoff-retry-smoke',
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
            profile_id: 'profile-chat-run-detail-handoff-smoke',
            name: 'Chat Run Detail Handoff Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: 'profile-chat-run-detail-handoff-smoke' },
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [run, failedRun] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, run);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${FAILED_RUN_ID}`) {
        sendJson(response, 200, failedRun);
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [runGroup, failedRunGroup] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${FAILED_RUN_GROUP_ID}`) {
        sendJson(response, 200, failedRunGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`) {
        sendJson(response, 200, runEventsPage(url, RUN_ID));
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${FAILED_RUN_ID}/events`) {
        sendJson(response, 200, runEventsPage(url, FAILED_RUN_ID));
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
const taskId = ${JSON.stringify(TASK_ID)};
const sessionId = ${JSON.stringify(SESSION_ID)};
const runGoal = ${JSON.stringify(RUN_GOAL)};
const runResult = ${JSON.stringify(RUN_RESULT)};
const failedRunId = ${JSON.stringify(FAILED_RUN_ID)};
const failedTaskId = ${JSON.stringify(FAILED_TASK_ID)};
const failedMessageId = ${JSON.stringify(FAILED_MESSAGE_ID)};
const failedRunGoal = ${JSON.stringify(FAILED_RUN_GOAL)};
const failedUserPrompt = ${JSON.stringify(FAILED_USER_PROMPT)};
const failedRunError = ${JSON.stringify(FAILED_RUN_ERROR)};
const retryDraft = ${JSON.stringify(RETRY_DRAFT)};
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
              chatButton: document.querySelector('[data-testid="chat-message-open-run-detail"]')?.outerHTML || '',
              retryButton: document.querySelector('[data-testid="chat-message-retry"]')?.outerHTML || '',
              composerInput: document.querySelector('[data-testid="chat-composer-input"]')?.outerHTML || '',
              composerSend: document.querySelector('[data-testid="chat-composer-send"]')?.outerHTML || '',
              copyButton: document.querySelector('[data-testid="chat-message-copy"]')?.outerHTML || '',
              codeCopyButton: document.querySelector('[data-testid="chat-code-copy"]')?.outerHTML || '',
              detail: document.querySelector('[data-testid="agent-run-detail"]')?.outerHTML || '',
              task: document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent || '',
              result: document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent || '',
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat');
  await win.webContents.executeJavaScript(
    'window.__retrySmokeBridgeUrl = ' + JSON.stringify(bridgeUrl),
    true,
  );
  console.log('[electron-smoke] chat loaded');
  await waitFor(win, () => {
    const chatButton = document.querySelector('[data-testid="chat-message-open-run-detail"]');
    const retryButton = document.querySelector('[data-testid="chat-message-retry"]');
    const bodyText = document.body.textContent || '';
    return !chatButton
      && document.querySelector('[data-testid="chat-message-copy"]')
      && document.querySelector('[data-testid="chat-code-copy"]')
      && bodyText.includes(${JSON.stringify(RUN_RESULT)})
      && bodyText.includes(${JSON.stringify(FAILED_RUN_ERROR)})
      && bodyText.includes('查看详情')
      && retryButton?.disabled === false;
  }, 'consumer Chat hides successful Run Detail and keeps failed detail action');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-composer-input"]');
      if (!input) throw new Error('missing Chat composer input');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(RETRY_DRAFT)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    })();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="chat-composer-input"]')?.value === ${JSON.stringify(RETRY_DRAFT)}
    && document.querySelector('[data-testid="chat-composer-send"]')?.disabled === false
  ), 'retry draft ready');
  await win.webContents.executeJavaScript(\`
    const retry = document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-retry"]');
    if (!retry) throw new Error('missing failed Chat message retry button');
    retry.click();
  \`, true);
  await waitFor(win, () => Boolean(
    document.querySelector('[data-message-id="local:pending-assistant-reply"]')
  ), 'failed Chat retry loading');
  await waitFor(win, async () => {
    const state = await fetch(window.__retrySmokeBridgeUrl + '/__smoke/state').then((response) => response.json());
    const retry = document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-retry"]');
    const input = document.querySelector('[data-testid="chat-composer-input"]');
    const send = document.querySelector('[data-testid="chat-composer-send"]');
    return state.retryPayloads.length === 1
      && state.publicTaskPayloads[0]?.prompt === ${JSON.stringify(FAILED_USER_PROMPT)}
      && !state.publicTaskPayloads[0]?.prompt.includes(${JSON.stringify(FAILED_RUN_ERROR)})
      && retry?.disabled === false
      && !document.querySelector('[data-message-id="local:pending-assistant-reply"]')
      && input?.value === ${JSON.stringify(RETRY_DRAFT)}
      && send?.disabled === false;
  }, 'failed Chat retry rejection releases submitting state with original prompt');
  await win.webContents.executeJavaScript(\`
    document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-retry"]')?.click();
  \`, true);
  await waitFor(win, () => Boolean(
    document.querySelector('[data-message-id="local:pending-assistant-reply"]')
  ), 'successful failed Chat retry loading');
  await waitFor(win, async () => {
    const state = await fetch(window.__retrySmokeBridgeUrl + '/__smoke/state').then((response) => response.json());
    const retry = document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-retry"]');
    const input = document.querySelector('[data-testid="chat-composer-input"]');
    const send = document.querySelector('[data-testid="chat-composer-send"]');
    return state.retryPayloads.length === 2
      && state.publicTaskPayloads[1]?.prompt === ${JSON.stringify(FAILED_USER_PROMPT)}
      && retry?.disabled === false
      && input?.value === ${JSON.stringify(RETRY_DRAFT)}
      && send?.disabled === false;
  }, 'successful failed Chat retry releases submitting state');
  console.log('[electron-smoke] failed Chat retry reuses original user prompt and releases state');
  await win.webContents.executeJavaScript(\`
    const openFailedRun = document.querySelector('[data-message-id="${FAILED_MESSAGE_ID}"] [data-testid="chat-message-failure-open-detail"]');
    if (!openFailedRun) throw new Error('missing failed Chat message detail button');
    openFailedRun.click();
  \`, true);
  await waitFor(win, () => (
    window.location.hash.includes('/agents')
    && window.location.hash.includes(${JSON.stringify(FAILED_RUN_ID)})
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(FAILED_RUN_ID)}
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-task-id') === ${JSON.stringify(FAILED_TASK_ID)}
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-status') === 'failed'
    && document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes(${JSON.stringify(FAILED_RUN_GOAL)})
    && document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes(${JSON.stringify(FAILED_RUN_ERROR)})
  ), 'failed Chat message Run Detail handoff');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const failedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.failed');
    return events.length === 3
      && eventTypes.includes('agent.run.started')
      && eventTypes.includes('model.request.failed')
      && eventTypes.includes('agent.run.failed')
      && sequences.join(',') === '1,2,3'
      && runIds.every((id) => id === ${JSON.stringify(FAILED_RUN_ID)})
      && failedEvent?.textContent.includes(${JSON.stringify(FAILED_RUN_ERROR)});
  }, 'failed Run Detail replay events');
  console.log('[electron-smoke] failed Chat message opened matching Run Detail');
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat');
  await waitFor(win, () => {
    const completedArticle = document.querySelector('[data-message-id="${COMPLETED_MESSAGE_ID}"]');
    return completedArticle?.querySelector('[data-testid="chat-message-open-run-detail"]') == null
      && document.querySelector('[data-testid="chat-message-copy"]')
      && document.querySelector('[data-testid="chat-code-copy"]')
      && document.body.textContent.includes(${JSON.stringify(RUN_RESULT)});
  }, 'completed Chat message after failed Run Detail stays consumer-safe');
  await win.webContents.executeJavaScript(\`
  (() => {
    window.__ohaChatCopiedText = [];
    window.ohaDesktop = {
      ...(window.ohaDesktop || {}),
      copyText: async (text) => {
        window.__ohaChatCopiedText.push(text);
      },
    };
    const copyButtons = Array.from(document.querySelectorAll('[data-testid="chat-message-copy"]'));
    const assistantCopyButton = copyButtons.find((button) => button.closest('[data-message-id]')?.textContent.includes(${JSON.stringify(RUN_RESULT)}));
    assistantCopyButton.click();
  })();
  \`, true);
  await waitFor(win, () => (
    Array.isArray(window.__ohaChatCopiedText)
    && window.__ohaChatCopiedText[0] === ${JSON.stringify(ASSISTANT_CONTENT)}
    && document.querySelector('[data-testid="chat-message-copy"].copied')
  ), 'completed Chat message copied');
  console.log('[electron-smoke] completed Chat message copied');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-code-copy\\"]').click()", true);
  await waitFor(win, () => (
    Array.isArray(window.__ohaChatCopiedText)
    && window.__ohaChatCopiedText[1] === ${JSON.stringify(CODE_BLOCK)}
    && document.querySelector('[data-testid="chat-code-copy"].copied')
  ), 'completed Chat code block copied');
  console.log('[electron-smoke] completed Chat code block copied');
  await waitFor(win, () => (
    document.querySelector('[data-message-id="${COMPLETED_MESSAGE_ID}"] [data-testid="chat-message-open-run-detail"]') == null
  ), 'completed Chat message keeps Run Detail hidden');
  console.log('[electron-smoke] completed Chat message kept Run Detail hidden');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-run-detail-handoff-smoke-'));
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
  if (bridgeState.publicTaskPayloads.length !== 2) {
    throw new Error(`expected two public retry attempts, got ${bridgeState.publicTaskPayloads.length}`);
  }
  if (bridgeState.publicTaskPayloads.some((payload) => payload.prompt !== FAILED_USER_PROMPT)) {
    throw new Error(`failed retry used the wrong public prompt: ${JSON.stringify(bridgeState.publicTaskPayloads)}`);
  }
  const retryClientMessageIds = bridgeState.publicTaskPayloads.map((payload) => (
    String(payload.metadata?.client_message_id || '')
  ));
  if (
    retryClientMessageIds.some((clientMessageId) => (
      !clientMessageId || clientMessageId === FAILED_ORIGINAL_CLIENT_MESSAGE_ID
    ))
    || new Set(retryClientMessageIds).size !== retryClientMessageIds.length
  ) {
    throw new Error(`failed retry did not use fresh client message ids: ${JSON.stringify(retryClientMessageIds)}`);
  }
  if (bridgeState.retryPayloads.length !== 2) {
    throw new Error(`expected two failed message retry requests, got ${bridgeState.retryPayloads.length}`);
  }
  if (bridgeState.retryPayloads.some((payload) => payload.message_id !== FAILED_MESSAGE_ID)) {
    throw new Error(`unexpected retry message_id: ${JSON.stringify(bridgeState.retryPayloads)}`);
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
