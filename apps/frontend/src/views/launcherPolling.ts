export type LauncherPollingTimer = {
  clearTimeout(timerId: number): void;
  setTimeout(callback: () => void, delayMs: number): number;
};

export type LauncherPollingVisibility = {
  readonly hidden: boolean;
  addEventListener(event: 'visibilitychange', listener: () => void): void;
  removeEventListener(event: 'visibilitychange', listener: () => void): void;
};

type StartLauncherPollingOptions = {
  intervalMs: number | (() => number);
  refresh: () => Promise<unknown>;
  timer?: LauncherPollingTimer;
  visibility?: LauncherPollingVisibility;
};

export function startLauncherPolling({
  intervalMs,
  refresh,
  timer = window,
  visibility = document,
}: StartLauncherPollingOptions): () => void {
  let stopped = false;
  let running = false;
  let timerId: number | null = null;

  const clearTimer = () => {
    if (timerId === null) return;
    timer.clearTimeout(timerId);
    timerId = null;
  };
  const scheduleNext = () => {
    clearTimer();
    if (stopped || visibility.hidden) return;
    const delayMs = typeof intervalMs === 'function' ? intervalMs() : intervalMs;
    timerId = timer.setTimeout(() => {
      timerId = null;
      void run();
    }, Math.max(0, delayMs));
  };
  const run = async () => {
    if (stopped || visibility.hidden || running) return;
    running = true;
    try {
      await refresh();
    } finally {
      running = false;
      scheduleNext();
    }
  };

  const handleVisibilityChange = () => {
    clearTimer();
    if (stopped || visibility.hidden) return;
    void run();
  };

  visibility.addEventListener('visibilitychange', handleVisibilityChange);
  void run();
  return () => {
    stopped = true;
    clearTimer();
    visibility.removeEventListener('visibilitychange', handleVisibilityChange);
  };
}
