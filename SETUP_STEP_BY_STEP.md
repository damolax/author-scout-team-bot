# Setup

## 1. Telegram

You already created the bot with @BotFather. Keep the token private.

## 2. GitHub

This repository contains the bot source. Keep the repository private before adding any project-specific configuration.

## 3. PostgreSQL

Create one persistent PostgreSQL database. One database is enough for all teams because the application isolates teams internally.

Copy the connection string into Render as `DATABASE_URL`.

## 4. Render

Create a Python Web Service from this repository.

Build command:
`pip install -r requirements.txt`

Start command:
`uvicorn bot_main:app --host 0.0.0.0 --port $PORT`

Add:
- TELEGRAM_BOT_TOKEN
- PUBLIC_BASE_URL
- TELEGRAM_WEBHOOK_SECRET
- DATABASE_URL
- APP_SECRET
- TOKEN_ENCRYPTION_KEY
- MAX_FIND_COUNT=30
- REQUEST_TIMEOUT=12
- TIMEZONE_NAME=Africa/Lagos

The Google variables can be added later when you want live deliverability tests.

## 5. First bot test

Open the bot in Telegram and send:

`/start`

Then:

`/newteam Main Team`

Share the invite code with a teammate. They send:

`/join CODE`

Test:

`/find 5 | UAE | fiction | male | email`

Then:

`/stats`

## 6. ChatGPT message workflow

Use your author research with ChatGPT.

Upload an XLSX/CSV back to the bot containing:
- Author or Email
- Subject
- First Message

Then send:

`/queue`

Tap **Open Gmail**, send manually, return to Telegram and tap **Mark Sent**.

## 7. Live deliverability tests

This is optional.

Create a Google OAuth Web Application and enable the Gmail API.

Only request:
`openid email https://www.googleapis.com/auth/gmail.send`

Set callback:
`https://YOUR-RENDER-DOMAIN/oauth/google/callback`

Add to Render:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REDIRECT_URI

Then users can run `/gmail`, connect Gmail and opt an inbox into either the team or global testing pool.

A live test uses one connected sender Gmail to send to up to 10 opted-in testing inboxes. The owners report placement manually in Telegram. The bot does not read their inboxes.
