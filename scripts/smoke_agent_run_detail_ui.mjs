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
const WORKFLOW_REJECT_RUN_ID = 'workflow_run_detail_ui_smoke_child_reject';
const WORKFLOW_REJECT_CHILD_RUN_ID = 'agent_run_detail_ui_smoke_workflow_child_reject';
const WORKFLOW_CANCEL_RUN_ID = 'workflow_run_detail_ui_smoke_child_cancel';
const WORKFLOW_CANCEL_CHILD_RUN_ID = 'agent_run_detail_ui_smoke_workflow_child_cancel';
const ACTIVE_CANCEL_RUN_ID = 'agent_run_detail_ui_smoke_active_cancel';
const RERUN_RUN_ID = 'agent_run_detail_ui_smoke_rerun';
const RUN_TASK_ID = 'task-run-detail-ui-smoke';
const RUN_SESSION_ID = 'session-run-detail-ui-smoke';
const APPROVAL_TASK_ID = 'task-run-detail-ui-smoke-approval';
const APPROVAL_SESSION_ID = 'session-run-detail-ui-smoke-approval';
const ACTIVE_CANCEL_TASK_ID = 'task-run-detail-ui-smoke-active-cancel';
const ACTIVE_CANCEL_SESSION_ID = 'session-run-detail-ui-smoke-active-cancel';
const RERUN_TASK_ID = 'task-run-detail-ui-smoke-rerun';
const WORKFLOW_TASK_ID = 'task-run-detail-ui-smoke-workflow';
const WORKFLOW_SESSION_ID = 'session-run-detail-ui-smoke-workflow';
const WORKFLOW_CHILD_TASK_ID = 'task-run-detail-ui-smoke-workflow-child';
const WORKFLOW_CHILD_SESSION_ID = 'session-run-detail-ui-smoke-workflow-child';
const WORKFLOW_REJECT_TASK_ID = 'task-run-detail-ui-smoke-workflow-reject';
const WORKFLOW_REJECT_SESSION_ID = 'session-run-detail-ui-smoke-workflow-reject';
const WORKFLOW_REJECT_CHILD_TASK_ID = 'task-run-detail-ui-smoke-workflow-child-reject';
const WORKFLOW_REJECT_CHILD_SESSION_ID = 'session-run-detail-ui-smoke-workflow-child-reject';
const WORKFLOW_CANCEL_TASK_ID = 'task-run-detail-ui-smoke-workflow-cancel';
const WORKFLOW_CANCEL_SESSION_ID = 'session-run-detail-ui-smoke-workflow-cancel';
const WORKFLOW_CANCEL_CHILD_TASK_ID = 'task-run-detail-ui-smoke-workflow-child-cancel';
const WORKFLOW_CANCEL_CHILD_SESSION_ID = 'session-run-detail-ui-smoke-workflow-child-cancel';
const RUN_GROUP_ID = 'run_group_detail_ui_smoke';
const WORKFLOW_RUN_GROUP_ID = 'run_group_detail_ui_workflow_child_smoke';
const WORKFLOW_REJECT_RUN_GROUP_ID = 'run_group_detail_ui_workflow_child_reject_smoke';
const WORKFLOW_CANCEL_RUN_GROUP_ID = 'run_group_detail_ui_workflow_child_cancel_smoke';
const WORKFLOW_ID = 'workflow-detail-child-approval-smoke';
const ARTIFACT_PATH = 'summary.md';
const WORKFLOW_ARTIFACT_PATH = 'workflow-summary.md';
const ARTIFACT_CONTENT = '# Run Detail UI Smoke\n\nArtifact preview loaded from mock Bridge.';
const now = new Date().toISOString();
let rerunCreated = false;
let approvalApproved = false;
let workflowChildApproved = false;
let workflowChildRejected = false;
let workflowChildCancelled = false;
let activeRunCancelled = false;
const runEventRequests = [];
const deletedRunIds = [];

const run = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'agent',
  task_id: RUN_TASK_ID,
  session_id: RUN_SESSION_ID,
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
    task_id: APPROVAL_TASK_ID,
    session_id: APPROVAL_SESSION_ID,
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
    task_id: WORKFLOW_CHILD_TASK_ID,
    session_id: WORKFLOW_CHILD_SESSION_ID,
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
    task_id: WORKFLOW_TASK_ID,
    session_id: WORKFLOW_SESSION_ID,
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

function activeCancelRun() {
  return {
    run_id: ACTIVE_CANCEL_RUN_ID,
    run_group_id: RUN_GROUP_ID,
    run_group_source: 'agent',
    task_id: ACTIVE_CANCEL_TASK_ID,
    session_id: ACTIVE_CANCEL_SESSION_ID,
    task_run_link_run_status: activeRunCancelled ? 'cancelled' : 'running',
    task_run_link_last_event_sequence: activeRunCancelled ? 2 : 1,
    kind: 'agent_run',
    runnable_id: 'agent-run-detail-smoke',
    runnable_name: 'Run Detail Smoke Agent',
    status: activeRunCancelled ? 'cancelled' : 'running',
    user_goal: 'Cancel active Agent Run from Run Detail smoke',
    result: activeRunCancelled ? 'Run Detail active Run cancelled from UI smoke' : '',
    timeline: activeRunCancelled
      ? [
          { event: 'agent.run.started', status: 'running', detail: 'Cancel active Agent Run from Run Detail smoke', time: now },
          { event: 'agent.run.cancelled', status: 'cancelled', detail: 'Run Detail active Run cancelled from UI smoke', time: now },
        ]
      : [
          { event: 'agent.run.started', status: 'running', detail: 'Cancel active Agent Run from Run Detail smoke', time: now },
        ],
    artifacts: [],
    created_at: now,
    updated_at: activeRunCancelled ? new Date(Date.now() + 1000).toISOString() : now,
    agent_run_id: ACTIVE_CANCEL_RUN_ID,
  };
}

function runGroup() {
  return {
    run_group_id: RUN_GROUP_ID,
    title: 'Run Detail UI Smoke',
    source: 'agent',
    status: activeRunCancelled ? 'completed' : 'running',
    summary: activeRunCancelled ? 'Active Run cancelled and completed runs remain' : 'One active Agent Run',
    child_run_ids: [ACTIVE_CANCEL_RUN_ID, APPROVAL_RUN_ID, RUN_ID, RERUN_RUN_ID],
    created_at: now,
    updated_at: activeRunCancelled ? new Date(Date.now() + 1000).toISOString() : now,
  };
}

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

