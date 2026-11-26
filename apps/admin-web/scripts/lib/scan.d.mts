export interface Finding { file: string; rule: string; sample: string }
export const SECRET_PATTERNS: ReadonlyArray<readonly [string, RegExp]>;
export const ALLOWED_URL_PREFIXES: readonly string[];
export const SOURCE_FORBIDDEN: ReadonlyArray<readonly [string, RegExp]>;
export function scanSecrets(text: string, file: string): Finding[];
export function scanUrls(text: string, file: string, allowed?: readonly string[]): Finding[];
export function scanSource(text: string, file: string): Finding[];
export function checkCsp(html: string): string[];
