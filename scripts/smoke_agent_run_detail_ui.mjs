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
const RUN_ID = 'agent_run_detail_ui_smoke';
const APPROVAL_RUN_ID = 'agent_run_detail_ui_smoke_approval';
const WORKFLOW_RUN_ID = 'workflow_run_detail_ui_smoke_child_approval';
const WORKFLOW_CHILD_RUN_ID = 'agent_run_detail_ui_smoke_workflow_child';
const RERUN_RUN_ID = 'agent_run_detail_ui_smoke_rerun';
const RUN_GROUP_ID = 'run_group_detail_ui_smoke';
const WORKFLOW_RUN_GROUP_ID = 'run_group_detail_ui_workflow_child_smoke';
const WORKFLOW_ID = 'workflow-detail-child-approval-smoke';
const ARTIFACT_PATH = 'summary.md';
const WORKFLOW_ARTIFACT_PATH = 'workflow-summary.md';
const ARTIFACT_CONTENT = '# Run Detail UI Smoke\n\nArtifact preview loaded from mock Bridge.';
const now = new Date().toISOString();
let rerunCreated = false;
let approvalApproved = false;
let workflowChildApproved = false;

const run = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'agent',
  task_id: 'task-run-detail-ui-smoke',
  session_id: 'session-run-detail-ui-smoke',
  task_run_link_run_status: 'completed',
  task_run_link_last_event_sequence: 201,
  kind: 'agent_run',
  runnable_id: 'agent-run-detail-smoke',
  runnable_name: 'Run Detail Smoke Agent',
  status: 'completed',
  user_goal: 'Inspect Native RunEvent replay from Agent Studio smoke',
  result: 'Run Detail UI smoke completed through replay facts',
  timeline: [],
  artifacts: [{
    path: ARTIFACT_PATH,
    kind: 'markdown',
    source_run_id: RUN_ID,
    source_runnable_name: 'Run Detail Smoke Agent',
  }],
  created_at: now,
  updated_at: now,
  agent_run_id: RUN_ID,
};

function approvalRun() {
  return {
    run_id: APPROVAL_RUN_ID,
    run_group_id: RUN_GROUP_ID,
    run_group_source: 'agent',
    task_id: 'task-run-detail-ui-smoke-approval',
    session_id: 'session-run-detail-ui-smoke-approval',
    task_run_link_run_status: approvalApproved ? 'completed' : 'approval_required',
    task_run_link_last_event_sequence: approvalApproved ? 5 : 2,
    kind: 'agent_run',
    runnable_id: 'agent-run-detail-smoke',
    runnable_name: 'Run Detail Smoke Agent',
    status: approvalApproved ? 'completed' : 'approval_required',
    user_goal: 'Approve Native Run Detail from Agent Studio smoke',
    result: approvalApproved ? 'Run Detail approval smoke completed' : '',
    pending_approval: approvalApproved ? undefined : {
      approval_id: 'approval-run-detail-ui-smoke',
      tool: 'terminal.run',
      input_preview: {
        command: 'printf run-detail-approval-smoke',
        cwd: '/workspace',
        checkpoint: 'Run Detail approval smoke',
      },
    },
    timeline: [],
    artifacts: [],
    created_at: now,
    updated_at: now,
    agent_run_id: APPROVAL_RUN_ID,
  };
}

function workflowChildRun() {
  return {
    run_id: WORKFLOW_CHILD_RUN_ID,
    run_group_id: WORKFLOW_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: 'task-run-detail-ui-smoke-workflow-child',
    session_id: 'session-run-detail-ui-smoke-workflow-child',
    task_run_link_run_status: workflowChildApproved ? 'completed' : 'approval_required',
    task_run_link_last_event_sequence: workflowChildApproved ? 5 : 2,
    kind: 'agent_run',
    runnable_id: 'agent-run-detail-smoke',
    runnable_name: 'Coding Agent',
    status: workflowChildApproved ? 'completed' : 'approval_required',
    user_goal: 'Approve child Agent from Workflow Run Detail smoke',
    result: workflowChildApproved ? 'Workflow child approval Electron smoke complete' : '',
    pending_approval: workflowChildApproved ? undefined : {
      approval_id: 'approval-workflow-child-detail-ui-smoke',
      tool: 'terminal.run',
      input_preview: {
        command: 'printf workflow-child-electron-approved',
        cwd: '/workspace',
        checkpoint: 'Workflow child approval smoke',
      },
    },
    timeline: [],
    artifacts: [],
    created_at: now,
    updated_at: now,
    agent_run_id: WORKFLOW_CHILD_RUN_ID,
  };
}

