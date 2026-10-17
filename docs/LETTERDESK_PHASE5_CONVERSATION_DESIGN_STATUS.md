# Letter Desk Phase 5 — Visual Conversation Automation (2026-10-17)

**Repository**: `damolax/author-scout-team-bot`, feature branch `feature/letterdesk-unified-neon`, draft PR #5.
**Product site remains**: https://author-scout-team-bot.vercel.app/ (unchanged).
**Staging UI**: https://letterdesk-v2-ui-preview.onrender.com/
**Staging API**: https://letterdesk-v2-api-preview.onrender.com/
**Neon**: isolated branch `letterdesk-unified-staging`.

## What's implemented

- Visually connected branch-map interface embedded independently in all six service dashboards.
- Per-service starter graphs, with editable initial, Yes, No, question, objection, later, follow-up and additional nested response paths.
- Semantic difference between `no` in answer to a specific question (can have a reviewed follow-up) and `negative`/explicit decline or `opt_out` (terminal stop).
- Named nodes such as `Message01`, `Message0101Yes`, `Message0101No`, `Message0201Yes`, `Message0201No`; unlimited *depth within bounded graph limits* (max 45 nodes and 120 edges; 12-message-per-contact cap).
- Subject/body editing, alternative versions A/B etc. (maximum eight per node); all draft messages always require human review.
- Branch outcomes `yes`, `no`, `positive`, `question`, `objection`, `not_now`, `negative`, `opt_out`, `no_reply`, `bounce`, `uncertain`; action types reviewed draft, manual review, wait or stop.
- Explicit refusal, opt-out and hard-bounce branches MUST stop. Completed/terminal nodes never become sendable transitions; loops and duplicate outcome branches are prohibited.
- No-reply branches require at least a 24-hour delay and respect caps (starter uses seven days).
- Human-readable simulation choosing a node, reply outcome, sent count and follow-up count. This is *simulation*, not inbox reply classification or automatic sending.
- Read-only authenticated API: list, per-service sample, validate, simulate, fetch draft, fetch revision history.
- Separate, **feature-flag gated** save/update/archive for draft templates only. Optimistic revision numbers prevent one tab overwriting another; archived templates retain versions; no hard delete.
- Additive Neon staging schema: `ld_flow_designs`, `ld_flow_design_revisions`. Earlier relational `ld_message_flows` tables are retained for future publishing/queue execution but not yet connected to the draft designer.

## Security and testing

- `LETTERDESK_FLOW_WRITE_ENABLED=false` by default. No saving is enabled on the staging API while signed-in user acceptance is pending.
- No `publish`, `activate`, `auto-send` or Gmail endpoint is implemented by Phase 5. The existing staging middleware still prohibits sending and other unsafe mutations.
- Authenticated endpoints require ownership of the selected service workspace; another team's templates must not be exposed.
- Unit tests cover all six starters, Yes/No contextual branching, cap enforcement, loops, duplicate edges, explicit refusals, terminal-node safeguards and simulation no-send behavior.
- API tests cover anonymous denial, wrong-service denial, authorized validation and simulation, write-disable gate and no publish route.
- CI frontend build and Python tests confirm code compiles. Actual signed-in browser testing and create/edit/revision API integration on the staging database have **not yet been completed**.

## What is deliberately *not* claimed complete

- Gmail reply ingestion or automatic intent classification (Phase 7) is not connected.
- Scheduled multi-step sending and verified Gmail Send as alias routing (Phase 6) remain disabled.
- Publishing flow graphs into an active sending worker is not part of the current draft stage; all content requires a separate review/approval before any future activation.
- Import file branch variants from Phase 4 remain stored as passive per-row drafts, not automatically applied to a universal template.
- True dragging node locations on the canvas is not implemented: layout is automatic and nodes are clickable/editable; branch connectors are visual.
- Live Vercel production domain remains unchanged.
- Signed-in staging login and durable saving need user acceptance before the protected flags are enabled.

## Acceptance path

1. Sign in to isolated staging UI.
2. Choose Service Workspaces → Author → Conversation Builder.
3. Open the map and try `Message01` -> Yes; validate and simulate `Message0101Yes`.
4. Switch to Automation, Shopify or another mode; verify a different starter and separate templates.
5. Set a reply node to explicit opt-out and verify simulation stops.
6. After login acceptance, enable `LETTERDESK_FLOW_WRITE_ENABLED=true` **only for the isolated staging Render API**. Create a draft, edit/save revision 2, reload, verify history and team separation.
7. Do not enable production or automatic messaging until subsequent sending/security and real-reply phases have passed.

## Next phase

**Phase 6 — Gmail and campaigns:** Google OAuth scope strategy, per-service sender assignments with verified Send as aliases, secret encryption/rotation, safe queue and scheduled sending with duplicate guards, sender-health restrictions, reply/stop suppression, and careful test sends. This phase must include re-check of the previously disclosed Google client secret and Google verification requirements before production authorization.
