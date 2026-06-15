import type { AgentDraft } from '../components/AgentEditorPanel';
import type { AgentSpec, RunnableSummary, SkillSpec } from '../../../lib/agents';
import type { ModelProfile, ModelProfileDefaults } from '../../../lib/modelProfiles';

const defaultAgentIds = new Set([
  'agent_yachiyo_orchestrator',
  'agent_coding',
  'agent_design',
  'agent_review',
  'agent_research',
  'agent_office',
  'agent_custom',
]);

export function scopesToText(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value || '');
}

export function textToScopes(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function policyTools(agent: AgentSpec): Set<string> {
  const allowed = agent.tool_policy?.allowed_tools;
  return new Set(Array.isArray(allowed) ? allowed.map((item) => String(item)) : []);
}

export function draftToolPolicy(draft: AgentDraft): Record<string, unknown> {
  const allowed = new Set<string>();
  if (draft.allow_workspace_read) {
    allowed.add('workspace.list');
    allowed.add('workspace.read');
  }
  if (draft.allow_workspace_write) allowed.add('workspace.write_patch');
  if (draft.allow_terminal) allowed.add('terminal.run');
  if (draft.allow_artifacts) allowed.add('artifact.write');
  return {
    allowed_tools: Array.from(allowed),
    approval_required: {
      'terminal.run': true,
      'workspace.write_patch': true,
    },
  };
}

export function agentToDraft(agent: AgentSpec): AgentDraft {
  const workspace = agent.workspace_policy || {};
  const tools = policyTools(agent);
  return {
    agent_id: agent.agent_id,
    name: agent.name,
    nickname: agent.nickname || agent.name,
    description: agent.description || '',
    avatar_url: agent.avatar_url || '',
    category: agent.category || 'custom',
    instructions: agent.instructions || '',
    persona_prompt: agent.persona_prompt || '',
    model_mode: agent.model_mode === 'custom_api' ? 'custom_api' : 'profile',
    model_profile_id: agent.model_profile_id || '',
    vision_model_profile_id: agent.vision_model_profile_id || '',
    base_url: agent.model_config?.base_url || '',
    model: agent.model_config?.model || '',
    api_key: '',
    output_contract: agent.output_contract || 'chat',
    allow_workspace_read: tools.has('workspace.list') || tools.has('workspace.read'),
    allow_workspace_write: tools.has('workspace.write_patch'),
    allow_terminal: tools.has('terminal.run'),
    allow_artifacts: agent.tool_policy?.allowed_tools === undefined ? true : tools.has('artifact.write'),
    default_workdir: String(workspace.default_workdir || ''),
    readable_scopes: scopesToText(workspace.readable_scopes || ['.']),
    writable_scopes: scopesToText(workspace.writable_scopes || []),
    enabled: agent.enabled !== false,
  };
}

export function toolPolicyCapabilityLine(policy: unknown): string {
  if (!policy || typeof policy !== 'object') return '';
  const raw = policy as { allowed_tools?: unknown; approval_required?: unknown };
  const allowedTools = Array.isArray(raw.allowed_tools)
    ? raw.allowed_tools.map((tool) => String(tool || '').trim()).filter(Boolean)
    : [];
  const approvalRequired = raw.approval_required && typeof raw.approval_required === 'object'
    ? raw.approval_required as Record<string, unknown>
    : {};
  const tools = [...allowedTools];
  Object.keys(approvalRequired).forEach((tool) => {
    if (approvalRequired[tool] === true && !tools.includes(tool)) tools.push(tool);
  });
  if (!tools.length) return '';
  const labels: string[] = [];
  const add = (label: string) => {
    if (!labels.includes(label)) labels.push(label);
  };
  const needsApproval = (tool: string) => approvalRequired[tool] === true;
  if (tools.includes('workspace.read') || tools.includes('workspace.list')) add('读文件');
  if (tools.includes('workspace.write_patch')) add(needsApproval('workspace.write_patch') ? '写补丁需审批' : '写补丁');
  if (tools.includes('terminal.run')) add(needsApproval('terminal.run') ? '终端需审批' : '终端');
  if (tools.includes('artifact.write')) add('产物');
  tools.forEach((tool) => {
    if (['workspace.read', 'workspace.list', 'workspace.write_patch', 'terminal.run', 'artifact.write'].includes(tool)) return;
    add(needsApproval(tool) ? `${tool} 需审批` : tool);
  });
  return labels.length ? `工具 ${labels.join('、')}` : '';
}

export function runnableCapabilityLine(item: Pick<RunnableSummary, 'category' | 'description' | 'enabled' | 'kind' | 'output_contract' | 'tool_policy'>): string {
  const parts = [
    item.enabled === false ? '停用' : '',
    item.category ? `类别 ${item.category}` : '',
    item.output_contract ? `交付 ${item.output_contract}` : '',
    item.kind === 'agent' ? toolPolicyCapabilityLine(item.tool_policy) : '',
    item.kind === 'workflow' ? 'Workflow' : '',
  ].filter(Boolean);
  return parts.join(' · ') || (item.kind === 'workflow' ? 'Workflow' : 'Agent');
}

export function runnableOptionLabel(item: RunnableSummary): string {
  return `${item.kind}: ${item.name} · ${runnableCapabilityLine(item)}`;
}

export function agentCapabilityLine(agent: Pick<AgentSpec, 'category' | 'enabled' | 'output_contract' | 'tool_policy'>): string {
  return [
    agent.enabled === false ? '停用' : '',
    agent.category ? `类别 ${agent.category}` : '',
    agent.output_contract ? `交付 ${agent.output_contract}` : '',
    toolPolicyCapabilityLine(agent.tool_policy),
  ].filter(Boolean).join(' · ') || 'Agent';
}

export function agentRunReadinessIssue(
  agent: AgentSpec,
  chatProfiles: ModelProfile[],
  modelDefaults: ModelProfileDefaults,
  skills: SkillSpec[],
): string {
  if (agent.enabled === false) return 'Agent 已停用，无法运行。';
  const disabledMountedSkills = skills.filter((skill) => skill.enabled === false && agent.skill_ids?.includes(skill.skill_id));
  if (disabledMountedSkills.length) return `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用。`;
  if (agent.model_mode === 'custom_api') {
    const config = agent.model_config || {};
    const missing = [
      !String(config.base_url || '').trim() ? 'Base URL' : '',
      !String(config.model || '').trim() ? 'Model' : '',
      !config.api_key_configured ? 'API Key' : '',
    ].filter(Boolean);
    if (missing.length) return `Custom API 配置不完整：缺少 ${missing.join('、')}。`;
    return '';
  }
  if (agent.model_mode === 'follow_main' || defaultAgentIds.has(agent.agent_id || '')) {
    const defaultChatProfileId = String(modelDefaults.chat || '').trim();
    if (!defaultChatProfileId) return '默认 Chat Profile 尚未设置。';
    if (!chatProfiles.some((profile) => profile.profile_id === defaultChatProfileId)) {
      return '默认 Chat Profile 不可用或已停用。';
    }
    return '';
  }
  if (!agent.model_profile_id) return '尚未选择 Chat Profile。';
  if (!chatProfiles.some((profile) => profile.profile_id === agent.model_profile_id)) {
    return '当前 Chat Profile 不可用或已停用。';
  }
  return '';
}
