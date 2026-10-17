# Letter Desk Phase 3 — Six-Service Scouting & Evidence (2026-10-17)

Environment: GitHub feature branch `feature/letterdesk-unified-neon`, Neon branch `letterdesk-unified-staging`; production `main` remains unchanged.
This is a staging milestone, NOT a full production scouting launch.

## Implemented

1. Service-specific search query planner for Author, Automation, Website Design, Digital Planner, Shopify and Google Maps.
2. Dedicated Scouting Studio in each service dashboard: niche, country, city, research signals, optional seed website, live query previews, job history, and evidence results.
3. Neon staging tables `ld_discovery_jobs` and `ld_discovery_results`, with per-service workspace binding.
4. DDGS public web discovery adapter and bounded official-website contact research (small page caps, requests timeouts, basic robots.txt compliance, internal-network URL rejection, no browser logins).
5. Collection of public `mailto:` and visible contact emails only; each saved as **published but unverified** with exact source page URL. No generated or guessed emails.
6. Optional official Google Places Text Search API (New) adapter for Google Maps mode. It requires `GOOGLE_PLACES_API_KEY`, enabled API permissions and billing; Google Maps UI scraping is intentionally NOT used. Listings with no official website remain research-only.
7. Team-level duplicate keys, service-specific opportunities, unconfirmed source evidence and no-message send eligibility by default.
8. Isolated background discovery worker with database row claiming, stale-job recovery and request caps. Web requests queue jobs rather than waiting for a long search response.
9. Hard stage-only gate `LETTERDESK_SCOUT_WRITE_ENABLED=false` by default. The separate staging middleware still blocks legacy send, SMTP and Telegram/web research mutation routes, even when this discovery flag is later enabled.
10. Regression tests for search-plan differences, blocked local/internal URLs, published email extraction, Maps API adapter, team isolation, and disabled-by-default job writing.

## Explicit limitations / remaining acceptance

- **The new query planner and read-only job history can be tested in preview after sign-in.** Login acceptance was previously reported as failing, and signed-in browser validation remains outstanding.
- **Actual remote scouting jobs are intentionally disabled** until a signed-in acceptance pass. To enable on isolated preview, set `LETTERDESK_SCOUT_WRITE_ENABLED=true` on preview Render API and redeploy, after confirming staging safety. Do not enable on the live Render service.
- To enable Maps mode, separately configure a server-side `GOOGLE_PLACES_API_KEY` with billing/quotas and restrictions. Never put the key in `VITE_` frontend variables.
- External search execution, website permission outcomes, and real source persistence have not yet been end-to-end verified against live sites. The code unit/integration suite uses mocked providers to avoid unsolicited network requests.
- The current URL/public-domain checks defend common SSRF patterns but do not harden DNS rebinding through pinned network resolution. Deploy with conservative network egress and firewall restrictions before broad production crawling.
- Full opportunity scoring and personalized research are Phase 7; file imports are Phase 4; conversation branching UI is Phase 5; Gmail/API automated sending is Phase 6.
- Do not treat a published public email as deliverable or opt-in. No prospect receives an email merely because the engine finds a contact candidate.
- No guaranteed email discovery; source sites may omit contacts or prohibit crawling.
- No provider abuse, bypassing logins, high-volume scraping, or guaranteed deliverability.

## Preview validation checklist

1. Sign in to `https://letterdesk-v2-ui-preview.onrender.com/?signin=1` using the existing staging account.
2. Open Service Workspaces → each service → Scouting Studio. Enter Madrid/Spain, adjust niche/signals; ensure all six query plans differ.
3. Verify no automatic campaign send and no requested Gmail permissions.
4. Query-only preview should show 'Scouting execution locked'.
5. Once login and safe worker passes, enable preview-only discovery writes. Create **one test job**, inspect exact public source URLs, extracted mailto results, pending research status, team isolation and duplicate key reuse.
6. Re-run safe migrations, validate no legacy data changed, test mobile navigation and cancel/restart behavior.
7. Turn off write flag at any incident; production remains unchanged.

## Phase 4 next

Excel/CSV imports with per-service column mapping, preview and row-level validation, optional `First Message` and `Message0101Yes/No` branches, duplicate/suppression checks, rollback and asynchronous import of 500+ records.
