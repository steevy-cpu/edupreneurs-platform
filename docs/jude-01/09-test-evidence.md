# 9. Test evidence

Run on 2026-11-26, branch `feature/jude-01-grounded-tutor`, macOS, Python 3.13.

## Commands and results

| Check | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 131 files already formatted |
| Types (strict) | `uv run mypy` | Success: no issues found in 52 source files |
| API contract unchanged | `uv run python scripts/export_openapi.py --check` | openapi.json is up to date |
| Tutor contracts fresh | `uv run python -m edu_api.tutor.contracts --check` | up to date |
| All unit tests | `uv run pytest tests/unit` | **392 passed** (71 pre-existing + 321 tutor) |
| Tutor unit tests | `uv run pytest tests/unit/tutor` | **321 passed** |
| Budget on real PostgreSQL | `JUDE_TEST_ADMIN_DATABASE_URL=… uv run pytest tests/tutor_pg` | **23 passed** (see below) |
| Mock demonstration | `uv run python -m edu_api.tutor.demo` | runs offline; transcript below |

Tutor unit tests by file: `test_service` 87 · `test_safety` 56 · `test_prompts`
54 · `test_gateway_and_providers` 34 · `test_validation` 29 · `test_budget` 21 ·
`test_retrieval` 14 · `test_privacy` 11 · `test_router` 10 · `test_contracts_and_demo` 5.

### PostgreSQL tests: how they were run

- **Throwaway server.** A private `postgres:16-alpine` container started for
  this worktree only (random local port, data in memory, removed afterwards).
  The shared local Supabase stack used by the other agents was **not** touched.
  23 passed, three consecutive runs of the budget suite, no flakiness seen.
- **CI-like roles.** The same suite also passed against that container with a
  *non-superuser* admin and a real `edu_api_login` login role, which is how the
  project's Supabase PostgreSQL is set up (its `postgres` role is not a superuser).
- Each session creates its own database, applies the proposal, and drops it.

## Acceptance tests requested → where they are

| Requirement | Test(s) |
|---|---|
| Correct approved lesson retrieval | `test_retrieval.py::test_question_about_subtracting_finds_the_balance_principle`, `::test_lexical_baseline_meets_its_bar_in_both_languages`; integration `test_published_seed_lesson_is_read_in_both_languages` |
| Rejected or withdrawn lesson refusal | `test_service.py::test_unapproved_revisions_are_refused[draft/in_review/rejected]`, `::test_a_withdrawn_lesson_is_refused`, `::test_a_newer_draft_does_not_replace_the_published_revision`; integration `test_draft_in_review_and_unreleased_revisions_do_not_exist_for_the_tutor` |
| Wrong-learner access denial | `::test_a_lesson_another_learner_may_read_is_refused_to_this_one`, `::test_the_request_cannot_name_a_learner`, `::test_usage_is_accounted_to_the_caller_only`; `test_router.py::test_a_body_naming_another_learner_is_rejected`; PG `test_one_learner_cannot_settle_or_release_anothers_reservation`, `test_the_api_role_cannot_read_or_write_any_tutor_table` |
| French/Creole locale selection | `::test_creole_lesson_is_answered_in_creole_with_creole_references`, `::test_french_lesson_can_be_explained_in_creole`, `::test_fixed_messages_follow_the_answer_language`, `::test_an_unsupported_locale_is_rejected_by_the_contract` |
| Correct reference attribution | `::test_question_about_the_lesson_gets_a_cited_grounded_answer`, `::test_references_point_only_at_passages_that_were_actually_supplied`; `test_validation.py::test_valid_answer_gets_real_references_for_the_ids_it_cited` |
| Missing-context behaviour | `::test_a_question_the_lesson_does_not_cover_gets_a_limitation_not_an_answer`, `::test_model_saying_it_lacks_context_becomes_the_reviewed_limitation`; `test_retrieval.py::test_unrelated_question_retrieves_nothing` |
| Hallucinated references | `test_validation.py::test_a_reference_the_server_did_not_issue_is_rejected[5 cases]`, `::test_a_real_looking_lesson_id_is_not_accepted_as_a_reference`; `test_service.py::test_an_invented_reference_is_never_shown_and_is_retried` |
| Unrelated retrieved passages | `test_retrieval.py::test_only_passages_of_the_requested_lesson_are_ever_returned`, `::test_unrelated_question_stays_unanswered_even_with_a_block_in_focus` |
| Prompt injection | in content: `test_prompts.py::test_system_message_depends_only_on_closed_choices_never_on_content`, `::test_untrusted_text_is_confined_to_one_escaped_json_document`; `test_service.py::test_instructions_hidden_in_lesson_text_stay_in_the_data_message`, `::test_a_model_that_obeys_injected_text_is_caught_before_the_student_sees_it`; from the student: `::test_a_student_trying_to_change_the_rules_gets_a_fixed_reply_and_no_model_call` |
| Invalid structured model output | `test_validation.py::test_malformed_output_is_rejected[9 cases]`; `test_service.py::test_output_that_stays_invalid_fails_safely[7 behaviours]` |
| Provider timeout and retry | `test_service.py::test_provider_timeout_is_retried_and_then_succeeds`, `::test_provider_timeout_after_all_retries_is_a_stable_error`; `test_gateway_and_providers.py::test_timeout_is_retried_with_backoff_then_succeeds`, `::test_retries_are_bounded` |
| Duplicate usage requests | `test_service.py::test_duplicate_request_is_refused_without_a_second_provider_call`, `::test_a_duplicate_sent_while_the_first_is_in_flight_is_refused`; PG `test_duplicate_keys_are_refused_and_charged_once`, `test_the_same_request_sent_many_times_at_once_is_admitted_once` |
| Concurrent budget reservations | PG `test_concurrent_reservations_never_exceed_the_global_ceiling`, `test_concurrent_reserve_and_settle_keep_the_books_exact`, `test_per_learner_concurrency_holds_under_a_burst`, `test_concurrent_learners_cannot_overshoot_the_ceiling_through_the_service`; in-memory equivalents in `test_budget.py`, `test_service.py` |
| Budget exhaustion | `test_service.py::test_daily_allowance_is_enforced_before_the_provider_is_called`, `::test_exhausted_global_budget_refuses_everyone_without_a_provider_call`; `test_budget.py::test_each_limit_refuses_with_its_own_stable_error` |
| Global kill switch | `test_service.py::test_kill_switch_stops_requests_before_any_provider_call`, `::test_static_kill_switch_in_settings_also_stops_requests`; PG `test_kill_switch_refuses_and_is_audited`, `test_schema_starts_paused_with_zero_limits` |
| No persisted student conversation text | `test_privacy.py` (all 11); PG `test_no_column_can_hold_conversation_text`, `test_answer_is_accounted_once_and_no_text_reaches_the_database` |
| No external provider calls in the test suite | `tests/unit/tutor/conftest.py::no_network` (autouse: any socket connect fails the test); `test_gateway_and_providers.py::test_a_live_provider_is_refused_without_explicit_authorisation`, `::test_defaults_are_the_safe_ones`; the real adapter is driven only by `httpx.MockTransport` |
| Jude is not in the live app | `test_router.py::test_the_production_app_exposes_no_jude_route`, `::test_shared_application_files_do_not_import_the_tutor`; integration `test_jude_01_adds_nothing_to_the_application_database` |

