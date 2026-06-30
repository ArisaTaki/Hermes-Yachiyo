import type {
  AgentGroupSnapshot as RuntimeAgentGroupSnapshot,
  GroupRunSnapshot as RuntimeGroupRunSnapshot,
  RunTimelineSnapshot as RuntimeRunTimelineSnapshot,
  WorkflowRunSnapshot as RuntimeWorkflowRunSnapshot,
} from '../runtime-shared/types';

export type {
  AgentDefinitionSnapshot,
  AgentDeskItemSnapshot,
  AgentDeskSnapshot,
  AgentGroupMemberSnapshot,
  AgentGroupSnapshot,
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  ArtifactContentSnapshot,
  ArtifactSnapshot,
  CapabilityCategory,
  CapabilitySnapshot,
  DesktopExecutionCapabilitySnapshot,
  DesktopExecutionRisk,
  FutureTaskSnapshot,
  FutureTaskTriggerResultSnapshot,
  GroupRunSnapshot,
  InstallRestrictedToolPluginRequest,
  MemorySnapshot,
  MemoryTraceSnapshot,
  PlannerDecisionSnapshot,
  PlannerOrchestrationStartSnapshot,
  PlannerTraceSummarySnapshot,
  PublicRunEvent,
  RerunRunRequest,
  RunEventPageSnapshot,
  RunTimelineChildSnapshot,
  RunTimelineSnapshot,
  SkillFolderSnapshot,
  SkillSnapshot,
  SkillSourceRootSnapshot,
  SkillTraceSnapshot,
  RestrictedPluginToolSnapshot,
  RestrictedToolPluginSnapshot,
  ToolCatalogItemSnapshot,
  ToolCatalogSnapshot,
  ToolCallSnapshot,
  ToolPlanSnapshot,
  ToolPlanStepSnapshot,
  RuntimePlanSnapshot,
  StartPlannerOrchestrationRequest,
  UpdateRestrictedToolPluginRequest,
  WorkflowRunSnapshot,
  WorkflowSnapshot,
  TaskIntentKind,
  TaskIntentSnapshot,
} from '../runtime-shared/types';

export type SaveAgentGroupRequest = {
  group_id?: string;
  name?: string;
  description?: string;
  members?: Array<{ agent_id: string; role?: string; sort_order?: number; enabled?: boolean }>;
  participant_ids?: string[];
  mode?: RuntimeAgentGroupSnapshot['mode'];
  moderator_agent_id?: string | null;
  default_model?: string | null;
  memory_scope?: RuntimeAgentGroupSnapshot['memory_scope'];
  tool_policy_id?: string | null;
  enabled?: boolean;
};

export type YachiyoRunTimelineSnapshot = RuntimeRunTimelineSnapshot & {
  task_id?: string | null;
  session_id?: string | null;
  task_run_link_created_at?: string | null;
  task_run_link_updated_at?: string | null;
  task_run_link_run_status?: string | null;
  task_run_link_last_event_sequence?: number | null;
  workflow_id?: RuntimeWorkflowRunSnapshot['workflow_id'];
  objective?: RuntimeWorkflowRunSnapshot['objective'];
  current_node_id?: RuntimeWorkflowRunSnapshot['current_node_id'];
  current_node_label?: RuntimeWorkflowRunSnapshot['current_node_label'];
  final_answer?: RuntimeWorkflowRunSnapshot['final_answer'];
};

export type YachiyoGroupRunSnapshot = Omit<RuntimeGroupRunSnapshot, 'runs'> & {
  runs?: YachiyoRunTimelineSnapshot[];
};
