# Architecture

**Stack:** React 19, TypeScript (strict), Vite, React Router (hash routing). Runtime dependencies: **three** (`react`, `react-dom`,
`react-router-dom`), exact versions. Charts are ~150 lines of local SVG (`components/charts.tsx`) instead of Recharts: no third-party
runtime for a staff tool handling minors' data, strict-CSP friendly, every chart has a text alternative and a real data table.
Dev tooling: Vite, Vitest, Testing Library, axe-core, ESLint.

```
src/
  domain/      pure rules transcribed from Admin-00: roles.ts (doc 2), metrics.ts (doc 3), blocks.ts (v1 contract), editorial.ts (workflow)
  data/        synthetic fixtures + in-memory EditorialStore  (the mock of the future API client)
  state/       Services (typed adapter), RolePreview (synthetic persona)
  components/  Shell, MetricTile, charts, Heatmap, BlockEditor, PhonePreview, ConfirmDialog …
  pages/       Dashboard, MetricCatalog, Content*, RolesPage, ModulePage (truthful placeholders)
```

## The adapter

`state/Services.tsx` defines `AdminServices { getDashboard(); editorial: EditorialStore }`. Screens never import fixtures. The future
OpenAPI-generated FastAPI client implements the same shapes (`domain/dashboard.ts` mirrors `GET /v1/staff/metrics/{id}`; `EditorialStore.dispatch`
mirrors the revision/review/pack routes and returns an **audit receipt**, today a clearly labelled synthetic one).

## Source of truth

* **Metrics:** `domain/metrics.ts` holds the 21 definitions; a test parses `03-metric-catalog.md` and checks ids, tier and availability.
* **Roles:** `domain/roles.ts`; a test parses the matrix in `02-roles-and-permissions.md` cell by cell.
* **Lesson blocks:** `domain/blocks.ts`; a test compares limits and key pattern with `packages/contracts/content/lesson-blocks.schema.json`.
  Only v1 (heading, paragraph, example, callout). Unknown/v2 types are **rejected**, not rendered; no claim of v2 compatibility.

## Honest states

Every tile is one of: `fixture` (SYNTHÉTIQUE badge), `stale` (amber after 2× refresh), `unavailable` (reason shown: M4 app opens, M10 downloads,
M11 online reads, M13 device sync, M14 exams, M19 Jude AI, M20 revenue, M21 individual fraud signals) or `restricted` (M21 for non-admins).
Small groups (< K=5, provisional) are suppressed before reaching the UI; no individual learner record exists anywhere in the app.

## Deviations from Admin-00 / interpretation (please review)

1. **Section access per role is derived** from the per-action matrix (`SECTION_ACCESS`, with a stated basis). Where Admin-00 is silent
   (exams, moderation, Jude, Gold, leaderboard) the default is admin-only (deny by default).
2. "Limited" analytics for editor/reviewer/publisher shows M5, M7, M8, M16 in the demo. The real limit (“own content”) is server-side.
3. The **author ≠ publisher** rule is shown although Admin-00 lists it as *to add* (flagged in the UI as such).
4. Rollback and withdraw are demonstrated although the server has no withdraw route (L-B2-3); the UI says so.
5. French only (strings inline in components); an i18n layer is deferred until English staff labels are wanted.
6. `?persona=` URL parameter exists for demos/screenshots only; it is not authentication.
