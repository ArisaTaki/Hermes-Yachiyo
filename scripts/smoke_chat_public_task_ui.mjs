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
const AGENT_ID = 'chat-public-task-smoke-agent';
const AGENT_NAME = 'Public Task Smoke Agent';
const TASK_ID = 'task-chat-public-task-ui-smoke';
const ALIAS_TASK_ID = 'task-chat-public-task-alias-smoke';
const RUN_ID = 'run-chat-public-task-ui-smoke';
const APPROVAL_ID = 'approval-chat-public-task-ui-smoke';
const SESSION_ID = 'session-chat-public-task-ui-smoke';
const NEW_SESSION_ID = 'session-chat-public-task-ui-smoke-new';
const PROMPT = 'Draft a public task status card';
const COMPOSER_TEXT = `@"${AGENT_NAME}" ${PROMPT}`;
const TASK_TITLE = 'Public Task Smoke Agent Task';
const TASK_STEP = 'Public runtime events are visible in Chat.';
const TASK_SUMMARY = 'Chat accepted a public Agent task through /yachiyo/tasks.';
const NO_TOOL_FINAL_RESPONSE = '早上好，很高兴见到你。';
const TASK_RESPONSE_DELAY_MS = 900;
const NEW_DRAFT_TEXT = 'Keep this newer composer draft';
const NEW_DRAFT_IMAGE_NAME = 'newer-draft.svg';
const SECOND_MESSAGE_TEXT = 'Second message canonicalized first';
const SECOND_ASSISTANT_TEXT = 'Second message reply';
const THIRD_MESSAGE_TEXT = 'Third message remains optimistic';
const ORDERING_CANONICAL_CREATED_AT = '2099-01-01T00:00:00.000Z';
const SHARED_SESSION_CLIENT_MESSAGE_ID = 'shared-session-client-message-id';
const SAME_ID_SESSION_B_TEXT = 'Session B uses the same client id';
const NEW_DRAFT_IMAGE_DATA_URL = `data:image/svg+xml;base64,${Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="#7c3aed"/></svg>',
).toString('base64')}`;
const now = new Date().toISOString();
const approvedAt = new Date(Date.now() + 1000).toISOString();
const rejectedAt = new Date(Date.now() + 2000).toISOString();

const bridgeState = {
  approvalStatus: 'pending',
  aliasRegressionEnabled: false,
  aliasTaskStatus: 'completed',
  readinessMode: 'cdp_only',
  approveCalls: 0,
  approvePayloads: [],
  legacyMessagePayloads: [],
  legacyRunnableCatalogHits: 0,
  internalRecoveryCompleted: false,
  internalRecoveryFailed: false,
  messageSyncFailures: 0,
  messagesRequested: 0,
  noToolCompleted: false,
  currentSessionId: SESSION_ID,
  rejectCalls: 0,
  requestLog: [],
  runnableCatalogHits: 0,
  taskEventsRequested: 0,
  taskEventAfterSequences: [],
  timelineRequests: 0,
  timelineResponses: 0,
  taskRequest: null,
  taskMode: 'success',
  taskResponseFailed: false,
  taskResponseSent: false,
  sessionClearCalls: 0,
  sessionLoadCalls: 0,
  sessionLoadPayloads: [],
  legacyCanonicalVisible: false,
  legacyResponseSent: false,
  staleTaskListResponses: 0,
  staleTaskListResponsesCompleted: 0,
};

function resetBridgeState() {
  bridgeState.approvalStatus = 'pending';
  bridgeState.aliasRegressionEnabled = false;
  bridgeState.aliasTaskStatus = 'completed';
  bridgeState.readinessMode = 'cdp_only';
  bridgeState.approveCalls = 0;
  bridgeState.approvePayloads = [];
  bridgeState.legacyMessagePayloads = [];
  bridgeState.legacyRunnableCatalogHits = 0;
  bridgeState.internalRecoveryCompleted = false;
  bridgeState.internalRecoveryFailed = false;
  bridgeState.messageSyncFailures = 0;
  bridgeState.messagesRequested = 0;
  bridgeState.noToolCompleted = false;
  bridgeState.currentSessionId = SESSION_ID;
  bridgeState.rejectCalls = 0;
  bridgeState.requestLog = [];
  bridgeState.runnableCatalogHits = 0;
  bridgeState.taskEventsRequested = 0;
  bridgeState.taskEventAfterSequences = [];
  bridgeState.timelineRequests = 0;
  bridgeState.timelineResponses = 0;
  bridgeState.taskRequest = null;
  bridgeState.taskMode = 'success';
  bridgeState.taskResponseFailed = false;
  bridgeState.taskResponseSent = false;
  bridgeState.sessionClearCalls = 0;
  bridgeState.sessionLoadCalls = 0;
  bridgeState.sessionLoadPayloads = [];
  bridgeState.legacyCanonicalVisible = false;
  bridgeState.legacyResponseSent = false;
  bridgeState.staleTaskListResponses = 0;
  bridgeState.staleTaskListResponsesCompleted = 0;
}

const publicAgent = {
  runnable_id: AGENT_ID,
  agent_id: AGENT_ID,
  kind: 'agent',
  name: AGENT_NAME,
  nickname: AGENT_NAME,
  description: 'Smoke agent exposed through the Yachiyo public runnable catalog.',
  enabled: true,
  output_contract: 'report',
  tool_capabilities: ['workspace.read'],
  approval_required_tools: ['workspace.write'],
};

function log(message) {
  process.stdout.write(`[chat-public-task-ui-smoke] ${message}\n`);
}

function pendingApproval() {
  return {
    approval_id: APPROVAL_ID,
    run_id: RUN_ID,
    source_run_id: RUN_ID,
    source_runnable_id: AGENT_ID,
    source_runnable_name: AGENT_NAME,
    title: 'Approve public workspace write',
    description: 'Public task smoke requires Chat approval before continuing.',
    status: 'pending',
    tool_name: 'workspace.write',
    risk_level: 'high',
    input_preview: {
      path: 'public-task-approval-smoke.md',
      reason: 'Chat public task approval smoke',
    },
    policy_reason: 'workspace.write requires user approval',
    requested_at: now,
    open_in_studio_url: `#/agents?run=${encodeURIComponent(RUN_ID)}`,
  };
}

function currentTaskStatus() {
  if (bridgeState.taskMode === 'polling_identity' && bridgeState.timelineResponses === 0) return 'running';
  if (bridgeState.approvalStatus === 'pending') return 'waiting_approval';
  if (bridgeState.approvalStatus === 'approved') return 'running';
  if (bridgeState.approvalStatus === 'rejected') return 'cancelled';
  return 'running';
}

function currentTaskEvents() {
  const events = [
    {
      event_id: 'event-chat-public-task-smoke-1',
      run_id: RUN_ID,
      sequence: 1,
      schema_version: 1,
      event_type: 'agent.run.started',
      title: 'Agent run started',
      detail: 'Public task entered the shared runtime.',
      actor: 'agent',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { task_id: TASK_ID, agent_id: AGENT_ID, prompt: PROMPT },
      created_at: now,
    },
    {
      event_id: 'event-chat-public-task-smoke-2',
      run_id: RUN_ID,
      sequence: 2,
      schema_version: 1,
      event_type: 'agent.tool.call',
      title: 'workspace.read',
      detail: 'The shared runtime exposes tool calls in the Chat task card.',
      actor: 'tool',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { tool: 'workspace.read', status: 'completed' },
      created_at: now,
    },
    {
      event_id: 'event-chat-public-task-smoke-3',
      run_id: RUN_ID,
      sequence: 3,
      schema_version: 1,
      event_type: 'agent.tool.approval_required',
      title: 'workspace.write approval required',
      detail: 'Public task card must expose approval actions in Chat.',
      actor: 'runtime',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { approval_id: APPROVAL_ID, tool: 'workspace.write', status: 'pending' },
      created_at: now,
    },
  ];
  if (bridgeState.approvalStatus === 'approved') {
    events.push({
      event_id: 'event-chat-public-task-smoke-4',
      run_id: RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'agent.tool.approval_approved',
      title: 'workspace.write approved',
      detail: 'Chat approved the public task card approval.',
      actor: 'user',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { approval_id: APPROVAL_ID, tool: 'workspace.write', status: 'approved' },
      created_at: approvedAt,
    });
  }
  if (bridgeState.approvalStatus === 'rejected') {
    events.push({
      event_id: 'event-chat-public-task-smoke-4',
      run_id: RUN_ID,
      sequence: 4,
      schema_version: 1,
      event_type: 'agent.tool.approval_rejected',
      title: 'workspace.write rejected',
      detail: 'Chat rejected the public task card approval.',
      actor: 'user',
      visibility: 'user',
      sensitivity: 'normal',
      payload: { approval_id: APPROVAL_ID, tool: 'workspace.write', status: 'rejected' },
      created_at: rejectedAt,
    });
  }
  return events;
}

function publicTaskSnapshot() {
  if (bridgeState.taskMode === 'no_tool_chat') return noToolTaskSnapshot();
  if (bridgeState.taskMode === 'internal_recovery_chat') return internalRecoveryTaskSnapshot();
  const pending = bridgeState.approvalStatus === 'pending';
  return {
    task_id: TASK_ID,
    conversation_id: SESSION_ID,
    title: TASK_TITLE,
    status: currentTaskStatus(),
    summary: TASK_SUMMARY,
    current_step: pending ? 'Waiting for workspace.write approval.' : TASK_STEP,
    progress_text: pending ? 'workspace.write requires approval' : TASK_STEP,
    needs_user_action: pending,
    pending_approvals: pending ? [pendingApproval()] : [],
    recent_events: currentTaskEvents(),
    artifacts: [],
    planner_summary: {
      intent_kind: 'public_task_smoke',
      selected_tools: ['workspace.read'],
      required_capabilities: ['workspace.read'],
    },
    runtime_execution_envelope: {
      envelope_id: 'envelope-chat-public-task-ui-smoke',
      decision_id: 'decision-chat-public-task-ui-smoke',
      plan_id: 'plan-chat-public-task-ui-smoke',
      intent_kind: 'public_task_smoke',
      requests: [],
    },
    runtime_debug: {
      runtime_doctrine: 'public_task_smoke',
      runtime_stage: 'execute',
      runtime_request_count: 1,
    },
    task_core: {
      core_id: 'core-chat-public-task-ui-smoke',
      workspace: {
        workspace_id: 'workspace-chat-public-task-ui-smoke',
        title: 'Public task smoke workspace',
        items: [],
      },
      todos: [{
        todo_id: 'todo-chat-public-task-ui-smoke',
        title: 'Read the public task workspace',
        status: 'in_progress',
      }],
      checkpoints: [],
    },
    task_progress: {
      status: currentTaskStatus(),
      total_todos: 1,
      completed_todos: 0,
      active_todos: 1,
      progress_text: pending ? 'Waiting for approval' : 'Executing public task',
    },
    open_in_studio_url: `#/agents?run=${encodeURIComponent(RUN_ID)}`,
    created_at: now,
    updated_at: bridgeState.approvalStatus === 'approved'
      ? approvedAt
      : bridgeState.approvalStatus === 'rejected'
        ? rejectedAt
        : now,
  };
}

