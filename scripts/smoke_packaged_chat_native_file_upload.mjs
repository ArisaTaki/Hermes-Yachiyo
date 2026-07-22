#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_TIMEOUT_MS = 60_000;
const SESSION_ID = 'session-packaged-chat-native-file-smoke';
const TASK_ID = 'task-packaged-chat-native-file-smoke';
const RUN_ID = 'main_chat_run_packaged_native_file_smoke';
const RUN_GROUP_ID = 'group-packaged-chat-native-file-smoke';
const RUN_GOAL = 'packaged native file upload smoke';
const RUN_RESULT = 'Packaged native file upload smoke reply saw the selected image.';
const MESSAGE_TEXT = 'packaged native file upload smoke';
const INTERNAL_ACTIVITY_TEXT = 'PACKAGED_CHAT_INTERNAL_ACTIVITY_SENTINEL';
const INTERNAL_TOOL_NAME = 'internal.packaged_chat_tool_sentinel';
const INTERNAL_RECOVERY_TEXT = 'PACKAGED_CHAT_INTERNAL_RECOVERY_SENTINEL';
const IMAGE_NAME = 'packaged-native-picker-smoke.svg';
const IMAGE_DATA = Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#0f766e"/><circle cx="12" cy="12" r="7" fill="#ffffff"/></svg>',
);
const IMAGE_DATA_URL = `data:image/svg+xml;base64,${IMAGE_DATA.toString('base64')}`;

const bridgeState = {
  messages: [],
  postPayloads: [],
};

function parseArgs(argv) {
  const args = {
    appExecutable: '',
    appCwd: '',
    timeoutMs: DEFAULT_TIMEOUT_MS,
    reportJson: '',
    processLedgerJson: '',
    smokeRoot: '',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--app-executable') args.appExecutable = argv[++index] || '';
    else if (arg === '--app-cwd') args.appCwd = argv[++index] || '';
    else if (arg === '--timeout-ms') args.timeoutMs = Number(argv[++index] || DEFAULT_TIMEOUT_MS);
    else if (arg === '--report-json') args.reportJson = argv[++index] || '';
    else if (arg === '--process-ledger-json') args.processLedgerJson = argv[++index] || '';
    else if (arg === '--smoke-root') args.smokeRoot = argv[++index] || '';
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!args.appExecutable) throw new Error('--app-executable is required');
  if (!args.appCwd) throw new Error('--app-cwd is required');
  if (!Number.isFinite(args.timeoutMs) || args.timeoutMs <= 0) {
    throw new Error('--timeout-ms must be a positive number');
  }
  return args;
}

