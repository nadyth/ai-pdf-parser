# 04 · API reference

All JSON endpoints live under `/api/v1` and are also browsable at `/docs` (Swagger) and
`/redoc`. Source: [`app/api/v1/`](../app/api/v1/). Response/request shapes are the Pydantic
models in [`app/schemas/`](../app/schemas/).

## Authentication

Every `/api/v1/documents/*` and `/api/v1/rules/*` route requires an API key. `/health` is
open.

- **Header:** `X-API-Key: <one of API_KEYS>` (preferred for API clients).
- **Cookie:** `api_key=<key>` (used by the UI; the same dependency accepts either).

Keys come from the `API_KEYS` env var (comma-separated). Invalid/missing → **401** with
`WWW-Authenticate: ApiKey`. Auth is enforced by `require_api_key`
([`app/core/security.py`](../app/core/security.py)) wired in as a router-level dependency.

## Error shape

- Domain errors raised as `NotFoundError` → **404**, other `AppError` → **400**, both as
  `{"error": "...", "details": {...}}`.
- Most route-level validation uses `HTTPException`, returning FastAPI's default
  `{"detail": "..."}` body.

## Health

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| GET | `/api/v1/health` | none | Liveness — returns `{"status": "ok"}` |

## Documents

Source: [`app/api/v1/documents.py`](../app/api/v1/documents.py). Schemas in
[`app/schemas/document.py`](../app/schemas/document.py) and
[`app/schemas/callback.py`](../app/schemas/callback.py).

### `POST /api/v1/documents` — upload + enqueue

**Body:** `multipart/form-data`

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `file` | file | yes | Must end in `.pdf` |
| `rule_id` | string | no | A `Rule.id` to apply; 404 if unknown |
| `callback_url` | string | no | One-shot completion/failure webhook |
| `callback_secret` | string | no | Enables HMAC-SHA256 signing of the callback |

**Responses:** `201` → `DocumentOut`. `400` non-PDF/empty/invalid. `413`
over `MAX_UPLOAD_BYTES` or `MAX_PAGES`. `404` unknown `rule_id`.

`DocumentOut` fields: `id, filename, size_bytes, page_count, processed_page_count, status,
error, rule_id, callback_url, callback_status, started_at, finished_at, created_at,
updated_at`.

### `GET /api/v1/documents` — list

| Query | Type | Default | Notes |
| ----- | ---- | ------- | ----- |
| `status` | enum | — | Filter by `pending`/`processing`/`completed`/`failed` |
| `limit` | int | 50 | 1–500 |
| `offset` | int | 0 | ≥ 0 |

Returns `list[DocumentOut]`, newest first, each with live `processed_page_count`.

### `GET /api/v1/documents/{id}` — detail

Returns `DocumentDetail` (= `DocumentOut` plus `consolidated_text` and `rule_output`).
`404` if not found.

### `DELETE /api/v1/documents/{id}` — delete

Deletes the row (cascades to pages/sections/callbacks) and removes the storage directory.
`204` on success, `404` if not found.

### `POST /api/v1/documents/{id}/reprocess` — re-enqueue

| Query | Type | Default | Notes |
| ----- | ---- | ------- | ----- |
| `force` | bool | `false` | `true` wipes prior pages + sections + consolidated/rule output before re-running |

Default (`force=false`) **resumes** — keeps done pages and re-enqueues. Resets status to
`pending`, clears `error`/timestamps/`callback_status`, enqueues a fresh `parse_document`
job (timestamped job id). Returns `DocumentOut`. `404` if not found.

### `GET /api/v1/documents/{id}/content`

Returns `DocumentContent`: `{ document_id, consolidated_text, rule_output, page_count }`.

### `GET /api/v1/documents/{id}/pages`

Returns `list[PageOut]` ordered by `index`. `PageOut`: `id, index, plumber_text,
vision_text, consolidated_text, image_path`.

### `GET /api/v1/documents/{id}/pages/{index}`

One page by 0-based `index`. `404` if not found.

### `GET /api/v1/documents/{id}/pages/{index}/image`

Returns the rendered 300 DPI **PNG** (`image/png`). `404` if the page or file is missing
(e.g. when `KEEP_PAGE_IMAGES=false` deleted it).

### `GET /api/v1/documents/{id}/sections`

Returns `list[SectionOut]` ordered by `order`. `SectionOut`: `id, order, kind, title,
content, data, page_start, page_end`. Populated only when a rule produced a top-level
array — see [07](07-rules-and-extraction.md).

### `GET /api/v1/documents/{id}/sections/{order}`

One section by `order`. `404` if not found.

### `GET /api/v1/documents/{id}/callbacks`

Returns `list[CallbackDeliveryOut]` ordered by `attempt` — the webhook audit trail.

## Rules

Source: [`app/api/v1/rules.py`](../app/api/v1/rules.py). Schemas in
[`app/schemas/rule.py`](../app/schemas/rule.py). Full CRUD.

| Method | Path | Body / Notes |
| ------ | ---- | ------------ |
| POST | `/api/v1/rules` | `RuleCreate` → `201 RuleOut`. `409` if name/slug exists. |
| GET | `/api/v1/rules` | `list[RuleOut]`, newest first |
| GET | `/api/v1/rules/{id}` | `RuleOut`; `404` if missing |
| PATCH | `/api/v1/rules/{id}` | `RuleUpdate` (partial); renaming re-slugs |
| DELETE | `/api/v1/rules/{id}` | `204`; `404` if missing |

`RuleCreate` fields: `name` (1–255, required), `description?`, `body_md` (required,
markdown), `model_route?`, `model_override?`, `output_schema?` (JSON object).
`RuleOut` adds `id, slug, created_at, updated_at`.

## Quick examples

```bash
# Upload with a rule and a callback
curl -X POST http://localhost:8000/api/v1/documents \
  -H "X-API-Key: dev-local-key" \
  -F "file=@book.pdf" \
  -F "rule_id=<rule-uuid>" \
  -F "callback_url=https://example.com/hook"

# Poll progress
curl http://localhost:8000/api/v1/documents/<id> -H "X-API-Key: dev-local-key"

# Create a rule
curl -X POST http://localhost:8000/api/v1/rules \
  -H "X-API-Key: dev-local-key" -H "Content-Type: application/json" \
  -d '{"name":"Questions","body_md":"# Extract each question as an object..."}'
```

> When adding or changing an endpoint, update this page **and** follow the
> "Add/modify an API endpoint" recipe in [12 · Feature playbooks](12-feature-playbooks.md).
