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
const MAIN_SESSION_ID = 'chat_group_ui_smoke_main';
const GROUP_SESSION_ID = 'chat_group_ui_smoke_group';
const AGENT_ID = 'chat-group-ui-agent';
const GROUP_NAME = 'Chat Group UI Smoke';
const GROUP_GOAL = 'Coordinate the group UI smoke';
const GROUP_FOLLOWUP_TEXT = 'Add this follow-up to the current group task.';
const GROUP_AVATAR_DATA_URL = `data:image/svg+xml;base64,${Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="8" fill="#14b8a6"/><text x="16" y="21" text-anchor="middle" font-size="16" fill="#fff">群</text></svg>',
).toString('base64')}`;
const RUN_GROUP_ID = 'run_group_chat_group_ui_smoke';
const GROUP_AGENT_RUN_ID = 'agent_run_chat_group_ui_smoke';
const GROUP_SUMMARY_RUN_ID = 'main_chat_run_group_summary_ui_smoke';
const SUMMARY_TASK_ID = 'task-chat-group-summary-ui-smoke';
const GROUP_AGENT_TASK_ID = 'task-chat-group-agent-ui-smoke';
const GROUP_AGENT_RESULT = 'Group UI Agent completed Native group dispatch.';
const GROUP_SUMMARY_RESULT = 'Oha-Yachiyo completed the group summary.';
const now = new Date().toISOString();

const bridgeState = {
  currentSessionId: MAIN_SESSION_ID,
  groupCreated: false,
  groupCreatePayload: null,
  messagePayload: null,
  followupPayload: null,
  groupSummaryStatus: 'idle',
  messagesBySession: new Map([[MAIN_SESSION_ID, []]]),
  failNextGroupSessionLoad: false,
  skipNextMainSessionDelay: false,
  sessionLoadCompletions: [],
  sessionLoadFailures: [],
  timeoutNextGroupSessionLoads: 0,
};

const agentRunnable = {
  id: AGENT_ID,
  name: 'Group UI Agent',
  nickname: 'Group Agent',
  kind: 'agent',
  enabled: true,
  output_contract: 'report',
  tool_policy: {
    allowed_tools: ['workspace.read'],
    approval_required: {},
  },
};

const groupParticipants = [
  { kind: 'main', name: 'Oha-Yachiyo', nickname: 'Yachiyo' },
  { kind: 'agent', id: AGENT_ID, name: agentRunnable.name, nickname: agentRunnable.nickname },
];

const studioGroupParticipants = [
  { agent_id: AGENT_ID, name: agentRunnable.name, role: 'member', sort_order: 1, enabled: true },
];

function log(message) {
  process.stdout.write(`[chat-group-summary-ui-smoke] ${message}\n`);
}

function studioAgentSnapshot() {
  return {
    agent_id: AGENT_ID,
    name: agentRunnable.name,
    nickname: agentRunnable.nickname,
    description: 'Chat group UI smoke agent',
    avatar_url: '',
    category: 'smoke',
    instructions: 'Handle the group UI smoke task.',
    persona_prompt: '',
    model_mode: 'follow_main',
    execution_backend: 'native_profile',
    model_profile_id: '',
    vision_model_profile_id: '',
    model_config: {},
    tool_policy: agentRunnable.tool_policy,
    workspace_policy: {
      default_workdir: '',
      readable_scopes: ['.'],
      writable_scopes: [],
    },
    output_contract: agentRunnable.output_contract,
    enabled: true,
    editable: true,
    deletable: true,
    skill_ids: [],
    created_at: now,
    updated_at: now,
  };
}

function studioGroupSnapshot() {
  return {
    group_id: GROUP_SESSION_ID,
    name: GROUP_NAME,
    description: GROUP_GOAL,
    members: studioGroupParticipants,
    mode: 'parallel',
    moderator_agent_id: null,
    default_model: null,
    memory_scope: 'shared',
    tool_policy_id: null,
    enabled: true,
    created_at: now,
    updated_at: now,
  };
}

function groupSessionContext() {
  return {
    conversation_kind: 'group',
    runnable_id: GROUP_SESSION_ID,
    runnable_name: GROUP_NAME,
    run_group_id: RUN_GROUP_ID,
    participants: groupParticipants,
  };
}

function sessionsPayload() {
  const sessions = [
    {
      session_id: MAIN_SESSION_ID,
      title: 'Main chat',
      conversation_kind: 'main',
      message_count: 0,
      token_count: 0,
      updated_at: now,
    },
  ];
  if (bridgeState.groupCreated) {
    sessions.unshift({
      session_id: GROUP_SESSION_ID,
      title: GROUP_NAME,
      conversation_kind: 'group',
      runnable_id: GROUP_SESSION_ID,
      runnable_name: GROUP_NAME,
      run_group_id: RUN_GROUP_ID,
      participants: groupParticipants,
      message_count: bridgeState.messagesBySession.get(GROUP_SESSION_ID)?.length || 0,
      token_count: 0,
      is_processing: false,
      processing_count: 0,
      latest_message_preview: bridgeState.groupSummaryStatus === 'completed'
        ? GROUP_SUMMARY_RESULT
        : bridgeState.messagePayload
          ? 'Waiting for main model summary'
          : '',
      updated_at: now,
    });
  }
  return {
    ok: true,
    current_session_id: bridgeState.currentSessionId,
    sessions,
  };
}

