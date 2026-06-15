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

const GROUP_SESSION_ID = 'launcher_group_summary';
const DELEGATED_SESSION_ID = 'launcher_delegated_summary';
const GROUP_TASK_ID = 'launcher_group_summary_task';
const DELEGATED_TASK_ID = 'launcher_delegated_summary_task';
const BUBBLE_SUMMARY = 'Group summary: Design and Coding finished Native dispatch.';
const DELEGATED_SUMMARY = 'Delegated summary: Coding finished Native delegated run.';
const BUBBLE_QUICK_TEXT = 'Bubble quick input from launcher smoke';
const LIVE2D_REPLY = 'Live2D latest reply from launcher smoke';
const LIVE2D_QUICK_TEXT = 'Live2D quick input from launcher smoke';
const STATUS_LABEL = '2 recent sessions';
const now = new Date().toISOString();

const bridgeState = {
  ackPayloads: [],
  bubbleDefaultOpenBehavior: 'reply_bubble',
  live2dClickAction: 'toggle_reply',
  modeRequests: [],
  quickMessagePayload: null,
  quickMessagePayloads: [],
};

const recentSessions = [
  {
    session_id: GROUP_SESSION_ID,
    conversation_kind: 'group',
    title: 'Launcher Group',
    summary: BUBBLE_SUMMARY,
    latest_task_id: GROUP_TASK_ID,
    latest_status: 'completed',
    updated_at: now,
  },
  {
    session_id: DELEGATED_SESSION_ID,
    conversation_kind: 'agent',
    title: 'Delegated Agent',
    summary: DELEGATED_SUMMARY,
    latest_task_id: DELEGATED_TASK_ID,
    latest_status: 'completed',
    updated_at: now,
  },
];

const previewSvg = Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 240"><rect width="180" height="240" fill="#f4f7fb"/><circle cx="90" cy="80" r="42" fill="#7aa7c7"/><path d="M38 206c12-48 92-48 104 0" fill="#355a7a"/><circle cx="76" cy="75" r="5" fill="#102236"/><circle cx="104" cy="75" r="5" fill="#102236"/><path d="M75 103q15 12 30 0" fill="none" stroke="#102236" stroke-width="6" stroke-linecap="round"/></svg>',
).toString('base64');

function log(message) {
  process.stdout.write(`[launcher-session-summary-ui-smoke] ${message}\n`);
}

