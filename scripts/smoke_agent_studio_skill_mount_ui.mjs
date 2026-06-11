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
const AGENT_ID = 'agent-studio-skill-mount-ui-smoke-agent';
const SKILL_A_ID = 'agent-studio-skill-mount-ui-smoke-a';
const SKILL_B_ID = 'agent-studio-skill-mount-ui-smoke-b';
const FOLDER_ID = 'agent-studio-skill-mount-ui-smoke-folder';
const PROFILE_ID = 'agent-studio-skill-mount-ui-smoke-profile';
const now = new Date().toISOString();

let agent = agentSpec([]);
const attachSkillRequests = [];
const detachSkillRequests = [];
const updateAgentRequests = [];

function log(message) {
  process.stdout.write(`[agent-studio-skill-mount-ui-smoke] ${message}\n`);
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

function readJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('error', reject);
    request.on('end', () => {
      const body = Buffer.concat(chunks).toString('utf8').trim();
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
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

function agentSpec(skillIds) {
  return {
    agent_id: AGENT_ID,
    name: 'Skill Mount Smoke Agent',
    nickname: 'Mount Smoke',
    description: 'Agent Studio Skill mount Electron smoke',
    avatar_url: '',
    category: 'smoke',
    instructions: 'Exercise Agent Studio Skill attach and detach paths.',
    persona_prompt: '',
    model_mode: 'profile',
    model_profile_id: PROFILE_ID,
    vision_model_profile_id: '',
    model_config: {},
    tool_policy: { allowed_tools: ['workspace.read'] },
    workspace_policy: {
      default_workdir: '',
      readable_scopes: ['.'],
      writable_scopes: [],
    },
    skill_ids: skillIds,
    output_contract: 'chat',
    enabled: true,
    editable: true,
    deletable: true,
    created_at: now,
    updated_at: now,
  };
}

const folders = [{
  folder_id: FOLDER_ID,
  name: 'Mount Smoke Folder',
  source_scope: 'all',
  skill_count: 2,
  installed_count: 2,
  native_count: 0,
  created_at: now,
  updated_at: now,
}];

const skills = [
  {
    skill_id: SKILL_A_ID,
    name: 'Mount Skill A',
    description: 'First attach/detach smoke Skill',
    source_path: 'mount-skill-a',
    local_path: '/tmp/oha-yachiyo/skills/mount-a',
    folder_id: FOLDER_ID,
    folder_name: 'Mount Smoke Folder',
    source_type: 'installed',
    content_summary: 'Mount Skill A summary',
    skill_markdown: '# Mount Skill A',
    enabled: true,
    created_at: now,
    updated_at: now,
  },
  {
    skill_id: SKILL_B_ID,
    name: 'Mount Skill B',
    description: 'Second bulk mount smoke Skill',
    source_path: 'mount-skill-b',
    local_path: '/tmp/oha-yachiyo/skills/mount-b',
    folder_id: FOLDER_ID,
    folder_name: 'Mount Smoke Folder',
    source_type: 'installed',
    content_summary: 'Mount Skill B summary',
    skill_markdown: '# Mount Skill B',
    enabled: true,
    created_at: now,
    updated_at: now,
  },
];

function withSkillIds(skillIds) {
  agent = agentSpec(Array.from(new Set(skillIds)));
  return agent;
}

async function startMockBridge() {
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, { agents: [agent] });
        return;
      }
      if (request.method === 'PATCH' && url.pathname === `/ui/agents/${AGENT_ID}`) {
        const payload = await readJson(request);
        updateAgentRequests.push(payload);
        if (Array.isArray(payload.skill_ids)) {
          withSkillIds(payload.skill_ids);
        }
        sendJson(response, 200, agent);
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/agents/${AGENT_ID}/skills`) {
        const payload = await readJson(request);
        attachSkillRequests.push(payload);
        withSkillIds([...(agent.skill_ids || []), payload.skill_id]);
        sendJson(response, 200, agent);
        return;
      }
      if (request.method === 'DELETE' && url.pathname === `/ui/agents/${AGENT_ID}/skills/${SKILL_A_ID}`) {
        detachSkillRequests.push(SKILL_A_ID);
        withSkillIds((agent.skill_ids || []).filter((skillId) => skillId !== SKILL_A_ID));
        sendJson(response, 200, agent);
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills') {
        sendJson(response, 200, { skills });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills/sources') {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skill-folders') {
        sendJson(response, 200, { folders });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, {
          ok: true,
          profiles: [{
            profile_id: PROFILE_ID,
            name: 'Skill Mount Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: PROFILE_ID },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [{
            id: AGENT_ID,
            name: agent.name,
            kind: 'agent',
            enabled: true,
            output_contract: 'chat',
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [] });
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
              selectedAgent: document.querySelector('[data-testid="agent-editor"]')?.textContent || '',
              mountSummary: document.querySelector('[data-testid="agent-skill-mount-summary"]')?.textContent || '',
              mountCount: document.querySelector('[data-testid="agent-skill-mount-visible-count"]')?.textContent || '',
              skills: Array.from(document.querySelectorAll('[data-testid="agent-skill-mount-item"]')).map((node) => ({
                id: node.getAttribute('data-skill-id'),
                mounted: node.getAttribute('data-skill-mounted'),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/agents');
  console.log('[electron-smoke] agent studio agents loaded');
  await waitFor(win, () => document.querySelector('[data-testid="agent-list-open"]'), 'agent list');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="agent-list-open"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-skill-mounts"]')
    && document.querySelectorAll('[data-testid="agent-skill-mount-item"]').length === 2
    && document.querySelector('[data-testid="agent-skill-mount-summary"]')?.textContent.includes('0 mounted / 2 visible skills')
    && document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]')?.getAttribute('data-skill-mounted') === 'false'
  ), 'unmounted skill mount grid');
  console.log('[electron-smoke] mount grid ready');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]')?.getAttribute('data-skill-mounted') === 'true'
    && document.querySelector('[data-testid="agent-skill-mount-summary"]')?.textContent.includes('1 mounted / 2 visible skills')
  ), 'single skill attached');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]')?.getAttribute('data-skill-mounted') === 'false'
    && document.querySelector('[data-testid="agent-skill-mount-summary"]')?.textContent.includes('0 mounted / 2 visible skills')
  ), 'single skill detached');
  console.log('[electron-smoke] single attach and detach complete');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="agent-skill-mount-all-visible"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]')?.getAttribute('data-skill-mounted') === 'true'
    && document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_B_ID}"]')?.getAttribute('data-skill-mounted') === 'true'
    && document.querySelector('[data-testid="agent-skill-mount-visible-count"]')?.textContent.includes('2 / 2')
  ), 'bulk mounted visible skills');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="agent-skill-unmount-all-visible"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_A_ID}"]')?.getAttribute('data-skill-mounted') === 'false'
    && document.querySelector('[data-testid="agent-skill-mount-item"][data-skill-id="${SKILL_B_ID}"]')?.getAttribute('data-skill-mounted') === 'false'
    && document.querySelector('[data-testid="agent-skill-mount-visible-count"]')?.textContent.includes('0 / 2')
  ), 'bulk unmounted visible skills');
  console.log('[electron-smoke] bulk mount and unmount complete');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-studio-skill-mount-smoke-'));
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
  if (attachSkillRequests.length !== 1 || attachSkillRequests[0].skill_id !== SKILL_A_ID) {
    throw new Error(`unexpected attach requests: ${JSON.stringify(attachSkillRequests)}`);
  }
  if (detachSkillRequests.length !== 1 || detachSkillRequests[0] !== SKILL_A_ID) {
    throw new Error(`unexpected detach requests: ${JSON.stringify(detachSkillRequests)}`);
  }
  const bulkMount = updateAgentRequests.find((request) => Array.isArray(request.skill_ids) && request.skill_ids.length === 2);
  if (!bulkMount || !bulkMount.skill_ids.includes(SKILL_A_ID) || !bulkMount.skill_ids.includes(SKILL_B_ID)) {
    throw new Error(`missing bulk mount request: ${JSON.stringify(updateAgentRequests)}`);
  }
  const bulkUnmount = updateAgentRequests.find((request) => Array.isArray(request.skill_ids) && request.skill_ids.length === 0);
  if (!bulkUnmount) {
    throw new Error(`missing bulk unmount request: ${JSON.stringify(updateAgentRequests)}`);
  }
  if ((agent.skill_ids || []).length !== 0) {
    throw new Error(`expected final agent skill_ids to be empty, got ${JSON.stringify(agent.skill_ids)}`);
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