function workflowRejectChildRun() {
  return {
    run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
    run_group_id: WORKFLOW_REJECT_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: WORKFLOW_REJECT_CHILD_TASK_ID,
    session_id: WORKFLOW_REJECT_CHILD_SESSION_ID,
    task_run_link_run_status: workflowChildRejected ? 'cancelled' : 'approval_required',
    task_run_link_last_event_sequence: workflowChildRejected ? 4 : 2,
    kind: 'agent_run',
    runnable_id: 'agent-run-detail-smoke',
    runnable_name: 'Coding Agent',
    status: workflowChildRejected ? 'cancelled' : 'approval_required',
    user_goal: 'Reject child Agent approval from Workflow Run Detail smoke',
    result: workflowChildRejected ? 'Workflow child approval rejected from Electron smoke' : '',
    pending_approval: workflowChildRejected ? undefined : {
      approval_id: 'approval-workflow-child-reject-detail-ui-smoke',
      tool: 'terminal.run',
      input_preview: {
        command: 'printf workflow-child-electron-rejected',
        cwd: '/workspace',
        checkpoint: 'Workflow child reject smoke',
      },
    },
    timeline: [],
    artifacts: [],
    created_at: now,
    updated_at: now,
    agent_run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
  };
}

function workflowRejectRun() {
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
      status: workflowChildRejected ? 'cancelled' : 'approval_required',
      child_run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
      workflow_node_id: 'agent-reject',
      workflow_node_task: 'Reject child Agent approval from Workflow Run Detail smoke',
      artifact_count: 0,
      time: now,
    },
  ];
  return {
    run_id: WORKFLOW_REJECT_RUN_ID,
    run_group_id: WORKFLOW_REJECT_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: WORKFLOW_REJECT_TASK_ID,
    session_id: WORKFLOW_REJECT_SESSION_ID,
    task_run_link_run_status: workflowChildRejected ? 'cancelled' : 'approval_required',
    task_run_link_last_event_sequence: 3,
    kind: 'workflow_run',
    runnable_id: WORKFLOW_ID,
    runnable_name: 'Run Detail Child Reject Workflow',
    status: workflowChildRejected ? 'cancelled' : 'approval_required',
    user_goal: 'Reject Workflow child from Run Detail smoke',
    result: workflowChildRejected ? 'Workflow child approval rejected from Electron smoke' : '',
    timeline: workflowChildRejected
      ? [
          ...baseTimeline,
          {
            event: 'workflow.run.cancelled',
            detail: 'Workflow child approval rejected from Electron smoke',
            status: 'cancelled',
            child_run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
            time: now,
          },
        ]
      : [
          ...baseTimeline,
          {
            event: 'workflow.run.approval_required',
            detail: 'Child Agent approval required',
            status: 'approval_required',
            child_run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
            pending_approval: workflowRejectChildRun().pending_approval,
            time: now,
          },
        ],
    artifacts: [],
    created_at: now,
    updated_at: now,
    workflow_run_id: WORKFLOW_REJECT_RUN_ID,
  };
}

function workflowRejectRunGroup() {
  return {
    run_group_id: WORKFLOW_REJECT_RUN_GROUP_ID,
    title: 'Run Detail Workflow Child Reject Smoke',
    source: 'workflow',
    status: workflowChildRejected ? 'cancelled' : 'approval_required',
    summary: workflowChildRejected ? 'Workflow child approval rejected' : 'Workflow waiting for child rejection smoke',
    child_run_ids: [WORKFLOW_REJECT_RUN_ID, WORKFLOW_REJECT_CHILD_RUN_ID],
    created_at: now,
    updated_at: now,
  };
}

function workflowCancelChildRun() {
  return {
    run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
    run_group_id: WORKFLOW_CANCEL_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: WORKFLOW_CANCEL_CHILD_TASK_ID,
    session_id: WORKFLOW_CANCEL_CHILD_SESSION_ID,
    task_run_link_run_status: workflowChildCancelled ? 'cancelled' : 'approval_required',
    task_run_link_last_event_sequence: workflowChildCancelled ? 3 : 2,
    kind: 'agent_run',
    runnable_id: 'agent-run-detail-smoke',
    runnable_name: 'Coding Agent',
    status: workflowChildCancelled ? 'cancelled' : 'approval_required',
    user_goal: 'Cancel child Agent from Workflow Run Detail smoke',
    result: workflowChildCancelled ? 'Workflow child run cancelled from Electron smoke' : '',
    pending_approval: workflowChildCancelled ? undefined : {
      approval_id: 'approval-workflow-child-cancel-detail-ui-smoke',
      tool: 'terminal.run',
      input_preview: {
        command: 'printf workflow-child-electron-cancelled',
        cwd: '/workspace',
        checkpoint: 'Workflow child cancel smoke',
      },
    },
    timeline: [],
    artifacts: [],
    created_at: now,
    updated_at: now,
    agent_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
  };
}

function workflowCancelRun() {
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
      status: workflowChildCancelled ? 'cancelled' : 'approval_required',
      child_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
      workflow_node_id: 'agent-cancel',
      workflow_node_task: 'Cancel child Agent from Workflow Run Detail smoke',
      artifact_count: 0,
      time: now,
    },
  ];
  return {
    run_id: WORKFLOW_CANCEL_RUN_ID,
    run_group_id: WORKFLOW_CANCEL_RUN_GROUP_ID,
    run_group_source: 'workflow',
    task_id: WORKFLOW_CANCEL_TASK_ID,
    session_id: WORKFLOW_CANCEL_SESSION_ID,
    task_run_link_run_status: workflowChildCancelled ? 'cancelled' : 'approval_required',
    task_run_link_last_event_sequence: 3,
    kind: 'workflow_run',
    runnable_id: WORKFLOW_ID,
    runnable_name: 'Run Detail Child Cancel Workflow',
    status: workflowChildCancelled ? 'cancelled' : 'approval_required',
    user_goal: 'Cancel Workflow child from Run Detail smoke',
    result: workflowChildCancelled ? 'Workflow child run cancelled from Electron smoke' : '',
    timeline: workflowChildCancelled
      ? [
          ...baseTimeline,
          {
            event: 'workflow.run.cancelled',
            detail: 'Workflow child run cancelled from Electron smoke',
            status: 'cancelled',
            child_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
            time: now,
          },
        ]
      : [
          ...baseTimeline,
          {
            event: 'workflow.run.approval_required',
            detail: 'Child Agent approval required',
            status: 'approval_required',
            child_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
            pending_approval: workflowCancelChildRun().pending_approval,
            time: now,
          },
        ],
    artifacts: [],
    created_at: now,
    updated_at: now,
    workflow_run_id: WORKFLOW_CANCEL_RUN_ID,
  };
}

function workflowCancelRunGroup() {
  return {
    run_group_id: WORKFLOW_CANCEL_RUN_GROUP_ID,
    title: 'Run Detail Workflow Child Cancel Smoke',
    source: 'workflow',
    status: workflowChildCancelled ? 'cancelled' : 'approval_required',
    summary: workflowChildCancelled ? 'Workflow child run cancelled' : 'Workflow waiting for child cancel smoke',
    child_run_ids: [WORKFLOW_CANCEL_RUN_ID, WORKFLOW_CANCEL_CHILD_RUN_ID],
    created_at: now,
    updated_at: now,
  };
}

