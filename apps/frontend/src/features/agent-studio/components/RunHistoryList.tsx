import type { RunSpec } from '../types';

export type RunHistoryGroupView = {
  key: string;
  label: string;
  subtitle: string;
  avatarUrl?: string;
  runs: RunSpec[];
};

export function RunHistoryList({
  busy,
  collapsedRunHistoryGroups,
  filteredRuns,
  formatRunDate,
  onOpenRunDetail,
  onToggleRunHistoryGroup,
  onToggleRunSelected,
  runHistoryGroupSummary,
  runHistoryGroups,
  runHistoryManagementMode,
  runKindLabel,
  runSearchActive,
  runStatusFilteredRuns,
  runStatusLabel,
  runStatusTone,
  selectedRunId,
  selectedRunIdSet,
}: {
  busy: boolean;
  collapsedRunHistoryGroups: Set<string>;
  filteredRuns: RunSpec[];
  formatRunDate: (value?: string) => string;
  onOpenRunDetail: (runId: string) => void;
  onToggleRunHistoryGroup: (groupKey: string) => void;
  onToggleRunSelected: (runId: string) => void;
  runHistoryGroupSummary: (runs: RunSpec[]) => string;
  runHistoryGroups: RunHistoryGroupView[];
  runHistoryManagementMode: boolean;
  runKindLabel: (kind: string) => string;
  runSearchActive: boolean;
  runStatusFilteredRuns: RunSpec[];
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedRunId: string;
  selectedRunIdSet: Set<string>;
}) {
  return (
    <div className="run-list grouped">
      {runHistoryGroups.map((group) => {
        const collapsed = collapsedRunHistoryGroups.has(group.key);
        const selectedInGroup = group.runs.some((run) => run.run_id === selectedRunId);
        return (
          <section className={`run-history-group${selectedInGroup ? ' has-selected-run' : ''}`} key={group.key}>
            <button
              type="button"
              className="run-history-group-head"
              aria-expanded={!collapsed}
              onClick={() => onToggleRunHistoryGroup(group.key)}
            >
              <RunHistoryAvatar avatarUrl={group.avatarUrl} name={group.label} />
              <div>
                <strong>{group.label}</strong>
                <span>{group.subtitle} · {group.runs.length} runs · {runHistoryGroupSummary(group.runs)}</span>
              </div>
              <em aria-hidden="true">{collapsed ? '+' : '-'}</em>
            </button>
            {!collapsed ? (
              <div className={runHistoryManagementMode ? 'run-history-group-list managing' : 'run-history-group-list'}>
                {group.runs.map((run) => (
                  <div
                    className={run.run_id === selectedRunId ? 'run-list-row active' : 'run-list-row'}
                    data-run-group-id={run.run_group_id || ''}
                    data-run-id={run.run_id}
                    data-run-kind={run.kind}
                    data-run-status={run.status}
                    data-task-id={run.task_id || ''}
                    data-testid="agent-run-history-row"
                    key={run.run_id}
                  >
                    <label className="run-list-select" aria-label={`选择 Run ${run.run_id}`}>
                      <input
                        data-testid="agent-run-history-select-run"
                        type="checkbox"
                        checked={selectedRunIdSet.has(run.run_id)}
                        disabled={busy || !runHistoryManagementMode}
                        onChange={() => onToggleRunSelected(run.run_id)}
                      />
                    </label>
                    <button
                      type="button"
                      className={run.run_id === selectedRunId ? 'run-list-item active' : 'run-list-item'}
                      data-run-id={run.run_id}
                      data-run-status={run.status}
                      data-testid="agent-run-history-open-run"
                      onClick={() => onOpenRunDetail(run.run_id)}
                    >
                      <span className={`run-list-status-dot ${runStatusTone(run.status)}`} aria-hidden="true" />
                      <span className="run-list-item-copy">
                        <strong>{run.user_goal || run.runnable_name || run.runnable_id}</strong>
                        <span>{runKindLabel(run.kind)} · {runStatusLabel(run.status)} · {formatRunDate(run.updated_at || run.created_at)}</span>
                        {run.result ? <small>{run.result}</small> : null}
                      </span>
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </section>
        );
      })}
      {!filteredRuns.length ? (
        <div className="empty-state inline-empty">
          {runSearchActive && runStatusFilteredRuns.length ? '没有匹配搜索的 Run。' : '当前分类下没有 Run。'}
        </div>
      ) : null}
    </div>
  );
}

function RunHistoryAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  return (
    <span className={avatarUrl ? 'agent-avatar has-image' : 'agent-avatar'} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : runHistoryInitial(name)}
    </span>
  );
}

function runHistoryInitial(name: string): string {
  const clean = name.trim();
  if (!clean) return 'A';
  return Array.from(clean)[0]?.toUpperCase() || 'A';
}
