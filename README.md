# TiPTiB

Today I plan, Tomorrow I buy.

TiPTiB is a small self-hosted app for wishlists, buy plans, priority ranking, manual price estimates, and virtual savings. It is intentionally not a banking or accounting app: saving accounts are just labels for where money is meant to sit in the real world.

## Features

- Multi-user login with private, isolated user data.
- Wishlists with ranked items and lifecycle statuses: `idea`, `planned`, `saving`, `ready`, `bought`, `skipped`.
- Categories, price min/avg/max, actual price, notes, and links.
- Manual virtual deposits and per-item recurring savings rules.
- Named saving accounts such as Cash, ING Savings, or Envelope.
- Mobile-first responsive UI with installable PWA shell.
- SQLite by default, PostgreSQL-ready through `TIPTIB_DATABASE_URL`.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` and create the first admin user.

## Docker

```powershell
docker compose up --build
```

The app will be available at `http://127.0.0.1:8000`.

## Configuration

Copy `.env.example` to `.env` or set environment variables:

- `TIPTIB_DATABASE_URL`
- `TIPTIB_SECRET_KEY`
- `TIPTIB_DEFAULT_CURRENCY`
- `TIPTIB_DEFAULT_TIMEZONE`
- `TIPTIB_BOOTSTRAP_USERNAME`
- `TIPTIB_BOOTSTRAP_PASSWORD`

## Tests

```powershell
pytest
```
