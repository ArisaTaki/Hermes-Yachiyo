import type { Dispatch, SetStateAction } from 'react';

import { chooseAvatarImage } from '../../../lib/bridge';
import type { AgentDraft } from '../types';

type UseAgentAvatarActionsOptions = {
  setBusyAction: (label: string) => void;
  setDraft: Dispatch<SetStateAction<AgentDraft>>;
  setError: (message: string) => void;
  setStatus: (message: string) => void;
};

export function useAgentAvatarActions({
  setBusyAction,
  setDraft,
  setError,
  setStatus,
}: UseAgentAvatarActionsOptions) {
  async function pickAgentAvatar() {
    setBusyAction('选择 Agent 头像');
    setError('');
    try {
      const selection = await chooseAvatarImage();
      const avatar = typeof selection === 'string' ? selection : selection?.data_url || selection?.path || '';
      if (avatar) {
        setDraft((current) => ({ ...current, avatar_url: avatar }));
        setStatus('已选择 Agent 头像');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Agent 头像失败');
    } finally {
      setBusyAction('');
    }
  }

  return {
    pickAgentAvatar,
  };
}
