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
const VOICE_ARCHIVE_PATH = '/tmp/oha-yachiyo-proactive-tts-ui-smoke-voice.zip';
const TEST_TEXT = 'Proactive TTS Electron smoke text.';

const bridgeState = {
  gsvServiceInstallRequests: 0,
  gsvServiceInstalled: false,
  gsvServiceStatusPayloads: [],
  gsvServiceUninstallRequests: 0,
  settings: initialSettings(),
  permissionPayload: null,
  proactivePayload: null,
  ttsTestPayload: null,
  voiceImportPayload: null,
  settingsPayloads: [],
};

function log(message) {
  process.stdout.write(`[proactive-tts-ui-smoke] ${message}\n`);
}

function initialTtsSettings() {
  return {
    enabled: true,
    provider: 'gpt-sovits',
    endpoint: '',
    command: 'say {text}',
    voice: 'smoke-yachiyo',
    timeout_seconds: 30,
    max_chars: 80,
    notification_prompt: 'Speak concise proactive care smoke text.',
    gsv_base_url: 'http://127.0.0.1:9880',
    gsv_service_workdir: '/tmp/gpt-sovits-smoke',
    gsv_service_command: 'python api_v2.py -a 127.0.0.1 -p 9880',
    gsv_gpt_weights_path: '/tmp/yachiyo-gpt.ckpt',
    gsv_sovits_weights_path: '/tmp/yachiyo-sovits.pth',
    gsv_ref_audio_path: '/tmp/yachiyo-ref.wav',
    gsv_ref_audio_text: '月見八千代です。',
    gsv_ref_audio_language: 'ja',
    gsv_aux_ref_audio_path: '',
    gsv_text_language: 'zh',
    gsv_top_k: 15,
    gsv_top_p: 1,
    gsv_temperature: 1,
    gsv_text_split_method: 'cut1',
    gsv_batch_size: 1,
    gsv_batch_threshold: 0.75,
    gsv_split_bucket: true,
    gsv_speed_factor: 1,
    gsv_fragment_interval: 0.3,
    gsv_streaming_mode: false,
    gsv_seed: -1,
    gsv_parallel_infer: false,
    gsv_repetition_penalty: 1.35,
    gsv_media_type: 'wav',
  };
}

function initialSettings() {
  const tts = initialTtsSettings();
  const proactive = {
    proactive_enabled: true,
    proactive_desktop_watch_enabled: true,
    proactive_interval_seconds: 300,
    proactive_trigger_probability: 1,
  };
  return {
    tts,
    mode_settings: {
      bubble: { config: { ...proactive, tts } },
      live2d: { config: { ...proactive, tts } },
    },
  };
}

function voiceResource() {
  return {
    ok: true,
    installed: true,
    default_assets_root: '/tmp/oha-yachiyo-voices',
    default_assets_root_display: '~/Library/Application Support/Oha-Yachiyo/voices',
    default_service_workdir: '/tmp/gpt-sovits-smoke',
    default_service_workdir_display: '~/AI/GPT-SoVITS',
    default_service_command: 'python api_v2.py -a 127.0.0.1 -p 9880',
    releases_url: 'https://example.test/oha-yachiyo/releases',
    voice_package_url: 'https://example.test/oha-yachiyo/yachiyo-voice.zip',
    help_text: 'Voice resource smoke ready.',
    service_help_text: 'Service resource smoke ready.',
    service_project_url: 'https://example.test/gpt-sovits',
  };
}

function ttsStatus() {
  return {
    ok: true,
    success: true,
    tool: 'proactive_tts',
    provider: bridgeState.settings.tts.provider,
    message: 'TTS runtime smoke ready',
    spoken_text: 'last smoke utterance',
  };
}

function gsvServiceStatus() {
  return {
    reachable: true,
    workdir_display: '~/AI/GPT-SoVITS',
    workdir_exists: true,
    command_configured: true,
    launch_agent_installed: bridgeState.gsvServiceInstalled,
    launch_agent_running: bridgeState.gsvServiceInstalled,
    plist_path_display: bridgeState.gsvServiceInstalled ? '~/Library/LaunchAgents/com.oha-yachiyo.gpt-sovits.plist' : '',
    api_process: {
      running: true,
      pid: 9880,
      command: 'python api_v2.py',
      port: 9880,
    },
    platform_supported: true,
    tools: { python: true, git: true },
    models: { gpt: true, sovits: true },
  };
}

