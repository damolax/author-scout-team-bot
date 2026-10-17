# Letter Desk 2.0 — Phase 4 advanced imports (17 October 2026)

**Status: implemented in protected development branch; CI passed; read-only import previews on staging.**

- Main site remains `https://author-scout-team-bot.vercel.app/` (not modified).
- Code: `feature/letterdesk-unified-neon`, draft PR #5.
- Preview UI: `https://letterdesk-v2-ui-preview.onrender.com/`.
- Preview API: `https://letterdesk-v2-api-preview.onrender.com/`.
- Database: Neon `letterdesk-unified-staging`, not production branch.

## Scope implemented

- Six import profiles and per-workspace dashboards (author, automation, website-design, digital-planner, shopify, google-maps).
- `.csv`, `.xlsx`, `.xlsm`, maximum 8 MB and 5,000 nonempty rows.
- Downloadable service-specific CSV header templates; accepts common legacy author workbook headings.
- First Message and Subject optional. `Message 01`, `Message0101Yes`, `Message0101No`, `Message0201Yes`, etc. recognized as passive branch templates.
- Preview shows row statuses and summary: created, linked, suppressed, invalid, historical skip and potential unsent drafts; first 25 sample rows shown.
- Checks a prospect's name, email/website or Maps reference, recognized URL formats and email syntax; detects duplicates within the workbook and same-team database; respects team-wide suppressions.
- Old sent/replied rows do not become new outgoing campaigns; new first messages remain `needs_review`, and no message is ever auto-sent by import.
- Preview is **read-only**; confirm requires separate user action and a 20-minute HMAC confirmation token bound to service, team, filename, row count and exact file SHA-256.
- Confirm database transaction uses batched `jsonb_to_recordset` operations to insert leads, opportunities, optional unsent drafts and import row records, keeping original research and messages intact.
- File hashes prevent repeated completion of the exact same file for one team/service.
- New `ld_import_rows` stores row status, optional branch variations, references and reason.
- Import history API and UI.
- Commit endpoint defaults **OFF** via `LETTERDESK_IMPORT_WRITE_ENABLED=false`.

## Tests and limitations

- GitHub CI: six service parser formats/mappings, optional messages, nested branches, opt-outs, old statuses, 5,001-row rejection, authenticated API, cross-team isolation, HMAC, preview read-only/confirmation lock.
- Staging PostgreSQL `EXPLAIN` syntax verification passed for the core batched INSERT statements; no actual import rows were written by this smoke check.
- The staging DB currently has 262 legacy leads and 52 nondeleted migrated messages (the original messages table has 146 total including tombstones). No extra prospects/emails were sent or created by Phase 4 setup.
- **Not yet verified:** a complete logged-in user upload session and a real database commit by a user; stage importer writes remain disabled until acceptance. The confirmed login issue from the previous phase still needs user validation.
- No post-import destructive deletion/rollback endpoint is enabled yet; batches and rows are auditable and reversible work remains to be designed safely.
- Manual override for completely unfamiliar input headings is not yet in the UI; download the recognized header template or rename headers before upload.
- Parse and SQL execution are batched but a strict "<5 seconds for 500" performance guarantee is not established from real workload timing.
- Other planned services (campaign sending, visual branching editor, live multi-service scouting) have independent feature gates.

## Next acceptance milestones

1. User signs in to staging preview and opens **Service Workspaces → Import prospects and message paths**.
2. Select a service, download CSV header template, choose a small representative workbook, preview and confirm that data is recognized.
3. Validate account-specific access, old sent flags, duplicates and opt-outs in staging.
4. Enable `LETTERDESK_IMPORT_WRITE_ENABLED=true` **only on isolated staging** after those checks and run a user-approved one-row import; verify resulting `needs_review` messages and no Gmail send.
5. Benchmark a 500-row upload and import and implement a safe undo flow before changing production.
6. Phase 5 will add visual branching conversations and reusable message variants in the workspace.

## Important safety

Do not add a Gmail sending permission or start a campaign as a side effect of importing. Do not enable all write flags at once. The live Vercel domain and production Neon branch must remain unchanged pending the end-to-end release checklist.
