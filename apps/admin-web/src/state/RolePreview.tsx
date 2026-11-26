import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { DEFAULT_PERSONA_ID, personaById, type Persona } from '../domain/roles';

/**
 * SYNTHETIC ROLE PREVIEW — not authentication.
 * Choosing a persona only changes which screens and buttons this prototype shows. It proves nothing about
 * who a person is. In production, identity, MFA and every permission check happen in FastAPI; hiding a
 * button never protects anything. No credential, token or session exists in this app.
 */
interface Ctx { persona: Persona; setPersonaId: (id: string) => void }
const RolePreviewContext = createContext<Ctx | null>(null);

export function RolePreviewProvider({ children, initialPersonaId = DEFAULT_PERSONA_ID }: { children: ReactNode; initialPersonaId?: string }) {
  const [id, setId] = useState(initialPersonaId);
  const value = useMemo<Ctx>(() => ({ persona: personaById(id), setPersonaId: setId }), [id]);
  return <RolePreviewContext.Provider value={value}>{children}</RolePreviewContext.Provider>;
}

export function useRolePreview(): Ctx {
  const c = useContext(RolePreviewContext);
  if (!c) throw new Error('RolePreviewProvider missing');
  return c;
}
