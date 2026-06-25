# 12 · Feature playbooks

Step-by-step recipes for the common ways this project changes. **Each recipe ends with
updating the wiki** — that step is mandatory, not optional (see
[13 · Wiki maintenance](13-wiki-maintenance.md) and [`../AGENTS.md`](../AGENTS.md)).

> Before starting any recipe: read the relevant wiki page(s) using the area→page map in
> the [wiki index](README.md).

---

## Add or modify an API endpoint

1. **Schema** — add/adjust the request & response models in `app/schemas/` (reuse
   `ORMModel`/`ConfigDict(from_attributes=True)` for ORM-backed responses).
2. **Route** — add the handler to the right router in `app/api/v1/` (`documents.py`,
   `rules.py`, or a new module). Match existing style: `response_model=`, a `summary=`,
   and `db: AsyncSession = Depends(db_session)`.
3. **Auth** — routers already apply `Depends(require_api_key)` at the router level; new
   routes inherit it. A brand-new router must add that dependency and be `include_router`-ed
   in `app/main.py`.
4. **DB access** — query via the injected `AsyncSession`; raise `HTTPException(404, ...)`
   for missing rows. Reuse helpers like `_processed_count` / `_doc_to_out` where relevant.
5. **Test** — add a test if there's non-trivial logic.
6. **Docs** — update [04 · API reference](04-api-reference.md) (and [05](05-ui.md) if the
   UI mirrors it).

*Files:* `app/api/v1/*.py`, `app/schemas/*.py`, `app/main.py`.

---

## Add a DB column or table

1. **Model** — edit/add the SQLAlchemy model in `app/db/models.py`. Use `String(36)`
   UUID PKs, `TimestampMixin`, `JsonType` for JSON, and `ondelete="CASCADE"` +
   `cascade="all, delete-orphan"` for child relations.
2. **Schemas** — expose the new field(s) in the relevant `app/schemas/` models if they
   should appear in API responses.
3. **Migration** — `uv run alembic revision --autogenerate -m "..."` then
   `uv run alembic upgrade head`. Commit the generated file. (Startup auto-create covers
   fresh dev DBs but not existing ones.)
4. **Usage** — update any pipeline/worker code that reads/writes the model; remember to
   `clean_text`/`clean_jsonable` text/JSON before persisting.
5. **Docs** — update [03 · Data model](03-data-model.md) (table + ER/state diagrams).

*Files:* `app/db/models.py`, `app/schemas/*.py`, `alembic/versions/*`.

---

## Add a pipeline stage or change a prompt

1. **Prompt** — edit/add a constant in `app/services/pdf/prompts.py`. Keep `.format()`
   placeholder names intact (callers depend on them).
2. **Stage** — for a new per-page step, extend `_process_one_page` in
   `app/services/pdf/pipeline.py`; for a new model task, call `llm.chat`/`llm.vision` with
   a new task name and add a matching route in `model_routes.yaml` (see next recipe).
3. **Persistence** — if the stage produces new per-page data, add a `Page` column (use the
   DB recipe) and store it in `_persist_page` (`app/tasks/parse.py`).
4. **Concurrency** — remember PDFium calls must stay behind `render._PDFIUM_LOCK`.
5. **Docs** — update [06 · Parsing pipeline](06-parsing-pipeline.md) (and
   [07](07-rules-and-extraction.md) if rules are involved).

*Files:* `app/services/pdf/{pipeline,prompts,llm,render,plumber}.py`, `app/tasks/parse.py`.

---

## Add an LLM provider / route, or swap a model

1. **Provider** — add a `providers.<name>` block to `app/config/model_routes.yaml` with
   `type: litellm`, `api_key_env`, and `base_url`.
2. **Env** — add the `api_key_env` variable to `.env.example` (and your `.env`).
3. **Route** — add/point a `routes.<task>` entry at the provider+model, or just change the
   `model:` on an existing route to swap models.
4. **Per-rule override** — alternatively set `model_route`/`model_override` on a `Rule`.
5. **Test** — extend `tests/test_router.py` if resolution behavior changes.
6. **Docs** — update [08 · Model routing](08-model-routing.md) and the provider-key table
   in [10 · Configuration](10-configuration.md).

*Files:* `app/config/model_routes.yaml`, `.env.example`, `tests/test_router.py`.

---

## Add a new rule output shape / section kind

1. **Prompt** — adjust `RULE_EXTRACTION_PROMPT_TEMPLATE` /
   `CHUNKED_RULE_EXTRACTION_PROMPT_TEMPLATE` if the expected JSON changes.
2. **Merge** — update `_merge_chunk_outputs` in `pipeline.py` if a new top-level shape
   needs special merging.
3. **Sections** — update `_section_fields` in `app/tasks/parse.py` to map new keys to
   `title`/`content`/`data`, or set a different `kind`.
4. **Docs** — update [07 · Rules & extraction](07-rules-and-extraction.md).

*Files:* `app/services/pdf/{prompts,pipeline}.py`, `app/tasks/parse.py`.

---

## Add a config / env var

1. Add the field with a sane default to `Settings` in `app/core/settings.py`.
2. Document it in `.env.example`.
3. Read it via `get_settings().<field>`. (Remember `get_settings()` is cached — restart
   to pick up changes.)
4. **Docs** — add a row to the table in [10 · Configuration](10-configuration.md).

*Files:* `app/core/settings.py`, `.env.example`.

---

## Add a webhook event

1. **Emit** — enqueue `deliver_callback(document_id, "<event>", {...})` where appropriate
   (see how `parse_document` / `_mark_failed` do it in `app/tasks/parse.py`).
2. **Payload** — keep `data` small and JSON-serializable.
3. **Docs** — update the events/payload section of
   [09 · Background jobs & webhooks](09-background-jobs-and-webhooks.md).

*Files:* `app/tasks/parse.py` (or wherever the event originates), `app/tasks/callback.py`,
`app/services/webhooks.py`.

---

## Remove a feature

1. Delete the code (route/model/stage/setting) and any now-dead helpers.
2. For DB removals, add an Alembic migration that drops the column/table.
3. Remove references across schemas, UI, pipeline, and tests.
4. Run `uv run ruff check .` and `uv run mypy app` to catch dangling references.
5. **Docs** — delete or update the corresponding wiki section(s) so nothing documents a
   feature that no longer exists.

---

## Definition of done (every change)

- [ ] Code compiles, `ruff` + `mypy` clean, tests pass (`uv run pytest -q`).
- [ ] Migration added if the schema changed.
- [ ] `.env.example` updated if config changed.
- [ ] **Relevant wiki page(s) updated**, plus `README.md` if user-facing behavior changed.

If you skipped the last box, the task is **not done**. See
[13 · Wiki maintenance](13-wiki-maintenance.md).
