# 10 · Configuration

All configuration is environment-driven via **pydantic-settings**
([`app/core/settings.py`](../app/core/settings.py)). Values load from the process
environment and a local `.env` file ([`.env.example`](../.env.example) is the documented
template). Unknown env vars are ignored (`extra="ignore"`).

`get_settings()` is `@lru_cache`-d — settings are read **once per process**. Changing env
vars requires a restart.

## Environment variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `APP_NAME` | `pdf-parser` | App name |
| `APP_ENV` | `dev` | Environment label (logged at startup) |
| `LOG_LEVEL` | `INFO` | Log level for `structlog`/stdlib logging |
| `API_KEYS` | `dev-local-key` | **Comma-separated** keys gating API + UI |
| `DATABASE_URL` | `sqlite+aiosqlite:///./storage/pdfparser.db` | Async SQLAlchemy URL |
| `REDIS_URL` | `redis://localhost:6379/0` | arq broker |
| `STORAGE_ROOT` | `./storage` | Root for PDFs + rendered pages (auto-created) |
| `PDF_RENDER_DPI` | `300` | Page render resolution |
| `MAX_UPLOAD_BYTES` | `2147483648` (2 GiB) | Hard upload size limit |
| `MAX_PAGES` | `1000` | Reject PDFs with more pages |
| `PAGE_CONCURRENCY` | `4` | Parallel in-flight pages in the pipeline |
| `KEEP_PAGE_IMAGES` | `true` | Keep rendered PNGs (else delete per page) |
| `RULE_CHUNK_PAGES` | `40` | Chunk rule extraction past this many pages |
| `LLM_MAX_ATTEMPTS` | `5` | Per-LLM-call retry attempts |
| `LLM_BACKOFF_BASE_SECONDS` | `2.0` | LLM retry backoff base |
| `PARSE_JOB_TIMEOUT_SECONDS` | `21600` (6h) | arq `parse_document` timeout |
| `WEBHOOK_TIMEOUT_SECONDS` | `10.0` | Per callback POST timeout |
| `WEBHOOK_MAX_RETRIES` | `5` | Max callback delivery attempts |
| `WEBHOOK_BACKOFF_BASE_SECONDS` | `2.0` | Callback backoff base (capped 300s) |
| `MODEL_ROUTES_PATH` | *(unset)* | Override path to `model_routes.yaml` |

### Provider API keys

Read at route-resolution time based on each provider's `api_key_env` in
[`model_routes.yaml`](../app/config/model_routes.yaml):

| Variable | Provider |
| -------- | -------- |
| `OLLAMA_API_KEY` | ollama (default vision + text models) |
| `OPENAI_API_KEY` | openai |
| `ANTHROPIC_API_KEY` | anthropic |
| `GEMINI_API_KEY` | gemini |
| `MISTRAL_API_KEY` | mistral |

Only the keys for providers you actually route to need values. The default config uses
`ollama`, so set `OLLAMA_API_KEY`.

## Notes & validators

- `API_KEYS` accepts a comma-separated string and is split into a list (`_split_keys`).
- `STORAGE_ROOT` is created on load (`_ensure_storage`).
- Booleans (`KEEP_PAGE_IMAGES`) accept `true/false/1/0` etc. (pydantic parsing).

## Database choice

| Mode | `DATABASE_URL` |
| ---- | -------------- |
| Local quick start | `sqlite+aiosqlite:///./storage/pdfparser.db` |
| Docker / production | `postgresql+asyncpg://pdf:pdf@postgres:5432/pdfparser` |

The `JsonType` decorator transparently uses `JSONB` on Postgres and `JSON` on SQLite, so
models work on both. Postgres is recommended for anything beyond local experimentation.

## Storage layout

Under `STORAGE_ROOT`:

```
storage/
  documents/
    <document_id>/
      original.pdf          # the uploaded file
      filename.txt          # original filename hint
      pages/
        page_0000.png       # rendered pages (removed if KEEP_PAGE_IMAGES=false)
        page_0001.png
        ...
```

Deleting a document removes its `documents/<id>/` directory (`LocalStorage.delete_doc`).

## Adding a new setting

1. Add the field (with a default) to `Settings` in `app/core/settings.py`.
2. Document it in [`.env.example`](../.env.example).
3. Add a row to the table above.
4. Use it via `get_settings().<field>`.

Follow the "Add a config/env var" recipe in [12 · Feature playbooks](12-feature-playbooks.md).
