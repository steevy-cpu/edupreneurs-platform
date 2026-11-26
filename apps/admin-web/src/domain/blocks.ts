/**
 * Lesson blocks — content format v1, transcribed from packages/contracts/content/lesson-blocks.schema.json.
 * Only these four block types exist. Format v2 (images, math, audio…) is NOT supported: it is not approved,
 * and this editor must not claim v2 renderer compatibility.
 */

export type Tone = 'tip' | 'warning' | 'remember';
export const TONES: readonly Tone[] = ['tip', 'warning', 'remember'];

export type Block =
  | { key: string; type: 'heading'; text: string }
  | { key: string; type: 'paragraph'; text: string }
  | { key: string; type: 'example'; title?: string; steps: string[] }
  | { key: string; type: 'callout'; tone: Tone; text: string };

export type BlockType = Block['type'];
export const BLOCK_TYPES: readonly BlockType[] = ['heading', 'paragraph', 'example', 'callout'];

export const LIMITS = { maxBlocks: 200, heading: 200, text: 4000, title: 200, steps: 20, step: 500 } as const;
export const KEY_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export interface Issue {
  /** Stable rule code, shown inline (Admin-00 doc 1 §B). */
  code: string;
  message: string;
  blockKey?: string;
  /** Index of the block in the list, when known. */
  index?: number;
}

// Control characters, zero-width / bidi-override characters and the BOM are refused (plain-text rule).
// Code points refused by the plain-text rule: control characters, zero-width and bidi-override characters, BOM.
const INVISIBLE_RANGES: ReadonlyArray<readonly [number, number]> = [[0x0, 0x8], [0xb, 0xc], [0xe, 0x1f], [0x7f, 0x9f], [0x200b, 0x200f], [0x202a, 0x202e], [0x2060, 0x2064], [0xfeff, 0xfeff]];
const hasInvisible = (s: string): boolean => [...s].some((ch) => { const c = ch.codePointAt(0)!; return INVISIBLE_RANGES.some(([a, b]) => c >= a && c <= b); });
const MARKUP = /<\/?[a-zA-Z!]/;

function checkText(value: unknown, max: number, label: string, base: Pick<Issue, 'blockKey' | 'index'>, out: Issue[]): void {
  if (typeof value !== 'string' || value.trim().length === 0) {
    out.push({ ...base, code: 'text_empty', message: `${label} : texte vide.` });
    return;
  }
  if (value.length > max) out.push({ ...base, code: 'text_too_long', message: `${label} : ${value.length} caractères, maximum ${max}.` });
  if (hasInvisible(value)) out.push({ ...base, code: 'control_char', message: `${label} : caractère de contrôle ou invisible interdit.` });
  if (MARKUP.test(value)) out.push({ ...base, code: 'markup', message: `${label} : le balisage (HTML) est interdit, texte brut seulement.` });
}

const ALLOWED_FIELDS: Record<BlockType, readonly string[]> = {
  heading: ['key', 'type', 'text'],
  paragraph: ['key', 'type', 'text'],
  example: ['key', 'type', 'title', 'steps'],
  callout: ['key', 'type', 'tone', 'text'],
};

/** Validate against the v1 contract. Accepts `unknown` so imported/edited data is checked, not trusted. */
export function validateBlocks(blocks: unknown): Issue[] {
  const out: Issue[] = [];
  if (!Array.isArray(blocks) || blocks.length < 1) {
    return [{ code: 'block_count', message: 'Une leçon contient au moins un bloc.' }];
  }
  if (blocks.length > LIMITS.maxBlocks) out.push({ code: 'block_count', message: `Maximum ${LIMITS.maxBlocks} blocs.` });
  const seen = new Set<string>();
  blocks.forEach((raw: unknown, index) => {
    const b = (raw ?? {}) as Record<string, unknown>;
    const key = typeof b.key === 'string' ? b.key : undefined;
    const base = { blockKey: key, index };
    if (!key || !KEY_PATTERN.test(key)) out.push({ ...base, code: 'key_pattern', message: `Bloc ${index + 1} : identifiant invalide (a-z, 0-9, tirets, 64 max).` });
    else if (seen.has(key)) out.push({ ...base, code: 'key_duplicate', message: `Bloc ${index + 1} : identifiant « ${key} » en double.` });
    else seen.add(key);

    const type = b.type as BlockType;
    if (!BLOCK_TYPES.includes(type)) {
      out.push({ ...base, code: 'unknown_type', message: `Bloc ${index + 1} : type « ${String(b.type)} » inconnu. Seul le format v1 est pris en charge.` });
      return;
    }
    for (const f of Object.keys(b)) {
      if (!ALLOWED_FIELDS[type].includes(f)) out.push({ ...base, code: 'unexpected_field', message: `Bloc ${index + 1} : champ « ${f} » non autorisé.` });
    }
    const label = `Bloc ${index + 1} (${type})`;
    switch (type) {
      case 'heading': checkText(b.text, LIMITS.heading, label, base, out); break;
      case 'paragraph': checkText(b.text, LIMITS.text, label, base, out); break;
      case 'callout':
        if (!TONES.includes(b.tone as Tone)) out.push({ ...base, code: 'callout_tone', message: `${label} : ton invalide (tip, warning, remember).` });
        checkText(b.text, LIMITS.text, label, base, out);
        break;
      case 'example': {
        if (b.title !== undefined && b.title !== '') checkText(b.title, LIMITS.title, `${label} titre`, base, out);
        const steps = b.steps;
        if (!Array.isArray(steps) || steps.length < 1 || steps.length > LIMITS.steps) {
          out.push({ ...base, code: 'steps_count', message: `${label} : de 1 à ${LIMITS.steps} étapes.` });
        } else {
          steps.forEach((s, si) => checkText(s, LIMITS.step, `${label} étape ${si + 1}`, base, out));
        }
        break;
      }
    }
  });
  return out;
}

/** Plain-text summary of a block, used by the diff view. */
export function blockText(b: Block): string {
  switch (b.type) {
    case 'heading':
    case 'paragraph': return b.text;
    case 'callout': return `[${b.tone}] ${b.text}`;
    case 'example': return [b.title, ...b.steps.map((s, i) => `${i + 1}. ${s}`)].filter(Boolean).join(' — ');
  }
}

export type DiffKind = 'added' | 'removed' | 'changed' | 'unchanged';
export interface DiffEntry { key: string; kind: DiffKind; before?: string; after?: string }

/** Block-level diff keyed by block `key` (stable ids are what the contract provides for this). */
export function diffBlocks(prev: readonly Block[], next: readonly Block[]): DiffEntry[] {
  const before = new Map(prev.map((b) => [b.key, b]));
  const out: DiffEntry[] = [];
  const seen = new Set<string>();
  for (const b of next) {
    seen.add(b.key);
    const old = before.get(b.key);
    if (!old) out.push({ key: b.key, kind: 'added', after: blockText(b) });
    else if (JSON.stringify(old) !== JSON.stringify(b)) out.push({ key: b.key, kind: 'changed', before: blockText(old), after: blockText(b) });
    else out.push({ key: b.key, kind: 'unchanged', after: blockText(b) });
  }
  for (const b of prev) if (!seen.has(b.key)) out.push({ key: b.key, kind: 'removed', before: blockText(b) });
  return out;
}
