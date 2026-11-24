# 5. Role and permission matrix

There are two kinds of "role" in this design. Keeping them apart avoids confusion:

- **People roles** — what a person is allowed to do in the product.
- **Database roles** — what a connection from the API is physically able to do.

A request succeeds only if **both** allow it.

## People roles

| Role | Who | How they get it | Who can remove it |
|---|---|---|---|
| **Learner** | A student, 7AF–NS4 | Enrolled by staff or (later) a school official; consent recorded; then verified into a community | Safety lead, admin; a linked adult can pause |
| **Teacher** | An adult leading a class group | Enrolled as `teacher` by staff after the school confirms them; assigned to their group by staff | Safety lead, admin |
| **Authorised adult** | Parent/guardian or school official linked to specific learners | Link created and verified by staff (never by the adult alone) | Safety lead, admin |
| **Moderator** | Trained staff reviewing content | Row in `social.staff_roles`, inserted by the database owner out of band | Database owner |
| **Safety lead** | The accountable person for child safety | Same | Database owner |
| **Social admin** | Staff managing enrolments and communities | Same | Database owner |

One person can hold several roles. Two rules cut across all of them:
**nobody acts on themselves** (cannot approve own content, own membership, own
adult link, lift own sanction) and **nobody grants themselves a role**.

### What each person can do

✔ allowed · ✖ never · ◐ limited as noted

| Action | Learner | Teacher (own group) | Authorised adult | Moderator | Safety lead | Social admin |
|---|---|---|---|---|---|---|
| Read published content of own communities | ✔ | ✔ | ✖ ¹ | ✔ all | ✔ all | ✖ |
| Read unpublished / removed content | own only | own only | ✖ | ✔ | ✔ | ✖ |
| Submit posts, comments | ✔ ² | ✔ ² | ✖ | ✖ ³ | ✖ ³ | ✖ |
| Post an announcement | ✖ | ✔ ² | ✖ | ✖ | ✖ | ✖ |
| React | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ |
| Delete own content | ✔ | ✔ | ✖ | — | — | — |
| Report content or a display name | ✔ | ✔ | ✖ | — | — | — |
| Block a learner | ✔ | ✔ | ✖ | — | — | — |
| Block a teacher or staff member | ✖ (report instead) | ✖ | ✖ | — | — | — |
| See the member list of a group | ✖ | ✔ | ✖ | ✔ | ✔ | ✔ |
| Approve / decline a join request | ✖ | ✔ not own | ✖ | ✔ | ✔ | ✔ |
| Approve / reject new content | ✖ | ✖ ⁴ | ✖ | ✔ not own | ✔ not own | ✖ |
| Remove published content, dismiss reports | ✖ | ✖ ⁴ | ✖ | ✔ | ✔ | ✖ |
| See who filed a report | ✖ | ✖ | ✖ | ✖ | ✔ audited | ✖ |
| Warn, mute, suspend ≤ 7 days (learners) | ✖ | ✖ | ✖ | ✔ | ✔ | ✖ |
| Suspend > 7 days, ban, sanction a teacher | ✖ | ✖ | ✖ | ✖ | ✔ | ✖ |
| Lift a ban | ✖ | ✖ | ✖ | ✖ | ✔ | ✖ |
| Escalate to safety lead | ✖ | ✖ | ✖ | ✔ | ✔ | ✖ |
| Escalate to family/school or an authority | ✖ | ✖ | ✖ | ✖ | ✔ | ✖ |
| Place / release an evidence hold | ✖ | ✖ | ✖ | place (by escalating) | ✔ both | ✖ |
| Enrol people, record consent | ✖ | ✖ | ✖ | ✖ | ✔ | ✔ |
| Create communities, invites; assign members | ✖ | ✖ | ✖ | ✖ | ✔ | ✔ |
| Open / freeze a community | ✖ | ✖ | ✖ | ✖ | ✔ | ✔ |
| Global kill switch and limits | ✖ | ✖ | ✖ | ✖ | ✔ | ✖ |
| Change a learner's safety settings | own, only stricter if locked | ✖ | ✔ linked learners (Social-04) | ✖ | ✔ | ✖ |
| Withdraw consent / pause a learner | ✖ | ✖ | ✔ linked learners (Social-04) | ✖ | ✔ | ✔ |
| Erase a person's social data | ✖ | ✖ | request it | ✖ | ✔ | ✔ |
| Read the audit trail | ✖ | ✖ | ✖ | ✖ | ✔ | ✖ |
| Read anyone's lessons, scores or progress | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ |

