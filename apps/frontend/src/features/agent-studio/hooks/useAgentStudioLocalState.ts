import { useState } from 'react';
import type { Edge, Node } from '@xyflow/react';
import {
  useEdgesState,
  useNodesState,
} from '@xyflow/react';

import type { ModelProfile, ModelProfileDefaults } from '../../../lib/modelProfiles';
import type {
  AgentDraft,
  FutureTaskSpec,
  MemorySpec,
  RunnableSummary,
  RunGroupSpec,
  RunSpec,
  SkillFolderSpec,
  SkillSourceRoot,
  SkillSpec,
} from '../types';
import type { RunArtifactPreview } from '../components/runDetailTypes';
import type { RunKindFilter, RunStatusFilter } from '../utils/runs';
import type { SkillFolderFilter, SkillImportResult, SkillSourceFilter } from '../utils/skills';
import { starterNodes } from '../utils/workflow';

export const emptyAgentDraft: AgentDraft = {
  name: '',
  nickname: '',
  description: '',
  avatar_url: '',
  category: 'custom',
  instructions: '',
  persona_prompt: '',
  model_mode: 'profile',
  model_profile_id: '',
  vision_model_profile_id: '',
  base_url: '',
  model: '',
  api_key: '',
  output_contract: 'chat',
  allow_workspace_read: false,
  allow_workspace_write: false,
  allow_terminal: false,
  allow_artifacts: true,
  allow_screen_context: true,
  allow_app_control: true,
  allow_media_control: true,
  allow_foreground_input: false,
  allow_browser_control: true,
  default_workdir: '',
  readable_scopes: '.',
  writable_scopes: '',
  enabled: true,
};

export function useAgentStudioLocalState() {
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [modelDefaults, setModelDefaults] = useState<ModelProfileDefaults>({});
  const [runnables, setRunnables] = useState<RunnableSummary[]>([]);
  const [runs, setRuns] = useState<RunSpec[]>([]);
  const [runGroups, setRunGroups] = useState<RunGroupSpec[]>([]);
  const [memories, setMemories] = useState<MemorySpec[]>([]);
  const [futureTasks, setFutureTasks] = useState<FutureTaskSpec[]>([]);
  const [runDetailCache, setRunDetailCache] = useState<RunSpec[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [skillManagementMode, setSkillManagementMode] = useState(false);
  const [draft, setDraft] = useState<AgentDraft>(emptyAgentDraft);
  const [skillSources, setSkillSources] = useState<SkillSourceRoot[]>([]);
  const [skillFolders, setSkillFolders] = useState<SkillFolderSpec[]>([]);
  const [newSkillFolderName, setNewSkillFolderName] = useState('');
  const [editingSkillFolderId, setEditingSkillFolderId] = useState('');
  const [editingSkillFolderName, setEditingSkillFolderName] = useState('');
  const [skillFolderDeleteModes, setSkillFolderDeleteModes] = useState<Record<string, 'folder' | 'skills'>>({});
  const [skillTargetFolderId, setSkillTargetFolderId] = useState('');
  const [skillInstallCommand, setSkillInstallCommand] = useState('');
  const [skillImportResults, setSkillImportResults] = useState<SkillImportResult[]>([]);
  const [skillLibraryFilter, setSkillLibraryFilter] = useState<SkillSourceFilter>('installed');
  const [skillLibraryFolderFilter, setSkillLibraryFolderFilter] = useState<SkillFolderFilter>('all');
  const [skillLibrarySearch, setSkillLibrarySearch] = useState('');
  const [skillMountFilter, setSkillMountFilter] = useState<SkillSourceFilter>('installed');
  const [skillMountFolderFilter, setSkillMountFolderFilter] = useState<SkillFolderFilter>('all');
  const [skillMountSearch, setSkillMountSearch] = useState('');
  const [workflowName, setWorkflowName] = useState('New Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [workflowEnabled, setWorkflowEnabled] = useState(true);
  const [agentRunGoal, setAgentRunGoal] = useState('');
  const [workflowRunGoal, setWorkflowRunGoal] = useState('');
  const [runKindFilter, setRunKindFilter] = useState<RunKindFilter>('all');
  const [runStatusFilter, setRunStatusFilter] = useState<RunStatusFilter>('all');
  const [runSearchQuery, setRunSearchQuery] = useState('');
  const [collapsedRunHistoryGroups, setCollapsedRunHistoryGroups] = useState<Set<string>>(new Set());
  const [artifactPreview, setArtifactPreview] = useState<RunArtifactPreview | null>(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(starterNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  return {
    agentRunGoal,
    artifactPreview,
    busyAction,
    collapsedRunHistoryGroups,
    draft,
    editingSkillFolderId,
    editingSkillFolderName,
    edges,
    error,
    futureTasks,
    loading,
    memories,
    modelDefaults,
    modelProfiles,
    newSkillFolderName,
    nodes,
    onEdgesChange,
    onNodesChange,
    runDetailCache,
    runGroups,
    runKindFilter,
    runSearchQuery,
    runStatusFilter,
    runnables,
    runs,
    selectedSkillIds,
    setAgentRunGoal,
    setArtifactPreview,
    setBusyAction,
    setCollapsedRunHistoryGroups,
    setDraft,
    setEditingSkillFolderId,
    setEditingSkillFolderName,
    setEdges,
    setError,
    setFutureTasks,
    setLoading,
    setMemories,
    setModelDefaults,
    setModelProfiles,
    setNewSkillFolderName,
    setNodes,
    setRunDetailCache,
    setRunGroups,
    setRunKindFilter,
    setRunSearchQuery,
    setRunStatusFilter,
    setRunnables,
    setRuns,
    setSelectedSkillIds,
    setSkillFolderDeleteModes,
    setSkillFolders,
    setSkillImportResults,
    setSkillInstallCommand,
    setSkillLibraryFilter,
    setSkillLibraryFolderFilter,
    setSkillLibrarySearch,
    setSkillManagementMode,
    setSkillMountFilter,
    setSkillMountFolderFilter,
    setSkillMountSearch,
    setSkillSources,
    setSkillTargetFolderId,
    setSkills,
    setStatus,
    setWorkflowDescription,
    setWorkflowEnabled,
    setWorkflowName,
    setWorkflowRunGoal,
    skillFolderDeleteModes,
    skillFolders,
    skillImportResults,
    skillInstallCommand,
    skillLibraryFilter,
    skillLibraryFolderFilter,
    skillLibrarySearch,
    skillManagementMode,
    skillMountFilter,
    skillMountFolderFilter,
    skillMountSearch,
    skillSources,
    skillTargetFolderId,
    skills,
    status,
    workflowDescription,
    workflowEnabled,
    workflowName,
    workflowRunGoal,
  };
}
