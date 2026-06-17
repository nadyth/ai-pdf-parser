from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.logging import log
from app.core.settings import get_settings
from app.db.base import SessionLocal
from app.db.models import CallbackStatus, Document, DocumentStatus, Page, Rule, Section
from app.services.pdf import pipeline, render
from app.services.pdf.pipeline import PageResult
from app.services.pdf.text import clean_jsonable, clean_text
from app.services.storage import get_storage


async def _set_page_count(document_id: str, n_pages: int) -> None:
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc:
            doc.page_count = n_pages
            await db.commit()


async def _load_done_pages(document_id: str) -> set[int]:
    """Return indexes of pages that already have consolidated_text saved."""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Page.index).where(
                    Page.document_id == document_id,
                    Page.consolidated_text.is_not(None),
                )
            )
        ).all()
        return {r[0] for r in rows}


async def _persist_page(document_id: str, result: PageResult, keep_image: bool) -> None:
    """Insert (or update) the Page row immediately, then optionally drop the PNG."""
    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(Page).where(
                    Page.document_id == document_id, Page.index == result.index
                )
            )
        ).scalar_one_or_none()
        plumber_t = clean_text(result.plumber_text)
        vision_t = clean_text(result.vision_text)
        consolidated_t = clean_text(result.consolidated_text)
        if existing is None:
            db.add(
                Page(
                    document_id=document_id,
                    index=result.index,
                    plumber_text=plumber_t,
                    vision_text=vision_t,
                    consolidated_text=consolidated_t,
                    image_path=str(result.image_path) if keep_image else None,
                )
            )
        else:
            existing.plumber_text = plumber_t
            existing.vision_text = vision_t
            existing.consolidated_text = consolidated_t
            existing.image_path = str(result.image_path) if keep_image else None
        await db.commit()

    if not keep_image:
        try:
            os.remove(result.image_path)
        except OSError:
            pass


async def parse_document(ctx, document_id: str) -> dict:
    """arq task: stream-process a document end-to-end.

    Resumable: pages that already have consolidated_text are skipped, so a
    retry after a crash picks up where the previous run stopped.
    """
    settings = get_settings()
    storage = get_storage()

    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            log.error("doc_missing", document_id=document_id)
            return {"ok": False, "error": "not_found"}

        doc.status = DocumentStatus.processing
        doc.started_at = datetime.now(timezone.utc)
        doc.error = None
        await db.commit()

        rule_md = None
        rule_route = None
        rule_model = None
        if doc.rule_id:
            rule = (
                await db.execute(select(Rule).where(Rule.id == doc.rule_id))
            ).scalar_one_or_none()
            if rule:
                rule_md = rule.body_md
                rule_route = rule.model_route
                rule_model = rule.model_override

        pdf_path = Path(doc.storage_path)
        pages_dir = storage.pages_dir(document_id)
        callback_url = doc.callback_url

    try:
        n_pages = await render.count_pages(pdf_path)
    except Exception as e:
        return await _mark_failed(document_id, callback_url, ctx, f"page_count_failed: {e}")

    if n_pages > settings.max_pages:
        return await _mark_failed(
            document_id,
            callback_url,
            ctx,
            f"too_many_pages: {n_pages} > MAX_PAGES={settings.max_pages}",
        )

    await _set_page_count(document_id, n_pages)
    done = await _load_done_pages(document_id)
    if done:
        log.info("resuming", document_id=document_id, already_done=len(done))

    async def _on_complete(r: PageResult) -> None:
        await _persist_page(document_id, r, settings.keep_page_images)

    async def _skip(idx: int) -> bool:
        return idx in done

    try:
        await pipeline.stream_pages(
            pdf_path,
            pages_dir,
            n_pages,
            max_concurrency=settings.page_concurrency,
            on_page_complete=_on_complete,
            skip_check=_skip,
        )
    except Exception as e:
        log.exception("parse_failed", document_id=document_id)
        return await _mark_failed(document_id, callback_url, ctx, str(e))

    # All pages persisted. Build the consolidated text + rule output.
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Page).where(Page.document_id == document_id).order_by(Page.index)
            )
        ).scalars().all()
        page_results = [
            PageResult(
                index=r.index,
                plumber_text=r.plumber_text or "",
                vision_text=r.vision_text or "",
                consolidated_text=r.consolidated_text or "",
                image_path=Path(r.image_path) if r.image_path else Path(""),
            )
            for r in rows
        ]

    rule_output = None
    full_text = "\n\n".join(
        f"# Page {p.index + 1}\n\n{p.consolidated_text}" for p in page_results
    )

    if rule_md:
        try:
            rule_output, full_text = await pipeline.apply_rule(
                page_results,
                rule_md=rule_md,
                rule_model_route=rule_route,
                rule_model_override=rule_model,
            )
        except Exception as e:
            log.error("rule_extraction_failed", error=str(e))
            rule_output = {"_error": str(e)[:500]}

    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return {"ok": False, "error": "doc_vanished"}

        # Wipe any prior sections (in case of a re-run that produced different output)
        await db.execute(
            Section.__table__.delete().where(Section.document_id == document_id)
        )

        doc.consolidated_text = clean_text(full_text)
        cleaned_output = clean_jsonable(rule_output)
        doc.rule_output = (
            cleaned_output
            if isinstance(cleaned_output, dict)
            else ({"items": cleaned_output} if cleaned_output is not None else None)
        )

        if isinstance(cleaned_output, list):
            for i, item in enumerate(cleaned_output):
                title, content, data = _section_fields(item)
                db.add(
                    Section(
                        document_id=document_id,
                        order=i,
                        kind="rule_item",
                        title=clean_text(title),
                        content=clean_text(content),
                        data=clean_jsonable(data),
                    )
                )

        doc.status = DocumentStatus.completed
        doc.finished_at = datetime.now(timezone.utc)
        if doc.callback_url:
            doc.callback_status = CallbackStatus.pending
        await db.commit()

    if callback_url:
        await ctx["redis"].enqueue_job(
            "deliver_callback",
            document_id,
            "document.completed",
            {
                "page_count": n_pages,
                "has_rule_output": rule_output is not None,
            },
        )

    return {"ok": True, "page_count": n_pages}


async def _mark_failed(document_id: str, callback_url: str | None, ctx, msg: str) -> dict:
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.failed
            doc.error = msg[:2000]
            doc.finished_at = datetime.now(timezone.utc)
            if doc.callback_url:
                doc.callback_status = CallbackStatus.pending
            await db.commit()
    if callback_url:
        await ctx["redis"].enqueue_job(
            "deliver_callback",
            document_id,
            "document.failed",
            {"error": msg[:500]},
        )
    return {"ok": False, "error": msg}


def _section_fields(item) -> tuple[str | None, str | None, dict | None]:
    if isinstance(item, dict):
        title = item.get("title") or item.get("name") or item.get("question") or None
        content = item.get("content") or item.get("text") or item.get("body") or None
        return (
            str(title) if title else None,
            str(content) if content else None,
            item,
        )
    return (None, str(item), None)
