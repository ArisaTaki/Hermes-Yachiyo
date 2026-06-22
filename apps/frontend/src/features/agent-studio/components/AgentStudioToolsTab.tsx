import { useEffect, useMemo, useState } from 'react';

import type { ToolCatalogItemSnapshot, ToolCatalogSnapshot } from '../../yachiyo-studio/types';

type RiskFilter = 'all' | 'low' | 'medium' | 'high' | 'unknown';

const emptyCatalog: ToolCatalogSnapshot = {
  tools: [],
  capabilities: {},
};

type AgentStudioToolsTabProps = {
  catalog: ToolCatalogSnapshot | null;
  error: string;
  loading: boolean;
  onReload: () => void;
};

export function AgentStudioToolsTab({
  catalog: rawCatalog,
  error,
  loading,
  onReload,
}: AgentStudioToolsTabProps) {
  const catalog = rawCatalog || emptyCatalog;
  const [selectedToolName, setSelectedToolName] = useState('');
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [capabilityFilter, setCapabilityFilter] = useState('all');

  useEffect(() => {
    const tools = catalog.tools || [];
    setSelectedToolName((current) => (
      tools.some((tool) => tool.tool_name === current) ? current : tools[0]?.tool_name || ''
    ));
  }, [catalog.tools]);

  const capabilityOptions = useMemo(() => {
    const ids = new Set<string>();
    Object.keys(catalog.capabilities || {}).forEach((capabilityId) => ids.add(capabilityId));
    catalog.tools.forEach((tool) => {
      if (tool.capability_id) ids.add(tool.capability_id);
    });
    return Array.from(ids).sort();
  }, [catalog]);

  const filteredTools = useMemo(() => {
    const query = search.trim().toLowerCase();
    return catalog.tools.filter((tool) => {
      const risk = normalizedRisk(tool);
      if (riskFilter !== 'all' && risk !== riskFilter) return false;
      if (capabilityFilter !== 'all' && tool.capability_id !== capabilityFilter) return false;
      if (!query) return true;
      return [
        tool.tool_name,
        tool.function_name,
        tool.description,
        tool.capability_id || '',
      ].some((value) => String(value || '').toLowerCase().includes(query));
    });
  }, [capabilityFilter, catalog.tools, riskFilter, search]);

  const selectedTool = useMemo(() => {
    return catalog.tools.find((tool) => tool.tool_name === selectedToolName) || filteredTools[0] || null;
  }, [catalog.tools, filteredTools, selectedToolName]);

  return (
    <section className="agent-studio-grid agent-studio-tools-grid" data-testid="agent-studio-tools-tab">
      <aside className="agent-studio-panel studio-tool-list-panel">
        <div className="section-heading-row">
          <div>
            <h2>Tools</h2>
            <span>{filteredTools.length} / {catalog.tools.length}</span>
          </div>
          <button
            type="button"
            className="hy-btn hy-btn-ghost"
            disabled={loading}
            onClick={onReload}
          >
            刷新
          </button>
        </div>

        <div className="studio-tool-filters">
          <label>
            <span>Search</span>
            <input
              className="hy-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label>
            <span>Risk</span>
            <select
              className="hy-select"
              value={riskFilter}
              onChange={(event) => setRiskFilter(event.target.value as RiskFilter)}
            >
              <option value="all">All</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          <label>
            <span>Capability</span>
            <select
              className="hy-select"
              value={capabilityFilter}
              onChange={(event) => setCapabilityFilter(event.target.value)}
            >
              <option value="all">All</option>
              {capabilityOptions.map((capabilityId) => (
                <option key={capabilityId} value={capabilityId}>{capabilityLabel(capabilityId)}</option>
              ))}
            </select>
          </label>
        </div>

        {error ? <div className="notice danger">{error}</div> : null}
        <div className="studio-tool-list" data-testid="agent-studio-tool-list">
          {filteredTools.map((tool) => (
            <button
              type="button"
              key={tool.tool_name}
              className={tool.tool_name === selectedTool?.tool_name ? 'studio-tool-item active' : 'studio-tool-item'}
              aria-pressed={tool.tool_name === selectedTool?.tool_name}
              onClick={() => setSelectedToolName(tool.tool_name)}
            >
              <span>
                <strong>{tool.tool_name}</strong>
                <small>{capabilityLabel(tool.capability_id || '')}</small>
              </span>
              <span className={`studio-tool-risk ${normalizedRisk(tool)}`}>{riskLabel(tool)}</span>
            </button>
          ))}
          {!filteredTools.length ? <span className="studio-tool-empty">No tools</span> : null}
        </div>
      </aside>

      <div className="agent-studio-panel studio-tool-detail" data-testid="agent-studio-tool-detail">
        {selectedTool ? <ToolDetail tool={selectedTool} catalog={catalog} /> : null}
        {!selectedTool && !loading ? <span className="studio-tool-empty">No tool selected</span> : null}
        {loading ? <span className="studio-tool-empty">Loading tools</span> : null}
      </div>
    </section>
  );
}

