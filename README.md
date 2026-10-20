# Project Pipeline

Tracks every tile job from the first call until it is done, so nothing
stalls because nobody knew it was their turn.

**First slice — what works now**

- Sign in with Google, `@hstile.com` only. New people wait until an admin sets their role.
- People and companies in one list, with duplicate matching on phone, email and close names, plus a merge tool.
- Jobs created thin (a rep and one named person), renamed freely, with class, lead source and customer-side roles (one owner, one designer… history kept).
- Calls, showroom visits and site visits on one timeline. Scheduled visits that resolve to happened / no-show / cancelled / rescheduled.
- Selection: one flat list of tiles, areas as tags, a decision per area, declined tiles crossed out in place. QR scan of the showroom tags.
- Steps with a named person and a due date. Every event needs a next step; the last open step can't be closed without one. Bad answers land on the rep.
- The rep's morning view: went wrong, today's visits, due now, stuck.
- Every change to every table logged field by field. "The story" and "Everything" on each job.

**NetSuite:** read-only item sync (inventory items, hourly, plus Sync now on the Team screen), and live stock on a stock tile — free and on hand by location and lot (cached 5 minutes).

**Order assembly (first part):** plans and photos on the job (upload, phone camera, Dropbox / Google Drive links pulled in), footage per area with its source and confidence, and the takeoff task (default person on the Team screen; it can't close until every area has footage). Availability per chosen tile: our stock is available only if one lot covers the need; two lots is short until the rep goes ahead with a reason; local and overseas are confirmed by hand; anything short puts a task on the rep. Estimates: pick the areas (each needs footage and a chosen tile), lines are priced from NetSuite Base Price (live), any price can be changed and is marked, with warnings for approximate footage, unchecked or short availability, missing quantities and missing prices. Not yet sent to NetSuite. Files are kept in the database.

**Not yet:** the NetSuite push and read-back,  push notifications, templates, footage and availability, away/gone, offline queue.
The item list is a stand-in table until the sync exists.

## Layout

```
api/     FastAPI + SQLAlchemy + Alembic (Python 3.12)
  app/rules/       the fixed lists and pure rules (matching, QR)
  app/services/    business rules that touch the database
  app/routers/     the HTTP endpoints
  migrations/sql/  the schema, as plain SQL
web/     React + TypeScript, built with esbuild into an installable app
```

One service: FastAPI serves `/api/*` and the built app at `/`.
Every business rule lives in the server. The app only shows data and sends taps.

## Run it locally

Needs Python 3.12, Node 22 and Postgres 16.

```bash
createdb pipeline
cd api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://postgres@localhost:5432/pipeline DEV_LOGIN=1 ADMIN_EMAILS=you@hstile.com SECRET_KEY=dev
alembic upgrade head
python -m scripts.seed_demo        # optional: 21 Mountain Rd demo data
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd web
npm install
npm run dev                        # http://localhost:5173, API proxied to :8000
```

Sign in with the test box using `jay@hstile.com` (seeded rep) or your admin email.

## Tests

```bash
cd api
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres python -m pytest -q
```

Each run creates and drops its own throwaway database. GitHub runs the same tests on every push.

## Deploy on Railway

1. New project → **Deploy from GitHub repo** → this repo. Railway reads `railway.json` and builds the `Dockerfile`.
2. In the same project: **New → Database → PostgreSQL**.
3. On the app service → **Variables**:
   - `DATABASE_URL` → reference the Postgres service's `DATABASE_URL`
   - `SECRET_KEY` → a long random string
   - `GOOGLE_CLIENT_ID` → see below
   - `ALLOWED_DOMAIN` = `hstile.com`
   - `ADMIN_EMAILS` = your email
   - `DEV_LOGIN` = `1` only while testing without Google; remove it after
4. **Settings → Networking → Generate domain.** That address is the app.

Migrations run on every start.

### Sign-in

People sign in with email and password. An admin adds each person on the Team screen with a temporary password, and they pick their own on first sign-in.
Forgotten password: open the person on the Team screen → Reset password. Eight wrong tries lock an account for 15 minutes.
First setup: while `DEV_LOGIN=1`, sign in with Test sign-in, set your own password (Today → bottom of the page), sign out, sign in with it, then set `DEV_LOGIN=0`.

### Google sign-in (optional)

Google Cloud Console → APIs & Services → Credentials → **Create credentials → OAuth client ID** → Web application.
Add the Railway address (and `http://localhost:5173` for local) under **Authorized JavaScript origins**.
Copy the client ID into `GOOGLE_CLIENT_ID`. With the OAuth consent screen set to **Internal**, only `@hstile.com` accounts can use it.

### NetSuite item sync

Read-only. Uses SuiteQL with token-based auth: the existing integration's consumer key and secret, plus an access token made for this app.
Set `NS_ACCOUNT_ID`, `NS_CONSUMER_KEY`, `NS_CONSUMER_SECRET`, `NS_TOKEN_ID`, `NS_TOKEN_SECRET` on Railway (never in the repo).
The token's role needs **REST Web Services** and **SuiteAnalytics Workbook**, plus view access to items.
The first run is a full copy, about a minute after start; then changes every `NS_SYNC_MINUTES` (default 60), and a full copy again once a day.
Status and a **Sync now** button are on the Team screen.

### Phones

Open the address in Chrome on Android → menu → **Add to Home screen**.
If staff phones are content-filtered, have the Railway address and `accounts.google.com` whitelisted first.
