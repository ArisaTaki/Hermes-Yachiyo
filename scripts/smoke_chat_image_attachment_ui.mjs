#!/usr/bin/env node
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FRONTEND = path.join(ROOT, 'apps', 'frontend');
const ELECTRON = path.join(FRONTEND, 'node_modules', '.bin', process.platform === 'win32' ? 'electron.cmd' : 'electron');
const VITE = path.join(FRONTEND, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite');
const SESSION_ID = 'session-chat-image-smoke';
const TASK_ID = 'task-chat-image-ui-smoke';
const RUN_ID = 'main_chat_run_image_ui_smoke';
const RUN_GROUP_ID = 'group-chat-image-ui-smoke';
const RUN_GOAL = 'browser image attachment smoke';
const RUN_RESULT = 'Browser image attachment NativeRunEngine reply saw image attachment.';
const now = new Date().toISOString();
const CHAT_IMAGE_SMOKE_FILE_NAMES = [
  'smoke-image-cdp.svg',
  'smoke-image-cdp-second.svg',
  'smoke-image-cdp-third.svg',
  'smoke-image-cdp-fourth.svg',
];
const NATIVE_PICKER_IMAGE_NAME = 'smoke-image-native.svg';
const TEST_IMAGE_DATA_URL = `data:image/svg+xml;base64,${Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#0ea5e9"/><circle cx="12" cy="12" r="7" fill="#fff"/></svg>',
).toString('base64')}`;
const TEST_IMAGE_BYTE_SIZE = Buffer.from(TEST_IMAGE_DATA_URL.split(',')[1] || '', 'base64').length;

const bridgeState = {
  messages: [],
  postPayloads: [],
};

function log(message) {
  process.stdout.write(`[chat-image-ui-smoke] ${message}\n`);
}

function fail(message) {
  throw new Error(message);
}

function pickPort() {
  return new Promise((resolve, reject) => {
    const server = http.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === 'string') reject(new Error('could not allocate local port'));
        else resolve(address.port);
      });
    });
  });
}

function readRequestJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      if (!chunks.length) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (error) {
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'content-type,x-oha-yachiyo-bridge-token',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

function messagePayload() {
  return {
    ok: true,
    session_id: SESSION_ID,
    messages: bridgeState.messages,
    session_context: { conversation_kind: 'main' },
    is_processing: false,
    processing_count: 0,
    approval_count: 0,
    token_count: 0,
  };
}

const run = {
  run_id: RUN_ID,
  run_group_id: RUN_GROUP_ID,
  run_group_source: 'main_chat',
  task_id: TASK_ID,
  session_id: SESSION_ID,
  task_run_link_run_status: 'completed',
  task_run_link_last_event_sequence: 2,
  kind: 'main_chat_run',
  runnable_id: 'builtin:yachiyo-main',
  runnable_name: 'Oha-Yachiyo',
  status: 'completed',
  user_goal: RUN_GOAL,
  result: RUN_RESULT,
  timeline: [
    { event: 'model.output.completed', status: 'completed', output: RUN_RESULT },
    { event: 'run.completed', status: 'completed', result: RUN_RESULT },
  ],
  artifacts: [],
  created_at: now,
  updated_at: now,
};

const runGroup = {
  run_group_id: RUN_GROUP_ID,
  title: 'Chat Image Attachment Smoke',
  source: 'main_chat',
  status: 'completed',
  summary: RUN_RESULT,
  child_run_ids: [RUN_ID],
  created_at: now,
  updated_at: now,
};

const runEvents = [
  {
    event_id: 'event-chat-image-smoke-1',
    run_id: RUN_ID,
    sequence: 1,
    schema_version: 1,
    event_type: 'model.output.completed',
    actor: 'model',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { output: RUN_RESULT },
    created_at: now,
  },
  {
    event_id: 'event-chat-image-smoke-2',
    run_id: RUN_ID,
    sequence: 2,
    schema_version: 1,
    event_type: 'run.completed',
    actor: 'runtime',
    visibility: 'user',
    sensitivity: 'normal',
    payload: { result: RUN_RESULT },
    created_at: now,
  },
];

function runEventsPage(url) {
  const afterSequence = Math.max(0, Number(url.searchParams.get('after_sequence') || '0'));
  const limit = Math.max(1, Number(url.searchParams.get('limit') || '200'));
  return {
    run_id: RUN_ID,
    after_sequence: afterSequence,
    limit,
    events: runEvents.filter((event) => event.sequence > afterSequence).slice(0, limit),
  };
}

async function startMockBridge() {
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/chat/executor') {
        sendJson(response, 200, {
          executor: 'NativeAgentExecutor',
          available: true,
          image_input: {
            can_attach_images: true,
            label: '添加图片附件',
          },
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/assistant/profile') {
        sendJson(response, 200, { ok: true, agent_name: 'Oha-Yachiyo', user_avatar_url: '' });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runnables') {
        sendJson(response, 200, {
          runnables: [{ id: 'builtin:yachiyo-main', name: 'Oha-Yachiyo', kind: 'agent', enabled: true, output_contract: 'chat' }],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/agents') {
        sendJson(response, 200, { agents: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills') {
        sendJson(response, 200, { skills: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skills/sources') {
        sendJson(response, 200, { roots: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/skill-folders') {
        sendJson(response, 200, { folders: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/model-profiles') {
        sendJson(response, 200, { ok: true, profiles: [], defaults: {} });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/yachiyo/studio/workflows') {
        sendJson(response, 200, { workflows: [] });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/runs') {
        sendJson(response, 200, { runs: [run] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/runs/${RUN_ID}`) {
        sendJson(response, 200, run);
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/run-groups') {
        sendJson(response, 200, { run_groups: [runGroup] });
        return;
      }
      if (request.method === 'GET' && url.pathname === `/ui/run-groups/${RUN_GROUP_ID}`) {
        sendJson(response, 200, runGroup);
        return;
      }
      if (request.method === 'GET' && url.pathname === `/yachiyo/studio/runs/${RUN_ID}/events`) {
        sendJson(response, 200, runEventsPage(url));
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/sessions') {
        sendJson(response, 200, {
          ok: true,
          current_session_id: SESSION_ID,
          sessions: [
            {
              session_id: SESSION_ID,
              title: 'Chat image UI smoke',
              conversation_kind: 'main',
            },
          ],
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/chat/messages') {
        sendJson(response, 200, messagePayload());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/chat/messages') {
        const body = await readRequestJson(request);
        log(`mock bridge received chat message with ${Array.isArray(body.attachments) ? body.attachments.length : 0} attachment(s)`);
        bridgeState.postPayloads.push(body);
        const attachments = Array.isArray(body.attachments) ? body.attachments : [];
        bridgeState.messages = [
          {
            id: 'user-image-message',
            role: 'user',
            content: String(body.text || ''),
            status: 'completed',
            created_at: new Date().toISOString(),
            attachments: attachments.map((attachment, index) => ({
              id: attachment.id || `smoke-image-${index}`,
              kind: 'image',
              name: attachment.name || 'smoke-image.svg',
              mime_type: attachment.mime_type || 'image/svg+xml',
              size: attachment.size || 0,
              url: attachment.data_url,
            })),
            metadata: {},
          },
          {
            id: 'assistant-chat-image-ui-smoke-reply',
            role: 'assistant',
            content: RUN_RESULT,
            status: 'completed',
            task_id: TASK_ID,
            created_at: new Date().toISOString(),
            metadata: {
              task_id: TASK_ID,
              run_id: RUN_ID,
              run_status: 'completed',
              runnable_id: 'builtin:yachiyo-main',
              runnable_kind: 'agent',
              run_group_id: RUN_GROUP_ID,
              source: 'main_chat',
            },
          },
        ];
        sendJson(response, 200, { ok: true, task_id: TASK_ID, run_id: RUN_ID, run_status: 'completed' });
        return;
      }
      sendJson(response, 404, { ok: false, error: `not found: ${request.method} ${url.pathname}` });
    } catch (error) {
      sendJson(response, 500, { ok: false, error: error instanceof Error ? error.message : String(error) });
    }
  });
  const port = await pickPort();
  await new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  return { server, url: `http://127.0.0.1:${port}` };
}

function waitForHttp(url, timeoutMs = 15_000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      http.get(url, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
        } else if (Date.now() - started > timeoutMs) {
          reject(new Error(`timed out waiting for ${url}`));
        } else {
          setTimeout(attempt, 250);
        }
      }).on('error', (error) => {
        if (Date.now() - started > timeoutMs) reject(error);
        else setTimeout(attempt, 250);
      });
    };
    attempt();
  });
}

function startVite(port) {
  const child = spawn(VITE, ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: FRONTEND,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, FORCE_COLOR: '0' },
  });
  child.stdout.on('data', (chunk) => process.stdout.write(chunk));
  child.stderr.on('data', (chunk) => process.stderr.write(chunk));
  return child;
}

function killProcess(child) {
  if (!child || child.killed) return;
  child.kill('SIGTERM');
}

function runElectronSmoke(devUrl, bridgeUrl) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-chat-image-smoke-'));
  const imageFileNames = CHAT_IMAGE_SMOKE_FILE_NAMES;
  const imageFilePaths = imageFileNames.map((name) => path.join(tempDir, name));
  for (const filePath of imageFilePaths) {
    fs.writeFileSync(
      filePath,
      Buffer.from(TEST_IMAGE_DATA_URL.split(',')[1] || '', 'base64'),
    );
  }
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const imageDataUrl = ${JSON.stringify(TEST_IMAGE_DATA_URL)};
const imageByteSize = ${JSON.stringify(TEST_IMAGE_BYTE_SIZE)};
const imageFileNames = ${JSON.stringify(imageFileNames)};
const imageFilePaths = ${JSON.stringify(imageFilePaths)};
const nativePickerImageName = ${JSON.stringify(NATIVE_PICKER_IMAGE_NAME)};
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 30000);
function waitFor(win, predicate, label, timeout = 15000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const result = await win.webContents.executeJavaScript('(' + predicate.toString() + ')()', true);
        if (result) {
          resolve(result);
          return;
        }
      } catch {}
      if (Date.now() - started > timeout) {
        let debug = '';
        try {
          debug = await win.webContents.executeJavaScript(\`
            JSON.stringify({
              status: document.querySelector('.chat-status')?.textContent || '',
              previews: document.querySelectorAll('[data-testid="chat-composer-attachment-preview"]').length,
              messageAttachments: document.querySelectorAll('[data-testid="chat-message-attachment-item"]').length,
              messages: Array.from(document.querySelectorAll('.chat-message, .message-bubble')).map((node) => node.textContent).slice(-5),
              bodyText: document.body.textContent.slice(-1200),
            })
          \`, true);
        } catch {}
        reject(new Error('timeout waiting for ' + label + (debug ? ': ' + debug : '')));
      } else {
        setTimeout(tick, 120);
      }
    };
    tick();
  });
}
async function setChatImageInputFilesWithCdp(win, filePaths) {
  if (!win.webContents.debugger.isAttached()) win.webContents.debugger.attach('1.3');
  const documentResult = await win.webContents.debugger.sendCommand('DOM.getDocument', { depth: -1, pierce: true });
  const queryResult = await win.webContents.debugger.sendCommand('DOM.querySelector', {
    nodeId: documentResult.root.nodeId,
    selector: '[data-testid="chat-image-file-input"]',
  });
  if (!queryResult.nodeId) throw new Error('chat image file input not found through CDP');
  await win.webContents.debugger.sendCommand('DOM.setFileInputFiles', {
    files: filePaths,
    nodeId: queryResult.nodeId,
  });
}
async function main() {
  await app.whenReady();
  console.log('[electron-smoke] app ready');
  const win = new BrowserWindow({
    width: 1280,
    height: 900,
    show: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  win.webContents.on('console-message', (_event, level, message) => {
    if (level >= 2) console.error('[renderer]', message);
  });
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/chat');
  console.log('[electron-smoke] chat loaded');
  await waitFor(
    win,
    () => (
      document.querySelector('textarea.chat-input')
      && !document.querySelector('.chat-loading-state')
      && !document.querySelector('[data-testid="chat-composer-image-attach-button"]')?.disabled
    ),
    'chat composer readiness',
  );
  console.log('[electron-smoke] composer ready');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-image-file-input"]');
      const buttons = [
        document.querySelector('[data-testid="chat-header-image-attach-button"]'),
        document.querySelector('[data-testid="chat-composer-image-attach-button"]'),
      ];
      if (!input) throw new Error('chat image file input not found');
      if (input.type !== 'file') throw new Error('chat image input must stay a file input');
      if (input.accept !== 'image/*') throw new Error('chat image input must only accept images');
      if (!input.multiple) throw new Error('chat image input must support multiple images');
      if (!input.hidden) throw new Error('chat image input must stay hidden behind visible attach buttons');
      if (buttons.some((button) => !button)) throw new Error('chat image attach button not found');
      if (buttons.some((button) => button.disabled)) throw new Error('chat image attach button disabled');
      let clickCount = 0;
      const hadOwnClick = Object.prototype.hasOwnProperty.call(input, 'click');
      const ownClick = hadOwnClick ? input.click : undefined;
      Object.defineProperty(input, 'click', { configurable: true, value: () => { clickCount += 1; } });
      try {
        buttons.forEach((button) => button.click());
      } finally {
        delete input.click;
        if (hadOwnClick) Object.defineProperty(input, 'click', { configurable: true, value: ownClick });
      }
      if (clickCount !== buttons.length) throw new Error('chat image attach buttons did not target file input');
    })();
  \`, true);
  console.log('[electron-smoke] image attach buttons target file input fallback');
  await win.webContents.executeJavaScript(\`
    (() => {
      window.__chatNativePickerCalls = 0;
      window.ohaDesktop = {
        ...(window.ohaDesktop || {}),
        chooseChatImages: async () => {
          window.__chatNativePickerCalls += 1;
          return [{
            path: '/tmp/oha-yachiyo-native-picker-smoke/' + \${JSON.stringify(nativePickerImageName)},
            file_name: \${JSON.stringify(nativePickerImageName)},
            mime_type: 'image/svg+xml',
            size: \${JSON.stringify(imageByteSize)},
            width: 24,
            height: 24,
            data_url: \${JSON.stringify(imageDataUrl)},
          }];
        },
      };
    })();
  \`, true);
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-image-file-input"]');
      const button = document.querySelector('[data-testid="chat-composer-image-attach-button"]');
      if (!input || !button) throw new Error('chat native picker smoke controls not found');
      let clickCount = 0;
      const hadOwnClick = Object.prototype.hasOwnProperty.call(input, 'click');
      const ownClick = hadOwnClick ? input.click : undefined;
      Object.defineProperty(input, 'click', { configurable: true, value: () => { clickCount += 1; } });
      try {
        button.click();
      } finally {
        delete input.click;
        if (hadOwnClick) Object.defineProperty(input, 'click', { configurable: true, value: ownClick });
      }
      if (clickCount !== 0) throw new Error('chat desktop image picker should not click hidden file input');
    })();
  \`, true);
  await waitFor(win, () => {
    const preview = document.querySelector('[data-testid="chat-composer-attachment-preview"]');
    return window.__chatNativePickerCalls === 1
      && preview
      && preview.getAttribute('data-attachment-name') === ${JSON.stringify(NATIVE_PICKER_IMAGE_NAME)}
      && preview.getAttribute('data-attachment-mime') === 'image/svg+xml'
      && Number(preview.getAttribute('data-attachment-size') || 0) > 0
      && preview.getAttribute('data-attachment-width') === '24'
      && preview.getAttribute('data-attachment-height') === '24';
  }, 'composer attachment preview from desktop native picker API');
  console.log('[electron-smoke] desktop native image picker API rendered attachment preview');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-attachment-remove\\"]').click()", true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-composer-attachment-preview"]'), 'removed native picker attachment preview');
  await win.webContents.executeJavaScript(\`
    (async () => {
      const input = document.querySelector('[data-testid="chat-image-file-input"]');
      if (!input) throw new Error('chat image file input not found');
      const blob = await fetch(\${JSON.stringify(imageDataUrl)}).then((response) => response.blob());
      const file = new File([blob], 'smoke-image.svg', { type: 'image/svg+xml' });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      Object.defineProperty(input, 'files', { configurable: true, value: transfer.files });
      input.dispatchEvent(new Event('change', { bubbles: true }));
      delete input.files;
    })();
  \`, true);
  await waitFor(win, () => {
    const preview = document.querySelector('[data-testid="chat-composer-attachment-preview"]');
    return preview
      && preview.getAttribute('data-attachment-name') === 'smoke-image.svg'
      && preview.getAttribute('data-attachment-mime') === 'image/svg+xml'
      && Number(preview.getAttribute('data-attachment-size') || 0) > 0
      && preview.getAttribute('data-attachment-width') === '24'
      && preview.getAttribute('data-attachment-height') === '24';
  }, 'composer attachment preview');
  console.log('[electron-smoke] attachment preview rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-composer-attachment-remove\\"]').click()", true);
  await waitFor(win, () => !document.querySelector('[data-testid="chat-composer-attachment-preview"]'), 'removed composer attachment preview');
  await waitFor(win, () => document.querySelector('button[aria-label="发送消息"]')?.disabled, 'disabled send button after attachment removal');
  console.log('[electron-smoke] attachment preview removed');
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('[data-testid="chat-image-file-input"]');
      if (!input) throw new Error('chat image file input not found');
      delete input.files;
      input.value = '';
    })();
  \`, true);
  await setChatImageInputFilesWithCdp(win, imageFilePaths);
  await waitFor(win, () => {
    const expectedNames = ${JSON.stringify(imageFileNames)};
    const previews = Array.from(document.querySelectorAll('[data-testid="chat-composer-attachment-preview"]'));
    const names = previews.map((preview) => preview.getAttribute('data-attachment-name'));
    const buttons = [
      document.querySelector('[data-testid="chat-header-image-attach-button"]'),
      document.querySelector('[data-testid="chat-composer-image-attach-button"]'),
    ];
    const input = document.querySelector('[data-testid="chat-image-file-input"]');
    return previews.length === expectedNames.length
      && expectedNames.every((name) => names.includes(name))
      && previews.every((preview) => (
        preview.getAttribute('data-attachment-mime') === 'image/svg+xml'
        && Number(preview.getAttribute('data-attachment-size') || 0) > 0
        && preview.getAttribute('data-attachment-width') === '24'
        && preview.getAttribute('data-attachment-height') === '24'
      ))
      && buttons.every((button) => button?.disabled)
      && input?.disabled;
  }, 'composer max attachment previews after removal');
  console.log('[electron-smoke] attachment previews rendered through CDP file input');
  await win.webContents.executeJavaScript(\`
    const input = document.querySelector('textarea.chat-input');
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(input, 'browser image attachment smoke');
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: 'browser image attachment smoke' }));
  \`, true);
  await waitFor(win, () => !document.querySelector('button[aria-label="发送消息"]')?.disabled, 'enabled send button');
  await win.webContents.executeJavaScript("document.querySelector('button[aria-label=\\"发送消息\\"]').closest('form').requestSubmit()", true);
  await waitFor(win, () => {
    const expectedNames = ${JSON.stringify(imageFileNames)};
    const items = Array.from(document.querySelectorAll('[data-testid="chat-message-attachment-item"]'));
    const names = items.map((item) => item.getAttribute('data-attachment-name'));
    return items.length === expectedNames.length
      && expectedNames.every((name) => names.includes(name))
      && items.every((item) => (
        item.getAttribute('data-attachment-id')
        && item.getAttribute('data-attachment-kind') === 'image'
        && item.getAttribute('data-attachment-mime') === 'image/svg+xml'
        && Number(item.getAttribute('data-attachment-size') || 0) > 0
      ));
  }, 'rendered message attachments');
  await waitFor(win, () => (
    !document.querySelector('[data-testid="chat-composer-attachment-preview"]')
    && document.querySelector('textarea.chat-input')?.value === ''
  ), 'composer cleared after image send');
  console.log('[electron-smoke] message attachments rendered');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-message-attachment-item\\"]').click()", true);
  await waitFor(win, () => {
    const modal = document.querySelector('[data-testid="chat-image-viewer-modal"]');
    const image = document.querySelector('[data-testid="chat-image-viewer-stage"] img');
    return modal
      && image?.getAttribute('alt') === 'smoke-image-cdp.svg'
      && image?.getAttribute('src')?.startsWith('data:image/svg+xml');
  }, 'image viewer modal with rendered image');
  console.log('[electron-smoke] image viewer opened');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"chat-image-viewer-close\\"]').click()", true);
  await waitFor(win, () => (
    !document.querySelector('[data-testid="chat-image-viewer-backdrop"]')
    && !document.querySelector('[data-testid="chat-image-viewer-modal"]')
    && !document.querySelector('[data-testid="chat-image-viewer-stage"]')
  ), 'closed image viewer modal');
  console.log('[electron-smoke] image viewer closed');
  await waitFor(win, () => {
    const reply = document.querySelector('[data-message-id="assistant-chat-image-ui-smoke-reply"]');
    const openRun = reply?.querySelector('[data-testid="chat-message-open-run-detail"]');
    return reply?.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && openRun
      && openRun.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && openRun.getAttribute('data-run-status') === 'completed'
      && openRun.textContent.includes('Agent Studio');
  }, 'image assistant reply Run Detail action');
  await win.webContents.executeJavaScript("document.querySelector('[data-message-id=\\"assistant-chat-image-ui-smoke-reply\\"] [data-testid=\\"chat-message-open-run-detail\\"]').click()", true);
  await waitFor(win, () => {
    const detail = document.querySelector('[data-testid="agent-run-detail"]');
    const result = document.querySelector('[data-testid="agent-run-detail-result"]');
    const task = document.querySelector('[data-testid="agent-run-detail-task"]');
    const events = Array.from(document.querySelectorAll('[data-testid="agent-run-detail-execution-event"]'));
    const eventTypes = events.map((node) => node.getAttribute('data-run-event'));
    const outputEvent = events.find((node) => node.getAttribute('data-run-event') === 'model.output.completed');
    const completedEvent = events.find((node) => node.getAttribute('data-run-event') === 'run.completed');
    return window.location.hash.includes(${JSON.stringify(RUN_ID)})
      && detail?.getAttribute('data-run-id') === ${JSON.stringify(RUN_ID)}
      && detail?.getAttribute('data-run-kind') === 'main_chat_run'
      && detail?.getAttribute('data-run-status') === 'completed'
      && detail?.getAttribute('data-task-id') === ${JSON.stringify(TASK_ID)}
      && detail?.getAttribute('data-session-id') === ${JSON.stringify(SESSION_ID)}
      && task?.textContent.includes(${JSON.stringify(RUN_GOAL)})
      && result?.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && events.length === 2
      && eventTypes.includes('model.output.completed')
      && eventTypes.includes('run.completed')
      && outputEvent?.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && completedEvent?.textContent.includes(${JSON.stringify(RUN_RESULT)})
      && events.every((node) => node.getAttribute('data-run-event-run-id') === ${JSON.stringify(RUN_ID)});
  }, 'image message Run Detail replay handoff');
  console.log('[electron-smoke] image message Run Detail replay verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const mainPath = path.join(tempDir, 'main.cjs');
  fs.writeFileSync(mainPath, script, 'utf8');
  return new Promise((resolve, reject) => {
    const child = spawn(ELECTRON, [mainPath], {
      cwd: FRONTEND,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, ELECTRON_ENABLE_LOGGING: '1' },
    });
    const timeout = setTimeout(() => {
      child.kill('SIGTERM');
      reject(new Error('electron smoke child timed out'));
    }, 45_000);
    child.stdout.on('data', (chunk) => process.stdout.write(chunk));
    child.stderr.on('data', (chunk) => process.stderr.write(chunk));
    child.on('error', (error) => {
      clearTimeout(timeout);
      fs.rmSync(tempDir, { recursive: true, force: true });
      reject(error);
    });
    child.on('exit', (code, signal) => {
      clearTimeout(timeout);
      fs.rmSync(tempDir, { recursive: true, force: true });
      if (code === 0) resolve();
      else reject(new Error(`electron smoke failed with code=${code} signal=${signal || ''}`));
    });
  });
}

async function main() {
  if (process.env.CI && process.platform === 'darwin') {
    log('running on CI macOS; Electron may require a display session');
  }
  const bridge = await startMockBridge();
  const vitePort = await pickPort();
  const vite = startVite(vitePort);
  try {
    const devUrl = `http://127.0.0.1:${vitePort}`;
    await waitForHttp(devUrl);
    await runElectronSmoke(devUrl, bridge.url);
    const payload = bridgeState.postPayloads[0];
    if (!payload) fail('Chat UI did not send a message');
    if (payload.text !== 'browser image attachment smoke') fail(`unexpected submitted text: ${payload.text}`);
    if (!payload.client_message_id) fail('Chat UI did not submit client_message_id for image message idempotency');
    if (!Array.isArray(payload.attachments) || payload.attachments.length !== CHAT_IMAGE_SMOKE_FILE_NAMES.length) {
      fail(`Chat UI did not submit exactly ${CHAT_IMAGE_SMOKE_FILE_NAMES.length} attachments`);
    }
    const attachmentNames = payload.attachments.map((attachment) => attachment.name);
    for (const expectedName of CHAT_IMAGE_SMOKE_FILE_NAMES) {
      if (!attachmentNames.includes(expectedName)) fail(`missing submitted attachment: ${expectedName}`);
    }
    for (const attachment of payload.attachments) {
      if (!attachment.id) fail('submitted attachment did not include a client attachment id');
      if (attachment.mime_type !== 'image/svg+xml') fail(`unexpected attachment mime: ${attachment.mime_type}`);
      if (!(Number(attachment.size) > 0)) fail(`unexpected attachment size: ${attachment.size}`);
      if (attachment.width !== 24 || attachment.height !== 24) {
        fail(`unexpected attachment dimensions: ${attachment.width}x${attachment.height}`);
      }
      if (!String(attachment.data_url || '').startsWith('data:image/svg+xml')) {
        fail('submitted attachment did not include image data URL');
      }
    }
    log('passed');
  } finally {
    killProcess(vite);
    await new Promise((resolve) => bridge.server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