function messagesPayload() {
  const messages = bridgeState.messagesBySession.get(bridgeState.currentSessionId) || [];
  const isGroup = bridgeState.currentSessionId === GROUP_SESSION_ID;
  return {
    ok: true,
    session_id: bridgeState.currentSessionId,
    messages,
    session_context: isGroup ? groupSessionContext() : { conversation_kind: 'main' },
    is_processing: false,
    processing_count: 0,
    approval_count: 0,
    token_count: 0,
  };
}

function createGroupMessages(text) {
  const summaryCompleted = bridgeState.groupSummaryStatus === 'completed';
  const agentSummaryMetadata = {
    sender: { kind: 'agent', id: AGENT_ID, name: agentRunnable.name, nickname: agentRunnable.nickname },
    target: { kind: 'group', id: GROUP_SESSION_ID, name: GROUP_NAME },
    runnable_kind: 'agent',
    runnable_id: AGENT_ID,
    run_group_id: RUN_GROUP_ID,
    group_goal: text,
    group_dispatch_count: 1,
    group_dispatch_run_group_id: RUN_GROUP_ID,
    group_agent_summary_task_id: SUMMARY_TASK_ID,
    group_agent_summary_status: summaryCompleted ? 'completed' : 'processing',
    ...(summaryCompleted ? {} : { group_agent_summary_pending: true }),
  };
  const messages = [
    {
      id: 'chat-group-ui-user-message',
      role: 'user',
      content: text,
      status: 'completed',
      created_at: now,
      metadata: {
        sender: { kind: 'main', name: 'Oha-Yachiyo', nickname: 'Yachiyo' },
        target: { kind: 'group', id: GROUP_SESSION_ID, name: GROUP_NAME },
      },
    },
    {
      id: 'chat-group-ui-agent-summary-message',
      role: 'assistant',
      content: 'Group UI Agent accepted the task and returned a draft result.',
      status: summaryCompleted ? 'completed' : 'processing',
      created_at: now,
      task_id: GROUP_AGENT_TASK_ID,
      metadata: agentSummaryMetadata,
      activity_events: [
        {
          event_id: 'activity-chat-group-ui-smoke',
          task_id: GROUP_AGENT_TASK_ID,
          title: 'Group UI Agent',
          detail: 'NativeRunEngine group dispatch is linked to this RunGroup.',
          status: 'completed',
          metadata: {
            run_id: GROUP_AGENT_RUN_ID,
            run_group_id: RUN_GROUP_ID,
            run_status: 'completed',
          },
          created_at: now,
        },
      ],
    },
  ];
  if (summaryCompleted) {
    messages.push({
      id: 'chat-group-ui-main-summary-message',
      role: 'assistant',
      content: GROUP_SUMMARY_RESULT,
      status: 'completed',
      created_at: now,
      task_id: SUMMARY_TASK_ID,
      metadata: {
        sender: { kind: 'main', name: 'Oha-Yachiyo', nickname: 'Yachiyo' },
        target: { kind: 'group', id: GROUP_SESSION_ID, name: GROUP_NAME },
        group_agent_summary_for_task_id: GROUP_AGENT_TASK_ID,
        group_agent_summary_for_message_id: 'chat-group-ui-agent-summary-message',
        run_id: GROUP_SUMMARY_RUN_ID,
        run_status: 'completed',
        run_group_id: RUN_GROUP_ID,
      },
    });
  }
  if (bridgeState.followupPayload) {
    messages.push({
      id: 'chat-group-ui-followup-message',
      role: 'user',
      content: String(bridgeState.followupPayload.text || ''),
      status: 'completed',
      created_at: now,
      metadata: {
        sender: { kind: 'main', name: 'Oha-Yachiyo', nickname: 'Yachiyo' },
        target: { kind: 'group', id: GROUP_SESSION_ID, name: GROUP_NAME },
        group_followup_for_task_ids: [GROUP_AGENT_TASK_ID],
        group_followup_for_agent_message_ids: ['chat-group-ui-agent-summary-message'],
      },
    });
  }
  return messages;
}

function groupAgentRun() {
  return {
    run_id: GROUP_AGENT_RUN_ID,
    kind: 'agent_run',
    status: 'completed',
    title: agentRunnable.name,
    agent_id: AGENT_ID,
    runnable_id: AGENT_ID,
    runnable_name: agentRunnable.name,
    session_id: GROUP_SESSION_ID,
    task_id: GROUP_AGENT_TASK_ID,
    group_run_id: RUN_GROUP_ID,
    run_group_id: RUN_GROUP_ID,
    user_goal: GROUP_GOAL,
    result: GROUP_AGENT_RESULT,
    task_run_link_run_status: 'completed',
    task_run_link_last_event_sequence: 4,
    events: groupAgentRunEvents(),
    timeline: [
      { event: 'agent.run.started', status: 'running', detail: 'Started Native group dispatch.' },
      { event: 'agent.tool.call', status: 'completed', tool: 'workspace.read', detail: 'Read workspace context.' },
      { event: 'model.output.completed', status: 'completed', detail: GROUP_AGENT_RESULT },
      { event: 'agent.run.completed', status: 'completed', detail: GROUP_AGENT_RESULT },
    ],
    artifacts: [],
    created_at: now,
    updated_at: now,
  };
}

