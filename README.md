# courtside-backend

Backend API for **Courtside**, a basketball stats app for a recreational league.
Implements the contract defined in [`BACKEND.md`](./BACKEND.md).

## Stack

- **Python 3.12** + **FastAPI** + **Pydantic v2** (camelCase JSON via `alias_generator`)
- **SQLAlchemy 2.0** + **Alembic** — Postgres in Docker locally, Aurora Serverless v2 via the **RDS Data API** in production
- **Custom JWT** (HS256) + **bcrypt** — no Cognito
- **Anthropic SDK** — Haiku 4.5 for archetype prose, Sonnet 4.6 for chat
- **AWS Lambda** + **Lambda Web Adapter** — the same FastAPI app runs locally under uvicorn and inside Lambda
  - `/api/chat` is a separate Lambda behind a Function URL in `RESPONSE_STREAM` mode (SSE)
  - everything else is behind API Gateway REST
- **Terraform** — infra lives in `infra/` (added later)

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — `brew install uv`
- Docker (for local Postgres)

`uv` manages Python itself; you don't need to install Python 3.12 separately.

## Setup

```bash
# clone, then:
cp .env.example .env
uv sync                       # creates .venv and installs deps (pinned via uv.lock)
docker compose up -d postgres
uv run alembic upgrade head   # apply migrations
```

## Run the API

```bash
uv run uvicorn courtside.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/api/health>
- OpenAPI docs: <http://localhost:8000/docs>

## Tests

```bash
uv run pytest
```

Tests require the local Postgres container to be running. Each test runs in a
transaction that is rolled back at the end (savepoint-based), so state from one
test does not leak into the next.

## Database migrations

```bash
uv run alembic upgrade head             # apply
uv run alembic downgrade base           # roll back to empty
uv run alembic revision --autogenerate -m "your message"
```

`DB_DRIVER` selects the SQLAlchemy dialect:

- `psycopg` (default) — local Postgres via the `postgresql+psycopg://` URL
- `aurora_data_api` — production via AWS RDS Data API (no VPC required for Lambda)

## Project layout

```
src/courtside/
  main.py             # FastAPI app, mounts routers, installs error handlers
  config.py           # Pydantic Settings (env-driven)
  errors.py           # APIError + handlers for the {error, message} envelope
  db/
    session.py        # engine factory (psycopg vs aurora-data-api) + get_db
    models.py         # SQLAlchemy 2.0 models
  schemas/
    base.py           # CamelModel — camelCase JSON via alias_generator
    player.py, auth.py
  routes/
    __init__.py       # CamelRouter — default response_model_by_alias=True
    auth.py, me.py
  auth/
    tokens.py         # JWT sign/verify + bcrypt
    deps.py           # get_current_player FastAPI dependency
alembic/              # migrations
tests/                # pytest suite
docker-compose.yml    # local Postgres
pyproject.toml        # deps managed by uv
```

## Conventions

- **JSON shape** is the source of truth (BACKEND.md). All responses are
  camelCase via Pydantic `alias_generator=to_camel`; `CamelRouter` opts every
  route into `response_model_by_alias=True` so we never forget.
- **Errors** always follow `{ "error": "<code>", "message": "<text>" }`. Raise
  `APIError(status, code, message)` from any route.
- **Multi-tenancy** — every team-scoped row carries `team_id`. We're single-team
  for now; flipping the switch later is a middleware change, not a migration.
- **No comments** unless the *why* is non-obvious. Names should carry the *what*.

## Useful endpoints

| Method | Path | Auth |
|---|---|---|
| GET  | `/api/health` | none |
| POST | `/api/auth/login` | none |
| POST | `/api/auth/logout` | none |
| GET  | `/api/me` | bearer |
| POST | `/api/me/onboard` | bearer |

More to come — see `BACKEND.md` for the full contract.
