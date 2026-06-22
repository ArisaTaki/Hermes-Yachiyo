import type { AgentDraft } from '../types';
import type { ToolCatalogItemSnapshot, ToolCatalogSnapshot } from '../../yachiyo-studio/types';
import {
  appControlTools,
  browserControlTools,
  foregroundInputTools,
  mediaControlTools,
  screenContextTools,
} from './agents';

export type AgentToolCapabilitySummary = {
  id: string;
  label: string;
  enabled: boolean;
  tools: string[];
  catalogTools: ToolCatalogItemSnapshot[];
  missingPermissions: string[];
  fallbackNotes: string[];
  diagnosticRoutes: string[];
  riskLevel: 'low' | 'medium' | 'high' | 'unknown';
  approvalRequired: boolean;
};

type AgentToolCapabilityDefinition = {
  id: string;
  label: string;
  tools: string[];
  enabled: (draft: AgentDraft) => boolean;
};

const workspaceReadTools = ['workspace.list', 'workspace.read'];
const workspaceWriteTools = ['workspace.write_patch'];
const terminalTools = ['terminal.run'];
const artifactTools = ['artifact.write'];

const capabilityDefinitions: AgentToolCapabilityDefinition[] = [
  {
    id: 'screen_context',
    label: 'Screen',
    tools: screenContextTools,
    enabled: (draft) => draft.allow_screen_context,
  },
  {
    id: 'app_control',
    label: 'App Control',
    tools: appControlTools,
    enabled: (draft) => draft.allow_app_control,
  },
  {
    id: 'media_control',
    label: 'Media',
    tools: mediaControlTools,
    enabled: (draft) => draft.allow_media_control,
  },
  {
    id: 'foreground_input',
    label: 'Foreground Input',
    tools: foregroundInputTools,
    enabled: (draft) => draft.allow_foreground_input,
  },
  {
    id: 'browser_control',
    label: 'Browser',
    tools: browserControlTools,
    enabled: (draft) => draft.allow_browser_control,
  },
  {
    id: 'workspace_read',
    label: 'Read workspace',
    tools: workspaceReadTools,
    enabled: (draft) => draft.allow_workspace_read,
  },
  {
    id: 'workspace_write',
    label: 'Write files',
    tools: workspaceWriteTools,
    enabled: (draft) => draft.allow_workspace_write,
  },
  {
    id: 'terminal',
    label: 'Terminal',
    tools: terminalTools,
    enabled: (draft) => draft.allow_terminal,
  },
  {
    id: 'artifacts',
    label: 'Write artifacts',
    tools: artifactTools,
    enabled: (draft) => draft.allow_artifacts,
  },
];

const riskRank = {
  unknown: 0,
  low: 1,
  medium: 2,
  high: 3,
} as const;

export function agentToolCapabilitySummaries(
  draft: AgentDraft,
  catalog: ToolCatalogSnapshot | null | undefined,
): AgentToolCapabilitySummary[] {
  const toolByName = new Map((catalog?.tools || []).map((tool) => [tool.tool_name, tool]));
  return capabilityDefinitions.map((definition) => {
    const catalogTools = definition.tools
      .map((toolName) => toolByName.get(toolName))
      .filter((tool): tool is ToolCatalogItemSnapshot => Boolean(tool));
    return {
      id: definition.id,
      label: definition.label,
      enabled: definition.enabled(draft),
      tools: definition.tools,
      catalogTools,
      missingPermissions: unique(
        catalogTools.flatMap((tool) => tool.missing_permissions || []),
      ),
      fallbackNotes: unique(
        catalogTools.flatMap((tool) => tool.fallback_notes || []),
      ),
      diagnosticRoutes: unique(
        catalogTools.map((tool) => tool.diagnostic_route || '').filter(Boolean),
      ),
      riskLevel: highestRisk(catalogTools),
      approvalRequired: catalogTools.some((tool) => tool.approval_required),
    };
  });
}

export function enabledCapabilityPermissionNotices(
  summaries: AgentToolCapabilitySummary[],
): string[] {
  return summaries
    .filter((summary) => summary.enabled && summary.missingPermissions.length)
    .map((summary) => `${summary.label}: ${summary.missingPermissions.join(', ')}`);
}

function highestRisk(tools: ToolCatalogItemSnapshot[]): AgentToolCapabilitySummary['riskLevel'] {
  return tools.reduce<AgentToolCapabilitySummary['riskLevel']>((highest, tool) => {
    const next = normalizedRisk(tool.risk_level);
    return riskRank[next] > riskRank[highest] ? next : highest;
  }, 'unknown');
}

function normalizedRisk(value: unknown): AgentToolCapabilitySummary['riskLevel'] {
  const risk = String(value || '').trim().toLowerCase();
  if (risk === 'low' || risk === 'medium' || risk === 'high') return risk;
  return 'unknown';
}

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  values.forEach((value) => {
    const clean = String(value || '').trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    result.push(clean);
  });
  return result;
}
