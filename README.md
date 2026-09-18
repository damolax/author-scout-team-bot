# Author Scout Team Bot

Telegram bot for team author scouting, global author duplicate prevention, ChatGPT research/message handoff, Gmail outreach workflow, campaign tracking, and LinkedIn Connection Intelligence.

## Author scouting

1. Create a team with `/newteam Team Name` or join with `/join CODE`.
2. Scout authors with natural language or `/find` filters.
3. v3.1 runs discovery routes concurrently, rejects known duplicates before network research, verifies multiple candidates concurrently, and stops/cancels slow work once the requested number of qualified authors is reached.
4. `/export` produces the ChatGPT-ready workbook for deep research and first-message generation.
5. Upload the completed workbook back to Telegram and use `/queue`.

## LinkedIn Connection Intelligence

Set up once:

`/connectsetup https://www.linkedin.com/in/your-profile`

Optional focus:

`/connectsetup https://www.linkedin.com/in/your-profile | publishing authors literary agents`

Then use:

- `/connections` — show qualified profiles already waiting in your background queue.
- `/connectionstatus` — ready/connected/skipped/not-relevant counts.
- `/connectionprefs` — tune countries, excluded public locations, fit threshold, ready-pool target, and query focus.

The background worker continuously replenishes each enabled user's ready pool. Pressing Connections displays profiles already researched; it does not start the research from zero.

Connection actions are intentionally manual. The bot does not send LinkedIn invitations. Use **Open LinkedIn**, then return and press **Mark Connected**. Connected profiles are archived in the database rather than deleted so the same team does not receive them again.

The default geographic rule excludes profiles whose public professional location is Nigeria. The system never infers nationality, ethnicity, or other sensitive traits from names, photos, language, or appearance.

## Speed architecture in v3.1

- concurrent discovery routes
- bounded parallel author verification
- search-result caching
- author/contact research caching
- shared HTTP keep-alive connection pool
- fast primary search backend with fallback only when required
- fail-fast website/email qualification before additional activity research
- one duplicate-set DB read per run instead of one query per candidate
- first-qualified-result processing and cancellation of unnecessary pending work

Tune performance in Render with the variables shown in `.env.example`. Start with `AUTHOR_RESEARCH_CONCURRENCY=10`. If your hosting/search providers tolerate the load, it can be raised up to 16.

## Production

Build:

`pip install -r requirements.txt`

Start:

`uvicorn bot_main_v3:app --host 0.0.0.0 --port $PORT`

`bot_main.py` remains in the repository as the v2 fallback. To roll back, point Render's start command back to `uvicorn bot_main:app ...`.

## Persistent author source index

Author Scout v3.2 now keeps a persistent, demand-driven author reservoir in the database.

- Every `/find` request updates a search-demand profile.
- The background source-index worker discovers useful author directories, literature centres, writers' associations, agencies, publishers, festivals and list pages.
- Candidate identities are stored in `author_candidate_pool`.
- A configurable number are pre-verified in the background for website, public professional email and recent activity.
- `/find` uses already verified reservoir records first and only opens fresh web discovery when the reservoir cannot fill the request.
- Claimed authors are suppressed in the reservoir so they are not recycled.
- Use `/indexstatus` to inspect reservoir, verification and source counts.

This is designed to reduce cold-search latency substantially as the reservoir warms up.
