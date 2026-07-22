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

const AGENT_ID = 'entry-route-agent';
const TASK_ID = 'entry-route-task';
const RUN_ID = 'entry-route-run';
const SKILL_ID = 'entry-route-skill';
const MEMORY_ID = 'entry-route-memory';
const FUTURE_TASK_ID = 'entry-route-future-task';
const now = new Date().toISOString();

const pathHitCounts = new Map();

function log(message) {
  process.stdout.write(`[yachiyo-entry-routes-ui-smoke] ${message}\n`);
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
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS,PATCH,DELETE',
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

function recordHit(method, pathname) {
  const key = `${method} ${pathname}`;
  pathHitCounts.set(key, (pathHitCounts.get(key) || 0) + 1);
}

function entryAgent() {
  return {
    agent_id: AGENT_ID,
    name: 'Entry Route Agent',
    nickname: 'Entry Agent',
    description: 'Smoke-test Agent for top-level Yachiyo entry routes.',
    avatar_url: '',
    category: 'smoke',
    instructions: 'Validate Yachiyo route boundaries.',
    persona_prompt: '',
    model_mode: 'profile',
    model_profile_id: '',
    vision_model_profile_id: '',
    model_config: {},
    tool_policy: {
      allowed_tools: ['workspace.read'],
      approval_required: {
        'workspace.write_patch': true,
      },
    },
    workspace_policy: {
      default_workdir: '',
      readable_scopes: ['.'],
      writable_scopes: [],
    },
    output_contract: 'chat',
    enabled: true,
    editable: true,
    deletable: true,
    skill_ids: [SKILL_ID],
    created_at: now,
    updated_at: now,
  };
}

function entrySkill() {
  return {
    skill_id: SKILL_ID,
    name: 'Entry Route Skill',
    description: 'Visible from the top-level Skills entry.',
    source_path: 'owner/repo --skill entry-route',
    local_path: '/tmp/oha-yachiyo/skills/entry-route',
    folder_id: '',
    folder_name: '',
    source_type: 'npx_skills',
    source_ref: 'owner/repo --skill entry-route',
    content_hash: 'entry-route-skill-hash',
    last_synced_at: now,
    sync_status: 'synced',
    content_summary: 'Skill visible through the top-level Skills route.',
    skill_markdown: '# Entry Route Skill\n\nSmoke-test top-level Skills navigation.',
    asset_paths: [],
    enabled: true,
    created_at: now,
    updated_at: now,
  };
}

function entryRunTimeline() {
  return {
    run_id: RUN_ID,
    agent_id: AGENT_ID,
    title: 'Entry Route Agent Task',
    kind: 'agent_run',
    status: 'running',
    user_goal: 'Validate top-level Yachiyo entry routes.',
    task_id: TASK_ID,
    session_id: 'entry-route-session',
    events: entryTaskEvents(),
    approvals: [],
    artifacts: [],
    created_at: now,
    updated_at: now,
  };
}

function entryTaskEvents() {
  return [
    {
      event_id: 'entry-route-event-1',
      run_id: RUN_ID,
      sequence: 1,
      event_type: 'agent.run.started',
      title: 'Run started',
      detail: 'Entry Route Agent started from Tasks.',
      status: 'running',
      created_at: now,
      payload: {
        agent_id: AGENT_ID,
        task_id: TASK_ID,
      },
    },
    {
      event_id: 'entry-route-event-2',
      run_id: RUN_ID,
      sequence: 2,
      event_type: 'tool.call.started',
      title: 'Tool call',
      detail: 'workspace.read',
      tool_name: 'workspace.read',
      status: 'running',
      created_at: now,
      payload: {
        tool_name: 'workspace.read',
      },
    },
  ];
}

function entryTaskSnapshot() {
  return {
    task_id: TASK_ID,
    conversation_id: 'entry-route-conversation',
    title: 'Entry Route Agent Task',
    status: 'running',
    summary: 'Task visible from the top-level Tasks route.',
    current_step: 'Running route smoke',
    progress_text: 'Checking entry routes',
    needs_user_action: false,
    pending_approvals: [],
    artifacts: [],
    recent_events: entryTaskEvents(),
    open_in_studio_url: `#/agents?run=${encodeURIComponent(RUN_ID)}`,
    created_at: now,
    updated_at: now,
  };
}

function entryMemory() {
  return {
    memory_id: MEMORY_ID,
    scope: 'global',
    kind: 'fact',
    content: 'Entry Route Memory is visible from the top-level Memories entry.',
    source_session_id: 'entry-route-session',
    source_message_id: '',
    source_task_id: TASK_ID,
    source_run_id: RUN_ID,
    confidence: 0.98,
    pinned: true,
    user_confirmed: true,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

function entryFutureTask() {
  return {
    future_task_id: FUTURE_TASK_ID,
    title: 'Entry Route Future Task',
    prompt: 'Follow up on top-level Yachiyo entry routes.',
    runnable_id: AGENT_ID,
    runnable_name: 'Entry Route Agent',
    status: 'scheduled',
    scheduled_at_epoch: Math.floor(Date.now() / 1000) + 3600,
    cron: null,
    source_run_id: RUN_ID,
    last_run_id: '',
    run_count: 0,
    error: '',
    created_at: now,
    updated_at: now,
    cancelled_at: null,
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
      recordHit(request.method || 'GET', url.pathname);

      if (request.method === 'GET' && url.pathname === '/ui/dashboard') {
        sendJson(response, 200, {
          bridge: { state: 'running', url: 'http://127.0.0.1' },
          chat: { is_processing: false, active_task_count: 1 },
          tasks: { active_count: 1 },
          assistant: {
            agent_name: '月見八千代',
            agent_nickname: '八千代',
            agent_avatar_url: '',
          },
          native_agent: { ready: true },
          workspace: { initialized: true, path: '~/.hermes/yachiyo' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/activity') {
        sendJson(response, 200, { events: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, { ok: true, sources: [], profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/tasks') {
        sendJson(response, 200, { tasks: [entryTaskSnapshot()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}/events`) {
        sendJson(response, 200, {
          task_id: TASK_ID,
          run_id: RUN_ID,
          events: entryTaskEvents(),
          after_sequence: Number(url.searchParams.get('after_sequence') || 0),
          limit: Number(url.searchParams.get('limit') || 200),
          has_more: false,
          next_after_sequence: 2,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/agents') {
        sendJson(response, 200, { agents: [entryAgent()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/groups') {
        sendJson(response, 200, { groups: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/runs') {
        sendJson(response, 200, { runs: [entryRunTimeline()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/timeline`) {
        sendJson(response, 200, entryRunTimeline());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`) {
        sendJson(response, 200, {
          run_id: RUN_ID,
          events: entryTaskEvents(),
          after_sequence: Number(url.searchParams.get('after_sequence') || 0),
          limit: Number(url.searchParams.get('limit') || 200),
          has_more: false,
          next_after_sequence: 2,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/group-runs') {
        sendJson(response, 200, { group_runs: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skills') {
        sendJson(response, 200, { skills: [entrySkill()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skills/sources') {
        sendJson(response, 200, {
          roots: [{
            path: '/tmp/oha-yachiyo/native-skill-library',
            source_type: 'native_global',
            library: 'native',
            exists: true,
            skill_count: 0,
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skill-folders') {
        sendJson(response, 200, { folders: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/memories') {
        sendJson(response, 200, { memories: [entryMemory()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/future-tasks') {
        sendJson(response, 200, { future_tasks: [entryFutureTask()] });
        return;
      }
      sendJson(response, 404, { error: `unexpected smoke route: ${request.method} ${url.pathname}` });
    } catch (error) {
      sendJson(response, 500, { error: error instanceof Error ? error.message : String(error) });
    }
  });
  const port = await pickPort();
  await new Promise((resolve) => {
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
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 35000);
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
              tasks: Array.from(document.querySelectorAll('[data-testid="yachiyo-agent-task-card"]')).map((node) => ({
                id: node.getAttribute('data-task-id'),
                run: node.getAttribute('data-run-id'),
                text: node.textContent,
              })),
              skills: Array.from(document.querySelectorAll('[data-testid="skill-card"]')).map((node) => ({
                id: node.getAttribute('data-skill-id'),
                text: node.textContent,
              })),
              memories: Array.from(document.querySelectorAll('[data-testid="agent-memory-item"]')).map((node) => ({
                id: node.getAttribute('data-memory-id'),
                text: node.textContent,
              })),
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

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/tasks');
  await waitFor(win, () => (
    window.location.hash === '#/tasks'
    && document.querySelector('[data-testid="yachiyo-tasks-page"]')
    && document.querySelector('[data-testid="yachiyo-tasks-filter-active"]')
    && document.querySelector('[data-testid="yachiyo-tasks-filter-all"]')
    && document.querySelector('[data-task-id="${TASK_ID}"]')
    && document.querySelector('[data-testid="yachiyo-agent-task-card"]')?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
    && document.querySelector('[data-testid="yachiyo-agent-task-open-studio"]')
  ), 'top-level tasks route');
  console.log('[electron-smoke] tasks route rendered');

  await win.webContents.executeJavaScript(
    "document.querySelector('[data-testid=\\\"yachiyo-agent-task-runtime-details\\\"] summary').click()",
    true,
  );
  await waitFor(win, () => (
    document.querySelector('[data-testid="yachiyo-agent-task-runtime-details"]')?.open === true
    && document.querySelector('[data-testid="yachiyo-agent-task-runtime-details-body"]')
    && document.querySelector('[data-testid="yachiyo-agent-task-card"]')?.getAttribute('data-event-source') === 'run_event_page'
    && document.querySelectorAll('[data-testid="yachiyo-agent-task-timeline-event"]').length === 2
  ), 'lazy task event replay');
  console.log('[electron-smoke] tasks event replay loaded after opening runtime details');

  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"yachiyo-agent-task-open-studio\\"]').click()", true);
  await waitFor(win, () => (
    window.location.hash.includes('#/agents')
    && (
      new URLSearchParams(window.location.hash.split('?')[1] || '').get('run') === ${JSON.stringify(RUN_ID)}
      || window.location.hash === '#/agents/' + ${JSON.stringify(RUN_ID)}
    )
    && document.querySelector('[data-testid="agent-studio-runs"]')
    && document.body.textContent.includes('Entry Route Agent Task')
  ), 'tasks handoff to Agent Studio run route');
  console.log('[electron-smoke] tasks handoff opened Agent Studio run route');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/skills');
  await waitFor(win, () => (
    window.location.hash === '#/skills'
    && document.querySelector('[data-testid="skill-library"]')
    && document.querySelector('[data-testid="skill-list"]')
    && document.querySelector('[data-testid="skill-card"]')?.getAttribute('data-skill-id') === ${JSON.stringify(SKILL_ID)}
    && document.querySelector('[data-testid="skill-card"]')?.textContent.includes('Entry Route Skill')
  ), 'top-level skills route');
  console.log('[electron-smoke] skills route rendered');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/memories');
  await waitFor(win, () => (
    window.location.hash === '#/memories'
    && document.querySelector('[data-testid="agent-runtime-memory"]')
    && document.querySelector('[data-testid="agent-memory-list"]')
    && document.querySelector('[data-memory-id="${MEMORY_ID}"]')
    && document.querySelector('[data-memory-id="${MEMORY_ID}"]')?.textContent.includes('Entry Route Memory')
    && document.querySelector('[data-testid="agent-future-task-item"]')?.textContent.includes('Entry Route Future Task')
  ), 'top-level memories route');
  console.log('[electron-smoke] memories route rendered');

  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-yachiyo-entry-routes-smoke-'));
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

function assertRouteHit(method, pathname) {
  const key = `${method} ${pathname}`;
  if (!pathHitCounts.get(key)) throw new Error(`expected mock bridge route hit: ${key}`);
}

function assertMockBridgeContract() {
  [
    ['GET', '/yachiyo/tasks'],
    ['GET', `/yachiyo/tasks/${TASK_ID}/events`],
    ['GET', '/yachiyo/studio/agents'],
    ['GET', '/yachiyo/studio/skills'],
    ['GET', '/yachiyo/studio/memories'],
    ['GET', '/yachiyo/studio/future-tasks'],
    ['GET', '/yachiyo/studio/runs'],
    ['GET', `/yachiyo/studio/runs/${RUN_ID}/events`],
    ['GET', '/ui/model-profiles'],
  ].forEach(([method, pathname]) => assertRouteHit(method, pathname));
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