function log(message) {
  process.stdout.write(`[packaged-chat-native-file] ${message}\n`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function remainingDeadlineMs(deadline, label) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error(`global timeout waiting for ${label}`);
  return remaining;
}

async function withinDeadline(promise, deadline, label) {
  const remaining = remainingDeadlineMs(deadline, label);
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`global timeout waiting for ${label}`)), remaining);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function writeProcessLedger(ledgerPath, appProcess, executable, smokeRoot, cleaned) {
  if (!ledgerPath || !appProcess?.pid) return;
  const payload = {
    pid: appProcess.pid,
    pgid: process.platform === 'win32' ? null : appProcess.pid,
    executable: path.resolve(executable),
    smoke_root: path.resolve(smokeRoot),
    cleaned: Boolean(cleaned),
  };
  fs.mkdirSync(path.dirname(ledgerPath), { recursive: true });
  const temporaryPath = `${ledgerPath}.${process.pid}.tmp`;
  fs.writeFileSync(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  fs.renameSync(temporaryPath, ledgerPath);
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
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS,PATCH,DELETE',
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

function messagePayload() {
  return {
    ok: true,
    session_id: SESSION_ID,
    messages: bridgeState.messages,
    session_context: { conversation_kind: 'main' },
    is_processing: false,
    processing_count: 0,
    approval_count: 0,
    token_count: 0,
  };
}

function settingsPayload() {
  return {
    app: {
      start_minimized: false,
      tray_enabled: false,
    },
    display: {
      current_mode: 'none',
    },
    mode_settings: {
      bubble: { id: 'bubble', title: 'Bubble', config: {} },
      live2d: { id: 'live2d', title: 'Live2D', config: {} },
    },
    window_mode: {
      open_chat_on_start: false,
    },
  };
}

const now = new Date().toISOString();
const smokeRun = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'main_chat',
  task_id: TASK_ID,
  session_id: SESSION_ID,
  task_run_link_run_status: 'completed',
  task_run_link_last_event_sequence: 5,
  kind: 'main_chat_run',
  runnable_id: 'builtin:yachiyo-main',
  runnable_name: 'Oha-Yachiyo',
  status: 'completed',
  user_goal: RUN_GOAL,
  result: RUN_RESULT,
  timeline: [
    { event: 'agent.activity.internal', status: 'completed', detail: INTERNAL_ACTIVITY_TEXT },
    { event: 'agent.tool.call', status: 'completed', tool_name: INTERNAL_TOOL_NAME },
    { event: 'agent.replan.recovery.updated', status: 'blocked', detail: INTERNAL_RECOVERY_TEXT },
    { event: 'model.output.completed', status: 'completed', output: RUN_RESULT },
    { event: 'run.completed', status: 'completed', result: RUN_RESULT },
  ],
  artifacts: [],
  created_at: now,
  updated_at: now,
};

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Packaged Chat Native File Upload Smoke',
  source: 'main_chat',
  status: 'completed',
  summary: RUN_RESULT,
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

const runEvents = [
  {
    event_id: 'event-packaged-chat-native-file-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'agent.activity.internal',
    actor: 'runtime',
    visibility: 'internal',
    sensitivity: 'normal',
    title: INTERNAL_ACTIVITY_TEXT,
    detail: INTERNAL_ACTIVITY_TEXT,
    payload: { activity: INTERNAL_ACTIVITY_TEXT },
    created_at: now,
  },
  {
    event_id: 'event-packaged-chat-native-file-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'agent.tool.call',
    actor: 'tool',
    visibility: 'internal',
    sensitivity: 'normal',
    title: INTERNAL_TOOL_NAME,
    detail: INTERNAL_TOOL_NAME,
    payload: { tool_name: INTERNAL_TOOL_NAME, tool_call_id: 'internal-tool-call-smoke' },
    created_at: now,
  },
  {
    event_id: 'event-packaged-chat-native-file-3',
    run_id: RUN_ID,
    sequence: 3,
    schema_version: 1,
    event_type: 'agent.replan.recovery.updated',
    actor: 'runtime',
    visibility: 'internal',
    sensitivity: 'normal',
    title: INTERNAL_RECOVERY_TEXT,
    detail: INTERNAL_RECOVERY_TEXT,
    payload: {
      request_id: 'internal-recovery-smoke',
      status: 'blocked',
      selected_tool_name: INTERNAL_TOOL_NAME,
      failure_detail: INTERNAL_RECOVERY_TEXT,
    },
    created_at: now,
  },
  {
    event_id: 'event-packaged-chat-native-file-4',
    run_id: RUN_ID,
    sequence: 4,
    schema_version: 1,
    event_type: 'model.output.completed',
    actor: 'model',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { output: RUN_RESULT },
    created_at: now,
  },
  {
    event_id: 'event-packaged-chat-native-file-5',
    run_id: RUN_ID,
    sequence: 5,
    schema_version: 1,
    event_type: 'run.completed',
    actor: 'runtime',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: RUN_RESULT },
    created_at: now,
  },
];

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
      if (request.method === 'GET' && url.pathname === '/ui/dashboard') {
        sendJson(response, 200, {
          assistant: {
            agent_name: 'Oha-Yachiyo',
            agent_nickname: 'Yachiyo',
            agent_avatar_url: '',
          },
          bridge: {
            status: 'running',
            url: 'mock-packaged-chat-native-file-bridge',
          },
          chat: {
            is_processing: false,
            processing_count: 0,
            approval_count: 0,
            current_session_id: SESSION_ID,
          },
          native_agent: {
            ready: true,
            readiness_level: 'ready',
          },
          activities: [],
          recent_tasks: [],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/settings') {
        sendJson(response, 200, settingsPayload());
        return;
      }
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
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [{ id: 'builtin:yachiyo-main', name: 'Oha-Yachiyo', kind: 'agent', enabled: true, output_contract: 'chat' }],
        });
        return;
      }
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
        sendJson(response, 200, { folders: [] });
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
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [smokeRun] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, smokeRun);
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
        sendJson(response, 200, {
          ok: true,
          current_session_id: SESSION_ID,
          sessions: [{ session_id: SESSION_ID, title: 'Packaged native file upload smoke', conversation_kind: 'main' }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        sendJson(response, 200, messagePayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages') {
        const body = await readRequestJson(request);
        bridgeState.postPayloads.push(body);
        const attachments = Array.isArray(body.attachments) ? body.attachments : [];
        bridgeState.messages = [
          {
            id: 'user-packaged-native-file-message',
            role: 'user',
            content: String(body.text || ''),
            status: 'completed',
            created_at: new Date().toISOString(),
            attachments: attachments.map((attachment, index) => ({
              id: attachment.id || `packaged-native-file-${index}`,
              kind: 'image',
              name: attachment.name || IMAGE_NAME,
              mime_type: attachment.mime_type || 'image/svg+xml',
              size: attachment.size || 0,
              url: attachment.data_url,
            })),
            metadata: {},
          },
          {
            id: 'assistant-packaged-native-file-smoke-reply',
            role: 'assistant',
            content: RUN_RESULT,
            status: 'completed',
            task_id: TASK_ID,
            created_at: new Date().toISOString(),
            activity_events: [
              {
                event_id: 'chat-internal-activity-smoke',
                tool_name: INTERNAL_TOOL_NAME,
                phase: 'agent.tool.call',
                title: INTERNAL_ACTIVITY_TEXT,
                detail: INTERNAL_TOOL_NAME,
                status: 'completed',
                visibility: 'internal',
                metadata: {
                  run_id: RUN_ID,
                  tool_call_id: 'internal-tool-call-smoke',
                  recovery_actions: [
                    {
                      action_kind: 'runtime_observation_retry',
                      tool: INTERNAL_TOOL_NAME,
                      label: INTERNAL_RECOVERY_TEXT,
                    },
                  ],
                },
              },
            ],
            metadata: {
              task_id: TASK_ID,
              run_id: RUN_ID,
              run_status: 'completed',
              runnable_id: 'builtin:yachiyo-main',
              runnable_kind: 'agent',
              run_group_id: RUN_GROUP_ID,
              source: 'main_chat',
              replan_recoveries: [
                {
                  request_id: 'internal-recovery-smoke',
                  trigger: 'tool_failure',
                  status: 'blocked',
                  run_id: RUN_ID,
                  task_id: TASK_ID,
                  selected_tool_name: INTERNAL_TOOL_NAME,
                  failure_detail: INTERNAL_RECOVERY_TEXT,
                  recovery_actions: [],
                },
              ],
            },
          },
        ];
        sendJson(response, 200, { ok: true, task_id: TASK_ID, run_id: RUN_ID, run_status: 'completed' });
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

async function waitForPageTarget(debugPort, deadline) {
  let lastError = '';
  while (Date.now() < deadline) {
    try {
      const response = await withinDeadline(
        fetch(`http://127.0.0.1:${debugPort}/json/list`),
        deadline,
        'packaged DevTools page target',
      );
      if (!response.ok) throw new Error(`DevTools /json/list returned ${response.status}`);
      const targets = await response.json();
      const page = targets.find((target) => (
        target
        && target.type === 'page'
        && target.webSocketDebuggerUrl
        && !String(target.url || '').startsWith('devtools://')
      ));
      if (page) return page;
      lastError = 'no page target exposed yet';
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(Math.min(250, Math.max(1, deadline - Date.now())));
  }
  throw new Error(`packaged app did not expose a DevTools page target: ${lastError}`);
}

class CdpClient {
  constructor(webSocketDebuggerUrl) {
    if (typeof WebSocket !== 'function') {
      throw new Error('Node.js WebSocket global is unavailable; use Node 20.19+');
    }
    this.nextId = 1;
    this.pending = new Map();
    this.ws = new WebSocket(webSocketDebuggerUrl);
    this.ready = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', () => reject(new Error('DevTools websocket failed to open')), { once: true });
    });
    this.ws.addEventListener('message', (event) => this.handleMessage(event.data));
    this.ws.addEventListener('close', () => {
      for (const { reject } of this.pending.values()) reject(new Error('DevTools websocket closed'));
      this.pending.clear();
    });
  }

  handleMessage(data) {
    const text = typeof data === 'string' ? data : Buffer.from(data).toString('utf8');
    let message;
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }
    if (!message.id || !this.pending.has(message.id)) return;
    const { resolve, reject } = this.pending.get(message.id);
    this.pending.delete(message.id);
    if (message.error) reject(new Error(`${message.error.message || 'CDP error'} (${message.error.code || 'unknown'})`));
    else resolve(message.result || {});
  }

  async send(method, params = {}) {
    await this.ready;
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(payload);
    });
  }

  close() {
    this.ws.close();
  }
}

