import type { AgentSpec } from '../types';
import { saveYachiyoStudioAgent } from '../../yachiyo-studio/api';
import type { AgentDraft } from '../types';
import {
  agentToDraft,
  draftToolPolicy,
  publicAgentToAgentSpec,
  textToScopes,
} from '../utils/agents';

type AgentSaveRefreshOptions = {
  selectedAgentId?: string;
};

type UseAgentSaveActionsOptions = {
  draft: AgentDraft;
  selectedAgentId: string;
  selectedAgentReadOnly: boolean;
  setDraft: (draft: AgentDraft) => void;
  setSelectedAgentId: (agentId: string) => void;
  setStatus: (message: string) => void;
};

export function useAgentSaveActions({
  draft,
  selectedAgentId,
  selectedAgentReadOnly,
  setDraft,
  setSelectedAgentId,
  setStatus,
}: UseAgentSaveActionsOptions) {
  async function saveAgent(): Promise<AgentSaveRefreshOptions> {
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改。');
      return { selectedAgentId };
    }
    const request: Partial<AgentSpec> = {
      name: draft.name,
      nickname: draft.nickname,
      description: draft.description,
      avatar_url: draft.avatar_url,
      category: draft.category,
      instructions: draft.instructions,
      persona_prompt: draft.persona_prompt,
      model_mode: draft.model_mode,
      model_profile_id: draft.model_mode === 'profile' ? draft.model_profile_id : '',
      vision_model_profile_id: draft.vision_model_profile_id,
      tool_policy: draftToolPolicy(draft),
      workspace_policy: {
        default_workdir: draft.default_workdir,
        readable_scopes: textToScopes(draft.readable_scopes),
        writable_scopes: textToScopes(draft.writable_scopes),
      },
      output_contract: draft.output_contract,
      enabled: draft.enabled,
    };
    if (draft.model_mode === 'custom_api') {
      request.model_config = {
        provider: 'openai_compatible',
        base_url: draft.base_url,
        model: draft.model,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      };
    }
    const saved = publicAgentToAgentSpec(await saveYachiyoStudioAgent(
      draft.agent_id ? { ...request, agent_id: draft.agent_id } : request,
    ));
    setSelectedAgentId(saved.agent_id);
    setDraft(agentToDraft(saved));
    return { selectedAgentId: saved.agent_id };
  }

  return {
    saveAgent,
  };
}
