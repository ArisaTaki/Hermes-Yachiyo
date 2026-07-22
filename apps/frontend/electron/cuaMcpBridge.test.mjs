import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import net from 'node:net';
import test from 'node:test';

import {
  CUA_MCP_BRIDGE_PROTOCOL,
  CUA_MCP_BRIDGE_VERSION,
  CuaMcpBridge,
} from '../dist-electron/cuaMcpBridge.js';

const TOKEN_A = 'a'.repeat(64);
const TOKEN_B = 'b'.repeat(64);

function lineReader(socket) {
  let buffer = Buffer.alloc(0);
  const waiting = [];
  socket.on('data', (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    while (waiting.length > 0) {
      const newline = buffer.indexOf(0x0a);
      if (newline < 0) break;
      const resolve = waiting.shift();
      const line = buffer.subarray(0, newline).toString('utf8');
      buffer = buffer.subarray(newline + 1);
      resolve(line);
    }
  });
  return () => new Promise((resolve) => {
    const newline = buffer.indexOf(0x0a);
    if (newline >= 0) {
      const line = buffer.subarray(0, newline).toString('utf8');
      buffer = buffer.subarray(newline + 1);
      resolve(line);
      return;
    }
    waiting.push(resolve);
  });
}

function connect(url) {
  const parsed = new URL(url);
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({
      host: parsed.hostname,
      port: Number(parsed.port),
    });
    socket.once('connect', () => resolve(socket));
    socket.once('error', reject);
  });
}

function waitForClose(socket) {
  if (socket.destroyed) return Promise.resolve();
  return new Promise((resolve) => socket.once('close', resolve));
}

function waitForExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => child.once('exit', resolve));
}

function handshake(token) {
  return `${JSON.stringify({
    protocol: CUA_MCP_BRIDGE_PROTOCOL,
    version: CUA_MCP_BRIDGE_VERSION,
    token,
  })}\n`;
}

