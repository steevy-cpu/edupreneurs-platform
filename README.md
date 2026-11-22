# Edupreneurs — platform backend and student app

> **Naming.** The product is **Edupreneurs**. "Mon Edupreneur" is the domain
> (mon-edupreneur.com) and the name of this repository; older documents here use
> "Mon Edupreneur 2.0" as the project's working title.

Backend for an offline-first learning platform for Haitian learners (7AF–NS4) on
unreliable networks and older phones. This repository currently contains
**Foundation-01**: the database, authentication, a small real API, and the
offline synchronisation contract — all running **locally only**.

> **Status:** local development foundation. Not deployed anywhere and **not
> production-ready**. See `docs/NEXT_STEPS.md` for what is missing before a cloud deployment.

## What is in here

| Path | What it is |
|---|---|
| `supabase/migrations/` | The database schema — the single source of truth (4 ordered SQL files) |
| `supabase/seed.sql` | Synthetic test data: 2 students, an editor, a reviewer, one 9AF maths lesson in French and Haitian Creole, 5 practice questions |
| `supabase/tests/` | Database tests (pgTAP): structure, permissions, publication rules, sync function |
| `services/api/` | The FastAPI service (Python) |
| `tests/` | API tests (pytest): unit + integration against the real local database and Auth |
| `packages/contracts/` | OpenAPI contract and JSON Schemas for lesson content |
| `scripts/` | Local-only helpers (setup, get a test token, export the contract) |
| `docs/` | Architecture, security, API contract, schema changelog, test report, next steps |
| `docs/reference/` | The original v0.2 drafts and the assignment, kept unmodified for comparison |
| `apps/student-native/` | React Native (Expo) student app — Mobile-01. See its README and `docs/MOBILE_01_REPORT.md` |
| `services/worker/` | Reserved for future workers (empty on purpose) |

## Prerequisites (macOS or Linux)

| Tool | Why | Install |
|---|---|---|
| Docker-compatible runtime (Docker Desktop, OrbStack, Colima, or Docker Engine on Linux) | Runs local Postgres + Supabase Auth | docker.com / orbstack.dev |
| Node.js 20+ and npm | Only to install the pinned Supabase CLI | nodejs.org or `nvm` |
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.13 and the Python dependencies from `uv.lock` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| GNU make | Task runner | preinstalled on macOS (Xcode tools) and most Linux |

You do **not** need a Supabase account, a cloud project, or any secret from anyone.

## First-time setup

```bash
make setup
```

This one command: installs the pinned tools, generates a local Auth signing key,
starts the local stack in Docker, rebuilds the database from the migrations and
seed, writes a git-ignored `.env`, and creates the API's least-privilege database login.
The first run downloads about 1.5 GB of Docker images.

## Daily commands

| Command | What it does |
|---|---|
| `make start` / `make stop` | Start / stop the local stack (data is kept between stops) |
| `make db-reset` | **Destroys and rebuilds the local database** from migrations + seed, then re-creates `.env` and the API login |
| `make api` | Run the API at http://127.0.0.1:8000 — interactive docs at http://127.0.0.1:8000/docs |
| `make token ACCOUNT=student_a` | Print a real local access token (`student_a`, `student_b`, `editor`, `reviewer`) |
| `make test-db` | Database tests (pgTAP) |
| `make test-api` | API tests (pytest) |
| `make test` | Both |
| `make lint` / `make typecheck` / `make format` | Ruff and mypy |
| `make check` | Everything CI runs |
| `make openapi` | Regenerate `packages/contracts/openapi.json` after changing the API |
| `make status` | Show local stack URLs |
| `make mobile-install` / `mobile-check` / `mobile-test` | Mobile app: install, static checks, 52 core tests against the local stack |
| `make dev-login ACCOUNT=student_a` | Print an e-mail + password to type into the app |
| `make mobile-env TARGET=ios-sim` then `make mobile-ios` | Configure and run the app on the iOS Simulator (`android-emu` / `mobile-android` for Android) |

### Try it by hand

```bash
make api                                   # terminal 1
TOKEN=$(make -s token ACCOUNT=student_a)   # terminal 2
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/me
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/v1/catalog?locale=ht"
```

More examples, including sync push/pull, are in `docs/API_CONTRACT.md`.

## How the pieces fit (30 seconds)

1. The phone signs in with **Supabase Auth** and gets a short-lived access token.
2. The phone calls **our FastAPI service** with that token. The API verifies the
   token's signature with Auth's public key — the API itself cannot create tokens.
3. The API talks to **PostgreSQL** as a restricted role. For each request it opens one
   transaction and tells the database "this transaction is for user X". Row-level
   security then only shows that user's rows.
4. Learning data (answers, scores, progress) can only be written by one database
   function, which scores the answer itself and guarantees each offline operation
   is applied exactly once.

Details: `docs/ARCHITECTURE.md` and `docs/SECURITY.md`.

## Safety rules for this repository

- **Local only.** Never run `supabase link`, `supabase db push`, or `supabase db reset --remote` from here.
- `make db-reset` only ever targets the local Docker database.
- Never commit `.env` or `supabase/signing_keys.json` (both are git-ignored).
- All data is synthetic. Do not load real student data into a development database.
- The existing Lovable application is unrelated: nothing here connects to it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop / OrbStack, then `make start` |
| `port is already allocated` (54321/54322) | Another local Supabase project is running: `npx supabase stop` in that project, or stop the container using the port |
| Tests fail with `.env is missing [...]` | The stack was never set up: `make setup` |
| API returns 503 `dependency_unavailable` | The database is not running (`make start`) or `.env` is stale (`make db-reset`) |
| `password authentication failed for user "edu_api_login"` | The login role is gone after a rebuild: `make db-reset` (re-creates it) |
| Tokens are rejected right after `make db-reset` on a fresh machine | The signing key changed; get a new token with `make token` |
| A database test fails after you edited content by hand | `make db-reset` restores the exact seed state |
| Want the Supabase dashboard | Set `[studio] enabled = true` in `supabase/config.toml`, then `make stop && make start` (http://127.0.0.1:54323) |
