# Letter Desk Phase 8 — Integration, Reliability & Launch Preparation
**Date:** 17 October 2026
**Branch:** `feature/letterdesk-unified-neon` (protected PR #5)
**Production:** `https://author-scout-team-bot.vercel.app/` remains unchanged.
**Staging:** `https://letterdesk-v2-ui-preview.onrender.com/?signin=1`; backend `https://letterdesk-v2-api-preview.onrender.com`; Neon `letterdesk-unified-staging`.

## Improvements implemented

### 1. Persistent login (regression fix)
- On the original preview URL, `?signin=1` incorrectly removed `authorScoutSession` and `authorScoutSessionInfo` during initial boot. That caused the site to appear to log users out on page refresh or when returning to the shared link.
- Boot now treats this as a harmless navigation hint: tries the stored signed session and clears only the query marker after successful sign-in.
- Password-recovery pages remain isolated from normal login restoration.
- Email authentication resets the visible pending/busy state in a `finally` block, even after unexpected failure.
- Pure session policy extracted into `web/src/letterdesk/session-policy.js`, with Node regression tests.
- Letter Desk's first navigation item and default logged-in landing screen are the **six Service Workspaces**; clicking the Letter Desk logo returns to that area. Original Author Scout features remain navigable.

### 2. Lazy, per-service workspaces
- Previously each of five workspaces' feature panels fetched content during initial sign-in even if collapsed, potentially creating a burst of network/database requests.
- Scouting Studio, Import Studio, Flow Studio, Campaign Studio and Reply Studio now defer expensive queries until opened.
- Scouting Studio defaults closed for a lightweight service landing screen.
- Changes retain service-specific keys and state isolation. Effects are not started on non-active service panels.
- CI frontend build and existing source-contract regression checks run on all commits.

### 3. Import undo, independent of message delivery
- New `letterdesk_import_undo.py`: a **dry-run** inspection estimates drafts and records that can be safely removed.
- User must type exact filename and submit a signed, 15-minute confirmation token bound to team, service, batch and safety summary. A second server-side safety check runs within the same PostgreSQL transaction.
- Undo rejects any batch involving queued/sent/replied/changed message data. It preserves already-researched opportunities, contacts linked to another service, suppression records, and import audit trails.
- Untouched batch-owned drafts, conversations, opportunities and leads are deleted only if no references remain; other records are retained. Human-authored edits are protected by comparing draft subject/body against the file's original stored Message01/subject.
- An import-specific provenance marker `_letterdesk_import_batch` on **new** opportunities differentiates records newly created by that batch from pre-existing opportunities. Existing service detail fields remain accessible.
- The original import's rows retain an audit status but branch text is redacted after undo. The completed batch records a per-operation summary, timestamp and approving web account ID. Explicit do-not-contact records persist.
- History UI provides **Review undo**, shows safety blockers, requires typed filename and confirmation; no one-click deletion.
- Distinct `LETTERDESK_IMPORT_UNDO_ENABLED=false` flag means previously authorized imports do not automatically allow undo.
- Neon migration is additive: `undo_summary` and `undo_account_id` on `ld_import_batches`; index on team/service/status. Original data was not modified in rollout.
- Real PostgreSQL `EXPLAIN` parsing passed for the 9 mutation statements used by undo, without executing the changes.

### 4. Performance and coverage
- Automated regression creates **500 synthetic records** for each of six service modes. Parses first messages, nested Yes/No branches and source URLs without network calls or sending.
- Existing 5,000-record parser upper bound and 8 MB file cap remain in place.
- Actual browser upload and Neon write times for a 500-record workbook **have not yet been measured**: the parser benchmark is not equivalent to an upload-in-under-five-seconds guarantee.
- A separate test confirms staging forbids importing/undoing when flags are off.
- Production email sending, Gmail reading, flow publishing and reply ingestion flags remain false.

## What is verifiably still pending

**Phase 8 is an integration-hardening implementation, not a proven production release.** These acceptance tasks require authorized test accounts, representative files, or external approvals not present in the automated checks:

1. **Real sign-in acceptance:** Use a staging test user's email/password, sign in via `?signin=1`, refresh, navigate away and return; verify the account stays signed in until manual Sign out. Also verify password reset and wrong-password feedback. The corrected code and automated tests cannot substitute for an actual user's browser session.
2. **Real upload and undo:** Enable only `LETTERDESK_IMPORT_WRITE_ENABLED=true` on staging for a controlled test file, import one synthetic/no-contact row, inspect Neon records and optional draft, then enable `LETTERDESK_IMPORT_UNDO_ENABLED=true` solely to test dry-run and confirmed undo. Verify no suppression is deleted and shared contacts remain.
3. **500-record workload benchmark:** Measure complete frontend upload → HTTP → parser → Neon transaction → UI refresh, with representative XLSX and CSV; optimize connection pool, indexes and worker load if required. The user's requested sub-five-second experience is a target, **not a validated claim**.
4. **Flow/editor persisted writes:** Enable staged `LETTERDESK_FLOW_WRITE_ENABLED=true` only after test account authentication. Save a flow, reload revision, simulate branches and verify team isolation.
5. **Gmail:** Rotate previously exposed OAuth client secret; configure Google's consent screen and exact server callback; connect only one owned test Gmail address and verify aliases. `gmail.settings.basic` and `gmail.readonly` are restricted scopes that may require Google app verification/security assessment. Real replies and test sends remain disabled.
6. **Multi-team isolation:** Test with two genuinely independent staging accounts/teams to confirm one cannot access the other's prospects, imports, templates, replies, Gmail connection, or senders.
7. **Privacy/release compliance:** Publish an accurate accessible privacy policy, opt-out/deletion workflow, appropriate contact-basis disclosures and Google API Limited Use terms. Legal contact/privacy details must be supplied by the operator.
8. **Production release:** Review environment variables without copying or logging secrets, back up and migrate the intended Neon production database, run the same tests, then cut over Vercel only after the signed acceptance checklist. Do not enable mass outreach on launch.

## Safe environment defaults

```env
LETTERDESK_STAGING_ISOLATED=true
LETTERDESK_V2_ENABLED=true
LETTERDESK_IMPORT_WRITE_ENABLED=false
LETTERDESK_IMPORT_UNDO_ENABLED=false
LETTERDESK_FLOW_WRITE_ENABLED=false
LETTERDESK_GMAIL_OAUTH_ENABLED=false
LETTERDESK_GMAIL_READ_OAUTH_ENABLED=false
LETTERDESK_GMAIL_READ_ENABLED=false
LETTERDESK_REPLY_WRITE_ENABLED=false
LETTERDESK_GMAIL_SEND_ENABLED=false
LETTERDESK_REPLY_SAFETY_READY=false
LETTERDESK_DELIVERY_OPERATOR_APPROVED=false
```

### Release verdict
- **Code and automated regression:** verify via latest GitHub Actions on the protected branch.
- **Staging deployment:** verify via latest Render frontend and backend service deploys.
- **Signed-in workflow, approved test send, and production readiness:** **not yet certified**. Do not claim all end-to-end behaviors work merely because CI passed.
