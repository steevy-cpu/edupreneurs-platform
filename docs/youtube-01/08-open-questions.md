# 8. Legal and provider uncertainties

None of these blocks the backend foundation. All of them must be answered before learners see a video.

| ID | Question | Why it matters | Who |
|---|---|---|---|
| OQ-1 | Is Mon-Edupreneur a **child-directed** API client (learners about 11–19, including under-13s; Haiti; possibly EU or US users)? Is a mixed-audience treatment possible? | Decides the Google Play / iOS designation, guardian consent, player features (DP III.J) | Counsel |
| OQ-2 | May thumbnails (`i.ytimg.com`) be cached by the app, and for how long? No explicit rule was found | Data use on weak networks vs. API data rules | YouTube / counsel. Default: platform HTTP cache only, never offline |
| OQ-3 | Does any reward tied to a lesson that *contains* a video count as an "incentive for engaging with YouTube Applications" (DP III.F.3)? | Gold and streak design | Counsel. Default: rewards never depend on a video |
| OQ-4 | Exact wording and scope of the privacy disclosure and consent for minors (DP III.A.2, D.2.b) | Required before enablement | Counsel |
| OQ-5 | **YouTube Player for Education**: eligibility, cost and availability in Haiti for an independent education app | Ad-free, recommendation-free player designed for schools | YouTube partnerships |
| OQ-6 | Referer when the Android and iOS application ids differ, and whether `react-native-webview` reliably sends the Referer on the embed's own request | Error 153 risk | Device test D2/D6/D13; YouTube if needed |
| OQ-7 | Current `search.list` quota cost (read today as "100 per day, 1 quota each", which differs from the long-standing 100 units per call) | Sizing of the staff search tool | Re-verify on the live page; ask YouTube if unclear |
| OQ-8 | Is a teacher-curated list of videos a "search result" under DP III.C.5? | Presentation of curated lists | Counsel (believed not) |
| OQ-9 | Ads in the embedded player shown to minors (non-personalized after designation) | Families' expectations; cannot be blocked | Owner decision; disclose |
| OQ-10 | Rights in the 242 legacy curated videos: any third-party or region restrictions beyond what the API reports | Import approval | Teachers / owner |

The policy texts were read through a fetch tool that summarises pages and quotes short phrases; any requirement relied on legally should be re-read on the live page.