async function evaluate(client, expression, deadline, label = 'DevTools evaluation') {
  const result = await withinDeadline(client.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  }), deadline, label);
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.text || result.exceptionDetails.exception?.description || 'unknown exception';
    throw new Error(`Runtime.evaluate failed: ${detail}`);
  }
  return result.result?.value;
}

async function waitForDocumentReady(client, deadline) {
  await evaluate(client, `
    new Promise((resolve) => {
      if (document.readyState !== 'loading') resolve(document.readyState);
      else window.addEventListener('DOMContentLoaded', () => resolve(document.readyState), { once: true });
      setTimeout(() => resolve(document.readyState), ${Math.max(1, deadline - Date.now())});
    })
  `, deadline, 'packaged document readiness');
}

async function navigateToChat(client, deadline) {
  await waitFor(client, `
    (() => {
      if (document.querySelector('textarea.chat-input')) return true;
      const navButtons = Array.from(document.querySelectorAll('.hy-nav button'));
      const chatButton = navButtons.find((button) => button.textContent.trim() === '对话');
      if (chatButton) {
        const now = Date.now();
        if (!window.__packagedChatSmokeLastChatNavClick || now - window.__packagedChatSmokeLastChatNavClick > 500) {
          window.__packagedChatSmokeLastChatNavClick = now;
          chatButton.click();
        }
      } else if (window.location.hash !== '#/chat') {
        window.history.pushState(null, '', '#/chat');
        window.dispatchEvent(new Event('oha-route-change'));
        window.dispatchEvent(new HashChangeEvent('hashchange'));
      }
      return Boolean(document.querySelector('textarea.chat-input'));
    })()
  `, 'packaged chat route navigation', deadline);
}

