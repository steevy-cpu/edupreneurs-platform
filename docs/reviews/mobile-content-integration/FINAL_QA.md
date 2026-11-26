# Independent Mobile-02 and Content-Delivery-00 QA

**Ready for owner approval on the corrected integration.** Independent QA closes QA-1 through QA-11 on `ff1b4d88`. The real-stack gates passed, and the unchanged emulator rerun passed all six French and Haitian Creole configurations. The first device attempt and its interruption remain documented below.

## Final corrective re-review

The final review target is [PR #26 at ff1b4d88e9082167dd7419eff6d6563d47a1a65c](https://github.com/steevy-cpu/edupreneurs-platform/commit/ff1b4d88e9082167dd7419eff6d6563d47a1a65c), based on [PR #25 at 3ed9a197164fa177d8a353aa71e0b52c69eddd1e](https://github.com/steevy-cpu/edupreneurs-platform/pull/25). It includes the original corrections and the follow-up fixes for QA-10 and QA-11. Both QA probe sources matched the copies committed by the implementer byte for byte. No implementation changes were made by the reviewer.

| Gate | Independent result on ff1b4d88 |
| --- | --- |
| Isolation | New GitHub-hosted VM and Supabase project for each job. Shared override unset. Database and gateway container bindings, API service DSN, Auth issuer/JWKS and loopback ports verified. Separate guarded tests rejected inconsistent targets. |
| Database and backend | 215/215 pgTAP assertions before pytest, 148/148 pytest tests, 215/215 pgTAP assertions after pytest. |
| Mobile regression | Generated API types fresh. Application and test TypeScript passed. 477/477 Jest tests passed in 32 suites on real API, Auth and SQLite. Covered reading without a permanent download, offline reopening, eventual sync, deletion, transaction rollback, withdrawals, late responses and account switching. |
| Original and follow-up probes | 11/11 original cases and 4/4 recovery/invalid-response cases passed separately. These 15 are included in the 477. A separate detached local run also passed all 26 selected component and QA cases. |
| Device and evidence isolation | The recording adapter accepted the intended serial, rejected a wrong serial, and added and removed only ports 41400 and 41401. Two invocations of the same Maestro flow on different synthetic serials produced distinct default logs and captured each serial's own file. The first log and an explicitly shared log kept their original sentinel. |
| API 24, 320 dp | 6/6 on the fresh-runner retry, with 30/30 checkpoints and captures. The interrupted first attempt completed 2/6. |

[Live stack and recording-adapter job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45869164441/job/140079815004) · [Machine-readable stack results](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45869164441/artifacts/15141732114).

### Final Android evidence

On the first attempt, both 1.0 cells completed. French 1.3 reached Home, then the next Maestro invocation hit the 240-second process timeout before emitting a flow banner. The remaining invocations stopped before a UI assertion. The ADB captures show the same French Home screen before and after the timeout and through subsequent attempted launches. This localizes the interruption to the interval before the driver exercised the next action. The logs do not establish its underlying cause. A fresh hosted job retried the same SHA with the same commands. [First job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45869164441/job/140079815010) · [First attempt original PNGs and CSV](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45869164441/artifacts/15142653354) · [Home before and after the timeout](screenshots/ff1b4d8-attempt1.jpg).

Each matrix link shows Home, the learning path, the online reader, a saved practice answer and the lesson in Réviser/Revize after a process restart. The hosted API 24 release build ran with 1 GB RAM and a 320 dp viewport. Each cell began with cleared app data and used the same synthetic server account. At 2.0 the learner had to scroll through the lesson to reach practice. Both languages completed it. Device connectivity stayed available during these six journeys; the live integration suite separately exercised network loss and offline reopening.

| Language | Font 1.0 | Font 1.3 | Font 2.0 |
| --- | --- | --- | --- |
| French | [Pass · 5 captures](screenshots/ff1b4d8/fr-1.0.jpg) | [Pass · 5 captures](screenshots/ff1b4d8/fr-1.3.jpg) | [Pass · 5 captures](screenshots/ff1b4d8/fr-2.0.jpg) |
| Haitian Creole | [Pass · 5 captures](screenshots/ff1b4d8/ht-1.0.jpg) | [Pass · 5 captures](screenshots/ff1b4d8/ht-1.3.jpg) | [Pass · 5 captures](screenshots/ff1b4d8/ht-2.0.jpg) |

[Passing device job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45869164441/job/140089491996) · [30 original PNGs, settings, SHA and results CSV](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45869164441/artifacts/15143688552).

### Disposition of the findings

| Findings | Evidence on the final correction |
| --- | --- |
| QA-1, QA-4 · Online progress and catalog truth | Home and Réviser showed the online lesson with zero downloads. A lesson missing from a fresh catalog returned unlisted. |
| QA-2, QA-3 · Offline replacement | Releasing an older download after a newer explicit choice retained the selected revision. A well-formed response containing an incomplete paragraph left the readable copy intact. |
| QA-5, QA-9, QA-10 · Connectivity and recovery | HTTP 503, transport loss, a malformed HTTP 200 body and a successful retry were distinguished in the bilingual reader/Profile checks. A successful authenticated read removed stale offline advice without acknowledging pending operations. |
| QA-6 · Assessment contract | The runtime refused an unknown assessment mode before saving practice content. No controlled-exam implementation was exercised. |
| QA-7, QA-8, QA-11 · Isolation | The gate rejected conflicting endpoints. The recorder verified scoped forwarding, unique evidence directories and correct capture ownership. |

### Merge-readiness verdict

| Target | Owner action |
| --- | --- |
| #26 onto #25 | Ready for owner approval at `ff1b4d88`. All original and follow-up findings passed independent retest. |
| #3 Mobile-02 and #22 Content-Delivery-00 | Their integrated behavior is ready for owner approval through corrected #25. The standalone heads predate the corrections. Land #26 into #25 first, then verify the resulting tree and CI before advancing the consolidated PR. |
| Student release | Use a clean release assembly after changing feature flags. The verified incremental cache hazard remains open. Physical-device startup and low-storage behavior were outside the measured gates. |

In the implementer’s separate clean-release experiment, the incremental flags-off build retained flags-on bytes. A clean flags-off assembly matched a forced rebuild. [Exact-SHA bundle comparison](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45872662951/job/140096286664).

The remaining product decisions concern retention of previously downloaded withdrawn lessons, classification of future controlled exams, and educator review of Haitian Creole wording. Current tests cover the existing practice-only contract and truthful catalog states.

## Earlier correction at 54321c1

The first reviewed correction was [54321c1755db7d9258a351710665e620a88e1831](https://github.com/steevy-cpu/edupreneurs-platform/commit/54321c1755db7d9258a351710665e620a88e1831), stacked directly on [#25 at 3ed9a197164fa177d8a353aa71e0b52c69eddd1e](https://github.com/steevy-cpu/edupreneurs-platform/commit/3ed9a197164fa177d8a353aa71e0b52c69eddd1e). A separate detached checkout and fresh GitHub-hosted stacks exercised the exact correction. The correction's copy of the original independent suite matched the QA source byte for byte.

| Gate | Result on #26 |
| --- | --- |
| Static and database | Generated API types and both TypeScript checks passed. All 215 pgTAP assertions passed before and after 148 passing pytest cases. |
| Mobile real stack | 472/472 passed across 31 suites, including the original 11 now carried by the candidate. Includes SQLite, real API/Auth, online-only answers, restart/reconnect, deletion, withdrawal, lost responses and cross-account isolation. |
| Original QA suite rerun in isolation | 11/11 passed. QA-2, QA-3, QA-5, QA-6 and QA-7 changed from red on #25 to green. QA-1 and QA-4 stayed green. This repeat is already represented within the 472. |
| QA-8 device target | The recording adapter verified both selected serial and forward/remove operations on 41400 and 41401, refused the wrong serial, and rejected a second disposable DB port and a conflicting mobile Auth endpoint. It made zero network or ADB connections. |
| QA-9 service recovery | The independent rerun of the two localized reader tests traversed HTTP 503, lost connection and successful retry with one queued completion. Two additional localized Profile checks retained both pending operation payloads and their IDs after an unrelated authenticated read recovered. No sync receipt or last-sync time was manufactured. |
| Additional cases | A completely received malformed HTTP 200 response produced a false offline diagnosis in French and Haitian Creole (QA-10). The workstation runner can also mix or erase evidence from parallel worktrees (QA-11). |
| API 24 acceptance | Six of six French and Haitian Creole cells passed at API 24, 320 dp and font scales 1.0, 1.3 and 2.0. [Device job for this intermediate SHA](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45867547383/job/140074215633). |

[Supplemental checks showing QA-10 before the fix](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45868623383/job/140077946437) · [Correction stack job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45867547383/job/140074215357) · [Original probes](acceptance.test.tsx) · [Recording adapter](record-android-target.sh) · [Supplemental recovery and response checks](recovery.test.tsx).

### Follow-up findings first confirmed on 54321c1, corrected on ff1b4d88

| Finding | Reproduction and evidence | Expected behavior, minimal fix and regression |
| --- | --- | --- |
| QA-10 · Medium, misleading connectivity diagnosis | Return HTTP 200 with the fully received text `temporarily unavailable` to the real API client while opening an uncached online lesson. Both localized reader checks showed the no-Internet message and the offline badge. Retry was available and SQLite contained no permanent copy. `src/core/api/http.ts` emits `invalid_response` as a network error, `src/core/api/client.ts` reports unreachable, and `reasonOf` in `src/core/learning/contentAccess.ts` chooses offline. | Distinguish an undecodable completed HTTP response from transport failure, show the existing invalid-content or service-retry message, and avoid deriving device connectivity from the parse result. Keep both localized assertions in `recovery.test.tsx`. This extends the original passing 503 and recovery scenarios. |
| QA-11 · Medium, local test evidence collision | Run the default `OUT`, `LOG` and log initialization lines from `apps/student-native/scripts/e2e-run.sh` in two temporary checkout directories with different serials, one temporary volume and no output overrides. After the first writes a sentinel and the second initializes, the paths are identical and the first log is zero bytes. The screenshot collector also chooses the latest matching flow in the user's global Maestro directory. The hosted QA job used one VM and run-specific evidence per job. | Default logs and screenshots to a run-specific directory and give that run its own Maestro artifact root. Preserve explicit output overrides. Add a two-run test that keeps the first log and associates each capture with its serial. |

On the final SHA the implementer separately verified that an incremental flags-off build reused flags-on bytes. After Gradle clean, the packaged flags-off bundle matched the forced rebuild byte for byte. I checked the job SHA and result. Independent device acceptance used fresh VMs. [Implementer’s clean-release comparison](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45872662951/job/140096286664). [Candidate build-cache note](https://github.com/steevy-cpu/edupreneurs-platform/blob/54321c1755db7d9258a351710665e620a88e1831/docs/mobile-integration-2026-11-26/BUILD_CACHE.md).

## Parent evidence on PR #25

The parent had two ways for a replacement download to leave a learner with the wrong or unreadable offline revision. Both were corrected and independently retested above.

### Results on the #25 head

| Gate | Independent evidence on the pinned SHA |
| --- | --- |
| Database and isolation | New GitHub-hosted VM with project `edu-qa-45840800322-1`. The QA wrapper verified the database and gateway container bindings and effective service/Auth URLs before the suites. The #20 harness reported DB port 41002, gateway 41001 and API 41000. The shared override was unset. The network-free mixed-endpoint probe still reproduced QA-7. |
| PostgreSQL and backend | 215 pgTAP assertions passed, 148 pytest cases passed, and all 215 pgTAP assertions passed again after pytest. |
| Mobile static checks and real stack | Generated API types fresh, app and test TypeScript passed, all 441 cases in 30 mobile Jest suites passed. These include real Auth, SQLite, restart/reconnect, server scoring, lost-response recovery, account isolation, download removal and real withdrawal. |
| Independent negative and privacy cases | 6 passed, 5 failed. Home and Réviser displayed the online lesson title, omitted catalog entries were identified as unlisted, late response bodies were discarded, queued work stayed account-specific, and a late Auth refresh could not restore learner A after learner B signed in. QA-2, QA-3, QA-5, QA-6 and QA-7 reproduced. |
| Local cross-check | Across component, unit, experience, delivery and independent probes, 399 passed and 8 failed. Five were the same product/harness findings. The other three were local socket-bind denials; those three passed on GitHub. |
| Android device acceptance | 6/6 passed on API 24 at 320 dp, with 30 screenshots. All six completed online reading, practice and post-restart review. |

[Independent run and jobs](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45840800322) · [Stack log](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45840800322/job/139981680977) · [Stack results artifact](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45840800322/artifacts/15128201631) · [Review on #25](https://github.com/steevy-cpu/edupreneurs-platform/pull/25#pullrequestreview-6076012498).

### Learner scenarios on the published candidate

| Scenario | Observed behavior |
| --- | --- |
| 1. Read online without a download | The live online-reading suite found zero permanent copies after reading and answering. |
| 2. Reopen a download offline | The real-stack test reopened the saved lesson after recreating the client and SQLite handles offline. |
| 3. Persist and sync online-only answers | Pending answers survived restart. After reconnecting, the API scored them. Retrying a lost response preserved a single operation. |
| 4. Show online-only progress | Independent Home and Réviser assertions both found the lesson title with no saved copy. This closes QA-1. |
| 5. Delete a download | Removing the public copy preserved the learner's attempts, completion and pending work in the real-stack test. |
| 6. Replace interrupted or corrupted content | Ordinary interruptions and storage failures rolled back. A delayed earlier download and an incomplete paragraph both displaced good content (QA-2, QA-3). |
| 7. Switch accounts | Live A/B sessions isolated attempts, lesson references and pending uploads. Late HTTP and Auth results in the independent probes could not replace the new account's state. |
| 8. Withdraw or republish a lesson | The live withdrawal/republication and stale-catalog tests passed. A fresh catalog omission now returns unlisted (QA-4 closed). Service outage and recovery messaging still fail in QA-5 and QA-9. |
| 9. Keep practice separate from controlled exams | The server serves practice only. The independent runtime test saved a response tagged with an unsupported assessment mode (QA-6). |
| 10. Reach controls at large text | See the Android matrix for independent device coverage and the separately attributed candidate screenshots. |

[Candidate integration tests](https://github.com/steevy-cpu/edupreneurs-platform/tree/3ed9a197164fa177d8a353aa71e0b52c69eddd1e/apps/student-native/tests/integration) · [Independent regression cases](acceptance.test.tsx).

### Independent Android evidence

The release build ran on API 24 with a 1 GB x86_64 AVD. The verified logical display was 640 × 1066 at 320 dpi (320 dp wide). ADB captured the underlying 320 × 640 framebuffer. Each cell started from cleared app data and signed in against isolated Auth. All six reached Home; in the three Haitian Creole cells the driver changed language through Profile and verified “Pwofil” before returning. The four bottom navigation tabs were visible at each setting. At 2.0, the empty-state action was below the first viewport. This screenshot alone does not establish its reachability by scrolling.

![Independent Home screenshots in French and Haitian Creole at font scales 1.0, 1.3 and 2.0](screenshots/home-api24.jpg)

The contact sheet contains ADB captures taken after Maestro's API 24 screenshot service returned a null image. That interrupted the first attempt before the lesson path. The raw PNGs and the effective display settings were uploaded by the isolated runner. [Home run](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45851177725/job/140017674616) · [Original PNGs](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45851177725/artifacts/15135240989).

| Language | Font 1.0 | Font 1.3 | Font 2.0 |
| --- | --- | --- | --- |
| French | [Pass · 5 captures](screenshots/fr-1.0.jpg) | [Pass · 5 captures](screenshots/fr-1.3.jpg) | [Pass · 5 captures](screenshots/fr-2.0.jpg) |
| Haitian Creole | [Pass · 5 captures](screenshots/ht-1.0.jpg) | [Pass · 5 captures](screenshots/ht-1.3.jpg) | [Pass · 5 captures](screenshots/ht-2.0.jpg) |

All six flows activated read online, opened practice, submitted an answer, saw its local confirmation, stopped and relaunched the app, and found the lesson in Réviser/Revize. The isolated API and Auth stayed available. Each cell cleared app data and reused the synthetic server account, so post-restart totals can include earlier cells. The separate live suites verified offline restart and synchronized operation counts. [Final device run](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45858518754/job/140043167951) · [30 original PNGs, display settings, candidate SHA and results CSV](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45858518754/artifacts/15137679357).

At 2.0, practice follows the entire lesson in the scrollable reader. An earlier 15-second search stopped midway in both languages. With a 120-second allowance, the same build met the same visibility and tap assertions in both. Large text required additional scrolling, including on the catalog screen. The passed matrix covers this seeded path and its navigation. The download, account-switch and withdrawal assertions used the live integration suites. [Earlier device job](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45853769281/job/140026725242).

### Device evidence from the candidate

I inspected the 19 original 480×800 screenshots committed by the implementer. At scale 2.0 the French and Creole path screenshots show the separate read and download buttons, including their text. The online answer screenshot shows a durable local confirmation; the review and profile screenshots distinguish pending from acknowledged work. These captures come from the implementer's emulator session. [Screenshot directory](https://github.com/steevy-cpu/edupreneurs-platform/tree/3ed9a197164fa177d8a353aa71e0b52c69eddd1e/docs/mobile-integration-2026-11-26/screenshots).

**QA-9 · Medium, stale connectivity message after recovery.** In the reconnect flow, take the backend offline, attempt the online reader, restore the backend, then retry successfully before the next sync. Screenshot 28 shows the reloaded reader labeled “En ligne · non téléchargée” and simultaneously “Hors ligne”. The shared header derives its connectivity badge from the previous sync report in `src/ui/shell.tsx`. Distinguish last-sync status from current reader reachability, or clear the stale indication on confirmed service contact. Add a recovery screen assertion covering the interval between successful retrieval and subsequent sync. [Reconnect screenshot](https://github.com/steevy-cpu/edupreneurs-platform/blob/3ed9a197164fa177d8a353aa71e0b52c69eddd1e/docs/mobile-integration-2026-11-26/screenshots/28-online-retry-ok.png).

## Provenance

| Ref | Verified revision | Scope |
| --- | --- | --- |
| main | `6ad3fdbf40d07238274e841d73cff17e72355346` | Contains #20, #2 and #23 |
| #3 | `54fec1c9547a23f644b504b5498385c252e94357` | Mobile-02, including Design-00. [CI passed](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45514360028) |
| #22 | `e30c81645b528ab508b94796e7954a57fd1e9ef5` | Content delivery, based on #3. [CI passed](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45818568188) |
| #15 | `202c12f680d0ac67cf793d39a2fbe8dcdaed3cb2` | Native corrections, based on #8. [CI passed](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45625961541) |
| Independently tested local snapshot | `fec0920370d8f91bf975733cdbac08d5b38c3f60` | Merges #3 and #22 onto hardened main. Predates the local native reconciliation. |
| Published consolidated candidate | `3ed9a197164fa177d8a353aa71e0b52c69eddd1e` | [Draft #25](https://github.com/steevy-cpu/edupreneurs-platform/pull/25), based on hardened main. |

Local probes used a detached checkout, independent Node dependencies, synthetic accounts, temporary SQLite files and controlled responses. The published integration suites additionally used real Auth, the candidate FastAPI service and PostgreSQL in a disposable GitHub VM. The QA branch contains review materials only. The platform-stabilization commit remains on its original branch. Product comparisons use the repository's Lovable inventory, Mobile-02 report and Content-Delivery-00 decisions. No live prototype comparison was performed.

## Preliminary evidence on fec0920

| Gate | Observed result |
| --- | --- |
| App and test TypeScript | Both passed. The independent regression file also type-checked in the test checkout. |
| Existing delivery Jest config | 155 passed, 3 failed. Delivery 14/14, online screens 9/9, other screens 19/19, overview 6/6, design 76/76, core 17/17, local stack 9/9, port checks 5/8. The three failures were loopback bind errors (EPERM). |
| Independent acceptance probes | 2 passed, 8 failed across seven findings below. Both account switching with queued work in synthetic A/B account stores and cancellation during response-body reading passed. |
| Shared-target safety | The shared project is refused with the default harness settings. The reviewed global setup, local stack helper, test device and sync resilience test match #20 on this snapshot. A mixed-endpoint refusal test failed (QA-7). No shared database, gateway, API or Auth service was used. |
| Real Supabase, API/Auth and offline sync suites | Blocked by sandbox denial at the OrbStack socket. End-to-end upload, server receipt, retry and reconciliation remain unverified here. |
| API 24 at 320 dp | All six cells pending: fr and ht, each at 1.0, 1.3 and 2.0. ADB failed to bind its local listener. No screenshots, physical-device timings or layout verdict are available for this snapshot. |

### Functional coverage on fec0920

1. Opening an online lesson and answering it left no permanent lesson in SQLite. The reader and quiz used the in-memory copy.
2. A saved lesson reopened offline after closing and reopening database handles. OS process death on Android remains pending.
3. An online-only attempt and its pending operation survived a database reopen. Eventual server acknowledgement remains pending.
4. Home and Réviser both omitted online-only work (QA-1).
5. Deleting the public lesson through the store kept private attempts, completion and pending operations. This snapshot has no deletion control to exercise on-device.
6. Existing interrupted-response, structural validation and injected write-failure cases preserved the saved revision. Two independent replacement cases failed (QA-2 and QA-3).
7. Synthetic account stores isolated progress and queued work; a late response body was discarded after abort. Rapid sign-out/sign-in with actual secure storage, token refresh and server receipts still needs the real stack.
8. A fresh catalog omitting the saved lesson returned an incorrect update status (QA-4). A 503 produced incorrect connection advice (QA-5).
9. The current server declares only offline practice. The runtime client accepted an unsupported assessment mode (QA-6). There is no controlled-exam implementation or evidence of an actual exam disclosure.
10. Mock components establish wording and actions only. At 320 dp, scroll to the last answer and both catalog actions, activate each one, back out and reopen in both languages. Capture Home, Réviser, Learn, reader and quiz with the locale, scale, build SHA and API level.

## Preliminary findings and reproductions

Severity reflects effect on this slice. Each row describes one reproducible scenario, its observed result, its expected result and the regression to keep. The executable cases accompany this report.

| ID / severity | Reproduction and evidence | Affected path | Expected behavior, minimal correction and test |
| --- | --- | --- | --- |
| QA-1 · High, progress visibility | Read online without downloading; answer once and complete. SQLite showed one attempt and no saved copy. Home displayed “Choisis ta première leçon” and Réviser displayed “Rien à réviser pour l’instant”. Both screen assertions failed. | `src/app/home.tsx`, `src/app/review.tsx`, `savedLessonStandings` | Drive progress from the active account, retaining public lesson metadata sufficient to identify work after restart. Keep offline availability separate. Exercise both screens with zero downloads, then repeat after restart and account switch. This changes the ADR-3 presentation decision to meet the requested experience. |
| QA-2 · High, offline revision loss | Start download A for r1; hold its response. Finish an explicit download B for r2, then release A. The saved revision became 1. | `src/core/learning/actions.ts:saveLessonOffline`, `ContentStore.replaceLesson` | Serialize updates per lesson/locale or conditionally commit against the observed request generation. A late operation must not undo the more recent choice. Preserve intentional editorial rollbacks. Keep the two-request gated test. |
| QA-3 · High, unreadable saved content | Save r1. Return r2 whose only block is a paragraph missing its text. After replacement SQLite held r2, and the reader renders missing paragraph text as an empty string. | `src/core/api/validate.ts:validateLessonSnapshot`, lesson reader `BlockView` | Validate the required fields of recognized block types before replacing a valid revision. Keep the previous copy on validation failure. Retain the truncated-but-valid-JSON regression. |
| QA-4 · Medium, withdrawal status | Save a lesson, cache a fresh empty catalog in the same locale, call `checkForUpdates`. It returned `up_to_date`. | `src/core/learning/contentAccess.ts:checkForUpdates` | Return an unlisted/unknown result for absence and distinguish a missing or stale catalog. Only report current for a matching listed revision. Add omission and missing-catalog tests. This helper currently has no UI. |
| QA-5 · Medium, misleading recovery advice | With an empty session cache, return HTTP 503 while opening a lesson. The result had `reason: offline`; the reader says the student has no Internet. | `contentAccess.ts:reasonOf`, lesson reader error mapping, FR/HT strings | Distinguish service failure from connection loss and provide retry in either case. Retain the 503 test and add a localized screen assertion. |
| QA-6 · Medium, future assessment boundary | Feed the practice downloader a synthetic unknown assessment mode with otherwise valid practice-shaped data. The lesson and its practice key were persisted. | `src/core/api/validate.ts`, `downloadForOffline` | Require the current practice discriminator before caching or saving. Keep protected assessments server-scored with their own response contract. Add unknown/missing-mode tests. The server must omit protected keys before sending any response. |
| QA-7 · High, isolation precondition | Pass the harness a disposable project name, matching admin and gateway URLs, and an API service DSN for a different disposable port. With container liveness injected, `deriveTarget` accepted the configuration. No network requests were made. | `tests/support/localStack.js:deriveTarget`, `globalSetup.js` | Validate the effective API, database and Auth endpoints used by the child against this checkout and its running container bindings before spawning or resetting. Reject process overrides that redirect them. Keep the mixed-port test and add an inherited-environment case. |

## Corrective retests before publication

At local native reconciliation `e2e902e9701ccbd1ef19074fe9e047c4b477e8d2`, both TypeScript checks passed. The existing delivery configuration passed 263 cases and failed the same three socket binds. All 94 tests in the separate experience directory passed. The independent probes still recorded 2 passes and 8 failures.

At local correction `aefbad60aeb3b1f892c1697d27b90ad6586072b0`, both TypeScript checks and all 30 new continuity/freshness regressions passed. Of the ten independent probes, five passed and five failed. **QA-1 and QA-4 passed the independent retest.** QA-2, QA-3, QA-5, QA-6 and QA-7 reproduced. A follow-up strengthened the two screen assertions to require the lesson title, required the exact not-listed status, and added a sign-out race through the real SessionManager with a delayed synthetic Auth refresh and database reopen. Six of 11 probes passed; the same five failed. The restarted account stayed with learner B and could not read learner A’s marker. The corrective real-stack tests for online reading and withdrawal subsequently passed on the published SHA.

**QA-8 · High, Android runner isolation.** The default Android port-forward path checked the database project, then forwarded the device to fixed host ports. Running only its `backend reachable` function with a recording ADB stand-in emitted `reverse tcp:8000 tcp:8000` and `reverse tcp:54321 tcp:54321`. The stand-in contacted no device or service. The script can therefore use a different API/Auth pair from the stack it inspects. Derive both forwards from the verified runtime endpoints and require an exact device serial. Add a recording-adapter test with nondefault ports. The independent GitHub job uses a dedicated emulator, explicit reverse mappings and a new Supabase project on its own VM.

### Old-phone efficiency

On `aefbad60aeb3b1f892c1697d27b90ad6586072b0`, I populated temporary SQLite with 1, 25 and 100 two-question lessons and counted the account and content drivers' `first` and `all` calls during one `learningStandings` read. The counts were 6, 102 and 402. Home and Réviser use this operation on focus. Before large libraries ship, measure focus-to-render on API 24 and consider a bounded set of summary queries that avoid loading paragraph bodies. These are query counts from Node SQLite; device latency remains unmeasured.

## Reproduction

Use a separate checkout at the recorded snapshot. For the published run, use the full SHA in `CANDIDATE`. Use the matching locked dependencies. Run the existing suite before copying the independent probes so the counts stay distinct.

```sh
cd apps/student-native
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/tsc --noEmit -p tests
./node_modules/.bin/jest -c jest.delivery.config.js --runInBand
cp "$QA_REPORT_DIR/acceptance.test.tsx" tests/delivery/qa.acceptance.test.tsx
./node_modules/.bin/jest -c jest.delivery.config.js --runInBand --runTestsByPath tests/delivery/qa.acceptance.test.tsx
```

`QA_REPORT_DIR` is the absolute directory containing this report in the QA checkout. The probes use disposable SQLite files only. For the full integration gate, use fresh project, database, gateway, API listener, PID/log paths and account credentials; verify actual port ownership and all effective endpoints first. Leave the shared-stack override unset. Use a dedicated emulator or AVD, install the candidate build, and verify its endpoint configuration before starting it.

## Historical disposition of #25 before the corrective PR

| Review target | Verdict on the recorded revisions | Evidence needed for approval |
| --- | --- | --- |
| #3 Mobile-02 | Hold approval as part of #25. The standalone #3 head has CI evidence only. | All six device configurations passed on #25. Resolve the stale connectivity header (QA-9) and recheck recovery on the proposed merge head. |
| #22 Content-Delivery-00 | Hold. The combined candidate can lose an offline revision, install unreadable content and misreport availability. | Independently rerun QA-2, QA-3, QA-5 and QA-6 after corrections. Retain the passing online progress, deletion, sync and withdrawal regressions. |
| #25 consolidated candidate | Hold. The independent branch adds endpoint safeguards for its own disposable runner. The candidate harness and device script still accept inconsistent targets. | Correct QA-7 and QA-8, resolve QA-9, then rerun the live and device suites on the new exact SHA. |

The owner still needs to decide access to already downloaded withdrawn materials and which future papers are controlled exams. Native Haitian Creole wording needs educator review. Physical-device startup time, sustained memory pressure and low-storage behavior remain unmeasured. No production data or credentials were used.
