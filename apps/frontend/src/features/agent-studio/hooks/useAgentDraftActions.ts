import { useCallback, type Dispatch, type SetStateAction } from 'react';

import type { AgentDraft, AgentSpec } from '../types';
import { getStudioAgentForView } from '../utils/studioData';

type UseAgentDraftActionsOptions = {
  emptyAgentDraft: AgentDraft;
  mergeAgent: (agent: AgentSpec) => void;
  setDraft: Dispatch<SetStateAction<AgentDraft>>;
  setError: (message: string) => void;
  setSelectedAgentId: (agentId: string) => void;
  setStatus: (message: string) => void;
};

export function useAgentDraftActions({
  emptyAgentDraft,
  mergeAgent,
  setDraft,
  setError,
  setSelectedAgentId,
  setStatus,
}: UseAgentDraftActionsOptions) {
  const resetAgentDraft = useCallback(() => {
    setDraft({ ...emptyAgentDraft });
  }, [emptyAgentDraft, setDraft]);

  const startNewAgent = useCallback(() => {
    setSelectedAgentId('');
    resetAgentDraft();
    setStatus('正在编辑新的 Agent 草稿');
    setError('');
  }, [resetAgentDraft, setError, setSelectedAgentId, setStatus]);

  const selectAgent = useCallback((agentId: string) => {
    setSelectedAgentId(agentId);
    setStatus('');
    setError('');
    void getStudioAgentForView(agentId)
      .then((agent) => {
        mergeAgent(agent);
      })
      .catch(() => {
        setStatus('读取 Agent 详情失败，已使用列表快照。');
      });
  }, [mergeAgent, setError, setSelectedAgentId, setStatus]);

  return {
    resetAgentDraft,
    selectAgent,
    startNewAgent,
  };
}
