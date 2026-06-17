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

const AGENT_ID = 'agent-studio-groups-ui-smoke-agent';
const EXISTING_GROUP_ID = 'agent-studio-groups-ui-smoke-existing';
const CREATED_GROUP_ID = 'agent-studio-groups-ui-smoke-created';
const GROUP_RUN_ID = 'agent-studio-groups-ui-smoke-group-run';
const GROUP_RUN_ROOT_RUN_ID = 'agent-studio-groups-ui-smoke-root-run';
const EXISTING_GROUP_NAME = 'Groups Smoke Existing';
const CREATED_GROUP_NAME = 'Groups Smoke Created';
const UPDATED_DESCRIPTION = 'Edited by Agent Studio Groups Electron smoke';
const GROUP_OBJECTIVE = 'Coordinate a smoke group run with approval and artifact facts.';
const ARTIFACT_PATH = 'groups/smoke-summary.md';
const now = new Date().toISOString();

const smokeAgent = {
  agent_id: AGENT_ID,
  name: 'Groups Smoke Agent',
  nickname: 'Groups Smoke',
  description: 'Agent used by Agent Studio Groups UI smoke.',
  avatar_url: '',
  category: 'smoke',
  instructions: 'Exercise group management and group run UI.',
  persona_prompt: '',
  model_mode: 'profile',
  model_profile_id: 'profile-agent-studio-groups-smoke',
  vision_model_profile_id: '',
  model_config: {},
  tool_policy: {
    allowed_tools: ['workspace.read', 'workspace.write'],
    approval_required: { 'workspace.write': true },
  },
  workspace_policy: {
    default_workdir: '',
    readable_scopes: ['.'],
    writable_scopes: ['.'],
  },
  output_contract: 'chat',
  enabled: true,
  editable: true,
  deletable: true,
  system: false,
  skill_ids: [],
  created_at: now,
  updated_at: now,
};

const approval = {
  approval_id: 'agent-studio-groups-ui-smoke-approval',
  run_id: GROUP_RUN_ROOT_RUN_ID,
  source_run_id: GROUP_RUN_ROOT_RUN_ID,
  source_runnable_id: AGENT_ID,
  source_runnable_name: smokeAgent.name,
  group_id: CREATED_GROUP_ID,
  group_run_id: GROUP_RUN_ID,
  title: 'Approve group artifact write',
  description: 'Runtime approval fact for group run smoke.',
  status: 'pending',
  tool_name: 'workspace.write',
  risk_level: 'medium',
  input_preview: { path: ARTIFACT_PATH },
  policy_reason: 'workspace.write requires explicit approval',
  requested_at: now,
  open_in_studio_url: `#/agents/${GROUP_RUN_ROOT_RUN_ID}?group_run=${GROUP_RUN_ID}`,
};

const artifact = {
  artifact_id: 'agent-studio-groups-ui-smoke-artifact',
  run_id: GROUP_RUN_ROOT_RUN_ID,
  source_run_id: GROUP_RUN_ROOT_RUN_ID,
  source_tool: 'workspace.write',
  source_runnable_id: AGENT_ID,
  source_runnable_name: smokeAgent.name,
  group_id: CREATED_GROUP_ID,
  group_run_id: GROUP_RUN_ID,
  title: 'Group smoke summary',
  kind: 'markdown',
  path: ARTIFACT_PATH,
  mime_type: 'text/markdown',
  size_bytes: 96,
  preview_text: 'Group smoke artifact proves shared artifacts are visible from Agent Studio.',
  created_at: now,
};

const toolCall = {
  tool_call_id: 'agent-studio-groups-ui-smoke-tool-call',
  run_id: GROUP_RUN_ROOT_RUN_ID,
  source_run_id: GROUP_RUN_ROOT_RUN_ID,
  source_runnable_id: AGENT_ID,
  source_runnable_name: smokeAgent.name,
  group_id: CREATED_GROUP_ID,
  group_run_id: GROUP_RUN_ID,
  tool_name: 'workspace.write',
  status: 'waiting_approval',
  risk_level: 'medium',
  input_preview: { path: ARTIFACT_PATH },
  approval_id: approval.approval_id,
  started_at: now,
  completed_at: null,
};

