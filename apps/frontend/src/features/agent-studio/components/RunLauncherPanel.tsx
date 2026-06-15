import type { ReactNode } from 'react';

import type { RunnableSummary, RunSpec } from '../types';
import { RunHistoryList, type RunHistoryGroupView } from './RunHistoryList';

type RunKindFilter = 'all' | 'workflow' | 'agent';
type RunStatusFilter = 'all' | 'completed' | 'failed' | 'active';

type RunLauncherPanelProps = {
  allHistoryRunsSelected: boolean;
  busy: boolean;
  collapsedRunHistoryGroups: Set<string>;
  filteredRunIds: string[];
  filteredRuns: RunSpec[];
  formatRunDate: (value?: string) => string;
  runBulkDeleteDisabledReason: string;
  runFilterCounts: Record<RunKindFilter, number>;
  runGoal: string;
  runHistoryGroupSummary: (runs: RunSpec[]) => string;
  runHistoryGroups: RunHistoryGroupView[];
  runHistoryManagementMode: boolean;
  runKindFilter: RunKindFilter;
  runKindLabel: (kind: string) => string;
  runSearchActive: boolean;
  runSearchQuery: string;
  runStatusFilter: RunStatusFilter;
  runStatusFilterCounts: Record<RunStatusFilter, number>;
  runStatusFilteredRuns: RunSpec[];
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  runTarget: string;
  runTargetDisabledReason: string;
  runTargetWorkflowErrors: string[];
  runnables: RunnableSummary[];
  selectedHistoryRunCount: number;
  selectedRunId: string;
  selectedRunIdSet: Set<string>;
  selectedRunTarget: RunnableSummary | null;
  workflowPreview: ReactNode;
  onCreateRun: () => void;
  onFinishRunHistoryManagement: () => void;
  onOpenRunDetail: (runId: string) => void;
  onRequestDeleteSelectedRuns: () => void;
  onRunGoalChange: (value: string) => void;
  onRunSearchQueryChange: (value: string) => void;
  onRunTargetChange: (value: string) => void;
  onSelectRunKindFilter: (filter: RunKindFilter) => void;
  onSelectRunStatusFilter: (filter: RunStatusFilter) => void;
  onSetRunHistoryManagementMode: (enabled: boolean) => void;
  onSetSelectedRunIds: (runIds: string[]) => void;
  onToggleRunHistoryGroup: (groupKey: string) => void;
  onToggleRunSelected: (runId: string) => void;
  runnableCapabilityLine: (item: RunnableSummary) => string;
  runnableOptionLabel: (item: RunnableSummary) => string;
};