function noToolTaskSnapshot() {
  return {
    task_id: TASK_ID,
    conversation_id: SESSION_ID,
    title: 'Plain assistant reply',
    status: bridgeState.noToolCompleted ? 'completed' : 'running',
    summary: bridgeState.noToolCompleted ? NO_TOOL_FINAL_RESPONSE : null,
    current_step: null,
    progress_text: null,
    needs_user_action: false,
    pending_approvals: [],
    recent_events: [],
    tool_calls: [],
    artifacts: [],
    planner_summary: {
      intent_kind: 'general',
      selected_tools: [],
      required_capabilities: [],
    },
    runtime_execution_envelope: {
      envelope_id: 'envelope-chat-no-tool',
      decision_id: 'decision-chat-no-tool',
      plan_id: 'plan-chat-no-tool',
      intent_kind: 'general',
      requests: [{
        request_id: 'request-chat-no-tool-planned',
        tool_name: 'workspace.read',
        status: 'planned',
        observation_evidence: {},
        observation_retry: {
          tool: 'workspace.read',
          input: { path: 'README.md' },
          reason: 'Retry only if observation fails',
        },
      }],
    },
    task_progress: {
      status: bridgeState.noToolCompleted ? 'completed' : 'running',
      needs_replan: false,
      failed_verification_count: 0,
    },
    open_in_studio_url: `#/agents?run=${encodeURIComponent(RUN_ID)}`,
    created_at: now,
    updated_at: bridgeState.noToolCompleted ? approvedAt : now,
  };
}

function internalRecoveryTaskSnapshot() {
  const completed = bridgeState.internalRecoveryCompleted;
  const failed = bridgeState.internalRecoveryFailed;
  return {
    task_id: TASK_ID,
    conversation_id: SESSION_ID,
    title: 'Resolve an Apple Music title in the background',
    status: completed ? 'completed' : failed ? 'failed' : 'running',
    summary: failed ? '没有找到可播放的匹配歌曲。' : null,
    current_step: 'Trying alternate title matches',
    progress_text: 'Still working',
    // A task-wide user-action flag must not promote every internal retry into
    // a consumer-facing recovery button. Approvals/permissions are rendered
    // from their own explicit records.
    needs_user_action: true,
    pending_approvals: [],
    recent_events: [],
    tool_calls: [],
    artifacts: [],
    replan_recoveries: [
      {
        request_id: 'replan-internal-observation-retry',
        trigger: 'runtime_observation_retry',
        status: 'requested',
        failure_detail: 'The first localized title did not match the media library.',
        recovery_actions: [{
          action_id: 'retry-internal-observation',
          action_kind: 'runtime_observation_retry',
          label: 'Retry browser title observation',
          tool: 'browser.search',
          input: { query: '超时空辉夜姬 English title' },
        }],
      },
      {
        request_id: 'replan-internal-tool-failure',
        trigger: 'tool_failure',
        status: 'requested',
        failure_detail: 'The localized media query returned no result.',
        recovery_actions: [{
          action_id: 'retry-internal-media-query',
          action_kind: 'replan',
          label: 'Retry Apple Music with resolved title',
          tool: 'media.apple_music_play',
          input: { query: 'Cosmic Princess Kaguya' },
        }],
      },
    ],
    runtime_execution_envelope: {
      envelope_id: 'envelope-chat-internal-recovery',
      decision_id: 'decision-chat-internal-recovery',
      plan_id: 'plan-chat-internal-recovery',
      intent_kind: 'media_playback',
      requests: [{
        request_id: 'request-chat-internal-observation-retry',
        tool_name: 'browser.search',
        status: 'failed',
        observation_evidence: { verification_failed: true },
        observation_retry: {
          tool: 'browser.search',
          input: { query: '超时空辉夜姬 English title' },
          reason: 'Resolve an alternate media title in the background',
        },
      }],
    },
    task_progress: {
      status: completed ? 'completed' : failed ? 'failed' : 'running',
      needs_replan: true,
      failed_verification_count: 1,
      progress_text: 'Trying another match',
    },
    open_in_studio_url: `#/agents?run=${encodeURIComponent(RUN_ID)}`,
    created_at: now,
    updated_at: failed ? rejectedAt : now,
  };
}

function stalePendingTaskSnapshot() {
  const currentApprovalStatus = bridgeState.approvalStatus;
  bridgeState.approvalStatus = 'pending';
  try {
    return publicTaskSnapshot();
  } finally {
    bridgeState.approvalStatus = currentApprovalStatus;
  }
}

function aliasTaskSnapshot() {
  return {
    task_id: ALIAS_TASK_ID,
    conversation_id: SESSION_ID,
    title: 'Shared Alias Task B',
    status: bridgeState.aliasTaskStatus,
    summary: 'Task B shares a run alias with task A but must keep its own task identity.',
    current_step: 'Alias identity verified',
    progress_text: 'Completed',
    needs_user_action: false,
    pending_approvals: [],
    replan_recoveries: [{
      request_id: 'replan-completed-alias-regression',
      trigger: 'verification_failed',
      status: 'requested',
      recovery_actions: [{
        action_id: 'retry-completed-alias-regression',
        label: 'Retry completed alias task',
        tool: 'workspace.read',
        input: { path: 'README.md' },
      }],
    }],
    recent_events: [{
      event_id: 'event-chat-public-task-alias-smoke',
      run_id: RUN_ID,
      sequence: 1,
      event_type: 'agent.tool.completed',
      title: 'Shared alias completed',
      detail: 'Task B intentionally shares Task A run id.',
      actor: 'tool',
      payload: { tool_name: 'workspace.read' },
      status: 'completed',
      created_at: now,
    }],
    artifacts: [],
    created_at: now,
    updated_at: bridgeState.aliasTaskStatus === 'failed' ? rejectedAt : now,
  };
}

function runTimelineSnapshot() {
  if (bridgeState.taskMode === 'no_tool_chat') {
    const task = noToolTaskSnapshot();
    return {
      run_id: RUN_ID,
      task_id: TASK_ID,
      title: task.title,
      status: task.status,
      summary: task.summary,
      events: task.recent_events,
      tool_calls: [],
      pending_approvals: [],
      artifacts: [],
      children: [],
      created_at: now,
      updated_at: task.updated_at,
    };
  }
  return {
    run_id: RUN_ID,
    task_id: TASK_ID,
    title: TASK_TITLE,
    status: bridgeState.approvalStatus === 'pending' ? 'approval_required' : currentTaskStatus(),
    summary: TASK_SUMMARY,
    events: currentTaskEvents(),
    tool_calls: [],
    pending_approvals: bridgeState.approvalStatus === 'pending' ? [pendingApproval()] : [],
    artifacts: [],
    children: [],
    created_at: now,
    updated_at: bridgeState.approvalStatus === 'approved'
      ? approvedAt
      : bridgeState.approvalStatus === 'rejected'
        ? rejectedAt
        : now,
  };
}

function chatMessages() {
  if (
    bridgeState.taskMode === 'public_failure_then_legacy_timeout_late_failure'
    && bridgeState.legacyCanonicalVisible
  ) {
    const request = bridgeState.legacyMessagePayloads[0] || {};
    return [
      {
        id: 'chat-late-failure-user-message',
        role: 'user',
        content: request.text || PROMPT,
        status: 'failed',
        task_id: 'task-late-failure',
        created_at: now,
        metadata: {
          client_message_id: request.client_message_id,
          source: 'chat',
        },
      },
      {
        id: 'chat-late-failure-assistant-message',
        role: 'assistant',
        content: 'Late desktop task failed safely.',
        error: 'Late desktop task failed safely.',
        status: 'failed',
        task_id: 'task-late-failure',
        created_at: now,
        metadata: { source: 'chat', run_status: 'failed' },
      },
    ];
  }
  if (
    bridgeState.taskMode === 'public_failure_then_same_client_id_sessions'
    && bridgeState.currentSessionId === NEW_SESSION_ID
    && bridgeState.legacyCanonicalVisible
  ) {
    const request = bridgeState.legacyMessagePayloads[1] || {};
    return [{
      id: 'chat-same-id-session-b-canonical-message',
      role: 'user',
      content: request.text || SAME_ID_SESSION_B_TEXT,
      status: 'completed',
      created_at: now,
      metadata: {
        client_message_id: request.client_message_id,
        source: 'chat',
      },
    }];
  }
  if (
    bridgeState.taskMode === 'public_failure_then_ordered_second_message'
    && bridgeState.legacyCanonicalVisible
  ) {
    const request = bridgeState.legacyMessagePayloads[1] || {};
    return [
      {
        id: 'chat-ordered-second-user-message',
        role: 'user',
        content: request.text || SECOND_MESSAGE_TEXT,
        status: 'completed',
        created_at: ORDERING_CANONICAL_CREATED_AT,
        metadata: {
          client_message_id: request.client_message_id,
          source: 'chat',
        },
      },
      {
        id: 'chat-ordered-second-assistant-message',
        role: 'assistant',
        content: SECOND_ASSISTANT_TEXT,
        status: 'completed',
        created_at: ORDERING_CANONICAL_CREATED_AT,
        metadata: { source: 'chat' },
      },
    ];
  }
  if (
    bridgeState.taskMode === 'public_failure_then_post_commit_ok_false'
    && bridgeState.legacyCanonicalVisible
  ) {
    const request = bridgeState.legacyMessagePayloads[0] || {};
    return [{
      id: 'chat-post-commit-canonical-user-message',
      role: 'user',
      content: request.text || PROMPT,
      status: 'completed',
      created_at: now,
      metadata: {
        client_message_id: request.client_message_id,
        source: 'chat',
      },
    }];
  }
  if (!bridgeState.taskRequest || !bridgeState.taskResponseSent || bridgeState.taskResponseFailed) return [];
  if (bridgeState.taskMode === 'no_tool_chat') {
    return [
      {
        id: 'chat-public-task-user-message',
        role: 'user',
        content: PROMPT,
        status: 'completed',
        task_id: TASK_ID,
        created_at: now,
        metadata: {
          client_message_id: bridgeState.taskRequest?.metadata?.client_message_id,
          runnable_id: AGENT_ID,
          runnable_kind: 'agent',
          source: 'chat',
        },
      },
      {
        id: 'chat-public-task-assistant-message',
        role: 'assistant',
        content: bridgeState.noToolCompleted ? NO_TOOL_FINAL_RESPONSE : '',
        status: bridgeState.noToolCompleted ? 'completed' : 'processing',
        task_id: TASK_ID,
        created_at: now,
        metadata: {
          task_id: TASK_ID,
          run_id: RUN_ID,
          run_status: bridgeState.noToolCompleted ? 'completed' : 'running',
          runnable_id: AGENT_ID,
          runnable_kind: 'agent',
          source: 'chat',
        },
      },
    ];
  }
  return [
    {
      id: 'chat-public-task-user-message',
      role: 'user',
      content: PROMPT,
      status: 'completed',
      task_id: TASK_ID,
      created_at: now,
      metadata: {
        client_message_id: bridgeState.taskRequest?.metadata?.client_message_id,
        runnable_id: AGENT_ID,
        runnable_kind: 'agent',
        source: 'chat',
      },
    },
    {
      id: 'chat-public-task-assistant-message',
      role: 'assistant',
      content: 'Public Agent task accepted.',
      status: bridgeState.internalRecoveryFailed ? 'failed' : 'processing',
      task_id: TASK_ID,
      created_at: now,
      metadata: {
        task_id: TASK_ID,
        run_id: RUN_ID,
        run_status: bridgeState.internalRecoveryFailed ? 'failed' : 'running',
        runnable_id: AGENT_ID,
        runnable_kind: 'agent',
        source: 'chat',
      },
    },
    ...(bridgeState.aliasRegressionEnabled ? [{
      id: 'chat-public-task-alias-message',
      role: 'assistant',
      content: 'Shared alias task B completed.',
      status: 'completed',
      task_id: ALIAS_TASK_ID,
      created_at: now,
      metadata: {
        task_id: ALIAS_TASK_ID,
        run_id: RUN_ID,
        run_status: 'completed',
        source: 'chat',
      },
    }] : []),
  ];
}

