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
const SESSION_ID = 'chat_delegated_summary_ui_smoke_session';
const SOURCE_TASK_ID = 'task-chat-delegated-summary-source-ui-smoke';
const SUMMARY_TASK_ID = 'task-chat-delegated-summary-ui-smoke';
const DELEGATED_RUN_ID = 'agent_run_chat_delegated_summary_ui_smoke';
const SUMMARY_RUN_ID = 'main_chat_run_delegated_summary_ui_smoke';
const RUN_GROUP_ID = 'run_group_chat_delegated_summary_ui_smoke';
const AGENT_ID = 'coding-agent';
const AGENT_NAME = 'Coding Agent';
const APPROVAL_ID = 'approval-chat-delegated-summary-ui-smoke';
const APPROVAL_COMMAND = 'printf delegated-summary-ui-smoke';
const DELEGATED_GOAL = 'Build delegated summary UI smoke evidence';
const DELEGATED_RESULT = 'Coding Agent completed delegated summary UI smoke.';
const REJECTED_RESULT = 'Delegated run rejected from Chat.';
const SUMMARY_RESULT = 'Delegated summary UI smoke final summary.';
const REJECTED_SUMMARY_RESULT = 'Delegated summary UI smoke rejected summary.';
const now = new Date().toISOString();

const bridgeState = {
  delegatedStatus: 'approval_required',
  approveCalls: 0,
  rejectCalls: 0,
  summaryCalls: 0,
  summaryVisible: false,
  summaryStatus: '',
  summaryPayload: null,
  summaryRequests: [],
};

const agentRunnable = {
  id: AGENT_ID,
  name: AGENT_NAME,
  nickname: 'Coding',
  kind: 'agent',
  enabled: true,
  output_contract: 'report',
  tool_policy: {
    allowed_tools: ['terminal.run'],
    approval_required: { 'terminal.run': true },
  },
};

function log(message) {
  process.stdout.write(`[chat-delegated-summary-ui-smoke] ${message}\n`);
}

function pendingApproval() {
  return {
    approval_id: APPROVAL_ID,
    tool: 'terminal.run',
    input_preview: {
      command: APPROVAL_COMMAND,
      cwd: '/workspace',
      reason: 'Chat delegated summary UI smoke',
    },
    requested_at: now,
  };
}

function delegatedRun() {
  const completed = bridgeState.delegatedStatus === 'completed';
  const cancelled = bridgeState.delegatedStatus === 'cancelled';
  return {
    run_id: DELEGATED_RUN_ID,
    kind: 'agent_run',
    status: completed ? 'completed' : cancelled ? 'cancelled' : 'approval_required',
    runnable_id: AGENT_ID,
    runnable_name: AGENT_NAME,
    session_id: SESSION_ID,
    task_id: SOURCE_TASK_ID,
    run_group_id: RUN_GROUP_ID,
    user_goal: DELEGATED_GOAL,
    pending_approval: bridgeState.delegatedStatus === 'approval_required' ? pendingApproval() : {},
    result: completed ? DELEGATED_RESULT : cancelled ? REJECTED_RESULT : '',
    task_run_link_run_status: completed ? 'completed' : cancelled ? 'cancelled' : 'approval_required',
    task_run_link_last_event_sequence: completed ? 5 : cancelled ? 3 : 1,
    timeline: completed
      ? [
          { event: 'agent.tool.approval_required', status: 'approval_required', tool: 'terminal.run' },
          { event: 'agent.tool.approval_approved', status: 'running', tool: 'terminal.run' },
          { event: 'agent.tool.call', status: 'completed', tool: 'terminal.run' },
          { event: 'model.output.completed', status: 'completed', detail: DELEGATED_RESULT },
          { event: 'agent.run.completed', status: 'completed', detail: DELEGATED_RESULT },
        ]
      : cancelled
        ? [
            { event: 'agent.tool.approval_required', status: 'approval_required', tool: 'terminal.run' },
            { event: 'agent.tool.approval_rejected', status: 'cancelled', tool: 'terminal.run' },
            { event: 'agent.run.cancelled', status: 'cancelled' },
          ]
        : [
            { event: 'agent.tool.approval_required', status: 'approval_required', tool: 'terminal.run' },
          ],
    artifacts: [],
    created_at: now,
    updated_at: now,
  };
}