function echoSpawnRecorder({ ignoreSigterm = false } = {}) {
  const calls = [];
  const children = [];
  const source = ignoreSigterm
    ? "process.on('SIGTERM',()=>{});process.stdin.pipe(process.stdout);setInterval(()=>{},1000)"
    : 'process.stdin.pipe(process.stdout)';
  const spawnProcess = (command, args, options) => {
    calls.push({ command, args: [...args], options });
    const child = spawn(process.execPath, ['-e', source], {
      env: { PATH: process.env.PATH },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    children.push(child);
    return child;
  };
  return { calls, children, spawnProcess };
}

function bridgeOptions(spawnProcess, overrides = {}) {
  return {
    driverPath: '/Applications/Oha-Yachiyo.app/Contents/Resources/computer-use/macos/OhaCuaDriver.app/Contents/MacOS/cua-driver',
    hostBundleId: 'io.github.arisataki.oha-yachiyo',
    token: TOKEN_A,
    generation: 'generation-a',
    spawnProcess,
    processEnv: {
      HOME: '/Users/tester',
      PATH: '/usr/bin:/bin',
      LANG: 'zh_CN.UTF-8',
      OPENAI_API_KEY: 'must-not-reach-child',
      OHA_YACHIYO_CUA_MCP_BRIDGE_TOKEN: TOKEN_A,
    },
    handshakeTimeoutMs: 500,
    terminationTimeoutMs: 100,
    ...overrides,
  };
}

test('authenticates before spawning and forwards raw newline MCP traffic', async (t) => {
  const recorder = echoSpawnRecorder();
  const bridge = new CuaMcpBridge(bridgeOptions(recorder.spawnProcess));
  t.after(() => bridge.close());
  const url = await bridge.start();
  assert.match(url, /^tcp:\/\/127\.0\.0\.1:\d+$/);

  const socket = await connect(url);
  t.after(() => socket.destroy());
  const readLine = lineReader(socket);
  assert.equal(recorder.calls.length, 0);
  const message = JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' });
  socket.write(`${handshake(TOKEN_A)}${message}\n`);

  const ack = JSON.parse(await readLine());
  assert.deepEqual(ack, {
    protocol: CUA_MCP_BRIDGE_PROTOCOL,
    version: CUA_MCP_BRIDGE_VERSION,
    ok: true,
  });
  assert.equal(recorder.calls.length, 1);
  const call = recorder.calls[0];
  assert.equal(call.command, bridgeOptions().driverPath);
  assert.deepEqual(call.args, [
    'mcp',
    '--embedded',
    '--host-bundle-id',
    'io.github.arisataki.oha-yachiyo',
    '--no-overlay',
  ]);
  assert.equal(call.options.shell, false);
  assert.deepEqual(call.options.stdio, ['pipe', 'pipe', 'pipe']);
  assert.equal(call.options.env.CUA_DRIVER_EMBEDDED, '1');
  assert.equal(call.options.env.CUA_DRIVER_HOST_BUNDLE_ID, 'io.github.arisataki.oha-yachiyo');
  assert.equal(call.options.env.CUA_DRIVER_RS_TELEMETRY_ENABLED, '0');
  assert.equal(call.options.env.PATH, '/usr/bin:/bin:/usr/sbin:/sbin');
  assert.equal(call.options.env.OPENAI_API_KEY, undefined);
  assert.equal(call.options.env.OHA_YACHIYO_CUA_MCP_BRIDGE_TOKEN, undefined);

  assert.equal(await readLine(), message);
});

test('rejects invalid and oversized handshakes without spawning', async (t) => {
  const recorder = echoSpawnRecorder();
  const bridge = new CuaMcpBridge(bridgeOptions(recorder.spawnProcess, {
    handshakeTimeoutMs: 40,
  }));
  t.after(() => bridge.close());
  const url = await bridge.start();

  const invalid = await connect(url);
  invalid.write(handshake(TOKEN_B));
  await waitForClose(invalid);
  assert.equal(recorder.calls.length, 0);

  const oversized = await connect(url);
  oversized.write(`${'x'.repeat(4097)}\n`);
  await waitForClose(oversized);
  assert.equal(recorder.calls.length, 0);

  const idle = await connect(url);
  await waitForClose(idle);
  assert.equal(recorder.calls.length, 0);
});

test('bounds execution plus diagnostic sessions and rotation terminates both', async (t) => {
  const recorder = echoSpawnRecorder({ ignoreSigterm: true });
  const bridge = new CuaMcpBridge(bridgeOptions(recorder.spawnProcess, {
    terminationTimeoutMs: 40,
  }));
  t.after(() => bridge.close());
  const url = await bridge.start();

  const first = await connect(url);
  const firstReadLine = lineReader(first);
  first.write(handshake(TOKEN_A));
  await firstReadLine();
  assert.equal(recorder.calls.length, 1);
  await new Promise((resolve) => setTimeout(resolve, 50));

  const diagnostic = await connect(url);
  const diagnosticReadLine = lineReader(diagnostic);
  diagnostic.write(handshake(TOKEN_A));
  assert.equal(JSON.parse(await diagnosticReadLine()).ok, true);
  assert.equal(recorder.calls.length, 2);
  await new Promise((resolve) => setTimeout(resolve, 50));

  const overCapacity = await connect(url);
  overCapacity.write(handshake(TOKEN_A));
  await waitForClose(overCapacity);
  assert.equal(recorder.calls.length, 2);

  const firstClosed = waitForClose(first);
  const diagnosticClosed = waitForClose(diagnostic);
  const rotation = bridge.rotate({ token: TOKEN_B, generation: 'generation-b' });
  await firstClosed;
  await diagnosticClosed;
  const duringRotation = await connect(url);
  duringRotation.write(handshake(TOKEN_B));
  await waitForClose(duringRotation);
  assert.equal(recorder.calls.length, 2);
  await rotation;
  await waitForExit(recorder.children[0]);
  await waitForExit(recorder.children[1]);
  assert.equal(recorder.children[0].signalCode, 'SIGKILL');
  assert.equal(recorder.children[1].signalCode, 'SIGKILL');

  const stale = await connect(url);
  stale.write(handshake(TOKEN_A));
  await waitForClose(stale);
  assert.equal(recorder.calls.length, 2);

  const second = await connect(url);
  t.after(() => second.destroy());
  const secondReadLine = lineReader(second);
  second.write(handshake(TOKEN_B));
  assert.equal(JSON.parse(await secondReadLine()).ok, true);
  assert.equal(recorder.calls.length, 3);
});

test('close and rotation share cleanup for both active sessions', async () => {
  const recorder = echoSpawnRecorder({ ignoreSigterm: true });
  const bridge = new CuaMcpBridge(bridgeOptions(recorder.spawnProcess, {
    terminationTimeoutMs: 40,
  }));
  const url = await bridge.start();
  const first = await connect(url);
  const second = await connect(url);
  const firstReadLine = lineReader(first);
  const secondReadLine = lineReader(second);
  first.write(handshake(TOKEN_A));
  second.write(handshake(TOKEN_A));
  await Promise.all([firstReadLine(), secondReadLine()]);
  assert.equal(recorder.calls.length, 2);

  const firstClosed = waitForClose(first);
  const secondClosed = waitForClose(second);
  const rotation = bridge.rotate({ token: TOKEN_B, generation: 'generation-b' });
  const closing = bridge.close();
  await Promise.all([firstClosed, secondClosed, rotation, closing]);
  await Promise.all(recorder.children.map(waitForExit));

  assert.ok(
    recorder.children.every(
      (child) => child.signalCode === 'SIGTERM' || child.signalCode === 'SIGKILL',
    ),
  );
  await assert.rejects(connect(url));
});

test('start and close in the same turn both settle', async () => {
  const recorder = echoSpawnRecorder();
  const bridge = new CuaMcpBridge(bridgeOptions(recorder.spawnProcess));

  const starting = bridge.start();
  const closing = bridge.close();

  await assert.rejects(starting, /closed before listening|closing/);
  await closing;
  assert.equal(recorder.calls.length, 0);
});

test('does not acknowledge a child that fails to spawn', async (t) => {
  const calls = [];
  const spawnProcess = (command, args, options) => {
    calls.push({ command, args, options });
    return spawn('/definitely/missing/oha-yachiyo-cua-driver', [], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  };
  const bridge = new CuaMcpBridge(bridgeOptions(spawnProcess));
  t.after(() => bridge.close());
  const socket = await connect(await bridge.start());
  const received = [];
  socket.on('data', (chunk) => received.push(chunk));

  socket.write(handshake(TOKEN_A));
  await waitForClose(socket);

  assert.equal(calls.length, 1);
  assert.equal(Buffer.concat(received).length, 0);
});
