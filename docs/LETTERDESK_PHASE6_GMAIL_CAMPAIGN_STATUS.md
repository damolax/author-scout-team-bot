# Letter Desk 2.0 — Phase 6 Gmail Connections & Controlled Campaigns

**Date**: 17 October 2026. **Status**: Development implementation on protected branch, **NOT live sending or production cutover**.

- Code branch: `feature/letterdesk-unified-neon` / draft PR #5
- Main site (unchanged): https://author-scout-team-bot.vercel.app/
- Staging frontend: https://letterdesk-v2-ui-preview.onrender.com/
- Staging API: https://letterdesk-v2-api-preview.onrender.com/
- Staging Neon branch: `letterdesk-unified-staging`

## Features implemented

1. **Multiple Gmail accounts per team**: distinct `ld_gmail_connections` with Google subject, primary address, account ownership, encrypted refresh token, granted scopes and connection status.
2. **OAuth state replay protection**: random 256-bit state, SHA-256 stored in Neon, one-time consume, ten-minute expiry; no app access keys in callback URLs. Google authorization grants account permission, not campaign permission.
3. **Permission-minimizing account connections**: Gmail send + `openid email` scopes by default; optional restricted `gmail.settings.basic` only on explicit user request for Gmail `users.settings.sendAs.list` discovery.
4. **Verified Send as identities**: Google primary email or aliases Google reports as `verificationStatus=accepted`; unverified/pending aliases cannot be enabled for campaigns. Manual alias entry is not treated as proof. The restricted scope can trigger Google app verification/security-assessment obligations.
5. **Service-specific sender routing**: each of the six dashboards has a Gmail & Campaign Center and can choose one independently verified Gmail identity for each draft campaign. Only the account owner can enable that sender, create or activate campaigns and approve its queued messages.
6. **Campaign drafts and approval queue**: named campaign, sender, max daily 1–30, minimum interval >=120 sec, 9–17 local time defaults, IANA timezone; eligible unsent draft picker, documented contact basis, explicit queue approval, pause/hold. Service- and team-scoped.
7. **Recipients must be reviewed**: only unsent `needs_review` messages, recipient equal to draft email, no stopped/lost conversation, no team-level opt-out, no duplicated queued/sent outreach to same address in a team, explicit opt-in/existing relationship/documented legitimate-interest basis and written evidence.
8. **Three-key production delivery engine** in `letterdesk_campaign_delivery.py`: `LETTERDESK_GMAIL_SEND_ENABLED`, `LETTERDESK_REPLY_SAFETY_READY`, `LETTERDESK_DELIVERY_OPERATOR_APPROVED` must all be true AND `LETTERDESK_STAGING_ISOLATED` must be false. No Gmail sending runs in staging under any combination of these keys.
9. **One-shot Gmail delivery**: refresh tokens decrypted server-side only, Gmail API POST once; successful Gmail provider ID recorded; an uncertain network result is quarantined and pauses the campaign **without automatic retry**. Sender daily and cooldown quota reserved at claim. Weekends and outside-business-hour sends are skipped. Global team daily cap of 100. Suppression checked immediately before claim.
10. **Safe disconnection**: only account owner can disconnect; encrypted refresh token field blanked, sender identities disabled, associated campaigns paused and unsent queue held. Users may additionally revoke app access in Google account settings.
11. **Separate Neon tables**: `ld_gmail_connections`, `ld_gmail_oauth_states`, `ld_gmail_sender_identities`, `ld_campaigns`, `ld_campaign_queue`, `ld_campaign_sender_health`. Preserves original prospects and historical email messages.
12. **UI**: connect Gmail, explicitly choose whether to request restricted alias scope, list owned/shared Gmail accounts, display Google-verified address status, service sender controls, campaign drafts, available unsent messages, consent/basis evidence, human approval queue and pause controls.

## Security and release gates

Leave **all flags FALSE** in Render staging initially:

```env
LETTERDESK_V2_ENABLED=true
LETTERDESK_STAGING_ISOLATED=true
LETTERDESK_GMAIL_OAUTH_ENABLED=false
LETTERDESK_CAMPAIGN_WRITE_ENABLED=false
LETTERDESK_GMAIL_SEND_ENABLED=false
LETTERDESK_REPLY_SAFETY_READY=false
LETTERDESK_DELIVERY_OPERATOR_APPROVED=false
```

