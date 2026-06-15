export type AgentGroupMemberSnapshot = {
  agent_id: string;
  name: string;
  role?: string | null;
  sort_order?: number;
  enabled?: boolean;
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

export type AgentGroupSnapshot = {
  group_id: string;
  name: string;
  description?: string | null;
  members: AgentGroupMemberSnapshot[];
  mode: 'moderated' | 'round_robin' | 'debate' | 'pipeline' | 'parallel' | 'custom' | string;
  moderator_agent_id?: string | null;
  default_model?: string | null;
  memory_scope?: 'shared' | 'per_agent' | 'hybrid' | string;
  tool_policy_id?: string | null;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type SaveAgentGroupRequest = {
  group_id?: string;
  name?: string;
  description?: string;
  members?: Array<{ agent_id: string; role?: string; sort_order?: number; enabled?: boolean }>;
  participant_ids?: string[];
  mode?: AgentGroupSnapshot['mode'];
  memory_scope?: AgentGroupSnapshot['memory_scope'];
  enabled?: boolean;
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

export type ApprovalCardSnapshot = {
  approval_id: string;
  run_id?: string | null;
  title: string;
  description?: string | null;
  status: string;
  tool_name?: string | null;
  risk_level?: string | null;
  input_preview?: Record<string, unknown>;
  policy_reason?: string | null;
  requested_at?: string;
  resolved_at?: string | null;
  open_in_studio_url?: string | null;
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
  visibility?: string;
  sensitivity?: string;
  payload?: Record<string, unknown>;
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

export type RunTimelineSnapshot = {
  run_id: string;
  parent_run_id?: string | null;
  group_run_id?: string | null;
  run_group_id?: string | null;
  workflow_run_id?: string | null;
  agent_id?: string | null;
  status: string;
  title?: string | null;
  events?: PublicRunEvent[];
  tool_calls?: ToolCallSnapshot[];
  approvals?: ApprovalCardSnapshot[];
  pending_approval?: ApprovalCardSnapshot | null;
  artifacts?: ArtifactSnapshot[];
  children?: Array<{
    run_id: string;
    title?: string | null;
    status?: string;
    kind?: string | null;
    agent_id?: string | null;
    workflow_id?: string | null;
  }>;
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
  runs?: RunTimelineSnapshot[];
  child_run_ids?: string[];
  shared_artifacts?: ArtifactSnapshot[];
  pending_approvals?: ApprovalCardSnapshot[];
  final_answer?: string | null;
  created_at?: string;
  updated_at?: string;
};
