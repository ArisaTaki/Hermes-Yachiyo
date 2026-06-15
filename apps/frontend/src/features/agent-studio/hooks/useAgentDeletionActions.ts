import type { Dispatch, SetStateAction } from 'react';

import type { AgentSpec } from '../../../lib/agents';
import { deleteYachiyoStudioAgent } from '../../yachiyo-studio/api';

type AgentDeletionRefreshOptions = {
  selectedAgentId?: string;
};

type ConfirmDialogRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type UseAgentDeletionActionsOptions = {
  draftAgentId: string;
  draftAgentName: string;
  resetAgentDraft: () => void;
  runAction: (action: () => Promise<AgentDeletionRefreshOptions | void>, label: string) => void;
  selectedAgentDeletable: boolean;
  selectedAgentId: string;
  selectedAgentName: string;
  selectedDeletableAgents: AgentSpec[];
  setSelectedAgentId: (agentId: string) => void;
  setSelectedAgentIds: Dispatch<SetStateAction<string[]>>;
  setStatus: (message: string) => void;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
};

export function useAgentDeletionActions({
  draftAgentId,
  draftAgentName,
  resetAgentDraft,
  runAction,
  selectedAgentDeletable,
  selectedAgentId,
  selectedAgentName,
  selectedDeletableAgents,
  setSelectedAgentId,
  setSelectedAgentIds,
  setStatus,
  showConfirmDialog,
}: UseAgentDeletionActionsOptions) {
  function requestDeleteAgent() {
    if (!draftAgentId) return;
    if (!selectedAgentDeletable) {
      setStatus('系统 Agent 只能查看，不能删除。');
      return;
    }
    const agentId = draftAgentId;
    const agentName = draftAgentName || selectedAgentName || 'Agent';
    showConfirmDialog({
      title: `删除「${agentName}」？`,
      description: '这个 Agent 的定义会从 Agent Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: '删除 Agent',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteYachiyoStudioAgent(agentId);
        setSelectedAgentIds((current) => current.filter((id) => id !== agentId));
        setSelectedAgentId('');
        resetAgentDraft();
        return { selectedAgentId: '' };
      }, '删除 Agent'),
    });
  }

  function requestDeleteSelectedAgents() {
    const targets = selectedDeletableAgents.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((agent) => agent.agent_id));
    const deletingCurrent = Boolean(selectedAgentId && targetIds.has(selectedAgentId));
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Agent？`,
      description: '这些 Agent 的定义会从 Agent Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: `删除 ${targets.length} 个 Agent`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const agent of targets) {
          await deleteYachiyoStudioAgent(agent.agent_id);
        }
        setSelectedAgentIds((current) => current.filter((id) => !targetIds.has(id)));
        if (deletingCurrent) {
          setSelectedAgentId('');
          resetAgentDraft();
          return { selectedAgentId: '' };
        }
        return undefined;
      }, '批量删除 Agent'),
    });
  }

  return {
    requestDeleteAgent,
    requestDeleteSelectedAgents,
  };
}
