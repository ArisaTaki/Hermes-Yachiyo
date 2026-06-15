export function AgentRunProgressCard({
  detail,
  onOpenDetails,
  runGroupId,
  runId,
  runStatus,
  runnableId,
  runnableKind,
  title,
}: {
  detail: string;
  onOpenDetails: () => void;
  runGroupId: string;
  runId: string;
  runStatus: string;
  runnableId: string;
  runnableKind: string;
  title: string;
}) {
  return (
    <div
      className="message-content message-agent-progress-card"
      data-run-group-id={runGroupId}
      data-run-id={runId}
      data-run-status={runStatus}
      data-runnable-id={runnableId}
      data-runnable-kind={runnableKind}
      data-testid="chat-agent-run-progress-card"
    >
      <span className="message-agent-progress-icon loading-ring" aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
        {runId ? (
          <button
            type="button"
            data-run-id={runId}
            data-run-status={runStatus}
            data-testid="chat-agent-run-progress-open-run-detail"
            onClick={onOpenDetails}
          >
            运行详情
          </button>
        ) : null}
      </div>
    </div>
  );
}
