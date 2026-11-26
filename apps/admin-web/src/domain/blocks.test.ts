import { describe, expect, it } from 'vitest';
import { repoFile } from '../test/repo';
import { buildEditorialFixture } from '../data/editorialFixtures';
import { diffBlocks, KEY_PATTERN, LIMITS, validateBlocks, type Block } from './blocks';

const schema = JSON.parse(repoFile('packages/contracts/content/lesson-blocks.schema.json'));
const ok: Block[] = [{ key: 'titre', type: 'heading', text: 'Titre' }];
const codes = (b: unknown) => validateBlocks(b).map((i) => i.code);

describe('v1 block contract', () => {
  it('uses the same limits as the published JSON schema', () => {
    const d = schema.$defs;
    expect(LIMITS.maxBlocks).toBe(schema.maxItems);
    expect(LIMITS.heading).toBe(d.heading.properties.text.maxLength);
    expect(LIMITS.text).toBe(d.text.maxLength);
    expect(LIMITS.steps).toBe(d.example.properties.steps.maxItems);
    expect(LIMITS.step).toBe(d.example.properties.steps.items.maxLength);
    expect(KEY_PATTERN.source).toBe(d.key.pattern);
    expect(d.block.oneOf).toHaveLength(4);
  });

  it('accepts a valid lesson', () => expect(validateBlocks(ok)).toEqual([]));
  it('rejects empty lessons and block-count overflow', () => {
    expect(codes([])).toEqual(['block_count']);
    expect(codes(Array.from({ length: 201 }, (_, i) => ({ key: `b${i}`, type: 'heading', text: 'x' })))).toContain('block_count');
  });
  it('rejects bad and duplicate keys', () => {
    expect(codes([{ key: 'Étape 1', type: 'heading', text: 'x' }])).toContain('key_pattern');
    expect(codes([ok[0], ok[0]])).toContain('key_duplicate');
  });
  it('refuses markup, control characters and invisible characters (plain text only)', () => {
    expect(codes([{ key: 'a', type: 'paragraph', text: 'Voir <b>ceci</b>' }])).toContain('markup');
    expect(codes([{ key: 'a', type: 'paragraph', text: 'texte' + String.fromCharCode(0) }])).toContain('control_char');
    expect(codes([{ key: 'a', type: 'paragraph', text: 'texte' + String.fromCharCode(0x200b) }])).toContain('control_char');
    expect(codes([{ key: 'a', type: 'paragraph', text: 'Si a < b alors' }])).not.toContain('markup');
  });
  it('enforces length limits per block type', () => {
    expect(codes([{ key: 'a', type: 'heading', text: 'x'.repeat(201) }])).toContain('text_too_long');
    expect(codes([{ key: 'a', type: 'paragraph', text: 'x'.repeat(4001) }])).toContain('text_too_long');
    expect(codes([{ key: 'a', type: 'example', steps: [] }])).toContain('steps_count');
    expect(codes([{ key: 'a', type: 'example', steps: ['x'.repeat(501)] }])).toContain('text_too_long');
  });
  it('rejects format-v2 and unknown block types instead of pretending to render them', () => {
    for (const t of ['image', 'math', 'audio', 'table']) expect(codes([{ key: 'a', type: t, src: 'x' }])).toContain('unknown_type');
  });
  it('rejects unexpected fields and invalid callout tones', () => {
    expect(codes([{ key: 'a', type: 'heading', text: 'x', html: '<i>' }])).toContain('unexpected_field');
    expect(codes([{ key: 'a', type: 'callout', tone: 'loud', text: 'x' }])).toContain('callout_tone');
  });
  it('validates all synthetic fixtures except the one deliberately invalid draft', () => {
    const bad: string[] = [];
    for (const r of buildEditorialFixture().revisions) for (const [loc, blocks] of Object.entries(r.blocks)) if (validateBlocks(blocks).length) bad.push(`${r.id}/${loc}`);
    expect(bad).toEqual(['rev-l-ax-b-1/fr']);
  });
});

describe('diffBlocks', () => {
  it('reports added, removed, changed and unchanged blocks by key', () => {
    const a: Block[] = [{ key: 'a', type: 'heading', text: 'A' }, { key: 'b', type: 'paragraph', text: 'B' }, { key: 'c', type: 'paragraph', text: 'C' }];
    const b: Block[] = [{ key: 'a', type: 'heading', text: 'A' }, { key: 'b', type: 'paragraph', text: 'B2' }, { key: 'd', type: 'paragraph', text: 'D' }];
    expect(diffBlocks(a, b).map((d) => `${d.key}:${d.kind}`)).toEqual(['a:unchanged', 'b:changed', 'd:added', 'c:removed']);
  });
});
