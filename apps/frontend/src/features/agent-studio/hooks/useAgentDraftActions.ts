import { useCallback, type Dispatch, type SetStateAction } from 'react';

import type { AgentDraft } from '../types';

type UseAgentDraftActionsOptions = {
  emptyAgentDraft: AgentDraft;
  setDraft: Dispatch<SetStateAction<AgentDraft>>;
  setError: (message: string) => void;
  setSelectedAgentId: (agentId: string) => void;
  setStatus: (message: string) => void;
};

export function useAgentDraftActions({
  emptyAgentDraft,
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
  }, [setError, setSelectedAgentId, setStatus]);

  return {
    resetAgentDraft,
    selectAgent,
    startNewAgent,
  };
}