function workflowRun() {
  const baseTimeline = [
    {
      event: 'workflow.node.start',
      detail: 'Start',
      status: 'completed',
      workflow_node_id: 'start',
      time: now,
    },
    {
      event: 'workflow.node.agent',
      detail: 'Coding Agent',
      status: workflowChildApproved ? 'completed' : 'approval_required',
      child_run_id: WORKFLOW_CHILD_RUN_ID,
      workflow_node_id: 'agent-1',
      workflow_node_task: 'Approve child Agent from Workflow Run Detail smoke',
      artifact_count: workflowChildApproved ? 1 : 0,
      time: now,
    },
  ];
  return {
    run_id: WORKFLOW_RUN_ID,
    run_group_id: WORKFLOW_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: 'task-run-detail-ui-smoke-workflow',
    session_id: 'session-run-detail-ui-smoke-workflow',
    task_run_link_run_status: workflowChildApproved ? 'completed' : 'approval_required',
    task_run_link_last_event_sequence: workflowChildApproved ? 6 : 3,
    kind: 'workflow_run',
    runnable_id: WORKFLOW_ID,
    runnable_name: 'Run Detail Child Approval Workflow',
    status: workflowChildApproved ? 'completed' : 'approval_required',
    user_goal: 'Approve Workflow child from Run Detail smoke',
    result: workflowChildApproved ? 'Workflow child approval Electron smoke complete' : '',
    timeline: workflowChildApproved
      ? [
          ...baseTimeline,
          {
            event: 'workflow.run.child_resumed',
            detail: 'Coding Agent resumed',
            status: 'completed',
            child_run_id: WORKFLOW_CHILD_RUN_ID,
            time: now,
          },
          {
            event: 'workflow.run.resumed',
            detail: 'Workflow resumed after child approval',
            status: 'completed',
            time: now,
          },
          {
            event: 'workflow.node.artifact',
            detail: WORKFLOW_ARTIFACT_PATH,
            status: 'completed',
            workflow_node_id: 'artifact-1',
            artifact: { path: WORKFLOW_ARTIFACT_PATH },
            time: now,
          },
          {
            event: 'workflow.run.completed',
            detail: 'Workflow child approval Electron smoke complete',
            status: 'completed',
            time: now,
          },
        ]
      : [
          ...baseTimeline,
          {
            event: 'workflow.run.approval_required',
            detail: 'Child Agent approval required',
            status: 'approval_required',
            child_run_id: WORKFLOW_CHILD_RUN_ID,
            pending_approval: workflowChildRun().pending_approval,
            time: now,
          },
        ],
    artifacts: workflowChildApproved ? [{
      path: WORKFLOW_ARTIFACT_PATH,
      kind: 'markdown',
      source_run_id: WORKFLOW_RUN_ID,
      source_runnable_name: 'Run Detail Child Approval Workflow',
    }] : [],
    created_at: now,
    updated_at: now,
    workflow_run_id: WORKFLOW_RUN_ID,
  };
}

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Run Detail UI Smoke',
  source: 'agent',
  status: 'completed',
  summary: 'One completed Agent Run',
  child_run_ids: [APPROVAL_RUN_ID, RUN_ID, RERUN_RUN_ID],
  created_at: now,
  updated_at: now,
};

function workflowRunGroup() {
  return {
    run_group_id: WORKFLOW_RUN_GROUP_ID,
    title: 'Run Detail Workflow Child Smoke',
    source: 'workflow',
    status: workflowChildApproved ? 'completed' : 'approval_required',
    summary: workflowChildApproved ? 'Workflow child approval completed' : 'Workflow waiting for child approval',
    child_run_ids: [WORKFLOW_RUN_ID, WORKFLOW_CHILD_RUN_ID],
    created_at: now,
    updated_at: now,
  };
}

const rerun = {
  ...run,
  run_id: RERUN_RUN_ID,
  task_id: 'task-run-detail-ui-smoke-rerun',
  result: 'Run Detail UI smoke rerun completed',
  task_run_link_last_event_sequence: 2,
  artifacts: [],
  agent_run_id: RERUN_RUN_ID,
};