function ToolDetail({
  catalog,
  tool,
}: {
  catalog: ToolCatalogSnapshot;
  tool: ToolCatalogItemSnapshot;
}) {
  const capability = tool.capability_id ? catalog.capabilities?.[tool.capability_id] : undefined;
  const inputSchema = toolInputSchema(tool);
  const schemaProperties = schemaPropertyRows(inputSchema);
  const missingPermissions = tool.missing_permissions || [];
  const fallbackNotes = tool.fallback_notes || [];
  const diagnosticRoute = tool.diagnostic_route || capability?.diagnostic_route || '';
  const modelFunctionName = modelToolFunctionName(tool) || tool.function_name;
  return (
    <>
      <div className="section-heading-row">
        <div>
          <h2>{tool.tool_name}</h2>
          <span>{modelFunctionName}</span>
        </div>
        <span className={`studio-tool-risk ${normalizedRisk(tool)}`}>{riskLabel(tool)}</span>
      </div>

      <div className="studio-tool-detail-grid">
        <span data-testid="studio-tool-risk-detail">
          <small>Risk</small>
          <strong>{riskLabel(tool)}</strong>
        </span>
        <span>
          <small>Capability</small>
          <strong>{capabilityLabel(tool.capability_id || '')}</strong>
        </span>
        <span>
          <small>Approval</small>
          <strong>{tool.approval_required ? 'Required' : 'Not required'}</strong>
        </span>
        <span>
          <small>Diagnostic</small>
          <strong data-testid="studio-tool-diagnostic-route">{diagnosticRoute || 'None'}</strong>
        </span>
        <span>
          <small>Source</small>
          <strong>{tool.source || 'runtime'}</strong>
        </span>
        <span>
          <small>Function</small>
          <strong>{tool.function_name}</strong>
        </span>
      </div>

      {tool.description ? <p className="studio-tool-description">{tool.description}</p> : null}

      <div className="studio-tool-inspector-section" data-testid="studio-tool-permissions">
        <div className="studio-tool-inspector-heading">
          <h3>Permissions</h3>
          <span>{missingPermissions.length ? 'Missing requirements' : 'Ready'}</span>
        </div>
        <div className="studio-tool-pill-row">
          {missingPermissions.map((permission) => (
            <span className="studio-tool-permission missing" key={permission}>{permission}</span>
          ))}
          {!missingPermissions.length ? (
            <span className="studio-tool-permission">permissions ready</span>
          ) : null}
        </div>
      </div>

      <div className="studio-tool-inspector-section" data-testid="studio-tool-fallback-notes">
        <div className="studio-tool-inspector-heading">
          <h3>Fallback</h3>
          <span>{fallbackNotes.length ? 'Runtime fallback path' : 'No fallback registered'}</span>
        </div>
        <div className="studio-tool-note-list">
          {fallbackNotes.map((note) => <span key={note}>{note}</span>)}
          {!fallbackNotes.length ? <span>No fallback registered for this tool.</span> : null}
        </div>
      </div>

      <div className="studio-tool-inspector-section" data-testid="studio-tool-schema-properties">
        <div className="studio-tool-inspector-heading">
          <h3>Schema Properties</h3>
          <span>{schemaProperties.length} parameters</span>
        </div>
        {schemaProperties.length ? (
          <div className="studio-tool-schema-property-list">
            {schemaProperties.map((property) => (
              <div className="studio-tool-schema-property" key={property.name}>
                <div>
                  <strong>{property.name}</strong>
                  {property.required ? <small>required</small> : null}
                </div>
                <span>{property.type}</span>
                {property.description ? <p>{property.description}</p> : null}
              </div>
            ))}
          </div>
        ) : (
          <span className="studio-tool-empty">No input properties</span>
        )}
      </div>

      <details className="run-detail-block run-detail-fold studio-tool-schema" data-testid="studio-tool-input-schema" open>
        <summary className="run-detail-section-head">
          <div>
            <h4>Input Schema</h4>
            <span>Model parameters</span>
          </div>
        </summary>
        <pre>{JSON.stringify(inputSchema, null, 2)}</pre>
      </details>

      <details className="run-detail-block run-detail-fold studio-tool-schema" data-testid="studio-tool-model-schema">
        <summary className="run-detail-section-head">
          <div>
            <h4>Model Tool Schema</h4>
            <span>{modelFunctionName}</span>
          </div>
        </summary>
        <pre>{JSON.stringify(tool.model_tool_schema || {}, null, 2)}</pre>
      </details>
    </>
  );
}

