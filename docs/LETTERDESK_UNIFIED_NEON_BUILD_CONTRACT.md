# Letter Desk 2.0 — Unified Neon build contract

Status: Phase 1 (foundation), 2026-10-16. This branch is development-only.
Production URL to retain at cutover: https://author-scout-team-bot.vercel.app/
Code branch: `feature/letterdesk-unified-neon`.
Neon project: existing Author Scout project; staging database branch `letterdesk-unified-staging`. Never run an unreviewed migration on main.

## Product architecture

- **One Letter Desk application** with six service modes: author, automation, website-design, digital-planner, shopify, google-maps.
- **Neon PostgreSQL** is the sole application database; do not depend on Supabase runtime/auth/storage. New auth must be integrated with the existing Neon Auth / current web login and migrated without account loss.
- **Vercel** hosts the main web UI. Use a separate staging deployment before switching the production build.
- Keep the existing **Render author research / Telegram** worker usable during the migration. Port verified code from `damolax/Scout-app`, `damolax/scout-extension`, and `damolax/scout-opportunity-intelligence` behind stable, authenticated endpoints. Do not reuse Supabase-coupled operations unchanged.
- Centralized lead/contact identity, suppression, provenance, audit, job orchestration, sending states, and permissions; service-specific workspaces keep independent scoring, lists, messages, sender mappings, templates and reporting.
- Use compliant public-web/authorized provider discovery and official Google Maps/Places APIs where necessary; respect provider restrictions, crawling limitations and opt-outs.

## Eight gated phases

1. **Foundation** — audit existing Neon and source repositories; create isolated GitHub and Neon branches; agree migration mapping, auth and job-queue design; add schema and domain contracts.
2. **UI** — premium Letter Desk shell, global overview, six service dashboards, role-based security, mobile support, loading/performance guarantees.
3. **Scouting** — Google Maps/local business discovery, web queries, email-source evidence, bounded website crawling, background jobs, professional contact validation; domain-specific rules for each service.
4. **Imports** — Excel/CSV per-service presets, header mapping, optional subject/message columns, preview, error export, queued large imports, deduplication, per-row evidence and import rollback.
5. **Conversation flows** — editable versioned templates, message variants, visual branches, positive/question/objection/not-now/negative/opt-out/no-reply classification, safe actions, preview, human review, stop conditions.
6. **Gmail & campaigns** — Google OAuth, verified Send-as mapping per service, safe token storage, approved queues, durable idempotent worker, provider-aware limits, failure handling and campaign progress.
7. **CRM & intelligence** — unified inbox where authorized, reply context, research-based recommendations, pipeline stages, analytics and service dashboards. Avoid adding restricted Google scopes unless justified and reviewed.
8. **Quality & launch** — unit/integration/browser/mobile/security tests; staged record migration/row counts, controlled alias-send tests, monitored release and rollback to old production.

Each gate requires tests, a demo of the actual behavior and no unreviewed production data mutations.

## Common upload columns (all six services)

`Name`, `Email`, `Website`, `Country`, `City`, `Source URL`, `Evidence Notes`, `Subject` (optional), `First Message` (optional), `First Message English` (optional), `Status` (optional), `Do Not Contact` (optional).

Minimum for prospect intake: a name plus at least one of professional email, website, or Google Maps URL. **An uploaded email is not automatically verified; and a row without a message is a lead, not a ready-to-send email.**

### Service-specific optional columns

| Workspace | Service-specific fields |
|---|---|
| Author | Author Name, Book Titles, Genre, Recent Publication, Publisher, Author Profile, Recent Activity, Literary Angle, Email Source URL |
| Automation | Business Name, Business Type, Current Tools, Manual Workflow Signal, Integration Opportunity, Opportunity Evidence URL |
| Website Design | Business Name, Website URL, Website Issue, Page URL, UX/Accessibility Observation, Website Technology, Evidence URL |
| Digital Planner | Creator or Shop Name, Storefront URL, Planner Niche, Product Type, Product URL, Audience, Opportunity Evidence URL |
| Shopify | Store Name, Shopify Store URL, Product Category, Store Issue, Issue Page URL, Ecommerce Opportunity, Evidence URL |
| Google Maps | Business Name, Google Maps URL, Google Place ID, Business Category, Address, Business Website, Listing Observation, Evidence URL |

All modes may import contact records without any first-message field. A service template may be attached later.

## Conversation graph

Every template has a version, service, owner, status (draft/published/archived), and a directed graph.

- Nodes have stable IDs such as `MSG-01`, `MSG-0101`, `MSG-0102`, optional variant group, subject, body, delay, and review policy.
- Edges use structured outcomes: `positive`, `question`, `objection`, `not_now`, `negative`, `opt_out`, `no_reply`, `bounce`, `uncertain`.
- `opt_out`, `negative` explicit refusal and permanent `bounce` always halt future automated outreach; log global suppression when appropriate.
- `uncertain`, legal/pricing/contractual commitments and complex positive responses route to human review. Explicit prior approval is required before new automation branches are enabled.
- No fabricated proof of research, fake scarcity, reply-tone disguises, or pressure scripts.
- No infinite loop: bound time, contact attempts and graph traversal depth. Archive finished branches.
- Original inbound replies remain evidence for classification only after separate authorized Gmail read scopes are granted; requesting `gmail.send` does not grant inbox access.

## Existing data and migration

Neon currently contains legacy `prospects`, `messages`, `teams`, `gmail_accounts`, author research, web-research queues, and Neon Auth tables. Perform identity-preserving, idempotent migration in staging first. Existing author messages, notes, replied/sent status, team ownership and suppression must survive. Avoid exporting sensitive OAuth credentials; existing Gmail accounts may require secure reconnect.

Single lead can have multiple independent `ld_opportunities` across services, but globally suppress opt-outs and prevent inadvertent duplicate sends.

## Environment-variable transfer checklist (names only — never commit values)

Review existing Letter Desk variables (`VITE_API_BASE_URL`, Neon database/auth variables, application URL, existing OAuth encryption keys) and Scout variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SCHEDULE_WORKER_SECRET`, `CRON_SECRET`, sender safety settings).

- Reuse **Google OAuth client identity** only after confirming authorized redirect URIs for the actual Letter Desk callback.
- Do **not** migrate `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, or `SUPABASE_SECRET_KEY`; replace their functionality with Neon.
- Never expose Gmail secrets, Neon role passwords, application secrets or refresh tokens through `VITE_`/`NEXT_PUBLIC_` environment prefixes.
- A Vercel deployment cannot be called integrated until runtime checks confirm every required server-side variable exists and the callback works.
- Custom branded subdomains are optional; the production Vercel address remains the supported entry point until DNS is tested.

## Rollout conditions

Do not change `main` or production domain until staged migrations reconcile counts, all required service modes and flows pass tests, Gmail alias verified From header matches, duplicate-send guard passes, and rollback is demonstrated.
