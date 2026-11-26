# 9. Updated and withdrawn content — policy-neutral states (implemented) and owner decisions (open)

Status: **implemented and tested** for the states and the safe behaviour. **Not decided:** retention and takedown policy.
Nothing here invents the owner's final policy; each place that needs one is marked **OWNER**.

## 1. What the phone can and cannot know

* A phone only learns about the server through a **successful** request. The catalog it last fetched (and when) is the only
  evidence it has about updates and withdrawals.
* **A phone that is offline cannot know that a withdrawal or takedown happened.** The app therefore never says "up to date" or
  "still valid". It shows the **date of its last check**, and its notices say that an offline phone cannot see newer changes.
  There is no immediate offline revocation, and the product must not claim one.
* The current server (`main`) hides a lesson through row-level security (course `visibility`, revision status). The lesson endpoint answers
  one identical `404 lesson_not_found` for unknown, unpublished, withdrawn and taken-down lessons. **The API does not say why**, so a
  routine withdrawal and a rights/safety takedown are **indistinguishable on the phone today**.

## 2. States of a downloaded lesson (`lessonFreshness`, `core/learning/contentAccess.ts`)

| State | Evidence | What the student sees (fr) | Copy and progress |
|---|---|---|---|
| `unverified` | no successful catalog fetch on this phone | "Mise à jour pas encore vérifiée" | kept |
| `current` | last successful catalog lists the **same** revision | "Dernière vérification : jj/mm/aaaa" (never "à jour") | kept |
| `update_available` | last catalog lists a **different** revision | "Nouvelle version disponible" + **Mettre à jour** (explicit) | old copy kept until the new one is verified |
| `not_listed` | last successful catalog does **not** list it | "Plus proposée sur le serveur (vérifié le …)" in the path; in the reader a notice stating the date and that offline the phone cannot see newer changes | kept and readable |
| `withdrawn_confirmed` | the **server itself** answered 404 for this lesson (download, update, or online open), after the last catalog that listed it | "Retirée par le serveur · ta progression est conservée" | kept and readable |

Rules implemented and tested:

1. **A missing catalog entry is never treated as proof that the saved copy is current** (`not_listed`, not `current`). Before: it returned "up to date".
2. A network failure is **not** a withdrawal. Only a real 404 records `server_gone_at`.
3. `server_gone_at` is cleared by the next successful download, and ignored if a **later** catalog lists the lesson again (re-published).
4. Progress, attempts, pending operations and completions are in the account database and are **never touched** by any of these states.
   Pending answers for a withdrawn lesson stay pending; whether the server accepts them is the server's decision, and a refusal
   surfaces through the existing "needs attention" state.
5. Online reading of a withdrawn lesson shows a clear "no longer available" message and offers the saved copy if there is one.

## 3. Updates

* The catalog (refreshed when the student opens Apprendre) carries `revision_id`; a different one means `update_available`.
* Updating is explicit and atomic (download → validate → one transaction). A failed update leaves the old revision.
* **Known consequence (unchanged behaviour):** question ids are per revision, so after an update the new questions start with no
  answers; answers to the previous revision remain in the account database and sync normally.

## 4. Decisions that belong to the owner — **OWNER**

| # | Decision | Current behaviour | Why it needs approval |
|---|---|---|---|
| W-1 | After `not_listed` / `withdrawn_confirmed`, may the student keep reading the saved copy? | Yes (policy-neutral default: keep, with a notice) | Educational and legal; a routine retirement may differ from a rights takedown |
| W-2 | Rights or safety takedown: must the app hide/remove the content at the next successful contact? | **Not distinguishable today.** | Needs an API field (e.g. catalog `availability: withdrawn | taken_down`, or a tombstone list) and a staff takedown route (audit L-B2-3). Then the client can hide `taken_down` content. Until then there is no way to tell the phone to remove content |
| W-3 | Maximum age of the last check before the app asks the student to reconnect | No limit; the date is shown | Product/legal |
| W-4 | Automatic deletion of withdrawn copies | Never automatic | Student data minimisation vs. storage on small phones |
| W-5 | Whether pending answers for a withdrawn lesson should still be accepted by the server | Server decides; client keeps them | Server policy |

## 5. Not built (and why)

* A "remove download" button and a storage screen (roadmap CD-2). The service operation `removeDownloaded` exists and keeps a minimal
  reference so the lesson stays on Home/Review as an online lesson; there is no UI yet.
* Hiding taken-down content: impossible without the W-2 API field.
* Background update checks: the catalog is refreshed on Apprendre only, deliberately, to save mobile data.
