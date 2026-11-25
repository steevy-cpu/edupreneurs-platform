/**
 * The harness may only touch this checkout's own stack. Pure Node: no Docker, no database
 * (container liveness is injected).
 */
import crypto from 'node:crypto';
import path from 'node:path';

/* eslint-disable @typescript-eslint/no-require-imports */
const stack = require('../support/localStack') as {
  parseSupabaseConfig: (text: string) => { projectId: string | null; apiPort: number | null; dbPort: number | null };
  deriveTarget: (input: {
    configText: string;
    env: Record<string, string>;
    processEnv?: Record<string, string | undefined>;
    isRunning?: (name: string) => boolean;
  }) => { projectId: string; dbContainer: string; kongContainer: string; dbPort: number; apiPort: number };
  repoTag: (root?: string) => string;
  PID_FILE: string;
  REPO_ROOT: string;
};

const config = (id: string, api = 57421, db = 57422) =>
  `# comment\nproject_id = "${id}"\n\n[api]\nenabled = true\nport = ${api}\n\n[db]\nport = ${db} # local\nshadow_port = 57420\n\n[studio]\nport = 57423\n`;
const env = (dbPort = 57422, apiPort = 57421) => ({
  LOCAL_ADMIN_DATABASE_URL: `postgresql://u:p@127.0.0.1:${dbPort}/postgres`,
  LOCAL_SUPABASE_URL: `http://127.0.0.1:${apiPort}`,
});
const up = () => true;

describe('test harness target derivation', () => {
  test('reads project id and the api / db ports, ignoring other sections', () => {
    expect(stack.parseSupabaseConfig(config('edu-x'))).toEqual({ projectId: 'edu-x', apiPort: 57421, dbPort: 57422 });
  });

  test('derives container names from the project id', () => {
    const target = stack.deriveTarget({ configText: config('edu-x'), env: env(), processEnv: {}, isRunning: up });
    expect(target.dbContainer).toBe('supabase_db_edu-x');
    expect(target.kongContainer).toBe('supabase_kong_edu-x');
    expect(target.dbPort).toBe(57422);
  });

  test('checks the container derived from this repo, not any other', () => {
    const asked: string[] = [];
    stack.deriveTarget({
      configText: config('edu-x'), env: env(), processEnv: {},
      isRunning: (name) => (asked.push(name), true),
    });
    expect(asked).toEqual(['supabase_db_edu-x']);
  });

  test('refuses when the derived container is not running', () => {
    expect(() =>
      stack.deriveTarget({ configText: config('edu-x'), env: env(), processEnv: {}, isRunning: () => false }),
    ).toThrow(/supabase_db_edu-x is not running/);
  });

  test('refuses the shared stack unless explicitly allowed', () => {
    const input = { configText: config('mon-edupreneur', 54321, 54322), env: env(54322, 54321), isRunning: up };
    expect(() => stack.deriveTarget({ ...input, processEnv: {} })).toThrow(/shared stack/);
    expect(() => stack.deriveTarget({ ...input, processEnv: { EDU_TEST_ALLOW_SHARED_STACK: '0' } })).toThrow(/shared stack/);
    expect(stack.deriveTarget({ ...input, processEnv: { EDU_TEST_ALLOW_SHARED_STACK: '1' } }).dbContainer).toBe(
      'supabase_db_mon-edupreneur',
    );
  });

  test('refuses when the .env database port is another stack', () => {
    expect(() =>
      stack.deriveTarget({ configText: config('edu-x'), env: env(54322), processEnv: {}, isRunning: up }),
    ).toThrow(/does not match supabase\/config.toml \[db\] port/);
  });

  test('refuses when the .env API URL port is another stack', () => {
    expect(() =>
      stack.deriveTarget({ configText: config('edu-x'), env: env(57422, 54321), processEnv: {}, isRunning: up }),
    ).toThrow(/LOCAL_SUPABASE_URL port/);
  });

  test('refuses a missing .env, a remote database host and a config without project_id', () => {
    expect(() => stack.deriveTarget({ configText: config('edu-x'), env: {}, processEnv: {}, isRunning: up })).toThrow(
      /LOCAL_ADMIN_DATABASE_URL is missing/,
    );
    expect(() =>
      stack.deriveTarget({
        configText: config('edu-x'),
        env: { LOCAL_ADMIN_DATABASE_URL: 'postgresql://u:p@db.example.com:57422/postgres' },
        processEnv: {}, isRunning: up,
      }),
    ).toThrow(/not this machine/);
    expect(() =>
      stack.deriveTarget({ configText: '[api]\nport = 1\n[db]\nport = 2\n', env: env(), processEnv: {}, isRunning: up }),
    ).toThrow(/no project_id/);
  });

  test('pid file is unique per checkout', () => {
    expect(stack.repoTag('/a/worktree-1')).not.toBe(stack.repoTag('/a/worktree-2'));
    expect(path.basename(stack.PID_FILE)).toBe(
      `edu-mobile-test-api-${crypto.createHash('sha256').update(stack.REPO_ROOT).digest('hex').slice(0, 12)}.pid`,
    );
  });
});
