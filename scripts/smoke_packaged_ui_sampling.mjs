#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const DEFAULT_TIMEOUT_MS = 60_000;
const MIN_ROUTE_TIMEOUT_MS = 15_000;
const ROUTE_SAMPLES = [
  {
    id: 'chat',
    route: '#/chat',
    selectors: [
      '[data-testid="chat-composer-input"]',
      '[data-testid="chat-composer-image-attach-button"]',
      '[data-testid="chat-composer-send"]',
    ],
  },
  {
    id: 'agent_studio_agents',
    route: '#/agents/agents',
    selectors: [
      '[data-testid="agent-studio-agents"]',
      '[data-testid="agent-list"]',
    ],
  },
  {
    id: 'workflow_studio',
    route: '#/agents/workflows',
    selectors: [
      '[data-testid="workflow-studio"]',
      '[data-testid="workflow-editor"]',
    ],
  },
  {
    id: 'activity_feed',
    route: '#/activity-all',
    selectors: [
      '[data-testid="activity-feed"]',
      '[data-testid="activity-list"]',
    ],
  },
  {
    id: 'diagnostics',
    route: '#/diagnostics',
    selectors: [
      '[data-testid="diagnostics-run-command"]',
      '[data-testid="diagnostics-screen-probe"]',
    ],
  },
  {
    id: 'proactive_tts',
    route: '#/proactive-tts',
    selectors: [
      '[data-testid="proactive-tts-settings"]',
      '[data-testid="proactive-save-settings"]',
    ],
  },
  {
    id: 'live2d_settings',
    route: '#/settings/live2d',
    selectors: [
      '[data-testid="live2d-resource-settings"]',
      '[data-testid="live2d-model-state"]',
    ],
  },
];

function parseArgs(argv) {
  const args = {
    debugPort: '',
    timeoutMs: DEFAULT_TIMEOUT_MS,
    reportJson: '',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--debug-port') args.debugPort = argv[++index] || '';
    else if (arg === '--timeout-ms') args.timeoutMs = Number(argv[++index] || DEFAULT_TIMEOUT_MS);
    else if (arg === '--report-json') args.reportJson = argv[++index] || '';
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!args.debugPort) throw new Error('--debug-port is required');
  if (!Number.isFinite(args.timeoutMs) || args.timeoutMs <= 0) {
    throw new Error('--timeout-ms must be a positive number');
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForPageTarget(debugPort, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = '';
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
      if (!response.ok) throw new Error(`DevTools /json/list returned ${response.status}`);
      const targets = await response.json();
      const page = targets.find((target) => (
        target
        && target.type === 'page'
        && target.webSocketDebuggerUrl
        && !String(target.url || '').startsWith('devtools://')
      ));
      if (page) return page;
      lastError = 'no page target exposed yet';
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(250);
  }
  throw new Error(`packaged app did not expose a DevTools page target: ${lastError}`);
}

class CdpClient {
  constructor(webSocketDebuggerUrl) {
    if (typeof WebSocket !== 'function') {
      throw new Error('Node.js WebSocket global is unavailable; use Node 20.19+');
    }
    this.nextId = 1;
    this.pending = new Map();
    this.ws = new WebSocket(webSocketDebuggerUrl);
    this.ready = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', () => reject(new Error('DevTools websocket failed to open')), { once: true });
    });
    this.ws.addEventListener('message', (event) => this.handleMessage(event.data));
    this.ws.addEventListener('close', () => {
      for (const { reject } of this.pending.values()) reject(new Error('DevTools websocket closed'));
      this.pending.clear();
    });
  }

  handleMessage(data) {
    const text = typeof data === 'string' ? data : Buffer.from(data).toString('utf8');
    let message;
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }
    if (!message.id || !this.pending.has(message.id)) return;
    const { resolve, reject } = this.pending.get(message.id);
    this.pending.delete(message.id);
    if (message.error) reject(new Error(`${message.error.message || 'CDP error'} (${message.error.code || 'unknown'})`));
    else resolve(message.result || {});
  }

  async send(method, params = {}) {
    await this.ready;
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(payload);
    });
  }

  close() {
    this.ws.close();
  }
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.text || result.exceptionDetails.exception?.description || 'unknown exception';
    throw new Error(`Runtime.evaluate failed: ${detail}`);
  }
  return result.result?.value;
}

