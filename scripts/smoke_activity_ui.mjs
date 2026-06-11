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
const ACTIVITY_EVENT_ID = 'activity_ui_smoke_event';
const OTHER_EVENT_ID = 'activity_ui_smoke_other';
const TASK_ID = 'task-activity-ui-smoke';
const SESSION_ID = 'session-activity-ui-smoke';
const ACTIVITY_TITLE = 'Activity UI smoke workspace read';
const ACTIVITY_DETAIL = 'workspace.read completed through NativeRunEngine activity projection.';
const TRACE_DETAIL = 'Expanded trace metadata proves Activity detail keeps full process context.';
const now = new Date().toISOString();

const bridgeState = {
  deletedEventIds: [],
  detailRequests: [],
  listRequests: [],
};

function log(message) {
  process.stdout.write(`[activity-ui-smoke] ${message}\n`);
}

function activityEvent() {
  return {
    event_id: ACTIVITY_EVENT_ID,
    trace_event_ids: ['activity-ui-smoke-start', ACTIVITY_EVENT_ID],
    task_id: TASK_ID,
    session_id: SESSION_ID,
    tool_name: 'workspace.read',
    phase: 'tool_end',
    title: ACTIVITY_TITLE,
    detail: ACTIVITY_DETAIL,
    status: 'completed',
    raw_status: 'completed',
    duration_seconds: 1.25,
    created_at: now,
    metadata: {
      run_id: 'activity_ui_smoke_run',
      run_group_id: 'activity_ui_smoke_run_group',
      path: 'README.md',
    },
  };
}

function otherEvent() {
  return {
    event_id: OTHER_EVENT_ID,
    task_id: 'task-activity-ui-smoke-other',
    session_id: 'session-activity-ui-smoke-other',
    tool_name: 'terminal.run',
    phase: 'tool_start',
    title: 'Other Activity UI smoke event',
    detail: 'A second event keeps list filtering meaningful.',
    status: 'running',
    raw_status: 'running',
    created_at: now,
    metadata: {},
  };
}

function activityTrace() {
  return [
    {
      event_id: 'activity-ui-smoke-start',
      task_id: TASK_ID,
      session_id: SESSION_ID,
      tool_name: 'workspace.read',
      phase: 'tool_start',
      title: 'Activity UI smoke started workspace read',
      detail: 'Started reading README.md from the workspace.',
      status: 'running',
      raw_status: 'running',
      created_at: now,
      metadata: { path: 'README.md' },
    },
    {
      ...activityEvent(),
      detail: TRACE_DETAIL,
    },
  ];
}

function availableEvents() {
  return [activityEvent(), otherEvent()].filter((event) => !bridgeState.deletedEventIds.includes(event.event_id));
}

