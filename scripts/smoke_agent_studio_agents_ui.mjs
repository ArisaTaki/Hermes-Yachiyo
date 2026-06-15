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
const SYSTEM_AGENT_ID = 'builtin:yachiyo-main';
const CREATED_AGENT_ID = 'agent-studio-agents-ui-smoke-created';
const CREATED_NAME = 'Agent Definition Smoke v1';
const UPDATED_NAME = 'Agent Definition Smoke v2';
const AVATAR_DATA_URL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';
const now = new Date().toISOString();

const systemAgent = {
  agent_id: SYSTEM_AGENT_ID,
  name: 'Oha-Yachiyo',
  nickname: 'Oha-Yachiyo',
  description: 'System main chat Agent managed by oha-yachiyo.',
  avatar_url: '',
  category: 'system',
  instructions: 'System managed Agent.',
  persona_prompt: '',
  model_mode: 'profile',
  model_profile_id: 'profile-agent-studio-agents-smoke',
  vision_model_profile_id: '',
  model_config: {},
  tool_policy: { allowed_tools: [] },
  workspace_policy: { default_workdir: '', readable_scopes: ['.'], writable_scopes: [] },
  output_contract: 'chat',
  enabled: true,
  editable: false,
  deletable: false,
  system: true,
  skill_ids: [],
  created_at: now,
  updated_at: now,
};

let agents = [systemAgent];
let createAgentRequest = null;
let updateAgentRequest = null;
let deletedAgentId = '';

