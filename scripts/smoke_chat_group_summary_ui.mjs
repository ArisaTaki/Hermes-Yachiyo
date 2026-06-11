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
const MAIN_SESSION_ID = 'chat_group_ui_smoke_main';
const GROUP_SESSION_ID = 'chat_group_ui_smoke_group';
const AGENT_ID = 'chat-group-ui-agent';
const GROUP_NAME = 'Chat Group UI Smoke';
const GROUP_GOAL = 'Coordinate the group UI smoke';
const RUN_GROUP_ID = 'run_group_chat_group_ui_smoke';
const SUMMARY_TASK_ID = 'task-chat-group-summary-ui-smoke';
const now = new Date().toISOString();

const bridgeState = {
  currentSessionId: MAIN_SESSION_ID,
  groupCreated: false,
  groupCreatePayload: null,
  messagePayload: null,
  messagesBySession: new Map([[MAIN_SESSION_ID, []]]),
};

const agentRunnable = {
  id: AGENT_ID,
  name: 'Group UI Agent',
  nickname: 'Group Agent',
  kind: 'agent',
  enabled: true,
  output_contract: 'report',
  tool_policy: {
    allowed_tools: ['workspace.read'],
    approval_required: {},
  },
};

const groupParticipants = [
  { kind: 'main', name: 'Oha-Yachiyo', nickname: 'Yachiyo' },
  { kind: 'agent', id: AGENT_ID, name: agentRunnable.name, nickname: agentRunnable.nickname },
];

function log(message) {
  process.stdout.write(`[chat-group-summary-ui-smoke] ${message}\n`);
}

function groupSessionContext() {
  return {
    conversation_kind: 'group',
    runnable_id: GROUP_SESSION_ID,
    runnable_name: GROUP_NAME,
    run_group_id: RUN_GROUP_ID,
    participants: groupParticipants,
  };
}

function sessionsPayload() {
  const sessions = [
    {
      session_id: MAIN_SESSION_ID,
      title: 'Main chat',
      conversation_kind: 'main',
      message_count: 0,
      token_count: 0,
      updated_at: now,
    },
  ];
  if (bridgeState.groupCreated) {
    sessions.unshift({
      session_id: GROUP_SESSION_ID,
      title: GROUP_NAME,
      conversation_kind: 'group',
      runnable_id: GROUP_SESSION_ID,
      runnable_name: GROUP_NAME,
      run_group_id: RUN_GROUP_ID,
      participants: groupParticipants,
      message_count: bridgeState.messagesBySession.get(GROUP_SESSION_ID)?.length || 0,
      token_count: 0,
      is_processing: false,
      processing_count: 0,
      latest_message_preview: bridgeState.messagePayload ? 'Waiting for main model summary' : '',
      updated_at: now,
    });
  }
  return {
    ok: true,
    current_session_id: bridgeState.currentSessionId,
    sessions,
  };
}

function messagesPayload() {
  const messages = bridgeState.messagesBySession.get(bridgeState.currentSessionId) || [];
  const isGroup = bridgeState.currentSessionId === GROUP_SESSION_ID;
  return {
    ok: true,
    session_id: bridgeState.currentSessionId,
    messages,
    session_context: isGroup ? groupSessionContext() : { conversation_kind: 'main' },
    is_processing: false,
    processing_count: 0,
    approval_count: 0,
    token_count: 0,
  };
}

