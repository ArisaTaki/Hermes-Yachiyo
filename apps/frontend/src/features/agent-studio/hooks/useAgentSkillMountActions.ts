import {
  attachSkill,
  detachSkill,
  updateAgent,
  type AgentSpec,
  type SkillSpec,
} from '../../../lib/agents';

type AgentSkillMountRefreshOptions = {
  selectedAgentId?: string;
  statusMessage?: string;
};

type UseAgentSkillMountActionsOptions = {
  draftAgentId: string;
  runAction: (action: () => Promise<AgentSkillMountRefreshOptions | void>, label: string) => void;
  selectedAgent: AgentSpec | null;
  selectedAgentReadOnly: boolean;
  setStatus: (message: string) => void;
  visibleMountSkillIds: string[];
};

export function useAgentSkillMountActions({
  draftAgentId,
  runAction,
  selectedAgent,
  selectedAgentReadOnly,
  setStatus,
  visibleMountSkillIds,
}: UseAgentSkillMountActionsOptions) {
  async function mountVisibleSkills(): Promise<AgentSkillMountRefreshOptions | void> {
    if (!draftAgentId || !selectedAgent) return;
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
      return;
    }
    const nextSkillIds = Array.from(new Set([...(selectedAgent.skill_ids || []), ...visibleMountSkillIds]));
    await updateAgent(draftAgentId, { skill_ids: nextSkillIds });
  }

  async function unmountVisibleSkills(): Promise<AgentSkillMountRefreshOptions | void> {
    if (!draftAgentId || !selectedAgent) return;
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
      return;
    }
    const visible = new Set(visibleMountSkillIds);
    const nextSkillIds = (selectedAgent.skill_ids || []).filter((skillId) => !visible.has(skillId));
    await updateAgent(draftAgentId, { skill_ids: nextSkillIds });
  }

  function toggleAgentSkillMount(skill: SkillSpec, mounted: boolean) {
    void runAction(async () => {
      if (!draftAgentId) return;
      if (selectedAgentReadOnly) {
        setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
        return;
      }
      if (mounted) await detachSkill(draftAgentId, skill.skill_id);
      else await attachSkill(draftAgentId, skill.skill_id);
    }, mounted ? '移除 Skill' : '挂载 Skill');
  }

  return {
    mountVisibleSkills,
    toggleAgentSkillMount,
    unmountVisibleSkills,
  };
}
