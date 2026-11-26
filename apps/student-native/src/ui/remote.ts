import { useMemo } from 'react';

import { anyNetworkFlag, FLAGS } from '../core/experience/flags';
import { ExperienceApi, ExperienceRemote } from '../core/experience/remote';
import { loadConfig } from '../platform/config';
import { useApp } from './AppContext';

/**
 * The server adapter for the experience features, bound to the signed-in
 * session — or null when there is no session or every network flag is off
 * (the default), in which case no screen can make one of these requests.
 *
 * It uses the session's own token source and abort signal, exactly like the
 * app's `ApiClient`: signing out cancels anything in flight.
 */
export function useRemote(): ExperienceRemote | null {
  const { services, session } = useApp();
  return useMemo(() => {
    if (!services || !session || !anyNetworkFlag(FLAGS)) return null;
    return new ExperienceApi({
      baseUrl: loadConfig().apiUrl,
      sessionSignal: session.signal,
      getAccessToken: (options) => services.sessions.accessToken(session, options),
    });
  }, [services, session]);
}
