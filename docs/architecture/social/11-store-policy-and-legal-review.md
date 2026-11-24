# 11. App Store and Google Play review, and where legal expertise is needed

**Read this first.** This is an engineer's reading of published store policies,
checked on 2026-11-24 by web search of the official pages. It is **not legal
advice** and it is not a guarantee of approval. Store policies change several
times a year; the exact current wording must be re-read on the linked pages
before any submission. Where the search did not confirm a detail, this page
says so instead of guessing.

## Summary

- Both stores require the same four things of any app with user-generated
  content: a way to **filter** objectionable material, a way to **report** it
  with timely action, a way to **block** abusive users, and **published
  contact** information. The design includes all four from the first release.
- Both stores treat anonymous or random chat as a serious problem, especially
  near children. The design has no anonymous or random contact of any kind.
- Google Play has a specific **Child Safety Standards** policy for apps in the
  *Social* (and *Dating*) categories. Whether it applies depends on the
  category chosen in Play Console; the design meets its substance either way.
- The stores decide **age rating and audience rules** from the answers the
  developer gives. Adding a community changes those answers. This is where a
  wrong answer causes a rejection or, worse, a later removal.
- The stores are the easier half. **National law** on children's data, consent
  and reporting of abuse is the harder half and needs counsel.

## Apple App Store

| Requirement (source) | What it asks | How the design responds | Still to do |
|---|---|---|---|
| Guideline 1.2 User-Generated Content | A method for filtering objectionable material from being posted | Local screen + **human approval before anything is visible** (stronger than the guideline asks) | Describe it in the review notes |
| 1.2 | A mechanism to report offensive content and timely responses | Report on every post, comment and name; deadlines of 4 h / 24 h; auto-hide | Publish the response-time commitment |
| 1.2 | The ability to block abusive users | Mutual block | — |
| 1.2 | Published contact information so users can easily reach you | `report_contact` in the rules endpoint and on the store listing | Create the address and a person who reads it |
| 1.2 (2026 revisions) | Random or anonymous chat is covered by 1.2 and such apps may be removed; developers are responsible for removing violating content; nonconsensual intimate imagery (including AI-generated) must be proactively prevented and removed | No anonymous or random contact; verified accounts in closed groups; no images in the initial scope | Re-read the October 2026 revision in full before submission — the search confirmed its existence and theme, not its complete text |
| 1.3 Kids Category | Apps *in the Kids Category* have strict limits (no third-party analytics/ads, parental gates for links out, etc.) | **Recommendation: do not place the app in the Kids Category.** It is an education app for teenagers and young adults; the category is designed for younger children and a community feature fits it poorly | Decide and record the category (legal/policy input: L-7) |
| 5.1.4 Kids / data from minors | Extra care with children's data; compliance with children's privacy laws wherever the app is offered | Age band not birth date; no contact data in profiles; no third-party sharing; short retention | Privacy policy and App Privacy details must describe community data accurately |
| Age rating (App Store Connect questionnaire; ratings 4+, 9+, 13+, 16+, 18+ since 2025) | The developer declares capabilities such as user-generated content and messaging; the rating follows, per region | The app will have user-generated content with pre-moderation and no private messaging | Answer the questionnaire again when the community ships. **The search did not confirm the exact wording of the UGC questions or which rating they produce** — check in App Store Connect, and expect the rating to rise from today's |
| Account deletion (5.1.1(v)) | Apps that allow account creation must let users start account deletion in the app | `erase_user` is the social half | Prerequisite P-6: the learning half and an in-app entry point |
| Declared Age Range API / regional age-assurance rules | In some regions (several US states, others) age categories must be requested and respected | Not required by the design; our own age band comes from the school/guardian | Relevant only for the storefronts chosen. Decide where the app is distributed (L-1) |
| Sign-in for review | Reviewers need a working demo account with the community enabled | Synthetic reviewer account in a synthetic community | Prepare with staging (P-1) |

## Google Play

| Requirement (source) | What it asks | How the design responds | Still to do |
|---|---|---|---|
| User-Generated Content policy | Clear terms of use; an in-app system for reporting objectionable content and users; a way to block users; moderation proportionate to the app; safeguards against threats, harassment and bullying, **particularly toward minors** | Rules that must be accepted; report; block; pre-moderation; sanctions | Publish terms and rules at a public URL |
| Child Safety Standards policy (apps declaring the *Social* or *Dating* category) | Published standards against child sexual abuse and exploitation (CSAE) at a globally accessible URL, linked in Play Console; an in-app way to report concerns; a **designated point of contact** who can speak to the app's CSAM-prevention practices; self-certification that the app acts on reports and removes CSAM on actual knowledge; compliance with applicable child-safety laws | The rules page will state the standards; in-app report with a `child_safety` category; the safety lead is the point of contact; escalation runbook | Even if the app stays in the *Education* category (recommended), publish the standards and name the contact — it costs little and the policy's scope may widen. **The search did not return Google's own text on the in-app mechanism**; read the help article before submitting |
| Families policy — target audience and content | If the declared target audience includes children, the Families requirements apply (content, ads SDKs, data practices); mixed-audience apps need a neutral age screen for certain purposes; anonymous-chat apps may not target children | No ads. No anonymous chat. Age band comes from enrolment | **Decide the declared target age groups** in Play Console with advice (L-7). Declaring an audience that includes under-13s triggers the full Families requirements; declaring 13+ while 12-year-old 7AF learners use the app would be inaccurate |
| Data safety form | Declare every type of data collected and shared, including user-generated content, and whether it can be deleted | Community content, display name, moderation records; nothing shared with third parties | Update the form when the community ships |
| Account deletion requirement | In-app and web path to request deletion of the account and associated data | Same as Apple | P-6 |
| Pending policy updates | Google's "upcoming policies" page mentions updates to the Families policy (regional appropriateness) and to the UGC policy (incidental sexual content, moderation requirements) | — | The search could not date these. Re-check before submission |

