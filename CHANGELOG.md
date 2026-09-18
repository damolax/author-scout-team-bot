# v3.2

- Added persistent Neon author source registry.
- Added demand-driven author candidate reservoir.
- Added background source crawling for directories, associations, agencies, publishers and literature sources.
- Added background pre-verification of website, public professional email and current activity.
- Changed /find to use pre-verified reservoir candidates before fresh web discovery.
- Freshly discovered candidates are written back to Neon for future runs.
- Claimed authors are suppressed from the reservoir.
- Added /indexstatus.
- Kept v3.1 high-speed parallel search, cache, keep-alive HTTP and LinkedIn Connection Intelligence.

# Changelog

## v3.1 — Connection Intelligence + High-Speed Research

- Added continuous background LinkedIn Connection Intelligence.
- Added `/connectsetup`, `/connections`, `/connectionstatus`, and `/connectionprefs`.
- Added team-level LinkedIn profile deduplication and optional global exclusivity.
- Added manual LinkedIn outcome buttons: Open LinkedIn, Mark Connected, Skip, Not Relevant, Save.
- Connected profiles are archived instead of deleted so duplicate suppression is permanent.
- Default public-location exclusion is Nigeria; nationality/ethnicity is never inferred.
- Added connection fit scoring based on the canonical `CONNECTION_FIT_PROMPT_V1.txt` criteria.
- Parallelized author discovery routes.
- Increased bounded author verification concurrency (default 10).
- Added fail-fast contact qualification before current-activity enrichment.
- Added result caching for research and search queries.
- Replaced multi-backend serial search cycling with fast primary search plus fallback only when needed.
- Reused HTTP keep-alive connections instead of creating a new HTTP client for every page fetch.
- Replaced per-candidate duplicate DB queries with one duplicate-set read per `/find` run.
- Author verification now uses first-qualified-result completion and cancels remaining slow tasks once the requested batch is filled.

## v2.0

- Existing team author scouting, shared duplicate prevention, ChatGPT workbook handoff, Gmail workflow, campaign stats, and deliverability testing.