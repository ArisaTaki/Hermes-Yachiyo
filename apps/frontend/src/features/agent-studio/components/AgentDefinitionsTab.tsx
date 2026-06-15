import type { AgentSpec, SkillFolderSpec, SkillSpec } from '../types';
import type { ModelProfile } from '../../../lib/modelProfiles';
import type { AgentDraft } from '../types';
import type { SkillFolderFilter, SkillSourceFilter } from '../utils/skills';
import { AgentEditorPanel } from './AgentEditorPanel';
import { AgentListPanel } from './AgentListPanel';

type AgentReadinessNotice = {
  tone: 'danger' | 'warn' | 'info';
  text: string;
};

type AgentDefinitionsTabProps = {
  agentManagementMode: boolean;
  agentQuickRunDisabled: boolean;
  agentQuickRunDisabledReason: string;
  agentReadinessNotices: AgentReadinessNotice[];
  agentRunGoal: string;
  agents: AgentSpec[];
  allAgentsSelected: boolean;
  busy: boolean;
  chatModelProfiles: ModelProfile[];
  customApiKeyConfigured: boolean;
  deletableAgentIds: string[];
  disabledMountedSkills: SkillSpec[];
  draft: AgentDraft;
  filteredMountSkills: SkillSpec[];
  mountedSkillCount: number;
  selectedAgentCount: number;
  selectedAgentDeletable: boolean;
  selectedAgentId: string;
  selectedAgentIdSet: Set<string>;
  selectedAgentReadOnly: boolean;
  selectedDeletableAgentCount: number;
  selectedSkillIds: string[];
  skillFolders: SkillFolderSpec[];
  skillMountFilter: SkillSourceFilter;
  skillMountFolderFilter: SkillFolderFilter;
  skillMountSearch: string;
  visibleMountedCount: number;
  visionModelProfiles: ModelProfile[];
  onAgentRunGoalChange: (value: string) => void;
  onClearAgentSelection: () => void;
  onDraftChange: (draft: AgentDraft) => void;
  onFinishAgentManagement: () => void;
  onMountVisibleSkills: () => void;
  onOpenModelProfiles: () => void;
  onPickAgentAvatar: () => void;
  onRequestDeleteAgent: () => void;
  onRequestDeleteSelectedAgents: () => void;
  onRunAgent: () => void;
  onSaveAgent: () => void;
  onSelectAgent: (agentId: string) => void;
  onSetAgentManagementMode: (enabled: boolean) => void;
  onSetSelectedAgentIds: (agentIds: string[]) => void;
  onSetSkillMountFilter: (filter: SkillSourceFilter) => void;
  onSetSkillMountFolderFilter: (filter: SkillFolderFilter) => void;
  onSetSkillMountSearch: (query: string) => void;
  onStartNewAgent: () => void;
  onTestAgentModel: () => void;
  onToggleAgentSelected: (agentId: string) => void;
  onToggleSkillMount: (skill: SkillSpec, mounted: boolean) => void;
  onUnmountVisibleSkills: () => void;
};

export function AgentDefinitionsTab({
  agentManagementMode,
  agentQuickRunDisabled,
  agentQuickRunDisabledReason,
  agentReadinessNotices,
  agentRunGoal,
  agents,
  allAgentsSelected,
  busy,
  chatModelProfiles,
  customApiKeyConfigured,
  deletableAgentIds,
  disabledMountedSkills,
  draft,
  filteredMountSkills,
  mountedSkillCount,
  selectedAgentCount,
  selectedAgentDeletable,
  selectedAgentId,
  selectedAgentIdSet,
  selectedAgentReadOnly,
  selectedDeletableAgentCount,
  selectedSkillIds,
  skillFolders,
  skillMountFilter,
  skillMountFolderFilter,
  skillMountSearch,
  visibleMountedCount,
  visionModelProfiles,
  onAgentRunGoalChange,
  onClearAgentSelection,
  onDraftChange,
  onFinishAgentManagement,
  onMountVisibleSkills,
  onOpenModelProfiles,
  onPickAgentAvatar,
  onRequestDeleteAgent,
  onRequestDeleteSelectedAgents,
  onRunAgent,
  onSaveAgent,
  onSelectAgent,
  onSetAgentManagementMode,
  onSetSelectedAgentIds,
  onSetSkillMountFilter,
  onSetSkillMountFolderFilter,
  onSetSkillMountSearch,
  onStartNewAgent,
  onTestAgentModel,
  onToggleAgentSelected,
  onToggleSkillMount,
  onUnmountVisibleSkills,
}: AgentDefinitionsTabProps) {
  return (
    <section className="agent-studio-grid" data-testid="agent-studio-agents">
      <AgentListPanel
        agents={agents}
        agentManagementMode={agentManagementMode}
        allAgentsSelected={allAgentsSelected}
        busy={busy}
        deletableAgentIds={deletableAgentIds}
        selectedAgentCount={selectedAgentCount}
        selectedAgentId={selectedAgentId}
        selectedAgentIdSet={selectedAgentIdSet}
        selectedDeletableAgentCount={selectedDeletableAgentCount}
        onClearSelection={onClearAgentSelection}
        onFinishManagement={onFinishAgentManagement}
        onRequestDeleteSelectedAgents={onRequestDeleteSelectedAgents}
        onSelectAgent={onSelectAgent}
        onSetAgentManagementMode={onSetAgentManagementMode}
        onSetSelectedAgentIds={onSetSelectedAgentIds}
        onStartNewAgent={onStartNewAgent}
        onToggleAgentSelected={onToggleAgentSelected}
      />
      <AgentEditorPanel
        agentQuickRunDisabled={agentQuickRunDisabled}
        agentQuickRunDisabledReason={agentQuickRunDisabledReason}
        agentReadinessNotices={agentReadinessNotices}
        agentRunGoal={agentRunGoal}
        busy={busy}
        chatModelProfiles={chatModelProfiles}
        customApiKeyConfigured={customApiKeyConfigured}
        disabledMountedSkills={disabledMountedSkills}
        draft={draft}
        filteredMountSkills={filteredMountSkills}
        mountedSkillCount={mountedSkillCount}
        selectedAgentDeletable={selectedAgentDeletable}
        selectedAgentReadOnly={selectedAgentReadOnly}
        selectedSkillIds={selectedSkillIds}
        skillFolders={skillFolders}
        skillMountFilter={skillMountFilter}
        skillMountFolderFilter={skillMountFolderFilter}
        skillMountSearch={skillMountSearch}
        visibleMountedCount={visibleMountedCount}
        visionModelProfiles={visionModelProfiles}
        onAgentRunGoalChange={onAgentRunGoalChange}
        onDraftChange={onDraftChange}
        onMountVisibleSkills={onMountVisibleSkills}
        onOpenModelProfiles={onOpenModelProfiles}
        onPickAgentAvatar={onPickAgentAvatar}
        onRequestDeleteAgent={onRequestDeleteAgent}
        onRunAgent={onRunAgent}
        onSaveAgent={onSaveAgent}
        onSetSkillMountFilter={onSetSkillMountFilter}
        onSetSkillMountFolderFilter={onSetSkillMountFolderFilter}
        onSetSkillMountSearch={onSetSkillMountSearch}
        onTestAgentModel={onTestAgentModel}
        onToggleSkillMount={onToggleSkillMount}
        onUnmountVisibleSkills={onUnmountVisibleSkills}
      />
    </section>
  );
}