function normalizedRisk(tool: ToolCatalogItemSnapshot): RiskFilter {
  const risk = String(tool.risk_level || '').trim().toLowerCase();
  if (risk === 'low' || risk === 'medium' || risk === 'high') return risk;
  return 'unknown';
}

function riskLabel(tool: ToolCatalogItemSnapshot): string {
  const risk = normalizedRisk(tool);
  if (risk === 'unknown') return 'unknown';
  return risk;
}

function capabilityLabel(value: string): string {
  if (!value) return 'Unscoped';
  return value.replace(/_/g, ' ');
}

type SchemaPropertyRow = {
  name: string;
  type: string;
  description: string;
  required: boolean;
};

function toolInputSchema(tool: ToolCatalogItemSnapshot): Record<string, unknown> {
  const directSchema = objectRecord(tool.input_schema);
  if (Object.keys(directSchema).length) return directSchema;
  const modelSchema = objectRecord(tool.model_tool_schema);
  const functionSchema = objectRecord(modelSchema.function);
  return objectRecord(functionSchema.parameters);
}

function modelToolFunctionName(tool: ToolCatalogItemSnapshot): string {
  const modelSchema = objectRecord(tool.model_tool_schema);
  const functionSchema = objectRecord(modelSchema.function);
  return typeof functionSchema.name === 'string' ? functionSchema.name : '';
}

function schemaPropertyRows(schema: Record<string, unknown>): SchemaPropertyRow[] {
  const properties = objectRecord(schema.properties);
  const required = new Set(stringArray(schema.required));
  return Object.entries(properties).map(([name, value]) => {
    const property = objectRecord(value);
    return {
      name,
      type: schemaPropertyType(property),
      description: typeof property.description === 'string' ? property.description : '',
      required: required.has(name),
    };
  });
}

function schemaPropertyType(property: Record<string, unknown>): string {
  const typeValue = property.type;
  if (typeof typeValue === 'string' && typeValue.trim()) return typeValue;
  if (Array.isArray(typeValue)) {
    const types = stringArray(typeValue);
    if (types.length) return types.join(' | ');
  }
  const anyOfTypes = Array.isArray(property.anyOf)
    ? property.anyOf
      .map((item) => objectRecord(item).type)
      .flatMap((item) => stringArray(Array.isArray(item) ? item : [item]))
    : [];
  if (anyOfTypes.length) return Array.from(new Set(anyOfTypes)).join(' | ');
  if (Array.isArray(property.enum) && property.enum.length) return `enum(${property.enum.length})`;
  return 'unknown';
}

function objectRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}
