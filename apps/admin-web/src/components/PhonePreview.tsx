import type { Block } from '../domain/blocks';

/**
 * 320 dp preview of the v1 block contract. Text is rendered as React text nodes only: markup in a block
 * appears literally, exactly as the phone's plain-text renderer would show it. Not a claim of v2 compatibility.
 */
export function PhonePreview({ blocks, locale }: { blocks: readonly Block[]; locale: string }) {
  return (
    <div className="phone" role="group" aria-label={`Aperçu téléphone 320 dp, ${locale}`}>
      <div className="phone-screen" lang={locale}>
        {blocks.length === 0 && <p className="muted">Aucun bloc.</p>}
        {blocks.map((b, i) => {
          switch (b.type) {
            case 'heading': return <p key={i} className="p-heading">{b.text}</p>;
            case 'paragraph': return <p key={i}>{b.text}</p>;
            case 'callout': return <div key={i} className={`p-callout ${b.tone}`}><strong>{b.tone === 'tip' ? 'Astuce' : b.tone === 'warning' ? 'Attention' : 'À retenir'} : </strong>{b.text}</div>;
            case 'example': return (
              <div key={i} className="p-example">
                {b.title && <strong>{b.title}</strong>}
                <ol>{b.steps.map((s, j) => <li key={j}>{s}</li>)}</ol>
              </div>
            );
          }
        })}
      </div>
    </div>
  );
}