OAuth connection has additional requirements (do NOT paste secrets into chat):

```env
GOOGLE_CLIENT_ID=<secret>
GOOGLE_CLIENT_SECRET=<secret>
TOKEN_ENCRYPTION_KEY=<genuine Fernet key>
LETTERDESK_GMAIL_SERVER_ORIGIN=https://letterdesk-v2-api-preview.onrender.com
LETTERDESK_GMAIL_FRONTEND_ORIGIN=https://letterdesk-v2-ui-preview.onrender.com
LETTERDESK_GMAIL_REDIRECT_URI=https://letterdesk-v2-api-preview.onrender.com/api/v2/letterdesk/gmail/callback
```

- Add exact OAuth callback to Google Auth Platform Web OAuth client; public sign-in site is the separate Render UI preview, while Google callbacks reach the Render API.
- The previously screenshotted Google OAuth client secret should be **rotated** before connecting any real Gmail account.
- Google Auth Platform **Testing** permits a limited test-user list (max 100); refresh-token lifetime can be short (often seven days for nonbasic scopes). Publishing/Google verification may be required before 100+ Gmail accounts.
- `gmail.settings.basic` is a restricted Gmail scope and may require additional Google verification/security assessment. Default primary-Gmail connection does not request it.
- Do not place Google tokens, encryption keys or other secrets in Vite `VITE_*` environment variables, URLs, GitHub commits or frontend localStorage.
- Compliance: visible website email is **not consent**. Where legitimate-interest messaging is lawful, record accurate relevance and applicable privacy/opt-out requirements; otherwise use verified permission or existing relationships.
- There is no automated Gmail reply ingestion, classification or suppression sync yet. `LETTERDESK_REPLY_SAFETY_READY` must remain false until Phase 7 provides that functionality and passes tests.
- A sender may be disabled by the user at any time, and campaigns paused. An in-flight Gmail API request cannot be withdrawn.
- No anonymous or unauthenticated sending endpoints exist.
- Google connected sender aliases only become verified when Google API confirms acceptance; no bypass or spoofing.

## Testing and acceptance

**Automated code tests**: OAuth scopes, one-time-state hashing, alias acceptance, cross-team access, staging disabled flags, campaign basis checking, no-send API isolation, Gmail delivery kill switches, header injection rejection.

**NOT yet proven**: a real Google consent/callback, successful token refresh, verified Send as alias discovery on a live Gmail account, a real single-account test send, Gmail reply synchronization, browser login acceptance (previously reported login page did not advance), actual 100+ account scale, or a production cutover. No outgoing emails have been triggered from Phase 6.

## Acceptance sequence before any real outreach

1. Resolve signed-in staging login and select **Service Workspaces → Gmail & Campaign Center**.
2. Rotate the previously exposed Google secret; configure Google OAuth staging client and exact redirect URL.
3. On a single authorized test Gmail account, set `LETTERDESK_GMAIL_OAUTH_ENABLED=true` only in staging. Connect, disconnect and reconnect, verify scope grant and encryption, and confirm cross-team isolation.
4. Verify primary Gmail and optional accepted aliases through the official Gmail Settings API permission process. Enable only verified identities.
5. Optionally turn on `LETTERDESK_CAMPAIGN_WRITE_ENABLED=true` on staging, create one **draft** campaign, queue an approved test contact, validate quotas and suppression/duplicate safeguards. No sends.
6. Phase 7 implements authorized reply ingestion, opt-out and bounce/negative stop conditions, campaign safety state machine, and reviewer-approved branches.
7. Only after Phase 7 and formal review may an operator enable production (non-staging) delivery flags. Test a single consented address before any broader release. The Vercel live app remains untouched until all release gates pass.

## Next phase

**Phase 7 — Conversation intelligence, Gmail reply monitoring, suppression and branching execution.** Reconcile real replies against Gmail thread IDs, honor opt-out/decline/bounce across all services, recommend context-dependent response drafts, require human review, and integrate with Phase 5 flow designs without auto-sending unreviewed content.
