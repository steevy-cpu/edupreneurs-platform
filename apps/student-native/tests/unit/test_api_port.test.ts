/**
 * The mobile test API must never share a port with another checkout's server. Pure Node: no Docker,
 * no database, no real API (spawn/fetch/log reader are injected or stubbed with `http`/`net`).
 */
import http from 'node:http';
import net from 'node:net';

/* eslint-disable @typescript-eslint/no-require-imports */
const stack = require('../support/localStack') as {
  defaultApiPort: (root?: string) => number;
  resolveApiPort: (env?: Record<string, string | undefined>, root?: string) => number;
  assertPortFree: (port: number) => Promise<void>;
  awaitOwnApi: (input: {
    port: number;
    fetchFn?: (url: string) => Promise<{ ok: boolean }>;
    readLog: () => string;
    isAlive: () => boolean;
    kill: () => void;
    timeoutMs?: number;
    pollMs?: number;
    sleep?: (ms: number) => Promise<void>;
  }) => Promise<void>;
  API_PORT: number;
  API_URL: string;
  REPO_ROOT: string;
};

function listen<T extends net.Server | http.Server>(server: T): Promise<number> {
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve((server.address() as net.AddressInfo).port));
  });
}
const close = (server: net.Server | http.Server) => new Promise<void>((resolve) => server.close(() => resolve()));

describe('per-checkout test API port', () => {
  it('is deterministic, in 20000-29999, and differs between checkouts', () => {
    expect(stack.defaultApiPort('/a/checkout')).toBe(stack.defaultApiPort('/a/checkout'));
    const ports = ['/a/one', '/a/two', '/b/one', '/b/two', '/c'].map((root) => stack.defaultApiPort(root));
    for (const port of ports) {
      expect(port).toBeGreaterThanOrEqual(20000);
      expect(port).toBeLessThan(30000);
    }
    expect(new Set(ports).size).toBe(ports.length);
    expect(stack.defaultApiPort('/a/one')).not.toBe(8011);
  });

  it('uses the derived port for this checkout unless overridden', () => {
    expect(stack.resolveApiPort({}, stack.REPO_ROOT)).toBe(stack.defaultApiPort(stack.REPO_ROOT));
    expect(stack.API_URL).toBe(`http://127.0.0.1:${stack.API_PORT}`);
  });

  it('honours EDU_MOBILE_TEST_API_PORT and rejects invalid values', () => {
    expect(stack.resolveApiPort({ EDU_MOBILE_TEST_API_PORT: '23456' })).toBe(23456);
    for (const bad of ['abc', '0', '70000', '12.5', '-1']) {
      expect(() => stack.resolveApiPort({ EDU_MOBILE_TEST_API_PORT: bad })).toThrow(/EDU_MOBILE_TEST_API_PORT/);
    }
  });
});

describe('assertPortFree', () => {
  it('rejects while something listens and resolves once the port is free', async () => {
    const server = net.createServer();
    const port = await listen(server);
    await expect(stack.assertPortFree(port)).rejects.toThrow(/EDU_MOBILE_TEST_API_PORT/);
    await close(server);
    await expect(stack.assertPortFree(port)).resolves.toBeUndefined();
  });
});

describe('awaitOwnApi (readiness of the harness\'s OWN server)', () => {
  const ok = { ok: true };

  // Reproduces the original defect: another checkout's server answers 200 on /ready while our own uvicorn
  // died with "address already in use". The old code accepted that; it must now refuse and kill our group.
  it('REFUSES when a foreign server answers /ready but our own process failed to bind', async () => {
    const foreign = http.createServer((_req, res) => res.end('{"status":"ready","from":"ANOTHER CHECKOUT"}'));
    const port = await listen(foreign);
    try {
      const kill = jest.fn();
      await expect(
        stack.awaitOwnApi({
          port,
          readLog: () => 'ERROR: [Errno 98] error while attempting to bind on address: address already in use',
          isAlive: () => false,
          kill,
          pollMs: 1,
          timeoutMs: 500,
        }),
      ).rejects.toThrow(/exited|already in use/);
      expect(kill).toHaveBeenCalled();
    } finally {
      await close(foreign);
    }
  });

  it('REFUSES when a foreign server answers /ready and our process is alive but never logged binding', async () => {
    const foreign = http.createServer((_req, res) => res.end('{"status":"ready"}'));
    const port = await listen(foreign);
    try {
      const kill = jest.fn();
      await expect(
        stack.awaitOwnApi({ port, readLog: () => 'Started server process [1]', isAlive: () => true, kill, pollMs: 5, timeoutMs: 100 }),
      ).rejects.toThrow(/did not become ready/);
      expect(kill).toHaveBeenCalled();
    } finally {
      await close(foreign);
    }
  });

  it('does not accept a bind line for a different port', async () => {
    const kill = jest.fn();
    await expect(
      stack.awaitOwnApi({
        port: 24680, fetchFn: async () => ok, kill, isAlive: () => true, pollMs: 1, timeoutMs: 30,
        readLog: () => 'Uvicorn running on http://127.0.0.1:8011 (Press CTRL+C to quit)',
      }),
    ).rejects.toThrow();
  });

  it('accepts only when the log shows the bind, the process is alive and /ready answers', async () => {
    const kill = jest.fn();
    let polls = 0;
    await stack.awaitOwnApi({
      port: 24680,
      readLog: () => (polls++ < 2 ? '' : 'INFO: Uvicorn running on http://127.0.0.1:24680 (Press CTRL+C to quit)'),
      fetchFn: async () => ok,
      isAlive: () => true,
      kill,
      pollMs: 1,
    });
    expect(kill).not.toHaveBeenCalled();
  });
});
