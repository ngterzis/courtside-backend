# courtside-backend

Backend API for **Courtside**, a basketball stats app for a recreational league.
Implements the contract defined in [`BACKEND.md`](./BACKEND.md).

## Related repositories

- [**courtside**](https://github.com/ngterzis/courtside) — the client app
- [**courtside-infra**](https://github.com/ngterzis/courtside-infra) — Terraform infrastructure (Aurora, Lambda, API Gateway, Function URL)

## Stack

- **Python 3.12** + **FastAPI** + **Pydantic v2** (camelCase JSON via `alias_generator`)
- **SQLAlchemy 2.0** + **Alembic** — Postgres in Docker locally, Aurora Serverless v2 via the **RDS Data API** in production
- **Custom JWT** (HS256) + **bcrypt** — no Cognito
- **Anthropic SDK**: Haiku 4.5 for archetype prose, Sonnet 4.6 for the tool-using chat agent
- **Langfuse**: LLM tracing, user-feedback scores and eval runs
- **AWS Lambda** + **Lambda Web Adapter** — the same FastAPI app runs locally under uvicorn and inside Lambda
  - `/api/chat` is a separate Lambda behind a Function URL in `RESPONSE_STREAM` mode (SSE)
  - everything else is behind API Gateway REST
- **Terraform** — infra lives in the [`courtside-infra`](https://github.com/ngterzis/courtside-infra) repo

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

Connection mode is env-driven (see `.env.example`):

- default — local Postgres via a `postgresql+psycopg://` URL built from `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`
- `DATABASE_URL` — a full SQLAlchemy URL; wins over the discrete fields (the Fargate migration task uses this)
- `USE_DATA_API=true` — production via the AWS RDS Data API using `DB_CLUSTER_ARN` + `DB_SECRET_ARN` (no VPC required for Lambda)

### Migrations must be backward-compatible

`deploy.yml` migrates *before* it deploys, and rolls the Lambda code back if the
new image fails its health check. A rollback reverts code; it does not revert
the schema. So a migration that the previous code cannot run against turns a
rollback into a second outage rather than a recovery.

Every migration must therefore leave the *previous* release working —
expand/contract, with destructive changes split across two deploys:

| | Deploy 1 | Deploy 2 |
|---|---|---|
| Add a column | add it nullable (or with a default) | start writing it; make it `NOT NULL` |
| Rename a column | add the new one, write both, read the old | backfill, read the new one |
| Drop a column | stop reading and writing it | drop it |

Never combine a destructive DDL change with the code that depends on it in one
deploy.

## Chat agent, observability & evals

> Full write-up of the implementation: [docs/chat-agent.md](docs/chat-agent.md).

`POST /api/chat` is a small tool-using agent. The system prompt carries a compact
player card; everything game-level is fetched through five **read-only,
player-scoped tools** (`services/chat_tools.py`). No tool accepts a player id,
so "never discuss teammates" is enforced in code, not only in the prompt. The
loop (`anthropic_client.stream_chat_events`) streams text from every round over
SSE, sends a `status` event while tools run, returns all of a round's results
in one message, and stops after 5 tool rounds.

### Tracing

Every turn is one [Langfuse](https://langfuse.com) trace (OpenTelemetry under
the hood):

```
chat.turn (agent)          user message → answer, rounds, tool calls, prompt version, user id
├── llm.round.1 (generation)  model, messages, tokens incl. prompt-cache reads, TTFT, stop reason
├── find_games (tool)         arguments → JSON result (ERROR level when the tool failed)
└── llm.round.2 (generation)
```

Tracing turns on when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are set and
is a no-op otherwise. A one-line JSON summary per turn is always logged.
Traces are flushed before the Lambda response ends (after `[DONE]` has been
sent, so a slow exporter never delays the answer). Users rate answers through
`POST /api/chat/feedback`, which records a `user_feedback` score on the trace.

### Offline evals

`evals/` holds 20 cases over a deterministic fixture league: lookups, game
detail, splits, past seasons, policy (teammates, playing time, prompt
injection) and no-data questions. Grading goes cheapest first:

1. **Code checks**: the expected tool was called, the right numbers appear in
   the answer (expected values computed from the fixture, not from the tools),
   no teammate names or numbers leak.
2. **LLM judge** (Haiku 4.5, structured output): grounded in the tool results,
   follows policy, helpfulness 1–5.

```bash
USE_DATA_API=false uv run python -m evals.run --out evals/RESULTS.md
USE_DATA_API=false uv run python -m evals.run --no-tools   # negative control
```

The negative control runs the same cases without tools and should fail. It
caught a lenient judge: the model invented `<tool_response>` text, and the
judge counted it as evidence until its prompt was tightened. With Langfuse keys
set, each run is uploaded as a dataset run named `<prompt version>@<git sha>`
so runs can be compared case by case. Runs cost API credits, so they run on
demand (`Evals` workflow), not on every push.

Latest run:

### Eval run `2026-10-19.tools-v3@acc2c14` (model `claude-sonnet-4-6`)

| Category | Passed | Facts | Grounded | Policy | Helpfulness |
|---|---|---|---|---|---|
| game_detail | 2/2 | 100% | 100% | 100% | 100% |
| lookup | 7/7 | 100% | 100% | 100% | 100% |
| no_data | 2/2 | 100% | 100% | 100% | 100% |
| past_seasons | 2/2 | 100% | 100% | 100% | 100% |
| policy | 4/4 | – | 100% | 100% | 100% |
| splits | 3/3 | 100% | 100% | 100% | 100% |
| **all** | 20/20 | 100% | 100% | 100% | 100% |

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
  services/
    games.py          # a player's performances with their games; get_or_create_game
    chat.py           # player card + cached static system prompt
    chat_tools.py     # read-only DB tools for the chat agent
  anthropic_client.py # Claude calls, chat tool loop
  observability.py    # Langfuse tracing + feedback scores
evals/                # chat eval suite: fixture, cases, graders, runner
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
| POST | `/api/chat` | bearer (SSE) |
| POST | `/api/chat/feedback` | bearer |

More to come — see `BACKEND.md` for the full contract.

## License

[MIT](./LICENSE)