function summaryRun() {
  return {
    run_id: SUMMARY_RUN_ID,
    kind: 'main_chat_run',
    status: 'completed',
    session_id: SESSION_ID,
    task_id: SUMMARY_TASK_ID,
    run_group_id: RUN_GROUP_ID,
    user_goal: `Summarize delegated Run ${DELEGATED_RUN_ID}`,
    result: summaryResult(),
    task_run_link_run_status: 'completed',
    task_run_link_last_event_sequence: 2,
    timeline: [
      { event: 'model.output.completed', status: 'completed', detail: summaryResult() },
      { event: 'run.completed', status: 'completed', detail: summaryResult() },
    ],
    artifacts: [],
    created_at: now,
    updated_at: now,
  };
}

function delegatedRunEvents() {
  const approvalRequired = {
    run_id: DELEGATED_RUN_ID,
    sequence: 1,
    event_type: 'agent.tool.approval_required',
    actor: 'agent',
    visibility: 'public',
    sensitivity: 'normal',
    payload: { tool: 'terminal.run', approval_id: APPROVAL_ID, input_preview: pendingApproval().input_preview },
    created_at: now,
  };
  if (bridgeState.delegatedStatus === 'approval_required') return [approvalRequired];
  if (bridgeState.delegatedStatus === 'cancelled') {
    return [
      approvalRequired,
      {
        run_id: DELEGATED_RUN_ID,
        sequence: 2,
        event_type: 'agent.tool.approval_rejected',
        actor: 'user',
        visibility: 'public',
        sensitivity: 'normal',
        payload: { tool: 'terminal.run', approval_id: APPROVAL_ID },
        created_at: now,
      },
      {
        run_id: DELEGATED_RUN_ID,
        sequence: 3,
        event_type: 'agent.run.cancelled',
        actor: 'agent',
        visibility: 'public',
        sensitivity: 'normal',
        payload: { status: 'cancelled' },
        created_at: now,
      },
    ];
  }
  return [
    approvalRequired,
    {
      run_id: DELEGATED_RUN_ID,
      sequence: 2,
      event_type: 'agent.tool.approval_approved',
      actor: 'user',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', approval_id: APPROVAL_ID },
      created_at: now,
    },
    {
      run_id: DELEGATED_RUN_ID,
      sequence: 3,
      event_type: 'agent.tool.call',
      actor: 'tool',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { tool: 'terminal.run', command: APPROVAL_COMMAND, status: 'completed' },
      created_at: now,
    },
    {
      run_id: DELEGATED_RUN_ID,
      sequence: 4,
      event_type: 'model.output.completed',
      actor: 'model',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { content: DELEGATED_RESULT },
      created_at: now,
    },
    {
      run_id: DELEGATED_RUN_ID,
      sequence: 5,
      event_type: 'agent.run.completed',
      actor: 'agent',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { result: DELEGATED_RESULT },
      created_at: now,
    },
  ];
}

function summaryRunEvents() {
  return [
    {
      run_id: SUMMARY_RUN_ID,
      sequence: 1,
      event_type: 'model.output.completed',
      actor: 'model',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { content: summaryResult() },
      created_at: now,
    },
    {
      run_id: SUMMARY_RUN_ID,
      sequence: 2,
      event_type: 'run.completed',
      actor: 'runtime',
      visibility: 'public',
      sensitivity: 'normal',
      payload: { result: summaryResult() },
      created_at: now,
    },
  ];
}

function summaryResult() {
  return bridgeState.summaryStatus === 'cancelled' ? REJECTED_SUMMARY_RESULT : SUMMARY_RESULT;
}

function runGroup() {
  const completed = bridgeState.delegatedStatus === 'completed';
  const cancelled = bridgeState.delegatedStatus === 'cancelled';
  return {
    run_group_id: RUN_GROUP_ID,
    source: 'delegation',
    status: completed ? 'completed' : cancelled ? 'cancelled' : 'approval_required',
    title: 'Chat delegated summary UI smoke',
    summary: bridgeState.summaryVisible ? summaryResult() : '',
    root_run_id: DELEGATED_RUN_ID,
    child_run_ids: bridgeState.summaryVisible ? [DELEGATED_RUN_ID, SUMMARY_RUN_ID] : [DELEGATED_RUN_ID],
    created_at: now,
    updated_at: now,
  };
}

