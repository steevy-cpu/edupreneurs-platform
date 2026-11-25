/**
 * Additions to the screen harness for the learner-experience tests
 * (onboarding, tour, word of the day, Gold).
 */
import type { Locale } from '../../src/core/api/types';
import type { AccountStore } from '../../src/core/db/accountStore';
import type { ExperienceRemote, ProfilePatch, RemoteOnboarding } from '../../src/core/experience/remote';
import { ApiError } from '../../src/core/api/errors';
import { translator } from '../../src/core/i18n/strings';
import { FakeApp, Phone } from './screenHarness';

export class RestartablePhone extends Phone {
  /**
   * Force-quit: the screen disappears and every account database is closed.
   * Nothing is "saved on exit" — the next `signIn` reopens the files from disk,
   * like a cold start.
   */
  async kill(): Promise<void> {
    await this.unmount();
    const open = (this as unknown as { accounts: Map<string, AccountStore> }).accounts;
    for (const account of open.values()) await account.close().catch(() => undefined);
    open.clear();
  }

  /**
   * The harness's stand-in app only RECORDS `setLocale`. Screens that change the
   * language while they are open need the real effect: the new language is used
   * at once and remembered for the account (same as AppContext.setLocale).
   */
  async signInLive(name: 'student.a' | 'student.b', locale?: Locale): Promise<FakeApp> {
    const app = await this.signIn(name, locale ?? 'fr');
    const saved = await app.session.account.getPreference('locale');
    if (!locale && (saved === 'fr' || saved === 'ht')) {
      app.locale = saved;
      app.t = translator(saved);
    }
    app.setLocale = async (next) => {
      app.calls.push(`setLocale ${next}`);
      app.locale = next;
      app.t = translator(next);
      await app.session.account.setPreference('locale', next);
    };
    return app;
  }
}

/** An in-memory stand-in for the server side of the experience endpoints. Synthetic data only. */
export class FakeRemote implements ExperienceRemote {
  /** 'offline' makes every call fail the way an unreachable server does. */
  mode: 'online' | 'offline' = 'online';
  onboarding: RemoteOnboarding = { state: 'new', onboarding_version: 0, tour_version_seen: 0, tour_dismissed: false };
  profile: ProfilePatch = {};
  readonly calls: string[] = [];

  private reach(call: string): void {
    this.calls.push(call);
    if (this.mode === 'offline') throw new ApiError('network', 'unreachable');
  }

  async getOnboarding(): Promise<RemoteOnboarding> {
    this.reach('GET /v1/me/onboarding');
    return { ...this.onboarding };
  }

  /** Behaves like the contract: the state only moves forward, the tour flags only grow. */
  async putOnboarding(body: RemoteOnboarding): Promise<RemoteOnboarding> {
    this.reach(`PUT /v1/me/onboarding ${JSON.stringify(body)}`);
    const order = ['new', 'profile_selected', 'downloads_informed', 'ready'];
    if (order.indexOf(body.state) > order.indexOf(this.onboarding.state)) this.onboarding.state = body.state;
    this.onboarding.onboarding_version = Math.max(this.onboarding.onboarding_version, body.onboarding_version);
    this.onboarding.tour_version_seen = Math.max(this.onboarding.tour_version_seen, body.tour_version_seen);
    this.onboarding.tour_dismissed = this.onboarding.tour_dismissed || body.tour_dismissed;
    return { ...this.onboarding };
  }

  async patchProfile(body: ProfilePatch): Promise<void> {
    this.reach(`PATCH /v1/me ${JSON.stringify(body)}`);
    this.profile = { ...this.profile, ...body };
  }
}
