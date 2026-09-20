# Author Scout Web

Static Vite/React dashboard for Author Scout.

## Architecture

- Vercel: dashboard UI
- Render: Author Scout API and long-running background workers
- Neon: persistent shared database
- Telegram: companion interface, /webkey generation and Gmail connection

## What the dashboard includes

- Overview
- Research jobs
- Verified Authors
- Messages / Outreach
- LinkedIn Connection Intelligence
- System / source-index status

The Messages workspace uses the same message records and Gmail connection as Telegram. It supports reviewing outreach, opening a prefilled Gmail compose window, Auto Send through a connected Gmail account, Mark Sent, and Mark Replied.

## Vercel deployment

1. In Vercel, choose Add New → Project.
2. Import the GitHub repository:
   `damolax/author-scout-team-bot`
3. Set Root Directory to:
   `web`
4. Vercel should detect Vite automatically.
5. Leave the default install/build settings.
6. No environment variable is required for the current production backend because the frontend defaults to:
   `https://author-scout-team-bot.onrender.com`
7. Click Deploy.

If you later use another backend, add this Vercel environment variable:

`VITE_API_BASE_URL=https://your-backend.example.com`

## Login

In Telegram, run:

`/webkey`

Copy the signed key and paste it into the web dashboard login screen.

## Gmail

To enable Auto Send, connect Gmail from Telegram first:

`/gmail`

The web dashboard will automatically detect the connected Gmail account for the same Telegram user.
