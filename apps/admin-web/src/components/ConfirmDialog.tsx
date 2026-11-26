import { useEffect, useId, useRef, useState } from 'react';
import type { Result } from '../domain/editorial';
import { Notice } from './ui';

interface Props {
  title: string;
  /** The exact object being acted on (Admin-00 cross-cutting rule: confirm with the exact object). */
  object: string;
  reasonLabel: string;
  reasonRequired: boolean;
  confirmLabel: string;
  danger?: boolean;
  /** True for actions that would need MFA step-up in production. */
  stepUp?: boolean;
  onConfirm: (reason: string) => Result;
  onClose: () => void;
}

/**
 * Confirmation with object, reason and (synthetic) audit receipt. Role="dialog", Escape closes, Tab is kept inside,
 * focus returns to the opener. The "receipt" proves nothing was written: it is labelled synthetic.
 */
export function ConfirmDialog({ title, object, reasonLabel, reasonRequired, confirmLabel, danger, stepUp, onConfirm, onClose }: Props) {
  const [reason, setReason] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(document.activeElement);
  const titleId = useId();
  const fieldId = useId();

  useEffect(() => {
    const el = opener.current as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('textarea, button')?.focus();
    return () => {
      if (el?.isConnected && !el.matches(':disabled')) el.focus();
      else document.getElementById('page-title')?.focus();
    };
  }, []);

  useEffect(() => { if (result?.ok) closeButton.current?.focus(); }, [result]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
    if (e.key !== 'Tab' || !box.current) return;
    // Sorted explicitly: some DOM implementations return a selector list grouped by selector, not in document order.
    const f = [...box.current.querySelectorAll<HTMLElement>('button:not(:disabled), textarea, input, select, a[href]')]
      .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    if (f.length === 0) return;
    const first = f[0]!;
    const last = f[f.length - 1]!;
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  const missing = reasonRequired && reason.trim().length === 0;

  return (
    <div className="modal-backdrop" onKeyDown={onKey}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={box}>
        <h2 id={titleId}>{title}</h2>
        <p><strong>Objet :</strong> {object}</p>
        {stepUp && <Notice tone="warn" title="Step-up MFA non implémenté.">En production, cette action exigerait une authentification MFA de moins de 5 minutes (AD-2). Ici, elle est simulée.</Notice>}
        {result?.ok ? (
          <>
            <Notice title="Terminé (synthétique).">Aucune donnée n’a été écrite : seul l’état en mémoire de cette page a changé, et il disparaît au rechargement.</Notice>
            <p className="receipt">Reçu d’audit synthétique {result.receipt.id}<br />{result.receipt.action} · {result.receipt.target}<br />par {result.receipt.actor}{result.receipt.reason ? ` · motif : ${result.receipt.reason}` : ''}</p>
            <div className="row"><button type="button" className="btn primary" ref={closeButton} onClick={onClose}>Fermer</button></div>
          </>
        ) : (
          <>
            <label className="field" htmlFor={fieldId}>
              {reasonLabel}{reasonRequired ? ' (obligatoire)' : ' (facultatif)'}
              <textarea id={fieldId} value={reason} onChange={(e) => setReason(e.target.value)} aria-invalid={missing && result !== null} />
            </label>
            {result && !result.ok && <p className="issue" role="alert">{result.message}</p>}
            <div className="row">
              <button type="button" className={`btn ${danger ? 'danger' : 'primary'}`} disabled={missing} onClick={() => setResult(onConfirm(reason))}>{confirmLabel}</button>
              <button type="button" className="btn" onClick={onClose}>Annuler</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
