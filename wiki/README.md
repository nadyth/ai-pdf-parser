# pdf-parser Wiki

This wiki is the **single source of truth** for how `pdf-parser` is built and how to
change it. It is written for both humans and LLM coding agents.

> ## 🟡 Golden Rule
> 1. **Read before you edit.** Before working on any feature or bug, read this index and
>    the specific page(s) for the area you are touching (see the map below).
> 2. **Follow the playbook.** Use the matching recipe in
>    [12-feature-playbooks.md](12-feature-playbooks.md).
> 3. **Update after you edit.** After developing, updating, or removing **any** feature,
>    you **must** update the relevant wiki page(s) in the same change. A feature is not
>    "done" until its documentation is current. See
>    [13-wiki-maintenance.md](13-wiki-maintenance.md).
>
> This rule is also enforced by [`../AGENTS.md`](../AGENTS.md).

## How to use this wiki (LLM agents)

- Each page is self-contained and focused on one topic. Load only the page(s) relevant to
  your task to save context.
- **Mermaid diagrams are for human readers and can be safely skipped by LLMs.** Every
  diagram is preceded by the marker `<!-- human-readable diagram; LLMs may skip -->`.
- Prose, tables, and code references are authoritative; keep them in sync with the code.

## Table of contents

| #  | Page | What it covers |
| -- | ---- | -------------- |
| 01 | [Overview](01-overview.md) | What the project is, the stack, repo layout, glossary |
| 02 | [Architecture](02-architecture.md) | Runtime topology, request & worker lifecycles |
| 03 | [Data model](03-data-model.md) | DB tables, relationships, status lifecycles |
| 04 | [API reference](04-api-reference.md) | Every `/api/v1` endpoint, params, schemas |
| 05 | [UI](05-ui.md) | Server-rendered admin UI, cookie auth, templates |
| 06 | [Parsing pipeline](06-parsing-pipeline.md) | Render → vision → plumber → consolidation |
| 07 | [Rules & extraction](07-rules-and-extraction.md) | Markdown rules, chunking, sections |
| 08 | [Model routing](08-model-routing.md) | `model_routes.yaml`, providers, resolution order |
| 09 | [Background jobs & webhooks](09-background-jobs-and-webhooks.md) | arq worker, callbacks |
| 10 | [Configuration](10-configuration.md) | Every env var, storage layout, DB choice |
| 11 | [Development](11-development.md) | Setup, running, tests, migrations, conventions |
| 12 | [Feature playbooks](12-feature-playbooks.md) | Step-by-step add/remove/update recipes |
| 13 | [Wiki maintenance](13-wiki-maintenance.md) | The mandatory "keep docs current" policy |

## Area → wiki page map

Use this to find the right page(s) before touching code.

| If you are changing… | Read & update |
| -------------------- | ------------- |
| API endpoints (`app/api/v1/`) | [04](04-api-reference.md), [12](12-feature-playbooks.md) |
| Pydantic schemas (`app/schemas/`) | [04](04-api-reference.md) |
| DB models (`app/db/models.py`) | [03](03-data-model.md), [12](12-feature-playbooks.md) |
| The PDF pipeline (`app/services/pdf/`) | [06](06-parsing-pipeline.md), [07](07-rules-and-extraction.md) |
| Prompts (`app/services/pdf/prompts.py`) | [06](06-parsing-pipeline.md), [07](07-rules-and-extraction.md) |
| Model routing (`app/core/router.py`, `app/config/model_routes.yaml`) | [08](08-model-routing.md) |
| Worker / queue / callbacks (`app/tasks/`, `app/services/webhooks.py`) | [09](09-background-jobs-and-webhooks.md) |
| Settings / env vars (`app/core/settings.py`, `.env.example`) | [10](10-configuration.md) |
| UI (`app/ui/`) | [05](05-ui.md) |
| Auth (`app/core/security.py`) | [04](04-api-reference.md), [05](05-ui.md) |
| Build/deploy (`Dockerfile`, `docker-compose.yml`, `alembic/`) | [11](11-development.md) |
