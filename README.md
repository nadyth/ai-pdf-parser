# PDF Parser

Async AI-powered PDF parser. Upload a PDF, get back page-, section-, and content-wise
results via API or UI. Default pipeline: 300dpi render → vision LLM + pdfplumber →
LLM consolidation. Optionally drive structured extraction with a user-defined
Markdown **rule**. Pass a one-shot **`callback_url`** on upload to be notified when
processing completes (retried with exponential backoff).

Sized for **whole-book parsing** (up to `MAX_PAGES=1000`). Pages stream through the
pipeline one at a time and are committed to the DB as soon as they're parsed, so
progress is visible mid-job and the worker is resumable if it crashes.

## 📚 Documentation

Full developer documentation lives in **[`wiki/`](wiki/README.md)** — architecture, data
model, API reference, the parsing pipeline, model routing, jobs/webhooks, configuration,
and step-by-step playbooks for adding/removing/updating features.

**Contributing (humans and LLM agents):** read the relevant wiki page **before** working
on a feature, and **update the wiki in the same change** — a feature is not done until its
docs are current. These rules are enforced by [`AGENTS.md`](AGENTS.md) (and surfaced to
Claude Code via [`CLAUDE.md`](CLAUDE.md)). See
[`wiki/13-wiki-maintenance.md`](wiki/13-wiki-maintenance.md).

## Stack

- **uv** managed Python 3.12+
- **FastAPI** + async **SQLAlchemy** (Postgres in Docker, SQLite for quick local)
- **arq** worker (Redis) for background processing
- **litellm** for LLM calls, behind a YAML `ModelRouter`
  (`app/config/model_routes.yaml` — same pattern as `video-job-runner`)
- **pypdfium2** (PDFium, prebuilt wheels) for page rendering + **pdfplumber** for text/table extraction
- **Jinja2 + HTMX** for a minimal admin UI
- **Alembic** for migrations
- **Docker compose** for a one-command bring-up

## Quick start (Docker)

```bash
cp .env.example .env
# Set OLLAMA_API_KEY (the default vision model is ollama/minimax-m3:cloud)

docker compose up --build
```

- API:    http://localhost:8000/api/v1
- Docs:   http://localhost:8000/docs
- UI:     http://localhost:8000/ui/  (log in with any value from `API_KEYS`)

## Quick start (local, uv)

```bash
uv sync
cp .env.example .env
# Edit .env — switch to sqlite for the simplest setup:
#   DATABASE_URL=sqlite+aiosqlite:///./storage/pdfparser.db
#   REDIS_URL=redis://localhost:6379/0

# Terminal 1: API
uv run uvicorn app.main:app --reload

# Terminal 2: worker (needs Redis running locally)
uv run arq app.tasks.worker.WorkerSettings
```

## Authentication

All API and UI routes require an API key — any value from `API_KEYS` (comma-separated
in `.env`). For the HTTP API send it as a header:

```
X-API-Key: dev-local-key
```

The UI accepts the same key on the login page and stores it in an httponly cookie.

## How parsing works

For every PDF:

1. The original is saved under `STORAGE_ROOT/documents/<id>/original.pdf`.
2. **Up-front** the API counts the pages (`pypdfium2`) and rejects anything
   larger than `MAX_PAGES`. `documents.page_count` is set immediately so the UI
   knows the total before any LLM work starts.
3. Pages are then **streamed**, bounded by `PAGE_CONCURRENCY`. For each page:
   - Render to a 300 DPI PNG (`pages/page_NNNN.png`).
   - `pdfplumber` extracts the text directly from the PDF.
   - The vision route (default `ollama/minimax-m3:cloud`) reads the PNG and
     returns layout-aware text.
   - The text-only consolidation route (default `ollama/glm-5.1:cloud`) merges
     both: vision wins for structure/order, pdfplumber wins for exact tokens.
   - The `Page` row is **committed immediately** with `consolidated_text` so
     `processed_page_count` reflects live progress and the run is resumable.
   - If `KEEP_PAGE_IMAGES=false`, the PNG is deleted after the row is written.
4. When every page is done, all `pages.consolidated_text` are joined to
   `documents.consolidated_text`.
5. If a rule was supplied:
   - When the doc fits in one prompt: the rule is run once over the full text.
   - When it doesn't (> `RULE_CHUNK_PAGES` pages): the rule is run **per chunk**,
     and outputs are merged (lists concatenate; dicts shallow-merge).
   - Top-level arrays are fanned out as **sections** for chapter-/item-wise browsing.
