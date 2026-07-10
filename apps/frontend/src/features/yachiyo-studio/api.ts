import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/bridge';
import type {
  AgentDefinitionSnapshot,
  AgentDeskSnapshot,
  AgentGroupSnapshot,
  ArtifactContentSnapshot,
  FutureTaskSnapshot,
  FutureTaskTriggerResultSnapshot,
  GroupRunSnapshot,
  InstallRestrictedToolPluginRequest,
  MemorySnapshot,
  PlannerDecisionSnapshot,
  PlannerOrchestrationStartSnapshot,
  ReplanContinuationSnapshot,
  RestrictedToolPluginSnapshot,
  RunEventPageSnapshot,
  RerunRunRequest,
  DesktopProviderConformanceSnapshot,
  RuntimeExecutionEnvelopeSnapshot,
  SaveAgentGroupRequest,
  SkillFolderSnapshot,
  SkillSnapshot,
  SkillSourceRootSnapshot,
  ToolCatalogSnapshot,
  StartPlannerOrchestrationRequest,
  UpdateRestrictedToolPluginRequest,
  WorkflowRunSnapshot,
  WorkflowSnapshot,
  YachiyoRunTimelineSnapshot,
} from './types';

export type YachiyoRunEventsPage = RunEventPageSnapshot;

export type YachiyoRunArtifactPayload = ArtifactContentSnapshot;

export type YachiyoStudioPlanTaskRequest = {
  prompt: string;
  allowed_tools?: string[];
  metadata?: Record<string, unknown>;
};

export type YachiyoStudioPlanExecutionRequest = YachiyoStudioPlanTaskRequest & {
  direct?: boolean;
};

export type YachiyoStudioStartPlannerOrchestrationRequest = StartPlannerOrchestrationRequest;

export type YachiyoStudioDesktopProviderSessionRequest = {
  host?: string;
  port?: number;
  provider_manifest?: string;
  provider_id?: string;
  requires_real_virtual_desktop_backend?: boolean;
  tools?: string[];
};

export type YachiyoStudioDesktopProviderSessionSnapshot = {
  error?: string;
  needed?: boolean;
  ok?: boolean;
  reason?: string;
  request_ids?: string[];
  status?: string;
  running?: boolean;
  started?: boolean;
  stopped?: boolean;
  pid?: number | null;
  provider_id?: string;
  provider_manifest?: string;
  authentication_configured?: boolean;
  url?: string;
  command?: string[];
  env?: Record<string, string>;
  provider_status?: Record<string, unknown>;
  provider_contract?: Record<string, unknown>;
  provider_conformance?: DesktopProviderConformanceSnapshot | null;
  source?: string;
  tool_names?: string[];
  desktop_session_kind?: string;
  desktop_session_isolated?: boolean | null;
  foreground_takeover_required?: boolean | null;
  keyboard_mouse_capture_supported?: boolean | null;
  desktop_backend_kind?: string;
  desktop_backend_is_loopback?: boolean | null;
  desktop_backend_ready_for_public_release?: boolean | null;
  requires_real_virtual_desktop_backend?: boolean | null;
};

export type YachiyoStudioVirtualDesktopProvisionRequest = {
  ssh_target: string;
  session_id: string;
  approved: boolean;
  start_session?: boolean;
};

export type YachiyoStudioVirtualDesktopProvisionSnapshot = {
  ok?: boolean;
  status?: string;
  error?: string;
  approval_required?: boolean;
  provider_id?: string;
  provider_manifest?: string;
  remote_provider_executable?: string;
  local_token_file?: string;
  running?: boolean;
  started?: boolean;
  session?: YachiyoStudioDesktopProviderSessionSnapshot;
};

export type YachiyoStudioRunReplanRecoveryActionRequest = {
  request_id: string;
  action_id?: string;
  agent_id?: string;
  title?: string;
  client_run_id?: string;
  continue_to_model?: boolean;
  metadata?: Record<string, unknown>;
};

export type YachiyoStudioNextReplanContinuationRequest = {
  request_id?: string;
  action_id?: string;
  agent_id?: string;
  title?: string;
  client_run_id?: string;
  continue_to_model?: boolean;
  metadata?: Record<string, unknown>;
};

