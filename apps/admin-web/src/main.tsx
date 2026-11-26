import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { AppRoutes } from './App';
import { RolePreviewProvider } from './state/RolePreview';
import { ServicesProvider } from './state/Services';
import './styles/app.css';

// Demo convenience for screenshots and walkthroughs: `?persona=p-chloe` preselects a SYNTHETIC persona. It is not
// authentication; unknown values fall back to the default persona.
const initialPersonaId = new URLSearchParams(window.location.search).get('persona') ?? undefined;

// Hash routing: no path ever reaches a server, so any plain static host can serve the build (no rewrite rules).
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ServicesProvider>
      <RolePreviewProvider initialPersonaId={initialPersonaId}>
        <HashRouter>
          <AppRoutes />
        </HashRouter>
      </RolePreviewProvider>
    </ServicesProvider>
  </StrictMode>,
);