## Checklist to run before the pilot build is submitted (Social-03)

- [ ] Current text of Apple guideline 1.2 and Google's UGC, Families and Child Safety Standards pages re-read by a named person; date recorded.
- [ ] Store category, declared audience and age-rating answers decided with advice and written down.
- [ ] Public web page with: community rules, child-safety standards, how to report, contact address, response-time commitment — in French and Haitian Creole.
- [ ] Privacy policy and both stores' privacy/data-safety declarations describe community data, retention and deletion.
- [ ] In-app: report and block reachable in two taps from any content; rules accepted before first post.
- [ ] Account deletion works end to end for both learning and social data.
- [ ] Reviewer demo account in a synthetic community, with notes explaining pre-moderation ("your test post will not appear until approved; here is an approved example").
- [ ] Child-safety point of contact named in Play Console; that person has read the runbook.

## Where legal or policy expertise is needed

None of these can be answered by engineering. They are ordered by how much they block.

| Id | Question | Why it matters to the design | Blocks |
|---|---|---|---|
| **L-1** | **Which laws apply?** Depends on where the company is legally established, where data is hosted, and where users are (Haiti; possibly the diaspora in the United States, Canada, France). Candidates to assess: Haitian law on privacy, minors and electronic communications; US COPPA if the operator or audience brings the app within it; GDPR/UK rules if offered there | Everything below | D-02, Social-03 |
| **L-2** | **Consent.** At what age can a learner consent alone? Can a **school** consent on behalf of parents, and under what agreement? What record of consent is sufficient? Is under-13 participation permissible at all, and with what verification of the parent? | `consent_method`, the pilot model, whether 7AF–8AF learners can take part | D-02, Social-03 |
| **L-3** | **Duties when abuse or exploitation is suspected.** Is there a legal obligation to report, to which authority, within what time? What must be preserved, for how long, and what must *not* be done with the material? Which Haitian bodies are competent, and does establishment abroad add duties there? | Escalation level 3, evidence holds, the runbook | Social-03 |
| **L-4** | **Retention.** Minimum and maximum periods for content, reports, moderation records and audit logs about minors | The `retain_*` settings (currently 30 / 90 / 365 / 730 days) | Social-03 |
| **L-5** | **Moderators and teachers.** Lawful background checks for people with access to minors' communications; employment or contractor terms; confidentiality | Staffing plan | Social-03 |
| **L-6** | **Documents.** Terms of use, community rules, privacy notice, school agreement, family information letter — in French and Haitian Creole, readable by a 13-year-old | P-8 | Social-03 |
| L-7 | **Store positioning.** Category, declared target audience and age rating that are both accurate and workable; whether to restrict distribution to specific countries | Store submissions | Social-03 |
| L-8 | **Rights of learners and parents** to access, correct and erase data; how identity is verified for such requests; a child's privacy toward their own parent (D-05) | Guardian tools, erasure | Social-04 |
| L-9 | **Hosting and transfer.** Whether storing Haitian minors' data in a foreign cloud region needs notice, consent or a particular contract | Choice of Supabase region | P-1 |
| L-10 | **Any future processor of learner text** (an AI moderation vendor, Jude, analytics). Contract terms, disclosure, lawfulness for minors' data | D-06 | Before any such feature |
| L-11 | **Ministry or school-network rules** on digital communication between teachers and pupils | Teacher role, D-04 | Social-03 |
| L-12 | **Liability and insurance** for operating a service used by minors | Company risk | Social-03 |

A note on Haitian institutions: public information suggests that
child-protection matters in Haiti involve the social-welfare institute (IBESR)
and the police brigade for the protection of minors (BPM). **This is recalled
from general knowledge and was not verified for this document**; who is
actually competent to receive a report from an online service, and how, is
question L-3 for counsel.

## Sources consulted (2026-11-24)

- Apple — App Review Guidelines: <https://developer.apple.com/app-store/review/guidelines/>
- Apple — news post on the October 2026 guideline update (nonconsensual intimate imagery): <https://developer.apple.com/news?id=vvzx6cul>
- Apple — Age ratings reference: <https://developer.apple.com/help/app-store-connect/reference/age-ratings>
- Apple — Age rating updates (2025): <https://developer.apple.com/news/upcoming-requirements?id=07242025a>
- Apple — Designing for kids and age-appropriate experiences: <https://developer.apple.com/kids/>
- Apple — Age assurance frameworks Q&A: <https://developer.apple.com/support/age-assurance>
- Google Play — Child Safety Standards policy: <https://support.google.com/googleplay/android-developer/answer/14747720>
- Google Play — Families policy: <https://support.google.com/googleplay/android-developer/answer/9893335>
- Google Play — User-Generated Content policy: <https://support.google.com/googleplay/android-developer/answer/12923286> (link as returned by search; confirm it is the current article)
- Google Play — Target audience and app content settings: <https://support.google.com/googleplay/android-developer/answer/9867159>
- Google Play — Upcoming policies: <https://support.google.com/googleplay/android-developer/answer/14554743>

Limits of this review: the pages were reached through search summaries, not
read in full; two secondary summaries disagreed about the date of Apple's
latest revision; Google's exact wording on in-app child-safety reporting was not retrieved.
