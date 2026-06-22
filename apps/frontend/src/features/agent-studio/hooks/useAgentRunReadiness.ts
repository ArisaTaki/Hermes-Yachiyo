import { useMemo } from 'react';

import type { AgentSpec, SkillSpec } from '../types';
import type { ModelProfile } from '../../../lib/modelProfiles';
import type { AgentDraft } from '../types';

export type AgentReadinessNotice = {
  tone: 'danger' | 'warn' | 'info';
  text: string;
};

type UseAgentRunReadinessOptions = {
  agentRunGoal: string;
  busy: boolean;
  chatModelProfiles: ModelProfile[];
  disabledMountedSkills: SkillSpec[];
  draft: AgentDraft;
  selectedAgent: AgentSpec | null;
  selectedAgentReadOnly: boolean;
};

export function useAgentRunReadiness({
  agentRunGoal,
  busy,
  chatModelProfiles,
  disabledMountedSkills,
  draft,
  selectedAgent,
  selectedAgentReadOnly,
}: UseAgentRunReadinessOptions) {
  const agentReadinessNotices = useMemo(() => {
    const notices: AgentReadinessNotice[] = [];
    const selectedProfileAvailable = draft.model_profile_id
      ? chatModelProfiles.some((profile) => profile.profile_id === draft.model_profile_id)
      : false;
    if (draft.model_mode === 'profile') {
      if (!draft.model_profile_id) {
        notices.push({ tone: 'danger', text: '尚未选择 Chat Profile；Agent Run 和 Workflow 节点运行前需要一个可用文本模型。' });
      } else if (!selectedProfileAvailable) {
        notices.push({ tone: 'danger', text: '当前 Chat Profile 不可用或已停用；请重新选择可用 Profile。' });
      }
    } else {
      if (!draft.base_url.trim() || !draft.model.trim()) {
        notices.push({ tone: 'danger', text: 'Custom API 需要 Base URL 和 Model，配置不完整时无法运行。' });
      }
      if (!draft.api_key.trim() && !selectedAgent?.model_config?.api_key_configured) {
        notices.push({ tone: 'danger', text: 'Custom API 尚未保存 API Key；请填写后保存，或切回 Chat Profile。' });
      }
    }
    if (disabledMountedSkills.length) {
      notices.push({ tone: 'danger', text: `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用；运行会被拦截。` });
    }
    if (draft.allow_workspace_write) {
      notices.push({
        tone: 'warn',
        text: draft.writable_scopes.trim()
          ? '`workspace.write_patch` 已启用；每次写文件都会先进入审批。'
          : draft.default_workdir.trim()
            ? '`workspace.write_patch` 已启用但 Writable Scopes 为空；写入会被工作区策略拒绝。'
            : '`workspace.write_patch` 已启用；保存后会自动分配独立工作目录，并允许在该目录内写入。',
      });
    }
    if (draft.allow_terminal) {
      notices.push({ tone: 'warn', text: '`terminal.run` 已启用；每次运行命令都会先进入审批。' });
    }
    if (draft.allow_foreground_input) {
      notices.push({ tone: 'info', text: '前台输入会作用在当前桌面焦点窗口；适合明确的点击后输入或快捷键任务。' });
    }
    if (draft.allow_browser_control) {
      notices.push({ tone: 'info', text: 'Browser/CDP 工具将在下一批执行能力中启用。' });
    }
    const hasTools = draft.allow_workspace_read
      || draft.allow_workspace_write
      || draft.allow_terminal
      || draft.allow_artifacts
      || draft.allow_screen_context
      || draft.allow_app_control
      || draft.allow_media_control
      || draft.allow_foreground_input;
    if (!hasTools) {
      notices.push({ tone: 'info', text: '当前 Agent 只会调用模型，不会获得工作区、桌面执行、命令或 artifact 工具。' });
    }
    return notices;
  }, [
    chatModelProfiles,
    disabledMountedSkills.length,
    draft.allow_app_control,
    draft.allow_artifacts,
    draft.allow_browser_control,
    draft.allow_foreground_input,
    draft.allow_media_control,
    draft.allow_screen_context,
    draft.allow_terminal,
    draft.allow_workspace_read,
    draft.allow_workspace_write,
    draft.api_key,
    draft.base_url,
    draft.default_workdir,
    draft.model,
    draft.model_mode,
    draft.model_profile_id,
    draft.writable_scopes,
    selectedAgent,
  ]);

  const agentQuickRunDisabledReason = useMemo(() => {
    if (!draft.agent_id) return '请先保存 Agent，再运行。';
    if (selectedAgentReadOnly) return '系统 Agent 只能查看，不能从 Agent Studio 直接运行。';
    if (draft.enabled === false || selectedAgent?.enabled === false) return '当前 Agent 已停用，无法运行。';
    if (draft.model_mode === 'profile') {
      if (!draft.model_profile_id) return '请选择可用 Chat Profile 后再运行。';
      if (!chatModelProfiles.some((profile) => profile.profile_id === draft.model_profile_id)) return '当前 Chat Profile 不可用或已停用。';
    } else {
      if (!draft.base_url.trim() || !draft.model.trim()) return 'Custom API 配置不完整，请填写 Base URL 和 Model。';
      if (!draft.api_key.trim() && !selectedAgent?.model_config?.api_key_configured) return 'Custom API 尚未保存 API Key。';
    }
    if (disabledMountedSkills.length) return `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用，请先启用或卸载后再运行。`;
    if (!agentRunGoal.trim()) return '请输入运行目标。';
    return '';
  }, [
    agentRunGoal,
    chatModelProfiles,
    disabledMountedSkills.length,
    draft.agent_id,
    draft.api_key,
    draft.base_url,
    draft.enabled,
    draft.model,
    draft.model_mode,
    draft.model_profile_id,
    selectedAgent,
    selectedAgentReadOnly,
  ]);

  return {
    agentQuickRunDisabled: busy || Boolean(agentQuickRunDisabledReason),
    agentQuickRunDisabledReason,
    agentReadinessNotices,
  };
}
