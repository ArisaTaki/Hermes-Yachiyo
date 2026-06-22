import { useEffect, useMemo, useState } from 'react';

import { getYachiyoStudioToolCatalog } from '../../yachiyo-studio/api';
import type { ToolCatalogItemSnapshot, ToolCatalogSnapshot } from '../../yachiyo-studio/types';

type RiskFilter = 'all' | 'low' | 'medium' | 'high' | 'unknown';

const emptyCatalog: ToolCatalogSnapshot = {
  tools: [],
  capabilities: {},
};

export function AgentStudioToolsTab() {
  const [catalog, setCatalog] = useState<ToolCatalogSnapshot>(emptyCatalog);
  const [selectedToolName, setSelectedToolName] = useState('');
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [capabilityFilter, setCapabilityFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function loadCatalog() {
    setLoading(true);
    setError('');
    try {
      const nextCatalog = await getYachiyoStudioToolCatalog();
      setCatalog(nextCatalog);
      const tools = nextCatalog.tools || [];
      setSelectedToolName((current) => (
        tools.some((tool) => tool.tool_name === current) ? current : tools[0]?.tool_name || ''
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Tool catalog unavailable');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

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
            onClick={() => void loadCatalog()}
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
  return (
    <>
      <div className="section-heading-row">
        <div>
          <h2>{tool.tool_name}</h2>
          <span>{tool.function_name}</span>
        </div>
        <span className={`studio-tool-risk ${normalizedRisk(tool)}`}>{riskLabel(tool)}</span>
      </div>

      <div className="studio-tool-detail-grid">
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
          <strong>{tool.diagnostic_route || capability?.diagnostic_route || 'None'}</strong>
        </span>
        <span>
          <small>Source</small>
          <strong>{tool.source || 'runtime'}</strong>
        </span>
      </div>

      {tool.description ? <p className="studio-tool-description">{tool.description}</p> : null}

      <div className="studio-tool-pill-row">
        {(tool.missing_permissions || []).map((permission) => (
          <span className="studio-tool-permission missing" key={permission}>{permission}</span>
        ))}
        {!(tool.missing_permissions || []).length ? (
          <span className="studio-tool-permission">permissions ready</span>
        ) : null}
      </div>

      {(tool.fallback_notes || []).length ? (
        <div className="studio-tool-note-list">
          {tool.fallback_notes?.map((note) => <span key={note}>{note}</span>)}
        </div>
      ) : null}

      <details className="run-detail-block run-detail-fold studio-tool-schema" open>
        <summary className="run-detail-section-head">
          <div>
            <h4>Input Schema</h4>
            <span>Model parameters</span>
          </div>
        </summary>
        <pre>{JSON.stringify(tool.input_schema || {}, null, 2)}</pre>
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
