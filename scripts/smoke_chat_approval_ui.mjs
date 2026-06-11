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
const SESSION_ID = 'chat_approval_ui_smoke_session';
const TASK_ID = 'task-chat-approval-ui-smoke';
const RUN_ID = 'main_chat_run_approval_ui_smoke';
const APPROVAL_ID = 'approval-chat-ui-smoke';
const APPROVAL_COMMAND = 'printf chat-approval-ui-smoke';
const now = new Date().toISOString();

const bridgeState = {
  status: 'pending',
  approveCalls: 0,
  rejectCalls: 0,
};

function log(message) {
  process.stdout.write(`[chat-approval-ui-smoke] ${message}\n`);
}

function fail(message) {
  throw new Error(message);
}

function resetApproval() {
  bridgeState.status = 'pending';
}

function pendingApproval() {
  return {
    approval_id: APPROVAL_ID,
    tool: 'terminal.run',
    input_preview: {
      command: APPROVAL_COMMAND,
      cwd: '/workspace',
      checkpoint: 'Chat approval UI smoke',
    },
  };
}

function runPayload() {
  const completed = bridgeState.status === 'approved';
  const rejected = bridgeState.status === 'rejected';
  return {
    run_id: RUN_ID,
    kind: 'main_chat_run',
    status: completed ? 'completed' : rejected ? 'cancelled' : 'approval_required',
    session_id: SESSION_ID,
    task_id: TASK_ID,
    task_run_link_run_status: completed ? 'completed' : rejected ? 'cancelled' : 'approval_required',
    task_run_link_last_event_sequence: completed ? 4 : rejected ? 3 : 1,
    pending_approval: bridgeState.status === 'pending' ? pendingApproval() : {},
    result: completed
      ? 'Approved from Chat approval UI smoke.'
      : rejected
        ? 'Rejected from chat'
        : '',
    timeline: bridgeState.status === 'pending'
      ? [{ event: 'agent.tool.approval_required', status: 'approval_required', tool: 'terminal.run' }]
      : completed
        ? [
            { event: 'agent.tool.approval_approved', status: 'running', tool: 'terminal.run' },
            { event: 'agent.tool.call', status: 'completed', tool: 'terminal.run' },
            { event: 'run.completed', status: 'completed' },
          ]
        : [
            { event: 'agent.tool.approval_rejected', status: 'cancelled', tool: 'terminal.run' },
            { event: 'agent.run.cancelled', status: 'cancelled' },
          ],
    created_at: now,
    updated_at: now,
  };
}

function assistantMessage() {
  if (bridgeState.status === 'approved') {
    return {
      id: 'assistant-chat-approval-ui-smoke-approved',
      role: 'assistant',
      content: 'Approved from Chat approval UI smoke.',
      status: 'completed',
      created_at: now,
      metadata: {
        task_id: TASK_ID,
        run_id: RUN_ID,
        run_status: 'completed',
        pending_approval: {},
      },
    };
  }
  if (bridgeState.status === 'rejected') {
    return {
      id: 'assistant-chat-approval-ui-smoke-rejected',
      role: 'assistant',
      content: 'Rejected from chat',
      status: 'failed',
      error: 'Rejected from chat',
      created_at: now,
      metadata: {
        task_id: TASK_ID,
        run_id: RUN_ID,
        run_status: 'cancelled',
        pending_approval: {},
      },
    };
  }
  return {
    id: 'assistant-chat-approval-ui-smoke-pending',
    role: 'assistant',
    content: '',
    status: 'processing',
    created_at: now,
    metadata: {
      task_id: TASK_ID,
      run_id: RUN_ID,
      run_status: 'approval_required',
      pending_approval: pendingApproval(),
      sender: { kind: 'assistant', name: 'Oha-Yachiyo' },
      delegated_goal: 'Approve the Chat approval UI smoke tool request.',
    },
  };
}

function messagesPayload() {
  const pending = bridgeState.status === 'pending';
  return {
    ok: true,
    session_id: SESSION_ID,
    messages: [
      {
        id: 'user-chat-approval-ui-smoke',
        role: 'user',
        content: 'Trigger a Chat approval UI smoke.',
        status: 'completed',
        created_at: now,
        metadata: { task_id: TASK_ID },
      },
      assistantMessage(),
    ],
    session_context: { conversation_kind: 'main' },
    is_processing: pending,
    processing_count: pending ? 1 : 0,
    approval_count: pending ? 1 : 0,
    token_count: 0,
  };
}

