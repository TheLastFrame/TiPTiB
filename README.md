# TiPTiB

Today I plan, Tomorrow I buy.

TiPTiB is a small self-hosted app for wishlists, buy plans, priority ranking, manual price estimates, and virtual savings. It is intentionally not a banking or accounting app: saving accounts are just labels for where money is meant to sit in the real world.

## Features

- Multi-user login with private, isolated user data.
- Wishlists with ranked items and lifecycle statuses: `idea`, `planned`, `saving`, `ready`, `bought`, `skipped`.
- Categories, price min/avg/max, actual price, notes, and links.
- Manual virtual deposits and per-item recurring savings rules.
- Named saving accounts such as Cash, ING Savings, or Envelope.
- Mobile-first responsive UI with custom CSS and an installable PWA shell.
- Dedicated history view for bought and skipped items.
- User preferences for currency/timezone and password changes from settings.
- SQLite by default, PostgreSQL-ready through `TIPTIB_DATABASE_URL`.
- Alembic migrations run on startup by default.

## Sorting Rules

Wishlist item sorting uses explicit price fallbacks:

- `max price`: max, then average, then actual, then min.
- `actual price`: actual, then average, then min, then max.
- `rank`: manual rank.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` and create the first admin user.

## Docker

Docker Compose stores the SQLite database in a named volume mounted at `/app/data`:

```powershell
$env:TIPTIB_SECRET_KEY = $(python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up --build
```

The app will be available at `http://127.0.0.1:8000`.

For a plain Docker run, mount `/app/data` yourself so the database survives container replacement:

```powershell
docker build -t tiptib .
docker volume create tiptib-data
docker run --rm -p 8000:8000 `
  -e TIPTIB_SECRET_KEY="<unique random value, 32+ chars>" `
  -v tiptib-data:/app/data `
  tiptib
```

## Configuration

Copy `.env.example` to `.env` or set environment variables:

- `TIPTIB_DATABASE_URL`
- `TIPTIB_SECRET_KEY` (required for Docker and production; use a unique random value with at least 32 characters)
- `TIPTIB_ENVIRONMENT` (`development` or `production`)
- `TIPTIB_ALLOWED_HOSTS` (comma-separated hostnames; required without `*` in production)
- `TIPTIB_SESSION_COOKIE_SECURE` (`true` behind HTTPS, `false` only for local HTTP)
- `TIPTIB_ALLOW_WEB_SETUP` (`false` by default in production)
- `TIPTIB_DEFAULT_CURRENCY`
- `TIPTIB_DEFAULT_TIMEZONE`
- `TIPTIB_RUN_MIGRATIONS_ON_STARTUP` (`true` by default)
- `TIPTIB_BOOTSTRAP_USERNAME`
- `TIPTIB_BOOTSTRAP_PASSWORD`

## Public Deployment

Run TiPTiB behind an HTTPS reverse proxy such as Caddy, Nginx, Traefik, or Cloudflare Tunnel, and preserve the original `Host` header. In production mode the app refuses default or short secrets, requires explicit allowed hosts, sends secure session cookies, emits security headers, and blocks first-run web setup unless you either provide bootstrap credentials or intentionally set `TIPTIB_ALLOW_WEB_SETUP=true`.

For a public instance, set at least:

```powershell
$env:TIPTIB_ENVIRONMENT = "production"
$env:TIPTIB_SECRET_KEY = "<unique random value, 32+ chars>"
$env:TIPTIB_ALLOWED_HOSTS = "tiptib.example.com"
$env:TIPTIB_SESSION_COOKIE_SECURE = "true"
$env:TIPTIB_BOOTSTRAP_USERNAME = "admin"
$env:TIPTIB_BOOTSTRAP_PASSWORD = "<long admin password>"
```

## Tests

```powershell
pytest
```
