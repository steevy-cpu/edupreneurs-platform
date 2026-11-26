import { RIGHTS_LABEL, STATUS_LABEL, type RevStatus, type RightsStatus } from '../domain/editorial';
import { Badge, type Tone } from './ui';

const STATUS_TONE: Record<RevStatus, Tone> = {
  draft: 'neutral', in_review: 'violet', changes_requested: 'warn', approved: 'info', published: 'ok', withdrawn: 'danger', superseded: 'outline',
};
export function StatusBadge({ status }: { status: RevStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}

const RIGHTS_TONE: Record<RightsStatus, Tone> = { cleared: 'ok', pending: 'warn', unknown: 'warn', restricted: 'danger' };
export function RightsBadge({ rights }: { rights: RightsStatus }) {
  return <Badge tone={RIGHTS_TONE[rights]}>{rights === 'cleared' ? '✔ ' : '! '}{RIGHTS_LABEL[rights]}</Badge>;
}