function log(message) {
  process.stdout.write(`[agent-studio-agents-ui-smoke] ${message}\n`);
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

function agentSpec(request = {}) {
  return {
    agent_id: CREATED_AGENT_ID,
    name: request.name || CREATED_NAME,
    nickname: request.nickname || request.name || CREATED_NAME,
    description: request.description || '',
    avatar_url: request.avatar_url || '',
    category: request.category || 'custom',
    instructions: request.instructions || '',
    persona_prompt: request.persona_prompt || '',
    model_mode: request.model_mode === 'custom_api' ? 'custom_api' : 'profile',
    model_profile_id: request.model_profile_id || '',
    vision_model_profile_id: request.vision_model_profile_id || '',
    model_config: request.model_config || {},
    tool_policy: request.tool_policy || { allowed_tools: ['workspace.read'] },
    workspace_policy: request.workspace_policy || {
      default_workdir: '',
      readable_scopes: ['.'],
      writable_scopes: [],
    },
    output_contract: request.output_contract || 'chat',
    enabled: request.enabled !== false,
    editable: true,
    deletable: true,
    skill_ids: request.skill_ids || [],
    created_at: now,
    updated_at: now,
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
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, { agents });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/agents') {
        createAgentRequest = await readJson(request);
        const created = agentSpec(createAgentRequest);
        agents = [systemAgent, created];
        sendJson(response, 200, created);
        return;
      }
      if (request.method === 'PATCH' && url.pathname === `/ui/agents/${CREATED_AGENT_ID}`) {
        updateAgentRequest = await readJson(request);
        const current = agents.find((agent) => agent.agent_id === CREATED_AGENT_ID) || agentSpec(createAgentRequest || {});
        const updated = { ...current, ...updateAgentRequest, agent_id: CREATED_AGENT_ID, updated_at: now };
        agents = [systemAgent, updated];
        sendJson(response, 200, updated);
        return;
      }
      if (request.method === 'DELETE' && url.pathname === `/ui/agents/${CREATED_AGENT_ID}`) {
        deletedAgentId = CREATED_AGENT_ID;
        agents = [systemAgent];
        sendJson(response, 200, { ok: true });
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
            profile_id: 'profile-agent-studio-agents-smoke',
            name: 'Agent Studio Agents Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: 'profile-agent-studio-agents-smoke' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: agents.map((agent) => ({
            id: agent.agent_id,
            name: agent.name,
            kind: 'agent',
            enabled: agent.enabled,
            output_contract: agent.output_contract,
            category: agent.category,
          })),
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
              agents: Array.from(document.querySelectorAll('[data-testid="agent-list-item"]')).map((node) => ({
                id: node.getAttribute('data-agent-id'),
                text: node.textContent,
              })),
              editor: document.querySelector('[data-testid="agent-editor"]')?.textContent || '',
              confirm: document.querySelector('[data-testid="confirm-dialog"]')?.textContent || '',
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/agents');
  console.log('[electron-smoke] agent studio agents loaded');
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-studio-agents"]')
    && document.querySelector('[data-testid="agent-editor"]')
    && document.querySelector('[data-testid="agent-list"]')
  ), 'agent studio agents');
  await waitFor(win, () => (
    document.querySelectorAll('[data-testid="agent-list-item"]').length === 1
    && document.querySelector('[data-agent-id="builtin:yachiyo-main"]')?.textContent.includes('Oha-Yachiyo')
  ), 'initial system Agent list');
  await win.webContents.executeJavaScript("document.querySelector('[data-agent-id=\\"builtin:yachiyo-main\\"] [data-testid=\\"agent-list-open\\"]').click()", true);
  await waitFor(win, () => {
    const systemItem = document.querySelector('[data-agent-id="builtin:yachiyo-main"]');
    const readOnlyFields = [
      document.querySelector('[data-testid="agent-name-input"]'),
      document.querySelector('[data-testid="agent-nickname-input"]'),
      document.querySelector('[data-testid="agent-description-input"]'),
      document.querySelector('[data-testid="agent-category-input"]'),
      document.querySelector('[data-testid="agent-instructions-input"]'),
      document.querySelector('[data-testid="agent-persona-input"]'),
    ];
    const outputContract = document.querySelector('[data-testid="agent-output-contract-select"]');
    const avatarSelect = document.querySelector('[data-testid="agent-avatar-select"]');
    const save = document.querySelector('[data-testid="agent-save"]');
    const quickRun = document.querySelector('.agent-quick-run button.primary-action');
    const quickRunGoal = document.querySelector('.agent-run-textarea');
    const inlineNotes = Array.from(document.querySelectorAll('.agent-inline-note')).map((node) => node.textContent || '');
    return document.querySelectorAll('[data-testid="agent-list-item"]').length === 1
      && systemItem?.textContent.includes('Oha-Yachiyo')
      && document.querySelector('[data-testid="agent-name-input"]')?.value === 'Oha-Yachiyo'
      && readOnlyFields.every((field) => field?.readOnly)
      && outputContract?.disabled
      && avatarSelect?.disabled
      && save?.disabled
      && !document.querySelector('[data-testid="agent-delete"]')
      && quickRun?.disabled
      && quickRunGoal?.disabled
      && quickRun?.getAttribute('title')?.includes('系统 Agent 只能查看')
      && inlineNotes.some((text) => text.includes('系统 Agent 由 oha-yachiyo 管理'));
  }, 'system Agent read-only guard');
  console.log('[electron-smoke] system Agent read-only guard verified');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-new\\"]').click()", true);
  await waitFor(win, () => (
    !document.querySelector('[data-testid="agent-delete"]')
    && document.querySelector('[data-testid="agent-name-input"]')?.value === ''
    && !document.querySelector('[data-testid="agent-name-input"]')?.readOnly
    && !document.querySelector('[data-testid="agent-output-contract-select"]')?.disabled
    && !document.querySelector('[data-testid="agent-avatar-select"]')?.disabled
    && !document.querySelector('[data-testid="agent-save"]')?.disabled
  ), 'new Agent draft after system Agent');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const setSelectValue = (element, value) => {
      element.value = value;
      element.dispatchEvent(new Event('change', { bubbles: true }));
    };
    window.__ohaAgentAvatarPickerCalls = 0;
    window.ohaDesktop = {
      ...(window.ohaDesktop || {}),
      chooseAvatarImage: async () => {
        window.__ohaAgentAvatarPickerCalls += 1;
        return {
          data_url: ${JSON.stringify(AVATAR_DATA_URL)},
          file_name: 'agent-avatar-smoke.png',
          path: '/tmp/oha-yachiyo/agent-avatar-smoke.png',
        };
      },
    };
    setNativeValue(document.querySelector('[data-testid="agent-name-input"]'), ${JSON.stringify(CREATED_NAME)});
    setNativeValue(document.querySelector('[data-testid="agent-nickname-input"]'), 'Definition Smoke');
    setNativeValue(document.querySelector('[data-testid="agent-description-input"]'), 'Created by Agent Studio Electron smoke');
    setNativeValue(document.querySelector('[data-testid="agent-category-input"]'), 'smoke');
    setNativeValue(document.querySelector('[data-testid="agent-instructions-input"]'), 'Preserve Agent Studio definition create and update paths.');
    setNativeValue(document.querySelector('[data-testid="agent-persona-input"]'), 'Concise QA helper.');
    setSelectValue(document.querySelector('[data-testid="agent-output-contract-select"]'), 'report');
    document.querySelector('[data-testid="agent-avatar-select"]').click();
  })();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-avatar-clear"]')
    && document.querySelector('.agent-avatar.has-image img')?.getAttribute('src')?.startsWith('data:image/png;base64,')
  ), 'agent avatar selected');
  const avatarPickerCalls = await win.webContents.executeJavaScript('window.__ohaAgentAvatarPickerCalls || 0', true);
  if (avatarPickerCalls !== 1) {
    throw new Error('expected Agent avatar picker to be called once, got ' + avatarPickerCalls);
  }
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-avatar-clear\\"]').click()", true);
  await waitFor(win, () => (
    !document.querySelector('[data-testid="agent-avatar-clear"]')
    && !document.querySelector('.agent-avatar.has-image img')
  ), 'agent avatar cleared');
  console.log('[electron-smoke] agent avatar cleared');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-avatar-select\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-avatar-clear"]')
    && document.querySelector('.agent-avatar.has-image img')?.getAttribute('src')?.startsWith('data:image/png;base64,')
  ), 'agent avatar reselected');
  const avatarPickerCallsAfterReselect = await win.webContents.executeJavaScript('window.__ohaAgentAvatarPickerCalls || 0', true);
  if (avatarPickerCallsAfterReselect !== 2) {
    throw new Error('expected Agent avatar picker to be called twice after reselect, got ' + avatarPickerCallsAfterReselect);
  }
  console.log('[electron-smoke] agent avatar reselected');
  await win.webContents.executeJavaScript(\`
  (() => {
    document.querySelector('[data-testid="agent-save"]').click();
  })();
  \`, true);
  await waitFor(win, () => {
    const item = document.querySelector('[data-agent-id="${CREATED_AGENT_ID}"]');
    return document.querySelectorAll('[data-testid="agent-list-item"]').length === 2
      && item
      && item.getAttribute('data-agent-id') === ${JSON.stringify(CREATED_AGENT_ID)}
      && item.textContent.includes(${JSON.stringify(CREATED_NAME)})
      && document.querySelector('[data-testid="agent-delete"]');
  }, 'created agent selected');
  console.log('[electron-smoke] agent created');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-management-toggle\\"]').click()", true);
  await waitFor(win, () => {
    const systemCheckbox = document.querySelector('[data-agent-id="builtin:yachiyo-main"] [data-testid="agent-list-select-checkbox"]');
    const customCheckbox = document.querySelector('[data-agent-id="${CREATED_AGENT_ID}"] [data-testid="agent-list-select-checkbox"]');
    return document.querySelector('[data-testid="agent-select-all"]')
      && document.querySelector('[data-testid="agent-delete-selected"]')?.disabled
      && document.querySelector('[data-agent-id="builtin:yachiyo-main"]')?.getAttribute('data-agent-deletable') === 'false'
      && document.querySelector('[data-agent-id="${CREATED_AGENT_ID}"]')?.getAttribute('data-agent-deletable') === 'true'
      && systemCheckbox?.disabled
      && !systemCheckbox?.checked
      && !customCheckbox?.disabled
      && !customCheckbox?.checked;
  }, 'agent management system selection guard');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-select-all\\"]').click()", true);
  await waitFor(win, () => {
    const systemCheckbox = document.querySelector('[data-agent-id="builtin:yachiyo-main"] [data-testid="agent-list-select-checkbox"]');
    const customCheckbox = document.querySelector('[data-agent-id="${CREATED_AGENT_ID}"] [data-testid="agent-list-select-checkbox"]');
    return systemCheckbox?.disabled
      && !systemCheckbox?.checked
      && customCheckbox?.checked
      && document.querySelector('.studio-bulk-actions')?.textContent.includes('已选择 1 / 2')
      && !document.querySelector('[data-testid="agent-delete-selected"]')?.disabled;
  }, 'agent select all excludes system Agent');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-clear-selection\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-delete-selected"]')?.disabled
    && !document.querySelector('[data-agent-id="${CREATED_AGENT_ID}"] [data-testid="agent-list-select-checkbox"]')?.checked
  ), 'agent clear selection');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-management-done\\"]').click()", true);
  await waitFor(win, () => !document.querySelector('[data-testid="agent-select-all"]'), 'agent management done');
  console.log('[electron-smoke] system Agent bulk selection guard verified');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    setNativeValue(document.querySelector('[data-testid="agent-name-input"]'), ${JSON.stringify(UPDATED_NAME)});
    setNativeValue(document.querySelector('[data-testid="agent-description-input"]'), 'Updated by Agent Studio Electron smoke');
    document.querySelector('[data-testid="agent-save"]').click();
  })();
  \`, true);
  await waitFor(win, () => {
    const item = document.querySelector('[data-agent-id="${CREATED_AGENT_ID}"]');
    return item
      && item.textContent.includes(${JSON.stringify(UPDATED_NAME)})
      && document.querySelector('[data-testid="agent-name-input"]')?.value === ${JSON.stringify(UPDATED_NAME)};
  }, 'updated agent selected');
  console.log('[electron-smoke] agent updated');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-delete\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="confirm-dialog"]')?.textContent.includes('删除 Agent'), 'delete confirm dialog');
  await win.webContents.executeJavaScript(\`
  document.querySelector('[data-testid="confirm-action"]').click();
  \`, true);
  await waitFor(win, () => (
    document.querySelectorAll('[data-testid="agent-list-item"]').length === 1
    && document.querySelector('[data-agent-id="builtin:yachiyo-main"]')
    && !document.querySelector('[data-testid="agent-delete"]')
    && document.querySelector('[data-testid="agent-name-input"]')?.value === ''
  ), 'agent deleted and editor reset');
  console.log('[electron-smoke] agent deleted');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-studio-agents-smoke-'));
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
  if (!createAgentRequest) throw new Error('agent was not created');
  if (!updateAgentRequest) throw new Error('agent was not updated');
  if (deletedAgentId !== CREATED_AGENT_ID) throw new Error(`agent was not deleted: ${deletedAgentId || 'missing delete'}`);
  if (createAgentRequest.name !== CREATED_NAME) throw new Error(`unexpected created agent name: ${createAgentRequest.name}`);
  if (createAgentRequest.nickname !== 'Definition Smoke') throw new Error(`unexpected created agent nickname: ${createAgentRequest.nickname}`);
  if (createAgentRequest.description !== 'Created by Agent Studio Electron smoke') {
    throw new Error(`unexpected created agent description: ${createAgentRequest.description}`);
  }
  if (createAgentRequest.avatar_url !== AVATAR_DATA_URL) {
    throw new Error(`unexpected created agent avatar: ${createAgentRequest.avatar_url || 'missing avatar'}`);
  }
  if (createAgentRequest.category !== 'smoke') throw new Error(`unexpected created agent category: ${createAgentRequest.category}`);
  if (createAgentRequest.instructions !== 'Preserve Agent Studio definition create and update paths.') {
    throw new Error(`unexpected created agent instructions: ${createAgentRequest.instructions}`);
  }
  if (createAgentRequest.persona_prompt !== 'Concise QA helper.') {
    throw new Error(`unexpected created agent persona: ${createAgentRequest.persona_prompt}`);
  }
  if (createAgentRequest.output_contract !== 'report') {
    throw new Error(`unexpected created output contract: ${createAgentRequest.output_contract}`);
  }
  if (updateAgentRequest.name !== UPDATED_NAME) throw new Error(`unexpected updated agent name: ${updateAgentRequest.name}`);
  if (updateAgentRequest.description !== 'Updated by Agent Studio Electron smoke') {
    throw new Error(`unexpected updated agent description: ${updateAgentRequest.description}`);
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
