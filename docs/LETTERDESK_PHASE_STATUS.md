# Letter Desk 2.0 — implementation status (2026-10-16)

## Current gate: Phase 1 staging migration **PASS**; Phase 2 UI in feature branch

Production URL: https://author-scout-team-bot.vercel.app
Draft pull request: https://github.com/damolax/author-scout-team-bot/pull/5
GitHub branch: feature/letterdesk-unified-neon
Neon project: author-scout-team-bot
Neon staging branch: letterdesk-unified-staging

### Verified Phase 1 migration

- Original Neon tables preserved.
- Two existing teams yielded 12 service workspaces (six service modes each).
- 262 legacy prospects became 262 author leads/opportunities.
- 48 ready legacy messages became `needs_review` drafts.
- 4 already-sent messages remain marked `sent`.
- 94 deleted messages are stored as **tombstones only**, not deliverable records.
- Migration rerun left counts unchanged; backfill was idempotent.
- `database/checks/20261016_letterdesk_migration_audit.sql` passed in isolated Neon staging.
- Production Neon main and GitHub main were not migrated/overwritten.

### Feature-branch implementation

- Service-specific CSV/Excel header aliases and optional first messages.
- Structured `Message0101Yes` / `Message0101No` replies and nested branches.
- Distinction between contextual 'No' and explicit rejection or opt-out.
- Read-only, authenticated Neon service API: `/api/v2/letterdesk/services` and `/api/v2/letterdesk/services/{service_key}/leads`.
- API tests prove team isolation and active-service filtering.
- Responsive six-service dashboard with real counts and per-service CSV template downloads.
- New experience is **behind staging flags**, inactive in production:
  - Render: `LETTERDESK_V2_ENABLED=true` AFTER staging Neon schema and backfill is in place.
  - Vercel preview: `VITE_LETTERDESK_V2_UI=true`.
- CI web build and API/unit regressions passed for the feature commits.

### Not yet finished

- Staging Render preview deployed using isolated Neon, confirmed health and anonymous access guard; signed-in browser acceptance is still pending.
- Service-specific lead scraping engines and Maps integration need porting from Scout, retaining provider-compliant crawling restrictions.
- Production Neon cutover must be planned with current main-backup snapshot and reconciliation before migrations.
- UI still needs per-service import execution, lead detail/edit, scouting controls, campaign queues, branching-flow visual editor, and per-service sender maps.
- Gmail OAuth, verified Send as routing, authorized reply syncing, retries, suppressions, provider caps and durable queue are **not enabled in the new platform**.
- Privacy-policy accuracy and Google OAuth requirements must be verified before requesting production scopes.
- End-to-end and mobile acceptance tests remain.
- Draft PR is intentionally unmerged. Do not treat a passing build as production readiness.

### Immediate next milestone

**Finish Phase 2: preview the six-mode dashboard against a staging Neon-backed Render API**, validate logins for both teams, verify imports without sending, and conduct mobile UI QA before moving to service-specific scouting engines (Phase 3).

## Phase 2 staging deployment (16 October 2026)

- Read-only **API preview**: https://letterdesk-v2-api-preview.onrender.com (separate Render web service, `feature/letterdesk-unified-neon`).
- **UI preview**: https://letterdesk-v2-ui-preview.onrender.com (separate Render static site, `feature/letterdesk-unified-neon`).
- UI build environment `VITE_NEON_AUTH_URL` points to Neon staging Auth; `VITE_API_BASE_URL` points to preview API; `VITE_LETTERDESK_V2_UI=true`.
- API environment `DATABASE_URL` points to staging Neon; `LETTERDESK_V2_ENABLED=true`; `LETTERDESK_STAGING_ISOLATED=true`. A distinct APP_SECRET protects the preview.
- Neon staging Auth trusted-origin list updated to include UI preview domain.
- Verified by independent web fetch: `/api/v1/health` returns JSON with `ok:true`, `/api/v2/letterdesk/services` returns `401` without credentials, frontend returns a sign-in page.
- Implemented middleware denies every non-allowed request in preview, including outbound email routes, state-changing imports, scouting jobs, and OAuth initiation. Background workers disabled at startup; log verified.
- **Still unverified**: a real end-to-end signed-in preview session with the user's credentials, actual service list rendering, mobile acceptance and Vercel preview deployment. No production merger.
- Deployment on **Vercel** is waiting on the user connecting the Vercel integration; Render staging UI remains the temporary preview.

### Preview acceptance steps

1. Open https://letterdesk-v2-ui-preview.onrender.com, sign in using an authorized staging account (never share credentials in chat).
2. Open **Service Workspaces** in top navigation. Check Author / Automation / Website Design / Digital Planner / Shopify / Google Maps.
3. In Author mode, expect records belonging to the signed-in team only; search by a known prospect and confirm sourced context.
4. Switch services and confirm each uses a separate list and tailored CSV template; no synthetic contacts should be displayed.
5. Confirm the legacy Letterdesk tab is still present (for comparison only); uploading/sending and scouting mutations on this preview must be disabled by backend.
6. On mobile, confirm six-mode selector layout, table overflow, login session behavior.
7. Report login errors or unexpected counts before any production migration.

Do not claim this preview is production-ready. Gmail aliases, template graph UI, actual importing, scouting, workflows and automatic sending are later phases.
