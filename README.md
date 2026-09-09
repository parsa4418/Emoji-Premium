# Kade Bot — Render + Neon

This version runs the original Telegram bot as a Render Web Service and uses Neon/PostgreSQL instead of Cloudflare D1.

## Render
- Runtime: Node
- Build Command: `npm install`
- Start Command: `npm start`

## Environment Variables
- `BOT_TOKEN` — Telegram bot token
- `ADMIN_ID` — numeric Telegram user ID of the admin
- `ADMIN_SECRET` — long random secret used for `/setup` and Telegram webhook validation
- `DATABASE_URL` — Neon PostgreSQL connection string
- `DB_POOL_MAX` — optional, default `5`

After deploy, open:
`https://YOUR-RENDER-DOMAIN/setup?key=YOUR_ADMIN_SECRET`

The setup endpoint creates the required tables and registers the Telegram webhook.

Health check:
`/health`
