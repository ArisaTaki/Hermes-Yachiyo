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
const AGENT_ID = 'workflow-save-run-agent';
const WORKFLOW_ID = 'workflow_save_run_ui_smoke_persisted';
const RUN_ID = 'workflow_save_run_ui_smoke_run';
const RUN_GROUP_ID = 'workflow_save_run_ui_smoke_group';
const WORKFLOW_TASK_ID = 'task-workflow-save-run-ui-smoke';
const WORKFLOW_SESSION_ID = 'session-workflow-save-run-ui-smoke';
const RUN_GOAL = 'Run saved Workflow from Electron UI smoke';
const WORKFLOW_ARTIFACT_PATH = 'workflow-save-run-summary.md';
const WORKFLOW_ARTIFACT_CONTENT = '# Workflow Save Run UI Smoke\n\nArtifact node output preview.';
const APPROVAL_WORKFLOW_ID = 'workflow_save_run_ui_smoke_approval_persisted';
const APPROVAL_RUN_ID = 'workflow_save_run_ui_smoke_approval_run';
const APPROVAL_RUN_GROUP_ID = 'workflow_save_run_ui_smoke_approval_group';
const APPROVAL_TASK_ID = 'task-workflow-save-run-ui-smoke-approval';
const APPROVAL_SESSION_ID = 'session-workflow-save-run-ui-smoke-approval';
const APPROVAL_RUN_GOAL = 'Run approval Workflow from Electron UI smoke';
const APPROVAL_CRITERIA = 'Approve this Workflow UI smoke before artifact handoff.';
const APPROVAL_ARTIFACT_PATH = 'workflow-approval-node-summary.md';
const APPROVAL_ARTIFACT_CONTENT = '# Workflow Approval UI Smoke\n\nApproved artifact preview.';
const now = new Date().toISOString();

let savedWorkflow = null;
let createdWorkflowRequest = null;
let createdApprovalWorkflowRequest = null;
let createdWorkflowRunRequest = null;
let createdApprovalWorkflowRunRequest = null;
let approvalRunApproved = false;

const agent = {
  agent_id: AGENT_ID,
  name: 'Workflow Save Run Agent',
  model_mode: 'follow_main',
  execution_backend: 'native_profile',
  model_config: {},
  enabled: true,
  editable: true,
  deletable: true,
};

function savedWorkflowSpec(request = {}, workflowId = WORKFLOW_ID) {
  return {
    workflow_id: workflowId,
    name: request.name || 'Workflow Save Run UI Smoke',
    description: request.description || '',
    nodes: request.nodes || [],
    edges: request.edges || [],
    enabled: request.enabled !== false,
    created_at: now,
    updated_at: now,
  };
}

const workflowRun = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'workflow',
  task_id: WORKFLOW_TASK_ID,
  session_id: WORKFLOW_SESSION_ID,
  task_run_link_run_status: 'completed',
  task_run_link_last_event_sequence: 4,
  kind: 'workflow_run',
  runnable_id: WORKFLOW_ID,
  runnable_name: 'Workflow Save Run UI Smoke',
  status: 'completed',
  user_goal: RUN_GOAL,
  result: 'Workflow save-and-run UI smoke completed',
  timeline: [
    { event: 'workflow.run.started', status: 'running', workflow_id: WORKFLOW_ID },
    { event: 'workflow.node.agent.completed', status: 'completed', agent_id: AGENT_ID },
    { event: 'workflow.node.artifact', status: 'completed', artifact: { path: WORKFLOW_ARTIFACT_PATH } },
    { event: 'workflow.run.completed', status: 'completed' },
  ],
  artifacts: [{
    path: WORKFLOW_ARTIFACT_PATH,
    kind: 'markdown',
    source_run_id: RUN_ID,
    source_runnable_name: 'Workflow Save Run UI Smoke',
  }],
  created_at: now,
  updated_at: now,
  workflow_run_id: RUN_ID,
};

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Workflow Save Run UI Smoke',
  source: 'workflow',
  status: 'completed',
  summary: 'Workflow save-and-run completed from UI',
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