export function RunLauncherPanel({
  allHistoryRunsSelected,
  busy,
  collapsedRunHistoryGroups,
  filteredRunIds,
  filteredRuns,
  formatRunDate,
  runBulkDeleteDisabledReason,
  runFilterCounts,
  runGoal,
  runHistoryGroupSummary,
  runHistoryGroups,
  runHistoryManagementMode,
  runKindFilter,
  runKindLabel,
  runSearchActive,
  runSearchQuery,
  runStatusFilter,
  runStatusFilterCounts,
  runStatusFilteredRuns,
  runStatusLabel,
  runStatusTone,
  runTarget,
  runTargetDisabledReason,
  runTargetWorkflowErrors,
  runnables,
  selectedHistoryRunCount,
  selectedRunId,
  selectedRunIdSet,
  selectedRunTarget,
  workflowPreview,
  onCreateRun,
  onFinishRunHistoryManagement,
  onOpenRunDetail,
  onRequestDeleteSelectedRuns,
  onRunGoalChange,
  onRunSearchQueryChange,
  onRunTargetChange,
  onSelectRunKindFilter,
  onSelectRunStatusFilter,
  onSetRunHistoryManagementMode,
  onSetSelectedRunIds,
  onToggleRunHistoryGroup,
  onToggleRunSelected,
  runnableCapabilityLine,
  runnableOptionLabel,
}: RunLauncherPanelProps) {
  return (
    <div className="agent-studio-panel">
      <div className="section-heading-row"><h2>Run Agent / Workflow</h2></div>
      <label>
        <span>Target</span>
        <select className="hy-select" value={runTarget} onChange={(event) => onRunTargetChange(event.target.value)}>
          <option value="">选择 Agent 或 Workflow</option>
          {runnables.map((item) => (
            <option value={item.id} key={item.id} disabled={item.enabled === false}>
              {runnableOptionLabel(item)}
            </option>
          ))}
        </select>
      </label>
      {selectedRunTarget ? (
        <div className="run-target-preview">
          <strong>{selectedRunTarget.nickname || selectedRunTarget.name}</strong>
          <span>{runnableCapabilityLine(selectedRunTarget)}</span>
          {selectedRunTarget.description ? <p>{selectedRunTarget.description}</p> : null}
        </div>
      ) : null}
      {runTargetDisabledReason ? (
        <div className="agent-inline-note warn">{runTargetDisabledReason}</div>
      ) : null}
      {selectedRunTarget?.kind === 'workflow' && runTargetWorkflowErrors.length > 1 ? (
        <div className="workflow-validation-box has-errors">
          <div>
            <strong>Workflow 运行前需要修复</strong>
            {runTargetWorkflowErrors.map((item) => <span key={`run-target-error-${item}`}>{item}</span>)}
          </div>
        </div>
      ) : null}
      {selectedRunTarget?.kind === 'workflow' ? workflowPreview : null}
      <label><span>Goal</span><textarea className="hy-input agent-textarea" value={runGoal} onChange={(event) => onRunGoalChange(event.target.value)} /></label>
      <button
        type="button"
        className="primary-action"
        disabled={!runTarget || Boolean(runTargetDisabledReason) || !runGoal.trim() || busy}
        title={runTargetDisabledReason || undefined}
        onClick={onCreateRun}
      >
        运行
      </button>
      <div className="run-history-toolbar">
        <div className="run-history-head">
          <span>Run History · {filteredRuns.length}{runSearchActive ? ` / ${runStatusFilteredRuns.length}` : ''}</span>
          {filteredRuns.length && !runHistoryManagementMode ? (
            <button type="button" data-testid="agent-run-history-manage" disabled={busy} onClick={() => onSetRunHistoryManagementMode(true)}>管理</button>
          ) : null}
        </div>
        <div className="run-history-search">
          <input
            className="hy-input"
            type="search"
            value={runSearchQuery}
            placeholder="搜索目标、Agent、结果、Run ID..."
            aria-label="搜索 Run History"
            onChange={(event) => onRunSearchQueryChange(event.target.value)}
          />
          {runSearchActive ? (
            <button type="button" onClick={() => onRunSearchQueryChange('')}>清除</button>
          ) : null}
        </div>
        <div className="run-filter-tabs" role="group" aria-label="Run history filter">
          {([
            ['all', 'All', runFilterCounts.all],
            ['workflow', 'Workflows', runFilterCounts.workflow],
            ['agent', 'Agents', runFilterCounts.agent],
          ] as const).map(([filter, label, count]) => (
            <button
              type="button"
              key={filter}
              className={runKindFilter === filter ? 'active' : ''}
              onClick={() => onSelectRunKindFilter(filter)}
            >
              {label} <span>{count}</span>
            </button>
          ))}
        </div>
        <div className="run-filter-tabs run-status-filter-tabs" role="group" aria-label="Run status filter">
          {([
            ['all', '全部', runStatusFilterCounts.all],
            ['completed', '完成', runStatusFilterCounts.completed],
            ['failed', '失败', runStatusFilterCounts.failed],
            ['active', '进行中', runStatusFilterCounts.active],
          ] as const).map(([filter, label, count]) => (
            <button
              type="button"
              key={filter}
              className={runStatusFilter === filter ? 'active' : ''}
              onClick={() => onSelectRunStatusFilter(filter)}
            >
              {label} <span>{count}</span>
            </button>
          ))}
        </div>
        {filteredRuns.length && runHistoryManagementMode ? (
          <div className="studio-bulk-actions" aria-label="Run History 批量操作" data-testid="agent-run-history-bulk-actions">
            <span>{selectedHistoryRunCount ? `已选择 ${selectedHistoryRunCount} / ${filteredRuns.length}` : `${filteredRuns.length} runs`}</span>
            <button type="button" data-testid="agent-run-history-select-all" disabled={busy} onClick={() => onSetSelectedRunIds(allHistoryRunsSelected ? [] : filteredRunIds)}>
              {allHistoryRunsSelected ? '取消全选' : '全选当前列表'}
            </button>
            <button type="button" data-testid="agent-run-history-clear-selection" disabled={busy || !selectedHistoryRunCount} onClick={() => onSetSelectedRunIds([])}>清空</button>
            <button
              type="button"
              className="danger-action"
              data-testid="agent-run-history-delete-selected"
              disabled={busy || !selectedHistoryRunCount || Boolean(runBulkDeleteDisabledReason)}
              title={runBulkDeleteDisabledReason || undefined}
              onClick={onRequestDeleteSelectedRuns}
            >
              删除所选
            </button>
            <button type="button" data-testid="agent-run-history-finish-management" disabled={busy} onClick={onFinishRunHistoryManagement}>完成</button>
          </div>
        ) : null}
      </div>
      <RunHistoryList
        busy={busy}
        collapsedRunHistoryGroups={collapsedRunHistoryGroups}
        filteredRuns={filteredRuns}
        formatRunDate={formatRunDate}
        onOpenRunDetail={onOpenRunDetail}
        onToggleRunHistoryGroup={onToggleRunHistoryGroup}
        onToggleRunSelected={onToggleRunSelected}
        runHistoryGroupSummary={runHistoryGroupSummary}
        runHistoryGroups={runHistoryGroups}
        runHistoryManagementMode={runHistoryManagementMode}
        runKindLabel={runKindLabel}
        runSearchActive={runSearchActive}
        runStatusFilteredRuns={runStatusFilteredRuns}
        runStatusLabel={runStatusLabel}
        runStatusTone={runStatusTone}
        selectedRunId={selectedRunId}
        selectedRunIdSet={selectedRunIdSet}
      />
    </div>
  );
}