export type YachiyoStudioNextReplanContinuationResult = {
  action_id?: string | null;
  approval_required?: boolean;
  auto_start_blockers?: string[];
  auto_start_eligible?: boolean;
  auto_start_reason?: string;
  continuation?: ReplanContinuationSnapshot | null;
  manual_start_available?: boolean;
  replan_request_id?: string;
  started: boolean;
  run?: YachiyoRunTimelineSnapshot | null;
  tool_name?: string;
  reason?: string;
};

export type YachiyoStudioRunToolRecoveryActionRequest = {
  tool_call_id: string;
  action_id: string;
  action_kind?: string;
  agent_id?: string;
  title?: string;
  client_run_id?: string;
  continue_to_model?: boolean;
  input_override?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type YachiyoSkillSyncResult = {
  source?: string;
  source_type?: string;
  source_ref?: string;
  status: 'imported' | 'updated' | 'skipped' | 'failed' | string;
  skill_id?: string;
  name?: string;
  message?: string;
};

export type YachiyoSkillSyncResponse = {
  ok?: boolean;
  roots?: SkillSourceRootSnapshot[];
  summary?: Record<string, number>;
  results?: YachiyoSkillSyncResult[];
};

export type YachiyoSkillInstallResponse = {
  ok?: boolean;
  installer?: string;
  command?: string[];
  started_at?: string;
  finished_at?: string;
  returncode?: number;
  stdout?: string;
  stderr?: string;
  sync?: YachiyoSkillSyncResponse | null;
};

export async function getYachiyoStudioToolCatalog(): Promise<ToolCatalogSnapshot> {
  return apiGet<ToolCatalogSnapshot>('/yachiyo/studio/tools');
}

export async function getYachiyoStudioDesktopProviderSession(): Promise<YachiyoStudioDesktopProviderSessionSnapshot> {
  return apiGet<YachiyoStudioDesktopProviderSessionSnapshot>(
    '/yachiyo/studio/tools/desktop-provider/session',
  );
}

export async function startYachiyoStudioDesktopProviderSession(
  request: YachiyoStudioDesktopProviderSessionRequest = {},
): Promise<YachiyoStudioDesktopProviderSessionSnapshot> {
  return apiPost<YachiyoStudioDesktopProviderSessionSnapshot>(
    '/yachiyo/studio/tools/desktop-provider/session/start',
    request,
  );
}

export async function stopYachiyoStudioDesktopProviderSession(): Promise<YachiyoStudioDesktopProviderSessionSnapshot> {
  return apiPost<YachiyoStudioDesktopProviderSessionSnapshot>(
    '/yachiyo/studio/tools/desktop-provider/session/stop',
    {},
  );
}

export async function provisionYachiyoStudioVirtualDesktopGuest(
  request: YachiyoStudioVirtualDesktopProvisionRequest,
): Promise<YachiyoStudioVirtualDesktopProvisionSnapshot> {
  return apiPost<YachiyoStudioVirtualDesktopProvisionSnapshot>(
    '/yachiyo/studio/tools/desktop-provider/provision',
    request,
  );
}

export async function planYachiyoStudioTask(
  request: YachiyoStudioPlanTaskRequest,
): Promise<PlannerDecisionSnapshot> {
  return apiPost<PlannerDecisionSnapshot>('/yachiyo/studio/planner', request);
}

export async function planYachiyoStudioExecution(
  request: YachiyoStudioPlanExecutionRequest,
): Promise<RuntimeExecutionEnvelopeSnapshot> {
  return apiPost<RuntimeExecutionEnvelopeSnapshot>('/yachiyo/studio/planner/execution', request);
}

export async function startYachiyoStudioPlannerOrchestration(
  request: YachiyoStudioStartPlannerOrchestrationRequest,
): Promise<PlannerOrchestrationStartSnapshot> {
  return apiPost<PlannerOrchestrationStartSnapshot>(
    '/yachiyo/studio/planner/orchestration/start',
    request,
  );
}

export async function listYachiyoRestrictedToolPlugins(): Promise<RestrictedToolPluginSnapshot[]> {
  const payload = await apiGet<{ plugins?: RestrictedToolPluginSnapshot[] }>(
    '/yachiyo/studio/tools/restricted-plugins',
  );
  return payload.plugins || [];
}

export async function installYachiyoRestrictedToolPlugin(
  request: InstallRestrictedToolPluginRequest,
): Promise<RestrictedToolPluginSnapshot> {
  return apiPost<RestrictedToolPluginSnapshot>(
    '/yachiyo/studio/tools/restricted-plugins',
    request,
  );
}

export async function updateYachiyoRestrictedToolPlugin(
  pluginId: string,
  request: UpdateRestrictedToolPluginRequest,
): Promise<RestrictedToolPluginSnapshot> {
  return apiPatch<RestrictedToolPluginSnapshot>(
    `/yachiyo/studio/tools/restricted-plugins/${encodeURIComponent(pluginId)}`,
    request,
  );
}

export async function uninstallYachiyoRestrictedToolPlugin(
  pluginId: string,
): Promise<RestrictedToolPluginSnapshot> {
  return apiDelete<RestrictedToolPluginSnapshot>(
    `/yachiyo/studio/tools/restricted-plugins/${encodeURIComponent(pluginId)}`,
  );
}

export async function listYachiyoStudioAgents(): Promise<AgentDefinitionSnapshot[]> {
  const payload = await apiGet<{ agents?: AgentDefinitionSnapshot[] }>('/yachiyo/studio/agents').catch(() => (
    apiGet<{ agents?: AgentDefinitionSnapshot[] }>('/ui/agents')
  ));
  return payload.agents || [];
}

export async function getYachiyoStudioAgent(agentId: string): Promise<AgentDefinitionSnapshot> {
  const publicPath = `/yachiyo/studio/agents/${encodeURIComponent(agentId)}`;
  const legacyPath = `/ui/agents/${encodeURIComponent(agentId)}`;
  return apiGet<AgentDefinitionSnapshot>(publicPath).catch(() => (
    apiGet<AgentDefinitionSnapshot>(legacyPath)
  ));
}

export async function saveYachiyoStudioAgent(
  request: Partial<AgentDefinitionSnapshot>,
): Promise<AgentDefinitionSnapshot> {
  const agentId = String(request.agent_id || '').trim();
  if (agentId) {
    const encodedAgentId = encodeURIComponent(agentId);
    return apiPatch<AgentDefinitionSnapshot>(`/yachiyo/studio/agents/${encodedAgentId}`, request).catch(() => (
      apiPatch<AgentDefinitionSnapshot>(`/ui/agents/${encodedAgentId}`, request)
    ));
  }
  return apiPost<AgentDefinitionSnapshot>('/yachiyo/studio/agents', request).catch(() => (
    apiPost<AgentDefinitionSnapshot>('/ui/agents', request)
  ));
}

export async function deleteYachiyoStudioAgent(agentId: string): Promise<{ ok?: boolean }> {
  const encodedAgentId = encodeURIComponent(agentId);
  return apiDelete(`/yachiyo/studio/agents/${encodedAgentId}`).catch(() => (
    apiDelete(`/ui/agents/${encodedAgentId}`)
  ));
}

export async function testYachiyoStudioAgentModel(
  agentId: string,
): Promise<{ ok?: boolean; message?: string; missing?: string[] }> {
  const encodedAgentId = encodeURIComponent(agentId);
  return apiPost<{ ok?: boolean; message?: string; missing?: string[] }>(`/yachiyo/studio/agents/${encodedAgentId}/test-model`, {}).catch(() => (
    apiPost<{ ok?: boolean; message?: string; missing?: string[] }>(`/ui/agents/${encodedAgentId}/test-model`, {})
  ));
}

export async function getYachiyoAgentDesk(agentId: string): Promise<AgentDeskSnapshot> {
  return apiGet<AgentDeskSnapshot>(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}/desk`);
}

export async function saveYachiyoAgentDeskNote(
  agentId: string,
  content: string,
): Promise<AgentDeskSnapshot> {
  return apiPost<AgentDeskSnapshot>(
    `/yachiyo/studio/agents/${encodeURIComponent(agentId)}/desk/note`,
    { content },
  );
}

export async function saveYachiyoAgentDeskFile(
  agentId: string,
  path: string,
  content: string,
): Promise<AgentDeskSnapshot> {
  return apiPost<AgentDeskSnapshot>(
    `/yachiyo/studio/agents/${encodeURIComponent(agentId)}/desk/files`,
    { path, content },
  );
}

export async function triggerYachiyoAgentDeskFileEvent(
  agentId: string,
  path: string,
  eventType: 'created' | 'modified' | 'deleted' | 'changed' = 'changed',
): Promise<FutureTaskSnapshot> {
  return apiPost<FutureTaskSnapshot>(
    `/yachiyo/studio/agents/${encodeURIComponent(agentId)}/desk/file-events`,
    { path, event_type: eventType },
  );
}

export async function attachYachiyoAgentSkill(
  agentId: string,
  skillId: string,
): Promise<AgentDefinitionSnapshot> {
  const encodedAgentId = encodeURIComponent(agentId);
  return apiPost<AgentDefinitionSnapshot>(`/yachiyo/studio/agents/${encodedAgentId}/skills`, {
    skill_id: skillId,
  }).catch(() => (
    apiPost<AgentDefinitionSnapshot>(`/ui/agents/${encodedAgentId}/skills`, { skill_id: skillId })
  ));
}

export async function detachYachiyoAgentSkill(
  agentId: string,
  skillId: string,
): Promise<AgentDefinitionSnapshot> {
  const encodedAgentId = encodeURIComponent(agentId);
  const encodedSkillId = encodeURIComponent(skillId);
  return apiDelete<AgentDefinitionSnapshot>(`/yachiyo/studio/agents/${encodedAgentId}/skills/${encodedSkillId}`).catch(() => (
    apiDelete<AgentDefinitionSnapshot>(`/ui/agents/${encodedAgentId}/skills/${encodedSkillId}`)
  ));
}

export async function listYachiyoSkills(): Promise<SkillSnapshot[]> {
  const payload = await apiGet<{ skills?: SkillSnapshot[] }>('/yachiyo/studio/skills').catch(() => (
    apiGet<{ skills?: SkillSnapshot[] }>('/ui/skills')
  ));
  return payload.skills || [];
}

export async function updateYachiyoSkill(
  skillId: string,
  request: Partial<SkillSnapshot>,
): Promise<SkillSnapshot> {
  const encodedSkillId = encodeURIComponent(skillId);
  return apiPatch<SkillSnapshot>(`/yachiyo/studio/skills/${encodedSkillId}`, request).catch(() => (
    apiPatch<SkillSnapshot>(`/ui/skills/${encodedSkillId}`, request)
  ));
}

export async function deleteYachiyoSkill(skillId: string): Promise<{ ok?: boolean }> {
  const encodedSkillId = encodeURIComponent(skillId);
  return apiDelete(`/yachiyo/studio/skills/${encodedSkillId}`).catch(() => (
    apiDelete(`/ui/skills/${encodedSkillId}`)
  ));
}

export async function listYachiyoSkillFolders(): Promise<SkillFolderSnapshot[]> {
  const payload = await apiGet<{ folders?: SkillFolderSnapshot[] }>('/yachiyo/studio/skill-folders').catch(() => (
    apiGet<{ folders?: SkillFolderSnapshot[] }>('/ui/skill-folders')
  ));
  return payload.folders || [];
}

export async function createYachiyoSkillFolder(
  request: Partial<SkillFolderSnapshot>,
): Promise<SkillFolderSnapshot> {
  return apiPost<SkillFolderSnapshot>('/yachiyo/studio/skill-folders', request).catch(() => (
    apiPost<SkillFolderSnapshot>('/ui/skill-folders', request)
  ));
}

export async function updateYachiyoSkillFolder(
  folderId: string,
  request: Partial<SkillFolderSnapshot>,
): Promise<SkillFolderSnapshot> {
  const encodedFolderId = encodeURIComponent(folderId);
  return apiPatch<SkillFolderSnapshot>(`/yachiyo/studio/skill-folders/${encodedFolderId}`, request).catch(() => (
    apiPatch<SkillFolderSnapshot>(`/ui/skill-folders/${encodedFolderId}`, request)
  ));
}

export async function deleteYachiyoSkillFolder(
  folderId: string,
  options: { deleteSkills?: boolean } = {},
): Promise<{ ok?: boolean; deleted_skill_count?: number }> {
  const query = options.deleteSkills ? '?delete_skills=true' : '';
  const encodedFolderId = encodeURIComponent(folderId);
  return apiDelete(`/yachiyo/studio/skill-folders/${encodedFolderId}${query}`).catch(() => (
    apiDelete(`/ui/skill-folders/${encodedFolderId}${query}`)
  ));
}

export async function listYachiyoSkillSources(): Promise<SkillSourceRootSnapshot[]> {
  const payload = await apiGet<{ roots?: SkillSourceRootSnapshot[] }>('/yachiyo/studio/skills/sources').catch(() => (
    apiGet<{ roots?: SkillSourceRootSnapshot[] }>('/ui/skills/sources')
  ));
  return payload.roots || [];
}

export async function importYachiyoSkill(
  sourcePath: string,
  folderId?: string,
): Promise<SkillSnapshot> {
  const body = {
    source_path: sourcePath,
    folder_id: folderId || undefined,
  };
  return apiPost<SkillSnapshot>('/yachiyo/studio/skills/import', body).catch(() => (
    apiPost<SkillSnapshot>('/ui/skills/import', body)
  ));
}

export async function syncYachiyoNativeSkills(): Promise<YachiyoSkillSyncResponse> {
  return apiPost('/yachiyo/studio/skills/sync', {}).catch(() => (
    apiPost('/ui/skills/sync', {})
  ));
}

export async function installYachiyoSkillCommand(
  command: string,
  folderId?: string,
): Promise<YachiyoSkillInstallResponse> {
  const body = {
    command,
    folder_id: folderId || undefined,
  };
  return apiPost('/yachiyo/studio/skills/install', body).catch(() => (
    apiPost('/ui/skills/install', body)
  ));
}

export async function listYachiyoMemories(
  includeDeleted = false,
  limit = 100,
): Promise<MemorySnapshot[]> {
  const query = new URLSearchParams({
    include_deleted: String(includeDeleted),
    limit: String(Math.max(1, Math.min(500, limit))),
  });
  const payload = await apiGet<{ memories?: MemorySnapshot[] }>(`/yachiyo/studio/memories?${query.toString()}`).catch(() => (
    apiGet<{ memories?: MemorySnapshot[] }>('/ui/memories').catch(() => ({ memories: [] }))
  ));
  return payload.memories || [];
}

export async function createYachiyoMemory(
  request: Partial<MemorySnapshot>,
): Promise<MemorySnapshot> {
  return apiPost<MemorySnapshot>('/yachiyo/studio/memories', request).catch(() => (
    apiPost<MemorySnapshot>('/ui/memories', request)
  ));
}

export async function updateYachiyoMemory(
  memoryId: string,
  request: Partial<MemorySnapshot> & { old_content?: string },
): Promise<MemorySnapshot> {
  const encodedMemoryId = encodeURIComponent(memoryId);
  return apiPatch<MemorySnapshot>(`/yachiyo/studio/memories/${encodedMemoryId}`, request).catch(() => (
    apiPatch<MemorySnapshot>(`/ui/memories/${encodedMemoryId}`, request)
  ));
}

export async function deleteYachiyoMemory(
  memoryId: string,
  reason = '',
): Promise<{ ok?: boolean }> {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  const encodedMemoryId = encodeURIComponent(memoryId);
  return apiDelete(`/yachiyo/studio/memories/${encodedMemoryId}${query}`).catch(() => (
    apiDelete(`/ui/memories/${encodedMemoryId}${query}`)
  ));
}

export async function listYachiyoFutureTasks(
  includeFinished = true,
  limit = 100,
): Promise<FutureTaskSnapshot[]> {
  const query = new URLSearchParams({
    include_finished: String(includeFinished),
    limit: String(Math.max(1, Math.min(500, limit))),
  });
  const payload = await apiGet<{ future_tasks?: FutureTaskSnapshot[] }>(`/yachiyo/studio/future-tasks?${query.toString()}`).catch(() => (
    apiGet<{ future_tasks?: FutureTaskSnapshot[] }>('/ui/future-tasks').catch(() => ({ future_tasks: [] }))
  ));
  return payload.future_tasks || [];
}

export async function cancelYachiyoFutureTask(
  futureTaskId: string,
  reason = '',
): Promise<{ ok?: boolean; future_task?: FutureTaskSnapshot }> {
  const encodedTaskId = encodeURIComponent(futureTaskId);
  return apiPost(
    `/yachiyo/studio/future-tasks/${encodedTaskId}/cancel`,
    reason ? { reason } : {},
  ).catch(() => (
    apiPost(`/ui/future-tasks/${encodedTaskId}/cancel`, reason ? { reason } : {})
  ));
}

export async function triggerDueYachiyoFutureTasks(
  limit = 20,
): Promise<{ ok?: boolean; triggered?: FutureTaskTriggerResultSnapshot[] }> {
  return apiPost('/yachiyo/studio/future-tasks/trigger-due', { limit }).catch(() => (
    apiPost('/ui/future-tasks/trigger-due', { limit })
  ));
}

export async function listYachiyoAgentGroups(): Promise<AgentGroupSnapshot[]> {
  const payload = await apiGet<{ groups?: AgentGroupSnapshot[] }>('/yachiyo/studio/groups');
  return payload.groups || [];
}

export async function getYachiyoAgentGroup(groupId: string): Promise<AgentGroupSnapshot> {
  return apiGet(`/yachiyo/studio/groups/${encodeURIComponent(groupId)}`);
}

export async function saveYachiyoAgentGroup(
  request: SaveAgentGroupRequest,
): Promise<AgentGroupSnapshot> {
  const groupId = String(request.group_id || '').trim();
  if (groupId) return apiPatch(`/yachiyo/studio/groups/${encodeURIComponent(groupId)}`, request);
  return apiPost('/yachiyo/studio/groups', request);
}

export async function startYachiyoGroupRun(
  groupId: string,
  objective: string,
  title?: string,
): Promise<GroupRunSnapshot> {
  const clientRunId = createClientRunId();
  return apiPost(`/yachiyo/studio/groups/${encodeURIComponent(groupId)}/runs`, {
    objective,
    title: title || undefined,
    client_run_id: clientRunId,
  });
}

export async function listYachiyoGroupRuns(limit = 50): Promise<GroupRunSnapshot[]> {
  const query = new URLSearchParams({ limit: String(Math.max(1, Math.min(200, limit))) });
  const payload = await apiGet<{ group_runs?: GroupRunSnapshot[] }>(`/yachiyo/studio/group-runs?${query.toString()}`);
  return payload.group_runs || [];
}

export async function getYachiyoGroupRun(groupRunId: string): Promise<GroupRunSnapshot> {
  return apiGet(`/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}`);
}

export async function startYachiyoGroupRunReplanRecoveryAction(
  groupRunId: string,
  request: YachiyoStudioRunReplanRecoveryActionRequest,
): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost<YachiyoRunTimelineSnapshot>(
    `/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}/replan-recovery-actions/start`,
    request,
  );
}

export async function startYachiyoGroupRunNextReplanContinuation(
  groupRunId: string,
  request: YachiyoStudioNextReplanContinuationRequest = {},
): Promise<YachiyoStudioNextReplanContinuationResult> {
  return apiPost<YachiyoStudioNextReplanContinuationResult>(
    `/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}/replan-recovery-actions/start-next`,
    request,
  );
}

export async function startYachiyoGroupRunToolRecoveryAction(
  groupRunId: string,
  request: YachiyoStudioRunToolRecoveryActionRequest,
): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost<YachiyoRunTimelineSnapshot>(
    `/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}/tool-recovery-actions/start`,
    request,
  );
}

export async function listYachiyoGroupRunEvents(
  groupRunId: string,
  afterSequence = 0,
  limit = 200,
): Promise<YachiyoRunEventsPage> {
  const query = new URLSearchParams({
    after_sequence: String(Math.max(0, afterSequence)),
    limit: String(Math.max(1, limit)),
  });
  return apiGet(`/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}/events?${query.toString()}`);
}

export async function getYachiyoRunTimeline(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  const publicPath = `/yachiyo/studio/runs/${encodeURIComponent(runId)}/timeline`;
  const legacyPath = `/ui/runs/${encodeURIComponent(runId)}`;
  return apiGet<YachiyoRunTimelineSnapshot>(publicPath).catch(() => (
    apiGet<YachiyoRunTimelineSnapshot>(legacyPath)
  ));
}

export async function startYachiyoRunReplanRecoveryAction(
  runId: string,
  request: YachiyoStudioRunReplanRecoveryActionRequest,
): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost<YachiyoRunTimelineSnapshot>(
    `/yachiyo/studio/runs/${encodeURIComponent(runId)}/replan-recovery-actions/start`,
    request,
  );
}

export async function startYachiyoRunNextReplanContinuation(
  runId: string,
  request: YachiyoStudioNextReplanContinuationRequest = {},
): Promise<YachiyoStudioNextReplanContinuationResult> {
  return apiPost<YachiyoStudioNextReplanContinuationResult>(
    `/yachiyo/studio/runs/${encodeURIComponent(runId)}/replan-recovery-actions/start-next`,
    request,
  );
}

export async function startYachiyoRunToolRecoveryAction(
  runId: string,
  request: YachiyoStudioRunToolRecoveryActionRequest,
): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost<YachiyoRunTimelineSnapshot>(
    `/yachiyo/studio/runs/${encodeURIComponent(runId)}/tool-recovery-actions/start`,
    request,
  );
}

export async function listYachiyoWorkflows(): Promise<WorkflowSnapshot[]> {
  const payload = await apiGet<{ workflows?: WorkflowSnapshot[] }>('/yachiyo/studio/workflows').catch(() => (
    apiGet<{ workflows?: WorkflowSnapshot[] }>('/ui/workflows')
  ));
  return payload.workflows || [];
}

export async function getYachiyoWorkflow(workflowId: string): Promise<WorkflowSnapshot> {
  const publicPath = `/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}`;
  const legacyPath = `/ui/workflows/${encodeURIComponent(workflowId)}`;
  return apiGet<WorkflowSnapshot>(publicPath).catch(() => (
    apiGet<WorkflowSnapshot>(legacyPath)
  ));
}

export async function saveYachiyoWorkflow(
  request: Partial<WorkflowSnapshot>,
): Promise<WorkflowSnapshot> {
  const workflowId = String(request.workflow_id || '').trim();
  if (workflowId) {
    const encodedWorkflowId = encodeURIComponent(workflowId);
    return apiPatch<WorkflowSnapshot>(`/yachiyo/studio/workflows/${encodedWorkflowId}`, request).catch(() => (
      apiPatch<WorkflowSnapshot>(`/ui/workflows/${encodedWorkflowId}`, request)
    ));
  }
  return apiPost<WorkflowSnapshot>('/yachiyo/studio/workflows', request).catch(() => (
    apiPost<WorkflowSnapshot>('/ui/workflows', request)
  ));
}

export async function listYachiyoRunTimelines(limit = 50): Promise<YachiyoRunTimelineSnapshot[]> {
  const query = new URLSearchParams({ limit: String(Math.max(1, Math.min(200, limit))) });
  const payload = await apiGet<{ runs?: YachiyoRunTimelineSnapshot[] }>(`/yachiyo/studio/runs?${query.toString()}`).catch(() => (
    apiGet<{ runs?: YachiyoRunTimelineSnapshot[] }>('/ui/runs')
  ));
  return payload.runs || [];
}

export async function startYachiyoAgentRun(
  agentId: string,
  objective: string,
  title?: string,
): Promise<YachiyoRunTimelineSnapshot> {
  const clientRunId = createClientRunId();
  return apiPost(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}/runs`, {
    objective,
    title: title || undefined,
    client_run_id: clientRunId,
  });
}