6. If the upload included `callback_url`, a one-shot POST is fired with the
   document id and a small payload (`document.completed` or `document.failed`).
   Retried with exponential backoff up to `WEBHOOK_MAX_RETRIES`. Each attempt is
   recorded in `callback_deliveries` and is queryable.

### Resume semantics

- The worker job is bounded by `PARSE_JOB_TIMEOUT_SECONDS` (default 6 h).
- If a job crashes mid-book, the next time `parse_document` runs for the same
  document it **skips pages that already have `consolidated_text`**, picking up
  where it left off.
- `POST /documents/{id}/reprocess` defaults to **resume** mode. Pass
  `?force=true` to wipe prior pages/sections and start over.
- Transient LLM errors (429, 5xx, timeouts) are retried per call with
  exponential backoff (`LLM_MAX_ATTEMPTS`, `LLM_BACKOFF_BASE_SECONDS`).

## Rules

A rule is **just markdown** describing what the PDF is and how to extract it.
Be as explicit as you want — sections to skip, columns to merge, schema to follow.
A typical example:

```markdown
# Two-column question paper

The PDF is a question paper with English on the **left column** and Hindi on the
**right column**.

- Ignore the cover page and any instructions section.
- Start parsing from the first numbered question.
- For each question return an object with:
  - `number` (int)
  - `english` (string)
  - `hindi` (string)
- Return a JSON array. Do not include surrounding prose or code fences.
```

You can override the model for a single rule with `model_override`
(e.g. `ollama/qwen2.5vl:cloud`) or pick a named route via `model_route`.

## API surface

Everything is under `/api/v1` and visible at `/docs`.

### Documents

| Method | Path                                            | Purpose                                |
| ------ | ----------------------------------------------- | -------------------------------------- |
| POST   | `/documents`                                    | Upload PDF (multipart) + optional `rule_id`, `callback_url`, `callback_secret` |
| GET    | `/documents`                                    | List documents (filter by `status`)    |
| GET    | `/documents/{id}`                               | Document detail + consolidated text + `processed_page_count` |
| DELETE | `/documents/{id}`                               | Delete document + artifacts            |
| POST   | `/documents/{id}/reprocess?force={bool}`        | Resume parsing (default) or wipe + restart with `force=true` |
| GET    | `/documents/{id}/content`                       | Full consolidated text + rule output   |
| GET    | `/documents/{id}/pages`                         | All pages                              |
| GET    | `/documents/{id}/pages/{index}`                 | One page (0-based)                     |
| GET    | `/documents/{id}/pages/{index}/image`           | 300dpi PNG                             |
| GET    | `/documents/{id}/sections`                      | Rule-extracted sections                |
| GET    | `/documents/{id}/sections/{order}`              | One section                            |
| GET    | `/documents/{id}/callbacks`                     | Callback delivery attempts             |

### Rules (full CRUD)

`POST/GET/PATCH/DELETE /rules[/{id}]` — markdown body, optional `model_route`,
`model_override`, `output_schema`.

### Callbacks

Pass `callback_url` (and optionally `callback_secret`) when uploading. On
completion or failure the system POSTs:

```json
{
  "event": "document.completed",
  "document_id": "…",
  "data": { "page_count": 12, "has_rule_output": true }
}
```

with `X-Event` and (if a secret was set) `X-Signature-Sha256` (HMAC-SHA256 of the
body). Non-2xx responses are retried with exponential backoff (2s, 4s, 8s, …)
up to `WEBHOOK_MAX_RETRIES`. Each attempt is logged.

## Model routing

`app/config/model_routes.yaml` defines providers and per-task routes. Resolution
order: explicit model override → named route override → task default → `_default`.
Mirrors `video-job-runner/app/config/model_routes.yaml`.

The primary vision model is `ollama/minimax-m3:cloud`. Swap models by editing the
YAML or by setting `model_override` on a rule.

## Migrations

Schema is auto-created at startup for dev convenience. For production:

```bash
uv run alembic revision --autogenerate -m "init"
uv run alembic upgrade head
```

## Layout

```
app/
  api/v1/         documents.py, rules.py, health.py
  config/         model_routes.yaml
  core/           settings.py, security.py, router.py, logging.py
  db/             base.py, models.py
  schemas/        Pydantic models
  services/       storage.py, webhooks.py, pdf/{pipeline,plumber,render,llm,prompts,text}.py
  tasks/          arq worker + parse_document + deliver_callback
  ui/             Jinja templates + static
  main.py         FastAPI factory
alembic/          migrations env
Dockerfile
docker-compose.yml
```

A fully annotated layout and deeper architecture notes are in
[`wiki/01-overview.md`](wiki/01-overview.md) and
[`wiki/02-architecture.md`](wiki/02-architecture.md).
