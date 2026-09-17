# Author Scout Team Bot

Telegram bot for team author scouting, shared duplicate prevention, ChatGPT message handoff, manual Gmail outreach, stats/leaderboards, and opt-in live deliverability testing.

## Main workflow

1. Create a team with `/newteam Team Name`.
2. Teammates join with `/join CODE`.
3. Scout authors with `/find 10 | UAE | fiction | male | email`.
4. The bot blocks prospects already claimed anywhere in the system.
5. Give researched authors to ChatGPT, then upload ChatGPT's XLSX/CSV back to the bot.
6. Use `/queue` for unsent messages.
7. Send manually with **Open Gmail**, then **Mark Sent**.
8. Optionally connect Gmail under `/gmail` for live deliverability tests only.
9. Live tests send the queued message to up to 10 opted-in test inboxes. Recipients report Inbox / Promotions / Spam / Not received from Telegram.

## Stats

`/stats` shows today, yesterday, last 7 days, today's global leader, and the rolling 5-hour leader.

Custom range:

`/stats 2026-09-01 2026-09-15`

Global top 10:

`/leaderboard`

## Production

Build:
`pip install -r requirements.txt`

Start:
`uvicorn bot_main:app --host 0.0.0.0 --port $PORT`

Environment variables are listed in `.env.example`.

Never commit real secrets or Telegram/Google credentials to GitHub.