¹ An adult manages settings and sees status; they do not read the community.
Whether a guardian should be able to see their own child's posts is decision D-05.
² Subject to review like everyone else. A teacher's post is approved by a moderator, not by the teacher.
³ Staff who also want to take part must hold a separate teacher/learner enrolment; their content is then reviewed by someone else.
⁴ Delegating first-line approval to a group's teacher is a later, gated option (Social-04, decision D-04).

The last row is the boundary requirement: no social role, human or database,
has any path to private academic data.

### How the caller's effective permission is computed

```
may write =  enrolment is active
         AND no suspension/ban (global or for this community)
         AND active, verified member of this community
         AND global switch open  AND community open
         AND current rules accepted
         AND no mute (global or for this community)
         AND the capability is on in safety settings
         AND (the community lets members post  OR  caller is its teacher)
```

Implemented once, in `social.write_denial()`, and returned as the specific
error code so the app can explain it. Every factor is read from the database at
request time; none is taken from the token or the request.

## Database roles

| | `edu_api` (learning, existing) | `edu_social` | `edu_social_mod` | `edu_social_worker` | `anon`, `authenticated`, `service_role`, PUBLIC |
|---|---|---|---|---|---|
| Used by | `/v1/me`, catalog, lessons, sync | `/v1/social/*` member routes | `/v1/social/moderation/*`, `/admin/*` | retention job | Supabase Data API |
| Can log in | no (via `edu_api_login`) | no (via `edu_social_login`) | no (via `edu_social_mod_login`) | no (via `edu_social_worker_login`) | n/a |
| BYPASSRLS / admin attributes | none | none | none | none | n/a |
| Schema `app` | as today | **nothing** | **nothing** | **nothing** | nothing |
| Schema `social` | **nothing** | USAGE | USAGE | USAGE | nothing |
| `INSERT` / `UPDATE` / `DELETE` on any `social` table | — | **none** | **none** | **none** | — |

### Table privileges in `social`

`S` = SELECT on all columns · `S(cols)` = SELECT on listed columns only ·
row filter = the row-level-security policy · `—` = no privilege.

| Table | `edu_social` | Row filter | `edu_social_mod` | Row filter |
|---|---|---|---|---|
| `config` | S(`submissions_open, guidelines_version`) | all | S | staff |
| `visibility_clock` | — | | — | |
| `staff_roles` | — | | S | own rows; all for safety lead / admin |
| `profiles` | S(`user_id, account_kind, display_name, avatar_key`) | own; shares a community and no block | S | staff |
| `enrollments` | S(6 columns) | own | S(`user_id, age_band, consent_status, consent_method, status, created_at`) | staff |
| `adult_links` | — | | S | safety lead / admin |
| `safety_settings` | S | own | S | staff |
| `communities` | S(10 columns) | open/frozen and: member, or own request, or listed + same band | S | staff |
| `community_invites` | — | | S(no digest) | safety lead / admin |
| `memberships` | S(5 columns) | own | S | staff |
| `posts` | S(16 columns; no digests, no screening) | own; or published + readable community + no block | S | moderator / safety lead |
| `comments` | S(16 columns) | as posts, and parent post published and visible | S | moderator / safety lead |
| `reactions` | S(`user_id, post_id, comment_id, kind`) | own | — | |
| `blocks` | S | own (as blocker) | — | |
| `reports` | S(8 columns; no snapshot) | own (as reporter) | S(14 columns; **no `reporter_id`**) | moderator / safety lead |
| `moderation_items` | — | | S | moderator / safety lead |
| `moderation_actions` | — | | S | moderator / safety lead |
| `sanctions` | S(8 columns) | own | S | moderator / safety lead |
| `escalations` | — | | S | safety lead; or the opener |
| `evidence_holds` | — | | S | safety lead |
| `notification_events` | S | own | — | |
| `audit_events` | — | | S | safety lead |
| `rate_counters` | — | | — | |