const runEvents = [
  {
    event_id: 'event-workflow-save-run-smoke-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'workflow.run.started',
    actor: 'workflow',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { workflow_id: WORKFLOW_ID, goal: RUN_GOAL },
    created_at: now,
  },
  {
    event_id: 'event-workflow-save-run-smoke-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'workflow.node.agent.completed',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { workflow_id: WORKFLOW_ID, agent_id: AGENT_ID },
    created_at: now,
  },
  {
    event_id: 'event-workflow-save-run-smoke-3',
    run_id: RUN_ID,
    sequence: 3,
    schema_version: 1,
    event_type: 'workflow.node.artifact',
    actor: 'workflow',
    visibility: 'user',
    sensitivity: 'normal',
    payload: {
      workflow_id: WORKFLOW_ID,
      workflow_node_id: 'artifact-1',
      workflow_node_label: WORKFLOW_ARTIFACT_PATH,
      artifact: { path: WORKFLOW_ARTIFACT_PATH },
    },
    created_at: now,
  },
  {
    event_id: 'event-workflow-save-run-smoke-4',
    run_id: RUN_ID,
    sequence: 4,
    schema_version: 1,
    event_type: 'workflow.run.completed',
    actor: 'workflow',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: workflowRun.result },
    created_at: now,
  },
];

function approvalWorkflowRun() {
  return {
    run_id: APPROVAL_RUN_ID,
    run_group_id: APPROVAL_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: APPROVAL_TASK_ID,
    session_id: APPROVAL_SESSION_ID,
    task_run_link_run_status: approvalRunApproved ? 'completed' : 'approval_required',
    task_run_link_last_event_sequence: approvalRunApproved ? 5 : 2,
    kind: 'workflow_run',
    runnable_id: APPROVAL_WORKFLOW_ID,
    runnable_name: 'Workflow Approval Save Run UI Smoke',
    status: approvalRunApproved ? 'completed' : 'approval_required',
    user_goal: APPROVAL_RUN_GOAL,
    result: approvalRunApproved ? 'Workflow approval save-and-run UI smoke completed' : '',
    pending_approval: approvalRunApproved ? undefined : {
      approval_id: 'approval-workflow-save-run-ui-smoke',
      tool: 'workflow.approval',
      input_preview: {
        node_id: 'approval-1',
        label: 'Manual Approval',
        criteria: APPROVAL_CRITERIA,
      },
    },
    timeline: approvalRunApproved
      ? [
          { event: 'workflow.run.started', status: 'running', workflow_id: APPROVAL_WORKFLOW_ID },
          { event: 'workflow.node.approval_required', status: 'approval_required', workflow_node_id: 'approval-1', detail: APPROVAL_CRITERIA },
          { event: 'workflow.node.approval_approved', status: 'completed', workflow_node_id: 'approval-1', detail: APPROVAL_CRITERIA },
          { event: 'workflow.node.artifact', status: 'completed', artifact: { path: APPROVAL_ARTIFACT_PATH } },
          { event: 'workflow.run.completed', status: 'completed' },
        ]
      : [
          { event: 'workflow.run.started', status: 'running', workflow_id: APPROVAL_WORKFLOW_ID },
          { event: 'workflow.node.approval_required', status: 'approval_required', workflow_node_id: 'approval-1', detail: APPROVAL_CRITERIA },
        ],
    artifacts: approvalRunApproved ? [{
      path: APPROVAL_ARTIFACT_PATH,
      kind: 'markdown',
      source_run_id: APPROVAL_RUN_ID,
      source_runnable_name: 'Workflow Approval Save Run UI Smoke',
    }] : [],
    created_at: now,
    updated_at: now,
    workflow_run_id: APPROVAL_RUN_ID,
  };
}