function launcherPayload(mode) {
  const live2d = mode === 'live2d';
  return {
    ok: true,
    mode,
    chat: {
      session_id: live2d ? DELEGATED_SESSION_ID : GROUP_SESSION_ID,
      is_processing: false,
      empty: false,
      status_label: STATUS_LABEL,
      latest_reply: live2d ? LIVE2D_REPLY : '',
      latest_reply_full: live2d ? LIVE2D_REPLY : '',
      recent_sessions: recentSessions,
    },
    notification: {
      has_unread: true,
      latest_message: live2d ? { status: 'completed', content: LIVE2D_REPLY } : { status: 'completed', content: '' },
    },
    proactive: {
      enabled: true,
      has_attention: false,
      message: '',
    },
    launcher: live2d
      ? {
          latest_status: 'completed',
          latest_reply: LIVE2D_REPLY,
          latest_reply_full: LIVE2D_REPLY,
          show_reply_bubble: true,
          enable_quick_input: true,
          click_action: bridgeState.live2dClickAction,
          default_open_behavior: 'chat_input',
          position_anchor: 'bottom-right',
          preview_url: `data:image/svg+xml;base64,${previewSvg}`,
          scale: 1,
          mouse_follow_enabled: false,
          render_quality_preset: 'low',
          renderer: {
            enabled: false,
            reason: 'Smoke preview fallback',
          },
          resource: {
            available: true,
            state: 'loaded',
            display_name: 'Smoke Live2D',
            status_label: 'Smoke Live2D ready',
            help_text: '',
          },
        }
      : {
          default_display: 'summary',
          default_open_behavior: bridgeState.bubbleDefaultOpenBehavior,
          enable_quick_input: true,
          latest_status: 'completed',
          show_unread_dot: true,
          has_attention: false,
          auto_hide: false,
          opacity: 1,
          avatar_url: '',
        },
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
      if (request.method === 'GET' && url.pathname === '/ui/launcher') {
        const mode = url.searchParams.get('mode') === 'live2d' ? 'live2d' : 'bubble';
        bridgeState.modeRequests.push(mode);
        sendJson(response, 200, launcherPayload(mode));
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/launcher/ack') {
        const body = await readRequestJson(request);
        bridgeState.ackPayloads.push(body);
        sendJson(response, 200, {
          ok: true,
          session_id: body.mode === 'live2d' ? DELEGATED_SESSION_ID : GROUP_SESSION_ID,
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/launcher/quick-message') {
        const body = await readRequestJson(request);
        bridgeState.quickMessagePayload = body;
        bridgeState.quickMessagePayloads.push(body);
        sendJson(response, 200, { ok: true, task_id: 'launcher-session-summary-quick-message' });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/state') {
        sendJson(response, 200, {
          ackPayloads: bridgeState.ackPayloads,
          bubbleDefaultOpenBehavior: bridgeState.bubbleDefaultOpenBehavior,
          live2dClickAction: bridgeState.live2dClickAction,
          modeRequests: bridgeState.modeRequests,
          quickMessagePayload: bridgeState.quickMessagePayload,
          quickMessagePayloads: bridgeState.quickMessagePayloads,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/bubble-chat-input') {
        bridgeState.bubbleDefaultOpenBehavior = 'chat_input';
        sendJson(response, 200, { ok: true, bubbleDefaultOpenBehavior: bridgeState.bubbleDefaultOpenBehavior });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/live2d-open-chat') {
        bridgeState.live2dClickAction = 'open_chat';
        sendJson(response, 200, { ok: true, live2dClickAction: bridgeState.live2dClickAction });
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
const http = require('node:http');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const bubbleSummary = ${JSON.stringify(BUBBLE_SUMMARY)};
const delegatedSummary = ${JSON.stringify(DELEGATED_SUMMARY)};
const bubbleQuickText = ${JSON.stringify(BUBBLE_QUICK_TEXT)};
const live2dReply = ${JSON.stringify(LIVE2D_REPLY)};
const live2dQuickText = ${JSON.stringify(LIVE2D_QUICK_TEXT)};
const groupSessionId = ${JSON.stringify(GROUP_SESSION_ID)};
const delegatedSessionId = ${JSON.stringify(DELEGATED_SESSION_ID)};
const groupTaskId = ${JSON.stringify(GROUP_TASK_ID)};
const delegatedTaskId = ${JSON.stringify(DELEGATED_TASK_ID)};
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 30000);
function requestBridgeJson(pathname) {
  return new Promise((resolve, reject) => {
    const request = http.request(bridgeUrl + pathname, { method: 'GET' }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8');
        if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error('GET ' + pathname + ' failed with status ' + response.statusCode + ': ' + body));
          return;
        }
        try {
          resolve(body ? JSON.parse(body) : {});
        } catch (error) {
          reject(error);
        }
      });
    });
    request.on('error', reject);
    request.end();
  });
}
function waitForBridgeState(predicate, label, timeout = 15000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const state = await requestBridgeJson('/__smoke/state');
        if (predicate(state)) {
          resolve(state);
          return;
        }
      } catch {}
      if (Date.now() - started > timeout) {
        reject(new Error('timeout waiting for bridge state: ' + label));
      } else {
        setTimeout(tick, 120);
      }
    };
    tick();
  });
}
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
              location: window.location.href,
              testids: Array.from(document.querySelectorAll('[data-testid]')).slice(0, 80).map((node) => ({
                testid: node.getAttribute('data-testid'),
                hidden: node.hidden,
                session: node.getAttribute('data-session-id'),
                task: node.getAttribute('data-task-id'),
                kind: node.getAttribute('data-conversation-kind'),
                text: (node.textContent || '').slice(0, 240),
              })),
              bodyText: (document.body.textContent || '').slice(-1600),
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
async function installOpenViewProbe(win) {
  await win.webContents.executeJavaScript(\`
    window.__ohaLauncherOpenViewCalls = [];
    window.ohaDesktop = {
      ...(window.ohaDesktop || {}),
      openView: async (view, params) => {
        window.__ohaLauncherOpenViewCalls.push({ view, params: params || {} });
      },
    };
    true;
  \`, true);
}
async function main() {
  await app.whenReady();
  console.log('[electron-smoke] app ready');
  const win = new BrowserWindow({
    width: 900,
    height: 700,
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
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&surface=desktop#/bubble');
  await installOpenViewProbe(win);
  console.log('[electron-smoke] bubble loaded');
  await waitFor(win, () => document.querySelector('[data-testid="bubble-launcher-shell"]'), 'bubble shell');
  await waitFor(win, () => {
    const summary = document.querySelector('[data-testid="bubble-launcher-summary"]');
    const probe = document.querySelector('[data-testid="bubble-launcher-session-summary-probe"]');
    const status = document.querySelector('[data-testid="bubble-launcher-status-label"]');
    const sessions = Array.from(document.querySelectorAll('[data-testid="bubble-launcher-recent-session"]'));
    const bodyText = document.body.textContent || '';
    return summary
      && summary.textContent.includes(${JSON.stringify(BUBBLE_SUMMARY)})
      && probe
      && status?.textContent.includes('2 recent sessions')
      && sessions.length === 2
      && sessions[0].getAttribute('data-session-id') === ${JSON.stringify(GROUP_SESSION_ID)}
      && sessions[0].getAttribute('data-task-id') === ${JSON.stringify(GROUP_TASK_ID)}
      && sessions[0].getAttribute('data-conversation-kind') === 'group'
      && sessions[0].textContent.includes(${JSON.stringify(BUBBLE_SUMMARY)})
      && sessions[1].getAttribute('data-session-id') === ${JSON.stringify(DELEGATED_SESSION_ID)}
      && sessions[1].getAttribute('data-task-id') === ${JSON.stringify(DELEGATED_TASK_ID)}
      && sessions[1].getAttribute('data-conversation-kind') === 'agent'
      && sessions[1].textContent.includes(${JSON.stringify(DELEGATED_SUMMARY)})
      && !bodyText.includes('oha.group_dispatch')
      && !bodyText.includes('<oha_group_dispatch>')
      && !bodyText.includes('run_oha_agent')
      && !bodyText.includes('<oha_delegation>');
  }, 'bubble summary and recent sessions');
  console.log('[electron-smoke] bubble summary rendered');
  await win.webContents.executeJavaScript(\`
    const button = document.querySelector('[data-testid="bubble-launcher-button"]');
    if (!button) throw new Error('missing bubble launcher button');
    button.click();
  \`, true);
  await waitForBridgeState((state) => (
    Array.isArray(state.ackPayloads)
    && state.ackPayloads.some((payload) => payload?.mode === 'bubble')
  ), 'bubble launcher ack');
  await waitFor(win, () => (
    Array.isArray(window.__ohaLauncherOpenViewCalls)
    && window.__ohaLauncherOpenViewCalls.some((call) => (
      call?.view === 'chat'
      && call?.params?.session_id === ${JSON.stringify(GROUP_SESSION_ID)}
      && call?.params?.conversation_kind === 'group'
      && call?.params?.task_id === ${JSON.stringify(GROUP_TASK_ID)}
    ))
  ), 'bubble launcher opened chat session');
  console.log('[electron-smoke] bubble launcher ack verified');

  await requestBridgeJson('/__smoke/bubble-chat-input');
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&surface=desktop#/bubble');
  await installOpenViewProbe(win);
  console.log('[electron-smoke] bubble chat input loaded');
  await waitFor(win, () => {
    const quickInput = document.querySelector('[data-testid="bubble-launcher-quick-input"]');
    const quickField = document.querySelector('[data-testid="bubble-launcher-quick-input-field"]');
    const quickSubmit = document.querySelector('[data-testid="bubble-launcher-quick-input-submit"]');
    return quickInput && quickField && quickSubmit;
  }, 'bubble quick input visible');
  await win.webContents.executeJavaScript(\`
    {
      const field = document.querySelector('[data-testid="bubble-launcher-quick-input-field"]');
      if (!field) throw new Error('missing bubble quick input field');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(field, ${JSON.stringify(`  ${BUBBLE_QUICK_TEXT}  `)});
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
  \`, true);
  await waitFor(win, () => {
    const submit = document.querySelector('[data-testid="bubble-launcher-quick-input-submit"]');
    return submit && !submit.disabled;
  }, 'bubble quick input submit enabled');
  await win.webContents.executeJavaScript(\`
    (() => {
      const submit = document.querySelector('[data-testid="bubble-launcher-quick-input-submit"]');
      if (!submit) throw new Error('missing bubble quick input submit');
      submit.click();
    })();
  \`, true);
  await waitForBridgeState((state) => (
    Array.isArray(state.quickMessagePayloads)
    && state.quickMessagePayloads.some((payload) => payload?.text === ${JSON.stringify(BUBBLE_QUICK_TEXT)} && payload?.mode === 'bubble')
  ), 'bubble quick input payload');
  await waitFor(win, () => !document.querySelector('[data-testid="bubble-launcher-quick-input"]'), 'bubble quick input submitted');
  console.log('[electron-smoke] bubble quick input submitted: ' + bubbleQuickText);

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&surface=desktop#/live2d');
  await installOpenViewProbe(win);
  console.log('[electron-smoke] live2d loaded');
  await waitFor(win, () => document.querySelector('[data-testid="live2d-launcher-shell"]'), 'live2d shell');
  await waitFor(win, () => {
    const quickInput = document.querySelector('[data-testid="live2d-launcher-quick-input"]');
    const quickField = document.querySelector('[data-testid="live2d-launcher-quick-input-field"]');
    const quickSubmit = document.querySelector('[data-testid="live2d-launcher-quick-input-submit"]');
    const latestReply = document.querySelector('[data-testid="live2d-launcher-latest-reply"]');
    const probe = document.querySelector('[data-testid="live2d-launcher-session-summary-probe"]');
    const preview = document.querySelector('[data-testid="live2d-launcher-preview-fallback"]');
    const sessions = Array.from(document.querySelectorAll('[data-testid="live2d-launcher-recent-session"]'));
    const bodyText = document.body.textContent || '';
    return quickInput
      && quickField
      && quickSubmit
      && latestReply?.textContent.includes(${JSON.stringify(LIVE2D_REPLY)})
      && probe
      && preview
      && sessions.length === 2
      && sessions[0].getAttribute('data-session-id') === ${JSON.stringify(GROUP_SESSION_ID)}
      && sessions[0].getAttribute('data-task-id') === ${JSON.stringify(GROUP_TASK_ID)}
      && sessions[0].getAttribute('data-conversation-kind') === 'group'
      && sessions[0].textContent.includes(${JSON.stringify(BUBBLE_SUMMARY)})
      && sessions[1].getAttribute('data-session-id') === ${JSON.stringify(DELEGATED_SESSION_ID)}
      && sessions[1].getAttribute('data-task-id') === ${JSON.stringify(DELEGATED_TASK_ID)}
      && sessions[1].getAttribute('data-conversation-kind') === 'agent'
      && sessions[1].textContent.includes(${JSON.stringify(DELEGATED_SUMMARY)})
      && !bodyText.includes('oha.group_dispatch')
      && !bodyText.includes('<oha_group_dispatch>')
      && !bodyText.includes('run_oha_agent')
      && !bodyText.includes('<oha_delegation>');
  }, 'live2d quick input and recent sessions');
  console.log('[electron-smoke] live2d summary rendered');
  await win.webContents.executeJavaScript(\`
    {
      const field = document.querySelector('[data-testid="live2d-launcher-quick-input-field"]');
      if (!field) throw new Error('missing live2d quick input field');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(field, ${JSON.stringify(`  ${LIVE2D_QUICK_TEXT}  `)});
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
  \`, true);
  await waitFor(win, () => {
    const submit = document.querySelector('[data-testid="live2d-launcher-quick-input-submit"]');
    return submit && !submit.disabled;
  }, 'live2d quick input submit enabled');
  await win.webContents.executeJavaScript(\`
    (() => {
      const submit = document.querySelector('[data-testid="live2d-launcher-quick-input-submit"]');
      if (!submit) throw new Error('missing live2d quick input submit');
      submit.click();
    })();
  \`, true);
  await waitFor(win, () => {
    const quickInput = document.querySelector('[data-testid="live2d-launcher-quick-input"]');
    const reply = document.querySelector('[data-testid="live2d-launcher-reply-text"]');
    return !quickInput && reply && reply.textContent.includes(${JSON.stringify(LIVE2D_REPLY)});
  }, 'live2d quick input submitted and reply restored');
  console.log('[electron-smoke] live2d quick input submitted: ' + live2dQuickText);
  await win.webContents.executeJavaScript(\`
    (() => {
      const stage = document.querySelector('[data-testid="live2d-launcher-stage"]');
      if (!stage) throw new Error('missing live2d launcher stage');
      stage.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    })();
  \`, true);
  await waitForBridgeState((state) => (
    Array.isArray(state.ackPayloads)
    && state.ackPayloads.some((payload) => payload?.mode === 'live2d')
  ), 'live2d launcher stage ack');
  console.log('[electron-smoke] live2d launcher ack verified');

  await requestBridgeJson('/__smoke/live2d-open-chat');
  const launcherRequestCountBeforeOpenChat = (await requestBridgeJson('/__smoke/state')).modeRequests.length;
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&surface=desktop#/live2d');
  await installOpenViewProbe(win);
  await waitFor(win, () => document.querySelector('[data-testid="live2d-launcher-shell"]'), 'live2d open-chat shell');
  await waitForBridgeState((state) => (
    state.live2dClickAction === 'open_chat'
    && Array.isArray(state.modeRequests)
    && state.modeRequests.length > launcherRequestCountBeforeOpenChat
  ), 'live2d open-chat launcher payload');
  const live2dAckCountBeforeOpenChat = (await requestBridgeJson('/__smoke/state')).ackPayloads
    .filter((payload) => payload?.mode === 'live2d').length;
  await win.webContents.executeJavaScript(\`
    (() => {
      const stage = document.querySelector('[data-testid="live2d-launcher-stage"]');
      if (!stage) throw new Error('missing live2d launcher stage for open chat');
      stage.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    })();
  \`, true);
  await waitForBridgeState((state) => (
    Array.isArray(state.ackPayloads)
    && state.ackPayloads.filter((payload) => payload?.mode === 'live2d').length > live2dAckCountBeforeOpenChat
  ), 'live2d open-chat ack');
  await waitFor(win, () => (
    Array.isArray(window.__ohaLauncherOpenViewCalls)
    && window.__ohaLauncherOpenViewCalls.some((call) => (
      call?.view === 'chat'
      && call?.params?.session_id === ${JSON.stringify(DELEGATED_SESSION_ID)}
      && call?.params?.conversation_kind === 'agent'
      && call?.params?.task_id === ${JSON.stringify(DELEGATED_TASK_ID)}
    ))
  ), 'live2d launcher opened delegated chat session');
  console.log('[electron-smoke] live2d open-chat session handoff verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-launcher-summary-smoke-'));
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
  if (!bridgeState.modeRequests.includes('bubble')) {
    throw new Error('bubble launcher payload was not requested');
  }
  if (!bridgeState.modeRequests.includes('live2d')) {
    throw new Error('live2d launcher payload was not requested');
  }
  const ackModes = bridgeState.ackPayloads.map((payload) => payload?.mode);
  if (!ackModes.includes('bubble')) {
    throw new Error(`bubble launcher ack was not called: ${JSON.stringify(bridgeState.ackPayloads)}`);
  }
  if (!ackModes.includes('live2d')) {
    throw new Error(`live2d launcher ack was not called: ${JSON.stringify(bridgeState.ackPayloads)}`);
  }
  const quickPayloads = bridgeState.quickMessagePayloads;
  const bubbleQuickPayload = quickPayloads.find((payload) => payload?.mode === 'bubble');
  if (!bubbleQuickPayload) {
    throw new Error(`bubble quick input did not call /ui/launcher/quick-message: ${JSON.stringify(quickPayloads)}`);
  }
  if (bubbleQuickPayload.text !== BUBBLE_QUICK_TEXT) {
    throw new Error(`bubble quick input text mismatch: ${JSON.stringify(bubbleQuickPayload.text)}`);
  }
  if (bubbleQuickPayload.session_id !== '') {
    throw new Error(`bubble quick input session_id should be empty: ${JSON.stringify(bubbleQuickPayload.session_id)}`);
  }
  const quickPayload = bridgeState.quickMessagePayload;
  if (!quickPayload) {
    throw new Error('live2d quick input did not call /ui/launcher/quick-message');
  }
  if (quickPayload.text !== LIVE2D_QUICK_TEXT) {
    throw new Error(`live2d quick input text mismatch: ${JSON.stringify(quickPayload.text)}`);
  }
  if (quickPayload.mode !== 'live2d') {
    throw new Error(`live2d quick input mode mismatch: ${JSON.stringify(quickPayload.mode)}`);
  }
  if (quickPayload.session_id !== '') {
    throw new Error(`live2d quick input session_id should be empty without proactive attention: ${JSON.stringify(quickPayload.session_id)}`);
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
