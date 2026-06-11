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
const BUBBLE_SUMMARY = 'Group summary: Design and Coding finished Native dispatch.';
const DELEGATED_SUMMARY = 'Delegated summary: Coding finished Native delegated run.';
const LIVE2D_REPLY = 'Live2D latest reply from launcher smoke';
const STATUS_LABEL = '2 recent sessions';
const now = new Date().toISOString();

const bridgeState = {
  modeRequests: [],
};

const recentSessions = [
  {
    session_id: GROUP_SESSION_ID,
    conversation_kind: 'group',
    title: 'Launcher Group',
    summary: BUBBLE_SUMMARY,
    latest_status: 'completed',
    updated_at: now,
  },
  {
    session_id: DELEGATED_SESSION_ID,
    conversation_kind: 'agent',
    title: 'Delegated Agent',
    summary: DELEGATED_SUMMARY,
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
      has_unread: live2d,
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
          enable_quick_input: false,
          click_action: 'toggle_reply',
          default_open_behavior: 'reply',
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
        await readRequestJson(request);
        sendJson(response, 200, { ok: true, session_id: GROUP_SESSION_ID });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/launcher/quick-message') {
        await readRequestJson(request);
        sendJson(response, 200, { ok: true, task_id: 'launcher-session-summary-quick-message' });
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
const bubbleSummary = ${JSON.stringify(BUBBLE_SUMMARY)};
const delegatedSummary = ${JSON.stringify(DELEGATED_SUMMARY)};
const live2dReply = ${JSON.stringify(LIVE2D_REPLY)};
const groupSessionId = ${JSON.stringify(GROUP_SESSION_ID)};
const delegatedSessionId = ${JSON.stringify(DELEGATED_SESSION_ID)};
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
              location: window.location.href,
              testids: Array.from(document.querySelectorAll('[data-testid]')).slice(0, 80).map((node) => ({
                testid: node.getAttribute('data-testid'),
                hidden: node.hidden,
                session: node.getAttribute('data-session-id'),
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

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&surface=desktop#/bubble');
  console.log('[electron-smoke] bubble loaded');
  await waitFor(win, () => document.querySelector('[data-testid="bubble-launcher-shell"]'), 'bubble shell');
  await waitFor(win, () => {
    const summary = document.querySelector('[data-testid="bubble-launcher-summary"]');
    const probe = document.querySelector('[data-testid="bubble-launcher-session-summary-probe"]');
    const status = document.querySelector('[data-testid="bubble-launcher-status-label"]');
    const sessions = Array.from(document.querySelectorAll('[data-testid="bubble-launcher-recent-session"]'));
    return summary
      && summary.textContent.includes(${JSON.stringify(BUBBLE_SUMMARY)})
      && probe
      && status?.textContent.includes('2 recent sessions')
      && sessions.length === 2
      && sessions[0].getAttribute('data-session-id') === ${JSON.stringify(GROUP_SESSION_ID)}
      && sessions[0].getAttribute('data-conversation-kind') === 'group'
      && sessions[0].textContent.includes(${JSON.stringify(BUBBLE_SUMMARY)})
      && sessions[1].getAttribute('data-session-id') === ${JSON.stringify(DELEGATED_SESSION_ID)}
      && sessions[1].getAttribute('data-conversation-kind') === 'agent'
      && sessions[1].textContent.includes(${JSON.stringify(DELEGATED_SUMMARY)});
  }, 'bubble summary and recent sessions');
  console.log('[electron-smoke] bubble summary rendered');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&surface=desktop#/live2d');
  console.log('[electron-smoke] live2d loaded');
  await waitFor(win, () => document.querySelector('[data-testid="live2d-launcher-shell"]'), 'live2d shell');
  await waitFor(win, () => {
    const reply = document.querySelector('[data-testid="live2d-launcher-reply-text"]');
    const latestReply = document.querySelector('[data-testid="live2d-launcher-latest-reply"]');
    const probe = document.querySelector('[data-testid="live2d-launcher-session-summary-probe"]');
    const preview = document.querySelector('[data-testid="live2d-launcher-preview-fallback"]');
    const sessions = Array.from(document.querySelectorAll('[data-testid="live2d-launcher-recent-session"]'));
    return reply
      && reply.textContent.includes(${JSON.stringify(LIVE2D_REPLY)})
      && latestReply?.textContent.includes(${JSON.stringify(LIVE2D_REPLY)})
      && probe
      && preview
      && sessions.length === 2
      && sessions[0].getAttribute('data-session-id') === ${JSON.stringify(GROUP_SESSION_ID)}
      && sessions[0].getAttribute('data-conversation-kind') === 'group'
      && sessions[0].textContent.includes(${JSON.stringify(BUBBLE_SUMMARY)})
      && sessions[1].getAttribute('data-session-id') === ${JSON.stringify(DELEGATED_SESSION_ID)}
      && sessions[1].getAttribute('data-conversation-kind') === 'agent'
      && sessions[1].textContent.includes(${JSON.stringify(DELEGATED_SUMMARY)});
  }, 'live2d reply and recent sessions');
  console.log('[electron-smoke] live2d summary rendered');
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