function approvalRunGroup() {
  return {
    run_group_id: APPROVAL_RUN_GROUP_ID,
    title: 'Workflow Approval Save Run UI Smoke',
    source: 'workflow',
    status: approvalRunApproved ? 'completed' : 'approval_required',
    summary: approvalRunApproved ? 'Workflow approval save-and-run completed from UI' : 'Workflow approval node waiting from UI',
    child_run_ids: [APPROVAL_RUN_ID],
    created_at: now,
    updated_at: now,
  };
}

function approvalRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-approval-save-run-smoke-1',
      run_id: APPROVAL_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'workflow.run.started',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { workflow_id: APPROVAL_WORKFLOW_ID, goal: APPROVAL_RUN_GOAL },
      created_at: now,
    },
    {
      event_id: 'event-workflow-approval-save-run-smoke-2',
      run_id: APPROVAL_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'workflow.node.approval_required',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_id: APPROVAL_WORKFLOW_ID,
        workflow_node_id: 'approval-1',
        workflow_node_label: 'Manual Approval',
        criteria: APPROVAL_CRITERIA,
        pending_approval: approvalWorkflowRun().pending_approval,
      },
      created_at: now,
    },
  ];
  if (!approvalRunApproved) return events;
  return [
    ...events,
    {
      event_id: 'event-workflow-approval-save-run-smoke-3',
      run_id: APPROVAL_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'workflow.node.approval_approved',
      actor: 'user',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_id: APPROVAL_WORKFLOW_ID,
        workflow_node_id: 'approval-1',
        workflow_node_label: 'Manual Approval',
        criteria: APPROVAL_CRITERIA,
      },
      created_at: now,
    },
    {
      event_id: 'event-workflow-approval-save-run-smoke-4',
      run_id: APPROVAL_RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'workflow.node.artifact',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_id: APPROVAL_WORKFLOW_ID,
        workflow_node_id: 'artifact-approval',
        workflow_node_label: APPROVAL_ARTIFACT_PATH,
        artifact: { path: APPROVAL_ARTIFACT_PATH },
      },
      created_at: now,
    },
    {
      event_id: 'event-workflow-approval-save-run-smoke-5',
      run_id: APPROVAL_RUN_ID,
      sequence: 5,
      schema_version: 1,
      event_type: 'workflow.run.completed',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: approvalWorkflowRun().result },
      created_at: now,
    },
  ];
}

