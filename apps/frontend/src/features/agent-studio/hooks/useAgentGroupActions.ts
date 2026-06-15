import { useCallback } from 'react';

import type { StudioRefreshOptions } from './useAgentStudioRefresh';
import type { AgentGroupRunResult } from './useAgentGroups';

type SaveAgentGroupDraftResult = {
  statusMessage: string;
};

type UseAgentGroupActionsOptions = {
  openRunDetail: (runId: string, options?: { revealInHistory?: boolean }) => void;
  runAgentGroup: () => Promise<AgentGroupRunResult>;
  saveAgentGroupDraft: () => Promise<SaveAgentGroupDraftResult>;
  selectedAgentGroupId: string;
  setRunTarget: (runTarget: string) => void;
};

export function useAgentGroupActions({
  openRunDetail,
  runAgentGroup,
  saveAgentGroupDraft,
  selectedAgentGroupId,
  setRunTarget,
}: UseAgentGroupActionsOptions) {
  const saveAgentGroup = useCallback(async (): Promise<StudioRefreshOptions> => {
    const { statusMessage } = await saveAgentGroupDraft();
    return { statusMessage };
  }, [saveAgentGroupDraft]);

  const runCurrentAgentGroup = useCallback(async (): Promise<StudioRefreshOptions> => {
    const { runId, statusMessage } = await runAgentGroup();
    if (runId) {
      setRunTarget(selectedAgentGroupId.trim());
      openRunDetail(runId, { revealInHistory: true });
    }
    return {
      selectedRunId: runId || undefined,
      statusMessage,
    };
  }, [openRunDetail, runAgentGroup, selectedAgentGroupId, setRunTarget]);

  return {
    runCurrentAgentGroup,
    saveAgentGroup,
  };
}
