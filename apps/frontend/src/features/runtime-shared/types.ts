export type TaskStatus = 'queued' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'cancelled' | 'expired';
export type GroupMode = 'moderated' | 'round_robin' | 'debate' | 'pipeline' | 'parallel' | 'custom';
export type MemoryScope = 'shared' | 'per_agent' | 'hybrid';

export type ReadinessSnapshot = {
  ready: boolean;
  status?: string;
  message?: string | null;
  capabilities?: Record<string, unknown>;
};

export type PublicRunEvent = {
  event_id?: string | null;
  run_id: string;
  sequence: number;
  schema_version?: number;
  event_type: string;
  title?: string | null;
  detail?: string | null;
  actor?: string | null;
  visibility?: 'user' | 'internal' | string;
  sensitivity?: 'public' | 'secret' | string;
  payload?: Record<string, unknown>;
  created_at?: string;
};

export type RunEventPageSnapshot = {
  run_id: string;
  after_sequence: number;
  limit: number;
  next_after_sequence: number;
  has_more: boolean;
  events: PublicRunEvent[];
};

export type ApprovalCardSnapshot = {
  approval_id: string;
  run_id?: string | null;
  title: string;
  description?: string | null;
  status?: ApprovalStatus | string;
  tool_name?: string | null;
  risk_level?: string | null;
  input_preview?: Record<string, unknown>;
  policy_reason?: string | null;
  requested_at?: string;
  resolved_at?: string | null;
  open_in_studio_url?: string | null;
};

export type ArtifactSnapshot = {
  artifact_id: string;
  run_id?: string | null;
  source_run_id?: string | null;
  title: string;
  kind: string;
  path?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  preview_text?: string | null;
  url?: string | null;
  created_at?: string;
};

export type ToolCallSnapshot = {
  tool_call_id: string;
  run_id?: string | null;
  tool_name: string;
  status: string;
  risk_level?: string | null;
  input_preview?: Record<string, unknown>;
  output_preview?: Record<string, unknown>;
  approval_id?: string | null;
  started_at?: string;
  completed_at?: string | null;
};