function updatedSettingsFromChanges(changes = {}) {
  const currentTts = { ...bridgeState.settings.tts };
  const proactive = {
    proactive_enabled: bridgeState.settings.mode_settings.live2d.config.proactive_enabled,
    proactive_desktop_watch_enabled: bridgeState.settings.mode_settings.live2d.config.proactive_desktop_watch_enabled,
    proactive_interval_seconds: bridgeState.settings.mode_settings.live2d.config.proactive_interval_seconds,
    proactive_trigger_probability: bridgeState.settings.mode_settings.live2d.config.proactive_trigger_probability,
  };
  for (const [key, value] of Object.entries(changes)) {
    if (key.startsWith('tts.')) {
      currentTts[key.slice(4)] = value;
    } else if (key.endsWith('.proactive_enabled')) {
      proactive.proactive_enabled = Boolean(value);
    } else if (key.endsWith('.proactive_desktop_watch_enabled')) {
      proactive.proactive_desktop_watch_enabled = Boolean(value);
    } else if (key.endsWith('.proactive_interval_seconds')) {
      proactive.proactive_interval_seconds = Number(value);
    } else if (key.endsWith('.proactive_trigger_probability')) {
      proactive.proactive_trigger_probability = Number(value);
    }
  }
  bridgeState.settings = {
    tts: currentTts,
    mode_settings: {
      bubble: { config: { ...proactive, tts: currentTts } },
      live2d: { config: { ...proactive, tts: currentTts } },
    },
  };
  return bridgeState.settings;
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
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS,PATCH,DELETE',
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

async function startMockBridge() {
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method === 'OPTIONS') {
        sendJson(response, 204, {});
        return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/ui/settings') {
        sendJson(response, 200, bridgeState.settings);
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/settings') {
        const body = await readRequestJson(request);
        bridgeState.settingsPayloads.push(body);
        sendJson(response, 200, {
          ok: true,
          app_state: updatedSettingsFromChanges(body.changes || {}),
        });
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/tts/status') {
        sendJson(response, 200, ttsStatus());
        return;
      }
      if (request.method === 'GET' && url.pathname === '/ui/tts/voice-resource') {
        sendJson(response, 200, voiceResource());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/tts/gpt-sovits/service-status') {
        const body = await readRequestJson(request);
        bridgeState.gsvServiceStatusPayloads.push(body);
        sendJson(response, 200, gsvServiceStatus());
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/tts/gpt-sovits/service/install') {
        await readRequestJson(request);
        bridgeState.gsvServiceInstallRequests += 1;
        bridgeState.gsvServiceInstalled = true;
        sendJson(response, 200, {
          ok: true,
          message: 'GPT-SoVITS service installed from UI smoke',
          status: gsvServiceStatus(),
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/tts/gpt-sovits/service/uninstall') {
        await readRequestJson(request);
        bridgeState.gsvServiceUninstallRequests += 1;
        bridgeState.gsvServiceInstalled = false;
        sendJson(response, 200, {
          ok: true,
          message: 'GPT-SoVITS service stopped from UI smoke',
          status: gsvServiceStatus(),
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/proactive/screen-permission/check') {
        const body = await readRequestJson(request);
        bridgeState.permissionPayload = body;
        sendJson(response, 200, {
          ok: true,
          allowed: true,
          message: 'Screen permission smoke ok',
          mode: 'screen',
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/proactive/test') {
        const body = await readRequestJson(request);
        bridgeState.proactivePayload = body;
        sendJson(response, 200, {
          ok: true,
          success: true,
          mode: body.mode || 'live2d',
          message: 'Proactive UI smoke queued',
          prompt: 'Observe desktop for proactive UI smoke.',
          response: 'Proactive UI smoke response.',
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/tts/voice-resource/import') {
        const body = await readRequestJson(request);
        bridgeState.voiceImportPayload = body;
        sendJson(response, 200, {
          ok: true,
          message: 'Voice package imported from UI smoke',
          imported_path: '/tmp/oha-yachiyo-voices/imported',
          imported_path_display: '~/Library/Application Support/Oha-Yachiyo/voices/imported',
          tts_settings: {
            ...bridgeState.settings.tts,
            enabled: true,
            provider: 'gpt-sovits',
            gsv_ref_audio_path: '/tmp/oha-yachiyo-voices/imported/yachiyo.wav',
            gsv_gpt_weights_path: '/tmp/oha-yachiyo-voices/imported/yachiyo.ckpt',
            gsv_sovits_weights_path: '/tmp/oha-yachiyo-voices/imported/yachiyo.pth',
          },
          resource: voiceResource(),
        });
        return;
      }
      if (request.method === 'POST' && url.pathname === '/ui/tts/test') {
        const body = await readRequestJson(request);
        bridgeState.ttsTestPayload = body;
        sendJson(response, 200, {
          ok: true,
          success: true,
          provider: bridgeState.settings.tts.provider,
          message: 'TTS smoke played',
          spoken_text: body.text || '',
        });
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
  const script = `
const { app, BrowserWindow } = require('electron');
const devUrl = ${JSON.stringify(devUrl)};
const bridgeUrl = ${JSON.stringify(bridgeUrl)};
const watchdog = setTimeout(() => {
  console.error('electron smoke timed out');
  app.exit(1);
}, 35000);
function waitFor(win, predicate, label, timeout = 18000) {
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
              provider: document.querySelector('[data-testid="proactive-tts-provider"]')?.value || '',
              status: document.querySelector('[data-testid="proactive-tts-status"]')?.textContent || '',
              runtime: document.querySelector('[data-testid="proactive-tts-runtime-status"]')?.textContent || '',
              proactiveResult: document.querySelector('[data-testid="proactive-test-result"]')?.textContent || '',
              ttsResult: document.querySelector('[data-testid="tts-test-result"]')?.textContent || '',
              archive: document.querySelector('[data-testid="tts-voice-archive-path"]')?.value || '',
              bodyText: document.body.textContent.slice(-1800),
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
  await win.loadURL(devUrl + '?bridge=' + encodeURIComponent(bridgeUrl) + '#/proactive-tts');
  await waitFor(win, () => (
    document.querySelector('[data-testid="proactive-tts-settings"]')
    && document.querySelector('[data-testid="proactive-tts-provider"]')?.value === 'gpt-sovits'
    && document.querySelector('[data-testid="tts-voice-import"]')
    && document.querySelector('[data-testid="tts-save-and-test"]')
  ), 'proactive TTS settings loaded');
  console.log('[electron-smoke] proactive TTS loaded');
  await waitFor(win, () => document.querySelector('[data-testid="proactive-tts-runtime-status"]')?.textContent.includes('TTS runtime smoke ready'), 'runtime status');
  await waitFor(win, () => (
    document.querySelector('[data-testid="tts-gsv-service-panel"]')
    && document.querySelector('[data-testid="tts-gsv-service-status"]')?.textContent.includes('API 已可达')
    && document.querySelector('[data-testid="tts-gsv-service-refresh"]')
    && document.querySelector('[data-testid="tts-gsv-service-install"]')
    && document.querySelector('[data-testid="tts-gsv-service-uninstall"]')
  ), 'GPT-SoVITS service controls');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"tts-gsv-service-refresh\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="tts-gsv-service-meta"]')?.textContent.includes('API 可达'), 'GPT-SoVITS service refresh');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"tts-gsv-service-install\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="proactive-tts-status"]')?.textContent.includes('GPT-SoVITS API 已就绪')
    && !document.querySelector('[data-testid="tts-gsv-service-uninstall"]')?.disabled
  ), 'GPT-SoVITS service install');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"tts-gsv-service-uninstall\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="confirm-dialog"]'), 'GPT-SoVITS service uninstall confirm');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"confirm-action\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="proactive-tts-status"]')?.textContent.includes('GPT-SoVITS service stopped from UI smoke')
    && document.querySelector('[data-testid="tts-gsv-service-status"]')?.textContent.includes('API 已可达')
  ), 'GPT-SoVITS service uninstall');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"proactive-screen-permission-check\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="proactive-test-result"]')?.textContent.includes('Screen permission smoke ok')
    && document.querySelector('[data-testid="proactive-tts-status"]')?.textContent.includes('Screen permission smoke ok')
  ), 'screen permission result');
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"proactive-test-run\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="proactive-test-result"]')?.textContent.includes('Proactive UI smoke queued')
    && document.querySelector('[data-testid="proactive-test-result"]')?.textContent.includes('Proactive UI smoke response.')
  ), 'proactive test result');
  await win.webContents.executeJavaScript(\`
    (() => {
      window.__ohaTtsVoiceArchivePickerCalls = 0;
      window.ohaDesktop = {
        ...(window.ohaDesktop || {}),
        chooseTtsVoiceArchive: async () => {
          window.__ohaTtsVoiceArchivePickerCalls += 1;
          return ${JSON.stringify(VOICE_ARCHIVE_PATH)};
        },
      };
    })();
  \`, true);
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"tts-voice-import\\"]').click()", true);
  await waitFor(win, () => document.querySelector('[data-testid="proactive-tts-status"]')?.textContent.includes('Voice package imported from UI smoke'), 'voice import result');
  const ttsPickerCalls = await win.webContents.executeJavaScript('window.__ohaTtsVoiceArchivePickerCalls || 0', true);
  if (ttsPickerCalls !== 1) {
    throw new Error('expected TTS voice archive picker to be called once, got ' + ttsPickerCalls);
  }
  await win.webContents.executeJavaScript(\`
    (() => {
      const input = document.querySelector('#tts-test-text-page');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(TEST_TEXT)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })();
  \`, true);
  await win.webContents.executeJavaScript("document.querySelector('[data-testid=\\"tts-save-and-test\\"]').click()", true);
  await waitFor(win, () => (
    document.querySelector('[data-testid="tts-test-result"]')?.textContent.includes('TTS smoke played')
    && document.querySelector('[data-testid="tts-test-result"]')?.textContent.includes(${JSON.stringify(TEST_TEXT)})
    && document.querySelector('[data-testid="proactive-tts-status"]')?.textContent.includes('TTS smoke played')
  ), 'TTS test result');
  console.log('[electron-smoke] proactive TTS actions verified');
  clearTimeout(watchdog);
  await win.close();
  app.quit();
}
main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  app.exit(1);
});
`;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'oha-proactive-tts-smoke-'));
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
    }, 50_000);
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

function assertMockBridgeContract() {
  if (!bridgeState.gsvServiceStatusPayloads.length) {
    throw new Error('GPT-SoVITS service status was not requested');
  }
  if (bridgeState.gsvServiceInstallRequests !== 1) {
    throw new Error(`unexpected GPT-SoVITS service install count: ${bridgeState.gsvServiceInstallRequests}`);
  }
  if (bridgeState.gsvServiceUninstallRequests !== 1) {
    throw new Error(`unexpected GPT-SoVITS service uninstall count: ${bridgeState.gsvServiceUninstallRequests}`);
  }
  if (!bridgeState.permissionPayload || bridgeState.permissionPayload.open_settings !== true) {
    throw new Error(`unexpected screen permission payload: ${JSON.stringify(bridgeState.permissionPayload)}`);
  }
  if (!bridgeState.proactivePayload || bridgeState.proactivePayload.mode !== 'live2d') {
    throw new Error(`unexpected proactive test payload: ${JSON.stringify(bridgeState.proactivePayload)}`);
  }
  if (!bridgeState.voiceImportPayload || bridgeState.voiceImportPayload.path !== VOICE_ARCHIVE_PATH) {
    throw new Error(`unexpected voice import payload: ${JSON.stringify(bridgeState.voiceImportPayload)}`);
  }
  if (!bridgeState.ttsTestPayload || bridgeState.ttsTestPayload.text !== TEST_TEXT) {
    throw new Error(`unexpected TTS test payload: ${JSON.stringify(bridgeState.ttsTestPayload)}`);
  }
  const ttsSettingsSave = bridgeState.settingsPayloads.find((payload) => payload?.changes?.['tts.provider'] === 'gpt-sovits');
  if (!ttsSettingsSave) {
    throw new Error(`TTS settings were not saved before test: ${JSON.stringify(bridgeState.settingsPayloads)}`);
  }
}

async function main() {
  const bridge = await startMockBridge();
  const vitePort = await pickPort();
  const vite = startVite(vitePort);
  try {
    const devUrl = `http://127.0.0.1:${vitePort}`;
    await waitForHttp(devUrl);
    await runElectronSmoke(devUrl, bridge.url);
    assertMockBridgeContract();
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
