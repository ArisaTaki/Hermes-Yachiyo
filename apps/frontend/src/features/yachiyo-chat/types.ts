export type TaskStatus = 'queued' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled';

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

export type ApprovalCardSnapshot = {
  approval_id: string;
  run_id?: string | null;
  title: string;
  description?: string | null;
  status?: 'pending' | 'approved' | 'rejected' | 'cancelled' | 'expired' | string;
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

export type YachiyoReadinessSnapshot = {
  ready: boolean;
  status?: string;
  message?: string | null;
  capabilities?: Record<string, unknown>;
};

export type StartChatTaskRequest = {
  prompt: string;
  conversation_id?: string | null;
  title?: string | null;
  agent_id?: string | null;
  metadata?: Record<string, unknown>;
};