export async function listYachiyoRunEvents(
  runId: string,
  afterSequence = 0,
  limit = 200,
): Promise<YachiyoRunEventsPage> {
  const query = new URLSearchParams({
    after_sequence: String(Math.max(0, afterSequence)),
    limit: String(Math.max(1, limit)),
  });
  const publicPath = `/yachiyo/studio/runs/${encodeURIComponent(runId)}/events?${query.toString()}`;
  const legacyPath = `/ui/runs/${encodeURIComponent(runId)}/events?${query.toString()}`;
  return apiGet<YachiyoRunEventsPage>(publicPath).catch(() => (
    apiGet<YachiyoRunEventsPage>(legacyPath)
  ));
}

export async function readYachiyoRunArtifact(
  runId: string,
  path: string,
): Promise<YachiyoRunArtifactPayload> {
  const encodedPath = path.split('/').map((part) => encodeURIComponent(part)).join('/');
  const publicPath = `/yachiyo/studio/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}`;
  const legacyPath = `/ui/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}`;
  return apiGet<YachiyoRunArtifactPayload>(publicPath).catch(() => (
    apiGet<YachiyoRunArtifactPayload>(legacyPath)
  ));
}

export async function rerunYachiyoRun(
  runId: string,
  request: RerunRunRequest = {},
): Promise<YachiyoRunTimelineSnapshot> {
  const publicPath = `/yachiyo/studio/runs/${encodeURIComponent(runId)}/rerun`;
  const legacyPath = `/ui/runs/${encodeURIComponent(runId)}/rerun`;
  return apiPost<YachiyoRunTimelineSnapshot>(publicPath, request).catch(() => (
    apiPost<YachiyoRunTimelineSnapshot>(legacyPath, request)
  ));
}

