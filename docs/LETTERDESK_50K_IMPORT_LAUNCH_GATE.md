# Letter Desk — 50,000-record bulk importing and launch acceptance
**Date:** 2026-10-19. **Branch:** `feature/letterdesk-unified-neon`. **Production:** unchanged at `https://author-scout-team-bot.vercel.app/`.

## Real limits and behavior

- Standard quick preview: CSV/XLSX/XLSM, currently 8 MB / 5,000 records in the browser. For larger spreadsheets, choose **Open importer → Bulk upload**.
- New persistent bulk uploader supports **50,000 nonempty prospect records per file** and **64 MiB compressed/source size**. The maximum safe expanded XLSX ZIP size is 192 MiB and up to 2,000 ZIP members. Files larger than that are rejected with a clear message, not silently truncated.
- User-provided first messages, subjects, English versions, author research, service-specific details, URLs, and nested Message01/Message0101Yes/Message0101No etc. are preserved by the existing approved import mapper.
- Upload is transferred through **1 MiB chunks** with SHA-256 idempotency. Browser sends up to three parts at once; changing any accepted part raises conflict rather than replacing evidence. Google/Gmail is not involved.
- Encrypted raw upload parts are stored only in the isolated Neon backend, scoped by team, account, workspace and whole-file SHA-256. The backend decrypts/verifies them, checks for missing parts, and reconstructs the 64 MiB maximum upload.
- All parsing is read-only at first. The background parser reads CSV and XLSX sequentially, retains duplicate state across 500-row chunks and returns summary + first 25 sample rows. Blank rows do not consume the 50k record allowance.
- An explicit **Confirm import** is mandatory. It checks a short-lived HMAC approval token tied to the exact owner workspace, uploaded hash and preview totals.
- After approval, the background worker commits up to **500 rows per Neon transaction** and checkpoints progress after each chunk. Previously completed parts are recognized by deterministic file fingerprints if the worker restarts; messages remain `needs_review`, never automatically sent.
- Incoming rows are checked for duplicates within the file and the team's existing leads, email opt-outs and historical sent/replied indicators; service-specific foreign keys and allowed contact verification flags remain the same.
- Paused clients can resume using the same file SHA without re-uploading completed chunks. Progress is persisted and polled every 3 seconds; the page can be closed and reopened using Recent bulk jobs.
- Encrypted raw chunks are purged after a **completed** import. Abandoned staging jobs are expired after seven days. Maximum five concurrently staged jobs / 192 MiB per account; older completed batches retain audit rows and results, not original full file bytes.
- Unknown network delivery errors or worker crashes do not trigger Gmail and do not auto-send. The bulk worker is separate from the outbound delivery worker.
- Existing regular import audit batches remain per 500-row part for traceability; a complete 50k upload creates up to 100 child batches and has its own master job/progress record. Rollback remains conservative and is not a one-click deletion of shared contacts.

## Feature flags, safety

```env
LETTERDESK_STAGING_ISOLATED=true
LETTERDESK_V2_ENABLED=true
LETTERDESK_BULK_UPLOAD_ENABLED=false
LETTERDESK_IMPORT_WRITE_ENABLED=false
LETTERDESK_GMAIL_SEND_ENABLED=false
LETTERDESK_REPLY_SAFETY_READY=false
LETTERDESK_DELIVERY_OPERATOR_APPROVED=false
```

- Setting only `LETTERDESK_BULK_UPLOAD_ENABLED=true` enables **encrypted staging and preview**, *not contact database writes*. It requires a working server-side Fernet `TOKEN_ENCRYPTION_KEY`.
- `LETTERDESK_IMPORT_WRITE_ENABLED=true` must be enabled separately, **on isolated staging first**, after checking the user login and one import transaction.
- Other Gmail and campaign flags must remain false; nothing about large uploads relaxes sender verification or opt-out requirements.
- Source files contain personal/professional contact information. Do not expose them in logs, public attachments or browser console, and do not enable bulk staging until the user is authorized to handle them.

## Automated test acceptance

- Six existing service templates and field imports tested with optional first messages and nested replies.
- Added **10,000 CSV author rows**, **10,000 XLSX Shopify rows** with research and message branch column, **50,000 CSV author rows**, and hard rejection of **50,001 rows**.
- Deduplication across 500-row boundaries, absolute row numbers and message branch retention.
- HMAC protection against mismatched team, workspace, job id, file sha and changed preview totals.
- Frontend Vite build, Python compile, Phase 1–8 regression tests and staging default no-send tests.

## Remaining production acceptance — do NOT mark complete without evidence

1. Browser login verification for a real staging user and session persistence on reload; no credentials exposed to ChatGPT.
2. One permitted small synthetic test import, confirming contact state and draft state, with conservative undo check.
3. A **real end-to-end 10,000 and 50,000 row browser upload** with elapsed times for SHA computation, chunk transfer, background preview, and database import separately. Unit tests are not a substitute for a production-like network benchmark.
4. Test worker interruption and recovery after a committed 500-row batch, no duplicate prospects/drafts and correct resumed progress totals.
5. Multi-user access and service separation on two independent accounts.
6. If Gmail is required at launch, connect one owned test account through Google OAuth, verify alias and exact scope, read a test thread only with permission, and verify suppression after opt-out. Restricted OAuth scope approvals and privacy disclosure are external prerequisites.
7. Final review of Neon production schema migration, Render/Vercel environment without logging secrets, access controls and backups. Main site stays untouched until approval and successful acceptance.

**Note:** 50k is a supported code-level upper bound, not a proven 50k-in-five-seconds promise. The total time for a network upload depends heavily on file size, client connection and Neon/Render plan.
