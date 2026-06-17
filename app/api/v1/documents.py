from __future__ import annotations

import os
from datetime import datetime, timezone

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.security import require_api_key
from app.core.settings import get_settings
from app.db.models import (
    CallbackDelivery,
    Document,
    DocumentStatus,
    Page,
    Rule,
    Section,
)
from app.schemas.callback import CallbackDeliveryOut
from app.schemas.document import (
    DocumentContent,
    DocumentDetail,
    DocumentOut,
    PageOut,
    SectionOut,
)
from app.services.pdf import render
from app.services.storage import get_storage
from app.tasks.queue import get_queue

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_api_key)],
)

_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB


async def _processed_count(db: AsyncSession, document_id: str) -> int:
    res = await db.execute(
        select(func.count())
        .select_from(Page)
        .where(
            Page.document_id == document_id,
            Page.consolidated_text.is_not(None),
        )
    )
    return int(res.scalar() or 0)


def _doc_to_out(doc: Document, processed: int) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    return out.model_copy(update={"processed_page_count": processed})


def _doc_to_detail(doc: Document, processed: int) -> DocumentDetail:
    out = DocumentDetail.model_validate(doc)
    return out.model_copy(update={"processed_page_count": processed})


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF and enqueue parsing",
    description=(
        "Uploads a PDF file. The default pipeline streams page-by-page in the "
        "background: 300 DPI render → vision LLM → pdfplumber → consolidation. "
        "Each page is committed as soon as it's parsed so progress is visible "
        "via `processed_page_count`.\n\n"
        "- Pass `rule_id` to additionally apply a user-defined extraction rule.\n"
        "- Pass `callback_url` to receive a POST when processing completes or "
        "fails (retried with exponential backoff). `callback_secret` enables "
        "HMAC signing.\n"
        "- Hard limits: `MAX_UPLOAD_BYTES` (default 2 GiB), `MAX_PAGES` "
        "(default 1000)."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="PDF file"),
    rule_id: str | None = Form(default=None, description="Optional Rule.id to apply"),
    callback_url: str | None = Form(default=None, description="One-shot completion webhook"),
    callback_secret: str | None = Form(default=None, description="HMAC-SHA256 secret"),
    db: AsyncSession = Depends(db_session),
) -> DocumentOut:
    s = get_settings()
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported.")

    if rule_id:
        rule = await db.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, f"Rule {rule_id} not found.")

    doc = Document(
        filename=file.filename,
        storage_path="",
        size_bytes=0,
        rule_id=rule_id,
        status=DocumentStatus.pending,
        callback_url=callback_url,
        callback_secret=callback_secret,
    )
    db.add(doc)
    await db.flush()

    storage = get_storage()
    target = storage.doc_dir(doc.id) / "original.pdf"
    total = 0
    try:
        async with aiofiles.open(target, "wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > s.max_upload_bytes:
                    try:
                        await out.close()
                    finally:
                        try:
                            os.remove(target)
                        except OSError:
                            pass
                    await db.delete(doc)
                    await db.commit()
                    raise HTTPException(
                        413,
                        f"PDF exceeds MAX_UPLOAD_BYTES ({s.max_upload_bytes}).",
                    )
                await out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        await db.delete(doc)
        await db.commit()
        raise

    if total == 0:
        await db.delete(doc)
        await db.commit()
        raise HTTPException(400, "Empty upload.")

    # Validate page count up-front so we reject 1500-page PDFs immediately
    # rather than discovering it inside the worker.
    try:
        n_pages = await render.count_pages(target)
    except Exception as e:
        await db.delete(doc)
        await db.commit()
        get_storage().delete_doc(doc.id)
        raise HTTPException(400, f"Not a valid PDF: {e}")

    if n_pages > s.max_pages:
        await db.delete(doc)
        await db.commit()
        get_storage().delete_doc(doc.id)
        raise HTTPException(
            413,
            f"PDF has {n_pages} pages > MAX_PAGES={s.max_pages}.",
        )

    async with aiofiles.open(storage.doc_dir(doc.id) / "filename.txt", "w") as f:
        await f.write(file.filename)

    doc.storage_path = str(target)
    doc.size_bytes = total
    doc.page_count = n_pages
    await db.commit()
    await db.refresh(doc)

    queue = await get_queue()
    await queue.enqueue_job("parse_document", doc.id, _job_id=f"parse:{doc.id}")

    return _doc_to_out(doc, 0)


@router.get("", response_model=list[DocumentOut], summary="List documents")
async def list_documents(
    status_filter: DocumentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[DocumentOut]:
    stmt = select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    out: list[DocumentOut] = []
    for d in rows:
        out.append(_doc_to_out(d, await _processed_count(db, d.id)))
    return out


@router.get("/{document_id}", response_model=DocumentDetail, summary="Get document detail")
async def get_document(document_id: str, db: AsyncSession = Depends(db_session)) -> DocumentDetail:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return _doc_to_detail(doc, await _processed_count(db, document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all derived artifacts",
)
async def delete_document(document_id: str, db: AsyncSession = Depends(db_session)) -> None:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    await db.delete(doc)
    await db.commit()
    get_storage().delete_doc(document_id)


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentOut,
    summary="Re-enqueue parsing (resume by default; ?force=true to wipe and restart)",
)
async def reprocess(
    document_id: str,
    force: bool = Query(False, description="Delete prior pages/sections before re-running"),
    db: AsyncSession = Depends(db_session),
) -> DocumentOut:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    if force:
        await db.execute(Page.__table__.delete().where(Page.document_id == document_id))
        await db.execute(Section.__table__.delete().where(Section.document_id == document_id))
        doc.consolidated_text = None
        doc.rule_output = None
    doc.status = DocumentStatus.pending
    doc.error = None
    doc.started_at = None
    doc.finished_at = None
    doc.callback_status = None
    await db.commit()
    queue = await get_queue()
    await queue.enqueue_job(
        "parse_document",
        document_id,
        _job_id=f"parse:{document_id}:{int(datetime.now(timezone.utc).timestamp())}",
    )
    await db.refresh(doc)
    return _doc_to_out(doc, await _processed_count(db, document_id))


@router.get(
    "/{document_id}/content",
    response_model=DocumentContent,
    summary="Whole-document consolidated content + rule output",
)
async def get_content(document_id: str, db: AsyncSession = Depends(db_session)) -> DocumentContent:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return DocumentContent(
        document_id=doc.id,
        consolidated_text=doc.consolidated_text,
        rule_output=doc.rule_output,
        page_count=doc.page_count,
    )


@router.get(
    "/{document_id}/pages",
    response_model=list[PageOut],
    summary="List all pages of a document",
)
async def list_pages(
    document_id: str,
    db: AsyncSession = Depends(db_session),
) -> list[PageOut]:
    rows = (
        await db.execute(
            select(Page).where(Page.document_id == document_id).order_by(Page.index)
        )
    ).scalars().all()
    return [PageOut.model_validate(r) for r in rows]


@router.get(
    "/{document_id}/pages/{index}",
    response_model=PageOut,
    summary="Get a single page (0-based index)",
)
async def get_page(
    document_id: str,
    index: int,
    db: AsyncSession = Depends(db_session),
) -> PageOut:
    row = (
        await db.execute(
            select(Page).where(Page.document_id == document_id, Page.index == index)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Page not found.")
    return PageOut.model_validate(row)


@router.get(
    "/{document_id}/pages/{index}/image",
    summary="Get the rendered 300dpi PNG for a page",
)
async def get_page_image(
    document_id: str,
    index: int,
    db: AsyncSession = Depends(db_session),
):
    row = (
        await db.execute(
            select(Page).where(Page.document_id == document_id, Page.index == index)
        )
    ).scalar_one_or_none()
    if row is None or not row.image_path or not os.path.exists(row.image_path):
        raise HTTPException(
            404,
            "Page image not available. (Possibly deleted by KEEP_PAGE_IMAGES=false.)",
        )
    return FileResponse(row.image_path, media_type="image/png")


@router.get(
    "/{document_id}/sections",
    response_model=list[SectionOut],
    summary="List rule-extracted sections (chapters/items)",
)
async def list_sections(
    document_id: str,
    db: AsyncSession = Depends(db_session),
) -> list[SectionOut]:
    rows = (
        await db.execute(
            select(Section).where(Section.document_id == document_id).order_by(Section.order)
        )
    ).scalars().all()
    return [SectionOut.model_validate(r) for r in rows]


@router.get(
    "/{document_id}/sections/{order}",
    response_model=SectionOut,
    summary="Get a single section by order",
)
async def get_section(
    document_id: str,
    order: int,
    db: AsyncSession = Depends(db_session),
) -> SectionOut:
    row = (
        await db.execute(
            select(Section).where(
                Section.document_id == document_id, Section.order == order
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Section not found.")
    return SectionOut.model_validate(row)


@router.get(
    "/{document_id}/callbacks",
    response_model=list[CallbackDeliveryOut],
    summary="List callback delivery attempts for a document",
)
async def list_callbacks(
    document_id: str,
    db: AsyncSession = Depends(db_session),
) -> list[CallbackDeliveryOut]:
    rows = (
        await db.execute(
            select(CallbackDelivery)
            .where(CallbackDelivery.document_id == document_id)
            .order_by(CallbackDelivery.attempt)
        )
    ).scalars().all()
    return [CallbackDeliveryOut.model_validate(r) for r in rows]
