/**
 * Additions to the screen harness for the learner-experience tests
 * (onboarding, tour, word of the day, Gold).
 */
import type { Locale } from '../../src/core/api/types';
import type { AccountStore } from '../../src/core/db/accountStore';
import type {
  DailyWordFetch,
  ExperienceRemote,
  ProfilePatch,
  RemoteDailyWord,
  RemoteOnboarding,
  RemoteOnboardingUpdate,
  RemoteRewardsSummary,
} from '../../src/core/experience/remote';
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

  /**
   * Behaves like the identity lane's endpoint: strict body (unknown fields and an
   * `onboarding_version` below 1 are refused with 422), the state only moves
   * forward, the tour flags only grow.
   */
  async putOnboarding(body: RemoteOnboardingUpdate): Promise<RemoteOnboarding> {
    this.reach(`PUT /v1/me/onboarding ${JSON.stringify(body)}`);
    const allowed = ['state', 'onboarding_version', 'tour_version_seen', 'tour_dismissed'];
    const unknown = Object.keys(body).filter((key) => !allowed.includes(key));
    if (unknown.length > 0 || !Number.isInteger(body.onboarding_version) || body.onboarding_version < 1) {
      throw new ApiError('client', 'validation_error', 422);
    }
    const order = ['new', 'profile_selected', 'downloads_informed', 'ready'];
    if (body.state && order.indexOf(body.state) > order.indexOf(this.onboarding.state)) this.onboarding.state = body.state;
    this.onboarding.onboarding_version = Math.max(this.onboarding.onboarding_version, body.onboarding_version);
    this.onboarding.tour_version_seen = Math.max(this.onboarding.tour_version_seen, body.tour_version_seen ?? 0);
    this.onboarding.tour_dismissed = this.onboarding.tour_dismissed || body.tour_dismissed === true;
    return { ...this.onboarding };
  }

  async patchProfile(body: ProfilePatch): Promise<void> {
    this.reach(`PATCH /v1/me ${JSON.stringify(body)}`);
    this.profile = { ...this.profile, ...body };
  }

  // ------------------------------------------------------------- word of the day
  /** Today's word per requested language; a missing entry answers 404 `daily_word_not_available`. */
  dailyWords: Partial<Record<Locale, RemoteDailyWord>> = {};
  /** The server's own clock, sent as the `Date` header. Null: the header is not readable (the app falls back to its clock). */
  serverNow: (() => Date) | null = null;
  /** Set to make the endpoint answer 404 with this code (e.g. the feature is off on the server). */
  dailyWordDisabledCode: string | null = null;

  static etagOf(word: RemoteDailyWord): string {
    return `"${word.haiti_date}:${word.locale}:${word.word.revision_id}"`;
  }

  async getDailyWord(locale: Locale, etag: string | null): Promise<DailyWordFetch> {
    this.reach(`GET /v1/daily-word?locale=${locale}${etag ? ` If-None-Match=${etag}` : ''}`);
    if (this.dailyWordDisabledCode) throw new ApiError('client', this.dailyWordDisabledCode, 404);
    const word = this.dailyWords[locale];
    if (!word) throw new ApiError('client', 'daily_word_not_available', 404);
    const serverDate = this.serverNow ? this.serverNow().toUTCString() : null;
    if (etag && etag === FakeRemote.etagOf(word)) return { kind: 'not_modified', serverDate };
    return { kind: 'word', word: JSON.parse(JSON.stringify(word)) as RemoteDailyWord, etag: FakeRemote.etagOf(word), serverDate };
  }

  // ------------------------------------------------------------------------ gold
  /** The server's summary for the signed-in learner; null answers 404 (feature off on the server). Synthetic numbers. */
  rewards: RemoteRewardsSummary | null = null;

  async getRewardsSummary(): Promise<RemoteRewardsSummary> {
    this.reach('GET /v1/rewards/summary');
    if (!this.rewards) throw new ApiError('client', 'not_found', 404);
    return JSON.parse(JSON.stringify(this.rewards)) as RemoteRewardsSummary;
  }
}

/** A synthetic server summary. The numbers mean nothing; they only have to be recognisable in assertions. */
export function sampleRewards(balance: number, over: Partial<RemoteRewardsSummary> = {}): RemoteRewardsSummary {
  return { balance, streak: { current: 3, longest: 7 }, achievements: 2, up_to_date: true, rules_status: null, ...over };
}

/**
 * Synthetic words for tests. `valid_until` is the next midnight in Haiti as a UTC
 * instant: in November Haiti is on standard time (UTC-5), so the day 2026-11-24
 * ends at 2026-11-25T05:00:00Z.
 */
export function sampleWord(day: '2026-11-23' | '2026-11-24' | '2026-11-25', locale: Locale, over: Partial<RemoteDailyWord> = {}): RemoteDailyWord {
  const next = { '2026-11-23': '2026-11-24', '2026-11-24': '2026-11-25', '2026-11-25': '2026-11-26' }[day];
  const fr = {
    '2026-11-23': ['curiosité', 'ku-rio-zi-té', 'Envie d’apprendre et de comprendre des choses nouvelles.', 'Sa curiosité le pousse à poser des questions en classe.', 'kiryozite'],
    '2026-11-24': ['persévérance', 'pèr-sé-vé-rans', 'Qualité d’une personne qui continue ses efforts malgré les difficultés.', 'Avec de la persévérance, elle a terminé tous ses exercices.', 'pèseverans'],
    '2026-11-25': ['hypothèse', 'i-po-tèz', 'Idée que l’on propose pour expliquer quelque chose, avant de la vérifier.', 'Nous testons notre hypothèse par une expérience.', 'ipotèz'],
  }[day];
  const ht = {
    '2026-11-23': ['kiryozite', 'ki-ryo-zi-te', 'Anvi aprann epi konprann bagay ki nouvo.', 'Kiryozite li fè l poze kesyon nan klas la.', 'curiosité'],
    '2026-11-24': ['pèseverans', 'pè-se-ve-rans', 'Kalite yon moun ki kontinye fè efò menm lè sa difisil.', 'Ak pèseverans, li fini tout egzèsis li yo.', 'persévérance'],
    '2026-11-25': ['ipotèz', 'i-po-tèz', 'Yon lide nou pwopoze pou eksplike yon bagay, anvan nou verifye l.', 'N ap teste ipotèz nou an ak yon eksperyans.', 'hypothèse'],
  }[day];
  const [term, pronunciation, definition, example, gloss] = locale === 'fr' ? fr : ht;
  return {
    haiti_date: day,
    locale,
    requested_locale: locale,
    is_fallback_locale: false,
    valid_until: `${next}T05:00:00Z`,
    word: {
      word_id: `word-${day}`,
      revision_id: `rev-${day}-${locale}`,
      term,
      pronunciation,
      part_of_speech: 'noun', // a language-neutral code, as the server sends it
      definition,
      example,
      gloss,
    },
    audio: null,
    ...over,
  };
}