async function waitForDocumentReady(client, timeoutMs) {
  await evaluate(client, `
    new Promise((resolve) => {
      if (document.readyState !== 'loading') resolve(document.readyState);
      else window.addEventListener('DOMContentLoaded', () => resolve(document.readyState), { once: true });
      setTimeout(() => resolve(document.readyState), ${Math.max(1000, timeoutMs)});
    })
  `);
}

async function navigateToRoute(client, route) {
  return evaluate(client, `
    (() => {
      const nextRoute = ${JSON.stringify(route)};
      if (window.location.hash !== nextRoute) window.location.hash = nextRoute;
      window.dispatchEvent(new Event('hashchange'));
      return window.location.href;
    })()
  `);
}

async function visibleSelectorMap(client, selectors) {
  return evaluate(client, `
    (() => {
      const selectors = ${JSON.stringify(selectors)};
      const result = {};
      for (const selector of selectors) {
        const node = document.querySelector(selector);
        if (!node) {
          result[selector] = false;
          continue;
        }
        const style = window.getComputedStyle(node);
        if (style.visibility === 'hidden' || style.display === 'none') {
          result[selector] = false;
          continue;
        }
        result[selector] = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
      }
      return result;
    })()
  `);
}

async function pageSnapshot(client) {
  return evaluate(client, `
    (() => ({
      hash: window.location.hash,
      title: document.title,
      readyState: document.readyState,
      bodyText: (document.body?.innerText || '').slice(0, 300),
    }))()
  `);
}

async function waitForVisibleSelectors(client, selectors, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastSnapshot = {};
  while (Date.now() < deadline) {
    const visibleMap = await visibleSelectorMap(client, selectors);
    const missing = selectors.filter((selector) => !visibleMap?.[selector]);
    if (missing.length === 0) return;
    lastSnapshot = await pageSnapshot(client);
    await sleep(250);
  }
  const visibleMap = await visibleSelectorMap(client, selectors);
  const missing = selectors.filter((selector) => !visibleMap?.[selector]);
  const detail = JSON.stringify(lastSnapshot);
  throw new Error(`selectors did not render before timeout: ${missing.join(', ')}; page=${detail}`);
}

async function sampleRoute(client, sample, timeoutMs) {
  const url = await navigateToRoute(client, sample.route);
  const routeTimeout = Math.max(
    MIN_ROUTE_TIMEOUT_MS,
    Math.floor(timeoutMs / ROUTE_SAMPLES.length),
  );
  await waitForVisibleSelectors(client, sample.selectors, routeTimeout);
  const title = await evaluate(client, 'document.title');
  const hash = await evaluate(client, 'window.location.hash');
  return {
    id: sample.id,
    route: sample.route,
    hash,
    title,
    url,
    selectors: sample.selectors,
  };
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const target = await waitForPageTarget(args.debugPort, args.timeoutMs);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  const samples = [];
  try {
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await waitForDocumentReady(client, args.timeoutMs);
    for (const sample of ROUTE_SAMPLES) {
      process.stdout.write(`[packaged-ui-sampling] ${sample.id} ${sample.route}\n`);
      samples.push(await sampleRoute(client, sample, args.timeoutMs));
    }
  } finally {
    client.close();
  }

  const report = {
    ok: true,
    sample_count: samples.length,
    samples,
  };
  if (args.reportJson) {
    fs.mkdirSync(path.dirname(args.reportJson), { recursive: true });
    fs.writeFileSync(args.reportJson, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  }
  process.stdout.write(`[packaged-ui-sampling] passed ${samples.length} packaged routes\n`);
}

run().catch((error) => {
  process.stderr.write(`[packaged-ui-sampling] failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
