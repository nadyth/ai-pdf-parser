from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging import log
from app.core.settings import get_settings
from app.services.pdf import llm, plumber, prompts, render


@dataclass
class PageResult:
    index: int
    plumber_text: str
    vision_text: str
    consolidated_text: str
    image_path: Path


PageCallback = Callable[[PageResult], Awaitable[None]]
"""Called once per completed page so the caller can commit state immediately."""

SkipCheck = Callable[[int], Awaitable[bool]]
"""Return True to skip a page index (resume support)."""


async def _process_one_page(
    pdf_path: Path,
    pages_dir: Path,
    index: int,
) -> PageResult:
    image_path = await render.render_page(pdf_path, pages_dir, index)
    plumber_text = await plumber.extract_page_text(pdf_path, index)

    vision_text = ""
    try:
        vision_text = await llm.vision(
            "page_vision", prompts.PAGE_VISION_PROMPT, image_path
        )
    except Exception as e:
        log.warning("vision_failed", page=index, error=str(e))

    consolidated = plumber_text
    if vision_text:
        try:
            prompt = prompts.CONSOLIDATION_PROMPT_TEMPLATE.format(
                vision_text=vision_text,
                plumber_text=plumber_text,
            )
            consolidated = await llm.chat(
                "consolidation",
                [{"role": "user", "content": prompt}],
            )
        except Exception as e:
            log.warning("consolidation_failed", page=index, error=str(e))
            consolidated = vision_text or plumber_text

    return PageResult(
        index=index,
        plumber_text=plumber_text,
        vision_text=vision_text,
        consolidated_text=consolidated,
        image_path=image_path,
    )


async def stream_pages(
    pdf_path: Path,
    pages_dir: Path,
    n_pages: int,
    *,
    max_concurrency: int = 4,
    on_page_complete: PageCallback | None = None,
    skip_check: SkipCheck | None = None,
) -> int:
    """Process pages one at a time, bounded by max_concurrency.

    For each page (except those filtered by skip_check) we render → extract →
    vision → consolidate, then invoke on_page_complete so the caller can
    persist. Returns the count of pages actually processed (excluding skipped).
    """
    sem = asyncio.Semaphore(max_concurrency)
    processed = 0
    processed_lock = asyncio.Lock()

    async def _one(idx: int) -> None:
        nonlocal processed
        if skip_check and await skip_check(idx):
            return
        async with sem:
            result = await _process_one_page(pdf_path, pages_dir, idx)
        if on_page_complete:
            await on_page_complete(result)
        async with processed_lock:
            processed += 1

    await asyncio.gather(*(_one(i) for i in range(n_pages)))
    return processed


# ── Rule extraction ────────────────────────────────────────────────────────


def _parse_rule_json(raw: str) -> Any:
    s = raw.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _build_page_block(page_index: int, text: str) -> str:
    return f"# Page {page_index + 1}\n\n{text}"


async def apply_rule(
    pages: list[PageResult],
    *,
    rule_md: str,
    rule_model_route: str | None = None,
    rule_model_override: str | None = None,
) -> tuple[Any, str]:
    """Run a rule against all pages. Returns (parsed_output, full_text).

    If pages span more than `rule_chunk_pages`, the rule is run per chunk and
    results are merged: lists concatenate, dicts shallow-merge.
    """
    s = get_settings()
    pages_sorted = sorted(pages, key=lambda p: p.index)
    full_text = "\n\n".join(
        _build_page_block(p.index, p.consolidated_text) for p in pages_sorted
    )

    if len(pages_sorted) <= s.rule_chunk_pages:
        raw = await llm.chat(
            "rule_extraction",
            [
                {
                    "role": "user",
                    "content": prompts.RULE_EXTRACTION_PROMPT_TEMPLATE.format(
                        rule_md=rule_md, document_text=full_text
                    ),
                }
            ],
            override_model=rule_model_override,
            route_name=rule_model_route,
        )
        return _parse_rule_json(raw), full_text

    # Chunked path
    chunk_size = s.rule_chunk_pages
    chunks: list[list[PageResult]] = [
        pages_sorted[i : i + chunk_size] for i in range(0, len(pages_sorted), chunk_size)
    ]
    total = len(chunks)
    log.info("rule_extraction_chunked", chunks=total, pages=len(pages_sorted))

    chunk_outputs: list[Any] = []
    for ci, chunk in enumerate(chunks):
        chunk_text = "\n\n".join(
            _build_page_block(p.index, p.consolidated_text) for p in chunk
        )
        prompt = prompts.CHUNKED_RULE_EXTRACTION_PROMPT_TEMPLATE.format(
            rule_md=rule_md,
            chunk_idx=ci + 1,
            total_chunks=total,
            page_start=chunk[0].index + 1,
            page_end=chunk[-1].index + 1,
            chunk_text=chunk_text,
        )
        try:
            raw = await llm.chat(
                "rule_extraction",
                [{"role": "user", "content": prompt}],
                override_model=rule_model_override,
                route_name=rule_model_route,
            )
            chunk_outputs.append(_parse_rule_json(raw))
        except Exception as e:
            log.error("rule_chunk_failed", chunk=ci + 1, error=str(e))
            chunk_outputs.append({"_error": str(e)[:500]})

    merged = _merge_chunk_outputs(chunk_outputs)
    return merged, full_text


def _merge_chunk_outputs(outputs: list[Any]) -> Any:
    """Concat lists, shallow-merge dicts, else preserve as `_chunks`."""
    if not outputs:
        return None
    if all(isinstance(o, list) for o in outputs):
        flat: list[Any] = []
        for o in outputs:
            flat.extend(o)
        return flat
    if all(isinstance(o, dict) for o in outputs):
        merged: dict[str, Any] = {}
        for o in outputs:
            merged.update(o)
        return merged
    return {"_chunks": outputs}
