# 1. Information architecture and wireframe-level screens

Desktop-first (≥ 1280 px; usable at 1024 px). French first; English labels may be added for staff later. Left navigation, global search
(by id/email only for roles allowed), a persistent **environment banner** (`LOCAL`, `STAGING`, `PRODUCTION` in colour + text), and the
signed-in staff member's role(s).

```
┌──────────────┬────────────────────────────────────────────────────────────┐
│ Edupreneurs  │  [PRODUCTION]                       🔎 search      ▾ Marie (publisher) │
│ Admin        ├────────────────────────────────────────────────────────────┤
│              │                                                            │
│ ▸ Tableau    │                     (page)                                 │
│ ▸ Contenu    │                                                            │
│ ▸ Examens &  │                                                            │
│   bibliothèque                                                            │
│ ▸ Mot du jour│                                                            │
│ ▸ Or & jeux  │                                                            │
│ ▸ Jude IA    │                                                            │
│ ▸ Administration                                                          │
│ ▸ Paiements  │                                                            │
└──────────────┴────────────────────────────────────────────────────────────┘
```
Nav items appear only if the role can use them (server still enforces).

## A. Tableau de bord
Rows of **metric tiles** (value, period, definition tooltip linking to doc 3, freshness timestamp "données au …", `—` with the reason when a source
is not available). Never a number without its definition and time window.

```
Apprenants inscrits   12 480   ▲ +312 (7 j)      Actifs (jour / mois)   1 905 / 6 220
Leçons terminées (7 j) 9 870                      Précision des réponses 71 %  (serveur)
┌ Inscriptions par semaine ────────┐  ┌ Engagement par classe et matière ──────────┐
│  line chart                      │  │  heat-map, groups < K are hidden           │
└──────────────────────────────────┘  └────────────────────────────────────────────┘
Santé de la synchronisation: opérations rejetées 0,4 % · en attente la plus ancienne —  (needs event)
Infrastructure: API ● · Base de données ● · Worker — (no worker deployment yet)
```
Small groups are suppressed (see doc 3 privacy tiers).

## B. Contenu éducatif
* **Catalogue**: grade → subject → unit → lesson tree; status chips (draft / in review / approved / published / withdrawn).
* **Lesson revision editor** (two panes: structured blocks | live phone preview at 320 dp, fr/ht tabs). Blocks per contract (v1 now; v2 gated). Validation errors inline by rule code.
* **Sources & rights** panel per revision (source, licence, rights status) — required before submit.
* **AI-assisted draft**: "Generate draft" creates a revision marked `ai_assisted`, authored by the requesting editor, visibly badged; it can never be approved by its author (existing rule: reviewer ≠ author).
* **Review queue**: diff vs previous revision, checklist (accuracy, language, copyright), approve / request changes (comment mandatory).
* **Publication**: pack builder → preview manifest (lessons, bytes, assets) → release → **rollback** and **withdraw** (takedown; missing today). Each shows who/when and requires step-up auth.
* **Assets & media**: upload, hash, usage references, rights; cannot delete an asset used by a published revision.

```
Revisions › Fractions (9AF) › v4  [IN REVIEW]
┌ Blocks ─────────────────┐ ┌ Preview 320dp ───┐ ┌ Review ────────────────┐
│ ⠿ heading  …            │ │                  │ │ Author: A. · Reviewer:—│
│ ⠿ paragraph …           │ │                  │ │ Sources: 2 ✔ rights ✔  │
│ ⠿ example  …            │ │                  │ │ [Approve] [Changes…]   │
└─────────────────────────┘ └──────────────────┘ └────────────────────────┘
```

## C. Examens et bibliothèque
Resource list by kind (practice exam, controlled exam, e-book, PDF, resource). **Class field (practice vs controlled)** is explicit and drives
delivery (Content-Delivery-00 ADR-8). Book record: file upload, hash, size, licence, territory, validity, entitlement rule, covers. Withdraw/replace with audit.

## D. Mot du jour
Word list (fr/ht), revision editor (word, definition, example sentences, pronunciation, optional audio with transcript), review queue (existing reviewer≠author), **calendar** (Haiti date; published days are immutable — existing DB rule), "ensure schedule" action, retire word.

## E. Or et engagement
Rule versions (reward amounts as data, activation date), achievements, streak policy (read-only view of Haiti-midnight rule), leaderboard policy (K floor, refresh schedule, eligibility), fraud signals (duplicate-op anomalies, abnormal earn rates — requires new queries). **Enabling any of these is gated by owner decisions** (PO-09, 2-C1…2-C4); the console shows the flag state and the gate.

## F. Jude IA
Model/provider configuration, per-feature flags, token usage and cost by day/feature, budgets with hard stops, error rates, provider health. **Entirely new** (no backend). No prompts or student text are displayed.

## G. Administration et sécurité
* **Support**: look up a learner by id/e-mail → *minimal* view (account state, grade, last sync time, pending-op count, entitlements) — no answers/profile text by default; each lookup is audited with a reason.
* Moderation queue (reports, if/when community exists — Social-00), announcements, notification campaigns (outbox; dummy adapter today).
* **Staff & roles**: grant/revoke with last-admin protection; **Audit log** viewer (filter by actor, action, target, date; export); operations (restore drill status, readiness checks, feature-flag state).
* Account lifecycle (export/erasure requests) — visible only when `EDU_ACCOUNT_LIFECYCLE_ENABLED` is allowed (**blocked by S3**).

## H. Paiements et activité commerciale
Plans/prices, entitlements and grants/revocations (exists), MonCash and other providers (events, orders, refunds), subscriptions, gifts, promo codes, **reconciliation** (provider vs ledger, mismatches queue). Read-only until the billing modules are approved; money-moving actions need step-up auth and two-person approval above a threshold (owner decision).

## Cross-cutting UI rules
* Every destructive/outward action: confirmation with the exact object, reason field, and an audit receipt shown afterwards.
* No student free text is rendered as HTML anywhere (plain text only — same rule as the content contract).
* Accessible: keyboard navigable, visible focus, contrast per Design-00 tokens, tables with real headers.
