# Author Scout Web

Static Vite/React dashboard for Author Scout.

## Architecture

- Vercel: dashboard UI
- Render: Author Scout API and long-running background workers
- Neon: persistent shared database
- Telegram: companion interface and /webkey generation

## Vercel

Import the repository into Vercel and set the project Root Directory to `web`.

No environment variables are required for the default production backend. To point the UI at another backend, set:

`VITE_API_BASE_URL=https://your-backend.example.com`

## Login

In Telegram, run `/webkey`. Paste the signed access key into the web dashboard.