function delegatedActivityEvent() {
  const pending = bridgeState.delegatedStatus === 'approval_required';
  const cancelled = bridgeState.delegatedStatus === 'cancelled';
  return {
    event_id: 'activity-chat-delegated-summary-ui-smoke',
    task_id: SOURCE_TASK_ID,
    title: pending
      ? `${AGENT_NAME} waiting for approval`
      : cancelled
        ? `${AGENT_NAME} delegated run rejected`
        : `${AGENT_NAME} completed delegated run`,
    detail: pending
      ? `Tool: terminal.run\nCommand: ${APPROVAL_COMMAND}\nAssociated task: ${DELEGATED_GOAL}`
      : cancelled
        ? REJECTED_RESULT
        : DELEGATED_RESULT,
    tool_name: 'oha.delegation',
    status: pending ? 'approval_required' : bridgeState.delegatedStatus,
    metadata: {
      run_id: DELEGATED_RUN_ID,
      run_group_id: RUN_GROUP_ID,
      run_status: pending ? 'approval_required' : bridgeState.delegatedStatus,
      delegated_goal: DELEGATED_GOAL,
      pending_approval: pending ? pendingApproval() : {},
    },
    created_at: now,
  };
}

function chatMessages() {
  const messages = [
    {
      id: 'user-chat-delegated-summary-ui-smoke',
      role: 'user',
      content: 'Ask Coding Agent to prepare delegated summary UI smoke evidence.',
      status: 'completed',
      created_at: now,
      metadata: { task_id: SOURCE_TASK_ID },
    },
    {
      id: 'assistant-chat-delegated-summary-ui-smoke-source',
      role: 'assistant',
      content: 'Coding Agent is handling the delegated work.',
      status: bridgeState.delegatedStatus === 'approval_required' ? 'processing' : 'completed',
      created_at: now,
      task_id: SOURCE_TASK_ID,
      metadata: {
        task_id: SOURCE_TASK_ID,
        run_group_id: RUN_GROUP_ID,
        sender: { kind: 'assistant', name: 'Oha-Yachiyo' },
      },
      activity_events: [delegatedActivityEvent()],
    },
  ];
  if (bridgeState.summaryVisible) {
    messages.push({
      id: 'assistant-chat-delegated-summary-ui-smoke-summary',
      role: 'assistant',
      content: summaryResult(),
      status: 'completed',
      created_at: now,
      task_id: SUMMARY_TASK_ID,
      metadata: {
        task_id: SUMMARY_TASK_ID,
        run_id: SUMMARY_RUN_ID,
        run_status: 'completed',
        run_group_id: RUN_GROUP_ID,
        delegated_run_summary_for_run_id: DELEGATED_RUN_ID,
        delegated_run_source_task_id: SOURCE_TASK_ID,
        sender: { kind: 'main', name: 'Oha-Yachiyo' },
      },
    });
  }
  return messages;
}

function messagesPayload() {
  const pending = bridgeState.delegatedStatus === 'approval_required';
  return {
    ok: true,
    session_id: SESSION_ID,
    messages: chatMessages(),
    session_context: { conversation_kind: 'main' },
    is_processing: pending,
    processing_count: pending ? 1 : 0,
    approval_count: pending ? 1 : 0,
    token_count: 0,
  };
}