const rerun = {
  ...run,
  run_id: RERUN_RUN_ID,
  task_id: RERUN_TASK_ID,
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
  {
    event_id: 'event-run-detail-smoke-3',
    run_id: RUN_ID,
    sequence: 3,
    schema_version: 1,
    event_type: 'memory.retrieved',
    actor: 'runtime',
    visibility: 'user',
    sensitivity: 'normal',
    payload: {
      count: 1,
      group_run_id: RUN_GROUP_ID,
      member_agent_id: 'agent-run-detail-smoke',
      memories: [{
        memory_id: 'memory-run-detail-smoke',
        kind: 'preference',
        scope: 'global',
        content: 'Run Detail smoke preference memory',
      }],
      status: 'completed',
    },
    created_at: now,
  },
  {
    event_id: 'event-run-detail-smoke-4',
    run_id: RUN_ID,
    sequence: 4,
    schema_version: 1,
    event_type: 'skill.dispatch.read',
    actor: 'runtime',
    visibility: 'user',
    sensitivity: 'normal',
    payload: {
      group_run_id: RUN_GROUP_ID,
      member_agent_id: 'agent-run-detail-smoke',
      status: 'completed',
      tool: 'skill.read',
      result: {
        skill_id: 'skill-run-detail-smoke',
        name: 'Run Detail Smoke Skill',
        description: 'Loads smoke skill instructions',
        source_ref: 'skills/run-detail-smoke/SKILL.md',
        source_type: 'native',
      },
    },
    created_at: now,
  },
  ...Array.from({ length: 196 }, (_, index) => {
    const sequence = index + 5;
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

function activeCancelRunEvents() {
  const events = [
    {
      event_id: 'event-run-detail-active-cancel-smoke-1',
      run_id: ACTIVE_CANCEL_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'agent.run.started',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { goal: 'Cancel active Agent Run from Run Detail smoke' },
      created_at: now,
    },
  ];
  if (!activeRunCancelled) return events;
  return [
    ...events,
    {
      event_id: 'event-run-detail-active-cancel-smoke-2',
      run_id: ACTIVE_CANCEL_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'agent.run.cancelled',
      actor: 'runtime',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: 'Run Detail active Run cancelled from UI smoke' },
      created_at: now,
    },
  ];
}

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

function workflowRejectRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-child-reject-smoke-1',
      run_id: WORKFLOW_REJECT_RUN_ID,
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
      event_id: 'event-workflow-child-reject-smoke-2',
      run_id: WORKFLOW_REJECT_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'workflow.node.agent',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_node_id: 'agent-reject',
        workflow_node_label: 'Coding Agent',
        status: workflowChildRejected ? 'cancelled' : 'approval_required',
        child_run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
      },
      created_at: now,
    },
  ];
  if (!workflowChildRejected) {
    return [
      ...events,
      {
        event_id: 'event-workflow-child-reject-smoke-3',
        run_id: WORKFLOW_REJECT_RUN_ID,
        sequence: 3,
        schema_version: 1,
        event_type: 'workflow.run.approval_required',
        actor: 'workflow',
        visibility: 'user',
        sensitivity: 'normal',
        payload: { status: 'approval_required', child_run_id: WORKFLOW_REJECT_CHILD_RUN_ID },
        created_at: now,
      },
    ];
  }
  return [
    ...events,
    {
      event_id: 'event-workflow-child-reject-smoke-3',
      run_id: WORKFLOW_REJECT_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'workflow.run.cancelled',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { status: 'cancelled', child_run_id: WORKFLOW_REJECT_CHILD_RUN_ID },
      created_at: now,
    },
  ];
}

function workflowRejectChildRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-child-reject-agent-smoke-1',
      run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'agent.run.started',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { goal: 'Reject child Agent approval from Workflow Run Detail smoke' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-reject-agent-smoke-2',
      run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'agent.tool.approval_required',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: 'printf workflow-child-electron-rejected' },
      created_at: now,
    },
  ];
  if (!workflowChildRejected) return events;
  return [
    ...events,
    {
      event_id: 'event-workflow-child-reject-agent-smoke-3',
      run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'agent.tool.approval_rejected',
      actor: 'user',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', approval_id: 'approval-workflow-child-reject-detail-ui-smoke' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-reject-agent-smoke-4',
      run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'agent.run.cancelled',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: 'Workflow child approval rejected from Electron smoke' },
      created_at: now,
    },
  ];
}

function workflowCancelRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-child-cancel-smoke-1',
      run_id: WORKFLOW_CANCEL_RUN_ID,
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
      event_id: 'event-workflow-child-cancel-smoke-2',
      run_id: WORKFLOW_CANCEL_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'workflow.node.agent',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: {
        workflow_node_id: 'agent-cancel',
        workflow_node_label: 'Coding Agent',
        status: workflowChildCancelled ? 'cancelled' : 'approval_required',
        child_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
      },
      created_at: now,
    },
  ];
  if (!workflowChildCancelled) {
    return [
      ...events,
      {
        event_id: 'event-workflow-child-cancel-smoke-3',
        run_id: WORKFLOW_CANCEL_RUN_ID,
        sequence: 3,
        schema_version: 1,
        event_type: 'workflow.run.approval_required',
        actor: 'workflow',
        visibility: 'user',
        sensitivity: 'normal',
        payload: { status: 'approval_required', child_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID },
        created_at: now,
      },
    ];
  }
  return [
    ...events,
    {
      event_id: 'event-workflow-child-cancel-smoke-3',
      run_id: WORKFLOW_CANCEL_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'workflow.run.cancelled',
      actor: 'workflow',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { status: 'cancelled', child_run_id: WORKFLOW_CANCEL_CHILD_RUN_ID },
      created_at: now,
    },
  ];
}