const memoryTrace = {
  trace_id: 'agent-studio-groups-ui-smoke-memory-trace',
  run_id: GROUP_RUN_ROOT_RUN_ID,
  sequence: 4,
  event_type: 'memory.retrieved',
  status: 'completed',
  action: 'retrieved',
  memory_id: 'agent-studio-groups-ui-smoke-memory',
  memory_kind: 'preference',
  count: 1,
  source_run_id: GROUP_RUN_ROOT_RUN_ID,
  source_runnable_id: AGENT_ID,
  source_runnable_name: smokeAgent.name,
  group_id: CREATED_GROUP_ID,
  group_run_id: GROUP_RUN_ID,
  title: 'Memory retrieved',
  detail: 'preference',
  payload_preview: { count: 1 },
  created_at: now,
};

const skillTrace = {
  trace_id: 'agent-studio-groups-ui-smoke-skill-trace',
  run_id: GROUP_RUN_ROOT_RUN_ID,
  sequence: 5,
  event_type: 'skill.selected',
  status: 'completed',
  skill_id: 'agent-studio-groups-ui-smoke-skill',
  skill_name: 'Group smoke skill',
  source_ref: 'native://group-smoke',
  source_type: 'native',
  source_run_id: GROUP_RUN_ROOT_RUN_ID,
  source_runnable_id: AGENT_ID,
  source_runnable_name: smokeAgent.name,
  group_id: CREATED_GROUP_ID,
  group_run_id: GROUP_RUN_ID,
  title: 'Skill selected',
  detail: 'native://group-smoke · native',
  payload_preview: { skill_id: 'agent-studio-groups-ui-smoke-skill' },
  created_at: now,
};

const rootRunEvents = [
  {
    event_id: 'agent-studio-groups-ui-smoke-run-started',
    run_id: GROUP_RUN_ROOT_RUN_ID,
    sequence: 1,
    event_type: 'group.run.started',
    title: 'Group run started',
    detail: GROUP_OBJECTIVE,
    actor: 'runtime',
    visibility: 'user',
    sensitivity: 'public',
    payload: { group_id: CREATED_GROUP_ID, group_run_id: GROUP_RUN_ID },
    created_at: now,
  },
  {
    event_id: 'agent-studio-groups-ui-smoke-tool-approval',
    run_id: GROUP_RUN_ROOT_RUN_ID,
    sequence: 2,
    event_type: 'tool.approval_required',
    title: 'Tool approval required',
    detail: 'workspace.write needs approval',
    actor: AGENT_ID,
    visibility: 'user',
    sensitivity: 'public',
    payload: {
      approval,
      tool_call: toolCall,
    },
    created_at: now,
  },
  {
    event_id: 'agent-studio-groups-ui-smoke-artifact-created',
    run_id: GROUP_RUN_ROOT_RUN_ID,
    sequence: 3,
    event_type: 'artifact.created',
    title: 'Artifact created',
    detail: artifact.title,
    actor: AGENT_ID,
    visibility: 'user',
    sensitivity: 'public',
    payload: { artifact },
    created_at: now,
  },
  {
    event_id: 'agent-studio-groups-ui-smoke-run-completed',
    run_id: GROUP_RUN_ROOT_RUN_ID,
    sequence: 6,
    event_type: 'group.run.completed',
    title: 'Group run completed',
    detail: 'Group run finished with observable timeline facts.',
    actor: 'runtime',
    visibility: 'user',
    sensitivity: 'public',
    payload: { group_id: CREATED_GROUP_ID, group_run_id: GROUP_RUN_ID },
    created_at: now,
  },
];

function groupSnapshot(overrides = {}) {
  return {
    group_id: overrides.group_id || CREATED_GROUP_ID,
    name: overrides.name || CREATED_GROUP_NAME,
    description: overrides.description || 'Created by Agent Studio Groups UI smoke.',
    members: overrides.members || [{
      agent_id: AGENT_ID,
      name: smokeAgent.name,
      role: 'moderator',
      sort_order: 0,
      enabled: true,
    }],
    mode: overrides.mode || 'moderated',
    moderator_agent_id: overrides.moderator_agent_id || AGENT_ID,
    default_model: overrides.default_model || 'profile-agent-studio-groups-smoke',
    memory_scope: overrides.memory_scope || 'shared',
    tool_policy_id: overrides.tool_policy_id || 'policy-agent-studio-groups-smoke',
    enabled: overrides.enabled !== false,
    created_at: now,
    updated_at: now,
  };
}