function sessionsPayload() {
  const pending = bridgeState.delegatedStatus === 'approval_required';
  return {
    ok: true,
    current_session_id: SESSION_ID,
    sessions: [
      {
        session_id: SESSION_ID,
        title: 'Chat delegated summary UI smoke',
        conversation_kind: 'main',
        message_count: chatMessages().length,
        token_count: 0,
        is_processing: pending,
        processing_count: pending ? 1 : 0,
        latest_message_preview: bridgeState.summaryVisible
          ? summaryResult()
          : pending
            ? 'Coding Agent waiting for approval'
            : bridgeState.delegatedStatus === 'cancelled'
              ? REJECTED_RESULT
              : DELEGATED_RESULT,
        latest_message_status: pending ? 'processing' : 'completed',
        updated_at: now,
      },
    ],
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

function runEventsPage(events, url) {
  const afterSequence = Number(url.searchParams.get('after_sequence') || '0');
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  return {
    after_sequence: Math.max(0, afterSequence),
    limit,
    events: events.filter((event) => event.sequence > afterSequence).slice(0, limit),
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
            name: AGENT_NAME,
            nickname: 'Coding',
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
        sendJson(response, 200, { ok: true, profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, {
          runs: bridgeState.summaryVisible ? [summaryRun(), delegatedRun()] : [delegatedRun()],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${DELEGATED_RUN_ID}`) {
        sendJson(response, 200, delegatedRun());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${SUMMARY_RUN_ID}`) {
        sendJson(response, bridgeState.summaryVisible ? 200 : 404, bridgeState.summaryVisible ? summaryRun() : { ok: false, error: 'summary run not created' });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [runGroup()] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${DELEGATED_RUN_ID}/events`) {
        sendJson(response, 200, { run_id: DELEGATED_RUN_ID, ...runEventsPage(delegatedRunEvents(), url) });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${SUMMARY_RUN_ID}/events`) {
        sendJson(response, 200, { run_id: SUMMARY_RUN_ID, ...runEventsPage(summaryRunEvents(), url) });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/state') {
        sendJson(response, 200, {
          delegatedStatus: bridgeState.delegatedStatus,
          approveCalls: bridgeState.approveCalls,
          rejectCalls: bridgeState.rejectCalls,
          summaryCalls: bridgeState.summaryCalls,
          summaryVisible: bridgeState.summaryVisible,
          summaryStatus: bridgeState.summaryStatus,
          summaryRequests: bridgeState.summaryRequests,
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${DELEGATED_RUN_ID}/approval/approve`) {
        bridgeState.delegatedStatus = 'completed';
        bridgeState.approveCalls += 1;
        sendJson(response, 200, delegatedRun());
        return;
      }
      if (request.method === 'POST' && url.pathname === `/ui/runs/${DELEGATED_RUN_ID}/approval/reject`) {
        bridgeState.delegatedStatus = 'cancelled';
        bridgeState.rejectCalls += 1;
        sendJson(response, 200, delegatedRun());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/delegated-run-summary') {
        const body = await readRequestJson(request);
        bridgeState.summaryPayload = body;
        bridgeState.summaryStatus = bridgeState.delegatedStatus;
        bridgeState.summaryVisible = true;
        bridgeState.summaryCalls += 1;
        bridgeState.summaryRequests.push({ body, status: bridgeState.delegatedStatus });
        sendJson(response, 200, {
          ok: true,
          summary_created: true,
          message_id: 'assistant-chat-delegated-summary-ui-smoke-summary',
          task_id: SUMMARY_TASK_ID,
          run_id: DELEGATED_RUN_ID,
          run_group_id: RUN_GROUP_ID,
          run_status: bridgeState.delegatedStatus,
          source_task_id: SOURCE_TASK_ID,
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/reset-delegated-approval') {
        bridgeState.delegatedStatus = 'approval_required';
        bridgeState.summaryVisible = false;
        bridgeState.summaryStatus = '';
        bridgeState.summaryPayload = null;
        sendJson(response, 200, { ok: true });
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
let chatLoadCounter = 0;
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 45000);
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
function postBridgeReset() {
  return requestBridgeJson('/__smoke/reset-delegated-approval', 'POST');
}
function waitForBridgeState(predicate, label, timeout = 18000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const state = await requestBridgeJson('/__smoke/state');
        if (predicate(state)) {
          resolve(state);
          return;
        }
      } catch {}
      if (Date.now() - started > timeout) {
        reject(new Error('timeout waiting for bridge state: ' + label));
      } else {
        setTimeout(tick, 120);
      }
    };
    tick();
  });
}
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
              notice: document.querySelector('[data-testid="chat-composer-approval-notice"]')?.outerHTML || '',
              messages: Array.from(document.querySelectorAll('[data-message-id]')).map((node) => ({
                id: node.getAttribute('data-message-id'),
                className: node.className,
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
async function waitForActivityApproval(win) {
  await waitFor(win, () => {
    const notice = document.querySelector('[data-testid="chat-composer-approval-notice"]');
    const openRun = document.querySelector('[data-testid="chat-composer-approval-open-run-detail"]');
    const approve = document.querySelector('[data-testid="chat-composer-approval-approve"]');
    const reject = document.querySelector('[data-testid="chat-composer-approval-reject"]');
    const row = document.querySelector('[data-testid="chat-message-activity-row"]');
    return notice?.getAttribute('data-approval-source') === 'activity'
      && notice?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && notice?.getAttribute('data-approval-id') === ${JSON.stringify(APPROVAL_ID)}
      && notice?.getAttribute('data-approval-tool') === 'terminal.run'
      && notice.textContent.includes(${JSON.stringify(APPROVAL_COMMAND)})
      && row?.getAttribute('data-activity-status') === 'approval_required'
      && row?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && row?.getAttribute('data-run-status') === 'approval_required'
      && row.textContent.includes('Coding Agent')
      && openRun?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && openRun?.getAttribute('data-run-status') === 'approval_required'
      && approve
      && reject;
  }, 'activity approval composer notice');
}
async function waitForApprovalRunDetail(win) {
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const approval = document.querySelector('[data-testid="agent-run-detail-approval"]');
    const request = document.querySelector('[data-testid="agent-run-approval-request"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    return window.location.hash.includes(${JSON.stringify(DELEGATED_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'agent_run'
      && detail?.getAttribute('data-run-status') === 'approval_required'
      && detail?.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(SOURCE_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
      && eventTypes.includes('agent.tool.approval_required')
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)})
      && approval
      && request?.textContent.includes('terminal.run')
      && request?.textContent.includes(${JSON.stringify(APPROVAL_COMMAND)});
  }, 'delegated approval Run Detail handoff');
}
async function waitForCompletedRunDetail(win) {
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const outputEvent = events.find((node) => node.getAttribute('data-run-event') === 'model.output.completed');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'agent.run.completed');
    return window.location.hash.includes(${JSON.stringify(DELEGATED_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'agent_run'
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(SOURCE_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
      && result?.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})
      && eventTypes.includes('agent.tool.approval_required')
      && eventTypes.includes('agent.tool.approval_approved')
      && eventTypes.includes('model.output.completed')
      && eventTypes.includes('agent.run.completed')
      && outputEvent?.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})
      && completedEvent?.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)});
  }, 'delegated completed Run Detail replay');
}
async function waitForSummaryRunDetail(win) {
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const outputEvent = events.find((node) => node.getAttribute('data-run-event') === 'model.output.completed');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'run.completed');
    return window.location.hash.includes(${JSON.stringify(SUMMARY_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(SUMMARY_RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'main_chat_run'
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(SUMMARY_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
      && result?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})
      && eventTypes.includes('model.output.completed')
      && eventTypes.includes('run.completed')
      && outputEvent?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})
      && completedEvent?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(SUMMARY_RUN_ID)});
  }, 'delegated summary Run Detail replay');
}
async function waitForCancelledRunDetail(win) {
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    return window.location.hash.includes(${JSON.stringify(DELEGATED_RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'agent_run'
      && detail?.getAttribute('data-run-status') === 'cancelled'
      && detail?.getAttribute('data-run-group-id') === ${JSON.stringify(RUN_GROUP_ID)}
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(SOURCE_TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
      && result?.textContent.includes(${JSON.stringify(REJECTED_RESULT)})
      && eventTypes.includes('agent.tool.approval_required')
      && eventTypes.includes('agent.tool.approval_rejected')
      && eventTypes.includes('agent.run.cancelled')
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)});
  }, 'delegated cancelled Run Detail replay');
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
  await waitForActivityApproval(win);
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-approval-reject\\"]').click()", true);
  await waitForBridgeState((state) => (
    state.rejectCalls === 1
    && state.summaryRequests?.some((request) => request.status === 'cancelled')
  ), 'delegated reject summary request');
  await loadChat(win);
  await waitFor(win, () => {
    const summary = document.querySelector('[data-message-id="assistant-chat-delegated-summary-ui-smoke-summary"]');
    const notice = document.querySelector('[data-testid="chat-composer-approval-notice"]');
    const row = document.querySelector('[data-testid="chat-message-activity-row"]');
    const openRun = document.querySelector('[data-testid="chat-message-activity-open-run-detail"]');
    return summary?.textContent.includes(${JSON.stringify(REJECTED_SUMMARY_RESULT)})
      && !summary.textContent.includes('run_oha_agent')
      && !document.body.textContent.includes('<oha_delegation>')
      && !notice
      && row?.getAttribute('data-activity-status') === 'cancelled'
      && row?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && row?.getAttribute('data-run-status') === 'cancelled'
      && row.textContent.includes(${JSON.stringify(REJECTED_RESULT)})
      && openRun?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && openRun?.getAttribute('data-run-status') === 'cancelled';
  }, 'delegated reject summary created in Chat');
  console.log('[electron-smoke] delegated reject summary rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-message-activity-open-run-detail\\"]').click()", true);
  await waitForCancelledRunDetail(win);
  console.log('[electron-smoke] delegated cancelled Run Detail replay verified');
  await postBridgeReset();
  await loadChat(win);
  await waitForActivityApproval(win);
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-approval-open-run-detail\\"]').click()", true);
  await waitForApprovalRunDetail(win);
  await loadChat(win);
  await waitForActivityApproval(win);
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-approval-approve\\"]').click()", true);
  await waitForBridgeState((state) => (
    state.approveCalls === 1
    && state.summaryRequests?.some((request) => request.status === 'completed')
  ), 'delegated approve summary request');
  await waitFor(win, () => {
    const summary = document.querySelector('[data-message-id="assistant-chat-delegated-summary-ui-smoke-summary"]');
    const notice = document.querySelector('[data-testid="chat-composer-approval-notice"]');
    const row = document.querySelector('[data-testid="chat-message-activity-row"]');
    const openSummary = summary?.querySelector('[data-testid="chat-message-open-run-detail"]');
    const openRun = document.querySelector('[data-testid="chat-message-activity-open-run-detail"]');
    return summary?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})
      && !summary.textContent.includes('run_oha_agent')
      && !document.body.textContent.includes('<oha_delegation>')
      && !notice
      && row?.getAttribute('data-activity-status') === 'completed'
      && row.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})
      && openSummary
      && openRun;
  }, 'delegated summary created in Chat');
  console.log('[electron-smoke] delegated summary rendered');
  await loadChat(win, {
    session_id: ${JSON.stringify(SESSION_ID)},
    conversation_kind: 'agent',
    task_id: ${JSON.stringify(SOURCE_TASK_ID)},
  });
  await waitFor(win, () => {
    const summary = document.querySelector('[data-message-id="assistant-chat-delegated-summary-ui-smoke-summary"]');
    return summary?.className.includes('search-highlighted')
      && summary.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})
      && document.body.textContent.includes(${JSON.stringify(DELEGATED_RESULT)});
  }, 'launcher task handoff highlights delegated summary message');
  console.log('[electron-smoke] launcher task handoff highlighted delegated summary');
  await win.webContents.executeJavaScript("document.querySelector('[data-message-id=\\"assistant-chat-delegated-summary-ui-smoke-summary\\"] [data-testid=\\"chat-message-open-run-detail\\"]').click()", true);
  await waitForSummaryRunDetail(win);
  console.log('[electron-smoke] delegated summary Run Detail replay verified');
  await loadChat(win);
  await waitFor(win, () => {
    const summary = document.querySelector('[data-message-id="assistant-chat-delegated-summary-ui-smoke-summary"]');
    const row = document.querySelector('[data-testid="chat-message-activity-row"]');
    const openRun = document.querySelector('[data-testid="chat-message-activity-open-run-detail"]');
    return summary?.textContent.includes(${JSON.stringify(SUMMARY_RESULT)})
      && row?.getAttribute('data-activity-status') === 'completed'
      && row?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && row?.getAttribute('data-run-status') === 'completed'
      && row.textContent.includes(${JSON.stringify(DELEGATED_RESULT)})
      && openRun?.getAttribute('data-run-id') === ${JSON.stringify(DELEGATED_RUN_ID)}
      && openRun?.getAttribute('data-run-status') === 'completed';
  }, 'delegated summary chat restored after Run Detail');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-message-activity-open-run-detail\\"]').click()", true);
  await waitForCompletedRunDetail(win);
  console.log('[electron-smoke] delegated Run Detail replay verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-delegated-summary-smoke-'));
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
    }, 65_000);
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
  if (bridgeState.approveCalls !== 1) {
    throw new Error(`expected one delegated approval approve call, saw ${bridgeState.approveCalls}`);
  }
  if (bridgeState.rejectCalls !== 1) {
    throw new Error(`expected one delegated approval reject call, saw ${bridgeState.rejectCalls}`);
  }
  if (bridgeState.summaryCalls !== 2) {
    throw new Error(`expected two delegated summary calls, saw ${bridgeState.summaryCalls}`);
  }
  if (bridgeState.summaryRequests.some((request) => request.body?.run_id !== DELEGATED_RUN_ID)) {
    throw new Error(`unexpected delegated summary payloads: ${JSON.stringify(bridgeState.summaryRequests)}`);
  }
  const summaryStatuses = bridgeState.summaryRequests.map((request) => request.status).join(',');
  if (summaryStatuses !== 'cancelled,completed') {
    throw new Error(`expected cancelled then completed delegated summaries, saw ${summaryStatuses}`);
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