"staff" = the verified actor of the transaction holds an active `moderator`,
`safety_lead` or `social_admin` role. The database role alone shows nothing:
every moderation policy also checks the actor.

### Function privileges

| Function group | `edu_social` | `edu_social_mod` | `edu_social_worker` |
|---|---|---|---|
| `current_actor_id` | ✔ | ✔ | — |
| Read helpers (`actor_access`, `can_read_community`, `blocked_with`, `shares_community_with`, `actor_grade_band`, `write_denial`) | ✔ | — | — |
| Member writes (`submit_post`, `submit_comment`, `set_reaction`, `file_report`, `set_block`, `join_with_invite`, `leave_community`, `delete_own_content`, `update_profile`, `accept_guidelines`, `update_own_settings`, `mark_notifications_read`) | ✔ | — | — |
| `visibility_changes`, `my_private_profile` | ✔ | — | — |
| `decide_join_request`, `community_members` | ✔ (checks teacher-of-group inside) | ✔ (checks staff inside) | — |
| `actor_has_staff_role` | — | ✔ | — |
| `mod_claim_next`, `mod_decide`, `mod_escalate`, `mod_impose_sanction`, `mod_lift_sanction`, `erase_user` | — | ✔ | — |
| `run_retention` | — | — | ✔ |
| Internal helpers and trigger functions | — | — | — |
| Everything, for PUBLIC / `anon` / `authenticated` / `service_role` / `edu_api` | — | — | — |

## Integration with identity

| Question | Answer |
|---|---|
| Who is calling? | `sub` of the verified access token → `edu.actor_id` for the transaction. Same mechanism as the learning API; nothing new to trust |
| Does the person exist? | `social.profiles.user_id` → `auth.users(id)`, `ON DELETE RESTRICT`: an Auth user with social data cannot be deleted by accident |
| May they take part? | `social.enrollments` — created by staff, never on first contact |
| How old are they? | `enrollments.age_band`, declared by the school or guardian at enrolment. Not read from Auth metadata, not a birth date |
| Which grade? | `profiles.grade_band`, declared at enrolment. **Not** read from `app.learner_profiles` |
| What is their name? | `profiles.display_name`, chosen for the community and approved by a moderator. **Not** `app.learner_profiles.display_name` |
| Are they staff? | `social.staff_roles`. **Not** `app.staff_roles`: a lesson editor is not a moderator |
| Are they signed in strongly enough? | Staff routes require the `aal2` claim |
| Sign-up | Stays disabled (`enable_signup = false`). Accounts are provisioned; that is what makes a ban meaningful |

## What a compromise of each role could and could not do

| If an attacker could run arbitrary SQL as… | They could | They could not |
|---|---|---|
| `edu_social_login` | Impersonate any learner **inside the social functions** (by setting `edu.actor_id`): submit content *for review*, react, report, block, read what that learner may read | Publish anything (needs an approval by someone else, through a role they do not have); read unpublished content of others' reports, staff tables or audit; read or write any learning data; write any table directly |
| `edu_social_mod_login` | The same impersonation, of a moderator: read content under review, approve or remove, sanction — every action recorded append-only | Read learning data; alter or delete the record of what they did; create a staff role; touch `auth.users` |
| `edu_social_worker_login` | Run the retention job early | Read or write anything |
| `edu_api_login` (learning) | What `docs/SECURITY.md` already describes | Read or write anything in `social` |

The impersonation risk is the same residual risk documented for the learning
API ("`edu.actor_id` is an ordinary setting"). It is contained by static,
parameterised SQL and by the fact that the dangerous step — making something
visible to children — always needs a second role.