function sessionsPayload() {
  const currentSessionId = bridgeState.currentSessionId;
  const includeOutboxRoundTripSessions = (
    bridgeState.taskMode === 'public_failure_then_post_commit_ok_false'
    || bridgeState.taskMode === 'public_failure_then_same_client_id_sessions'
  );
  const sessionIds = includeOutboxRoundTripSessions
    ? [SESSION_ID, NEW_SESSION_ID]
    : [currentSessionId];
  return {
    ok: true,
    current_session_id: currentSessionId,
    sessions: sessionIds.map((sessionId) => {
      const isOriginalSession = sessionId === SESSION_ID;
      return {
        session_id: sessionId,
        title: isOriginalSession ? 'Chat public task smoke' : 'New Chat smoke',
        conversation_kind: 'main',
        message_count: isOriginalSession ? chatMessages().length : 0,
        token_count: 0,
        is_processing: (
          sessionId === currentSessionId
          && isOriginalSession
          && currentTaskIsProcessing()
        ),
        processing_count: (
          sessionId === currentSessionId
          && isOriginalSession
          && currentTaskIsProcessing()
            ? 1
            : 0
        ),
        updated_at: now,
      };
    }),
  };
}

function messagesPayload() {
  const isOriginalSession = bridgeState.currentSessionId === SESSION_ID;
  const sameClientIdSessionMode = (
    bridgeState.taskMode === 'public_failure_then_same_client_id_sessions'
  );
  return {
    ok: true,
    session_id: bridgeState.currentSessionId,
    messages: isOriginalSession || sameClientIdSessionMode ? chatMessages() : [],
    session_context: { conversation_kind: 'main' },
    is_processing: isOriginalSession && currentTaskIsProcessing(),
    processing_count: isOriginalSession && currentTaskIsProcessing() ? 1 : 0,
    approval_count: 0,
    token_count: 0,
  };
}

function currentTaskIsProcessing() {
  if (!bridgeState.taskRequest || bridgeState.taskResponseFailed) return false;
  return bridgeState.taskMode !== 'no_tool_chat' || !bridgeState.noToolCompleted;
}

function runEventPage(url) {
  const afterSequence = Math.max(0, Number(url.searchParams.get('after_sequence') || '0'));
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  const events = currentTaskEvents().filter((event) => event.sequence > afterSequence).slice(0, limit);
  return {
    run_id: RUN_ID,
    after_sequence: afterSequence,
    limit,
    next_after_sequence: events.length ? events[events.length - 1].sequence : afterSequence,
    has_more: false,
    events,
  };
}

function publicState() {
  return {
    aliasRegressionEnabled: bridgeState.aliasRegressionEnabled,
    approvalStatus: bridgeState.approvalStatus,
    readinessMode: bridgeState.readinessMode,
    approveCalls: bridgeState.approveCalls,
    approvePayloads: bridgeState.approvePayloads,
    legacyMessagePayloads: bridgeState.legacyMessagePayloads,
    legacyRunnableCatalogHits: bridgeState.legacyRunnableCatalogHits,
    internalRecoveryFailed: bridgeState.internalRecoveryFailed,
    messageSyncFailures: bridgeState.messageSyncFailures,
    messagesRequested: bridgeState.messagesRequested,
    noToolCompleted: bridgeState.noToolCompleted,
    currentSessionId: bridgeState.currentSessionId,
    rejectCalls: bridgeState.rejectCalls,
    requestLog: bridgeState.requestLog,
    runnableCatalogHits: bridgeState.runnableCatalogHits,
    taskEventsRequested: bridgeState.taskEventsRequested,
    taskEventAfterSequences: bridgeState.taskEventAfterSequences,
    timelineRequests: bridgeState.timelineRequests,
    timelineResponses: bridgeState.timelineResponses,
    taskRequest: bridgeState.taskRequest,
    taskMode: bridgeState.taskMode,
    taskResponseFailed: bridgeState.taskResponseFailed,
    taskResponseSent: bridgeState.taskResponseSent,
    sessionClearCalls: bridgeState.sessionClearCalls,
    sessionLoadCalls: bridgeState.sessionLoadCalls,
    sessionLoadPayloads: bridgeState.sessionLoadPayloads,
    legacyCanonicalVisible: bridgeState.legacyCanonicalVisible,
    legacyResponseSent: bridgeState.legacyResponseSent,
    staleTaskListResponses: bridgeState.staleTaskListResponses,
    staleTaskListResponsesCompleted: bridgeState.staleTaskListResponsesCompleted,
  };
}

