#!/usr/bin/env node

import assert from 'node:assert/strict';
import test from 'node:test';

import { startLauncherPolling } from '../apps/frontend/src/views/launcherPolling.ts';

class FakeClock {
  now = 0;
  nextId = 1;
  timers = new Map();

  setTimeout = (callback, delay) => {
    const id = this.nextId++;
    this.timers.set(id, {
      callback,
      dueAt: this.now + Math.max(0, Number(delay) || 0),
    });
    return id;
  };

  clearTimeout = (id) => {
    this.timers.delete(id);
  };

  async advanceBy(milliseconds) {
    const target = this.now + milliseconds;
    while (true) {
      const next = [...this.timers.entries()]
        .filter(([, timer]) => timer.dueAt <= target)
        .sort((left, right) => left[1].dueAt - right[1].dueAt || left[0] - right[0])[0];
      if (!next) break;
      const [id, timer] = next;
      this.timers.delete(id);
      this.now = timer.dueAt;
      timer.callback();
      await Promise.resolve();
      await Promise.resolve();
    }
    this.now = target;
    await Promise.resolve();
  }
}

class FakeVisibility {
  hidden = false;
  listeners = new Set();

  addEventListener = (_event, listener) => {
    this.listeners.add(listener);
  };

  removeEventListener = (_event, listener) => {
    this.listeners.delete(listener);
  };

  setHidden(hidden) {
    this.hidden = hidden;
    for (const listener of this.listeners) listener();
  }
}

test('60 seconds of launcher polling never overlaps refresh requests', async () => {
  const clock = new FakeClock();
  const visibility = new FakeVisibility();
  let activeRequests = 0;
  let maxActiveRequests = 0;
  let requestCount = 0;

  const stop = startLauncherPolling({
    intervalMs: 5_000,
    refresh: async () => {
      requestCount += 1;
      activeRequests += 1;
      maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
      await new Promise((resolve) => clock.setTimeout(resolve, 7_500));
      activeRequests -= 1;
    },
    timer: clock,
    visibility,
  });

  await clock.advanceBy(60_000);
  stop();

  assert.equal(maxActiveRequests, 1);
  assert.equal(requestCount, 5);
});

test('hidden launcher pauses polling and resumes once when visible', async () => {
  const clock = new FakeClock();
  const visibility = new FakeVisibility();
  visibility.hidden = true;
  let requestCount = 0;

  const stop = startLauncherPolling({
    intervalMs: 5_000,
    refresh: async () => {
      requestCount += 1;
    },
    timer: clock,
    visibility,
  });

  await clock.advanceBy(60_000);
  assert.equal(requestCount, 0);

  visibility.setHidden(false);
  await Promise.resolve();
  assert.equal(requestCount, 1);

  visibility.setHidden(true);
  await clock.advanceBy(60_000);
  stop();
  assert.equal(requestCount, 1);
});

test('stopping launcher polling during a request leaves no timers or listeners', async () => {
  const clock = new FakeClock();
  const visibility = new FakeVisibility();
  let requestCount = 0;

  const stop = startLauncherPolling({
    intervalMs: 5_000,
    refresh: async () => {
      requestCount += 1;
      await new Promise((resolve) => clock.setTimeout(resolve, 7_500));
    },
    timer: clock,
    visibility,
  });

  stop();
  await clock.advanceBy(60_000);

  assert.equal(requestCount, 1);
  assert.equal(clock.timers.size, 0);
  assert.equal(visibility.listeners.size, 0);
});
