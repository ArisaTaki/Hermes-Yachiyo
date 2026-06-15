import type { GroupRunSnapshot } from '../../yachiyo-studio/types';

type GroupRunPanelProps = {
  agentGroupRunGoal: string;
  busy: boolean;
  latestAgentGroupRun: GroupRunSnapshot | null;
  selectedAgentGroupId: string;
  onAgentGroupRunGoalChange: (value: string) => void;
  onOpenAgentGroupRunTimeline: (groupRun: GroupRunSnapshot) => void;
  onRunAgentGroup: () => void;
};

export function GroupRunPanel({
  agentGroupRunGoal,
  busy,
  latestAgentGroupRun,
  selectedAgentGroupId,
  onAgentGroupRunGoalChange,
  onOpenAgentGroupRunTimeline,
  onRunAgentGroup,
}: GroupRunPanelProps) {
  return (
    <section className="group-run-panel" data-testid="agent-group-run-panel">
      <label>
        <span>Run 目标</span>
        <textarea
          className="hy-input"
          rows={4}
          value={agentGroupRunGoal}
          onChange={(event) => onAgentGroupRunGoalChange(event.target.value)}
        />
      </label>
      <div className="studio-heading-actions">
        <button type="button" className="primary-action" data-testid="agent-group-run" disabled={busy || !selectedAgentGroupId || !agentGroupRunGoal.trim()} onClick={onRunAgentGroup}>启动 Run</button>
        {latestAgentGroupRun ? (
          <button type="button" data-testid="agent-group-open-run" disabled={busy} onClick={() => onOpenAgentGroupRunTimeline(latestAgentGroupRun)}>打开 Run Timeline</button>
        ) : null}
      </div>
    </section>
  );
}
