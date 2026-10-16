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

- Staging deployment must point to the staging Neon database and implement cross-service authentication tests; no staging URL is verified yet.
- Service-specific lead scraping engines and Maps integration need porting from Scout, retaining provider-compliant crawling restrictions.
- Production Neon cutover must be planned with current main-backup snapshot and reconciliation before migrations.
- UI still needs per-service import execution, lead detail/edit, scouting controls, campaign queues, branching-flow visual editor, and per-service sender maps.
- Gmail OAuth, verified Send as routing, authorized reply syncing, retries, suppressions, provider caps and durable queue are **not enabled in the new platform**.
- Privacy-policy accuracy and Google OAuth requirements must be verified before requesting production scopes.
- End-to-end and mobile acceptance tests remain.
- Draft PR is intentionally unmerged. Do not treat a passing build as production readiness.

### Immediate next milestone

**Finish Phase 2: preview the six-mode dashboard against a staging Neon-backed Render API**, validate logins for both teams, verify imports without sending, and conduct mobile UI QA before moving to service-specific scouting engines (Phase 3).
