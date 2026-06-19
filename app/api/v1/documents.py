from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
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
    User,
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

router = APIRouter(prefix="/documents", tags=["documents"])

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


async def _get_doc_or_404(db: AsyncSession, document_id: str, user_id: str) -> Document:
    doc = (
        await db.execute(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> DocumentOut:
    s = get_settings()
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported.")

    if rule_id:
        rule = (
            await db.execute(
                select(Rule).where(Rule.id == rule_id, Rule.user_id == user.id)
            )
        ).scalar_one_or_none()
        if rule is None:
            raise HTTPException(404, f"Rule {rule_id} not found.")

    doc = Document(
        filename=file.filename,
        storage_path="",
        size_bytes=0,
        rule_id=rule_id,
        user_id=user.id,
        status=DocumentStatus.pending,
        callback_url=callback_url,
        callback_secret=callback_secret,
    )
    db.add(doc)
    await db.flush()

    # Stream to a temp file, then upload to GCS
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    total = 0
    try:
        with tmp_path.open("wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > s.max_upload_bytes:
                    tmp_path.unlink(missing_ok=True)
                    await db.delete(doc)
                    await db.commit()
                    raise HTTPException(
                        413, f"PDF exceeds MAX_UPLOAD_BYTES ({s.max_upload_bytes})."
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        tmp_path.unlink(missing_ok=True)
        await db.delete(doc)
        await db.commit()
        raise

    if total == 0:
        tmp_path.unlink(missing_ok=True)
        await db.delete(doc)
        await db.commit()
        raise HTTPException(400, "Empty upload.")

    try:
        n_pages = await render.count_pages(tmp_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        await db.delete(doc)
        await db.commit()
        raise HTTPException(400, f"Not a valid PDF: {e}")

    if n_pages > s.max_pages:
        tmp_path.unlink(missing_ok=True)
        await db.delete(doc)
        await db.commit()
        raise HTTPException(413, f"PDF has {n_pages} pages > MAX_PAGES={s.max_pages}.")

    blob_path = f"documents/{doc.id}/original.pdf"
    storage = get_storage()
    await storage.upload(blob_path, tmp_path)
    tmp_path.unlink(missing_ok=True)

    doc.storage_path = blob_path
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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> list[DocumentOut]:
    stmt = (
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    out: list[DocumentOut] = []
    for d in rows:
        out.append(_doc_to_out(d, await _processed_count(db, d.id)))
    return out


@router.get("/{document_id}", response_model=DocumentDetail, summary="Get document detail")
async def get_document(
    document_id: str,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> DocumentDetail:
    doc = await _get_doc_or_404(db, document_id, user.id)
    return _doc_to_detail(doc, await _processed_count(db, document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all derived artifacts",
)
async def delete_document(
    document_id: str,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> None:
    await _get_doc_or_404(db, document_id, user.id)
    await db.execute(Page.__table__.delete().where(Page.document_id == document_id))
    await db.execute(Section.__table__.delete().where(Section.document_id == document_id))
    doc = await _get_doc_or_404(db, document_id, user.id)
    await db.delete(doc)
    await db.commit()
    await get_storage().delete_prefix(f"documents/{document_id}/")


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentOut,
    summary="Re-enqueue parsing (resume by default; ?force=true to wipe and restart)",
)
async def reprocess(
    document_id: str,
    force: bool = Query(False, description="Delete prior pages/sections before re-running"),
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> DocumentOut:
    doc = await _get_doc_or_404(db, document_id, user.id)
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
async def get_content(
    document_id: str,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> DocumentContent:
    doc = await _get_doc_or_404(db, document_id, user.id)
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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> list[PageOut]:
    await _get_doc_or_404(db, document_id, user.id)
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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> PageOut:
    await _get_doc_or_404(db, document_id, user.id)
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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
):
    await _get_doc_or_404(db, document_id, user.id)
    row = (
        await db.execute(
            select(Page).where(Page.document_id == document_id, Page.index == index)
        )
    ).scalar_one_or_none()
    if row is None or not row.image_path:
        raise HTTPException(
            404,
            "Page image not available. (Possibly deleted by KEEP_PAGE_IMAGES=false.)",
        )
    try:
        data = await get_storage().read_bytes(row.image_path)
    except Exception:
        raise HTTPException(
            404,
            "Page image not available. (Possibly deleted by KEEP_PAGE_IMAGES=false.)",
        )
    return Response(content=data, media_type="image/png")


@router.get(
    "/{document_id}/sections",
    response_model=list[SectionOut],
    summary="List rule-extracted sections (chapters/items)",
)
async def list_sections(
    document_id: str,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> list[SectionOut]:
    await _get_doc_or_404(db, document_id, user.id)
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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> SectionOut:
    await _get_doc_or_404(db, document_id, user.id)
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
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> list[CallbackDeliveryOut]:
    await _get_doc_or_404(db, document_id, user.id)
    rows = (
        await db.execute(
            select(CallbackDelivery)
            .where(CallbackDelivery.document_id == document_id)
            .order_by(CallbackDelivery.attempt)
        )
    ).scalars().all()
    return [CallbackDeliveryOut.model_validate(r) for r in rows]