function workflowCancelChildRunEvents() {
  const events = [
    {
      event_id: 'event-workflow-child-cancel-agent-smoke-1',
      run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'agent.run.started',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { goal: 'Cancel child Agent from Workflow Run Detail smoke' },
      created_at: now,
    },
    {
      event_id: 'event-workflow-child-cancel-agent-smoke-2',
      run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'agent.tool.approval_required',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: 'printf workflow-child-electron-cancelled' },
      created_at: now,
    },
  ];
  if (!workflowChildCancelled) return events;
  return [
    ...events,
    {
      event_id: 'event-workflow-child-cancel-agent-smoke-3',
      run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'agent.run.cancelled',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { result: 'Workflow child run cancelled from Electron smoke' },
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
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS,DELETE',
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

function currentRuns() {
  const runs = [activeCancelRun(), workflowCancelRun(), workflowRejectRun(), workflowRun(), run, approvalRun()];
  return (rerunCreated ? [rerun, ...runs] : runs).filter((item) => !deletedRunIds.includes(item.run_id));
}

function currentRunById(runId) {
  const runs = [
    activeCancelRun(),
    workflowCancelRun(),
    workflowCancelChildRun(),
    workflowRejectRun(),
    workflowRejectChildRun(),
    workflowRun(),
    workflowChildRun(),
    approvalRun(),
    run,
    rerun,
  ];
  return runs.find((item) => item.run_id === runId && !deletedRunIds.includes(item.run_id)) || null;
}

function publicRunSnapshot(item) {
  const isWorkflow = item.kind === 'workflow_run';
  const parentRunId = workflowParentRunId(item.run_id);
  const pendingApproval = publicPendingApproval(item);
  return {
    run_id: item.run_id,
    parent_run_id: parentRunId || null,
    group_run_id: item.run_group_id || null,
    run_group_id: item.run_group_id || null,
    workflow_run_id: isWorkflow ? item.run_id : parentRunId || null,
    workflow_id: isWorkflow ? item.runnable_id : null,
    agent_id: isWorkflow ? null : item.runnable_id,
    status: item.status,
    title: item.runnable_name || item.runnable_id || item.run_id,
    task_id: item.task_id || null,
    session_id: item.session_id || null,
    task_run_link_run_status: item.task_run_link_run_status || null,
    task_run_link_last_event_sequence: item.task_run_link_last_event_sequence ?? null,
    events: publicRunEvents(item.run_id),
    tool_calls: [],
    approvals: pendingApproval ? [pendingApproval] : [],
    pending_approval: pendingApproval,
    artifacts: publicArtifacts(item),
    children: publicRunChildren(item),
    objective: item.user_goal || '',
    current_node_id: isWorkflow && item.status === 'approval_required' ? 'agent-1' : null,
    current_node_label: isWorkflow && item.status === 'approval_required' ? 'Coding Agent' : null,
    final_answer: item.result || '',
    created_at: item.created_at || now,
    updated_at: item.updated_at || item.created_at || now,
  };
}

function publicPendingApproval(item) {
  const pending = item.pending_approval;
  if (!pending) return null;
  return {
    approval_id: pending.approval_id || item.run_id,
    run_id: pending.run_id || item.run_id,
    source_run_id: item.run_id,
    source_runnable_id: item.runnable_id || null,
    source_runnable_name: item.runnable_name || null,
    workflow_run_id: workflowParentRunId(item.run_id) || null,
    title: `Approve ${pending.tool || 'tool'}`,
    description: null,
    status: pending.status || 'pending',
    tool_name: pending.tool || 'tool',
    risk_level: pending.risk_level || 'high',
    input_preview: typeof pending.input_preview === 'string'
      ? { preview: pending.input_preview }
      : pending.input_preview || {},
    policy_reason: pending.policy_reason || null,
    requested_at: pending.requested_at || now,
    resolved_at: pending.resolved_at || null,
    open_in_studio_url: pending.open_in_studio_url || null,
  };
}

function publicArtifacts(item) {
  return (item.artifacts || []).map((artifact, index) => ({
    artifact_id: artifact.artifact_id || `${item.run_id}:${artifact.path || artifact.kind || index}`,
    run_id: item.run_id,
    source_run_id: artifact.source_run_id || item.run_id,
    source_tool: artifact.source_tool || null,
    source_runnable_id: item.runnable_id || null,
    source_runnable_name: artifact.source_runnable_name || item.runnable_name || null,
    workflow_id: item.kind === 'workflow_run' ? item.runnable_id : null,
    workflow_run_id: item.kind === 'workflow_run' ? item.run_id : workflowParentRunId(item.run_id) || null,
    group_run_id: item.run_group_id || null,
    title: artifact.title || artifact.path || artifact.kind || 'Artifact',
    kind: artifact.kind || 'artifact',
    path: artifact.path || null,
    mime_type: artifact.mime_type || null,
    size_bytes: artifact.size_bytes ?? null,
    preview_text: artifact.preview_text || null,
    url: artifact.url || null,
    created_at: artifact.created_at || item.updated_at || now,
  }));
}

function publicRunChildren(item) {
  if (item.run_id === WORKFLOW_RUN_ID) return [publicRunChild(workflowChildRun())];
  if (item.run_id === WORKFLOW_REJECT_RUN_ID) return [publicRunChild(workflowRejectChildRun())];
  if (item.run_id === WORKFLOW_CANCEL_RUN_ID) return [publicRunChild(workflowCancelChildRun())];
  return [];
}

function publicRunChild(item) {
  const parentRunId = workflowParentRunId(item.run_id);
  return {
    run_id: item.run_id,
    title: item.runnable_name || item.runnable_id || item.run_id,
    status: item.status,
    kind: item.kind,
    parent_run_id: parentRunId || null,
    group_run_id: item.run_group_id || null,
    run_group_id: item.run_group_id || null,
    workflow_run_id: parentRunId || null,
    workflow_node_id: 'agent-1',
    workflow_node_label: 'Coding Agent',
    agent_id: item.runnable_id || null,
    workflow_id: null,
  };
}

function workflowParentRunId(runId) {
  if (runId === WORKFLOW_CHILD_RUN_ID) return WORKFLOW_RUN_ID;
  if (runId === WORKFLOW_REJECT_CHILD_RUN_ID) return WORKFLOW_REJECT_RUN_ID;
  if (runId === WORKFLOW_CANCEL_CHILD_RUN_ID) return WORKFLOW_CANCEL_RUN_ID;
  return '';
}

function publicRunEvents(runId) {
  if (runId === RUN_ID) return runEvents;
  if (runId === APPROVAL_RUN_ID) return approvalRunEvents();
  if (runId === WORKFLOW_RUN_ID) return workflowRunEvents();
  if (runId === WORKFLOW_CHILD_RUN_ID) return workflowChildRunEvents();
  if (runId === WORKFLOW_REJECT_RUN_ID) return workflowRejectRunEvents();
  if (runId === WORKFLOW_REJECT_CHILD_RUN_ID) return workflowRejectChildRunEvents();
  if (runId === WORKFLOW_CANCEL_RUN_ID) return workflowCancelRunEvents();
  if (runId === WORKFLOW_CANCEL_CHILD_RUN_ID) return workflowCancelChildRunEvents();
  if (runId === ACTIVE_CANCEL_RUN_ID) return activeCancelRunEvents();
  if (runId === RERUN_RUN_ID) return rerunEvents;
  return [];
}

async function startMockBridge() {
  const server = http.createServer((request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (
        request.method === 'GET'
        && (url.pathname === '/ui/agents' || url.pathname === '/yachiyo/studio/agents')
      ) {
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
      if (
        request.method === 'GET'
        && (url.pathname === '/ui/skills' || url.pathname === '/yachiyo/studio/skills')
      ) {
        sendJson(response, 200, { skills: [] });
        return;
      }
      if (
        request.method === 'GET'
        && (url.pathname === '/ui/skills/sources' || url.pathname === '/yachiyo/studio/skills/sources')
      ) {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (
        request.method === 'GET'
        && (url.pathname === '/ui/skill-folders' || url.pathname === '/yachiyo/studio/skill-folders')
      ) {
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/groups') {
        sendJson(response, 200, { groups: [] });
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/group-runs') {
        sendJson(response, 200, {
          group_runs: [
            workflowCancelRunGroup(),
            workflowRejectRunGroup(),
            workflowRunGroup(),
            runGroup(),
          ].map((group) => ({
            group_run_id: group.run_group_id,
            run_group_id: group.run_group_id,
            group_id: group.run_group_id,
            title: group.title,
            status: group.status,
            objective: group.summary || group.title,
            participants: [],
            active_speaker_agent_id: null,
            events: [],
            runs: group.child_run_ids.map(currentRunById).filter(Boolean).map(publicRunSnapshot),
            child_run_ids: group.child_run_ids,
            shared_artifacts: [],
            pending_approvals: [],
            final_answer: group.summary || '',
            created_at: group.created_at,
            updated_at: group.updated_at,
          })),
        });
        return;
      }
      if (
        request.method === 'GET'
        && url.pathname.startsWith('/yachiyo/studio/group-runs/')
        && url.pathname.endsWith('/events')
      ) {
        const groupRunId = decodeURIComponent(
          url.pathname.slice('/yachiyo/studio/group-runs/'.length, -'/events'.length),
        );
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: groupRunId,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: [],
          has_more: false,
          next_after_sequence: Math.max(0, afterSequence),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/runs') {
        sendJson(response, 200, { runs: currentRuns().map(publicRunSnapshot) });
        return;
      }
      if (
        request.method === 'GET'
        && url.pathname.startsWith('/yachiyo/studio/runs/')
        && url.pathname.endsWith('/timeline')
      ) {
        const runId = decodeURIComponent(
          url.pathname.slice('/yachiyo/studio/runs/'.length, -'/timeline'.length),
        );
        const item = currentRunById(runId);
        if (item) sendJson(response, 200, publicRunSnapshot(item));
        else sendJson(response, 404, { ok: false, error: `run not found: ${runId}` });
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/runs/${APPROVAL_RUN_ID}/approval/approve`) {
        approvalApproved = true;
        sendJson(response, 200, publicRunSnapshot(approvalRun()));
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_CHILD_RUN_ID}/approval/approve`) {
        workflowChildApproved = true;
        sendJson(response, 200, publicRunSnapshot(workflowChildRun()));
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}/approval/reject`) {
        workflowChildRejected = true;
        sendJson(response, 200, publicRunSnapshot(workflowRejectChildRun()));
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}/cancel`) {
        workflowChildCancelled = true;
        sendJson(response, 200, publicRunSnapshot(workflowCancelChildRun()));
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/runs/${ACTIVE_CANCEL_RUN_ID}/cancel`) {
        activeRunCancelled = true;
        sendJson(response, 200, publicRunSnapshot(activeCancelRun()));
        return;
      }
      if (request.method === 'POST' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/rerun`) {
        rerunCreated = true;
        sendJson(response, 200, publicRunSnapshot(rerun));
        return;
      }
      if (request.method === 'DELETE' && url.pathname.startsWith('/yachiyo/studio/runs/')) {
        const runId = decodeURIComponent(url.pathname.slice('/yachiyo/studio/runs/'.length));
        deletedRunIds.push(runId);
        sendJson(response, 200, { ok: true, deleted_run_ids: [runId], deleted_run_count: 1 });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/artifacts/${ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          run_id: RUN_ID,
          path: ARTIFACT_PATH,
          content: ARTIFACT_CONTENT,
          mime_type: 'text/markdown',
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_RUN_ID}/artifacts/${WORKFLOW_ARTIFACT_PATH}`) {
        sendJson(response, 200, {
          ok: true,
          run_id: WORKFLOW_RUN_ID,
          path: WORKFLOW_ARTIFACT_PATH,
          content: '# Workflow Summary\n\nWorkflow artifact preview loaded from mock Bridge.',
          mime_type: 'text/markdown',
          truncated: false,
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: currentRuns() });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${ACTIVE_CANCEL_RUN_ID}`) {
        sendJson(response, 200, activeCancelRun());
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
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_REJECT_RUN_ID}`) {
        sendJson(response, 200, workflowRejectRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}`) {
        sendJson(response, 200, workflowRejectChildRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_CANCEL_RUN_ID}`) {
        sendJson(response, 200, workflowCancelRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}`) {
        sendJson(response, 200, workflowCancelChildRun());
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
      if (request.method === 'POST' && url.pathname === `/ui/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}/approval/reject`) {
        workflowChildRejected = true;
        sendJson(response, 200, workflowRejectChildRun());
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}/cancel`) {
        workflowChildCancelled = true;
        sendJson(response, 200, workflowCancelChildRun());
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${ACTIVE_CANCEL_RUN_ID}/cancel`) {
        activeRunCancelled = true;
        sendJson(response, 200, activeCancelRun());
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
      if (request.method === 'DELETE' && url.pathname.startsWith('/ui/runs/')) {
        const runId = decodeURIComponent(url.pathname.slice('/ui/runs/'.length));
        deletedRunIds.push(runId);
        sendJson(response, 200, {
          ok: true,
          deleted_run_ids: [runId],
          deleted_run_count: 1,
        });
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
        sendJson(response, 200, { run_groups: [workflowCancelRunGroup(), workflowRejectRunGroup(), workflowRunGroup(), runGroup()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${WORKFLOW_RUN_GROUP_ID}`) {
        sendJson(response, 200, workflowRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${WORKFLOW_REJECT_RUN_GROUP_ID}`) {
        sendJson(response, 200, workflowRejectRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${WORKFLOW_CANCEL_RUN_GROUP_ID}`) {
        sendJson(response, 200, workflowCancelRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        runEventRequests.push({ after_sequence: Math.max(0, afterSequence), limit });
        sendJson(response, 200, {
          run_id: RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: runEvents.filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${ACTIVE_CANCEL_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: ACTIVE_CANCEL_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: activeCancelRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_RUN_ID}/events`) {
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
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_CHILD_RUN_ID}/events`) {
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
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_REJECT_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: WORKFLOW_REJECT_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: workflowRejectRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_REJECT_CHILD_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: WORKFLOW_REJECT_CHILD_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: workflowRejectChildRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_CANCEL_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: WORKFLOW_CANCEL_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: workflowCancelRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${WORKFLOW_CANCEL_CHILD_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, {
          run_id: WORKFLOW_CANCEL_CHILD_RUN_ID,
          after_sequence: Math.max(0, afterSequence),
          limit,
          events: workflowCancelChildRunEvents().filter((event) => event.sequence > afterSequence).slice(0, limit),
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
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RERUN_RUN_ID}/events`) {
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
const workflowRejectRunId = ${JSON.stringify(WORKFLOW_REJECT_RUN_ID)};
const workflowCancelRunId = ${JSON.stringify(WORKFLOW_CANCEL_RUN_ID)};
const activeCancelRunId = ${JSON.stringify(ACTIVE_CANCEL_RUN_ID)};
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(activeCancelRunId));
  console.log('[electron-smoke] active cancel run detail loaded');
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const cancel = document.querySelector('[data-testid="agent-run-detail-cancel"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const status = detail?.getAttribute('data-run-status');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(ACTIVE_CANCEL_RUN_ID)}
      && (status === 'running' || status === 'processing')
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(ACTIVE_CANCEL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(ACTIVE_CANCEL_SESSION_ID)}
      && document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes('Cancel active Agent Run from Run Detail smoke')
      && cancel
      && !cancel.disabled
      && events.some((node) => node.getAttribute('data-run-event') === 'agent.run.started');
  }, 'active cancel run detail article');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-cancel\\"]').click()", true);
  await waitFor(win, () => {
    const dialog = document.querySelector('[data-testid="confirm-dialog"]');
    const confirm = document.querySelector('[data-testid="confirm-action"]');
    return dialog?.textContent.includes('取消 Run')
      && dialog?.textContent.includes('这会终止当前进行中或待审批的 Run')
      && confirm
      && !confirm.disabled;
  }, 'active run cancel confirmation');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"confirm-action\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const cancelledEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.cancelled');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(ACTIVE_CANCEL_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'cancelled'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(ACTIVE_CANCEL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(ACTIVE_CANCEL_SESSION_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-cancel"]')
      && result?.textContent.includes('Run Detail active Run cancelled from UI smoke')
      && eventTypes.includes('agent.run.started')
      && eventTypes.includes('agent.run.cancelled')
      && sequences.join(',') === '1,2'
      && runIds.every((id) => id === ${JSON.stringify(ACTIVE_CANCEL_RUN_ID)})
      && cancelledEvent?.textContent.includes('Run Detail active Run cancelled from UI smoke');
  }, 'active run cancelled detail replay');
  console.log('[electron-smoke] active Run Detail cancel completed');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(approvalRunId));
  console.log('[electron-smoke] approval run detail loaded');
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'approval_required'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(APPROVAL_SESSION_ID)};
  }, 'approval run detail article');
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
    const startedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.started');
    const approvalRequiredEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.tool.approval_required');
    const toolCallEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.tool.call');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.completed');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(APPROVAL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(APPROVAL_SESSION_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-approval"]')
      && result?.textContent.includes('Run Detail approval smoke completed')
      && eventTypes.includes('agent.tool.approval_required')
      && eventTypes.includes('agent.tool.approval_approved')
      && eventTypes.includes('agent.tool.call')
      && eventTypes.includes('agent.run.completed')
      && sequences.join(',') === '1,2,3,4,5'
      && startedEvent?.textContent.includes('Approve Native Run Detail from Agent Studio smoke')
      && approvalRequiredEvent?.textContent.includes('terminal.run')
      && approvalRequiredEvent?.textContent.includes('printf run-detail-approval-smoke')
      && toolCallEvent?.textContent.includes('terminal.run')
      && toolCallEvent?.textContent.includes('printf run-detail-approval-smoke')
      && completedEvent?.textContent.includes('Run Detail approval smoke completed')
      && runIds.every((id) => id === ${JSON.stringify(APPROVAL_RUN_ID)});
  }, 'approved run detail replay');
  console.log('[electron-smoke] approval action completed');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(workflowRejectRunId));
  console.log('[electron-smoke] workflow child reject run detail loaded');
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_REJECT_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'approval_required'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_REJECT_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_REJECT_SESSION_ID)};
  }, 'workflow child reject parent run detail article');
  await waitFor(win, () => {
    const childApproval = document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]');
    const request = childApproval?.querySelector('[data-testid="agent-run-approval-request"]');
    const reject = document.querySelector('[data-testid="agent-run-detail-workflow-child-reject"]');
    return childApproval
      && childApproval.textContent.includes(${JSON.stringify(WORKFLOW_REJECT_CHILD_RUN_ID)})
      && request?.textContent.includes('terminal.run')
      && request?.textContent.includes('printf workflow-child-electron-rejected')
      && reject
      && !reject.disabled;
  }, 'workflow child reject bridge');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-workflow-child-reject\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const steps = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-workflow-step"]'));
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const rejectCancelledEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.run.cancelled');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_REJECT_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'cancelled'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_REJECT_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_REJECT_SESSION_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]')
      && result?.textContent.includes('Workflow child approval rejected from Electron smoke')
      && steps.some((node) => node.getAttribute('data-child-run-id') === ${JSON.stringify(WORKFLOW_REJECT_CHILD_RUN_ID)} && node.getAttribute('data-workflow-step-status') === 'cancelled')
      && eventTypes.includes('workflow.run.cancelled')
      && rejectCancelledEvent?.textContent.includes(${JSON.stringify(WORKFLOW_REJECT_CHILD_RUN_ID)})
      && runIds.every((id) => id === ${JSON.stringify(WORKFLOW_REJECT_RUN_ID)});
  }, 'workflow child reject completed parent detail');
  console.log('[electron-smoke] workflow child reject action completed');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(workflowCancelRunId));
  console.log('[electron-smoke] workflow child cancel run detail loaded');
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CANCEL_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'approval_required'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_CANCEL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_CANCEL_SESSION_ID)};
  }, 'workflow child cancel parent run detail article');
  await waitFor(win, () => {
    const childApproval = document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]');
    const request = childApproval?.querySelector('[data-testid="agent-run-approval-request"]');
    const cancel = document.querySelector('[data-testid="agent-run-detail-workflow-child-cancel"]');
    return childApproval
      && childApproval.textContent.includes(${JSON.stringify(WORKFLOW_CANCEL_CHILD_RUN_ID)})
      && request?.textContent.includes('terminal.run')
      && request?.textContent.includes('printf workflow-child-electron-cancelled')
      && cancel
      && !cancel.disabled;
  }, 'workflow child cancel bridge');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-workflow-child-cancel\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const steps = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-workflow-step"]'));
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const cancelCancelledEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.run.cancelled');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CANCEL_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'cancelled'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_CANCEL_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_CANCEL_SESSION_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]')
      && result?.textContent.includes('Workflow child run cancelled from Electron smoke')
      && steps.some((node) => node.getAttribute('data-child-run-id') === ${JSON.stringify(WORKFLOW_CANCEL_CHILD_RUN_ID)} && node.getAttribute('data-workflow-step-status') === 'cancelled')
      && eventTypes.includes('workflow.run.cancelled')
      && cancelCancelledEvent?.textContent.includes(${JSON.stringify(WORKFLOW_CANCEL_CHILD_RUN_ID)})
      && runIds.every((id) => id === ${JSON.stringify(WORKFLOW_CANCEL_RUN_ID)});
  }, 'workflow child cancel completed parent detail');
  console.log('[electron-smoke] workflow child cancel action completed');

  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(workflowRunId));
  console.log('[electron-smoke] workflow child approval run detail loaded');
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'approval_required'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_SESSION_ID)};
  }, 'workflow parent run detail article');
  await waitFor(win, () => {
    const childApproval = document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]');
    const request = childApproval?.querySelector('[data-testid="agent-run-approval-request"]');
    const approve = document.querySelector('[data-testid="agent-run-detail-workflow-child-approve"]');
    const reject = document.querySelector('[data-testid="agent-run-detail-workflow-child-reject"]');
    const cancel = document.querySelector('[data-testid="agent-run-detail-workflow-child-cancel"]');
    const openRun = document.querySelector('[data-testid="agent-run-detail-workflow-child-open-run"]');
    const executionChildOpenRun = document.querySelector('[data-testid="agent-run-detail-execution-open-child-run"]');
    return childApproval
      && childApproval.textContent.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)})
      && request?.textContent.includes('terminal.run')
      && request?.textContent.includes('printf workflow-child-electron-approved')
      && approve
      && reject
      && cancel
      && openRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}
      && openRun?.getAttribute('data-run-status') === 'approval_required'
      && executionChildOpenRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}
      && executionChildOpenRun?.getAttribute('data-run-status') === 'approval_required'
      && !approve.disabled;
  }, 'workflow child approval bridge');
  console.log('[electron-smoke] workflow child approval bridge rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-workflow-child-approve\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const steps = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-workflow-step"]'));
    const openStepRun = document.querySelector('[data-testid="agent-run-detail-workflow-step-open-run"]');
    const executionChildOpenRun = document.querySelector('[data-testid="agent-run-detail-execution-open-child-run"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const childResumedEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.run.child_resumed');
    const artifactEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.node.artifact');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'workflow.run.completed');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_SESSION_ID)}
      && !document.querySelector('[data-testid="agent-run-detail-workflow-child-approval"]')
      && result?.textContent.includes('Workflow child approval Electron smoke complete')
      && steps.some((node) => node.getAttribute('data-child-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)} && node.getAttribute('data-workflow-step-status') === 'completed')
      && steps.some((node) => node.getAttribute('data-workflow-step-kind') === 'artifact' && node.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)}))
      && openStepRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}
      && openStepRun?.getAttribute('data-run-status') === 'completed'
      && !openStepRun.disabled
      && executionChildOpenRun?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}
      && executionChildOpenRun?.getAttribute('data-run-status') === 'completed'
      && eventTypes.includes('workflow.run.child_resumed')
      && eventTypes.includes('workflow.run.resumed')
      && eventTypes.includes('workflow.node.artifact')
      && eventTypes.includes('workflow.run.completed')
      && childResumedEvent?.textContent.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)})
      && artifactEvent?.textContent.includes(${JSON.stringify(WORKFLOW_ARTIFACT_PATH)})
      && completedEvent?.textContent.includes('Workflow child approval Electron smoke complete')
      && runIds.every((id) => id === ${JSON.stringify(WORKFLOW_RUN_ID)});
  }, 'workflow child approval completed parent detail');
  console.log('[electron-smoke] workflow child approval completed parent detail');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-workflow-step-open-run\\"]').click()", true);
  await waitFor(win, () => window.location.hash.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}), 'workflow child route hash');
  await win.loadURL('about:blank');
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}));
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const startedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.started');
    const approvalRequiredEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.tool.approval_required');
    const toolCallEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.tool.call');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.completed');
    const parentOpen = document.querySelector('[data-testid="agent-run-detail-open-parent-run"]');
    return window.location.hash.includes(${JSON.stringify(WORKFLOW_CHILD_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)}
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(WORKFLOW_CHILD_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(WORKFLOW_CHILD_SESSION_ID)}
      && parentOpen?.getAttribute('data-run-id') === ${JSON.stringify(WORKFLOW_RUN_ID)}
      && parentOpen?.getAttribute('data-run-status') === 'completed'
      && result?.textContent.includes('Workflow child approval Electron smoke complete')
      && eventTypes.includes('agent.tool.approval_required')
      && eventTypes.includes('agent.tool.approval_approved')
      && eventTypes.includes('agent.tool.call')
      && eventTypes.includes('agent.run.completed')
      && startedEvent?.textContent.includes('Approve child Agent from Workflow Run Detail smoke')
      && approvalRequiredEvent?.textContent.includes('terminal.run')
      && approvalRequiredEvent?.textContent.includes('printf workflow-child-electron-approved')
      && toolCallEvent?.textContent.includes('terminal.run')
      && toolCallEvent?.textContent.includes('printf workflow-child-electron-approved')
      && completedEvent?.textContent.includes('Workflow child approval Electron smoke complete')
      && runIds.every((id) => id === ${JSON.stringify(WORKFLOW_CHILD_RUN_ID)});
  }, 'workflow child run detail replay');
  console.log('[electron-smoke] workflow child run detail rendered');

  await win.loadURL('about:blank');
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/agents/' + encodeURIComponent(runId));
  console.log('[electron-smoke] run detail loaded');
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    return detail?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(RUN_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(RUN_SESSION_ID)};
  }, 'run detail article');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail-task"]')?.textContent.includes('Inspect Native RunEvent replay'), 'run task block');
  await waitFor(win, () => document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes('Run Detail UI smoke completed through replay facts'), 'run result block');
  await waitFor(win, () => {
    const traces = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-memory-skill-trace"]'));
    const memoryTrace = traces.find((node) => node.getAttribute('data-runtime-trace-kind') === 'memory');
    const skillTrace = traces.find((node) => node.getAttribute('data-runtime-trace-kind') === 'skill');
    return document.querySelector('[data-testid="agent-run-detail-memory-skill-traces"]')
      && memoryTrace?.getAttribute('data-run-event') === 'memory.retrieved'
      && memoryTrace?.getAttribute('data-run-event-sequence') === '3'
      && memoryTrace?.getAttribute('data-memory-id') === 'memory-run-detail-smoke'
      && memoryTrace?.getAttribute('data-group-run-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && memoryTrace?.textContent.includes('Memory 检索')
      && memoryTrace?.textContent.includes('Run Detail smoke preference memory')
      && skillTrace?.getAttribute('data-run-event') === 'skill.dispatch.read'
      && skillTrace?.getAttribute('data-run-event-sequence') === '4'
      && skillTrace?.getAttribute('data-skill-id') === 'skill-run-detail-smoke'
      && skillTrace?.getAttribute('data-member-agent-id') === 'agent-run-detail-smoke'
      && skillTrace?.textContent.includes('Run Detail Smoke Skill')
      && skillTrace?.textContent.includes('skills/run-detail-smoke/SKILL.md');
  }, 'run detail memory skill trace replay');
  console.log('[electron-smoke] run detail memory skill trace replay verified');
  await waitFor(win, () => {
    const manage = document.querySelector('[data-testid="agent-run-history-manage"]');
    const rows = Array.from(document.querySelectorAll('[data-testid="agent-run-history-row"]'));
    const approvalOpen = document.querySelector('[data-testid="agent-run-history-row"][data-run-id="${APPROVAL_RUN_ID}"] [data-testid="agent-run-history-open-run"]');
    const selectedOpen = document.querySelector('[data-testid="agent-run-history-row"][data-run-id="${RUN_ID}"] [data-testid="agent-run-history-open-run"]');
    return manage
      && !manage.disabled
      && rows.some((row) => row.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)})
      && rows.some((row) => row.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)})
      && approvalOpen?.getAttribute('data-run-id') === ${JSON.stringify(APPROVAL_RUN_ID)}
      && approvalOpen?.getAttribute('data-run-status') === 'completed'
      && selectedOpen?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && selectedOpen?.getAttribute('data-run-status') === 'completed';
  }, 'agent run history management controls');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-history-manage\\"]').click()", true);
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="agent-run-history-bulk-actions"]');
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="agent-run-history-select-run"]'));
    return Boolean(bulk) && checkboxes.length >= 5 && checkboxes.every((input) => !input.disabled);
  }, 'agent run history management mode');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-history-select-all\\"]').click()", true);
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="agent-run-history-bulk-actions"]');
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="agent-run-history-select-run"]'));
    const deleteSelected = document.querySelector('[data-testid="agent-run-history-delete-selected"]');
    return checkboxes.length >= 5
      && bulk?.textContent.includes('已选择 ' + checkboxes.length + ' / ' + checkboxes.length)
      && checkboxes.every((input) => input.checked)
      && Boolean(deleteSelected)
      && !deleteSelected.disabled;
  }, 'agent run history select all');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-history-clear-selection\\"]').click()", true);
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="agent-run-history-bulk-actions"]');
    const checkboxes = Array.from(document.querySelectorAll('[data-testid="agent-run-history-select-run"]'));
    const deleteSelected = document.querySelector('[data-testid="agent-run-history-delete-selected"]');
    return checkboxes.length >= 5
      && bulk?.textContent.includes(checkboxes.length + ' runs')
      && checkboxes.every((input) => !input.checked)
      && Boolean(deleteSelected)
      && deleteSelected.disabled;
  }, 'agent run history clear selection');
  await win.webContents.executeJavaScript(\`
    document
      .querySelector('[data-testid="agent-run-history-row"][data-run-id="${APPROVAL_RUN_ID}"] [data-testid="agent-run-history-select-run"]')
      .click();
  \`, true);
  await waitFor(win, () => {
    const bulk = document.querySelector('[data-testid="agent-run-history-bulk-actions"]');
    const checkbox = document.querySelector('[data-testid="agent-run-history-row"][data-run-id="${APPROVAL_RUN_ID}"] [data-testid="agent-run-history-select-run"]');
    const deleteSelected = document.querySelector('[data-testid="agent-run-history-delete-selected"]');
    return checkbox?.checked
      && bulk?.textContent.includes('已选择 1 /')
      && Boolean(deleteSelected)
      && !deleteSelected.disabled;
  }, 'agent run history selected completed run');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-history-delete-selected\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="confirm-dialog"]')?.textContent.includes('删除 1 条 Run History'), 'agent run history delete confirm');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"confirm-action\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
    && !document.querySelector('[data-testid="agent-run-history-row"][data-run-id="${APPROVAL_RUN_ID}"]')
    && document.querySelector('[data-testid="agent-run-history-bulk-actions"]')
  ), 'agent run history bulk delete completed');
  console.log('[electron-smoke] run history selection controls and bulk delete verified');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const toolEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.tool.call');
    const modelEvent = events.find((node) => node.getAttribute('data-run-event') === 'model.output.completed');
    return events.length === 200
      && eventTypes.includes('agent.run.started')
      && eventTypes.includes('agent.tool.call')
      && !eventTypes.includes('agent.run.completed')
      && sequences[0] === '1'
      && sequences[199] === '200'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && toolEvent?.textContent.includes('"path": "README.md"')
      && modelEvent?.textContent.includes('Replay page smoke event 5')
      && document.querySelector('[data-testid="agent-run-detail-load-more-events"]');
  }, 'initial run event replay page');
  console.log('[electron-smoke] initial replay page rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"agent-run-detail-load-more-events\\"]').click()", true);
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.completed');
    return events.length === 201
      && eventTypes.includes('agent.run.completed')
      && sequences[200] === '201'
      && runIds.every((id) => id === ${JSON.stringify(RUN_ID)})
      && completedEvent?.textContent.includes(${JSON.stringify(run.result)})
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
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-task-id') === ${JSON.stringify(RERUN_TASK_ID)}
    && document.querySelector('[data-testid="agent-run-detail"]')?.getAttribute('data-session-id') === ${JSON.stringify(RUN_SESSION_ID)}
    && document.querySelector('[data-testid="agent-run-detail-result"]')?.textContent.includes('Run Detail UI smoke rerun completed')
  ), 'rerun run detail');
  await waitFor(win, () => {
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const sequences = events.map((node) => node.getAttribute('data-run-event-sequence'));
    const runIds = events.map((node) => node.getAttribute('data-run-event-run-id'));
    const rerunStartedEvent = events.find((node) => node.getAttribute('data-run-event') === 'run.rerun.started');
    const rerunCompletedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.completed');
    return events.length === 2
      && eventTypes.includes('run.rerun.started')
      && eventTypes.includes('agent.run.completed')
      && sequences.join(',') === '1,2'
      && rerunStartedEvent?.textContent.includes(${JSON.stringify(RUN_ID)})
      && rerunCompletedEvent?.textContent.includes('Run Detail UI smoke rerun completed')
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
    if (!workflowChildRejected) throw new Error('workflow child reject action was not called');
    if (!workflowChildCancelled) throw new Error('workflow child cancel action was not called');
    if (!activeRunCancelled) throw new Error('active Run Detail cancel action was not called');
    if (!deletedRunIds.includes(APPROVAL_RUN_ID)) throw new Error('agent run history delete route was not called');
    const initialReplayRequest = runEventRequests.some((request) => request.after_sequence === 0 && request.limit === 200);
    const loadMoreReplayRequest = runEventRequests.some((request) => request.after_sequence === 200 && request.limit === 200);
    if (!initialReplayRequest) {
      throw new Error(`initial RunEvent replay request was not made with after_sequence=0&limit=200: ${JSON.stringify(runEventRequests)}`);
    }
    if (!loadMoreReplayRequest) {
      throw new Error(`load-more RunEvent replay request was not made with after_sequence=200&limit=200: ${JSON.stringify(runEventRequests)}`);
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