export async function cancelYachiyoRun(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  const encodedRunId = encodeURIComponent(runId);
  return apiPost<YachiyoRunTimelineSnapshot>(`/yachiyo/studio/runs/${encodedRunId}/cancel`, {}).catch(() => (
    apiPost<YachiyoRunTimelineSnapshot>(`/ui/runs/${encodedRunId}/cancel`, {})
  ));
}

export async function deleteYachiyoRun(
  runId: string,
): Promise<{ ok?: boolean; deleted_run_ids?: string[]; deleted_run_count?: number }> {
  const encodedRunId = encodeURIComponent(runId);
  return apiDelete(`/yachiyo/studio/runs/${encodedRunId}`).catch(() => (
    apiDelete(`/ui/runs/${encodedRunId}`)
  ));
}

export async function approveYachiyoRunApproval(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  const encodedRunId = encodeURIComponent(runId);
  return apiPost<YachiyoRunTimelineSnapshot>(`/yachiyo/studio/runs/${encodedRunId}/approval/approve`, {}).catch(() => (
    apiPost<YachiyoRunTimelineSnapshot>(`/ui/runs/${encodedRunId}/approval/approve`, {})
  ));
}

export async function rejectYachiyoRunApproval(
  runId: string,
  reason = '',
): Promise<YachiyoRunTimelineSnapshot> {
  const encodedRunId = encodeURIComponent(runId);
  return apiPost<YachiyoRunTimelineSnapshot>(
    `/yachiyo/studio/runs/${encodedRunId}/approval/reject`,
    reason ? { reason } : {},
  ).catch(() => (
    apiPost<YachiyoRunTimelineSnapshot>(`/ui/runs/${encodedRunId}/approval/reject`, reason ? { reason } : {})
  ));
}

export async function startYachiyoWorkflowRun(
  workflowId: string,
  objective: string,
  title?: string,
): Promise<WorkflowRunSnapshot> {
  const clientRunId = createClientRunId();
  return apiPost(`/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}/runs`, {
    objective,
    title: title || undefined,
    client_run_id: clientRunId,
  });
}

export async function deleteYachiyoWorkflow(workflowId: string): Promise<{ ok?: boolean }> {
  const encodedWorkflowId = encodeURIComponent(workflowId);
  return apiDelete(`/yachiyo/studio/workflows/${encodedWorkflowId}`).catch(() => (
    apiDelete(`/ui/workflows/${encodedWorkflowId}`)
  ));
}

function createClientRunId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
