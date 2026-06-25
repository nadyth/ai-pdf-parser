# 11 · Development

How to run, test, and extend the project locally and in Docker.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`.python-version` pins the version).
- Redis running locally (for the worker) — or use Docker Compose, which provides it.
- A provider API key (default config uses `OLLAMA_API_KEY`).

## Local setup (uv)

```bash
uv sync                       # create .venv and install deps (incl. dev group)
cp .env.example .env
# For the simplest local DB, edit .env:
#   DATABASE_URL=sqlite+aiosqlite:///./storage/pdfparser.db
#   REDIS_URL=redis://localhost:6379/0
# Set OLLAMA_API_KEY (or whichever provider you route to).
```

Run the two processes in separate terminals:

```bash
# Terminal 1 — API (auto-reload)
uv run uvicorn app.main:app --reload
#   or: uv run python main.py   (host 0.0.0.0:8000, reload on)

# Terminal 2 — worker (needs Redis up)
uv run arq app.tasks.worker.WorkerSettings
```

Endpoints:

- API: <http://localhost:8000/api/v1>
- Swagger: <http://localhost:8000/docs> · ReDoc: <http://localhost:8000/redoc>
- UI: <http://localhost:8000/ui/> (log in with any value from `API_KEYS`)

> The API auto-creates tables at startup, so you can start without running migrations.

## Docker Compose

```bash
cp .env.example .env          # set OLLAMA_API_KEY
docker compose up --build
```

Brings up `postgres`, `redis`, `api`, and `worker` (see
[`docker-compose.yml`](../docker-compose.yml)). The `api` and `worker` share the build
([`Dockerfile`](../Dockerfile), a 2-stage uv build → slim runtime) and a `storage` volume.
`DATABASE_URL`/`REDIS_URL`/`STORAGE_ROOT` are injected to point at the compose services.

## Tests

```bash
uv run pytest -q
```

- Config: `pyproject.toml` → `[tool.pytest.ini_options] asyncio_mode = "auto"` (async
  tests need no decorator).
- Current coverage is minimal: [`tests/test_router.py`](../tests/test_router.py) exercises
  `ModelRouter` resolution. **Add tests alongside new features**, especially pure logic
  like merge/parse helpers in `pipeline.py` and router changes.

## Linting & types

```bash
uv run ruff check .           # lint (E,F,I,B,UP,W; line length 100)
uv run ruff format .          # format
uv run mypy app               # type-check
```

Config lives in `pyproject.toml` (`[tool.ruff]`, `[tool.ruff.lint]`).

## Migrations (Alembic)

Tables auto-create at startup for dev convenience. For production / schema changes:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

`alembic/env.py` imports `Base` and `app.db.models` and reads `DATABASE_URL` from
settings, so autogenerate sees the current models. Generated files land in
`alembic/versions/` (empty initially). Commit migrations with the model change.

## Conventions observed in this codebase

- `from __future__ import annotations` at the top of every module.
- Type hints everywhere; modern union syntax (`str | None`).
- Async throughout: async SQLAlchemy sessions (`SessionLocal`), `asyncio.to_thread` for
  blocking PDF work, `httpx.AsyncClient` for webhooks.
- Settings accessed via `get_settings()`; storage via `get_storage()`; the model router
  via `get_router()`; the arq pool via `get_queue()` — all lazy singletons / factories.
- Logging is structured (`structlog`): `log.info("event_name", key=value)` — event name
  first, then keyword fields. Avoid f-string log messages.
- Persist only NUL-clean text: pass strings through `clean_text` / `clean_jsonable`
  before writing to the DB.
- New API request/response shapes go in `app/schemas/`, not ad-hoc dicts.

## Where things are

See [01 · Overview](01-overview.md#repository-layout) for the full layout and the
[wiki index](README.md) area→page map to find the right docs before you change code.
