# 13 · Wiki maintenance

> **Policy:** No feature is "done" until its documentation is updated. After developing,
> updating, or removing **any** feature, you **must** update the relevant wiki page(s) in
> the **same** change set. This applies to humans and LLM agents alike, and is enforced by
> [`../AGENTS.md`](../AGENTS.md).

## Why this exists

This wiki is the onboarding path for every future contributor and LLM agent. If code and
docs drift, the wiki becomes actively misleading — worse than no docs, because agents will
trust stale instructions. Keeping them in lockstep is cheap when done per-change and
expensive to fix later.

## When to update

Update the wiki whenever you:

- Add, change, or remove an API or UI route.
- Add, change, or remove a DB model/column or an enum value.
- Change the parsing pipeline, a prompt, or rule/section behavior.
- Add a provider, route, or change model selection / resolution.
- Add, rename, or remove a setting / env var.
- Add a job or webhook event, or change retry/backoff behavior.
- Change build/run/deploy/test workflow.

If you're unsure whether a change is "big enough" — update the wiki. It's a few minutes.

## What to update — code area → wiki page

| You changed… | Update these pages |
| ------------ | ------------------ |
| `app/api/v1/*`, `app/schemas/*` | [04 · API reference](04-api-reference.md) |
| `app/ui/*` | [05 · UI](05-ui.md) |
| `app/db/models.py`, enums | [03 · Data model](03-data-model.md) |
| `app/services/pdf/*` (pipeline/render/plumber/llm) | [06 · Parsing pipeline](06-parsing-pipeline.md) |
| `app/services/pdf/prompts.py`, rule/section logic | [06](06-parsing-pipeline.md), [07 · Rules & extraction](07-rules-and-extraction.md) |
| `app/config/model_routes.yaml`, `app/core/router.py` | [08 · Model routing](08-model-routing.md) |
| `app/tasks/*`, `app/services/webhooks.py` | [09 · Background jobs & webhooks](09-background-jobs-and-webhooks.md) |
| `app/core/settings.py`, `.env.example` | [10 · Configuration](10-configuration.md) |
| `Dockerfile`, `docker-compose.yml`, `alembic/`, tooling | [11 · Development](11-development.md) |
| A new *way* to extend the system | [12 · Feature playbooks](12-feature-playbooks.md) |
| Anything user-facing | also `../README.md` |

Also: if you add/rename/remove a wiki page, update the table of contents and the area→page
map in the [wiki index](README.md).

## Per-change checklist

Copy this into your PR/commit description and tick it:

```
- [ ] Code change complete; ruff + mypy clean; tests pass
- [ ] Alembic migration added (if schema changed)
- [ ] .env.example updated (if config changed)
- [ ] Relevant wiki page(s) updated (see area→page map)
- [ ] README.md updated (if user-facing behavior changed)
- [ ] wiki/README.md TOC/area-map updated (if pages added/removed/renamed)
```

## Diagram convention

When adding or editing a mermaid diagram, precede it with the skip marker so LLM readers
know it is optional:

````markdown
<!-- human-readable diagram; LLMs may skip -->
```mermaid
...
```
````

Keep diagrams faithful to the prose; if they disagree, the prose + code win — fix the
diagram.

## Style for wiki edits

- Prefer tables and short prose over long narrative.
- Link to source files with relative paths (e.g. `../app/tasks/parse.py`) so references are
  clickable and verifiable.
- Keep each page focused on its topic; cross-link rather than duplicate.
- When you cite a value (default, limit, model name), make sure it matches the code.