function sessionsPayload() {
  const pending = bridgeState.status === 'pending';
  return {
    ok: true,
    current_session_id: SESSION_ID,
    sessions: [
      {
        session_id: SESSION_ID,
        title: 'Chat approval UI smoke',
        conversation_kind: 'main',
        message_count: 2,
        token_count: 0,
        is_processing: pending,
        processing_count: pending ? 1 : 0,
        latest_message_preview: bridgeState.status === 'approved'
          ? 'Approved from Chat approval UI smoke.'
          : bridgeState.status === 'rejected'
            ? 'Rejected from chat'
            : 'Waiting for tool approval',
        latest_message_status: bridgeState.status === 'approved'
          ? 'completed'
          : bridgeState.status === 'rejected'
            ? 'failed'
            : 'processing',
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
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, runPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${RUN_ID}/approval/approve`) {
        bridgeState.status = 'approved';
        bridgeState.approveCalls += 1;
        log(`mock bridge approved chat approval (${bridgeState.approveCalls})`);
        sendJson(response, 200, runPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${RUN_ID}/approval/reject`) {
        bridgeState.status = 'rejected';
        bridgeState.rejectCalls += 1;
        log(`mock bridge rejected chat approval (${bridgeState.rejectCalls})`);
        sendJson(response, 200, runPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/reset') {
        resetApproval();
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
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-approval-smoke-'));
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const chatUrl = devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat';
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 35000);
function waitFor(win, predicate, label, timeout = 18000) {
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
              approvalCard: document.querySelector('[data-testid="chat-message-approval-card"]')?.outerHTML || '',
              composerNotice: document.querySelector('[data-testid="chat-composer-approval-notice"]')?.outerHTML || '',
              messages: Array.from(document.querySelectorAll('[data-message-id]')).map((node) => ({
                id: node.getAttribute('data-message-id'),
                className: node.className,
                text: node.textContent.slice(0, 260),
              })),
              bodyText: document.body.textContent.slice(-1400),
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
async function waitForApproval(win, label) {
  await waitFor(win, () => {
    const card = document.querySelector('[data-testid="chat-message-approval-card"]');
    const actions = document.querySelector('[data-testid="chat-message-approval-actions"]');
    const composer = document.querySelector('[data-testid="chat-composer-approval-notice"]');
    const approve = document.querySelector('[data-testid="chat-message-approval-approve"]');
    const reject = document.querySelector('[data-testid="chat-message-approval-reject"]');
    const composerApprove = document.querySelector('[data-testid="chat-composer-approval-approve"]');
    const composerReject = document.querySelector('[data-testid="chat-composer-approval-reject"]');
    return document.querySelector('textarea.chat-input')
      && card?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && card?.getAttribute('data-approval-id') === ${JSON.stringify(APPROVAL_ID)}
      && card?.getAttribute('data-approval-tool') === 'terminal.run'
      && card.textContent.includes(${JSON.stringify(APPROVAL_COMMAND)})
      && actions?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && approve
      && reject
      && composer?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && composer?.getAttribute('data-approval-id') === ${JSON.stringify(APPROVAL_ID)}
      && composerApprove
      && composerReject;
  }, label);
}
async function waitForApproved(win, label) {
  await waitFor(win, () => {
    const approved = document.querySelector('[data-message-id="assistant-chat-approval-ui-smoke-approved"]');
    return approved?.textContent.includes('Approved from Chat approval UI smoke.')
      && !document.querySelector('[data-testid="chat-message-approval-card"]')
      && !document.querySelector('[data-testid="chat-composer-approval-notice"]');
  }, label);
}
async function waitForRejected(win, label) {
  await waitFor(win, () => {
    const rejected = document.querySelector('[data-message-id="assistant-chat-approval-ui-smoke-rejected"]');
    return rejected?.className.includes('error')
      && rejected?.textContent.includes('Rejected from chat')
      && !document.querySelector('[data-testid="chat-message-approval-card"]')
      && !document.querySelector('[data-testid="chat-composer-approval-notice"]');
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
  console.log('[electron-smoke] chat loaded for message approval');
  await waitForApproval(win, 'message approval card and composer notice');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-message-approval-approve\\"]').click()", true);
  await waitForApproved(win, 'message approval approve projection');
  console.log('[electron-smoke] message approval approved');

  await win.webContents.executeJavaScript("fetch(" + JSON.stringify(bridgeUrl + '/__smoke/reset') + ", { method: 'POST' })", true);
  await win.loadURL('about:blank');
  await win.loadURL(chatUrl);
  console.log('[electron-smoke] chat loaded for composer reject');
  await waitForApproval(win, 'composer approval notice after reset');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-approval-reject\\"]').click()", true);
  await waitForRejected(win, 'composer approval reject projection');
  console.log('[electron-smoke] composer approval rejected');

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
    }, 50_000);
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
    if (bridgeState.approveCalls !== 1) {
      fail(`expected one chat approval approve call, got ${bridgeState.approveCalls}`);
    }
    if (bridgeState.rejectCalls !== 1) {
      fail(`expected one chat approval reject call, got ${bridgeState.rejectCalls}`);
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
