# Independent Mobile-02 and Content-Delivery-00 QA

**Verdict on 26 November 2026: hold #3 and #22 as an integration.** This draft records preliminary results while the developer prepares a candidate. The findings below apply to the immutable snapshot identified here. Final candidate verification, corrective retesting and device acceptance are pending.

## Provenance

| Ref | Verified revision | Scope |
| --- | --- | --- |
| main | `6ad3fdbf40d07238274e841d73cff17e72355346` | Contains #20, #2 and #23 |
| #3 | `54fec1c9547a23f644b504b5498385c252e94357` | Mobile-02, including Design-00. [CI passed](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45514360028) |
| #22 | `e30c81645b528ab508b94796e7954a57fd1e9ef5` | Content delivery, based on #3. [CI passed](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45818568188) |
| #15 | `202c12f680d0ac67cf793d39a2fbe8dcdaed3cb2` | Native corrections, based on #8. [CI passed](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45625961541) |
| Independently tested local snapshot | `fec0920370d8f91bf975733cdbac08d5b38c3f60` | Merges #3 and #22 onto hardened main. Predates the local native reconciliation. |
| Published consolidated candidate | Pending | Requires a GitHub ref and exact SHA. |

QA used a detached checkout, its own Node dependencies, synthetic accounts, temporary SQLite files and a fake API. The QA branch contains review materials only. The platform-stabilization commit remains on its original branch. Product comparisons use the repository's Lovable inventory, Mobile-02 report and Content-Delivery-00 decisions. No live prototype comparison was performed.

## Evidence by gate

| Gate | Observed result |
| --- | --- |
| App and test TypeScript | Both passed. The independent regression file also type-checked in the test checkout. |
| Existing delivery Jest config | 155 passed, 3 failed. Delivery 14/14, online screens 9/9, other screens 19/19, overview 6/6, design 76/76, core 17/17, local stack 9/9, port checks 5/8. The three failures were loopback bind errors (EPERM). |
| Independent acceptance probes | 2 passed, 8 failed across seven findings below. Both account switching with queued work in synthetic A/B account stores and cancellation during response-body reading passed. |
| Shared-target safety | The shared project is refused with the default harness settings. The reviewed global setup, local stack helper, test device and sync resilience test match #20 on this snapshot. A mixed-endpoint refusal test failed (QA-7). No shared database, gateway, API or Auth service was used. |
| Real Supabase, API/Auth and offline sync suites | Blocked by sandbox denial at the OrbStack socket. End-to-end upload, server receipt, retry and reconciliation remain unverified here. |
| API 24 at 320 dp | All six cells pending: fr and ht, each at 1.0, 1.3 and 2.0. ADB failed to bind its local listener. No screenshots, physical-device timings or layout verdict are available for this snapshot. |

### Functional coverage

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

## Confirmed findings

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

At local correction `aefbad60aeb3b1f892c1697d27b90ad6586072b0`, both TypeScript checks and all 30 new continuity/freshness regressions passed. Of the ten independent probes, five passed and five failed. **QA-1 and QA-4 passed the independent retest.** QA-2, QA-3, QA-5, QA-6 and QA-7 reproduced. The developer also added real-stack tests for online reading and withdrawal; those require the live gate.

**Android runner isolation (High, e2e-run.sh at e2e902e).** The default Android port-forward path checked the database project, then forwarded the device to fixed host ports. Running only its `backend reachable` function with a recording ADB stand-in emitted `reverse tcp:8000 tcp:8000` and `reverse tcp:54321 tcp:54321`. The stand-in contacted no device or service. The script can therefore use a different API/Auth pair from the stack it inspects. Derive both forwards from the verified runtime endpoints and require an exact device serial. Add a recording-adapter test with nondefault ports. The independent GitHub job uses a dedicated emulator, explicit reverse mappings and a new Supabase project on its own VM.

## Reproduction

Run in a separate checkout pinned to the SHA above. Use the matching locked dependencies. Run the existing suite before copying the independent probes so the counts stay distinct.

```sh
cd apps/student-native
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/tsc --noEmit -p tests
./node_modules/.bin/jest -c jest.delivery.config.js --runInBand
cp "$QA_REPORT_DIR/acceptance.test.tsx" tests/delivery/qa.acceptance.test.tsx
./node_modules/.bin/jest -c jest.delivery.config.js --runInBand --runTestsByPath tests/delivery/qa.acceptance.test.tsx
```

`QA_REPORT_DIR` is the absolute directory containing this report in the QA checkout. The probes use disposable SQLite files only. For the full integration gate, use fresh project, database, gateway, API listener, PID/log paths and account credentials; verify actual port ownership and all effective endpoints first. Leave the shared-stack override unset. Use a dedicated emulator or AVD, install the candidate build, and verify its endpoint configuration before starting it.

## Decisions and merge gates

The owner still needs to decide access to already downloaded withdrawn materials and which future papers are controlled exams. Missing or stale catalog evidence must be described accurately under either policy. Native Haitian Creole wording needs educator review. No pass is claimed for low-memory startup time, storage pressure on the device, Android process restart or large-text reachability.

Hold consolidated approval until the online progress, download replacement and harness isolation findings are corrected and independently retested. Carry the exact published head into live sync and the six emulator runs. A passing report-only PR workflow does not exercise these downloaded regression probes against the candidate.