## Not verified — stated plainly

| Item | Why | Consequence |
|---|---|---|
| `tests/integration/test_tutor_lesson_source.py` (6 tests: `SqlLessonSource` under the real row-level security) | It needs the full local Supabase stack. The only one on this machine is shared with the other agents, and the repository's integration fixtures truncate learning tables on it, so it was **not run locally**. | It runs in CI on the pull request. Until that run is green, RLS-backed lesson reading is verified only by reading the SQL (it is the same query as `GET /v1/lessons/{id}`) and by the in-memory double. See the PR for the CI result. |
| `tests/tutor_pg` on the project's PostgreSQL 17 image | Run locally on PostgreSQL 16 only | Also runs in CI |
| Any real model: answer quality, staying in Creole, obeying support levels, resisting injection | No live call is authorised | Unknown. First task of Jude-02 |
| The OpenAI-compatible adapter against a real endpoint | Same | Request/response mapping tested against an in-memory transport only; real-world quirks (streaming flags, provider-specific fields, usage reporting) unverified |
| Semantic-embedding retrieval | No embedding model authorised | Not compared; only lexical rankers measured |
| The safeguarding screen on real student language | No real messages exist | Coverage unknown; needs expert and native-speaker review |
| Haitian Creole wording (fixed messages, synthetic lesson, mock phrases) | Written by the model that built this; not reviewed by a native speaker | Must be reviewed before any learner sees it |
| Load and latency | No load test | Global-counter contention at scale unknown |
| Mobile behaviour, including "offline never shows a Jude answer" | Mobile app is owned by other agents; no client exists | A written client rule only |

## Mock-provider demonstration

`uv run python -m edu_api.tutor.demo` — no network, no database, synthetic
lesson. The mock stitches lesson text together and does not translate; the
"answers" show the pipeline, not tutoring quality. Abridged output:

```
=== French lesson, question in French, answer in Haitian Creole
student  : Pourquoi on soustrait 5 des deux côtés ?
status   : answered | source=model | grounding=lesson | language=ht
jude     : Dapre leson an (ki ekri an fransè), repons lan chita sou pasaj mwen site anba a yo. …
cites    : block 'balance' of revision c1000000-0000-4000-8000-0000000000f1 [fr]
cites    : block 'exemple-addition' of revision c1000000-0000-4000-8000-0000000000f1 [fr]

=== Why was my answer wrong? (correctness decided by the server)
status   : answered | source=model | grounding=lesson | language=fr
correct? : False
cites    : question 'q-addition' of revision c1000000-0000-4000-8000-0000000000f1 [fr]

=== A question the lesson does not cover (no model call, nothing invented)
student  : Qui a gagné la Coupe du monde de football en 1998 ?
status   : insufficient_context | source=reviewed_template | grounding=none | language=fr

=== An attempt to change Jude's rules (no model call)
status   : declined | source=reviewed_template | grounding=none | language=fr

=== A message suggesting the student is in danger (reviewed message, no model call)
status   : safety_support | source=reviewed_template | grounding=none | language=ht

=== Over the daily allowance (refused before any provider call)
error    : tutor_daily_limit_reached (HTTP 429) — Today's Jude allowance is used up. It resets tomorrow.

=== Usage ledger (everything that was stored)
settled   outcome=answered spent_micro_usd=… tokens=…+… model=mock/jude-deterministic-v1 prompt=jude-tutor.v1
(4 rows; no text)
```
