import {
  spawn,
  type ChildProcessWithoutNullStreams,
  type SpawnOptions,
} from 'node:child_process';
import { createHash, timingSafeEqual } from 'node:crypto';
import { createServer, type Server, type Socket } from 'node:net';
import path from 'node:path';

export const CUA_MCP_BRIDGE_PROTOCOL = 'oha-yachiyo-cua-mcp-bridge';
export const CUA_MCP_BRIDGE_VERSION = 1;

const LOOPBACK_HOST = '127.0.0.1';
const MAX_HANDSHAKE_BYTES = 4 * 1024;
// The backend keeps one execution session and may briefly open one independent
// readiness probe. Keeping this bound at two prevents connection accumulation.
const MAX_CONCURRENT_SESSIONS = 2;
const DEFAULT_HANDSHAKE_TIMEOUT_MS = 1_000;
const DEFAULT_TERMINATION_TIMEOUT_MS = 2_000;
const TOKEN_PATTERN = /^[0-9a-f]{64}$/;

type CuaMcpChildOptions = SpawnOptions & {
  env: NodeJS.ProcessEnv;
  shell: false;
  stdio: ['pipe', 'pipe', 'pipe'];
};

export type CuaMcpSpawnProcess = (
  command: string,
  args: string[],
  options: CuaMcpChildOptions,
) => ChildProcessWithoutNullStreams;

export type CuaMcpBridgeCredentials = {
  token: string;
  generation: string;
};

export type CuaMcpBridgeOptions = CuaMcpBridgeCredentials & {
  driverPath: string;
  hostBundleId: string;
  spawnProcess?: CuaMcpSpawnProcess;
  processEnv?: NodeJS.ProcessEnv;
  handshakeTimeoutMs?: number;
  terminationTimeoutMs?: number;
};

type ActiveSession = {
  socket: Socket;
  child: ChildProcessWithoutNullStreams;
  disposePromise: Promise<void> | null;
};

function validateCredentials(credentials: CuaMcpBridgeCredentials): void {
  if (!TOKEN_PATTERN.test(credentials.token)) {
    throw new Error('Cua MCP bridge token must be 64 lowercase hexadecimal characters');
  }
  if (!credentials.generation.trim() || credentials.generation.length > 128) {
    throw new Error('Cua MCP bridge generation must be a non-empty identifier');
  }
}

function secureTokenEquals(candidate: unknown, expected: string): boolean {
  const candidateText = typeof candidate === 'string' ? candidate : '';
  const candidateDigest = createHash('sha256').update(candidateText, 'utf8').digest();
  const expectedDigest = createHash('sha256').update(expected, 'utf8').digest();
  const equal = timingSafeEqual(candidateDigest, expectedDigest);
  return typeof candidate === 'string' && equal;
}

function minimalDriverEnvironment(source: NodeJS.ProcessEnv, hostBundleId: string): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of ['HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'LC_CTYPE', 'USER', 'LOGNAME']) {
    const value = source[key];
    if (typeof value === 'string' && value) environment[key] = value;
  }
  environment.PATH = '/usr/bin:/bin:/usr/sbin:/sbin';
  environment.CUA_DRIVER_EMBEDDED = '1';
  environment.CUA_DRIVER_HOST_BUNDLE_ID = hostBundleId;
  environment.CUA_DRIVER_RS_TELEMETRY_ENABLED = '0';
  return environment;
}

function defaultSpawnProcess(
  command: string,
  args: string[],
  options: CuaMcpChildOptions,
): ChildProcessWithoutNullStreams {
  return spawn(command, args, options);
}

export class CuaMcpBridge {
  readonly #driverPath: string;
  readonly #hostBundleId: string;
  readonly #spawnProcess: CuaMcpSpawnProcess;
  readonly #processEnv: NodeJS.ProcessEnv;
  readonly #handshakeTimeoutMs: number;
  readonly #terminationTimeoutMs: number;
  #credentials: CuaMcpBridgeCredentials;
  #server: Server | null = null;
  #startPromise: Promise<string> | null = null;
  #url = '';
  #pendingSockets = new Set<Socket>();
  #activeSessions = new Set<ActiveSession>();
  #rotating = false;
  #closing = false;
  #closePromise: Promise<void> | null = null;

  constructor(options: CuaMcpBridgeOptions) {
    validateCredentials(options);
    if (!options.driverPath.trim()) throw new Error('Cua MCP driver path is required');
    if (!options.hostBundleId.trim()) throw new Error('Cua MCP host bundle id is required');
    this.#driverPath = options.driverPath;
    this.#hostBundleId = options.hostBundleId;
    this.#credentials = { token: options.token, generation: options.generation };
    this.#spawnProcess = options.spawnProcess ?? defaultSpawnProcess;
    this.#processEnv = options.processEnv ?? process.env;
    this.#handshakeTimeoutMs = options.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS;
    this.#terminationTimeoutMs = options.terminationTimeoutMs ?? DEFAULT_TERMINATION_TIMEOUT_MS;
  }

