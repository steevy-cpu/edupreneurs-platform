import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppRoutes } from '../App';
import { createMockServices, ServicesProvider, type AdminServices } from '../state/Services';
import { RolePreviewProvider } from '../state/RolePreview';

export function renderApp(path = '/', personaId = 'p-gaelle', services?: AdminServices) {
  const svc = services ?? createMockServices(() => new Date('2026-11-26T14:00:00Z'));
  const utils = render(
    <ServicesProvider services={svc}>
      <RolePreviewProvider initialPersonaId={personaId}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </RolePreviewProvider>
    </ServicesProvider>,
  );
  return { ...utils, services: svc };
}