function groupAgentRunEvents() {
  return [
    {
      run_id: GROUP_AGENT_RUN_ID,
      sequence: 1,
      event_type: 'agent.run.started',
      actor: 'agent',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { goal: GROUP_GOAL, run_group_id: RUN_GROUP_ID },
      created_at: now,
    },
    {
      run_id: GROUP_AGENT_RUN_ID,
      sequence: 2,
      event_type: 'agent.tool.call',
      actor: 'tool',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { tool: 'workspace.read', status: 'completed' },
      created_at: now,
    },
    {
      run_id: GROUP_AGENT_RUN_ID,
      sequence: 3,
      event_type: 'model.output.completed',
      actor: 'model',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { content: GROUP_AGENT_RESULT },
      created_at: now,
    },
    {
      run_id: GROUP_AGENT_RUN_ID,
      sequence: 4,
      event_type: 'agent.run.completed',
      actor: 'agent',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { result: GROUP_AGENT_RESULT },
      created_at: now,
    },
  ];
}

function groupSummaryRun() {
  return {
    run_id: GROUP_SUMMARY_RUN_ID,
    kind: 'main_chat_run',
    status: 'completed',
    title: 'Group summary',
    session_id: GROUP_SESSION_ID,
    task_id: SUMMARY_TASK_ID,
    group_run_id: RUN_GROUP_ID,
    run_group_id: RUN_GROUP_ID,
    user_goal: `Summarize group agent task ${GROUP_AGENT_TASK_ID}`,
    result: GROUP_SUMMARY_RESULT,
    task_run_link_run_status: 'completed',
    task_run_link_last_event_sequence: 2,
    events: groupSummaryRunEvents(),
    timeline: [
      { event: 'model.output.completed', status: 'completed', detail: GROUP_SUMMARY_RESULT },
      { event: 'run.completed', status: 'completed', detail: GROUP_SUMMARY_RESULT },
    ],
    artifacts: [],
    created_at: now,
    updated_at: now,
  };
}

function groupSummaryRunEvents() {
  return [
    {
      run_id: GROUP_SUMMARY_RUN_ID,
      sequence: 1,
      event_type: 'model.output.completed',
      actor: 'model',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { content: GROUP_SUMMARY_RESULT },
      created_at: now,
    },
    {
      run_id: GROUP_SUMMARY_RUN_ID,
      sequence: 2,
      event_type: 'run.completed',
      actor: 'runtime',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { result: GROUP_SUMMARY_RESULT },
      created_at: now,
    },
  ];
}

function groupRunGroup() {
  return {
    group_run_id: RUN_GROUP_ID,
    run_group_id: RUN_GROUP_ID,
    group_id: GROUP_SESSION_ID,
    kind: 'group_chat',
    status: 'completed',
    title: GROUP_NAME,
    objective: GROUP_GOAL,
    participants: studioGroupParticipants,
    events: groupRunEvents(),
    runs: bridgeState.groupSummaryStatus === 'completed'
      ? [groupAgentRun(), groupSummaryRun()]
      : [groupAgentRun()],
    summary: bridgeState.groupSummaryStatus === 'completed' ? GROUP_SUMMARY_RESULT : GROUP_AGENT_RESULT,
    root_run_id: GROUP_AGENT_RUN_ID,
    child_run_ids: bridgeState.groupSummaryStatus === 'completed'
      ? [GROUP_AGENT_RUN_ID, GROUP_SUMMARY_RUN_ID]
      : [GROUP_AGENT_RUN_ID],
    final_answer: bridgeState.groupSummaryStatus === 'completed' ? GROUP_SUMMARY_RESULT : null,
    shared_artifacts: [],
    pending_approvals: [],
    created_at: now,
    updated_at: now,
  };
}

