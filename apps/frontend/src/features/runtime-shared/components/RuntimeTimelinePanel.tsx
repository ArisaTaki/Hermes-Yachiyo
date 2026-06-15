import { RuntimeTimelineEventList, type RuntimeTimelineEventListProps } from './RuntimeTimelineEventList';

type RuntimeTimelinePanelProps = Omit<RuntimeTimelineEventListProps, 'className' | 'testId'> & {
  bodyClassName: string;
  className: string;
  eventListTestId: string;
  loadMoreClassName?: string;
  loadMoreLabel?: string;
  loadMoreLoadingLabel?: string;
  loadMoreTestId?: string;
  onLoadMoreEvents?: () => Promise<void> | void;
  panelTestId: string;
  replayError?: string;
  replayErrorClassName?: string;
  replayHasMore?: boolean;
  replayLoading?: boolean;
  subtitle: string;
  summaryClassName: string;
  title: string;
};

export function RuntimeTimelinePanel({
  bodyClassName,
  className,
  eventListTestId,
  loadMoreClassName,
  loadMoreLabel = '加载更多 RunEvent',
  loadMoreLoadingLabel = '加载中...',
  loadMoreTestId,
  onLoadMoreEvents,
  panelTestId,
  replayError,
  replayErrorClassName,
  replayHasMore = false,
  replayLoading = false,
  subtitle,
  summaryClassName,
  title,
  ...eventListProps
}: RuntimeTimelinePanelProps) {
  return (
    <details className={className} data-testid={panelTestId} open>
      <summary className={summaryClassName}>
        <div>
          <h4>{title}</h4>
          <span>{subtitle}</span>
        </div>
      </summary>
      <RuntimeTimelineEventList
        {...eventListProps}
        className={bodyClassName}
        testId={eventListTestId}
      />
      {replayError ? <p className={replayErrorClassName}>{replayError}</p> : null}
      {replayHasMore && onLoadMoreEvents ? (
        <div className={loadMoreClassName}>
          <button
            type="button"
            data-testid={loadMoreTestId}
            disabled={replayLoading}
            onClick={() => void onLoadMoreEvents()}
          >
            {replayLoading ? loadMoreLoadingLabel : loadMoreLabel}
          </button>
        </div>
      ) : null}
    </details>
  );
}
