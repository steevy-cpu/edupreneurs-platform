import { useState } from 'react';
import { BLOCK_TYPES, TONES, type Block, type BlockType, type Issue, type Tone } from '../domain/blocks';

const TYPE_LABEL: Record<BlockType, string> = { heading: 'Titre', paragraph: 'Paragraphe', example: 'Exemple', callout: 'Encadré' };
const TONE_LABEL: Record<Tone, string> = { tip: 'Astuce', warning: 'Attention', remember: 'À retenir' };

function nextKey(blocks: readonly Block[], type: BlockType): string {
  const used = new Set(blocks.map((b) => b.key));
  for (let i = 1; ; i++) {
    const k = `${type === 'callout' ? 'encadre' : type === 'heading' ? 'titre' : type === 'example' ? 'exemple' : 'paragraphe'}-${i}`;
    if (!used.has(k)) return k;
  }
}

function blank(type: BlockType, key: string): Block {
  switch (type) {
    case 'heading': return { key, type, text: 'Nouveau titre' };
    case 'paragraph': return { key, type, text: 'Nouveau paragraphe' };
    case 'example': return { key, type, title: 'Exemple', steps: ['Première étape'] };
    case 'callout': return { key, type, tone: 'tip', text: 'Nouvel encadré' };
  }
}

interface Props { blocks: Block[]; onChange: (next: Block[]) => void; issues: Issue[]; disabled?: boolean }

/** Structured editor for format-v1 blocks. Reordering uses buttons (keyboard-accessible), not drag and drop. */
export function BlockEditor({ blocks, onChange, issues, disabled }: Props) {
  const [newType, setNewType] = useState<BlockType>('paragraph');
  const set = (i: number, b: Block) => onChange(blocks.map((x, j) => (j === i ? b : x)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= blocks.length) return;
    const n = [...blocks];
    [n[i], n[j]] = [n[j]!, n[i]!];
    onChange(n);
  };
  return (
    <div>
      {blocks.map((b, i) => {
        const mine = issues.filter((x) => x.index === i);
        const n = i + 1;
        return (
          <section key={i} className={`block-edit ${mine.length ? 'invalid' : ''}`} aria-label={`Bloc ${n}, ${TYPE_LABEL[b.type]}`} aria-describedby={mine.length ? mine.map((_, k) => `bloc-${n}-erreur-${k}`).join(' ') : undefined}>
            <header>
              <strong>Bloc {n} · {TYPE_LABEL[b.type]}</strong>
              {!disabled && (
                <span className="row">
                  <button type="button" className="btn small" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Monter le bloc ${n}`}>↑</button>
                  <button type="button" className="btn small" onClick={() => move(i, 1)} disabled={i === blocks.length - 1} aria-label={`Descendre le bloc ${n}`}>↓</button>
                  <button type="button" className="btn small danger" onClick={() => onChange(blocks.filter((_, j) => j !== i))} aria-label={`Supprimer le bloc ${n}`}>Supprimer</button>
                </span>
              )}
            </header>
            <div className="stack">
              <label className="field">Identifiant du bloc
                <input type="text" value={b.key} disabled={disabled} onChange={(e) => set(i, { ...b, key: e.target.value })} aria-label={`Identifiant du bloc ${n}`} />
              </label>
              {b.type === 'heading' && (
                <label className="field">Texte<input type="text" value={b.text} disabled={disabled} onChange={(e) => set(i, { ...b, text: e.target.value })} aria-label={`Texte du bloc ${n}`} /></label>
              )}
              {b.type === 'paragraph' && (
                <label className="field">Texte<textarea value={b.text} disabled={disabled} onChange={(e) => set(i, { ...b, text: e.target.value })} aria-label={`Texte du bloc ${n}`} /></label>
              )}
              {b.type === 'callout' && (
                <>
                  <label className="field">Ton
                    <select value={b.tone} disabled={disabled} onChange={(e) => set(i, { ...b, tone: e.target.value as Tone })} aria-label={`Ton du bloc ${n}`}>
                      {TONES.map((t) => <option key={t} value={t}>{TONE_LABEL[t]}</option>)}
                    </select>
                  </label>
                  <label className="field">Texte<textarea value={b.text} disabled={disabled} onChange={(e) => set(i, { ...b, text: e.target.value })} aria-label={`Texte du bloc ${n}`} /></label>
                </>
              )}
              {b.type === 'example' && (
                <>
                  <label className="field">Titre (facultatif)<input type="text" value={b.title ?? ''} disabled={disabled} onChange={(e) => set(i, { ...b, title: e.target.value })} aria-label={`Titre du bloc ${n}`} /></label>
                  <label className="field">Étapes (une par ligne)<textarea value={b.steps.join('\n')} disabled={disabled} onChange={(e) => set(i, { ...b, steps: e.target.value.split('\n') })} aria-label={`Étapes du bloc ${n}`} /></label>
                </>
              )}
              {mine.map((x, k) => <p id={`bloc-${n}-erreur-${k}`} key={k} className="issue" role="alert"><code>{x.code}</code> {x.message}</p>)}
            </div>
          </section>
        );
      })}
      {!disabled && (
        <div className="row">
          <label className="sr-only" htmlFor="add-block-type">Type du nouveau bloc</label>
          <select id="add-block-type" value={newType} onChange={(e) => setNewType(e.target.value as BlockType)}>
            {BLOCK_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select>
          <button type="button" className="btn" onClick={() => onChange([...blocks, blank(newType, nextKey(blocks, newType))])}>Ajouter un bloc</button>
        </div>
      )}
      {issues.some((x) => x.index === undefined) && issues.filter((x) => x.index === undefined).map((x, k) => <p key={k} className="issue" role="alert"><code>{x.code}</code> {x.message}</p>)}
    </div>
  );
}
