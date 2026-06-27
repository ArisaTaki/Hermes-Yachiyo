import type { ReadinessSnapshot } from '../runtime-shared/types';

export type {
  AgentDefinitionSnapshot,
  AgentTaskLightSnapshot,
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  ArtifactContentSnapshot,
  ArtifactSnapshot,
  ChatRunnableCatalogSnapshot,
  ChatRunnableParticipantSnapshot,
  ChatRunnableSnapshot,
  PlannerTraceSummarySnapshot,
  PublicRunEvent,
  RunEventPageSnapshot,
  RunTimelineSnapshot,
  StartChatTaskRequest,
  TaskStatus,
  ToolCallSnapshot,
  WorkflowSnapshot,
} from '../runtime-shared/types';

export type YachiyoReadinessSnapshot = ReadinessSnapshot;

export type PendingAttachment = {
  id: string;
  name: string;
  mime_type: string;
  size: number;
  width?: number;
  height?: number;
  data_url: string;
};

export type ChatE2EImageDetail = {
  name?: string;
  mime_type?: string;
  mimeType?: string;
  data_url?: string;
  dataUrl?: string;
  base64?: string;
};

export type ChatAttachment = {
  id?: string;
  kind?: string;
  name?: string;
  mime_type?: string;
  size?: number;
  url?: string;
  source?: string;
  spoken_text?: string;
};

export type ChatActivityEvent = {
  event_id?: string;
  session_id?: string;
  task_id?: string;
  tool_name?: string;
  phase?: string;
  title?: string;
  detail?: string;
  status?: string;
  duration_seconds?: number | null;
  created_at?: string;
  metadata?: {
    run_id?: string;
    workflow_run_id?: string;
    run_status?: string;
    pending_approval?: Record<string, unknown>;
  } & Record<string, unknown>;
};

export type ChatParticipant = {
  kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  id?: string;
  name?: string;
  nickname?: string;
  description?: string;
  avatar_url?: string;
  category?: string;
  participants?: ChatParticipant[];
};

export type ChatMessageMetadata = {
  sender?: ChatParticipant;
  target?: ChatParticipant;
  runnable_kind?: string;
  runnable_id?: string;
  run_id?: string;
  run_group_id?: string;
  run_status?: string;
  group_goal?: string;
  delegated_goal?: string;
  pending_approval?: {
    approval_id?: string;
    tool?: string;
    input_preview?: unknown;
    requested_at?: string;
  };
  run_progress_title?: string;
  run_progress_detail?: string;
  run_artifact_count?: number;
  run_artifacts?: Array<{ path?: string; kind?: string }>;
  workflow_run_id?: string;
  workflow_status?: string;
  workflow_node?: string;
  workflow_waiting_child_run_id?: string;
  workflow_waiting_node?: string;
  workflow_waiting_tool?: string;
  workflow_waiting_pending_approval?: {
    approval_id?: string;
    tool?: string;
    input_preview?: unknown;
    requested_at?: string;
  };
  group_dispatch_count?: number;
  group_dispatch_run_group_id?: string;
  group_dispatch_skipped?: string[];
  group_agent_summary_task_id?: string;
  group_agent_summary_for_task_id?: string;
  group_agent_summary_pending?: boolean;
  group_agent_summary_status?: string;
  group_agent_summary_error?: string;
  delegated_run_source_task_id?: string;
  group_followup_for_task_ids?: string[];
  group_followup_for_agent_message_ids?: string[];
  guidance_type?: string;
  suggested_goal?: string;
};

export type ChatMessage = {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  status?: string;
  error?: string;
  created_at?: string;
  task_id?: string;
  token_count?: number;
  progress_label?: string;
  activity_events?: ChatActivityEvent[];
  attachments?: ChatAttachment[];
  metadata?: ChatMessageMetadata;
};

export type MessagesPayload = {
  ok?: boolean;
  error?: string;
  is_processing?: boolean;
  processing_count?: number;
  messages?: ChatMessage[];
  token_count?: number;
  anchor_message_id?: string;
  session_context?: ChatSessionContext;
};

export type DelegatedRunSummaryResult = {
  created: boolean;
  error: string;
  taskId: string;
  isProcessing: boolean;
  processingCount: number;
};

export type SessionSearchMatch = {
  kind?: string;
  query?: string;
  message_id?: string;
  role?: string;
  snippet?: string;
  created_at?: string;
  match_count?: number;
};

export type SessionItem = {
  session_id: string;
  title?: string;
  conversation_kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  runnable_id?: string;
  runnable_name?: string;
  run_group_id?: string;
  avatar_url?: string;
  participants?: ChatParticipant[];
  created_at?: string;
  updated_at?: string;
  message_count?: number;
  token_count?: number;
  is_processing?: boolean;
  processing_count?: number;
  approval_count?: number;
  latest_activity?: ChatActivityEvent | null;
  latest_message_preview?: string;
  latest_message_status?: string;
  search_match?: SessionSearchMatch | null;
};

export type SessionsPayload = {
  ok?: boolean;
  current_session_id?: string;
  sessions?: SessionItem[];
};

export type ChatSessionContext = {
  conversation_kind?: 'main' | 'agent' | 'workflow' | 'group' | 'unassigned' | string;
  runnable_id?: string;
  runnable_name?: string;
  run_group_id?: string;
  avatar_url?: string;
  participants?: ChatParticipant[];
};

export type ImageInputPayload = {
  can_attach_images?: boolean;
  mode?: string;
  route?: string;
  supports_native_vision?: boolean | null;
  requires_vision_pipeline?: boolean;
  label?: string;
  reason?: string;
};

export type ExecutorPayload = {
  executor?: string;
  available?: boolean;
  image_input?: ImageInputPayload;
};

export type AssistantProfilePayload = {
  ok?: boolean;
  agent_name?: string;
  agent_nickname?: string;
  agent_avatar_url?: string;
  user_avatar_url?: string;
};

export type RenderState = {
  shown: string;
  target: string;
};

export type ChatNotice = {
  id: number;
  kind: 'warn' | 'danger';
  title: string;
  detail: string;
  action_label?: string;
  action_view?: string;
  action_params?: Record<string, string>;
};