const runEvents = [
  {
    event_id: 'event-run-detail-smoke-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'agent.run.started',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { goal: run.user_goal },
    created_at: now,
  },
  {
    event_id: 'event-run-detail-smoke-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'agent.tool.call',
    actor: 'tool',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { tool: 'workspace.read', path: 'README.md' },
    created_at: now,
  },
  ...Array.from({ length: 198 }, (_, index) => {
    const sequence = index + 3;
    return {
      event_id: `event-run-detail-smoke-${sequence}`,
      run_id: RUN_ID,
      sequence,
      schema_version: 1,
      event_type: 'model.output.completed',
      actor: 'model',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { chunk: sequence, content: `Replay page smoke event ${sequence}` },
      created_at: now,
    };
  }),
  {
    event_id: 'event-run-detail-smoke-201',
    run_id: RUN_ID,
    sequence: 201,
    schema_version: 1,
    event_type: 'agent.run.completed',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: run.result },
    created_at: now,
  },
];

const rerunEvents = [
  {
    event_id: 'event-run-detail-smoke-rerun-1',
    run_id: RERUN_RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'run.rerun.started',
    actor: 'system',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { source_run_id: RUN_ID },
    created_at: now,
  },
  {
    event_id: 'event-run-detail-smoke-rerun-2',
    run_id: RERUN_RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'agent.run.completed',
    actor: 'agent',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: rerun.result },
    created_at: now,
  },
];

function approvalRunEvents() {
  const events = [
    {
      event_id: 'event-run-detail-approval-smoke-1',
      run_id: APPROVAL_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'agent.run.started',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { goal: 'Approve Native Run Detail from Agent Studio smoke' },
      created_at: now,
    },
    {
      event_id: 'event-run-detail-approval-smoke-2',
      run_id: APPROVAL_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'agent.tool.approval_required',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: 'printf run-detail-approval-smoke' },
      created_at: now,
    },
  ];
  if (!approvalApproved) return events;
  return [
    ...events,
    {
      event_id: 'event-run-detail-approval-smoke-3',
      run_id: APPROVAL_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'agent.tool.approval_approved',
      actor: 'user',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', approval_id: 'approval-run-detail-ui-smoke' },
      created_at: now,
    },
    {
      event_id: 'event-run-detail-approval-smoke-4',
      run_id: APPROVAL_RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'agent.tool.call',
      actor: 'tool',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: 'printf run-detail-approval-smoke' },
      created_at: now,
    },
    {
      event_id: 'event-run-detail-approval-smoke-5',
      run_id: APPROVAL_RUN_ID,
      sequence: 5,
      schema_version: 1,
      event_type: 'agent.run.completed',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: 'Run Detail approval smoke completed' },
      created_at: now,
    },
  ];
}

function workflowRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-child-smoke-1',
      run_id: WORKFLOW_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'workflow.node.start',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { workflow_node_id: 'start', workflow_node_label: 'Start', status: 'completed' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-smoke-2',
      run_id: WORKFLOW_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'workflow.node.agent',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_node_id: 'agent-1',
        workflow_node_label: 'Coding Agent',
        status: workflowChildApproved ? 'completed' : 'approval_required',
        child_run_id: WORKFLOW_CHILD_RUN_ID,
      },
      created_at: now,
    },
  ];
  if (!workflowChildApproved) {
    return [
      ...events,
      {
        event_id: 'event-workflow-child-smoke-3',
        run_id: WORKFLOW_RUN_ID,
        sequence: 3,
        schema_version: 1,
        event_type: 'workflow.run.approval_required',
        actor: 'workflow',
        visibility: 'user',
        sensitivity: 'normal',
        payload: { status: 'approval_required', child_run_id: WORKFLOW_CHILD_RUN_ID },
        created_at: now,
      },
    ];
  }
  return [
    ...events,
    {
      event_id: 'event-workflow-child-smoke-3',
      run_id: WORKFLOW_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'workflow.run.child_resumed',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { status: 'completed', child_run_id: WORKFLOW_CHILD_RUN_ID },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-smoke-4',
      run_id: WORKFLOW_RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'workflow.run.resumed',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { status: 'completed' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-smoke-5',
      run_id: WORKFLOW_RUN_ID,
      sequence: 5,
      schema_version: 1,
      event_type: 'workflow.node.artifact',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_node_id: 'artifact-1',
        workflow_node_label: WORKFLOW_ARTIFACT_PATH,
        status: 'completed',
        artifact: { path: WORKFLOW_ARTIFACT_PATH },
      },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-smoke-6',
      run_id: WORKFLOW_RUN_ID,
      sequence: 6,
      schema_version: 1,
      event_type: 'workflow.run.completed',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: 'Workflow child approval Electron smoke complete' },
      created_at: now,
    },
  ];
}

function workflowChildRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-child-agent-smoke-1',
      run_id: WORKFLOW_CHILD_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'agent.run.started',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { goal: 'Approve child Agent from Workflow Run Detail smoke' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-agent-smoke-2',
      run_id: WORKFLOW_CHILD_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'agent.tool.approval_required',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: 'printf workflow-child-electron-approved' },
      created_at: now,
    },
  ];
  if (!workflowChildApproved) return events;
  return [
    ...events,
    {
      event_id: 'event-workflow-child-agent-smoke-3',
      run_id: WORKFLOW_CHILD_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'agent.tool.approval_approved',
      actor: 'user',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', approval_id: 'approval-workflow-child-detail-ui-smoke' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-agent-smoke-4',
      run_id: WORKFLOW_CHILD_RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'agent.tool.call',
      actor: 'tool',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: 'printf workflow-child-electron-approved' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-agent-smoke-5',
      run_id: WORKFLOW_CHILD_RUN_ID,
      sequence: 5,
      schema_version: 1,
      event_type: 'agent.run.completed',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: 'Workflow child approval Electron smoke complete' },
      created_at: now,
    },
  ];
}

function log(message) {
  process.stdout.write(`[agent-run-detail-ui-smoke] ${message}\n`);
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
  const server = http.createServer((request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, {
          agents: [{
            agent_id: 'agent-run-detail-smoke',
            name: 'Run Detail Smoke Agent',
            model_mode: 'follow_main',
            execution_backend: 'native_profile',
            model_config: {},
            enabled: true,
            editable: true,
            deletable: true,
          }],
        });
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
            profile_id: 'profile-run-detail-smoke',
            name: 'Run Detail Smoke Chat Profile',
            capability: 'chat',
            provider: 'openai_compatible',
            enabled: true,
            api_key_configured: true,
            status: 'available',
          }],
          defaults: { chat: 'profile-run-detail-smoke' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/workflows') {
        sendJson(response, 200, {
          workflows: [{
            workflow_id: WORKFLOW_ID,
            name: 'Run Detail Child Approval Workflow',
            description: 'Workflow child approval smoke',
            enabled: true,
            nodes: [
              { id: 'start', type: 'input', data: { kind: 'start', label: 'Start' } },
              { id: 'agent-1', type: 'default', data: { kind: 'agent', label: 'Coding Agent', agent_id: 'agent-run-detail-smoke', task: 'Approve child Agent from Workflow Run Detail smoke' } },
              { id: 'artifact-1', type: 'output', data: { kind: 'artifact', label: WORKFLOW_ARTIFACT_PATH, path: WORKFLOW_ARTIFACT_PATH } },
            ],
            edges: [],
            created_at: now,
            updated_at: now,
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [
            {
              id: 'agent-run-detail-smoke',
              name: 'Run Detail Smoke Agent',
              kind: 'agent',
              enabled: true,
              output_contract: 'report',
            },
            {
              id: WORKFLOW_ID,
              name: 'Run Detail Child Approval Workflow',
              kind: 'workflow',
              enabled: true,
              output_contract: 'report',
            },
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: rerunCreated ? [rerun, workflowRun(), run, approvalRun()] : [workflowRun(), run, approvalRun()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_RUN_ID}`) {
        sendJson(response, 200, workflowRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_CHILD_RUN_ID}`) {
        sendJson(response, 200, workflowChildRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${APPROVAL_RUN_ID}`) {
        sendJson(response, 200, approvalRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, run);
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${APPROVAL_RUN_ID}/approval/approve`) {
        approvalApproved = true;
        sendJson(response, 200, approvalRun());
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${WORKFLOW_CHILD_RUN_ID}/approval/approve`) {
        workflowChildApproved = true;
        sendJson(response, 200, workflowChildRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RERUN_RUN_ID}`) {
        sendJson(response, rerunCreated ? 200 : 404, rerunCreated ? rerun : { ok: false, error: 'rerun not created' });
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${RUN_ID}/rerun`) {
        rerunCreated = true;
        sendJson(response, 200, rerun);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}/artifacts/${ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          path: ARTIFACT_PATH,
          content: ARTIFACT_CONTENT,
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_RUN_ID}/artifacts/${WORKFLOW_ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          path: WORKFLOW_ARTIFACT_PATH,
          content: '# Workflow Child Approval Smoke\n\nWorkflow child approval artifact preview.',
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [workflowRunGroup(), runGroup] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${WORKFLOW_RUN_GROUP_ID}`) {
        sendJson(response, 200, workflowRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/runs/${RUN_ID}/events`) {
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
      if (request.method === 'GET' && url.pathname === `/runs/${WORKFLOW_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: WORKFLOW_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: workflowRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/runs/${WORKFLOW_CHILD_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: WORKFLOW_CHILD_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: workflowChildRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/runs/${APPROVAL_RUN_ID}/events`) {
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
      if (request.method === 'GET' && url.pathname === `/runs/${RERUN_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, rerunCreated ? 200 : 404, rerunCreated ? {
          run_id: RERUN_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: rerunEvents.filter((event) => event.sequence > afterSequence).slice(0, limit),
        } : { ok: false, error: 'rerun not created' });
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
const approvalRunId = ${JSON.stringify(APPROVAL_RUN_ID)};
const workflowRunId = ${JSON.stringify(WORKFLOW_RUN_ID)};
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(approvalRunId));
  console.log('[electron-smoke] approval run detail loaded');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}, 'approval run detail article');
  await waitFor(win, () => {
    const approval = document.querySelector('[data-testid="agent-run-detail-approval"]');
    const request = document.querySelector('[data-testid="agent-run-approval-request"]');
    const approve = document.querySelector('[data-testid="agent-run-detail-approval-approve"]');
    const reject = document.querySelector('[data-testid="agent-run-detail-approval-reject"]');
    return approval
      && request?.textContent.includes('terminal.run')
      && request?.textContent.includes('printf run-detail-approval-smoke')
      && approve
      && reject
      && !approve.disabled;
  }, 'approval action box');
  console.log('[electron-smoke] approval box rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-approval-approve\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-approval"]')
      && result?.textContent.includes('Run Detail approval smoke completed')
      && eventTypes.includes('agent.tool.approval_required')
      && eventTypes.includes('agent.tool.approval_approved')
      && eventTypes.includes('agent.tool.call')
      && eventTypes.includes('agent.run.completed')
      && sequences.join(',') === '1,2,3,4,5'
      && runIds.every((id) => id === ${JSON.stringify(APPROVAL_RUN_ID)});
  }, 'approved run detail replay');
  console.log('[electron-smoke] approval action completed');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(workflowRunId));
  console.log('[electron-smoke] workflow child approval run detail loaded');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_RUN_ID)}, 'workflow parent run detail article');
  await waitFor(win, () => {
    const childApproval = document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]');
    const request = childApproval?.querySelector('[data-testid="agent-run-approval-request"]');
    const approve = document.querySelector('[data-testid="agent-run-detail-workflow-child-approve"]');
    const reject = document.querySelector('[data-testid="agent-run-detail-workflow-child-reject"]');
    const cancel = document.querySelector('[data-testid="agent-run-detail-workflow-child-cancel"]');
    const openRun = document.querySelector('[data-testid="agent-run-detail-workflow-child-open-run"]');
    return childApproval
      && childApproval.textContent.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)})
      && request?.textContent.includes('terminal.run')
      && request?.textContent.includes('printf workflow-child-electron-approved')
      && approve
      && reject
      && cancel
      && openRun
      && !approve.disabled;
  }, 'workflow child approval bridge');
  console.log('[electron-smoke] workflow child approval bridge rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-workflow-child-approve\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const steps = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-workflow-step"]'));
    const openStepRun = document.querySelector('[data-testid="agent-run-detail-workflow-step-open-run"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_RUN_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]')
      && result?.textContent.includes('Workflow child approval Electron smoke complete')
      && steps.some((node) => node.getAttribute('data-child-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)} && node.getAttribute('data-workflow-step-status') === 'completed')
      && steps.some((node) => node.getAttribute('data-workflow-step-kind') === 'artifact' && node.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)}))
      && openStepRun
      && !openStepRun.disabled
      && eventTypes.includes('workflow.run.child_resumed')
      && eventTypes.includes('workflow.run.resumed')
      && eventTypes.includes('workflow.node.artifact')
      && eventTypes.includes('workflow.run.completed')
      && runIds.every((id) => id === ${JSON.stringify(WORKFLOW_RUN_ID)});
  }, 'workflow child approval completed parent detail');
  console.log('[electron-smoke] workflow child approval completed parent detail');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-workflow-step-open-run\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return window.location.hash.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}
      && document.querySelector('[data-testid="agent-run-detail-open-parent-run"]')
      && result?.textContent.includes('Workflow child approval Electron smoke complete')
      && eventTypes.includes('agent.tool.approval_required')
      && eventTypes.includes('agent.tool.approval_approved')
      && eventTypes.includes('agent.tool.call')
      && eventTypes.includes('agent.run.completed')
      && runIds.every((id) => id === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)});
  }, 'workflow child run detail replay');
  console.log('[electron-smoke] workflow child run detail rendered');

  await win.loadURL('about:blank');
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(runId));
  console.log('[electron-smoke] run detail loaded');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}, 'run detail article');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes('Inspect Native RunEvent replay'), 'run task block');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes('Run Detail UI smoke completed through replay facts'), 'run result block');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return events.length === 200
      && eventTypes.includes('agent.run.started')
      && eventTypes.includes('agent.tool.call')
      && !eventTypes.includes('agent.run.completed')
      && sequences[0] === '1'
      && sequences[199] === '200'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && document.querySelector('[data-testid="agent-run-detail-load-more-events"]');
  }, 'initial run event replay page');
  console.log('[electron-smoke] initial replay page rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-load-more-events\\"]').click()", true);
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return events.length === 201
      && eventTypes.includes('agent.run.completed')
      && sequences[200] === '201'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && !document.querySelector('[data-testid="agent-run-detail-load-more-events"]');
  }, 'loaded more run event replay page');
  console.log('[electron-smoke] replay pagination loaded');
  await waitFor(win, () => {
    const artifact = document.querySelector('[data-testid="agent-run-detail-artifact"]');
    return artifact
      && artifact.getAttribute('data-artifact-path') === ${JSON.stringify(ARTIFACT_PATH)}
      && artifact.getAttribute('data-artifact-source-run-id') === ${JSON.stringify(RUN_ID)};
  }, 'run detail artifact item');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-artifact\\"]').click()", true);
  await waitFor(win, () => {
    const preview = document.querySelector('[data-testid="agent-run-detail-artifact-preview"]');
    return preview
      && preview.textContent.includes(${JSON.stringify(ARTIFACT_PATH)})
      && preview.textContent.includes('Artifact preview loaded from mock Bridge.');
  }, 'run detail artifact preview');
  console.log('[electron-smoke] artifact preview rendered');
  await waitFor(win, () => !document.querySelector('[data-testid="agent-run-detail-rerun"]')?.disabled, 'enabled rerun button');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-rerun\\"]').click()", true);
  await waitFor(win, () => (
    window.location.hash.includes(${JSON.stringify(RERUN_RUN_ID)})
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(RERUN_RUN_ID)}
    && document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes('Run Detail UI smoke rerun completed')
  ), 'rerun run detail');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    return events.length === 2
      && eventTypes.includes('run.rerun.started')
      && eventTypes.includes('agent.run.completed')
      && sequences.join(',') === '1,2'
      && runIds.every((id) => id === ${JSON.stringify(RERUN_RUN_ID)});
  }, 'rerun replay events');
  console.log('[electron-smoke] rerun detail rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-agent-run-detail-smoke-'));
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

async function main() {
  const bridge = await startMockBridge();
  const vitePort = await pickPort();
  const vite = startVite(vitePort);
  try {
    const devUrl = `http://127.0.0.1:${vitePort}`;
    await waitForHttp(devUrl);
    await runElectronSmoke(devUrl, bridge.url);
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