function log(message) {
  process.stdout.write(`[workflow-save-run-ui-smoke] ${message}\n`);
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
            profile_id: 'profile-workflow-save-run-smoke',
            name: 'Workflow Save Run Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: 'profile-workflow-save-run-smoke' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: savedWorkflow ? [savedWorkflow] : [] });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/yachiyo/studio/workflows') {
        const body = await readJson(request);
        const hasApprovalNode = Array.isArray(body.nodes)
          && body.nodes.some((node) => node?.data?.kind === 'approval');
        if (hasApprovalNode) {
          createdApprovalWorkflowRequest = body;
          savedWorkflow = savedWorkflowSpec(body, APPROVAL_WORKFLOW_ID);
        } else {
          createdWorkflowRequest = body;
          savedWorkflow = savedWorkflowSpec(body, WORKFLOW_ID);
        }
        sendJson(response, 200, savedWorkflow);
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [
            { id: AGENT_ID, name: agent.name, kind: 'agent', enabled: true, output_contract: 'report' },
            ...(savedWorkflow ? [{ id: WORKFLOW_ID, name: savedWorkflow.name, kind: 'workflow', enabled: true, output_contract: 'workflow' }] : []),
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, {
          runs: [
            ...(createdApprovalWorkflowRunRequest ? [approvalWorkflowRun()] : []),
            ...(createdWorkflowRunRequest ? [workflowRun] : []),
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, createdWorkflowRunRequest ? 200 : 404, createdWorkflowRunRequest ? workflowRun : { ok: false, error: 'run not created' });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${APPROVAL_RUN_ID}`) {
        sendJson(response, createdApprovalWorkflowRunRequest ? 200 : 404, createdApprovalWorkflowRunRequest ? approvalWorkflowRun() : { ok: false, error: 'approval run not created' });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}/artifacts/${WORKFLOW_ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          path: WORKFLOW_ARTIFACT_PATH,
          content: WORKFLOW_ARTIFACT_CONTENT,
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${APPROVAL_RUN_ID}/artifacts/${APPROVAL_ARTIFACT_PATH}`) {
        sendJson(response, approvalRunApproved ? 200 : 404, approvalRunApproved ? {
          ok: true,
          path: APPROVAL_ARTIFACT_PATH,
          content: APPROVAL_ARTIFACT_CONTENT,
          truncated: false,
        } : { ok: false, error: 'approval artifact not created' });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/workflow-runs') {
        const body = await readJson(request);
        if (body.workflow_id === WORKFLOW_ID) {
          createdWorkflowRunRequest = body;
          sendJson(response, 200, workflowRun);
          return;
        }
        if (body.workflow_id === APPROVAL_WORKFLOW_ID) {
          createdApprovalWorkflowRunRequest = body;
          approvalRunApproved = false;
          sendJson(response, 200, approvalWorkflowRun());
          return;
        }
        sendJson(response, 409, { ok: false, error: `wrong workflow_id: ${body.workflow_id}` });
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${APPROVAL_RUN_ID}/approval/approve`) {
        approvalRunApproved = true;
        sendJson(response, 200, approvalWorkflowRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, {
          run_groups: [
            ...(createdApprovalWorkflowRunRequest ? [approvalRunGroup()] : []),
            ...(createdWorkflowRunRequest ? [runGroup] : []),
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${APPROVAL_RUN_GROUP_ID}`) {
        sendJson(response, 200, approvalRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: runEvents.filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${APPROVAL_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: APPROVAL_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: approvalRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
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
const runId = ${JSON.stringify(RUN_ID)};
const runGoal = ${JSON.stringify(RUN_GOAL)};
const approvalRunId = ${JSON.stringify(APPROVAL_RUN_ID)};
const approvalRunGoal = ${JSON.stringify(APPROVAL_RUN_GOAL)};
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
              workflow: document.querySelector('[data-testid="workflow-studio"]')?.textContent || '',
              detail: document.querySelector('[data-testid="agent-run-detail"]')?.textContent || '',
              events: Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]')).map((node) => ({
                type: node.getAttribute('data-run-event'),
                sequence: node.getAttribute('data-run-event-sequence'),
                runId: node.getAttribute('data-run-event-run-id'),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/workflows');
  console.log('[electron-smoke] workflow studio loaded');
  await waitFor(win, () => document.querySelector('[data-testid="workflow-studio"]'), 'workflow studio');
  await waitFor(win, () => document.querySelectorAll('[data-testid="workflow-agent-palette-item"]').length === 1, 'workflow agent palette');
  await win.webContents.executeJavaScript(\`
  (async () => {
    const setNativeValue = (element, value) => {
      if (!element) throw new Error('missing input for value ' + value);
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    document.querySelector('[data-testid="workflow-new"]').click();
    setNativeValue(document.querySelector('[data-testid="workflow-name-input"]'), 'Workflow Save Run UI Smoke');
    setNativeValue(document.querySelector('[data-testid="workflow-description-input"]'), 'Created by Electron save-and-run smoke');
    document.querySelector('[data-testid="workflow-agent-palette-item"]').click();
  })();
  \`, true);
  await waitFor(win, () => {
    const rows = Array.from(document.querySelectorAll('[data-testid="workflow-node-setting-row"]'));
    const previewSteps = Array.from(document.querySelectorAll('[data-testid="workflow-run-preview-step"]'));
    return rows.length === 1
      && rows[0].textContent.includes('Workflow Save Run Agent')
      && previewSteps.some((node) => node.textContent.includes('Workflow Save Run Agent'));
  }, 'workflow agent draft ready');
  await win.webContents.executeJavaScript(\`
  (async () => {
    const setNativeValue = (element, value) => {
      if (!element) throw new Error('missing input for value ' + value);
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    document.querySelector('[data-testid="workflow-add-artifact-node"]').click();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const artifactPathInput = document.querySelector('[data-testid="workflow-node-artifact-path-input"]');
    setNativeValue(artifactPathInput, ${JSON.stringify(WORKFLOW_ARTIFACT_PATH)});
  })();
  \`, true);
  await waitFor(win, () => {
    const rows = Array.from(document.querySelectorAll('[data-testid="workflow-node-setting-row"]'));
    const previewSteps = Array.from(document.querySelectorAll('[data-testid="workflow-run-preview-step"]'));
    const artifactInput = document.querySelector('[data-testid="workflow-node-artifact-path-input"]');
    return rows.length === 2
      && rows.some((row) => row.textContent.includes('Workflow Save Run Agent'))
      && artifactInput?.value === ${JSON.stringify(WORKFLOW_ARTIFACT_PATH)}
      && previewSteps.some((node) => node.textContent.includes('Workflow Save Run Agent'))
      && previewSteps.some((node) => node.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)}));
  }, 'workflow draft ready');
  console.log('[electron-smoke] workflow draft ready');
  await win.webContents.executeJavaScript(\`
  (() => {
    const setNativeValue = (element, value) => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const goal = document.querySelector('[data-testid="workflow-run-goal-input"]');
    setNativeValue(goal, ${JSON.stringify(RUN_GOAL)});
  })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="workflow-save-and-run"]')?.disabled, 'enabled save and run');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"workflow-save-and-run\\"]').click()", true);
  await waitFor(win, () => (
    window.location.hash.includes(${JSON.stringify(RUN_ID)})
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_TASK_ID)}
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_SESSION_ID)}
    && document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes(${JSON.stringify(RUN_GOAL)})
    && document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes('Workflow save-and-run UI smoke completed')
  ), 'workflow run detail');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const artifactEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.node.artifact');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.run.completed');
    return events.length === 4
      && eventTypes.includes('workflow.run.started')
      && eventTypes.includes('workflow.node.agent.completed')
      && eventTypes.includes('workflow.node.artifact')
      && eventTypes.includes('workflow.run.completed')
      && sequences.join(',') === '1,2,3,4'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && artifactEvent?.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)})
      && completedEvent?.textContent.includes('Workflow save-and-run UI smoke completed');
  }, 'workflow run replay events');
  await waitFor(win, () => {
    const artifact = document.querySelector('[data-testid="agent-run-detail-artifact"]');
    return artifact
      && artifact.getAttribute('data-artifact-path') === ${JSON.stringify(WORKFLOW_ARTIFACT_PATH)}
      && artifact.getAttribute('data-artifact-source-run-id') === ${JSON.stringify(RUN_ID)};
  }, 'workflow artifact item');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-artifact\\"]').click()", true);
  await waitFor(win, () => {
    const preview = document.querySelector('[data-testid="agent-run-detail-artifact-preview"]');
    return preview
      && preview.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)})
      && preview.textContent.includes('Artifact node output preview.');
  }, 'workflow artifact preview');
  console.log('[electron-smoke] workflow save-and-run detail rendered');

  await win.loadURL('about:blank');
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&approval=1#/agents/workflows');
  await waitFor(win, () => document.querySelector('[data-testid="workflow-studio"]'), 'approval workflow studio');
  await win.webContents.executeJavaScript(\`
  (async () => {
    const setNativeValue = (element, value) => {
      if (!element) throw new Error('missing input for value ' + value);
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    document.querySelector('[data-testid="workflow-new"]').click();
    setNativeValue(document.querySelector('[data-testid="workflow-name-input"]'), 'Workflow Approval Save Run UI Smoke');
    setNativeValue(document.querySelector('[data-testid="workflow-description-input"]'), 'Approval node save-and-run smoke');
    document.querySelector('[data-testid="workflow-add-approval-node"]').click();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    setNativeValue(document.querySelector('[data-testid="workflow-node-approval-criteria-input"]'), ${JSON.stringify(APPROVAL_CRITERIA)});
  })();
  \`, true);
  await waitFor(win, () => {
    const rows = Array.from(document.querySelectorAll('[data-testid="workflow-node-setting-row"]'));
    const criteria = document.querySelector('[data-testid="workflow-node-approval-criteria-input"]');
    const previewSteps = Array.from(document.querySelectorAll('[data-testid="workflow-run-preview-step"]'));
    return rows.length === 1
      && criteria?.value === ${JSON.stringify(APPROVAL_CRITERIA)}
      && previewSteps.some((node) => node.textContent.includes('Approval') || node.textContent.includes('审批'));
  }, 'workflow approval draft ready');
  await win.webContents.executeJavaScript(\`
  (async () => {
    const setNativeValue = (element, value) => {
      if (!element) throw new Error('missing input for value ' + value);
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    document.querySelector('[data-testid="workflow-add-artifact-node"]').click();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    setNativeValue(document.querySelector('[data-testid="workflow-node-artifact-path-input"]'), ${JSON.stringify(APPROVAL_ARTIFACT_PATH)});
  })();
  \`, true);
  await waitFor(win, () => {
    const rows = Array.from(document.querySelectorAll('[data-testid="workflow-node-setting-row"]'));
    const artifactInput = document.querySelector('[data-testid="workflow-node-artifact-path-input"]');
    const previewSteps = Array.from(document.querySelectorAll('[data-testid="workflow-run-preview-step"]'));
    return rows.length === 2
      && artifactInput?.value === ${JSON.stringify(APPROVAL_ARTIFACT_PATH)}
      && previewSteps.some((node) => node.textContent.includes(${JSON.stringify(APPROVAL_ARTIFACT_PATH)}));
  }, 'workflow approval artifact draft ready');
  await win.webContents.executeJavaScript(\`
  (() => {
    const goal = document.querySelector('[data-testid="workflow-run-goal-input"]');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(goal, ${JSON.stringify(APPROVAL_RUN_GOAL)});
    goal.dispatchEvent(new Event('input', { bubbles: true }));
  })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="workflow-save-and-run"]')?.disabled, 'enabled approval workflow save and run');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"workflow-save-and-run\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const approval = document.querySelector('[data-testid="agent-run-detail-approval"]');
    const request = document.querySelector('[data-testid="agent-run-approval-request"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const approvalEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.node.approval_required');
    return window.location.hash.includes(${JSON.stringify(APPROVAL_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'approval_required'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(APPROVAL_SESSION_ID)}
      && approval?.textContent.includes('workflow.approval')
      && request?.textContent.includes(${JSON.stringify(APPROVAL_CRITERIA)})
      && eventTypes.includes('workflow.node.approval_required')
      && approvalEvent?.textContent.includes(${JSON.stringify(APPROVAL_CRITERIA)});
  }, 'workflow approval run detail');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-approval-approve\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const approvalEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.node.approval_approved');
    const artifactEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.node.artifact');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.run.completed');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(APPROVAL_SESSION_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-approval"]')
      && result?.textContent.includes('Workflow approval save-and-run UI smoke completed')
      && eventTypes.includes('workflow.node.approval_required')
      && eventTypes.includes('workflow.node.approval_approved')
      && eventTypes.includes('workflow.node.artifact')
      && eventTypes.includes('workflow.run.completed')
      && sequences.join(',') === '1,2,3,4,5'
      && runIds.every((id) => id === ${JSON.stringify(APPROVAL_RUN_ID)})
      && approvalEvent?.textContent.includes(${JSON.stringify(APPROVAL_CRITERIA)})
      && artifactEvent?.textContent.includes(${JSON.stringify(APPROVAL_ARTIFACT_PATH)})
      && completedEvent?.textContent.includes('Workflow approval save-and-run UI smoke completed');
  }, 'approved workflow replay events');
  await waitFor(win, () => {
    const artifact = document.querySelector('[data-testid="agent-run-detail-artifact"]');
    return artifact
      && artifact.getAttribute('data-artifact-path') === ${JSON.stringify(APPROVAL_ARTIFACT_PATH)}
      && artifact.getAttribute('data-artifact-source-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)};
  }, 'approved workflow artifact item');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-artifact\\"]').click()", true);
  await waitFor(win, () => {
    const preview = document.querySelector('[data-testid="agent-run-detail-artifact-preview"]');
    return preview
      && preview.textContent.includes(${JSON.stringify(APPROVAL_ARTIFACT_PATH)})
      && preview.textContent.includes('Approved artifact preview.');
  }, 'approved workflow artifact preview');
  console.log('[electron-smoke] workflow approval save-and-run detail rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-workflow-save-run-smoke-'));
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
  if (!createdWorkflowRequest) throw new Error('workflow was not saved');
  if (!createdWorkflowRunRequest) throw new Error('workflow run was not created');
  if (!createdApprovalWorkflowRequest) throw new Error('approval workflow was not saved');
  if (!createdApprovalWorkflowRunRequest) throw new Error('approval workflow run was not created');
  if (createdWorkflowRequest.name !== 'Workflow Save Run UI Smoke') {
    throw new Error(`unexpected saved workflow name: ${createdWorkflowRequest.name}`);
  }
  const agentNode = (createdWorkflowRequest.nodes || []).find((node) => node.data?.kind === 'agent');
  if (!agentNode || agentNode.data?.agent_id !== AGENT_ID) {
    throw new Error('saved workflow did not include the selected agent node');
  }
  const artifactNode = (createdWorkflowRequest.nodes || []).find((node) => node.data?.kind === 'artifact');
  if (!artifactNode || artifactNode.data?.artifact_path !== WORKFLOW_ARTIFACT_PATH) {
    throw new Error(`saved workflow did not include artifact node path ${WORKFLOW_ARTIFACT_PATH}`);
  }
  if (createdWorkflowRunRequest.workflow_id !== WORKFLOW_ID) {
    throw new Error(`workflow run used ${createdWorkflowRunRequest.workflow_id} instead of saved workflow id ${WORKFLOW_ID}`);
  }
  if (createdWorkflowRunRequest.user_goal !== RUN_GOAL) {
    throw new Error(`workflow run used unexpected goal: ${createdWorkflowRunRequest.user_goal}`);
  }
  if (!createdWorkflowRunRequest.client_run_id) {
    throw new Error('workflow run request did not include client_run_id');
  }
  const approvalNode = (createdApprovalWorkflowRequest.nodes || []).find((node) => node.data?.kind === 'approval');
  if (!approvalNode || approvalNode.data?.criteria !== APPROVAL_CRITERIA) {
    throw new Error(`saved approval workflow did not include criteria ${APPROVAL_CRITERIA}`);
  }
  const approvalArtifactNode = (createdApprovalWorkflowRequest.nodes || []).find((node) => node.data?.kind === 'artifact');
  if (!approvalArtifactNode || approvalArtifactNode.data?.artifact_path !== APPROVAL_ARTIFACT_PATH) {
    throw new Error(`saved approval workflow did not include artifact node path ${APPROVAL_ARTIFACT_PATH}`);
  }
  if (createdApprovalWorkflowRunRequest.workflow_id !== APPROVAL_WORKFLOW_ID) {
    throw new Error(`approval workflow run used ${createdApprovalWorkflowRunRequest.workflow_id} instead of saved workflow id ${APPROVAL_WORKFLOW_ID}`);
  }
  if (createdApprovalWorkflowRunRequest.user_goal !== APPROVAL_RUN_GOAL) {
    throw new Error(`approval workflow run used unexpected goal: ${createdApprovalWorkflowRunRequest.user_goal}`);
  }
  if (!createdApprovalWorkflowRunRequest.client_run_id) {
    throw new Error('approval workflow run request did not include client_run_id');
  }
  if (!approvalRunApproved) throw new Error('approval workflow approve route was not called');
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
