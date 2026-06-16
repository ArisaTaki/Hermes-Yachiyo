type UseGroupRunDebugActionsOptions = {
  loadMoreGroupRunReplayEvents: () => Promise<number>;
  setStatus: (message: string) => void;
};

export function useGroupRunDebugActions({
  loadMoreGroupRunReplayEvents,
  setStatus,
}: UseGroupRunDebugActionsOptions) {
  async function loadMoreSelectedGroupRunEvents() {
    const loadedCount = await loadMoreGroupRunReplayEvents();
    setStatus(loadedCount ? `已加载 ${loadedCount} 条 GroupRun Event replay` : '没有更多 GroupRun Event replay');
  }

  return {
    loadMoreSelectedGroupRunEvents,
  };
}
