# 6. Test plan

## A. Automated (implemented, synthetic content, mocked provider, no network, no real key)

| Adversarial case | Where | Test |
|---|---|---|
| Invalid or malicious ids (short, long, whitespace, NUL, markup, path traversal, URL syntax, Unicode lookalikes, non-strings) | unit | `test_malicious_or_malformed_video_ids` |
| Untrusted links (http, foreign host, look-alike host, credentials, port, duplicate `v=`, playlist, injected characters, oversize) | unit | `test_untrusted_links_are_refused` |
| URL injection through a stored value | unit | `test_urls_are_built_only_from_validated_ids` |
| Malformed ids or URLs reaching the database | pgTAP | identifier `throws_ok` block (`080`) |
| Unapproved video | pgTAP, HTTP | "a proposed (unreviewed) video is invisible"; `test_unreviewed_video_is_hidden` |
| Self-approval; approval by a non-reviewer; approving a non-presentable video | pgTAP | approval rules |
| Non-embeddable, deleted (`removed`), private, rejected/deleted upload, blocked in Haiti, age-restricted | unit, pgTAP, HTTP | `test_restricted_videos_are_not_presentable`; `hidden_when(...)`; `test_non_presentable_videos_are_hidden` |
| Expired metadata (and > 30-day validity refused) | pgTAP, HTTP | `metadata window`; `test_expired_metadata_hides_until_refreshed` |
| Metadata changes: title (kept, latest shown) vs channel, MFK, age rating, embeddability, duration (re-review) | pgTAP, HTTP | material-change rows; `test_material_metadata_change_requires_a_new_review` |
| Missing `madeForKids` / `embeddable` in the provider answer (never assumed) | unit | `test_incomplete_or_strange_metadata_is_rejected` |
| Videos marked Made for Kids (recorded, presentable, flagged to the client) | unit, pgTAP, HTTP | `test_made_for_kids_is_recorded_not_hidden`; `test_made_for_kids_video_is_flagged_for_the_client` |
| Unsupported or restricted content in the answer (unrequested items, unknown statuses, absurd durations, control/bidi characters, oversized titles) | unit | `test_missing_and_unrequested_items`; `test_text_is_cleaned_and_bounded`; durations |
| Incorrect or missing attribution | DB constraints + HTTP | `title`, `channel_id`, `channel_title` NOT NULL and bounded; card asserts title, channel and channel URL |
| API-key leakage (response, contract, errors, headers, logs, repr, settings dump, exception chains, URL) | unit, HTTP | `test_request_shape_key_only_in_header_and_only_to_google`; `test_provider_failures_never_carry_the_key`; `test_settings_never_print_the_key`; `test_no_learner_facing_search_and_no_key_in_the_contract`; `test_error_responses_do_not_leak_the_key` |
| No provider call without key **and** authorization | unit | `test_no_network_call_unless_key_and_authorization` |
| Redirect to another host is not followed | unit | `redirect-not-followed` |
| Excessive requests to the provider (more than 50 ids, duplicates collapsed) | unit | `test_input_ids_are_validated_and_bounded_before_any_call` |
| Search-query injection and excessive length | unit | `test_staff_search_terms_are_bounded`; `test_search_text_is_sent_as_data_not_syntax` |
| No learner-facing search route | HTTP | `test_no_learner_facing_search_and_no_key_in_the_contract` |
| Cross-account access (content is identical; no reviewer or staff data; learner cannot write) | pgTAP, HTTP | API-role read/write block; `test_every_account_sees_the_same_lesson_content` |
| Disabled feature flag | HTTP | `test_feature_is_off_by_default` |
| No-video lesson | HTTP | `test_lesson_without_videos_is_an_empty_list` |
| Unpublished, unknown or wrong-language lesson | HTTP, pgTAP | `test_unknown_or_unpublished_lesson_is_404`; inactive lesson row |
| Staff disable / withdraw | pgTAP, HTTP | `test_staff_can_disable_and_withdraw` |
| Schema surface unchanged elsewhere | pgTAP `010`, HTTP contract | counts and path list updated deliberately |

Offline playback cannot be expressed on the server beyond `requires_network: true`; it is a device test.

### Results before pushing

On a throwaway PostgreSQL 17 container (removed afterwards; the shared Supabase stack was never contacted): all pgTAP files pass, including `080` (40 assertions) and the updated `010`; the 20 HTTP tests pass with test-signed tokens. Unit: 168 passed (97 new). The authoritative run is the PR's CI on the disposable runner (real Supabase Auth).

## B. Physical-device tests (to run before enablement; not run)

| # | Device | Test | Pass criterion |
|---|---|---|---|
| D1 | Android API 24, 1 GB RAM, 320 dp | Open a lesson with 3 videos, offline then online | Text first; offline card; no WebView created before tap |
| D2 | same | Tap Watch | Player 288 × 200 (≥ 200 × 200), plays, no error 153 |
| D3 | same | Switch app / lock screen during playback | Audio stops; WebView destroyed |
| D4 | same | Open a second video | First player released; one WebView only (check memory) |
| D5 | same, 3G throttled | Tap Watch | Loading state; fallback after 15 s; lesson still usable |
| D6 | iPhone (oldest supported iOS), WKWebView | D2–D4 | Inline playback, no error 153, Referer `https://<bundle id>` |
| D7 | both | Font scale 1.3 and 2.0, fr and ht | No mid-word breaks; player box unchanged |
| D8 | both | Synthetic videos: removed, private, embedding off | Fallback message + "Ouvrir dans YouTube" opens the app/browser |
| D9 | both | Player's YouTube logo / title link | Opens YouTube externally; the lesson stays in the app |
| D10 | both | Metered connection | One-time data notice; data saver hides thumbnails |
| D11 | both | Screen reader (TalkBack, VoiceOver) | Card label read once with title, channel, duration, "YouTube" |
| D12 | both | Network capture | No request to YouTube before the tap; no analytics SDK traffic on video screens |
| D13 | both | Release build signed with the store id | Referer matches the store application id |