function createGroupMessages(text) {
  return [
    {
      id: 'chat-group-ui-user-message',
      role: 'user',
      content: text,
      status: 'completed',
      created_at: now,
      metadata: {
        sender: { kind: 'main', name: 'Oha-Yachiyo', nickname: 'Yachiyo' },
        target: { kind: 'group', id: GROUP_SESSION_ID, name: GROUP_NAME },
      },
    },
    {
      id: 'chat-group-ui-agent-summary-message',
      role: 'assistant',
      content: 'Group UI Agent accepted the task and returned a draft result.',
      status: 'processing',
      created_at: now,
      metadata: {
        sender: { kind: 'agent', id: AGENT_ID, name: agentRunnable.name, nickname: agentRunnable.nickname },
        target: { kind: 'group', id: GROUP_SESSION_ID, name: GROUP_NAME },
        runnable_kind: 'agent',
        runnable_id: AGENT_ID,
        run_group_id: RUN_GROUP_ID,
        group_goal: text,
        group_dispatch_count: 1,
        group_dispatch_run_group_id: RUN_GROUP_ID,
        group_agent_summary_task_id: SUMMARY_TASK_ID,
        group_agent_summary_pending: true,
        group_agent_summary_status: 'processing',
      },
      activity_events: [
        {
          event_id: 'activity-chat-group-ui-smoke',
          task_id: 'task-chat-group-agent-ui-smoke',
          title: 'Group UI Agent',
          detail: 'NativeRunEngine group dispatch is linked to this RunGroup.',
          status: 'completed',
          metadata: {
            run_group_id: RUN_GROUP_ID,
            run_status: 'completed',
          },
          created_at: now,
        },
      ],
    },
  ];
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
        sendJson(response, 200, {
          ok: true,
          agent_name: 'Oha-Yachiyo',
          agent_nickname: 'Yachiyo',
          user_avatar_url: '',
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, { runnables: [agentRunnable] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        log(`mock bridge messages session=${bridgeState.currentSessionId} count=${(bridgeState.messagesBySession.get(bridgeState.currentSessionId) || []).length}`);
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/groups') {
        const body = await readRequestJson(request);
        bridgeState.groupCreatePayload = body;
        bridgeState.groupCreated = true;
        bridgeState.currentSessionId = GROUP_SESSION_ID;
        bridgeState.messagesBySession.set(GROUP_SESSION_ID, []);
        sendJson(response, 200, {
          ok: true,
          session_id: GROUP_SESSION_ID,
          session_context: groupSessionContext(),
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages') {
        const body = await readRequestJson(request);
        log(`mock bridge group message text=${JSON.stringify(body.text || '')}`);
        bridgeState.messagePayload = body;
        bridgeState.messagesBySession.set(GROUP_SESSION_ID, createGroupMessages(String(body.text || '')));
        sendJson(response, 200, {
          ok: true,
          task_id: SUMMARY_TASK_ID,
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/sessions/load') {
        const body = await readRequestJson(request);
        bridgeState.currentSessionId = String(body.session_id || bridgeState.currentSessionId);
        sendJson(response, 200, { ok: true, session_id: bridgeState.currentSessionId });
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
const groupName = ${JSON.stringify(GROUP_NAME)};
const groupGoal = ${JSON.stringify(GROUP_GOAL)};
const runGroupId = ${JSON.stringify(RUN_GROUP_ID)};
const summaryTaskId = ${JSON.stringify(SUMMARY_TASK_ID)};
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
              groupsTab: document.querySelector('[data-testid="chat-session-tab-groups"]')?.textContent || '',
              dialog: document.querySelector('[data-testid="chat-group-dialog"]')?.textContent || '',
              header: document.querySelector('.chat-header')?.textContent || '',
              messages: Array.from(document.querySelectorAll('[data-message-id]')).map((node) => ({
                id: node.getAttribute('data-message-id'),
                text: node.textContent,
              })),
              summary: Array.from(document.querySelectorAll('[data-testid="chat-message-summary-status"]')).map((node) => ({
                task: node.getAttribute('data-summary-task-id'),
                status: node.getAttribute('data-summary-status'),
                tone: node.getAttribute('data-summary-tone'),
                runGroup: node.getAttribute('data-run-group-id'),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat');
  console.log('[electron-smoke] chat loaded');
  await waitFor(win, () => document.querySelector('[data-testid="chat-session-tab-groups"]'), 'chat groups tab');
  await waitFor(win, () => document.querySelector('[data-testid="chat-composer-input"]'), 'chat composer input');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-groups\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="chat-session-tab-create"]')?.getAttribute('aria-label') === '创建群组', 'group create action');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-create\\"]').click()", true);
  await waitFor(win, () => Boolean(document.querySelector('[data-testid="chat-group-dialog"]')), 'group dialog');
  await win.webContents.executeJavaScript(\`
    (() => {
      const setNativeValue = (element, value) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
      };
      setNativeValue(document.querySelector('[data-testid="chat-group-name-input"]'), ${JSON.stringify(GROUP_NAME)});
      document.querySelector('[data-testid="chat-group-agent-member-checkbox"]').click();
    })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-group-dialog-submit"]')?.disabled, 'enabled group create');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-group-dialog-submit\\"]').click()", true);
  await waitFor(win, () => (
    !document.querySelector('[data-testid="chat-group-dialog"]')
    && document.querySelector('[data-testid="chat-group-settings"]')
    && document.querySelector('.chat-header')?.textContent.includes(${JSON.stringify(GROUP_NAME)})
  ), 'created group selected');
  await waitFor(win, () => (
    document.body.textContent.includes('发送消息开始对话')
    && !document.body.textContent.includes('正在加载对话')
  ), 'created group empty conversation settled');
  console.log('[electron-smoke] group created');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-composer-input"]');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, ${JSON.stringify(GROUP_GOAL)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-composer-send"]')?.disabled, 'enabled group send');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-send\\"]').click()", true);
  await waitFor(win, () => {
    const summary = document.querySelector('[data-testid="chat-message-summary-status"]');
    return summary
      && summary.getAttribute('data-summary-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}
      && summary.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && summary.getAttribute('data-summary-tone') === 'pending'
      && summary.getAttribute('data-summary-status') === 'processing'
      && summary.textContent.includes('Waiting') === false
      && document.body.textContent.includes('Group UI Agent accepted the task')
      && document.body.textContent.includes(${JSON.stringify(GROUP_GOAL)});
  }, 'group summary status');
  console.log('[electron-smoke] group summary rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-group-summary-smoke-'));
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
  const groupPayload = bridgeState.groupCreatePayload;
  if (!groupPayload) throw new Error('group was not created');
  if (groupPayload.name !== GROUP_NAME) throw new Error(`unexpected group name: ${groupPayload.name}`);
  const participantIds = Array.isArray(groupPayload.participant_ids) ? groupPayload.participant_ids : [];
  if (participantIds.length !== 1 || participantIds[0] !== AGENT_ID) {
    throw new Error(`unexpected group participants: ${JSON.stringify(participantIds)}`);
  }
  const messagePayload = bridgeState.messagePayload;
  if (!messagePayload) throw new Error('group message was not sent');
  if (messagePayload.text !== GROUP_GOAL) throw new Error(`unexpected group message text: ${messagePayload.text}`);
  if (!messagePayload.client_message_id) throw new Error('group message did not include client_message_id');
  if (Array.isArray(messagePayload.attachments) && messagePayload.attachments.length) {
    throw new Error('group message smoke unexpectedly sent attachments');
  }
  if (bridgeState.currentSessionId !== GROUP_SESSION_ID) {
    throw new Error(`message was sent outside the created group: ${bridgeState.currentSessionId}`);
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