function assertPublicTaskContract(action) {
  const { taskRequest } = bridgeState;
  if (!taskRequest) throw new Error('/yachiyo/tasks was not called');
  if (bridgeState.legacyMessagePayloads.length !== 0) {
    throw new Error(`Chat public task fell back to /ui/chat/messages: ${JSON.stringify(bridgeState.legacyMessagePayloads)}`);
  }
  if (taskRequest.prompt !== PROMPT) {
    throw new Error(`public task prompt mismatch: ${JSON.stringify(taskRequest.prompt)}`);
  }
  if (taskRequest.agent_id !== AGENT_ID) {
    throw new Error(`public task agent_id mismatch: ${JSON.stringify(taskRequest.agent_id)}`);
  }
  if (taskRequest.conversation_id !== SESSION_ID) {
    throw new Error(`public task conversation_id mismatch: ${JSON.stringify(taskRequest.conversation_id)}`);
  }
  if (taskRequest.metadata?.source !== 'chat') {
    throw new Error(`public task source metadata mismatch: ${JSON.stringify(taskRequest.metadata)}`);
  }
  if (taskRequest.metadata?.runnable_kind !== 'agent') {
    throw new Error(`public task runnable_kind metadata mismatch: ${JSON.stringify(taskRequest.metadata)}`);
  }
  if (!taskRequest.metadata?.client_message_id) {
    throw new Error(`public task missing client_message_id metadata: ${JSON.stringify(taskRequest.metadata)}`);
  }
  if (bridgeState.approvePayloads[0]?.approval_id !== APPROVAL_ID) {
    throw new Error(`public task approval payload mismatch: ${JSON.stringify(bridgeState.approvePayloads[0])}`);
  }
  if (action === 'approve') {
    if (bridgeState.approveCalls !== 1) {
      throw new Error(`expected one public task approval call, saw ${bridgeState.approveCalls}`);
    }
    if (bridgeState.approvalStatus !== 'approved') {
      throw new Error(`public task approval did not continue task: ${bridgeState.approvalStatus}`);
    }
    return;
  }
  if (bridgeState.rejectCalls !== 1) {
    throw new Error(`expected one public task rejection call, saw ${bridgeState.rejectCalls}`);
  }
  if (bridgeState.approvePayloads[0]?.action !== 'reject') {
    throw new Error(`public task rejection payload mismatch: ${JSON.stringify(bridgeState.approvePayloads[0])}`);
  }
  if (bridgeState.approvalStatus !== 'rejected') {
    throw new Error(`public task rejection did not stop task: ${bridgeState.approvalStatus}`);
  }
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
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
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
      if (url.pathname !== '/__smoke/state') {
        bridgeState.requestLog.push(`${request.method} ${url.pathname}`);
        bridgeState.requestLog = bridgeState.requestLog.slice(-80);
      }
      if (request.method === 'GET' && url.pathname === '/__smoke/state') {
        sendJson(response, 200, publicState());
        return;
      }
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
      if (request.method === 'GET' && url.pathname === '/yachiyo/readiness') {
        const desktopMissingPermissions = bridgeState.readinessMode === 'mixed_permission'
          ? ['chrome_cdp', 'accessibility']
          : ['chrome_cdp'];
        sendJson(response, 200, {
          ready: true,
          status: 'ready',
          capabilities: {
            desktop_execution: {
              missing_permissions: desktopMissingPermissions,
              degraded_tools: ['browser.open_url'],
              unavailable_tools: ['browser.current_page', 'browser.extract_text'],
            },
            browser_control: {
              missing_permissions: ['chrome_cdp'],
            },
            desktop_provider_ready: true,
            sandbox_provider: {
              provider_id: 'local-desktop-smoke',
              provider_kind: 'local_desktop',
              available: true,
              adapter_ready: true,
              health: { checked: true, ok: true, status: 'ready' },
              desktop_backend_ready_for_public_release: true,
              keyboard_mouse_capture_supported: true,
              supported_tools: ['screen.capture', 'desktop.active_window', 'app.open'],
            },
          },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, sessionsPayload());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        bridgeState.messagesRequested += 1;
        if (
          bridgeState.taskMode === 'public_failure_then_legacy_timeout_late_failure'
          && bridgeState.taskRequest
          && !bridgeState.taskResponseSent
        ) {
          await new Promise((resolve) => setTimeout(resolve, 400));
        }
        if (bridgeState.taskMode === 'accepted_sync_failure' && bridgeState.taskResponseSent) {
          bridgeState.messageSyncFailures += 1;
          sendJson(response, 503, { ok: false, error: 'forced accepted-message sync failure' });
          return;
        }
        sendJson(response, 200, messagesPayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/session/clear') {
        bridgeState.sessionClearCalls += 1;
        bridgeState.currentSessionId = NEW_SESSION_ID;
        sendJson(response, 200, { ok: true, session_id: NEW_SESSION_ID });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/runnables') {
        bridgeState.runnableCatalogHits += 1;
        sendJson(response, 200, { agents: [publicAgent], workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        bridgeState.legacyRunnableCatalogHits += 1;
        sendJson(response, 200, {
          runnables: [{
            id: AGENT_ID,
            name: AGENT_NAME,
            nickname: AGENT_NAME,
            kind: 'agent',
            enabled: true,
            output_contract: 'report',
          }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/tasks') {
        if (
          bridgeState.taskRequest
          && bridgeState.approvalStatus !== 'pending'
          && bridgeState.staleTaskListResponses === 0
        ) {
          bridgeState.staleTaskListResponses += 1;
          await new Promise((resolve) => setTimeout(resolve, 120));
          bridgeState.staleTaskListResponsesCompleted += 1;
          sendJson(response, 200, { tasks: [stalePendingTaskSnapshot()] });
          return;
        }
        sendJson(response, 200, {
          tasks: bridgeState.taskRequest
            ? [publicTaskSnapshot(), ...(bridgeState.aliasRegressionEnabled ? [aliasTaskSnapshot()] : [])]
            : [],
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/enable-alias-regression') {
        bridgeState.aliasRegressionEnabled = true;
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/fail-alias-recovery') {
        bridgeState.aliasTaskStatus = 'failed';
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/complete-no-tool') {
        bridgeState.noToolCompleted = true;
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/fail-internal-recovery') {
        bridgeState.internalRecoveryFailed = true;
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/__smoke/complete-internal-recovery-task') {
        bridgeState.internalRecoveryCompleted = true;
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/yachiyo/tasks') {
        bridgeState.taskRequest = await readRequestJson(request);
        await new Promise((resolve) => setTimeout(
          resolve,
          bridgeState.taskMode === 'public_failure_then_legacy_timeout_late_failure'
            ? 1800
            : TASK_RESPONSE_DELAY_MS,
        ));
        bridgeState.taskResponseSent = true;
        if (
          bridgeState.taskMode === 'public_failure'
          || bridgeState.taskMode === 'public_failure_then_legacy_response_lost'
          || bridgeState.taskMode === 'public_failure_then_legacy_timeout_late_failure'
          || bridgeState.taskMode === 'public_failure_then_post_commit_ok_false'
          || bridgeState.taskMode === 'public_failure_then_uncertain_retry_rejected'
          || bridgeState.taskMode === 'public_failure_then_ordered_second_message'
          || bridgeState.taskMode === 'public_failure_then_same_client_id_sessions'
          || bridgeState.taskMode === 'public_failure_then_deferred_route'
        ) {
          bridgeState.taskResponseFailed = true;
          sendJson(response, 503, { ok: false, error: 'forced public task start failure' });
          return;
        }
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}`) {
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${RUN_ID}`) {
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}/timeline`) {
        bridgeState.timelineRequests += 1;
        if (bridgeState.taskMode === 'polling_identity') {
          await new Promise((resolve) => setTimeout(resolve, 900));
        }
        bridgeState.timelineResponses += 1;
        sendJson(response, 200, runTimelineSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${RUN_ID}/timeline`) {
        bridgeState.timelineRequests += 1;
        if (bridgeState.taskMode === 'polling_identity') {
          await new Promise((resolve) => setTimeout(resolve, 900));
        }
        bridgeState.timelineResponses += 1;
        sendJson(response, 200, runTimelineSnapshot());
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/tasks/${TASK_ID}/events`) {
        bridgeState.taskEventsRequested += 1;
        bridgeState.taskEventAfterSequences.push(Math.max(0, Number(url.searchParams.get('after_sequence') || '0')));
        sendJson(response, 200, runEventPage(url));
        return;
      }
      if (
        request.method === 'POST'
        && (
          url.pathname === `/yachiyo/tasks/${TASK_ID}/approve`
          || url.pathname === `/yachiyo/tasks/${TASK_ID}/approvals/${APPROVAL_ID}/approve`
        )
      ) {
        const body = await readRequestJson(request);
        bridgeState.approveCalls += 1;
        bridgeState.approvePayloads.push(body);
        bridgeState.approvalStatus = 'approved';
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (
        request.method === 'POST'
        && (
          url.pathname === `/yachiyo/tasks/${TASK_ID}/reject`
          || url.pathname === `/yachiyo/tasks/${TASK_ID}/approvals/${APPROVAL_ID}/reject`
        )
      ) {
        const body = await readRequestJson(request);
        bridgeState.rejectCalls += 1;
        bridgeState.approvePayloads.push({ ...body, action: 'reject' });
        bridgeState.approvalStatus = 'rejected';
        sendJson(response, 200, publicTaskSnapshot());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages') {
        const body = await readRequestJson(request);
        bridgeState.legacyMessagePayloads.push(body);
        if (bridgeState.taskMode === 'public_failure_then_legacy_timeout_late_failure') {
          await new Promise((resolve) => setTimeout(resolve, 900));
          bridgeState.legacyCanonicalVisible = true;
          bridgeState.legacyResponseSent = true;
          sendJson(response, 200, {
            ok: false,
            committed: true,
            delivery_state: 'accepted_uncertain',
            client_message_id: body.client_message_id,
            error: 'late failed projection',
          });
          return;
        }
        if (bridgeState.taskMode === 'public_failure_then_same_client_id_sessions') {
          bridgeState.legacyResponseSent = true;
          if (
            bridgeState.currentSessionId === NEW_SESSION_ID
            && bridgeState.legacyMessagePayloads.length > 2
          ) {
            bridgeState.legacyCanonicalVisible = true;
            sendJson(response, 200, {
              ok: true,
              committed: true,
              delivery_state: 'accepted',
              client_message_id: body.client_message_id,
            });
            return;
          }
          sendJson(response, 200, {
            ok: false,
            committed: true,
            delivery_state: 'accepted_uncertain',
            client_message_id: body.client_message_id,
            error: 'session-scoped projection delayed',
          });
          return;
        }
        if (bridgeState.taskMode === 'public_failure_then_ordered_second_message') {
          bridgeState.legacyResponseSent = true;
          if (bridgeState.legacyMessagePayloads.length === 2) {
            bridgeState.legacyCanonicalVisible = true;
            sendJson(response, 200, {
              ok: true,
              committed: true,
              delivery_state: 'accepted',
              client_message_id: body.client_message_id,
            });
            return;
          }
          if (bridgeState.legacyMessagePayloads.length > 2) {
            sendJson(response, 200, {
              ok: false,
              committed: true,
              delivery_state: 'accepted_uncertain',
              client_message_id: body.client_message_id,
              error: 'third message projection delayed',
            });
            return;
          }
          sendJson(response, 200, {
            ok: false,
            committed: true,
            delivery_state: 'accepted_uncertain',
            client_message_id: body.client_message_id,
            error: 'first message projection delayed',
          });
          return;
        }
        if (bridgeState.taskMode === 'public_failure_then_uncertain_retry_rejected') {
          bridgeState.legacyResponseSent = true;
          if (bridgeState.legacyMessagePayloads.length > 1) {
            sendJson(response, 200, {
              ok: false,
              committed: false,
              delivery_state: 'not_committed',
              client_message_id: body.client_message_id,
              error: 'forced retry rejection',
            });
            return;
          }
          sendJson(response, 200, {
            ok: false,
            committed: true,
            delivery_state: 'accepted_uncertain',
            client_message_id: body.client_message_id,
            error: 'forced initial uncertain delivery',
          });
          return;
        }
        if (bridgeState.taskMode === 'public_failure_then_legacy_response_lost') {
          sendJson(response, 504, { ok: false, error: 'forced legacy response timeout after acceptance' });
          return;
        }
        if (bridgeState.taskMode === 'public_failure_then_post_commit_ok_false') {
          bridgeState.legacyResponseSent = true;
          if (bridgeState.legacyMessagePayloads.length > 1) {
            bridgeState.legacyCanonicalVisible = true;
            sendJson(response, 200, {
              ok: true,
              committed: true,
              delivery_state: 'accepted',
              client_message_id: body.client_message_id,
            });
            return;
          }
          sendJson(response, 200, {
            ok: false,
            committed: true,
            delivery_state: 'accepted_uncertain',
            client_message_id: body.client_message_id,
            error: 'response projection is still converging',
          });
          return;
        }
        if (bridgeState.taskMode === 'public_failure_then_deferred_route') {
          await new Promise((resolve) => setTimeout(resolve, 700));
        }
        bridgeState.legacyResponseSent = true;
        sendJson(response, 200, {
          ok: true,
          committed: true,
          delivery_state: 'accepted',
          client_message_id: body.client_message_id,
          task_id: 'legacy-chat-public-task-fallback',
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/sessions/load') {
        const body = await readRequestJson(request);
        bridgeState.sessionLoadCalls += 1;
        bridgeState.sessionLoadPayloads.push(body);
        bridgeState.currentSessionId = String(body.session_id || bridgeState.currentSessionId);
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

function runElectronSmoke(devUrl, bridgeUrl, action, expectReadinessNotice = false, scenario = 'normal') {
  const script = String.raw`
const { app, BrowserWindow } = require('electron');
const devUrl = process.env.OHA_YACHIYO_SMOKE_DEV_URL;
const bridgeUrl = process.env.OHA_YACHIYO_SMOKE_BRIDGE_URL;
const approvalAction = process.env.OHA_YACHIYO_SMOKE_APPROVAL_ACTION === 'reject' ? 'reject' : 'approve';
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
          debug = await win.webContents.executeJavaScript(
            "(async () => JSON.stringify({" +
              "hash: window.location.hash," +
              "card: document.querySelector('[data-testid=\"yachiyo-agent-task-card\"]')?.outerHTML || ''," +
              "studio: document.querySelector('[data-testid=\"yachiyo-agent-task-open-studio\"]')?.outerHTML || ''," +
              "messages: Array.from(document.querySelectorAll('.message')).map((node) => node.textContent).slice(-4)," +
              "smokeState: await fetch(" + JSON.stringify(bridgeUrl + '/__smoke/state') + ").then((response) => response.json()).catch((error) => ({ error: String(error) }))," +
              "bodyText: document.body.textContent.slice(-1800)" +
            "}))()",
            true
          );
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '&chatRequestTimeoutMs=250#/chat');
  await win.webContents.executeJavaScript('window.__ohaSmoke = ' + JSON.stringify({
    agentId: process.env.OHA_YACHIYO_SMOKE_AGENT_ID,
    approvalId: process.env.OHA_YACHIYO_SMOKE_APPROVAL_ID,
    approvalAction: process.env.OHA_YACHIYO_SMOKE_APPROVAL_ACTION,
    bridgeUrl,
    composerText: process.env.OHA_YACHIYO_SMOKE_COMPOSER_TEXT,
    expectReadinessNotice: process.env.OHA_YACHIYO_SMOKE_EXPECT_READINESS_NOTICE === 'true',
    prompt: process.env.OHA_YACHIYO_SMOKE_PROMPT,
    scenario: process.env.OHA_YACHIYO_SMOKE_SCENARIO || 'normal',
    runId: process.env.OHA_YACHIYO_SMOKE_RUN_ID,
    taskId: process.env.OHA_YACHIYO_SMOKE_TASK_ID,
    taskTitle: process.env.OHA_YACHIYO_SMOKE_TASK_TITLE,
  }), true);
  await win.webContents.executeJavaScript(
    "window.__ohaBridgeTimeoutSeen = false;" +
      "new MutationObserver(() => {" +
        "if ((document.body?.textContent || '').includes('本地 Bridge 请求超时')) window.__ohaBridgeTimeoutSeen = true;" +
      "}).observe(document.body, { childList: true, subtree: true, characterData: true });",
    true,
  );
  console.log('[electron-smoke] chat loaded');
  await waitFor(win, () => Boolean(document.querySelector('[data-testid="chat-composer-input"]')), 'Chat composer');
  await waitFor(win, () => {
    const empty = document.querySelector('.empty-state');
    return Boolean(empty?.textContent.includes('发送消息开始对话'))
      && !document.querySelector('.chat-loading-state');
  }, 'initial empty Chat session');
  await waitFor(win, async () => {
    const smoke = window.__ohaSmoke || {};
    const response = await fetch(smoke.bridgeUrl + '/__smoke/state');
    const state = await response.json();
    return state.requestLog.includes('GET /yachiyo/readiness');
  }, 'CDP-only readiness response');
  if ((await win.webContents.executeJavaScript('Boolean((window.__ohaSmoke || {}).expectReadinessNotice)', true))) {
    await waitFor(win, () => {
      const notice = document.querySelector('.chat-toast')?.textContent || '';
      return notice.includes('桌面执行权限未就绪') && notice.includes('辅助功能权限');
    }, 'mixed desktop permission readiness notice');
  } else {
    await new Promise((resolve) => setTimeout(resolve, 200));
    const readinessNotice = await win.webContents.executeJavaScript(
      "document.querySelector('.chat-toast')?.textContent || ''",
      true,
    );
    if (readinessNotice) {
      throw new Error('CDP-only readiness must not create a global Chat notice: ' + readinessNotice);
    }
  }
  await win.webContents.executeJavaScript(
    "const input = document.querySelector('[data-testid=\"chat-composer-input\"]');" +
      "const send = document.querySelector('[data-testid=\"chat-composer-send\"]');" +
      "const smoke = window.__ohaSmoke || {};" +
      "if (!input || !send) throw new Error('missing Chat composer controls');" +
      "if (smoke.scenario === 'same_client_id_sessions') {" +
        "Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => " + ${JSON.stringify(JSON.stringify(SHARED_SESSION_CLIENT_MESSAGE_ID))} + " });" +
      "}" +
      "const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;" +
      "setter.call(input, smoke.composerText);" +
      "input.dispatchEvent(new Event('input', { bubbles: true }));" +
      "input.dispatchEvent(new Event('change', { bubbles: true }));" +
      "input.focus();" +
      "send.click();",
    true
  );
  const scenario = await win.webContents.executeJavaScript('(window.__ohaSmoke || {}).scenario', true);
  if (scenario === 'unanchored_submission') {
    const expectedComposer = await win.webContents.executeJavaScript('(window.__ohaSmoke || {}).composerText', true);
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return Boolean(state.taskRequest)
        || document.body.textContent.includes('正在准备会话');
    }, 'unanchored submission decision');
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return { state, input: document.querySelector('[data-testid=\"chat-composer-input\"]')?.value || '' };" +
      "})()",
      true
    );
    if (result.state.taskRequest || result.state.legacyMessagePayloads.length || result.input !== expectedComposer) {
      throw new Error('unanchored submission left the composer or reached a send route: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] unanchored submission stays in composer');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  await waitFor(win, async () => {
    const smoke = window.__ohaSmoke || {};
    const response = await fetch(smoke.bridgeUrl + '/__smoke/state');
    const state = await response.json();
    return Boolean(state.taskRequest)
      && state.taskResponseSent === false
      && state.legacyMessagePayloads.length === 0;
  }, 'pending public /yachiyo/tasks request');
  const optimisticUserMessages = await win.webContents.executeJavaScript(
    "Array.from(document.querySelectorAll('.message.user')).map((node) => node.textContent || '')",
    true
  );
  if (
    optimisticUserMessages.length !== 1
    || !optimisticUserMessages[0].includes((await win.webContents.executeJavaScript('(window.__ohaSmoke || {}).prompt', true)))
  ) {
    throw new Error(
      'user message was not rendered before /yachiyo/tasks responded: '
      + JSON.stringify(optimisticUserMessages)
    );
  }
  console.log('[electron-smoke] user message rendered before task acceptance');
  const optimisticAssistantLoading = await win.webContents.executeJavaScript(
    "(() => {" +
      "const message = document.querySelector('[data-message-id=\"local:pending-assistant-reply\"]');" +
      "const dots = Array.from(message?.querySelectorAll('.loading-dot') || []);" +
      "return {" +
        "messageCount: document.querySelectorAll('[data-message-id=\"local:pending-assistant-reply\"]')?.length || 0," +
        "dotCount: dots.length," +
        "dotsVisible: dots.every((dot) => dot.getClientRects().length > 0 && dot.getBoundingClientRect().width > 0)," +
        "hasTaskCard: Boolean(message?.querySelector('[data-testid=\"yachiyo-agent-task-card\"]'))" +
      "};" +
    "})()",
    true,
  );
  if (
    optimisticAssistantLoading.messageCount !== 1
    || optimisticAssistantLoading.dotCount !== 3
    || !optimisticAssistantLoading.dotsVisible
    || optimisticAssistantLoading.hasTaskCard
  ) {
    throw new Error(
      'assistant loading was not rendered before task acceptance: '
      + JSON.stringify(optimisticAssistantLoading)
    );
  }
  console.log('[electron-smoke] assistant loading rendered before task acceptance');
  if (scenario === 'no_tool_chat') {
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      const message = document.querySelector('[data-message-id="chat-public-task-assistant-message"]');
      const dots = Array.from(message?.querySelectorAll('.loading-dot') || []);
      return state.taskResponseSent === true
        && dots.length === 3
        && dots.every((dot) => dot.getClientRects().length > 0 && dot.getBoundingClientRect().width > 0)
        && !document.querySelector('[data-message-id="local:pending-assistant-reply"]')
        && !message?.querySelector('[data-testid="yachiyo-agent-task-card"]')
        && !message?.querySelector('[data-testid="chat-agent-run-progress-card"]')
        && !message?.querySelector('[data-testid="yachiyo-agent-task-runtime-details"]')
        && !message?.querySelector('[data-testid="chat-message-activity-list"]');
    }, 'no-tool reply shows three loading dots without execution UI');
    await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/complete-no-tool', { method: 'POST' })",
      true,
    );
    await waitFor(win, () => {
      const message = document.querySelector('[data-message-id="chat-public-task-assistant-message"]');
      return Boolean(message?.textContent.includes('早上好，很高兴见到你。'))
        && message?.querySelectorAll('.loading-dot').length === 0
        && !message?.querySelector('[data-testid="yachiyo-agent-task-card"]')
        && !message?.querySelector('[data-testid="chat-agent-run-progress-card"]')
        && !message?.querySelector('[data-testid="yachiyo-agent-task-runtime-details"]')
        && !message?.querySelector('[data-testid="chat-message-activity-list"]');
    }, 'completed no-tool reply stays free of execution UI');
    console.log('[electron-smoke] no-tool reply uses compact loading and plain completion');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'internal_recovery_chat') {
    await waitFor(win, () => {
      const message = document.querySelector('[data-message-id="chat-public-task-assistant-message"]');
      const card = message?.querySelector('[data-testid="yachiyo-agent-task-card"]');
      return card?.getAttribute('data-task-status') === 'running'
        && card.textContent.includes('正在处理')
        && Boolean(card.querySelector('[data-testid="yachiyo-agent-task-cancel"]'))
        && !card.querySelector('[data-testid="yachiyo-agent-task-canonical-recovery"]')
        && !card.querySelector('[data-testid="yachiyo-agent-task-recovery-actions"]')
        && !card.textContent.includes('Retry browser title observation')
        && !card.textContent.includes('Retry Apple Music with resolved title');
    }, 'running internal recovery stays hidden in consumer Chat');
    await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/fail-internal-recovery', { method: 'POST' })",
      true,
    );
    await waitFor(win, () => {
      const message = document.querySelector('[data-message-id="chat-public-task-assistant-message"]');
      const card = message?.querySelector('[data-testid="yachiyo-agent-task-card"]');
      const recoveryActions = card?.querySelectorAll('[data-testid="yachiyo-agent-task-run-recovery-action"]') || [];
      const messageRetries = message?.querySelectorAll('[data-testid="chat-message-retry"]') || [];
      const runnableRetries = message?.querySelectorAll(
        '[data-testid="chat-message-retry"], [data-testid="yachiyo-agent-task-run-recovery-action"]',
      ) || [];
      return card?.getAttribute('data-task-status') === 'failed'
        && message?.classList.contains('error')
        && recoveryActions.length === 1
        && messageRetries.length === 0
        && runnableRetries.length === 1
        && recoveryActions[0]?.textContent.includes('重试')
        && !recoveryActions[0]?.textContent.includes('Retry browser title observation')
        && !recoveryActions[0]?.textContent.includes('Retry Apple Music with resolved title');
    }, 'failed task keeps at most one consumer-friendly retry');
    console.log('[electron-smoke] running observation and replan recovery stays internal');
    console.log('[electron-smoke] failed message and task share one consumer-friendly retry');
    await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/complete-internal-recovery-task', { method: 'POST' })",
      true,
    );
    await waitFor(win, () => {
      const message = document.querySelector('[data-message-id="chat-public-task-assistant-message"]');
      return message?.classList.contains('error')
        && !message.querySelector('[data-testid="yachiyo-agent-task-run-recovery-action"]')
        && Boolean(message.querySelector('[data-testid="chat-message-retry"]'));
    }, 'completed stale task recovery leaves failed message retry available');
    console.log('[electron-smoke] completed stale task recovery does not hide message retry');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'late_failed_reconciliation') {
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.taskResponseFailed === true && state.legacyMessagePayloads.length === 1;
    }, 'legacy request entered late-failure window');
    await waitFor(win, () => document.body.textContent.includes('投递状态待确认'), 'late delivery marked uncertain');
    win.hide();
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      const failed = document.querySelector('[data-message-id="chat-late-failure-assistant-message"]');
      return state.legacyCanonicalVisible === true
        && state.messagesRequested >= 3
        && failed?.classList.contains('error');
    }, 'hidden Chat reconciles late canonical failure', 4500);
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return {" +
          "state," +
          "timeoutSeen: Boolean(window.__ohaBridgeTimeoutSeen)," +
          "localCount: document.querySelectorAll('[data-message-id^=\"local:\"]').length," +
          "failedCount: document.querySelectorAll('[data-message-id=\"chat-late-failure-assistant-message\"]').length" +
        "};" +
      "})()",
      true
    );
    if (
      result.timeoutSeen
      || result.localCount !== 0
      || result.failedCount !== 1
      || result.state.legacyMessagePayloads.length !== 1
    ) {
      throw new Error('late canonical reconciliation was not bounded and idempotent: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] hidden Chat reconciles one late failed canonical message without raw timeout');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'same_client_id_sessions') {
    await waitFor(win, () => document.body.textContent.includes('投递状态待确认'), 'session A uncertain delivery');
    await win.webContents.executeJavaScript(
      "Array.from(document.querySelectorAll('.chat-item')).find((node) => (node.textContent || '').includes('New Chat smoke'))?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.currentSessionId === ${JSON.stringify(NEW_SESSION_ID)}
        && !document.querySelector('[data-message-id^="local:"]');
    }, 'switch to empty session B before same-id send');
    await win.webContents.executeJavaScript(
      "(() => {" +
        "const input = document.querySelector('[data-testid=\"chat-composer-input\"]');" +
        "const send = document.querySelector('[data-testid=\"chat-composer-send\"]');" +
        "const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;" +
        "setter.call(input, " + ${JSON.stringify(JSON.stringify(SAME_ID_SESSION_B_TEXT))} + ");" +
        "input.dispatchEvent(new Event('input', { bubbles: true }));" +
        "input.dispatchEvent(new Event('change', { bubbles: true }));" +
        "send.click();" +
      "})()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      const local = document.querySelector('[data-message-id^="local:"]');
      const retry = document.querySelector('[data-testid="chat-message-retry"]');
      return state.legacyMessagePayloads.length === 2
        && local?.getAttribute('data-message-id') === 'local:' + ${JSON.stringify(SHARED_SESSION_CLIENT_MESSAGE_ID)}
        && (local?.textContent || '').includes(${JSON.stringify(SAME_ID_SESSION_B_TEXT)})
        && retry?.disabled === false;
    }, 'session B uncertain delivery with shared client id');
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-message-retry\"]')?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyMessagePayloads.length === 3
        && state.legacyCanonicalVisible === true
        && document.querySelector('[data-message-id="chat-same-id-session-b-canonical-message"]')
        && !document.querySelector('[data-message-id^="local:"]');
    }, 'session B canonical cleanup stays session scoped');
    await win.webContents.executeJavaScript(
      "Array.from(document.querySelectorAll('.chat-item')).find((node) => (node.textContent || '').includes('Chat public task smoke'))?.click()",
      true
    );
    await waitFor(win, () => {
      const local = document.querySelector('[data-message-id^="local:"]');
      const retry = document.querySelector('[data-testid="chat-message-retry"]');
      return local?.getAttribute('data-message-id') === 'local:' + ${JSON.stringify(SHARED_SESSION_CLIENT_MESSAGE_ID)}
        && (local?.textContent || '').includes(${JSON.stringify(PROMPT)})
        && retry?.disabled === false;
    }, 'session A same-id outbox survives session B canonical cleanup');
    const sameIdState = await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/state').then((response) => response.json())",
      true
    );
    if (
      sameIdState.legacyMessagePayloads.length !== 3
      || sameIdState.legacyMessagePayloads.some((payload) => payload.client_message_id !== ${JSON.stringify(SHARED_SESSION_CLIENT_MESSAGE_ID)})
    ) {
      throw new Error('same-id session isolation used inconsistent client ids: ' + JSON.stringify(sameIdState));
    }
    console.log('[electron-smoke] same client id remains isolated across session outboxes and canonical cleanup');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'optimistic_ordering') {
    await waitFor(win, () => document.body.textContent.includes('投递状态待确认'), 'first message uncertain before second send');
    await win.webContents.executeJavaScript(
      "(() => {" +
        "const input = document.querySelector('[data-testid=\"chat-composer-input\"]');" +
        "const send = document.querySelector('[data-testid=\"chat-composer-send\"]');" +
        "const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;" +
        "setter.call(input, " + ${JSON.stringify(JSON.stringify(SECOND_MESSAGE_TEXT))} + ");" +
        "input.dispatchEvent(new Event('input', { bubbles: true }));" +
        "input.dispatchEvent(new Event('change', { bubbles: true }));" +
        "send.click();" +
      "})()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyMessagePayloads.length === 2
        && state.legacyCanonicalVisible === true
        && document.body.textContent.includes(${JSON.stringify(SECOND_ASSISTANT_TEXT)})
        && Boolean(document.querySelector('[data-message-id^="local:"]'));
    }, 'second message canonical while first remains optimistic');
    const orderedTexts = await win.webContents.executeJavaScript(
      "Array.from(document.querySelectorAll('.message')).map((node) => node.textContent || '')",
      true
    );
    const firstIndex = orderedTexts.findIndex((text) => text.includes(${JSON.stringify(PROMPT)}));
    const secondIndex = orderedTexts.findIndex((text) => text.includes(${JSON.stringify(SECOND_MESSAGE_TEXT)}));
    const assistantIndex = orderedTexts.findIndex((text) => text.includes(${JSON.stringify(SECOND_ASSISTANT_TEXT)}));
    if (!(firstIndex >= 0 && firstIndex < secondIndex && secondIndex < assistantIndex)) {
      throw new Error('optimistic/canonical messages rendered out of submitted order: ' + JSON.stringify({ orderedTexts, firstIndex, secondIndex, assistantIndex }));
    }
    await win.webContents.executeJavaScript(
      "(() => {" +
        "const input = document.querySelector('[data-testid=\"chat-composer-input\"]');" +
        "const send = document.querySelector('[data-testid=\"chat-composer-send\"]');" +
        "const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;" +
        "setter.call(input, " + ${JSON.stringify(JSON.stringify(THIRD_MESSAGE_TEXT))} + ");" +
        "input.dispatchEvent(new Event('input', { bubbles: true }));" +
        "input.dispatchEvent(new Event('change', { bubbles: true }));" +
        "send.click();" +
      "})()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyMessagePayloads.length === 3
        && document.body.textContent.includes(${JSON.stringify(THIRD_MESSAGE_TEXT)})
        && document.querySelectorAll('[data-message-id^="local:"]').length === 2;
    }, 'third message remains optimistic beside delayed first message');
    const messagesAfterThirdSubmit = await win.webContents.executeJavaScript(
      "Array.from(document.querySelectorAll('.message')).map((node) => node.textContent || '')",
      true
    );
    const firstAfterThird = messagesAfterThirdSubmit.findIndex((text) => text.includes(${JSON.stringify(PROMPT)}));
    const secondAfterThird = messagesAfterThirdSubmit.findIndex((text) => text.includes(${JSON.stringify(SECOND_MESSAGE_TEXT)}));
    const assistantAfterThird = messagesAfterThirdSubmit.findIndex((text) => text.includes(${JSON.stringify(SECOND_ASSISTANT_TEXT)}));
    const thirdAfterThird = messagesAfterThirdSubmit.findIndex((text) => text.includes(${JSON.stringify(THIRD_MESSAGE_TEXT)}));
    if (!(firstAfterThird < secondAfterThird && secondAfterThird < assistantAfterThird && assistantAfterThird < thirdAfterThird)) {
      throw new Error('submitted sequence lost precedence over skewed canonical timestamps: ' + JSON.stringify({
        messagesAfterThirdSubmit,
        firstAfterThird,
        secondAfterThird,
        assistantAfterThird,
        thirdAfterThird,
      }));
    }
    console.log('[electron-smoke] optimistic A stays before canonical B and its reply');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'uncertain_retry_preserves_new_draft') {
    await waitFor(win, () => {
      const retry = document.querySelector('[data-testid="chat-message-retry"]');
      return document.body.textContent.includes('投递状态待确认')
        && retry?.getAttribute('aria-label') === '确认/重试投递'
        && retry.disabled === false;
    }, 'uncertain delivery before composing a newer draft');
    await win.webContents.executeJavaScript(
      "(() => {" +
        "const input = document.querySelector('[data-testid=\"chat-composer-input\"]');" +
        "const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;" +
        "setter.call(input, " + ${JSON.stringify(JSON.stringify(NEW_DRAFT_TEXT))} + ");" +
        "input.dispatchEvent(new Event('input', { bubbles: true }));" +
        "input.dispatchEvent(new Event('change', { bubbles: true }));" +
        "window.dispatchEvent(new CustomEvent('oha-chat-e2e-add-image', { detail: {" +
          "name: " + ${JSON.stringify(JSON.stringify(NEW_DRAFT_IMAGE_NAME))} + "," +
          "mime_type: 'image/svg+xml'," +
          "data_url: " + ${JSON.stringify(JSON.stringify(NEW_DRAFT_IMAGE_DATA_URL))} +
        "} }));" +
      "})()",
      true
    );
    await waitFor(win, () => {
      const input = document.querySelector('[data-testid="chat-composer-input"]');
      const attachment = document.querySelector('[data-testid="chat-composer-attachment-preview"]');
      return input?.value === ${JSON.stringify(NEW_DRAFT_TEXT)}
        && attachment?.getAttribute('data-attachment-name') === ${JSON.stringify(NEW_DRAFT_IMAGE_NAME)};
    }, 'newer composer draft and attachment');
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-message-retry\"]')?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyMessagePayloads.length === 2
        && document.body.textContent.includes('当前草稿已保留');
    }, 'explicit retry rejection preserves newer draft');
    const result = await win.webContents.executeJavaScript(
      "({" +
        "input: document.querySelector('[data-testid=\"chat-composer-input\"]')?.value || ''," +
        "attachmentNames: Array.from(document.querySelectorAll('[data-testid=\"chat-composer-attachment-preview\"]')).map((node) => node.getAttribute('data-attachment-name'))," +
        "localCount: document.querySelectorAll('[data-message-id^=\"local:\"]').length" +
      "})",
      true
    );
    if (
      result.input !== ${JSON.stringify(NEW_DRAFT_TEXT)}
      || result.attachmentNames.length !== 1
      || result.attachmentNames[0] !== ${JSON.stringify(NEW_DRAFT_IMAGE_NAME)}
      || result.localCount !== 0
    ) {
      throw new Error('explicit retry rejection overwrote the newer composer draft: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] rejected uncertain retry preserves newer text and attachment draft');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'outbox_switch_retry') {
    await waitFor(win, () => document.body.textContent.includes('投递状态待确认'), 'uncertain delivery before session switch');
    const initial = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return {" +
          "clientMessageId: state.legacyMessagePayloads[0]?.client_message_id || ''," +
          "localId: document.querySelector('[data-message-id^=\"local:\"]')?.getAttribute('data-message-id') || ''" +
        "};" +
      "})()",
      true
    );
    if (!initial.clientMessageId || initial.localId !== 'local:' + initial.clientMessageId) {
      throw new Error('uncertain outbox did not start with the delivery client id: ' + JSON.stringify(initial));
    }
    await win.webContents.executeJavaScript(
      "Array.from(document.querySelectorAll('.chat-item')).find((node) => (node.textContent || '').includes('New Chat smoke'))?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.currentSessionId === ${JSON.stringify(NEW_SESSION_ID)}
        && !document.querySelector('[data-message-id^="local:"]');
    }, 'uncertain outbox stays out of session B');
    await win.webContents.executeJavaScript(
      "Array.from(document.querySelectorAll('.chat-item')).find((node) => (node.textContent || '').includes('Chat public task smoke'))?.click()",
      true
    );
    await waitFor(win, () => {
      const local = document.querySelector('[data-message-id^="local:"]');
      const retry = document.querySelector('[data-testid="chat-message-retry"]');
      return Boolean(
        local
        && retry?.getAttribute('aria-label') === '确认/重试投递'
        && retry.disabled === false
      );
    }, 'uncertain outbox restored in session A');
    const restored = await win.webContents.executeJavaScript(
      "({" +
        "localId: document.querySelector('[data-message-id^=\"local:\"]')?.getAttribute('data-message-id') || ''," +
        "retryReady: document.querySelector('[data-testid=\"chat-message-retry\"]')?.disabled === false" +
      "})",
      true
    );
    if (restored.localId !== initial.localId || !restored.retryReady) {
      throw new Error('uncertain outbox changed identity after session round trip: ' + JSON.stringify({ initial, restored }));
    }
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-message-retry\"]')?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyMessagePayloads.length === 2
        && state.legacyCanonicalVisible === true
        && !document.querySelector('[data-message-id^="local:"]');
    }, 'restored uncertain outbox reconciles canonical message');
    const retryState = await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/state').then((response) => response.json())",
      true
    );
    if (
      retryState.legacyMessagePayloads[0]?.client_message_id !== initial.clientMessageId
      || retryState.legacyMessagePayloads[1]?.client_message_id !== initial.clientMessageId
    ) {
      throw new Error('session round-trip retry changed the delivery id: ' + JSON.stringify(retryState));
    }
    console.log('[electron-smoke] uncertain outbox survives session round trip and reuses its id');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'post_commit_ok_false') {
    await waitFor(win, () => document.body.textContent.includes('投递状态待确认'), 'post-commit uncertain delivery settled');
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "const local = document.querySelector('[data-message-id^=\"local:\"]');" +
        "return {" +
          "state," +
          "input: document.querySelector('[data-testid=\"chat-composer-input\"]')?.value || ''," +
          "localId: local?.getAttribute('data-message-id') || ''" +
        "};" +
      "})()",
      true
    );
    const requestClientMessageId = result.state.legacyMessagePayloads[0]?.client_message_id || '';
    if (
      !result.state.legacyResponseSent
      || result.state.legacyMessagePayloads.length !== 1
      || result.input
      || result.localId !== 'local:' + requestClientMessageId
    ) {
      throw new Error('post-commit ok:false rolled back or changed the optimistic delivery id: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] post-commit ok:false preserves the original optimistic delivery');
    await waitFor(win, () => {
      const retry = document.querySelector('[data-testid="chat-message-retry"]');
      return retry?.getAttribute('aria-label') === '确认/重试投递' && retry.disabled === false;
    }, 'uncertain optimistic delivery retry becomes available');
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-message-retry\"]').click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      const userMessages = Array.from(document.querySelectorAll('.message.user'));
      return state.legacyMessagePayloads.length === 2
        && state.legacyCanonicalVisible === true
        && !document.querySelector('[data-message-id^="local:"]')
        && userMessages.length === 1
        && userMessages[0]?.getAttribute('data-message-id') === 'chat-post-commit-canonical-user-message';
    }, 'uncertain delivery retry reconciles canonical message');
    const retryResult = await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/state').then((response) => response.json())",
      true
    );
    if (
      retryResult.legacyMessagePayloads[0]?.client_message_id
      !== retryResult.legacyMessagePayloads[1]?.client_message_id
    ) {
      throw new Error('uncertain delivery retry changed the idempotency key: ' + JSON.stringify(retryResult));
    }
    console.log('[electron-smoke] uncertain delivery retry reuses id and reconciles one canonical bubble');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'deferred_route_handoff') {
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyMessagePayloads.length === 1 && state.legacyResponseSent === false;
    }, 'legacy send blocks route handoff');
    await win.webContents.executeJavaScript(
      ${JSON.stringify(`window.location.hash = '#/chat?session_id=${encodeURIComponent(NEW_SESSION_ID)}'`)},
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.legacyResponseSent === true
        && state.sessionLoadCalls === 1
        && state.currentSessionId === ${JSON.stringify(NEW_SESSION_ID)};
    }, 'deferred route handoff replayed after legacy send');
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return { state, body: document.body.textContent };" +
      "})()",
      true
    );
    if (
      result.state.sessionLoadPayloads[0]?.session_id !== ${JSON.stringify(NEW_SESSION_ID)}
      || result.body.includes((await win.webContents.executeJavaScript('(window.__ohaSmoke || {}).prompt', true)))
    ) {
      throw new Error('deferred route handoff targeted or rendered the wrong conversation: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] deferred route handoff replays after legacy send');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'legacy_response_lost') {
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.taskResponseFailed === true && state.legacyMessagePayloads.length === 1;
    }, 'legacy request accepted before response loss');
    await waitFor(win, () => document.body.textContent.includes('投递状态待确认'), 'uncertain legacy delivery settled');
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return {" +
          "state," +
          "body: document.body.textContent," +
          "input: document.querySelector('[data-testid=\"chat-composer-input\"]')?.value || ''," +
          "localCount: document.querySelectorAll('[data-message-id^=\"local:\"]').length" +
        "};" +
      "})()",
      true
    );
    if (result.input || result.localCount !== 1 || !result.body.includes('投递状态待确认')) {
      throw new Error('uncertain legacy delivery lost idempotent optimistic state: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] response loss preserves original optimistic delivery');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'public_failure_after_new_session') {
    const expectedPrompt = await win.webContents.executeJavaScript('(window.__ohaSmoke || {}).prompt', true);
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-session-tab-create\"]')?.click()",
      true
    );
    await new Promise((resolve) => setTimeout(resolve, 250));
    const blockedState = await win.webContents.executeJavaScript(
      "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/state').then((response) => response.json())",
      true
    );
    if (
      blockedState.sessionClearCalls !== 0
      || blockedState.currentSessionId !== ${JSON.stringify(SESSION_ID)}
    ) {
      throw new Error('public pre-accept submission allowed a conversation mutation: ' + JSON.stringify(blockedState));
    }
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.taskResponseFailed === true
        && state.legacyMessagePayloads.length === 1
        && state.legacyResponseSent === true;
    }, 'public failure falls back in its original session');
    await waitFor(win, () => document.querySelector('[data-testid="chat-composer-input"]')?.readOnly === false, 'original submission settled');
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-session-tab-create\"]')?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.sessionClearCalls === 1 && state.currentSessionId === ${JSON.stringify(NEW_SESSION_ID)};
    }, 'new session after public submission settles');
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return {" +
          "state," +
          "input: document.querySelector('[data-testid=\"chat-composer-input\"]')?.value || ''," +
          "userMessages: Array.from(document.querySelectorAll('.message.user')).map((node) => node.textContent || '')" +
        "};" +
      "})()",
      true
    );
    if (result.state.legacyMessagePayloads.length !== 1) {
      throw new Error('public fallback did not stay single-delivery in its original session: ' + JSON.stringify(result));
    }
    if (result.input || result.userMessages.some((message) => message.includes(expectedPrompt))) {
      throw new Error('old submission leaked into the new session: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] public pre-accept blocks mutation, then new session opens after settlement');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'polling_identity_after_new_session') {
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.taskResponseSent === true && state.timelineRequests >= 1;
    }, 'run polling started for original session');
    await win.webContents.executeJavaScript(
      "document.querySelector('[data-testid=\"chat-session-tab-create\"]')?.click()",
      true
    );
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.sessionClearCalls === 1
        && state.currentSessionId === ${JSON.stringify(NEW_SESSION_ID)}
        && state.timelineResponses >= 1;
    }, 'old run polling response after new session');
    await new Promise((resolve) => setTimeout(resolve, 300));
    const result = await win.webContents.executeJavaScript(
      "({" +
        "body: document.body.textContent," +
        "footer: document.querySelector('.refined-status-line')?.textContent || ''," +
        "processing: Boolean(document.querySelector('.chat-input-wrapper.is-processing'))" +
      "})",
      true
    );
    if (
      result.processing
      || result.body.includes(${JSON.stringify(PROMPT)})
      || result.body.includes(${JSON.stringify(TASK_TITLE)})
      || result.footer.includes('审批')
      || result.footer.includes('Agent Run')
    ) {
      throw new Error('old run polling polluted the new conversation: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] run polling stays bound to its original conversation');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  if (scenario === 'accepted_sync_failure') {
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      const input = document.querySelector('[data-testid="chat-composer-input"]');
      const userMessages = Array.from(document.querySelectorAll('.message.user'))
        .filter((node) => (node.textContent || '').includes(smoke.prompt));
      return state.taskResponseSent === true
        && state.messageSyncFailures >= 1
        && state.legacyMessagePayloads.length === 0
        && userMessages.length === 1
        && input?.value === ''
        && document.body.textContent.includes('正在同步');
    }, 'accepted message survives initial sync failure');
    await waitFor(win, async () => {
      const smoke = window.__ohaSmoke || {};
      const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());
      return state.messagesRequested >= 3;
    }, 'background message reconciliation continues');
    const result = await win.webContents.executeJavaScript(
      "(async () => {" +
        "const smoke = window.__ohaSmoke || {};" +
        "const state = await fetch(smoke.bridgeUrl + '/__smoke/state').then((response) => response.json());" +
        "return {" +
          "state," +
          "input: document.querySelector('[data-testid=\"chat-composer-input\"]')?.value || ''," +
          "userMessageCount: Array.from(document.querySelectorAll('.message.user')).filter((node) => (node.textContent || '').includes(smoke.prompt)).length" +
        "};" +
      "})()",
      true
    );
    if (result.state.legacyMessagePayloads.length !== 0 || result.input || result.userMessageCount !== 1) {
      throw new Error('accepted message was lost, restored, or duplicated after sync failure: ' + JSON.stringify(result));
    }
    console.log('[electron-smoke] accepted message remains optimistic during sync retry');
    clearTimeout(watchdog);
    await win.close();
    app.quit();
    return;
  }
  await waitFor(win, () => {
    const smoke = window.__ohaSmoke || {};
    const cards = document.querySelectorAll('[data-testid="yachiyo-agent-task-card"]');
    const userMessages = Array.from(document.querySelectorAll('.message.user'))
      .filter((node) => (node.textContent || '').includes(smoke.prompt));
    const card = cards[0];
    const approval = document.querySelector('[data-testid="yachiyo-task-approval-card"]');
    const approve = document.querySelector('[data-testid="yachiyo-task-approval-approve"]');
    const reject = document.querySelector('[data-testid="yachiyo-task-approval-reject"]');
    const approvalStudio = document.querySelector('[data-testid="yachiyo-task-approval-open-studio"]');
    const details = document.querySelector('[data-testid="yachiyo-agent-task-runtime-details"]');
    const studio = document.querySelector('[data-testid="yachiyo-agent-task-open-studio"]');
    const activity = document.querySelector('[data-testid="chat-message-activity-list"]');
    return userMessages.length === 1
      && cards.length === 1
      && Boolean(card)
      && card.getAttribute('data-task-id') === smoke.taskId
      && card.getAttribute('data-run-id') === smoke.runId
      && card.getAttribute('data-task-status') === 'waiting_approval'
      && card.textContent.includes('需要你的确认')
      && approval?.getAttribute('data-approval-id') === smoke.approvalId
      && approval?.getAttribute('data-approval-tool') === 'workspace.write'
      && approve?.textContent.includes('批准')
      && reject?.textContent.includes('拒绝')
      && !approvalStudio
      && !details
      && !studio
      && !activity;
  }, 'consumer Chat keeps approval actions without technical execution UI');
  await new Promise((resolve) => setTimeout(resolve, 350));
  const compactReplayState = await win.webContents.executeJavaScript(
    "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/state').then((response) => response.json())",
    true
  );
  if (compactReplayState.taskEventsRequested !== 0) {
    throw new Error('consumer Chat fetched hidden task events: ' + JSON.stringify(compactReplayState));
  }
  await win.webContents.executeJavaScript(
    "(() => {" +
      "const smoke = window.__ohaSmoke || {};" +
      "const action = smoke.approvalAction === 'reject' ? 'reject' : 'approve';" +
      "const selector = action === 'reject' ? '[data-testid=\"yachiyo-task-approval-reject\"]' : '[data-testid=\"yachiyo-task-approval-approve\"]';" +
      "const button = document.querySelector(selector);" +
      "if (!button) throw new Error('missing public task approval ' + action + ' button');" +
      "button.click();" +
    "})();",
    true
  );
  await waitFor(win, async () => {
    const smoke = window.__ohaSmoke || {};
    const response = await fetch(smoke.bridgeUrl + '/__smoke/state');
    const state = await response.json();
    const action = smoke.approvalAction === 'reject' ? 'reject' : 'approve';
    return state.approvalStatus === (action === 'reject' ? 'rejected' : 'approved')
      && (action === 'reject' ? state.rejectCalls === 1 : state.approveCalls === 1)
      && state.approvePayloads[0]?.approval_id === smoke.approvalId;
  }, 'public task approval request');
  await waitFor(win, async () => {
    const smoke = window.__ohaSmoke || {};
    const response = await fetch(smoke.bridgeUrl + '/__smoke/state');
    const state = await response.json();
    return state.staleTaskListResponsesCompleted === 1;
  }, 'stale task list response completed');
  await waitFor(win, () => {
    const smoke = window.__ohaSmoke || {};
    const action = smoke.approvalAction === 'reject' ? 'reject' : 'approve';
    const card = document.querySelector('[data-testid="yachiyo-agent-task-card"]');
    const consumerFailure = document.querySelector('[data-testid="yachiyo-agent-task-consumer-failure"]');
    const approval = document.querySelector('[data-testid="yachiyo-task-approval-card"]');
    const approve = document.querySelector('[data-testid="yachiyo-task-approval-approve"]');
    const reject = document.querySelector('[data-testid="yachiyo-task-approval-reject"]');
    const details = document.querySelector('[data-testid="yachiyo-agent-task-runtime-details"]');
    const studio = document.querySelector('[data-testid="yachiyo-agent-task-open-studio"]');
    return (
      card?.getAttribute('data-task-id') === smoke.taskId
      && card?.getAttribute('data-run-id') === smoke.runId
      && (
        (action === 'approve'
          && card?.getAttribute('data-task-status') === 'running'
          && card.textContent.includes('正在处理'))
        || (action === 'reject'
          && card?.getAttribute('data-task-status') === 'cancelled'
          && Boolean(consumerFailure))
      )
      && !approval
      && !approve
      && !reject
      && !details
      && !studio
    );
  }, 'public task approval continued without technical history');
  await win.webContents.executeJavaScript(
    "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/enable-alias-regression', { method: 'POST' })",
    true
  );
  await waitFor(win, () => {
    const message = document.querySelector('[data-message-id="chat-public-task-alias-message"]');
    const card = document.querySelector('[data-message-id="chat-public-task-alias-message"] [data-testid="yachiyo-agent-task-card"]');
    return message?.textContent.includes('Shared alias task B completed.') && !card;
  }, 'completed tool-only alias stays hidden in consumer Chat');
  await win.webContents.executeJavaScript(
    "fetch((window.__ohaSmoke || {}).bridgeUrl + '/__smoke/fail-alias-recovery', { method: 'POST' })",
    true
  );
  await waitFor(win, () => {
    const message = document.querySelector('[data-message-id="chat-public-task-alias-message"]');
    const recoveryActions = message?.querySelectorAll('[data-testid="yachiyo-agent-task-run-recovery-action"]') || [];
    const taskCard = message?.querySelector('[data-testid="yachiyo-agent-task-card"]');
    const consumerFailure = message?.querySelector('[data-testid="yachiyo-agent-task-consumer-failure"]');
    const runtimeDetails = message?.querySelector('[data-testid="yachiyo-agent-task-runtime-details"]');
    const studio = message?.querySelector('[data-testid="yachiyo-agent-task-open-studio"]');
    const activity = message?.querySelector('[data-testid="chat-message-activity-list"]');
    return taskCard?.getAttribute('data-task-status') === 'failed'
      && Boolean(consumerFailure)
      && recoveryActions.length <= 1
      && (!recoveryActions.length || recoveryActions[0]?.textContent.includes('重试'))
      && !runtimeDetails
      && !studio
      && !activity;
  }, 'failed alias task exposes no more than one consumer-friendly retry');
  console.log('[electron-smoke] shared run alias preserves distinct task identity');
  console.log('[electron-smoke] consumer Chat hides technical execution UI');
  if (approvalAction === 'reject') {
    console.log('[electron-smoke] Chat public task approval rejected');
  } else {
    console.log('[electron-smoke] Chat public task approval approved');
  }
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-public-task-smoke-'));
  const mainPath = path.join(tempDir, 'main.cjs');
  fs.writeFileSync(mainPath, script, 'utf8');
  return new Promise((resolve, reject) => {
    const child = spawn(ELECTRON, [mainPath], {
      cwd: FRONTEND,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        ELECTRON_ENABLE_LOGGING: '1',
        OHA_YACHIYO_SMOKE_AGENT_ID: AGENT_ID,
        OHA_YACHIYO_SMOKE_APPROVAL_ID: APPROVAL_ID,
        OHA_YACHIYO_SMOKE_APPROVAL_ACTION: action,
        OHA_YACHIYO_SMOKE_COMPOSER_TEXT: COMPOSER_TEXT,
        OHA_YACHIYO_SMOKE_DEV_URL: devUrl,
        OHA_YACHIYO_SMOKE_BRIDGE_URL: bridgeUrl,
        OHA_YACHIYO_SMOKE_EXPECT_READINESS_NOTICE: expectReadinessNotice ? 'true' : 'false',
        OHA_YACHIYO_SMOKE_PROMPT: PROMPT,
        OHA_YACHIYO_SMOKE_SCENARIO: scenario,
        OHA_YACHIYO_SMOKE_RUN_ID: RUN_ID,
        OHA_YACHIYO_SMOKE_TASK_ID: TASK_ID,
        OHA_YACHIYO_SMOKE_TASK_TITLE: TASK_TITLE,
      },
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
    if (process.argv.includes('--late-failed-reconciliation-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_legacy_timeout_late_failure';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'late_failed_reconciliation');
      log('passed late failed reconciliation scenario');
      return;
    }
    if (process.argv.includes('--legacy-response-lost-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_legacy_response_lost';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'legacy_response_lost');
      log('passed legacy response-loss scenario');
      return;
    }
    if (process.argv.includes('--post-commit-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_post_commit_ok_false';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'post_commit_ok_false');
      log('passed post-commit scenario');
      return;
    }
    if (process.argv.includes('--outbox-switch-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_post_commit_ok_false';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'outbox_switch_retry');
      log('passed uncertain outbox session round-trip scenario');
      return;
    }
    if (process.argv.includes('--same-client-id-sessions-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_same_client_id_sessions';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'same_client_id_sessions');
      log('passed same-client-id session isolation scenario');
      return;
    }
    if (process.argv.includes('--draft-preservation-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_uncertain_retry_rejected';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'uncertain_retry_preserves_new_draft');
      log('passed uncertain retry draft-preservation scenario');
      return;
    }
    if (process.argv.includes('--ordering-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_ordered_second_message';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'optimistic_ordering');
      log('passed optimistic/canonical ordering scenario');
      return;
    }
    if (process.argv.includes('--public-preaccept-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'public_failure_after_new_session');
      log('passed public pre-accept conversation gate scenario');
      return;
    }
    if (process.argv.includes('--deferred-route-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'public_failure_then_deferred_route';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'deferred_route_handoff');
      log('passed deferred route scenario');
      return;
    }
    if (process.argv.includes('--no-tool-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'no_tool_chat';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'no_tool_chat');
      log('passed no-tool Chat rendering scenario');
      return;
    }
    if (process.argv.includes('--internal-recovery-only')) {
      resetBridgeState();
      bridgeState.taskMode = 'internal_recovery_chat';
      await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'internal_recovery_chat');
      log('passed internal recovery Chat suppression scenario');
      return;
    }
    if (process.argv.includes('--completed-recovery-only')) {
      await runElectronSmoke(devUrl, bridge.url, 'approve', false);
      assertPublicTaskContract('approve');
      log('passed completed-task recovery suppression scenario');
      return;
    }
    await runElectronSmoke(devUrl, bridge.url, 'approve', false);
    assertPublicTaskContract('approve');
    resetBridgeState();
    bridgeState.readinessMode = 'mixed_permission';
    await runElectronSmoke(devUrl, bridge.url, 'reject', true);
    assertPublicTaskContract('reject');
    resetBridgeState();
    bridgeState.taskMode = 'public_failure';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'public_failure_after_new_session');
    resetBridgeState();
    bridgeState.taskMode = 'polling_identity';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'polling_identity_after_new_session');
    resetBridgeState();
    bridgeState.taskMode = 'accepted_sync_failure';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'accepted_sync_failure');
    resetBridgeState();
    bridgeState.currentSessionId = '';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'unanchored_submission');
    resetBridgeState();
    bridgeState.taskMode = 'public_failure_then_legacy_response_lost';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'legacy_response_lost');
    resetBridgeState();
    bridgeState.taskMode = 'public_failure_then_post_commit_ok_false';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'post_commit_ok_false');
    resetBridgeState();
    bridgeState.taskMode = 'public_failure_then_deferred_route';
    await runElectronSmoke(devUrl, bridge.url, 'approve', false, 'deferred_route_handoff');
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