  get url(): string {
    return this.#url;
  }

  get generation(): string {
    return this.#credentials.generation;
  }

  start(): Promise<string> {
    if (this.#url) return Promise.resolve(this.#url);
    if (this.#closing) return Promise.reject(new Error('Cua MCP bridge is closing'));
    if (this.#startPromise) return this.#startPromise;

    const server = createServer((socket) => this.#acceptSocket(socket));
    this.#server = server;
    let trackedStart: Promise<string>;
    trackedStart = new Promise<string>((resolve, reject) => {
      const cleanup = () => {
        server.off('error', onError);
        server.off('listening', onListening);
        server.off('close', onCloseBeforeListening);
      };
      const onError = (error: Error) => {
        cleanup();
        if (this.#server === server) this.#server = null;
        reject(error);
      };
      const onListening = () => {
        if (this.#closing) {
          cleanup();
          reject(new Error('Cua MCP bridge closed before listening'));
          return;
        }
        const address = server.address();
        if (!address || typeof address === 'string') {
          cleanup();
          reject(new Error('Cua MCP bridge did not receive a TCP address'));
          return;
        }
        cleanup();
        this.#url = `tcp://${LOOPBACK_HOST}:${address.port}`;
        server.on('error', () => {});
        resolve(this.#url);
      };
      const onCloseBeforeListening = () => {
        cleanup();
        if (this.#server === server) this.#server = null;
        reject(new Error('Cua MCP bridge closed before listening'));
      };
      server.once('error', onError);
      server.once('listening', onListening);
      server.once('close', onCloseBeforeListening);
      server.listen({ host: LOOPBACK_HOST, port: 0 });
    }).finally(() => {
      if (this.#startPromise === trackedStart) this.#startPromise = null;
    });
    this.#startPromise = trackedStart;
    return trackedStart;
  }

  async rotate(credentials: CuaMcpBridgeCredentials): Promise<void> {
    validateCredentials(credentials);
    if (this.#rotating) throw new Error('Cua MCP bridge credentials are already rotating');
    this.#rotating = true;
    this.#credentials = { ...credentials };
    this.#rejectPendingSockets();
    try {
      await this.endActiveSession();
    } finally {
      this.#rotating = false;
    }
  }

  endActiveSession(): Promise<void> {
    const sessions = [...this.#activeSessions];
    return Promise.all(
      sessions.map((session) => this.#disposeSession(session, true)),
    ).then(() => undefined);
  }

  close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closing = true;
    this.#closePromise = (async () => {
      this.#rejectPendingSockets();
      const closeSession = this.endActiveSession();
      const settleStart = this.#startPromise?.then(
        () => undefined,
        () => undefined,
      ) ?? Promise.resolve();
      const server = this.#server;
      this.#server = null;
      this.#url = '';
      const closeServer = !server
        ? Promise.resolve()
        : new Promise<void>((resolve) => {
            try {
              server.close(() => resolve());
            } catch {
              resolve();
            }
          });
      await Promise.all([closeSession, closeServer, settleStart]);
    })();
    return this.#closePromise;
  }

  #acceptSocket(socket: Socket): void {
    socket.on('error', () => {});
    socket.setNoDelay(true);
    if (
      this.#closing
      || this.#rotating
      || this.#pendingSockets.size + this.#activeSessions.size >= MAX_CONCURRENT_SESSIONS
    ) {
      socket.destroy();
      return;
    }

    this.#pendingSockets.add(socket);
    let handshakeBuffer = Buffer.alloc(0);
    const timeout = setTimeout(() => reject(), this.#handshakeTimeoutMs);
    const cleanup = () => {
      clearTimeout(timeout);
      socket.off('data', onData);
      socket.off('close', onCloseBeforeAuthentication);
    };
    const reject = () => {
      cleanup();
      this.#pendingSockets.delete(socket);
      socket.destroy();
    };
    const onCloseBeforeAuthentication = () => {
      cleanup();
      this.#pendingSockets.delete(socket);
    };
    const onData = (chunk: Buffer) => {
      handshakeBuffer = Buffer.concat([handshakeBuffer, chunk]);
      const newlineIndex = handshakeBuffer.indexOf(0x0a);
      if (newlineIndex < 0) {
        if (handshakeBuffer.length > MAX_HANDSHAKE_BYTES) reject();
        return;
      }
      if (newlineIndex > MAX_HANDSHAKE_BYTES) {
        reject();
        return;
      }

      socket.pause();
      cleanup();
      const handshakeLine = handshakeBuffer.subarray(0, newlineIndex).toString('utf8');
      const remaining = handshakeBuffer.subarray(newlineIndex + 1);
      handshakeBuffer = Buffer.alloc(0);
      let payload: unknown;
      try {
        payload = JSON.parse(handshakeLine);
      } catch {
        reject();
        return;
      }
      const record = payload && typeof payload === 'object'
        ? payload as Record<string, unknown>
        : null;
      if (
        !record
        || record.protocol !== CUA_MCP_BRIDGE_PROTOCOL
        || record.version !== CUA_MCP_BRIDGE_VERSION
        || !secureTokenEquals(record.token, this.#credentials.token)
        || !this.#pendingSockets.has(socket)
        || this.#activeSessions.size >= MAX_CONCURRENT_SESSIONS
        || this.#rotating
        || this.#closing
      ) {
        reject();
        return;
      }

      let child: ChildProcessWithoutNullStreams;
      try {
        child = this.#spawnProcess(
          this.#driverPath,
          [
            'mcp',
            '--embedded',
            '--host-bundle-id',
            this.#hostBundleId,
            // CuaDriver's visual agent-cursor overlay creates an AppKit UI
            // runloop and makes the helper frontmost on macOS. Consumer mode
            // is intentionally quiet; background AX/CGEvent delivery does not
            // depend on the overlay.
            '--no-overlay',
          ],
          {
            cwd: path.dirname(this.#driverPath),
            env: minimalDriverEnvironment(this.#processEnv, this.#hostBundleId),
            shell: false,
            stdio: ['pipe', 'pipe', 'pipe'],
            windowsHide: true,
          },
        );
      } catch {
        reject();
        return;
      }

      this.#pendingSockets.delete(socket);
      const session: ActiveSession = { socket, child, disposePromise: null };
      this.#activeSessions.add(session);
      child.stdin.on('error', () => {});
      child.stdout.on('error', () => {});
      child.stderr.on('error', () => {});
      child.stderr.resume();
      child.once('error', () => void this.#disposeSession(session, false));
      child.once('exit', () => void this.#disposeSession(session, false));
      socket.once('close', () => void this.#disposeSession(session, true));
      child.once('spawn', () => {
        if (
          !this.#activeSessions.has(session)
          || this.#closing
          || this.#rotating
          || socket.destroyed
        ) {
          void this.#disposeSession(session, true);
          return;
        }
        socket.write(`${JSON.stringify({
          protocol: CUA_MCP_BRIDGE_PROTOCOL,
          version: CUA_MCP_BRIDGE_VERSION,
          ok: true,
        })}\n`);
        if (remaining.length > 0) child.stdin.write(remaining);
        socket.pipe(child.stdin);
        child.stdout.pipe(socket);
        socket.resume();
      });
    };

    socket.on('data', onData);
    socket.once('close', onCloseBeforeAuthentication);
  }

  #rejectPendingSockets(): void {
    const sockets = [...this.#pendingSockets];
    this.#pendingSockets.clear();
    for (const socket of sockets) socket.destroy();
  }

  #disposeSession(session: ActiveSession, terminateChild: boolean): Promise<void> {
    if (session.disposePromise) return session.disposePromise;
    const disposePromise = Promise.resolve().then(async () => {
      session.socket.unpipe(session.child.stdin);
      session.child.stdout.unpipe(session.socket);
      if (!session.socket.destroyed) session.socket.destroy();
      if (terminateChild) await this.#terminateChild(session.child);
    }).finally(() => {
      this.#activeSessions.delete(session);
    });
    session.disposePromise = disposePromise;
    return disposePromise;
  }

  #terminateChild(child: ChildProcessWithoutNullStreams): Promise<void> {
    if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
    return new Promise((resolve) => {
      let settled = false;
      let forceTimer: NodeJS.Timeout | null = null;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(termTimer);
        if (forceTimer) clearTimeout(forceTimer);
        child.off('exit', finish);
        child.off('error', finish);
        resolve();
      };
      const termTimer = setTimeout(() => {
        try {
          child.kill('SIGKILL');
        } catch {
          finish();
          return;
        }
        forceTimer = setTimeout(finish, this.#terminationTimeoutMs);
      }, this.#terminationTimeoutMs);
      child.once('exit', finish);
      child.once('error', finish);
      try {
        child.kill('SIGTERM');
      } catch {
        finish();
      }
    });
  }
}