function groupRunEvents() {
  const events = [
    {
      run_id: RUN_GROUP_ID,
      sequence: 1,
      event_type: 'group.run.started',
      actor: 'runtime',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { group_id: GROUP_SESSION_ID, objective: GROUP_GOAL },
      created_at: now,
    },
    {
      run_id: RUN_GROUP_ID,
      sequence: 2,
      event_type: 'group.member.completed',
      actor: 'agent',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { child_run_id: GROUP_AGENT_RUN_ID, agent_id: AGENT_ID },
      created_at: now,
    },
  ];
  if (bridgeState.groupSummaryStatus === 'completed') {
    events.push({
      run_id: RUN_GROUP_ID,
      sequence: 3,
      event_type: 'group.summary.completed',
      actor: 'model',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { child_run_id: GROUP_SUMMARY_RUN_ID, result: GROUP_SUMMARY_RESULT },
      created_at: now,
    });
  }
  return events;
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

function eventPage(runId, events, afterSequence, limit) {
  const filtered = events.filter((event) => event.sequence > afterSequence).slice(0, limit);
  const nextAfterSequence = filtered.length
    ? Math.max(...filtered.map((event) => event.sequence))
    : Math.max(0, afterSequence);
  return {
    run_id: runId,
    after_sequence: Math.max(0, afterSequence),
    limit,
    next_after_sequence: nextAfterSequence,
    has_more: events.some((event) => event.sequence > nextAfterSequence),
    events: filtered,
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
      if (request.method === 'GET' && url.pathname === '/ui/chat/executor') {
        sendJson(response, 200, {
          executor: 'NativeAgentExecutor',
          available: true,
          image_input: { can_attach_images: true, label: 'Add image' },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/assistant/profile') {
        sendJson(response, 200, {
          ok: true,
          agent_name: 'Oha-Yachiyo',
          agent_nickname: 'Yachiyo',
          user_avatar_url: '',
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, { runnables: [agentRunnable] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, {
          agents: [{
            agent_id: AGENT_ID,
            name: agentRunnable.name,
            nickname: agentRunnable.nickname,
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/agents') {
        sendJson(response, 200, { agents: [studioAgentSnapshot()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills') {
        sendJson(response, 200, { skills: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skills') {
        sendJson(response, 200, { skills: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills/sources') {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skills/sources') {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skill-folders') {
        sendJson(response, 200, { folders: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/skill-folders') {
        sendJson(response, 200, { folders: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, { ok: true, profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/groups') {
        sendJson(response, 200, { groups: [studioGroupSnapshot()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/groups/${GROUP_SESSION_ID}`) {
        sendJson(response, 200, studioGroupSnapshot());
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/runs') {
        sendJson(response, 200, {
          runs: bridgeState.groupSummaryStatus === 'completed'
            ? [groupSummaryRun(), groupAgentRun()]
            : [groupAgentRun()],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/group-runs') {
        sendJson(response, 200, { group_runs: [groupRunGroup()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/group-runs/${RUN_GROUP_ID}`) {
        sendJson(response, 200, groupRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/group-runs/${RUN_GROUP_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, eventPage(RUN_GROUP_ID, groupRunEvents(), afterSequence, limit));
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, {
          runs: bridgeState.groupSummaryStatus === 'completed'
            ? [groupSummaryRun(), groupAgentRun()]
            : [groupAgentRun()],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${GROUP_AGENT_RUN_ID}`) {
        sendJson(response, 200, groupAgentRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${GROUP_SUMMARY_RUN_ID}`) {
        sendJson(
          response,
          bridgeState.groupSummaryStatus === 'completed' ? 200 : 404,
          bridgeState.groupSummaryStatus === 'completed'
            ? groupSummaryRun()
            : { ok: false, error: 'summary run not created' },
        );
        return;
      }
      if (request.method === 'GET' && (
        url.pathname === `/yachiyo/studio/runs/${GROUP_AGENT_RUN_ID}`
        || url.pathname === `/yachiyo/studio/runs/${GROUP_AGENT_RUN_ID}/timeline`
      )) {
        sendJson(response, 200, groupAgentRun());
        return;
      }
      if (request.method === 'GET' && (
        url.pathname === `/yachiyo/studio/runs/${GROUP_SUMMARY_RUN_ID}`
        || url.pathname === `/yachiyo/studio/runs/${GROUP_SUMMARY_RUN_ID}/timeline`
      )) {
        sendJson(
          response,
          bridgeState.groupSummaryStatus === 'completed' ? 200 : 404,
          bridgeState.groupSummaryStatus === 'completed'
            ? groupSummaryRun()
            : { ok: false, error: 'summary run not created' },
        );
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [groupRunGroup()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, groupRunGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${GROUP_AGENT_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, eventPage(GROUP_AGENT_RUN_ID, groupAgentRunEvents(), afterSequence, limit));
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${GROUP_SUMMARY_RUN_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, eventPage(GROUP_SUMMARY_RUN_ID, groupSummaryRunEvents(), afterSequence, limit));
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${GROUP_AGENT_TASK_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, eventPage(GROUP_AGENT_RUN_ID, groupAgentRunEvents(), afterSequence, limit));
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${SUMMARY_TASK_ID}/events`) {
        const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
        const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
        sendJson(response, 200, eventPage(GROUP_SUMMARY_RUN_ID, groupSummaryRunEvents(), afterSequence, limit));
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        log(`mock bridge messages session=${bridgeState.currentSessionId} count=${(bridgeState.messagesBySession.get(bridgeState.currentSessionId) || []).length}`);
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/session-switch-state') {
        sendJson(response, 200, {
          current_session_id: bridgeState.currentSessionId,
          session_load_completions: bridgeState.sessionLoadCompletions,
          session_load_failures: bridgeState.sessionLoadFailures,
          timeout_group_loads_remaining: bridgeState.timeoutNextGroupSessionLoads,
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/fail-next-group-session-load') {
        bridgeState.failNextGroupSessionLoad = true;
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/timeout-next-group-session-loads') {
        bridgeState.skipNextMainSessionDelay = true;
        bridgeState.timeoutNextGroupSessionLoads = 2;
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/groups') {
        const body = await readRequestJson(request);
        bridgeState.groupCreatePayload = body;
        bridgeState.groupCreated = true;
        bridgeState.currentSessionId = GROUP_SESSION_ID;
        bridgeState.messagesBySession.set(GROUP_SESSION_ID, []);
        sendJson(response, 200, {
          ok: true,
          session_id: GROUP_SESSION_ID,
          session_context: groupSessionContext(),
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages') {
        const body = await readRequestJson(request);
        log(`mock bridge group message text=${JSON.stringify(body.text || '')}`);
        if (bridgeState.groupSummaryStatus === 'completed' && bridgeState.messagePayload) {
          bridgeState.followupPayload = body;
        } else {
          bridgeState.messagePayload = body;
          bridgeState.groupSummaryStatus = 'processing';
        }
        bridgeState.messagesBySession.set(
          GROUP_SESSION_ID,
          createGroupMessages(String(bridgeState.messagePayload?.text || body.text || '')),
        );
        sendJson(response, 200, {
          ok: true,
          task_id: bridgeState.followupPayload === body ? 'task-chat-group-followup-ui-smoke' : SUMMARY_TASK_ID,
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/complete-group-summary') {
        bridgeState.groupSummaryStatus = 'completed';
        bridgeState.messagesBySession.set(GROUP_SESSION_ID, createGroupMessages(String(bridgeState.messagePayload?.text || '')));
        sendJson(response, 200, { ok: true, summary_status: bridgeState.groupSummaryStatus });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/sessions/load') {
        const body = await readRequestJson(request);
        const targetSessionId = String(body.session_id || bridgeState.currentSessionId);
        if (targetSessionId === GROUP_SESSION_ID && bridgeState.failNextGroupSessionLoad) {
          bridgeState.failNextGroupSessionLoad = false;
          bridgeState.sessionLoadFailures.push(targetSessionId);
          sendJson(response, 500, { ok: false, error: 'planned group session switch failure' });
          return;
        }
        if (targetSessionId === GROUP_SESSION_ID && bridgeState.timeoutNextGroupSessionLoads > 0) {
          bridgeState.timeoutNextGroupSessionLoads -= 1;
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
        if (
          bridgeState.groupCreated
          && targetSessionId === MAIN_SESSION_ID
          && !bridgeState.skipNextMainSessionDelay
        ) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
        if (targetSessionId === MAIN_SESSION_ID) bridgeState.skipNextMainSessionDelay = false;
        bridgeState.currentSessionId = targetSessionId;
        bridgeState.sessionLoadCompletions.push(targetSessionId);
        sendJson(response, 200, { ok: true, session_id: bridgeState.currentSessionId });
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
const groupName = ${JSON.stringify(GROUP_NAME)};
const groupGoal = ${JSON.stringify(GROUP_GOAL)};
const runGroupId = ${JSON.stringify(RUN_GROUP_ID)};
const summaryTaskId = ${JSON.stringify(SUMMARY_TASK_ID)};
let chatLoadCounter = 0;
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 30000);
function requestBridgeJson(pathname, method = 'GET') {
  return new Promise((resolve, reject) => {
    const request = http.request(bridgeUrl + pathname, { method }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8');
        if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(method + ' ' + pathname + ' failed with status ' + response.statusCode + ': ' + body));
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
async function loadChat(win, params = {}) {
  chatLoadCounter += 1;
  const query = new URLSearchParams({
    bridge: bridgeUrl,
    smokeLoad: String(chatLoadCounter),
    ...params,
  });
  await win.loadURL(devUrl + '?' + query.toString() + '#/chat');
  await waitFor(win, () => document.querySelector('[data-testid="chat-composer-input"]'), 'chat composer input');
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
              groupsTab: document.querySelector('[data-testid="chat-session-tab-groups"]')?.textContent || '',
              dialog: document.querySelector('[data-testid="chat-group-dialog"]')?.textContent || '',
              header: document.querySelector('.chat-header')?.textContent || '',
              messages: Array.from(document.querySelectorAll('[data-message-id]')).map((node) => ({
                id: node.getAttribute('data-message-id'),
                className: node.className,
                text: node.textContent,
              })),
              summary: Array.from(document.querySelectorAll('[data-testid="chat-message-summary-status"]')).map((node) => ({
                task: node.getAttribute('data-summary-task-id'),
                status: node.getAttribute('data-summary-status'),
                tone: node.getAttribute('data-summary-tone'),
                runGroup: node.getAttribute('data-run-group-id'),
                text: node.textContent,
              })),
              followup: Array.from(document.querySelectorAll('[data-testid="chat-message-followup-status"]')).map((node) => ({
                taskIds: node.getAttribute('data-followup-task-ids'),
                agentMessageIds: node.getAttribute('data-followup-agent-message-ids'),
                text: node.textContent,
              })),
              activity: Array.from(document.querySelectorAll('[data-testid="chat-message-activity-row"]')).map((node) => ({
                status: node.getAttribute('data-activity-status'),
                tool: node.getAttribute('data-activity-tool'),
                text: node.textContent,
              })),
              runDetail: document.querySelector('[data-testid="agent-run-detail"]')?.outerHTML || '',
              runEvents: Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]')).map((node) => ({
                event: node.getAttribute('data-run-event'),
                run: node.getAttribute('data-run-event-run-id'),
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
async function waitForSummaryRunDetail(win) {
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const outputEvent = events.find((node) => node.getAttribute('data-run-event') === 'model.output.completed');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'run.completed');
    return window.location.hash.includes(${JSON.stringify(GROUP_SUMMARY_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(GROUP_SUMMARY_RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'main_chat_run'
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(GROUP_SESSION_ID)}
      && result?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})
      && eventTypes.includes('model.output.completed')
      && eventTypes.includes('run.completed')
      && outputEvent?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})
      && completedEvent?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(GROUP_SUMMARY_RUN_ID)});
  }, 'group summary Run Detail replay');
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
  await loadChat(win);
  console.log('[electron-smoke] chat loaded');
  await waitFor(win, () => document.querySelector('[data-testid="chat-session-tab-groups"]'), 'chat groups tab');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-groups\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="chat-session-tab-create"]')?.getAttribute('aria-label') === '创建群组', 'group create action');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-create\\"]').click()", true);
  await waitFor(win, () => Boolean(document.querySelector('[data-testid="chat-group-dialog"]')), 'group dialog');
  await win.webContents.executeJavaScript(\`
    (async () => {
      const input = document.querySelector('[data-testid="chat-group-avatar-file-input"]');
      const buttons = [
        document.querySelector('[data-testid="chat-group-avatar-preview"]'),
        document.querySelector('[data-testid="chat-group-avatar-select"]'),
      ];
      if (!input) throw new Error('chat group avatar file input not found');
      if (buttons.some((button) => !button)) throw new Error('chat group avatar picker button not found');
      let clickCount = 0;
      const hadOwnClick = Object.prototype.hasOwnProperty.call(input, 'click');
      const ownClick = hadOwnClick ? input.click : undefined;
      Object.defineProperty(input, 'click', { configurable: true, value: () => { clickCount += 1; } });
      try {
        buttons.forEach((button) => button.click());
        await new Promise((resolve) => setTimeout(resolve, 0));
      } finally {
        delete input.click;
        if (hadOwnClick) Object.defineProperty(input, 'click', { configurable: true, value: ownClick });
      }
      if (clickCount !== buttons.length) throw new Error('chat group avatar buttons did not target file input');
    })();
  \`, true);
  console.log('[electron-smoke] group avatar picker fallback targets file input');
  async function applyGroupAvatarFile() {
    await win.webContents.executeJavaScript(\`
      (async () => {
        const input = document.querySelector('[data-testid="chat-group-avatar-file-input"]');
        if (!input) throw new Error('chat group avatar file input not found');
        const dataUrl = ${JSON.stringify(GROUP_AVATAR_DATA_URL)};
        const payload = dataUrl.slice(dataUrl.indexOf(',') + 1);
        const bytes = Uint8Array.from(atob(payload), (character) => character.charCodeAt(0));
        const file = new File([bytes], 'group-avatar.svg', { type: 'image/svg+xml' });
        const transfer = new DataTransfer();
        transfer.items.add(file);
        Object.defineProperty(input, 'files', { configurable: true, value: transfer.files });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        delete input.files;
      })();
    \`, true);
  }
  await applyGroupAvatarFile();
  await waitFor(win, () => {
    const image = document.querySelector('[data-testid="chat-group-avatar-preview"] img');
    const clear = document.querySelector('[data-testid="chat-group-avatar-clear"]');
    const clearSecondary = document.querySelector('[data-testid="chat-group-avatar-clear-secondary"]');
    return image?.getAttribute('src')?.startsWith('data:image/svg+xml')
      && clear
      && !clear.disabled
      && clearSecondary
      && !clearSecondary.disabled;
  }, 'group avatar preview');
  console.log('[electron-smoke] group avatar preview rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-group-avatar-clear-secondary\\"]').click()", true);
  await waitFor(win, () => {
    const image = document.querySelector('[data-testid="chat-group-avatar-preview"] img');
    const clear = document.querySelector('[data-testid="chat-group-avatar-clear"]');
    return !image && clear?.disabled;
  }, 'cleared group avatar');
  console.log('[electron-smoke] group avatar cleared');
  await applyGroupAvatarFile();
  await waitFor(win, () => document.querySelector('[data-testid="chat-group-avatar-preview"] img')?.getAttribute('src')?.startsWith('data:image/svg+xml'), 'group avatar reapplied');
  await win.webContents.executeJavaScript(\`
    (() => {
      const setNativeValue = (element, value) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
      };
      setNativeValue(document.querySelector('[data-testid="chat-group-name-input"]'), ${JSON.stringify(GROUP_NAME)});
      document.querySelector('[data-testid="chat-group-agent-member-checkbox"]').click();
    })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-group-dialog-submit"]')?.disabled, 'enabled group create');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-group-dialog-submit\\"]').click()", true);
  await waitFor(win, () => (
    !document.querySelector('[data-testid="chat-group-dialog"]')
    && document.querySelector('[data-testid="chat-group-settings"]')
    && document.querySelector('.chat-header')?.textContent.includes(${JSON.stringify(GROUP_NAME)})
  ), 'created group selected');
  await waitFor(win, () => (
    document.body.textContent.includes('发送消息开始对话')
    && !document.body.textContent.includes('正在加载对话')
  ), 'created group empty conversation settled');
  console.log('[electron-smoke] group created');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-agents\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes('Main chat')), 'main session switch target');
  await win.webContents.executeJavaScript("Array.from(document.querySelectorAll('.chat-item')).find((node) => node.textContent.includes('Main chat')).click()", true);
  await new Promise((resolve) => setTimeout(resolve, 60));
  await waitFor(win, () => {
    const create = document.querySelector('[data-testid="chat-session-tab-create"]');
    const newConversation = document.querySelector('.chat-header button[aria-label="新对话"]');
    const remove = document.querySelector('.chat-header button[aria-label^="删除"]');
    const groupSettings = document.querySelector('[data-testid="chat-group-settings"]');
    return create?.disabled && newConversation?.disabled && remove?.disabled && groupSettings?.disabled;
  }, 'destructive conversation controls locked during switch');
  console.log('[electron-smoke] destructive conversation controls lock during mutation');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-groups\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)})), 'group session switch target');
  await win.webContents.executeJavaScript(\`
    (() => {
      const target = Array.from(document.querySelectorAll('.chat-item'))
        .find((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)}));
      if (!target) throw new Error('missing group session switch target');
      target.click();
    })();
  \`, true);
  await waitFor(win, async () => {
    const bridge = new URLSearchParams(window.location.search).get('bridge');
    const state = await fetch(bridge + '/__smoke/session-switch-state').then((response) => response.json());
    const completions = state.session_load_completions || [];
    return state.current_session_id === ${JSON.stringify(GROUP_SESSION_ID)}
      && completions.length >= 2
      && completions[completions.length - 2] === ${JSON.stringify(MAIN_SESSION_ID)}
      && completions[completions.length - 1] === ${JSON.stringify(GROUP_SESSION_ID)};
  }, 'latest rapid session switch wins');
  await waitFor(win, () => document.querySelector('.chat-header')?.textContent.includes(${JSON.stringify(GROUP_NAME)}), 'latest rapid session switch rendered');
  console.log('[electron-smoke] rapid session switches preserve latest target');
  await win.webContents.executeJavaScript(
    ${JSON.stringify(`window.location.hash = '#/chat?session_id=${encodeURIComponent(MAIN_SESSION_ID)}'`)},
    true
  );
  await new Promise((resolve) => setTimeout(resolve, 60));
  await win.webContents.executeJavaScript(
    ${JSON.stringify(`window.location.hash = '#/chat?session_id=${encodeURIComponent(GROUP_SESSION_ID)}'`)},
    true
  );
  await waitFor(win, async () => {
    const bridge = new URLSearchParams(window.location.search).get('bridge');
    const state = await fetch(bridge + '/__smoke/session-switch-state').then((response) => response.json());
    const completions = state.session_load_completions || [];
    return state.current_session_id === ${JSON.stringify(GROUP_SESSION_ID)}
      && completions.length >= 4
      && completions[completions.length - 2] === ${JSON.stringify(MAIN_SESSION_ID)}
      && completions[completions.length - 1] === ${JSON.stringify(GROUP_SESSION_ID)}
      && document.querySelectorAll('[data-message-id^="local:"]').length === 0;
  }, 'latest route handoff wins without optimistic message leak');
  console.log('[electron-smoke] route handoff delegates to the serialized session switch state machine');
  await requestBridgeJson('/__smoke/fail-next-group-session-load', 'POST');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-agents\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes('Main chat')), 'failed-switch main target');
  await win.webContents.executeJavaScript("Array.from(document.querySelectorAll('.chat-item')).find((node) => node.textContent.includes('Main chat')).click()", true);
  await new Promise((resolve) => setTimeout(resolve, 60));
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-groups\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)})), 'failed-switch group target');
  await win.webContents.executeJavaScript(\`
    Array.from(document.querySelectorAll('.chat-item'))
      .find((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)}))?.click();
  \`, true);
  await waitFor(win, async () => {
    const bridge = new URLSearchParams(window.location.search).get('bridge');
    const state = await fetch(bridge + '/__smoke/session-switch-state').then((response) => response.json());
    const failures = state.session_load_failures || [];
    return state.current_session_id === ${JSON.stringify(MAIN_SESSION_ID)}
      && failures[failures.length - 1] === ${JSON.stringify(GROUP_SESSION_ID)}
      && !document.querySelector('.chat-header')?.textContent.includes(${JSON.stringify(GROUP_NAME)})
      && !document.querySelector('[data-testid="chat-composer-input"]')?.disabled
      && !document.body.textContent.includes('正在加载对话');
  }, 'failed latest switch restores authoritative main session');
  console.log('[electron-smoke] failed latest switch restored authoritative server session');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-groups\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)})), 'restore group target');
  await win.webContents.executeJavaScript(\`
    Array.from(document.querySelectorAll('.chat-item'))
      .find((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)}))?.click();
  \`, true);
  await waitFor(win, () => document.querySelector('.chat-header')?.textContent.includes(${JSON.stringify(GROUP_NAME)}), 'group restored after failed switch');
  await loadChat(win, { chatRequestTimeoutMs: '120' });
  await requestBridgeJson('/__smoke/timeout-next-group-session-loads', 'POST');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-agents\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes('Main chat')), 'timeout main target');
  await win.webContents.executeJavaScript("Array.from(document.querySelectorAll('.chat-item')).find((node) => node.textContent.includes('Main chat')).click()", true);
  await new Promise((resolve) => setTimeout(resolve, 60));
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-session-tab-groups\\"]').click()", true);
  await waitFor(win, () => Array.from(document.querySelectorAll('.chat-item')).some((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)})), 'timeout group target');
  await win.webContents.executeJavaScript(\`
    Array.from(document.querySelectorAll('.chat-item'))
      .find((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)}))?.click();
  \`, true);
  await waitFor(win, async () => {
    const bridge = new URLSearchParams(window.location.search).get('bridge');
    const state = await fetch(bridge + '/__smoke/session-switch-state').then((response) => response.json());
    const form = document.querySelector('.chat-input-area');
    const input = document.querySelector('[data-testid="chat-composer-input"]');
    const attach = document.querySelector('[data-testid="chat-composer-image-attach-button"]');
    const send = document.querySelector('[data-testid="chat-composer-send"]');
    return state.timeout_group_loads_remaining === 0
      && form?.getAttribute('data-conversation-transition-locked') === 'true'
      && input?.disabled
      && attach?.disabled
      && send?.disabled;
  }, 'double timeout locks composer');
  console.log('[electron-smoke] double timeout keeps composer locked');
  await win.webContents.executeJavaScript(\`
    Array.from(document.querySelectorAll('.chat-item'))
      .find((node) => node.textContent.includes(${JSON.stringify(GROUP_NAME)}))?.click();
  \`, true);
  await waitFor(win, () => {
    const form = document.querySelector('.chat-input-area');
    const input = document.querySelector('[data-testid="chat-composer-input"]');
    return document.querySelector('.chat-header')?.textContent.includes(${JSON.stringify(GROUP_NAME)})
      && form?.getAttribute('data-conversation-transition-locked') === 'false'
      && !input?.disabled;
  }, 'composer unlocks after confirmed retry');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-composer-input"]');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, ${JSON.stringify(GROUP_GOAL)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-composer-send"]')?.disabled, 'enabled group send');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-send\\"]').click()", true);
  await waitFor(win, () => {
    const summary = document.querySelector('[data-testid="chat-message-summary-status"]');
    return summary
      && summary.getAttribute('data-summary-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}
      && summary.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && summary.getAttribute('data-summary-tone') === 'pending'
      && summary.getAttribute('data-summary-status') === 'processing'
      && summary.textContent.includes('Waiting') === false
      && document.body.textContent.includes('Group UI Agent accepted the task')
      && document.body.textContent.includes(${JSON.stringify(GROUP_GOAL)})
      && !document.body.textContent.includes('oha.group_dispatch')
      && !document.body.textContent.includes('<oha_group_dispatch>')
      && !document.body.textContent.includes('run_oha_agent');
  }, 'group summary status');
  console.log('[electron-smoke] group summary rendered');
  await requestBridgeJson('/__smoke/complete-group-summary', 'POST');
  await loadChat(win);
  await waitFor(win, () => {
    const summary = document.querySelector('[data-testid="chat-message-summary-status"]');
    const summaryMessage = document.querySelector('[data-message-id="chat-group-ui-main-summary-message"]');
    return summary
      && summary.getAttribute('data-summary-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}
      && summary.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && summary.getAttribute('data-summary-tone') === 'completed'
      && summary.getAttribute('data-summary-status') === 'completed'
      && summary.textContent.includes('主模型已整理')
      && !summary.textContent.includes('等待主模型整理')
      && summaryMessage?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})
      && !summaryMessage?.querySelector('[data-testid="chat-message-open-run-detail"]')
      && document.body.textContent.includes('Group UI Agent accepted the task')
      && !document.body.textContent.includes('oha.group_dispatch')
      && !document.body.textContent.includes('<oha_group_dispatch>')
      && !document.body.textContent.includes('run_oha_agent');
  }, 'group completed summary status');
  console.log('[electron-smoke] group summary completion rendered');
  await loadChat(win, {
    session_id: ${JSON.stringify(GROUP_SESSION_ID)},
    conversation_kind: 'group',
    task_id: ${JSON.stringify(SUMMARY_TASK_ID)},
  });
  await waitFor(win, () => {
    const summaryMessage = document.querySelector('[data-message-id="chat-group-ui-main-summary-message"]');
    return summaryMessage?.className.includes('search-highlighted')
      && summaryMessage.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})
      && document.body.textContent.includes(${JSON.stringify(GROUP_NAME)});
  }, 'launcher task handoff highlights group summary message');
  console.log('[electron-smoke] launcher task handoff highlighted group summary');
  await loadChat(win);
  await waitFor(win, () => {
    const summaryMessage = document.querySelector('[data-message-id="chat-group-ui-main-summary-message"]');
    return summaryMessage?.textContent.includes(${JSON.stringify(GROUP_SUMMARY_RESULT)})
      && document.body.textContent.includes('Group UI Agent accepted the task')
      && !summaryMessage?.querySelector('[data-testid="chat-message-open-run-detail"]')
      && !document.body.textContent.includes('oha.group_dispatch')
      && !document.body.textContent.includes('<oha_group_dispatch>')
      && !document.body.textContent.includes('run_oha_agent');
  }, 'group summary chat retained without Run Detail CTA');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-composer-input"]');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, ${JSON.stringify(GROUP_FOLLOWUP_TEXT)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })();
  \`, true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-composer-send"]')?.disabled, 'enabled group follow-up send');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-send\\"]').click()", true);
  await loadChat(win, {
    session_id: ${JSON.stringify(GROUP_SESSION_ID)},
    conversation_kind: 'group',
  });
  await waitFor(win, () => {
    const followup = document.querySelector('[data-testid="chat-message-followup-status"]');
    return followup
      && followup.getAttribute('data-followup-task-ids') === ${JSON.stringify(GROUP_AGENT_TASK_ID)}
      && followup.getAttribute('data-followup-agent-message-ids') === 'chat-group-ui-agent-summary-message'
      && followup.textContent.includes('已作为当前群组任务补充')
      && document.body.textContent.includes(${JSON.stringify(GROUP_FOLLOWUP_TEXT)});
  }, 'group follow-up status');
  console.log('[electron-smoke] group follow-up status rendered');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-group-summary-smoke-'));
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
  const groupPayload = bridgeState.groupCreatePayload;
  if (!groupPayload) throw new Error('group was not created');
  if (groupPayload.name !== GROUP_NAME) throw new Error(`unexpected group name: ${groupPayload.name}`);
  const participantIds = Array.isArray(groupPayload.participant_ids) ? groupPayload.participant_ids : [];
  if (participantIds.length !== 1 || participantIds[0] !== AGENT_ID) {
    throw new Error(`unexpected group participants: ${JSON.stringify(participantIds)}`);
  }
  if (!String(groupPayload.avatar_url || '').startsWith('data:image/svg+xml')) {
    throw new Error('group avatar was not submitted as a data URL');
  }
  const messagePayload = bridgeState.messagePayload;
  if (!messagePayload) throw new Error('group message was not sent');
  if (messagePayload.text !== GROUP_GOAL) throw new Error(`unexpected group message text: ${messagePayload.text}`);
  if (!messagePayload.client_message_id) throw new Error('group message did not include client_message_id');
  if (Array.isArray(messagePayload.attachments) && messagePayload.attachments.length) {
    throw new Error('group message smoke unexpectedly sent attachments');
  }
  const followupPayload = bridgeState.followupPayload;
  if (!followupPayload) throw new Error('group follow-up message was not sent');
  if (followupPayload.text !== GROUP_FOLLOWUP_TEXT) {
    throw new Error(`unexpected group follow-up text: ${followupPayload.text}`);
  }
  if (!followupPayload.client_message_id) throw new Error('group follow-up message did not include client_message_id');
  if (bridgeState.currentSessionId !== GROUP_SESSION_ID) {
    throw new Error(`message was sent outside the created group: ${bridgeState.currentSessionId}`);
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