function runTimelineSnapshot() {
  return {
    run_id: GROUP_RUN_ROOT_RUN_ID,
    group_run_id: GROUP_RUN_ID,
    run_group_id: GROUP_RUN_ID,
    agent_id: AGENT_ID,
    status: 'completed',
    title: 'Groups smoke root run',
    task_id: 'agent-studio-groups-ui-smoke-task',
    session_id: 'agent-studio-groups-ui-smoke-session',
    events: rootRunEvents,
    tool_calls: [toolCall],
    memory_traces: [memoryTrace],
    skill_traces: [skillTrace],
    approvals: [approval],
    pending_approval: approval,
    artifacts: [artifact],
    children: [],
    created_at: now,
    updated_at: now,
  };
}

function groupRunSnapshot() {
  return {
    group_run_id: GROUP_RUN_ID,
    run_group_id: GROUP_RUN_ID,
    group_id: CREATED_GROUP_ID,
    title: 'Groups smoke group run',
    status: 'completed',
    objective: GROUP_OBJECTIVE,
    participants: [{
      agent_id: AGENT_ID,
      name: smokeAgent.name,
      role: 'moderator',
      sort_order: 0,
      enabled: true,
    }],
    active_speaker_agent_id: null,
    events: rootRunEvents,
    runs: [runTimelineSnapshot()],
    child_run_ids: [GROUP_RUN_ROOT_RUN_ID],
    tool_calls: [toolCall],
    memory_traces: [memoryTrace],
    skill_traces: [skillTrace],
    shared_artifacts: [artifact],
    pending_approvals: [approval],
    final_answer: 'Group run completed with approval and artifact replay facts.',
    created_at: now,
    updated_at: now,
  };
}

let groups = [groupSnapshot({
  group_id: EXISTING_GROUP_ID,
  name: EXISTING_GROUP_NAME,
  description: 'Existing group for edit smoke.',
})];
let updateGroupRequest = null;
let createGroupRequest = null;
let startGroupRunRequest = null;
let groupRunStarted = false;

