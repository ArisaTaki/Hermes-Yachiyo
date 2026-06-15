import type { AgentGroupSnapshot as RuntimeAgentGroupSnapshot } from '../runtime-shared/types';

export type {
  AgentDefinitionSnapshot,
  AgentGroupMemberSnapshot,
  AgentGroupSnapshot,
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  ArtifactSnapshot,
  FutureTaskSnapshot,
  FutureTaskTriggerResultSnapshot,
  GroupRunSnapshot,
  MemorySnapshot,
  PublicRunEvent,
  RunTimelineChildSnapshot,
  RunTimelineSnapshot,
  SkillFolderSnapshot,
  SkillSnapshot,
  SkillSourceRootSnapshot,
  ToolCallSnapshot,
  WorkflowSnapshot,
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
