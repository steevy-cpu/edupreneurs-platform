import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** Read a file of the monorepo. Vitest runs with cwd = apps/admin-web. */
export const repoFile = (rel: string): string => readFileSync(resolve(process.cwd(), '../..', rel), 'utf8');