function log(message) {
  process.stdout.write(`[agent-studio-groups-ui-smoke] ${message}\n`);
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

function modelProfilesPayload() {
  return {
    ok: true,
    profiles: [{
      profile_id: 'profile-agent-studio-groups-smoke',
      name: 'Agent Studio Groups Smoke Chat Profile',
      capability: 'chat',
      provider: 'openai_compatible',
      enabled: true,
      api_key_configured: true,
      status: 'available',
    }],
    defaults: { chat: 'profile-agent-studio-groups-smoke' },
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/agents') {
        sendJson(response, 200, { agents: [smokeAgent] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/agents/${encodeURIComponent(AGENT_ID)}`) {
        sendJson(response, 200, smokeAgent);
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, { agents: [smokeAgent] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/groups') {
        sendJson(response, 200, { groups });
        return;
      }
      if (request.method === 'GET' && url.pathname.startsWith('/yachiyo/studio/groups/')) {
        const groupId = decodeURIComponent(url.pathname.split('/').pop() || '');
        const group = groups.find((item) => item.group_id === groupId);
        sendJson(response, group ? 200 : 404, group || { ok: false, error: 'group not found' });
        return;
      }
      if (request.method === 'PATCH' && url.pathname === `/yachiyo/studio/groups/${encodeURIComponent(EXISTING_GROUP_ID)}`) {
        updateGroupRequest = await readJson(request);
        const updated = groupSnapshot({
          ...updateGroupRequest,
          group_id: EXISTING_GROUP_ID,
          name: updateGroupRequest.name || EXISTING_GROUP_NAME,
          description: updateGroupRequest.description || UPDATED_DESCRIPTION,
          members: updateGroupRequest.members?.map((member, index) => ({
            agent_id: member.agent_id,
            name: smokeAgent.name,
            role: member.role || (index === 0 ? 'moderator' : 'member'),
            sort_order: member.sort_order ?? index,
            enabled: member.enabled !== false,
          })) || groups[0].members,
        });
        groups = [updated, ...groups.filter((group) => group.group_id !== EXISTING_GROUP_ID)];
        sendJson(response, 200, updated);
        return;
      }
      if (request.method === 'POST' && url.pathname === '/yachiyo/studio/groups') {
        createGroupRequest = await readJson(request);
        const created = groupSnapshot({
          ...createGroupRequest,
          group_id: CREATED_GROUP_ID,
          name: createGroupRequest.name || CREATED_GROUP_NAME,
          members: createGroupRequest.members?.map((member, index) => ({
            agent_id: member.agent_id,
            name: smokeAgent.name,
            role: member.role || (index === 0 ? 'moderator' : 'member'),
            sort_order: member.sort_order ?? index,
            enabled: member.enabled !== false,
          })) || undefined,
        });
        groups = [
          ...groups.filter((group) => group.group_id !== CREATED_GROUP_ID),
          created,
        ];
        sendJson(response, 200, created);
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/groups/${encodeURIComponent(CREATED_GROUP_ID)}/runs`) {
        startGroupRunRequest = await readJson(request);
        groupRunStarted = true;
        sendJson(response, 200, groupRunSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/group-runs') {
        sendJson(response, 200, { group_runs: groupRunStarted ? [groupRunSnapshot()] : [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/group-runs/${encodeURIComponent(GROUP_RUN_ID)}`) {
        sendJson(response, 200, groupRunSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/group-runs/${encodeURIComponent(GROUP_RUN_ID)}/events`) {
        sendJson(response, 200, {
          run_id: GROUP_RUN_ID,
          after_sequence: Number(url.searchParams.get('after_sequence') || 0),
          limit: Number(url.searchParams.get('limit') || 25),
          next_after_sequence: 4,
          has_more: false,
          events: rootRunEvents.map((event) => ({ ...event, run_id: GROUP_RUN_ID })),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/runs') {
        sendJson(response, 200, { runs: groupRunStarted ? [runTimelineSnapshot()] : [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${encodeURIComponent(GROUP_RUN_ROOT_RUN_ID)}/timeline`) {
        sendJson(response, 200, runTimelineSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${encodeURIComponent(GROUP_RUN_ROOT_RUN_ID)}/events`) {
        sendJson(response, 200, {
          run_id: GROUP_RUN_ROOT_RUN_ID,
          after_sequence: Number(url.searchParams.get('after_sequence') || 0),
          limit: Number(url.searchParams.get('limit') || 200),
          next_after_sequence: 4,
          has_more: false,
          events: rootRunEvents,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${encodeURIComponent(GROUP_RUN_ROOT_RUN_ID)}/artifacts/${ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          run_id: GROUP_RUN_ROOT_RUN_ID,
          path: ARTIFACT_PATH,
          content: '# Group smoke summary\n\nApproval and artifact facts are visible.',
          mime_type: 'text/markdown',
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: groupRunStarted ? [runTimelineSnapshot()] : [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${encodeURIComponent(GROUP_RUN_ROOT_RUN_ID)}`) {
        sendJson(response, 200, runTimelineSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: groupRunStarted ? [groupRunSnapshot()] : [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${encodeURIComponent(GROUP_RUN_ID)}`) {
        sendJson(response, 200, groupRunSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, modelProfilesPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skills') {
        sendJson(response, 200, { skills: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skills/sources') {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skill-folders') {
        sendJson(response, 200, { folders: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/memories') {
        sendJson(response, 200, { memories: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/future-tasks') {
        sendJson(response, 200, { future_tasks: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [{
            id: smokeAgent.agent_id,
            name: smokeAgent.name,
            kind: 'agent',
            enabled: true,
            output_contract: smokeAgent.output_contract,
            category: smokeAgent.category,
          }],
        });
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
              groups: Array.from(document.querySelectorAll('[data-testid="agent-group-list-item"]')).map((node) => ({
                id: node.getAttribute('data-agent-group-id'),
                text: node.textContent,
              })),
              groupEditor: document.querySelector('[data-testid="agent-group-editor"]')?.textContent || '',
              groupRun: document.querySelector('[data-testid="agent-group-run-panel"]')?.textContent || '',
              runDetail: document.querySelector('[data-testid="agent-run-detail"]')?.textContent || '',
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/groups');
  console.log('[electron-smoke] agent studio groups loaded');
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-studio-groups"]')
    && document.querySelector('[data-testid="agent-group-editor"]')
    && document.querySelector('[data-testid="agent-group-list"]')
    && document.querySelector('[data-agent-group-id="${EXISTING_GROUP_ID}"]')
  ), 'agent studio groups');
  await waitFor(win, () => (
    document.querySelector('[data-agent-group-id="${EXISTING_GROUP_ID}"]')?.textContent.includes(${JSON.stringify(EXISTING_GROUP_NAME)})
    && document.querySelector('[data-testid="agent-group-member-picker"] [data-agent-id="${AGENT_ID}"] input')?.checked
    && !document.querySelector('[data-testid="agent-group-save"]')?.disabled
  ), 'existing group selected');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const editor = document.querySelector('[data-testid="agent-group-editor"]');
    setNativeValue(editor.querySelector('[data-testid="agent-group-description"]'), ${JSON.stringify(UPDATED_DESCRIPTION)});
    setNativeValue(editor.querySelector('[data-testid="agent-group-default-model"]'), 'profile-agent-studio-groups-smoke-edited');
    setNativeValue(editor.querySelector('[data-testid="agent-group-tool-policy"]'), 'policy-agent-studio-groups-smoke-edited');
    document.querySelector('[data-testid="agent-group-save"]').click();
  })();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-group-description"]')?.value === ${JSON.stringify(UPDATED_DESCRIPTION)}
    && document.querySelector('[data-testid="agent-group-default-model"]')?.value === 'profile-agent-studio-groups-smoke-edited'
    && !document.querySelector('[data-testid="agent-group-new"]')?.disabled
    && !document.querySelector('[data-testid="agent-group-save"]')?.disabled
  ), 'existing group updated');
  console.log('[electron-smoke] existing group edited');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-group-new\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-group-editor"] h2')?.textContent.includes('New Group')
    && document.querySelector('[data-testid="agent-group-save"]')?.disabled
    && !document.querySelector('[data-testid="agent-group-member-picker"] [data-agent-id="${AGENT_ID}"] input')?.checked
  ), 'new group draft');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const editor = document.querySelector('[data-testid="agent-group-editor"]');
    const nameInput = editor.querySelector('label input.hy-input');
    setNativeValue(nameInput, ${JSON.stringify(CREATED_GROUP_NAME)});
    setNativeValue(editor.querySelector('[data-testid="agent-group-description"]'), 'Created by Agent Studio Groups Electron smoke');
    setNativeValue(editor.querySelector('[data-testid="agent-group-default-model"]'), 'profile-agent-studio-groups-smoke');
    setNativeValue(editor.querySelector('[data-testid="agent-group-tool-policy"]'), 'policy-agent-studio-groups-smoke');
    document.querySelector('[data-testid="agent-group-member-picker"] [data-agent-id="${AGENT_ID}"] input').click();
  })();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-group-member-picker"] [data-agent-id="${AGENT_ID}"] input')?.checked
    && !document.querySelector('[data-testid="agent-group-save"]')?.disabled
  ), 'new group member selected');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-group-save\\"]').click()", true);
  await waitFor(win, () => {
    const item = document.querySelector('[data-agent-group-id="${CREATED_GROUP_ID}"]');
    return item
      && item.textContent.includes(${JSON.stringify(CREATED_GROUP_NAME)})
      && document.querySelector('[data-testid="agent-group-moderator"]')?.value === ${JSON.stringify(AGENT_ID)}
      && document.querySelector('[data-testid="agent-group-default-model"]')?.value === 'profile-agent-studio-groups-smoke';
  }, 'created group selected');
  console.log('[electron-smoke] group created');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const textarea = document.querySelector('[data-testid="agent-group-run-panel"] textarea');
    setNativeValue(textarea, ${JSON.stringify(GROUP_OBJECTIVE)});
  })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="agent-group-run"]')?.disabled, 'group run enabled');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-group-run\\"]').click()", true);
  await waitFor(win, () => (
    window.location.hash.includes(${JSON.stringify(GROUP_RUN_ROOT_RUN_ID)})
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(GROUP_RUN_ROOT_RUN_ID)}
    && document.querySelector('[data-testid="agent-run-detail-execution-event"]')
  ), 'run detail opened from group run');
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-run-detail-group-run-overview"]')
    && document.querySelector('[data-testid="agent-run-detail-group-run-replay"]')
    && document.querySelector('[data-testid="agent-run-detail-group-run-approvals"]')
    && document.querySelector('[data-testid="agent-run-detail-group-run-tool-calls"]')
    && document.querySelector('[data-testid="agent-run-detail-group-run-tool-call-card"]')?.textContent.includes('workspace.write')
    && document.querySelector('[data-testid="agent-run-detail-group-run-memory-skill-traces"]')
    && Array.from(document.querySelectorAll('[data-testid="agent-run-detail-group-run-memory-skill-trace"]'))
      .some((node) => node.textContent.includes('Group smoke skill'))
    && document.querySelector('[data-testid="agent-run-detail-group-run-artifacts"]')
    && document.querySelector('[data-testid="agent-run-detail-group-run-artifact-item"]')
  ), 'group run detail runtime facts');
  console.log('[electron-smoke] group run detail verified');
  await win.webContents.executeJavaScript(\`
  Array.from(document.querySelectorAll('.agent-studio-tabs button'))
    .find((button) => button.textContent.trim() === 'Groups')
    .click();
  \`, true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-studio-groups"]')
    && document.querySelector('[data-testid="agent-group-run-latest"]')?.textContent.includes('Groups smoke group run')
    && document.querySelector('[data-testid="agent-group-run-event-summary"]')
    && document.querySelector('[data-testid="agent-group-run-event-page-meta"]')?.textContent.includes('events')
    && document.querySelector('[data-testid="agent-group-run-approvals"]')
    && document.querySelector('[data-testid="agent-group-run-artifacts"]')
    && document.querySelector('[data-testid="agent-group-run-artifact-item"]')
  ), 'latest group run runtime facts');
  console.log('[electron-smoke] group run latest panel verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-studio-groups-smoke-'));
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
  if (!updateGroupRequest) throw new Error('existing group was not updated');
  if (!createGroupRequest) throw new Error('group was not created');
  if (!startGroupRunRequest) throw new Error('group run was not started');
  if (updateGroupRequest.description !== UPDATED_DESCRIPTION) {
    throw new Error(`unexpected updated group description: ${updateGroupRequest.description}`);
  }
  if (updateGroupRequest.default_model !== 'profile-agent-studio-groups-smoke-edited') {
    throw new Error(`unexpected updated group model: ${updateGroupRequest.default_model}`);
  }
  if (updateGroupRequest.tool_policy_id !== 'policy-agent-studio-groups-smoke-edited') {
    throw new Error(`unexpected updated group policy: ${updateGroupRequest.tool_policy_id}`);
  }
  if (!Array.isArray(updateGroupRequest.members) || updateGroupRequest.members[0]?.agent_id !== AGENT_ID) {
    throw new Error('updated group did not preserve smoke agent member');
  }
  if (createGroupRequest.name !== CREATED_GROUP_NAME) {
    throw new Error(`unexpected created group name: ${createGroupRequest.name}`);
  }
  if (!Array.isArray(createGroupRequest.members) || createGroupRequest.members[0]?.agent_id !== AGENT_ID) {
    throw new Error('created group did not include smoke agent member');
  }
  if (createGroupRequest.moderator_agent_id !== AGENT_ID) {
    throw new Error(`unexpected group moderator: ${createGroupRequest.moderator_agent_id}`);
  }
  if (createGroupRequest.memory_scope !== 'shared') {
    throw new Error(`unexpected group memory scope: ${createGroupRequest.memory_scope}`);
  }
  if (createGroupRequest.tool_policy_id !== 'policy-agent-studio-groups-smoke') {
    throw new Error(`unexpected group tool policy: ${createGroupRequest.tool_policy_id}`);
  }
  if (startGroupRunRequest.objective !== GROUP_OBJECTIVE) {
    throw new Error(`unexpected group objective: ${startGroupRunRequest.objective}`);
  }
  if (!startGroupRunRequest.client_run_id) throw new Error('group run did not include client_run_id');
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
