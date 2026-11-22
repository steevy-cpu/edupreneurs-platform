import { useApp } from './AppContext';

/** For screens behind sign-in: the active session and services, or null while redirecting. */
export function useSignedIn() {
  const app = useApp();
  if (app.boot !== 'ready' || !app.session || !app.services) return null;
  return { ...app, session: app.session, services: app.services };
}
