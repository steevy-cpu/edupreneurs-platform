# V1 feature parity: prototype → mobile (2026-11-26)

**Directive:** Mon-Edupreneur is a live web prototype with 61 students, not a new MVP. The mobile application must preserve the core functionality they use.

**Status of this folder:** analysis and plans for owner decisions. Nothing was merged, deployed, imported, published or approved. No production student record, message or payment detail was accessed. No paid provider was called.

| Document | Mission |
|---|---|
| `01-feature-parity-matrix.md` | B: feature-parity matrix |
| `02-reuse-architecture.md` | C: reuse versus rebuild, identity, integration contracts |
| `03-curriculum-exam-readiness.md` | D: content and exam inventory, import pipeline, ExamHub design |
| `04-jude-live-plan.md` | E: Jude live-integration plan and bounded evaluation |
| `05-social-parity-gap.md` | F: social parity and safety gap |
| `06-release-backlog.md` | Dependency-ordered backlog |

## Evidence base and its limits

* Prototype: read-only inspection of the connected Lovable project source. **Not run. Database not queried.** "Exists" means present in source, not proven to work for students. Roughly 25 files were read directly; other points rely on the earlier Platform-00 audit and are less certain.
* Rebuild: `main` at `1094eb0` and the open pull requests; test figures quoted from repository reports.
* Content volumes (lessons, exams) and real usage of social features are **unknown** until the owner runs aggregate counts.

## The situation in six lines

1. `main` is a tested offline lesson, practice and sync slice with **one synthetic 9AF lesson**.
2. **Exams did not exist in the rebuild at all**; a first server-authoritative slice is implemented in a separate PR.
3. **Jude** is a mock-only engine in unmerged PRs; nothing live, no approved content to ground on.
4. **Community** is design-only, and the design (a noticeboard) is a different product from the prototype's social network.
5. **Existing students cannot sign in to their accounts from mobile**, and the recorded architecture decision was "do not migrate".
6. **39 draft PRs are open**; the overnight stack with accounts, notifications, rewards and the staff pipeline is 60 commits behind `main`.

## Highest-impact blockers

| # | Blocker | Why it matters | Who |
|---|---|---|---|
| 1 | **OD-1 identity continuity is undecided, and contradicts ADR-008** | No history or identity work can start | Owner |
| 2 | **No approved real content, and no named reviewers (OD-2, OD-3)** | "Complete curriculum" depends on human review volume; Jude has nothing to retrieve | Owner |
| 3 | **Content and exam volumes unknown** | Cannot size import or review | Owner-run counts |
| 4 | **Community model (OD-4) and legal position on minors (OD-5)** | All social work; DMs between minors are the highest-risk feature | Owner + counsel |
| 5 | **Jude Gate 0** (provider, terms, consent, safeguarding) and re-review of #43 | Live tutoring | Owner + Codex #1 |
| 6 | **Merge debt**: #4 stack, Jude stack, content and staging stacks | Account functions, notifications, rewards all sit there | Reviews |
| 7 | **No hosted environment; `main` unprotected** | No pilot, no secret store, checks are advisory | Owner |

## Owner decisions

| ID | Decision | Recommendation |
|---|---|---|
| OD-1 | Existing accounts: link on first login vs re-register | Link (Option A in `02-…`), rehearsed on synthetic fixtures first |
| OD-2 | Imported legacy lessons: status in the new platform | Draft until a human approves; no automatic "approved" |
| OD-3 | Reviewers | Name subject teachers and a native Creole speaker; size the workload after the counts |
| OD-4 | Community model for v1 | Noticeboard + moderated class group chat; no one-to-one DMs in v1 |
| OD-5 | Legal basis: minors' consent, data migration, third-party AI | Counsel |
| OD-6 | Legacy Gold and exam scores (client-supplied) | Do not import as records; optional one-time goodwill grant |
| OD-7 | Students with remaining paid time | Honour through entitlements; payments stay on web (v2) |
| OD-8 | Prototype features in neither list (Quiz Battle, e-book library, lesson audio, daily word, notes/favourites/goals, Google sign-in, subject tutors, referrals…) | Per-feature choice in `01-…` section C |
| OD-9 | Open-ended exam answers graded by AI | Self-review in v1; AI grading after Jude gates |

## Pull requests referenced

Content: #31 → #37 → #41 (corrected `d33edb6`), QA #34, #38, #44 and `qa/content-02a-retest-10620ea`. Staging: #33 → #39 → #42 → #46 (`1e42eaf`), QA #36, #40, #45. Jude: #28, #30, #35, #43. Social: #1. Overnight stack: #4–#21. Mobile: #22, #24, #32. Merged baseline: #2, #3, #20, #23, #25, #26, #27, #29.
