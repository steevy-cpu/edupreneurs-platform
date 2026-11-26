/**
 * The harness may only touch this checkout's own stack. Pure Node: no Docker, no database
 * (container liveness is injected).
 */
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/* eslint-disable @typescript-eslint/no-require-imports */
const stack = require('../support/localStack') as {
  parseSupabaseConfig: (text: string) => { projectId: string | null; apiPort: number | null; dbPort: number | null };
  deriveTarget: (input: {
    configText: string;
    env: Record<string, string>;
    processEnv?: Record<string, string | undefined>;
    getPorts?: (name: string, internal: number) => number[];
  }) => { projectId: string; dbContainer: string; kongContainer: string; dbPort: number; apiPort: number };
  repoTag: (root?: string) => string;
  PID_FILE: string;
  REPO_ROOT: string;
};

const config = (id: string, api = 57421, db = 57422) =>
  `# comment\nproject_id = "${id}"\n\n[api]\nenabled = true\nport = ${api}\n\n[db]\nport = ${db} # local\nshadow_port = 57420\n\n[studio]\nport = 57423\n`;
const env = (dbPort = 57422, apiPort = 57421) => ({
  LOCAL_ADMIN_DATABASE_URL: `postgresql://u:p@127.0.0.1:${dbPort}/postgres`,
  EDU_DATABASE_URL: `postgresql+asyncpg://svc:p@127.0.0.1:${dbPort}/postgres`,
  EDU_AUTH_ISSUER: `http://127.0.0.1:${apiPort}/auth/v1`,
  EDU_AUTH_JWKS_URL: `http://127.0.0.1:${apiPort}/auth/v1/.well-known/jwks.json`,
  LOCAL_SUPABASE_URL: `http://127.0.0.1:${apiPort}`,
});
const up = (_name: string, internal: number) => [internal === 5432 ? 57422 : 57421];

describe('test harness target derivation', () => {
  test('reads project id and the api / db ports, ignoring other sections', () => {
    expect(stack.parseSupabaseConfig(config('edu-x'))).toEqual({ projectId: 'edu-x', apiPort: 57421, dbPort: 57422 });
  });

  test('derives container names from the project id', () => {
    const target = stack.deriveTarget({ configText: config('edu-x'), env: env(), processEnv: {}, getPorts: up });
    expect(target.dbContainer).toBe('supabase_db_edu-x');
    expect(target.kongContainer).toBe('supabase_kong_edu-x');
    expect(target.dbPort).toBe(57422);
  });

  test('checks the container derived from this repo, not any other', () => {
    const asked: string[] = [];
    stack.deriveTarget({
      configText: config('edu-x'), env: env(), processEnv: {},
      getPorts: (name, internal) => (asked.push(name), up(name, internal)),
    });
    expect(asked).toEqual(['supabase_db_edu-x', 'supabase_kong_edu-x']);
  });

  test('refuses when the derived container is not running', () => {
    expect(() =>
      stack.deriveTarget({ configText: config('edu-x'), env: env(), processEnv: {}, getPorts: () => [] }),
    ).toThrow(/supabase_db_edu-x does not publish/);
  });

  test('refuses the shared stack even with the legacy override', () => {
    const input = { configText: config('mon-edupreneur', 54321, 54322), env: env(54322, 54321), getPorts: up };
    expect(() => stack.deriveTarget({ ...input, processEnv: {} })).toThrow(/separate worktree with its own project_id/);
    expect(() => stack.deriveTarget({ ...input, processEnv: { EDU_TEST_ALLOW_SHARED_STACK: '0' } })).toThrow(/shared stack/);
    expect(() => stack.deriveTarget({ ...input, processEnv: { EDU_TEST_ALLOW_SHARED_STACK: '1' } })).toThrow(/shared stack/);
  });

  test('refuses when the .env database port is another stack', () => {
    expect(() =>
      stack.deriveTarget({ configText: config('edu-x'), env: env(54322), processEnv: {}, getPorts: up }),
    ).toThrow(/LOCAL_ADMIN_DATABASE_URL does not match/);
  });

  test('refuses when the .env API URL port is another stack', () => {
    expect(() =>
      stack.deriveTarget({ configText: config('edu-x'), env: env(57422, 54321), processEnv: {}, getPorts: up }),
    ).toThrow(/LOCAL_SUPABASE_URL does not match/);
  });

  test('refuses a missing .env, a remote database host and a config without project_id', () => {
    expect(() => stack.deriveTarget({ configText: config('edu-x'), env: {}, processEnv: {}, getPorts: up })).toThrow(
      /LOCAL_ADMIN_DATABASE_URL is missing/,
    );
    expect(() =>
      stack.deriveTarget({
        configText: config('edu-x'),
        env: { LOCAL_ADMIN_DATABASE_URL: 'postgresql://u:p@db.example.com:57422/postgres' },
        processEnv: {}, getPorts: up,
      }),
    ).toThrow(/not this machine/);
    expect(() =>
      stack.deriveTarget({ configText: '[api]\nport = 1\n[db]\nport = 2\n', env: env(), processEnv: {}, getPorts: up }),
    ).toThrow(/no project_id/);
  });

  test.each(['EDU_DATABASE_URL', 'edu_database_url', 'EDU_AUTH_ISSUER', 'EDU_AUTH_JWKS_URL', 'LOCAL_SUPABASE_URL'])(
    'refuses inherited %s redirection before Docker or HTTP', (key) => {
      const getPorts = jest.fn();
      expect(() => stack.deriveTarget({ configText: config('edu-x'), env: env(),
        processEnv: { [key]: 'http://localhost:42001' }, getPorts })).toThrow(/Conflicting/);
      expect(getPorts).not.toHaveBeenCalled();
    });

  test.each([
    { EDU_DATABASE_URL: 'postgresql+asyncpg://localhost:57422/postgres?host=other' },
    { EDU_AUTH_ISSUER: 'http://wrong.example:57421/auth/v1' },
    { EDU_AUTH_JWKS_URL: 'http://localhost:57421/auth/v1/other' },
  ])('refuses inconsistent root service or Auth endpoints', (override) => {
    expect(() => stack.deriveTarget({ configText: config('edu-x'), env: Object.assign(env(), override),
      processEnv: {}, getPorts: up })).toThrow();
  });

  test('refuses a gateway from another stack on the expected container name', () => {
    expect(() => stack.deriveTarget({ configText: config('edu-x'), env: env(), processEnv: {},
      getPorts: (_name, internal) => internal === 5432 ? [57422] : [42001] })).toThrow(/supabase_kong/);
  });

  test('pid file is unique per checkout', () => {
    expect(stack.repoTag('/a/worktree-1')).not.toBe(stack.repoTag('/a/worktree-2'));
    expect(path.basename(stack.PID_FILE)).toBe(
      `edu-mobile-test-api-${crypto.createHash('sha256').update(stack.REPO_ROOT).digest('hex').slice(0, 12)}.pid`,
    );
  });
});

