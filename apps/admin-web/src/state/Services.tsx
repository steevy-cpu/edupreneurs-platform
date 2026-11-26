import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { buildDashboardFixture } from '../data/dashboardFixtures';
import { EditorialStore } from '../data/editorialStore';
import type { DashboardData } from '../domain/dashboard';
import type { EditorialState } from '../domain/editorial';

/**
 * The typed adapter the screens talk to. Today: in-memory mocks. Later: an OpenAPI-generated client for
 * the reviewed FastAPI staff API (`/v1/staff/*`). Screens must not import fixtures directly.
 */
export interface AdminServices {
  getDashboard(): Promise<DashboardData>;
  editorial: EditorialStore;
}

export function createMockServices(clock?: () => Date): AdminServices {
  return {
    getDashboard: () => Promise.resolve(buildDashboardFixture()),
    editorial: new EditorialStore(clock),
  };
}

const ServicesContext = createContext<AdminServices | null>(null);

export function ServicesProvider({ services, children }: { services?: AdminServices; children: ReactNode }) {
  const value = useMemo(() => services ?? createMockServices(), [services]);
  return <ServicesContext.Provider value={value}>{children}</ServicesContext.Provider>;
}

export function useServices(): AdminServices {
  const c = useContext(ServicesContext);
  if (!c) throw new Error('ServicesProvider missing');
  return c;
}

export function useEditorial(): { state: EditorialState; store: EditorialStore } {
  const { editorial } = useServices();
  const state = useSyncExternalStore(editorial.subscribe, editorial.getSnapshot);
  return { state, store: editorial };
}
