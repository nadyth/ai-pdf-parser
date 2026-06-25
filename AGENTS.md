# AGENTS.md

Guidance for any AI/LLM agent (and human contributor) working in this repository.
`pdf-parser` is an async, AI-powered PDF parsing service (FastAPI + arq worker + litellm).

## 🛑 Mandatory workflow — read this first

The project's full documentation lives in [`wiki/`](wiki/README.md). It is the source of
truth. You **must** follow this workflow for every task:

1. **Read before you edit.** Before working on any feature or bug, open
   [`wiki/README.md`](wiki/README.md) and read the specific page(s) for the area you are
   touching. Use the area→page map below to find them. **Do not start editing code before
   reading the relevant wiki page(s).**
2. **Follow the playbook.** Use the matching recipe in
   [`wiki/12-feature-playbooks.md`](wiki/12-feature-playbooks.md). It lists the exact files
   to touch for each kind of change.
3. **Update after you edit.** After developing, updating, or removing **any** feature, you
   **must** update the relevant wiki page(s) in the **same** change. A task is **not done**
   until its documentation is current. The policy and per-change checklist are in
   [`wiki/13-wiki-maintenance.md`](wiki/13-wiki-maintenance.md).
4. **Keep companions in sync.** Update [`README.md`](README.md) when user-facing behavior
   changes and [`.env.example`](.env.example) when configuration changes.

If you only do one thing: **read the wiki before, update the wiki after.**

## Area → wiki page map

| If you are changing… | Read & update |
| -------------------- | ------------- |
| API endpoints (`app/api/v1/`) / schemas (`app/schemas/`) | [04-api-reference](wiki/04-api-reference.md) |
| DB models (`app/db/models.py`) | [03-data-model](wiki/03-data-model.md) |
| PDF pipeline (`app/services/pdf/`) | [06-parsing-pipeline](wiki/06-parsing-pipeline.md) |
| Prompts / rule & section logic | [06](wiki/06-parsing-pipeline.md), [07-rules-and-extraction](wiki/07-rules-and-extraction.md) |
| Model routing (`app/core/router.py`, `app/config/model_routes.yaml`) | [08-model-routing](wiki/08-model-routing.md) |
| Worker / queue / callbacks (`app/tasks/`, `app/services/webhooks.py`) | [09-background-jobs-and-webhooks](wiki/09-background-jobs-and-webhooks.md) |
| Settings / env vars (`app/core/settings.py`, `.env.example`) | [10-configuration](wiki/10-configuration.md) |
| UI (`app/ui/`) | [05-ui](wiki/05-ui.md) |
| Build / deploy / migrations / tooling | [11-development](wiki/11-development.md) |

Architecture overview and the full layout: [01-overview](wiki/01-overview.md),
[02-architecture](wiki/02-architecture.md).

## Quick commands

```bash
uv sync                                       # install deps
uv run uvicorn app.main:app --reload          # API (http://localhost:8000)
uv run arq app.tasks.worker.WorkerSettings    # background worker (needs Redis)
uv run pytest -q                              # tests
uv run ruff check . && uv run mypy app        # lint + type-check
uv run alembic revision --autogenerate -m "…" # new migration
uv run alembic upgrade head                   # apply migrations
```

## Definition of done

- [ ] Code compiles; `ruff` + `mypy` clean; `pytest` passes.
- [ ] Alembic migration added if the schema changed.
- [ ] `.env.example` updated if config changed.
- [ ] **Relevant `wiki/` page(s) updated** (see the map above).
- [ ] `README.md` updated if user-facing behavior changed.

Skipping the wiki update means the task is incomplete. See
[`wiki/13-wiki-maintenance.md`](wiki/13-wiki-maintenance.md).