describe('Android disposable backend', () => {
  const { deviceTarget } = require('../../scripts/e2e-target');
  const ports = { fastApiPort: 41000, apiPort: 41001 };
  const mobile = { EXPO_PUBLIC_API_URL: 'http://127.0.0.1:41000', EXPO_PUBLIC_SUPABASE_URL: 'http://127.0.0.1:41001' };
  test('rejects a client built for another service or an inherited redirect', () => {
    expect(() => deviceTarget(ports, { ...mobile, EXPO_PUBLIC_API_URL: 'http://localhost:42000' }, {}, ['localhost'])).toThrow();
    expect(() => deviceTarget(ports, mobile, { EXPO_PUBLIC_SUPABASE_URL: 'http://localhost:54321' }, ['127.0.0.1'])).toThrow();
  });
  test('records both reverse mappings on exactly the selected serial, including removal', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-record-adb-'));
    try {
      const adb = path.join(dir, 'adb');
      const record = path.join(dir, 'calls');
      fs.writeFileSync(adb, '#!/bin/sh\necho "$@" >> "$RECORD"\nif [ "$3" = get-serialno ]; then echo "$2"; fi\n', { mode: 0o700 });
      const script = path.resolve(__dirname, '../../scripts/android-device.sh');
      const target = deviceTarget(ports, mobile, {}, ['127.0.0.1']);
      const env = { ...process.env, ADB: adb, ANDROID_SERIAL: 'emulator-5572', RECORD: record,
        FASTAPI_PORT: String(target.fastApiPort), AUTH_PORT: String(target.apiPort) };
      const run = '. "$1"; select_android; android_backend reachable; android_backend unreachable';
      expect(() => execFileSync('bash', ['-ec', run, 'test', script], {
        env: { ...env, ANDROID_SERIAL: '' }, stdio: 'pipe',
      })).toThrow();
      expect(fs.existsSync(record)).toBe(false);
      execFileSync('bash', ['-ec', run, 'test', script], { env });
      expect(fs.readFileSync(record, 'utf8').trim().split('\n')).toEqual([
        '-s emulator-5572 get-serialno',
        '-s emulator-5572 reverse tcp:41000 tcp:41000', '-s emulator-5572 reverse tcp:41001 tcp:41001',
        '-s emulator-5572 reverse --remove tcp:41000', '-s emulator-5572 reverse --remove tcp:41001',
      ]);
    } finally { fs.rmSync(dir, { recursive: true, force: true }); }
  });
});