function listPayload(url) {
  const query = (url.searchParams.get('query') || '').trim().toLowerCase();
  const status = (url.searchParams.get('status') || '').trim();
  const phase = (url.searchParams.get('phase') || '').trim();
  const filtered = availableEvents().filter((event) => {
    const haystack = `${event.title} ${event.detail} ${event.session_id} ${event.task_id} ${event.tool_name}`.toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (status && event.status !== status) return false;
    if (phase && event.phase !== phase) return false;
    return true;
  });
  return {
    ok: true,
    events: filtered,
    statuses: ['completed', 'running'],
    phases: ['tool_start', 'tool_end'],
    tools: ['workspace.read', 'terminal.run'],
    total: filtered.length,
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
      if (request.method === 'GET' && url.pathname === '/ui/activity') {
        bridgeState.listRequests.push(Object.fromEntries(url.searchParams.entries()));
        sendJson(response, 200, listPayload(url));
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/activity/${ACTIVITY_EVENT_ID}`) {
        bridgeState.detailRequests.push(ACTIVITY_EVENT_ID);
        sendJson(response, 200, {
          ok: true,
          event: activityEvent(),
          trace: activityTrace(),
          scope: 'task',
          total: 2,
        });
        return;
      }
      if (request.method === 'DELETE' && url.pathname === `/ui/activity/${ACTIVITY_EVENT_ID}`) {
        await readRequestJson(request);
        bridgeState.deletedEventIds.push(ACTIVITY_EVENT_ID);
        sendJson(response, 200, { ok: true, deleted: 1 });
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
const eventId = ${JSON.stringify(ACTIVITY_EVENT_ID)};
const otherEventId = ${JSON.stringify(OTHER_EVENT_ID)};
const activityTitle = ${JSON.stringify(ACTIVITY_TITLE)};
const activityDetail = ${JSON.stringify(ACTIVITY_DETAIL)};
const traceDetail = ${JSON.stringify(TRACE_DETAIL)};
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
              hash: window.location.hash,
              rows: Array.from(document.querySelectorAll('[data-testid="activity-row"]')).map((node) => ({
                id: node.getAttribute('data-activity-event-id'),
                text: node.textContent,
              })),
              detail: document.querySelector('[data-testid="activity-detail-page"]')?.outerHTML || '',
              confirm: document.querySelector('[data-testid="confirm-dialog"]')?.textContent || '',
              bodyText: document.body.textContent.slice(-1800),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/activity-all');
  await waitFor(win, () => {
    const feed = document.querySelector('[data-testid="activity-feed"]');
    const rows = Array.from(document.querySelectorAll('[data-testid="activity-row"]'));
    return feed
      && rows.some((node) => node.getAttribute('data-activity-event-id') === ${JSON.stringify(ACTIVITY_EVENT_ID)})
      && rows.some((node) => node.getAttribute('data-activity-event-id') === ${JSON.stringify(OTHER_EVENT_ID)});
  }, 'activity feed rows');
  console.log('[electron-smoke] activity feed loaded');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="activity-search-input"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'workspace');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })();
  \`, true);
  await waitFor(win, () => {
    const rows = Array.from(document.querySelectorAll('[data-testid="activity-row"]'));
    return rows.length === 1
      && rows[0].getAttribute('data-activity-event-id') === ${JSON.stringify(ACTIVITY_EVENT_ID)}
      && rows[0].textContent.includes(${JSON.stringify(ACTIVITY_TITLE)});
  }, 'activity search filter');
  console.log('[electron-smoke] activity filter verified');
  await win.webContents.executeJavaScript(\`
    const open = document.querySelector('[data-testid="activity-row"][data-activity-event-id="${ACTIVITY_EVENT_ID}"] [data-testid="activity-row-open"]');
    if (!open) throw new Error('missing activity row open button');
    open.click();
  \`, true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="activity-detail-page"]');
    const summary = document.querySelector('[data-testid="activity-detail-summary"]');
    const body = document.querySelector('[data-testid="activity-detail-body"]');
    const traceRows = Array.from(document.querySelectorAll('[data-testid="activity-trace-row"]'));
    return window.location.hash.includes(${JSON.stringify(ACTIVITY_EVENT_ID)})
      && detail?.getAttribute('data-activity-event-id') === ${JSON.stringify(ACTIVITY_EVENT_ID)}
      && summary?.textContent.includes('workspace.read')
      && body?.textContent.includes(${JSON.stringify(ACTIVITY_DETAIL)})
      && traceRows.length === 2
      && traceRows.some((node) => node.getAttribute('data-activity-event-id') === ${JSON.stringify(ACTIVITY_EVENT_ID)});
  }, 'activity detail loaded');
  console.log('[electron-smoke] activity detail verified');
  await win.webContents.executeJavaScript(\`
    const expand = document.querySelector('[data-testid="activity-trace-row"][data-activity-event-id="${ACTIVITY_EVENT_ID}"] [data-testid="activity-trace-expand"]');
    if (!expand) throw new Error('missing activity trace expand button');
    expand.click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="activity-trace-row"][data-activity-event-id="${ACTIVITY_EVENT_ID}"]')?.classList.contains('expanded')
    && document.querySelector('[data-testid="activity-trace"]')?.textContent.includes(${JSON.stringify(TRACE_DETAIL)})
  ), 'activity trace expanded');
  console.log('[electron-smoke] activity trace expanded');
  await win.webContents.executeJavaScript(\`
    const button = document.querySelector('[data-testid="activity-detail-delete"]');
    if (!button) throw new Error('missing activity delete button');
    button.click();
  \`, true);
  await waitFor(win, () => document.querySelector('[data-testid="confirm-dialog"]'), 'activity delete confirm dialog');
  await win.webContents.executeJavaScript(\`
    const confirm = document.querySelector('[data-testid="confirm-action"]');
    if (!confirm) throw new Error('missing confirm action');
    confirm.click();
  \`, true);
  await waitFor(win, () => {
    const feed = document.querySelector('[data-testid="activity-feed"]');
    const rows = Array.from(document.querySelectorAll('[data-testid="activity-row"]'));
    return window.location.hash.includes('#/activity-all')
      && feed
      && rows.every((node) => node.getAttribute('data-activity-event-id') !== ${JSON.stringify(ACTIVITY_EVENT_ID)})
      && (rows.length === 0 || rows.some((node) => node.getAttribute('data-activity-event-id') === ${JSON.stringify(OTHER_EVENT_ID)}));
  }, 'activity deleted and list refreshed');
  console.log('[electron-smoke] activity delete verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-activity-ui-smoke-'));
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

function assertMockBridgeContract() {
  if (!bridgeState.listRequests.length) {
    throw new Error('activity list was not requested');
  }
  if (!bridgeState.listRequests.some((request) => request.query === 'workspace')) {
    throw new Error(`activity query filter was not requested: ${JSON.stringify(bridgeState.listRequests)}`);
  }
  if (!bridgeState.detailRequests.includes(ACTIVITY_EVENT_ID)) {
    throw new Error(`activity detail was not requested: ${JSON.stringify(bridgeState.detailRequests)}`);
  }
  if (!bridgeState.deletedEventIds.includes(ACTIVITY_EVENT_ID)) {
    throw new Error(`activity event was not deleted: ${JSON.stringify(bridgeState.deletedEventIds)}`);
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