async function waitFor(client, predicateExpression, label, deadline) {
  let debug = '';
  while (Date.now() < deadline) {
    try {
      const result = await evaluate(client, predicateExpression, deadline, label);
      if (result) return result;
    } catch (error) {
      debug = error instanceof Error ? error.message : String(error);
    }
    await sleep(Math.min(150, Math.max(1, deadline - Date.now())));
  }
  try {
    debug = await evaluate(client, `
      JSON.stringify({
        status: document.querySelector('.chat-status')?.textContent || '',
        previews: document.querySelectorAll('[data-testid="chat-composer-attachment-preview"]').length,
        messageAttachments: document.querySelectorAll('[data-testid="chat-message-attachment-item"]').length,
        hash: window.location.hash,
        navButtons: Array.from(document.querySelectorAll('.hy-nav button')).map((button) => button.textContent.trim()).filter(Boolean).slice(0, 12),
        bodyText: document.body.textContent.slice(-1000),
      })
    `, deadline, `${label} diagnostics`);
  } catch {}
  throw new Error(`timeout waiting for ${label}${debug ? `: ${debug}` : ''}`);
}

function processTreeAlive(child) {
  if (!child) return false;
  if (process.platform !== 'win32' && child.pid) {
    try {
      process.kill(-child.pid, 0);
      return true;
    } catch (error) {
      if (error && error.code === 'EPERM') return true;
      return false;
    }
  }
  return child.exitCode === null && child.signalCode === null;
}