export type AgentTaskSnapshot = {
  task_id: string;
  conversation_id?: string | null;
  title: string;
  status: TaskStatus;
  summary?: string | null;
  current_step?: string | null;
  progress_text?: string | null;
  needs_user_action?: boolean;
  pending_approvals?: ApprovalCardSnapshot[];
  recent_events?: PublicRunEvent[];
  artifacts?: ArtifactSnapshot[];
  open_in_studio_url?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type RunTimelineChildSnapshot = {
  run_id: string;
  title?: string | null;
  status?: string;
  kind?: string | null;
  agent_id?: string | null;
  workflow_id?: string | null;
};

export type RunTimelineSnapshot = {
  run_id: string;
  parent_run_id?: string | null;
  group_run_id?: string | null;
  run_group_id?: string | null;
  workflow_run_id?: string | null;
  agent_id?: string | null;
  status: string;
  title?: string | null;
  task_id?: string | null;
  session_id?: string | null;
  task_run_link_created_at?: string | null;
  task_run_link_updated_at?: string | null;
  task_run_link_run_status?: string | null;
  task_run_link_last_event_sequence?: number | null;
  events?: PublicRunEvent[];
  tool_calls?: ToolCallSnapshot[];
  approvals?: ApprovalCardSnapshot[];
  pending_approval?: ApprovalCardSnapshot | null;
  artifacts?: ArtifactSnapshot[];
  children?: RunTimelineChildSnapshot[];
  created_at?: string;
  updated_at?: string;
};

export type AgentDefinitionSnapshot = {
  agent_id: string;
  name: string;
  nickname?: string | null;
  description?: string | null;
  instructions?: string | null;
  persona_prompt?: string | null;
  avatar_url?: string | null;
  category?: string | null;
  model_mode?: string | null;
  execution_backend?: string | null;
  model_profile_id?: string | null;
  vision_model_profile_id?: string | null;
  model_config?: Record<string, unknown>;
  tool_policy?: Record<string, unknown>;
  workspace_policy?: Record<string, unknown>;
  skill_ids?: string[];
  output_contract?: string | null;
  enabled?: boolean;
  virtual?: boolean;
  system?: boolean;
  builtin?: boolean;
  editable?: boolean;
  deletable?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type SkillSnapshot = {
  skill_id: string;
  name: string;
  description?: string | null;
  source_path?: string | null;
  local_path?: string | null;
  folder_id?: string | null;
  folder_name?: string | null;
  source_type?: string | null;
  origin_path?: string | null;
  source_ref?: string | null;
  content_hash?: string | null;
  last_synced_at?: string | null;
  sync_status?: string | null;
  content_summary?: string | null;
  skill_markdown?: string | null;
  asset_paths?: string[];
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type SkillFolderSnapshot = {
  folder_id: string;
  name: string;
  description?: string | null;
  source_scope?: 'all' | 'installed' | 'native' | string;
  sort_order?: number;
  skill_count?: number;
  installed_count?: number;
  native_count?: number;
  created_at?: string;
  updated_at?: string;
};

export type SkillSourceRootSnapshot = {
  path: string;
  source_type: string;
  library?: 'native' | 'installed' | string | null;
  exists?: boolean;
  skill_count?: number;
};

export type MemorySnapshot = {
  memory_id: string;
  scope: string;
  kind: string;
  content: string;
  source_session_id?: string | null;
  source_message_id?: string | null;
  source_task_id?: string | null;
  source_run_id?: string | null;
  confidence?: number;
  pinned?: boolean;
  user_confirmed?: boolean;
  created_at?: string;
  updated_at?: string;
  deleted_at?: string | null;
};

export type FutureTaskSnapshot = {
  future_task_id: string;
  title: string;
  prompt: string;
  runnable_id?: string | null;
  runnable_name?: string | null;
  status: 'scheduled' | 'triggered' | 'cancelled' | 'failed' | string;
  scheduled_at_epoch: number;
  cron?: string | null;
  source_run_id?: string | null;
  last_run_id?: string | null;
  run_count?: number;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  cancelled_at?: string | null;
};

export type AgentGroupMemberSnapshot = {
  agent_id: string;
  name: string;
  role?: string | null;
  sort_order?: number;
  enabled?: boolean;
};

export type AgentGroupSnapshot = {
  group_id: string;
  name: string;
  description?: string | null;
  members: AgentGroupMemberSnapshot[];
  mode: GroupMode | string;
  moderator_agent_id?: string | null;
  default_model?: string | null;
  memory_scope?: MemoryScope | string;
  tool_policy_id?: string | null;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type GroupRunSnapshot = {
  group_run_id: string;
  run_group_id?: string | null;
  group_id: string;
  title: string;
  status: string;
  objective: string;
  participants: AgentGroupMemberSnapshot[];
  active_speaker_agent_id?: string | null;
  events?: PublicRunEvent[];
  runs?: RunTimelineSnapshot[];
  child_run_ids?: string[];
  shared_artifacts?: ArtifactSnapshot[];
  pending_approvals?: ApprovalCardSnapshot[];
  final_answer?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type WorkflowSnapshot = {
  workflow_id: string;
  name: string;
  description?: string | null;
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  default_input_schema?: Record<string, unknown>;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type WorkflowRunSnapshot = RunTimelineSnapshot & {
  workflow_id?: string | null;
  objective?: string;
  current_node_id?: string | null;
  current_node_label?: string | null;
  final_answer?: string | null;
};

export type FutureTaskTriggerResultSnapshot = {
  ok?: boolean;
  future_task?: FutureTaskSnapshot | null;
  run?: RunTimelineSnapshot | null;
  error?: string | null;
};

export type StartChatTaskRequest = {
  prompt: string;
  conversation_id?: string | null;
  title?: string | null;
  agent_id?: string | null;
  metadata?: Record<string, unknown>;
};
