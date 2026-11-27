# Social feature parity and safety gap

**Status:** gap report. No social feature is built, enabled or exposed. Prototype behaviour is as read in source (not run, no posts or messages read).

## The product difference, stated plainly

**Social-00 (PR #1) designs a supervised, text-only, pre-moderated class noticeboard. The live prototype is an open social network.** They are different products. Shipping the noticeboard under the name "community" would remove, for 61 students, the feed, follows, direct messages, group chats and media they have today. That may be the right decision for safety, but it must be a **decision** (OD-4), not a substitution.

## Parity table

| Capability | Live prototype (in source) | Social-00 design (#1) | Gap | Safety assessment |
|---|---|---|---|---|
| Feed of posts | `/feed`: text + images, real-time | Class noticeboard, text only, every post approved by a second person before it is visible | **Different product** | Open feed among minors with images and no pre-moderation is the higher-risk design |
| Comments, likes, shares | Yes (`post_comments`, `post_likes`, `post_shares`) | Comments and reactions, pre-moderated; no shares | Partial | Acceptable when moderated |
| Follows and follow requests | Yes (pending / accepted / rejected) | **Excluded** | Missing | Follow graphs enable contact across grades and ages |
| Public profiles and user search | `/profile/:userId`, `/user-search` | **Excluded** | Missing | Search exposes minors to any signed-in user |
| Direct messages | Yes: anyone can message anyone; media; reactions; typing; read receipts | **Excluded** (only an unapproved future migration) | Missing | **Highest risk.** Private one-to-one contact between minors (and any adult account) with no blocking and no message reporting |
| Group chats | Yes (`group_chats`, `group_members`, avatars) | Closed class groups joined by code + teacher/staff verification; grade bands 7AF–9AF and NS1–NS4 never mixed | Different model | The designed model is safer |
| Media | Images in posts and messages; **public-read buckets** | Text only | Missing | Image moderation needs tooling or staff time; public buckets are a privacy problem |
| Real-time presence | Supabase Realtime, presence | None | Missing | Low value, real cost |
| Reporting | Posts and users → founder review | Reports with auto-hide on severe categories | Improved | — |
| **Blocking** | **None** | Block (noticeable in a small class: stated limit) | Prototype lacks it | Required before any launch |
| Message reporting | **None** | n/a (no DMs) | — | Required if DMs are kept |
| Pre-moderation | None | All content | Improved | Needs daily staffed rota |
| Staff controls | Founder UUIDs hardcoded; `admin-delete-post` | Queue (claim, decide, escalate), sanctions (warn, mute, suspend), appeals, evidence holds, append-only audit, three default-off switches | Improved | Needs named people |
| Age rules | None (grade gating is client-only) | Grade-band separation; guardianship deferred | Open | 7AF includes under-13s; grade is not age |
| In-app social notifications | Yes | Via the notification outbox (#6) | Dependent | — |
| Code | Live | **Design only: 21 documents; SQL parsed, never executed; 0 lines of product code** | Whole build | — |

## What students use today

**Unknown.** Source shows what is possible, not what is used. Before deciding, the owner can obtain **aggregate, non-personal counts** from the legacy database (posts per week, number of students who posted, number of DM conversations in the last 30 days, group count, report count). No message content needs to be read. This is the single most useful input for OD-4.

## Options for the owner (OD-4)

| Option | What students get in v1 | Engineering | Safety and staffing | Parity |
|---|---|---|---|---|
| **1. Noticeboard only** (Social-00 as designed) | Class board, comments, reactions | Social-01/02 builds | Lowest risk; needs a safety lead and two moderators | **Reduction**, must be communicated to students and families |
| **2. Noticeboard + moderated class group chat** *(suggested)* | Board plus chat inside verified class groups; no one-to-one DMs; text only | Option 1 + group chat with report, block, rate limits, retention, staff read access under audit | Moderate; chat is post-moderated with fast takedown, so staffing and reporting must be real | Closer; DMs and follows still removed |
| **3. Full parity** (feed, follows, DMs, media) | What they have today | Largest; media moderation; abuse tooling | Highest risk; needs legal sign-off for private messaging among minors, guardian consent model, and probably automated scanning (Social-00 excludes AI moderation: D-06) | Full |
| **4. Keep social on the web for now** | Mobile has no community; link to the web app | None | Leaves today's unmoderated DMs running | Parity by coexistence |

Under options 1–3 the open issues in the **live** prototype (no blocking, no message reporting, public media buckets, permissive policies) remain until the web app is changed or retired: a risk that exists today regardless of the mobile decision.

## Minimum safety bar before any student-visible social surface

1. Decisions D-01 (model), D-02 (ages and consent), D-03 (named safety lead and two moderators), D-06 (AI moderation) from Social-00; legal questions L-1…L-6 answered by counsel.
2. Report and block on every surface; severe-report auto-hide.
3. Staffed moderation queue with response targets; sanctions and appeals.
4. Append-only audit of staff actions; evidence holds; retention and erasure rules.
5. Server-side rate limits; no public media buckets; no cross-band contact.
6. Privacy notice and community rules in French and Creole; guardian information for under-13s.
7. Platform prerequisites P-1…P-9 (hosted staging, gateway rate limiting, staff second factor, account deletion, backups).
8. Feature flag default off; staff-only pilot first.

## Migration of existing social data

Default: **do not migrate** posts or messages. They are private communications of minors, collected under the prototype's terms, with no review. If the owner wants continuity (for example, class groups), it needs an explicit legal basis and consent (OD-5), and only structural data (group membership) should be considered.