async function waitForProcessTreeExit(child, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!processTreeAlive(child)) return true;
    await sleep(50);
  }
  return !processTreeAlive(child);
}

function signalProcessTree(child, signal) {
  if (!child || !processTreeAlive(child)) return;
  try {
    if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal);
    else child.kill(signal);
  } catch {}
}

async function terminateProcess(child) {
  if (!child || !processTreeAlive(child)) return;
  signalProcessTree(child, 'SIGTERM');
  if (await waitForProcessTreeExit(child, 3000)) return;
  signalProcessTree(child, 'SIGKILL');
  if (await waitForProcessTreeExit(child, 3000)) return;
  throw new Error(`packaged app process tree ${child.pid || 'unknown'} did not exit after SIGKILL`);
}

async function runPackagedChatSmoke(client, deadline) {
  await waitForDocumentReady(client, deadline);
  await navigateToChat(client, deadline);
  await waitFor(client, `
    (() => (
      document.querySelector('textarea.chat-input')
      && !document.querySelector('.chat-loading-state')
      && typeof window.ohaDesktop?.chooseChatImages === 'function'
      && !document.querySelector('[data-testid="chat-composer-image-attach-button"]')?.disabled
    ))()
  `, 'packaged chat composer readiness', deadline);
  log('packaged chat composer ready');

  await evaluate(client, `
    (() => {
      const input = document.querySelector('[data-testid="chat-image-file-input"]');
      const button = document.querySelector('[data-testid="chat-composer-image-attach-button"]');
      if (!input || !button) throw new Error('chat native file smoke controls not found');
      window.__chatNativeHiddenInputClickCount = 0;
      const hadOwnClick = Object.prototype.hasOwnProperty.call(input, 'click');
      const ownClick = hadOwnClick ? input.click : undefined;
      Object.defineProperty(input, 'click', { configurable: true, value: () => { window.__chatNativeHiddenInputClickCount += 1; } });
      button.click();
      setTimeout(() => {
        delete input.click;
        if (hadOwnClick) Object.defineProperty(input, 'click', { configurable: true, value: ownClick });
      }, 2500);
    })()
  `, deadline, 'open packaged native file picker');
  await waitFor(client, `
    (() => {
      const preview = document.querySelector('[data-testid="chat-composer-attachment-preview"]');
      return preview
        && window.__chatNativeHiddenInputClickCount === 0
        && preview.getAttribute('data-attachment-name') === ${JSON.stringify(IMAGE_NAME)}
        && preview.getAttribute('data-attachment-mime') === 'image/svg+xml'
        && Number(preview.getAttribute('data-attachment-size') || 0) > 0
        && preview.getAttribute('data-attachment-width') === '24'
        && preview.getAttribute('data-attachment-height') === '24';
    })()
  `, 'packaged native file preview', deadline);
  log('packaged native file preview rendered');

  await evaluate(client, `
    (() => {
      const input = document.querySelector('textarea.chat-input');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(MESSAGE_TEXT)});
      input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: ${JSON.stringify(MESSAGE_TEXT)} }));
    })()
  `, deadline, 'fill packaged Chat composer');
  await waitFor(client, `
    (() => !document.querySelector('button[aria-label="发送消息"]')?.disabled)()
  `, 'enabled send button', deadline);
  await evaluate(client, `
    document.querySelector('button[aria-label="发送消息"]').closest('form').requestSubmit()
  `, deadline, 'submit packaged Chat message');
  await waitFor(client, `
    (() => {
      const item = document.querySelector('[data-testid="chat-message-attachment-item"]');
      return item
        && item.getAttribute('data-attachment-name') === ${JSON.stringify(IMAGE_NAME)}
        && item.getAttribute('data-attachment-kind') === 'image'
        && item.getAttribute('data-attachment-mime') === 'image/svg+xml'
        && Number(item.getAttribute('data-attachment-size') || 0) > 0
        && !document.querySelector('[data-testid="chat-composer-attachment-preview"]')
        && document.querySelector('textarea.chat-input')?.value === '';
    })()
  `, 'packaged message attachment render', deadline);
  log('packaged message attachment rendered');

  await evaluate(
    client,
    `document.querySelector('[data-testid="chat-message-attachment-item"]').click()`,
    deadline,
    'open packaged image viewer',
  );
  await waitFor(client, `
    (() => {
      const modal = document.querySelector('[data-testid="chat-image-viewer-modal"]');
      const image = document.querySelector('[data-testid="chat-image-viewer-stage"] img');
      return modal
        && image?.getAttribute('alt') === ${JSON.stringify(IMAGE_NAME)}
        && image?.getAttribute('src')?.startsWith('data:image/svg+xml');
    })()
  `, 'packaged image viewer modal', deadline);
  log('packaged image viewer opened');
  await evaluate(
    client,
    `document.querySelector('[data-testid="chat-image-viewer-close"]').click()`,
    deadline,
    'close packaged image viewer',
  );
  await waitFor(client, `
    (() => (
      !document.querySelector('[data-testid="chat-image-viewer-backdrop"]')
      && !document.querySelector('[data-testid="chat-image-viewer-modal"]')
      && !document.querySelector('[data-testid="chat-image-viewer-stage"]')
    ))()
  `, 'closed packaged image viewer modal', deadline);

  await waitFor(client, `
    (() => {
      const reply = document.querySelector('[data-message-id="assistant-packaged-native-file-smoke-reply"]');
      const openRun = reply?.querySelector('[data-testid="chat-message-open-run-detail"]');
      const forbiddenSelectors = [
        '[data-testid="chat-message-activity-list"]',
        '[data-testid="chat-message-activity-row"]',
        '[data-testid="yachiyo-agent-task-card"]',
        '[data-testid="yachiyo-agent-task-runtime-details"]',
        '[data-testid="yachiyo-agent-task-canonical-recovery"]',
        '[data-testid="yachiyo-agent-task-recovery-statuses"]',
        '.message-activity-row.failed',
        '.yachiyo-agent-task-planner-chip.missing',
        '[data-summary-tone="warning"]',
      ];
      const pageText = document.body.textContent || '';
      return reply?.textContent.includes(${JSON.stringify(RUN_RESULT)})
        && !reply.textContent.includes(${JSON.stringify(INTERNAL_ACTIVITY_TEXT)})
        && !reply.textContent.includes(${JSON.stringify(INTERNAL_TOOL_NAME)})
        && !reply.textContent.includes(${JSON.stringify(INTERNAL_RECOVERY_TEXT)})
        && !pageText.includes(${JSON.stringify(INTERNAL_ACTIVITY_TEXT)})
        && !pageText.includes(${JSON.stringify(INTERNAL_TOOL_NAME)})
        && !pageText.includes(${JSON.stringify(INTERNAL_RECOVERY_TEXT)})
        && forbiddenSelectors.every((selector) => !document.querySelector(selector))
        && !openRun;
    })()
  `, 'packaged native file assistant reply with hidden internal execution', deadline);
  log('packaged native file assistant reply verified without Chat internal execution');
  await evaluate(client, `
    (() => {
      const route = ${JSON.stringify(`#/agents/${RUN_ID}`)};
      window.history.pushState(null, '', route);
      window.dispatchEvent(new Event('oha-route-change'));
      return window.location.hash;
    })()
  `, deadline, 'navigate directly to packaged Agent Studio replay');
  await waitFor(client, `
    (() => {
      const detail = document.querySelector('[data-testid="agent-run-detail"]');
      const result = document.querySelector('[data-testid="agent-run-detail-result"]');
      const task = document.querySelector('[data-testid="agent-run-detail-task"]');
      const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
      const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
      return window.location.hash.includes(${JSON.stringify(RUN_ID)})
        && detail?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
        && detail?.getAttribute('data-run-kind') === 'main_chat_run'
        && detail?.getAttribute('data-run-status') === 'completed'
        && detail?.getAttribute('data-task-id') === ${JSON.stringify(TASK_ID)}
        && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
        && task?.textContent.includes(${JSON.stringify(RUN_GOAL)})
        && result?.textContent.includes(${JSON.stringify(RUN_RESULT)})
        && events.length === 5
        && eventTypes.includes('agent.activity.internal')
        && eventTypes.includes('agent.tool.call')
        && eventTypes.includes('agent.replan.recovery.updated')
        && eventTypes.includes('model.output.completed')
        && eventTypes.includes('run.completed')
        && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(RUN_ID)});
    })()
  `, 'packaged native file Agent Studio replay through direct route', deadline);
  log('packaged native file Agent Studio replay verified through direct route');
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const systemTempRoot = path.resolve(os.tmpdir());
  const requestedSmokeRoot = args.smokeRoot ? path.resolve(args.smokeRoot) : '';
  if (
    requestedSmokeRoot
    && (
      requestedSmokeRoot === systemTempRoot
      || !requestedSmokeRoot.startsWith(`${systemTempRoot}${path.sep}`)
    )
  ) {
    throw new Error('--smoke-root must be a child of the system temporary directory');
  }
  const tempDir = args.smokeRoot
    ? requestedSmokeRoot
    : fs.mkdtempSync(path.join(os.tmpdir(), 'oha-packaged-chat-native-file-'));
  const homeDir = path.join(tempDir, 'home');
  const ohaHome = path.join(homeDir, '.oha-yachiyo');
  const electronSmokeRoot = path.join(tempDir, 'electron-smoke-root');
  const imagePath = path.join(tempDir, IMAGE_NAME);
  fs.mkdirSync(tempDir, { recursive: true });
  fs.mkdirSync(homeDir, { recursive: true });
  fs.mkdirSync(electronSmokeRoot, { recursive: true });
  fs.writeFileSync(imagePath, IMAGE_DATA);

  const bridge = await startMockBridge();
  const debugPort = await pickPort();
  const deadline = Date.now() + args.timeoutMs;
  let appProcess;
  let client;
  try {
    appProcess = spawn(
      args.appExecutable,
      [`--remote-debugging-port=${debugPort}`, '--remote-allow-origins=*'],
      {
        cwd: args.appCwd,
        detached: process.platform !== 'win32',
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          HOME: homeDir,
          OHA_YACHIYO_HOME: ohaHome,
          OHA_YACHIYO_BRIDGE_URL: bridge.url,
          OHA_YACHIYO_SKIP_BACKEND: '1',
          OHA_YACHIYO_DESKTOP_SMOKE_MODE: '1',
          OHA_YACHIYO_ELECTRON_SMOKE_ROOT: electronSmokeRoot,
          OHA_YACHIYO_CHAT_IMAGE_PICKER_SMOKE_PATHS: JSON.stringify([imagePath]),
        },
      },
    );
    writeProcessLedger(
      args.processLedgerJson,
      appProcess,
      args.appExecutable,
      tempDir,
      false,
    );
    appProcess.stdout.on('data', (chunk) => process.stdout.write(chunk));
    appProcess.stderr.on('data', (chunk) => process.stderr.write(chunk));
    const target = await waitForPageTarget(debugPort, deadline);
    client = new CdpClient(target.webSocketDebuggerUrl);
    await withinDeadline(client.send('Page.enable'), deadline, 'enable packaged page domain');
    await withinDeadline(client.send('Runtime.enable'), deadline, 'enable packaged runtime domain');
    await runPackagedChatSmoke(client, deadline);
    const appBuildMetadata = await evaluate(client, `
      (async () => {
        const info = await window.ohaDesktop?.getAppUpdateInfo?.();
        return info?.current || null;
      })()
    `, deadline, 'read packaged app build metadata');
    if (!appBuildMetadata || typeof appBuildMetadata !== 'object') {
      throw new Error('packaged app build metadata is unavailable');
    }
    if (typeof appBuildMetadata.commit !== 'string' || !appBuildMetadata.commit.trim()) {
      throw new Error('packaged app build metadata did not include commit');
    }

    const payload = bridgeState.postPayloads[0];
    if (!payload) throw new Error('packaged Chat UI did not send a message');
    if (payload.text !== MESSAGE_TEXT) throw new Error(`unexpected submitted text: ${payload.text}`);
    if (!payload.client_message_id) throw new Error('packaged Chat UI did not submit client_message_id');
    if (!Array.isArray(payload.attachments) || payload.attachments.length !== 1) {
      throw new Error(`packaged Chat UI submitted unexpected attachments: ${JSON.stringify(payload.attachments)}`);
    }
    const attachment = payload.attachments[0];
    if (attachment.name !== IMAGE_NAME) throw new Error(`unexpected attachment name: ${attachment.name}`);
    if (attachment.mime_type !== 'image/svg+xml') throw new Error(`unexpected attachment mime: ${attachment.mime_type}`);
    if (!(Number(attachment.size) > 0)) throw new Error(`unexpected attachment size: ${attachment.size}`);
    if (attachment.width !== 24 || attachment.height !== 24) {
      throw new Error(`unexpected attachment dimensions: ${attachment.width}x${attachment.height}`);
    }
    if (!String(attachment.data_url || '').startsWith('data:image/svg+xml')) {
      throw new Error('submitted attachment did not include an image data URL');
    }

    const report = {
      ok: true,
      selected_file_name: IMAGE_NAME,
      selected_file_count: 1,
      submitted_text: MESSAGE_TEXT,
      submitted_attachment_count: 1,
      run_id: RUN_ID,
      task_id: TASK_ID,
      image_viewer_verified: true,
      run_detail_verified: true,
      chat_technical_action_hidden: true,
      internal_execution_hidden: true,
      run_detail_navigation_source: 'direct_agent_studio_route',
      desktop_picker_ipc_verified: true,
      hidden_file_input_click_count: 0,
      app_build_metadata: appBuildMetadata,
    };
    if (args.reportJson) {
      fs.mkdirSync(path.dirname(args.reportJson), { recursive: true });
      fs.writeFileSync(args.reportJson, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    }
    log('passed');
  } finally {
    if (client) client.close();
    try {
      await terminateProcess(appProcess);
      writeProcessLedger(
        args.processLedgerJson,
        appProcess,
        args.appExecutable,
        tempDir,
        true,
      );
    } finally {
      await new Promise((resolve) => bridge.server.close(resolve));
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  }
}

run().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
