# Letter Desk Phase 7 — Reply Intelligence, Gmail Thread Monitoring & Reviewed Branches

**Date:** 17 October 2026
**Build:** `feature/letterdesk-unified-neon` (protected development branch / PR #5)
**Release state:** Staging implementation; **no live Gmail read permission, campaign sending, or automatic replies enabled**.

## Implemented architecture

- Six separate service dashboards now contain **Reply Inbox & Decisions** with historical replies, status filters, account-sync health, chosen contact, human classification, proposed next message and flow assignment.
- Conservative deterministic English/Spanish reply triage: possible positive, contextual Yes/No, question, objection, not-now, explicit negative, opt-out, confirmed delivery failure, uncertain.
- **"No" means context-dependent No.** Explicit "No thanks"/"not interested"/"don't follow up" is a hard decline; unsubscribe/remove-me requests are opt-outs; all high-confidence stop outcomes immediately suppress that normalized email across *all* service workspaces in its team.
- Clear stop decisions persist in team-wide `ld_suppressions` and hold all unsent `ld_campaign_queue` entries for the recipient; any reply pauses remaining contact-specific queued outreach pending review. Already-sent messages are not unsent.
- Every inbound message is encrypted at rest using `TOKEN_ENCRYPTION_KEY` before entering `ld_reply_inbox`; existing tokens and Gmail messages are not stored in plaintext.
- Manual reply recording requires selecting an existing **sent** conversation and verifying that the reply's sender address matches the prospect's original contact. The client supplies an idempotency key to prevent duplicate submissions.
- Read-only classification preview is available without changing any contact or campaign, even when all write flags are off.
- Reviewer can confirm/change uncertain classification or stop a recipient; decisions are audit-stamped. Draft next-step recommendations remain encrypted proposals **within the reply record**, not approved outgoing messages or queued emails. No auto-sending.
- Phase 5 `ld_flow_designs` can be assigned as a frozen snapshot to an individual conversation. Once replies exist, the assigned history cannot be silently replaced. Service starter flow applies when none is assigned.
- Google Gmail readonly permission `https://www.googleapis.com/auth/gmail.readonly` is **restricted** and optional. An explicit checkbox in Gmail & Campaign Center requests it; default OAuth still only asks `openid email gmail.send`.
- Gmail reader uses **GET only known sent Gmail thread IDs** from `ld_campaign_queue.provider_thread_id`; it does *not* enumerate the mailbox or run broad Gmail searches. Reads `text/plain` content only, ignores attachments and HTML, matches reply FROM to the exact recipient and TO to the verified sending identity, and requires a date later than the sent message.
- Each Gmail provider message has a unique (connection ID, provider ID) database key for deduplication. Known threads are read round-robin with persisted per-thread checked timestamps; polling is capped at 12 threads per account per pass.
- A per-Gmail-connection `ld_gmail_reply_sync` heartbeat tracks recent successful checks and errors. The Phase 6 delivery worker now requires `gmail.send` **and** `gmail.readonly`, a healthy sync within the last 30 minutes, and existing three-key external release controls, and persists Gmail's response thread ID for later replies.
- An opt-in read-only worker is mounted, but never starts with default staging flags. No automatic follow-up is sent on any reply, even if its branch is suggested.

## Neon additive staging changes

`ld_reply_inbox`, `ld_conversation_flow_bindings`, `ld_gmail_reply_sync`, `ld_gmail_thread_watch`, and `ld_campaign_queue.provider_thread_id`. No destructive migrations or replacement of existing message history.

## Safe environment defaults (keep false until acceptance)

```env
LETTERDESK_REPLY_WRITE_ENABLED=false
LETTERDESK_GMAIL_READ_OAUTH_ENABLED=false
LETTERDESK_GMAIL_READ_ENABLED=false
LETTERDESK_GMAIL_SEND_ENABLED=false
LETTERDESK_REPLY_SAFETY_READY=false
LETTERDESK_DELIVERY_OPERATOR_APPROVED=false
LETTERDESK_STAGING_ISOLATED=true
```

Phase 7's Gmail reader additionally requires `LETTERDESK_GMAIL_OAUTH_ENABLED=true` and secure Google/OAuth credentials **only when intentionally authorizing** a test Gmail account. The policy/privacy notice must disclose scope and data retention before permission is requested. Do not enable `gmail.settings.basic` merely to read replies; that scope is separate and also restricted.

## Regression coverage

- Yes vs No vs explicit decline, unsubscription, Spanish stop phrases, quoted original-email content, incomplete/ambiguous replies.
- Gmail thread message extraction: exact sender/recipient/time validation, ignoring unrelated participants and HTML.
- Scoped Gmail readonly opt-in vs default send-only authorization.
- Authenticated per-service classification preview, wrong-team isolation, write-disabled manual intake and flow assignment.
- Staging no-send and no-automatic-retry controls remain in force.
- GitHub CI Python checks, frontend production build and staging deployment monitored.

## IMPORTANT: What is *not* yet verified or complete

- Prior staging sign-in issue still requires a real signed-in browser acceptance test.
- A real authorized Google read-only OAuth grant and token refresh have not yet been tested. Google may require restricted-scope OAuth verification or an external security assessment.
- No actual Gmail sent-thread reply has been ingested end-to-end. Unit tests use simulated Gmail payloads.
- Hard-bounce emails generated by mailer-daemon are not automatically attributed to a prospect unless confirmed from a known thread and exact recipient. Currently they require manual review; no inbox-wide scanning or guessed identity matching.
- Gmail background polling has conservative workload caps, not proven to support 100+ Gmail accounts at scale.
- Existing legacy messages without a recorded Gmail `provider_thread_id` are not silently correlated to Gmail messages. Manual reply capture remains available for those.
- Decision draft suggestions are not yet turned into editable approved `ld_message_records` automatically. This is deliberate: the reviewer must verify evidence and placeholders first.
- Data deletion workflows, audit export, Gmail verification paperwork and retention implementation remain release-gate work.
- Enabling flow assignment/reply recording on isolated staging still requires `LETTERDESK_REPLY_WRITE_ENABLED=true`, **after** sign-in and encryption acceptance. No staging Google connection or sending has been enabled by this phase.
- Production Vercel `https://author-scout-team-bot.vercel.app/` is unchanged.

## Final acceptance before any wider sending

1. Verify isolated staging login; test classification without enabling any writes.
2. Enable reply writes **only in staging**, enter a synthetic/manual reply on an authorized existing test conversation, confirm opt-out across all six services, dedupe and reviewer audit, then verify no queued message is sent.
3. Rotate earlier exposed Google OAuth client secret and configure exact callback for staging. Test ONE authorized Gmail account, first with basic send scope and then with separately approved readonly scope.
4. Confirm a single consented test send in a later authorized non-staging controlled environment, capture Gmail provider thread ID and prove reply intake without reading unrelated mailbox threads.
5. Test unsubscription, bounce, duplicate replies, network timeout, account disconnect, delayed polling, token revocation, team isolation, and post-reply send blocking.
6. Complete documented GDPR/ePrivacy/other applicable outreach legal review, OAuth limited-use privacy disclosures and data retention/delete controls.
7. Only after all gates and signed approval should campaigns be permitted on the primary Vercel site. Do not enable live delivery during this staging phase.

**Likely next milestone:** Phase 8 integration/acceptance hardening: real-user sign-in, file/import undo, 500-row performance, controlled sender OAuth, policy and final Vercel/Neon launch checklist. "Perfect functionality" requires live browser and provider tests, not just passing mocks.
