from __future__ import annotations

from pathlib import Path

import aiofiles
from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.settings import get_settings
from app.db.models import (
    CallbackDelivery,
    Document,
    DocumentStatus,
    Page,
    Rule,
    Section,
)

router = APIRouter(tags=["ui"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_UPLOAD_CHUNK = 1024 * 1024


def _check_cookie(api_key: str | None) -> bool:
    return bool(api_key) and api_key in set(get_settings().api_keys)


def _require_ui_auth(api_key: str | None = Cookie(default=None)) -> str:
    if not _check_cookie(api_key):
        raise HTTPException(303, headers={"Location": "/ui/login"})
    return api_key  # type: ignore


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@router.get("/ui/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/ui/login", include_in_schema=False)
async def login_submit(api_key: str = Form(...)) -> RedirectResponse:
    if not _check_cookie(api_key):
        return RedirectResponse(url="/ui/login?error=1", status_code=303)
    resp = RedirectResponse(url="/ui/", status_code=303)
    resp.set_cookie("api_key", api_key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@router.post("/ui/logout", include_in_schema=False)
async def logout() -> RedirectResponse:
    resp = RedirectResponse(url="/ui/login", status_code=303)
    resp.delete_cookie("api_key")
    return resp


@router.get("/ui/", response_class=HTMLResponse, include_in_schema=False)
async def index(
    request: Request,
    _: str = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    docs = (
        await db.execute(select(Document).order_by(Document.created_at.desc()).limit(50))
    ).scalars().all()
    rules = (await db.execute(select(Rule).order_by(Rule.name))).scalars().all()
    return templates.TemplateResponse(
        request, "index.html", {"documents": docs, "rules": rules}
    )


@router.post("/ui/upload", include_in_schema=False)
async def ui_upload(
    file: UploadFile = File(...),
    rule_id: str | None = Form(default=None),
    callback_url: str | None = Form(default=None),
    callback_secret: str | None = Form(default=None),
    _: str = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    from app.services.storage import get_storage
    from app.tasks.queue import get_queue

    s = get_settings()
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF only.")

    doc = Document(
        filename=file.filename,
        storage_path="",
        size_bytes=0,
        rule_id=rule_id or None,
        status=DocumentStatus.pending,
        callback_url=callback_url or None,
        callback_secret=callback_secret or None,
    )
    db.add(doc)
    await db.flush()

    storage = get_storage()
    target = storage.doc_dir(doc.id) / "original.pdf"
    total = 0
    async with aiofiles.open(target, "wb") as out:
        while True:
            chunk = await file.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > s.max_upload_bytes:
                await out.close()
                target.unlink(missing_ok=True)
                await db.delete(doc)
                await db.commit()
                raise HTTPException(413, "PDF too large.")
            await out.write(chunk)
    if total == 0:
        await db.delete(doc)
        await db.commit()
        raise HTTPException(400, "Empty file.")

    # Validate page count up-front.
    from app.services.pdf import render as render_svc

    try:
        n_pages = await render_svc.count_pages(target)
    except Exception as e:
        await db.delete(doc)
        await db.commit()
        get_storage().delete_doc(doc.id)
        raise HTTPException(400, f"Not a valid PDF: {e}") from e
    if n_pages > s.max_pages:
        await db.delete(doc)
        await db.commit()
        get_storage().delete_doc(doc.id)
        raise HTTPException(413, f"{n_pages} pages > MAX_PAGES={s.max_pages}.")

    doc.storage_path = str(target)
    doc.size_bytes = total
    doc.page_count = n_pages
    await db.commit()
    queue = await get_queue()
    await queue.enqueue_job("parse_document", doc.id, _job_id=f"parse:{doc.id}")
    return RedirectResponse(url=f"/ui/documents/{doc.id}", status_code=303)


@router.get(
    "/ui/documents/{document_id}", response_class=HTMLResponse, include_in_schema=False
)
async def doc_detail(
    request: Request,
    document_id: str,
    _: str = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Not found.")
    pages = (
        await db.execute(select(Page).where(Page.document_id == document_id).order_by(Page.index))
    ).scalars().all()
    sections = (
        await db.execute(
            select(Section).where(Section.document_id == document_id).order_by(Section.order)
        )
    ).scalars().all()
    callbacks = (
        await db.execute(
            select(CallbackDelivery)
            .where(CallbackDelivery.document_id == document_id)
            .order_by(CallbackDelivery.attempt)
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "document.html",
        {"doc": doc, "pages": pages, "sections": sections, "callbacks": callbacks},
    )


@router.get("/ui/rules", response_class=HTMLResponse, include_in_schema=False)
async def rules_index(
    request: Request,
    _: str = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    rules = (await db.execute(select(Rule).order_by(Rule.created_at.desc()))).scalars().all()
    return templates.TemplateResponse(request, "rules.html", {"rules": rules})


@router.post("/ui/rules", include_in_schema=False)
async def rules_create(
    name: str = Form(...),
    description: str = Form(""),
    body_md: str = Form(...),
    model_route: str = Form(""),
    model_override: str = Form(""),
    _: str = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    from slugify import slugify

    rule = Rule(
        name=name,
        slug=slugify(name),
        description=description or None,
        body_md=body_md,
        model_route=model_route or None,
        model_override=model_override or None,
    )
    db.add(rule)
    await db.commit()
    return RedirectResponse(url="/ui/rules", status_code=303)


@router.post("/ui/rules/{rule_id}/delete", include_in_schema=False)
async def rules_delete(
    rule_id: str,
    _: str = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    r = await db.get(Rule, rule_id)
    if r:
        await db.delete(r)
        await db.commit()
    return RedirectResponse(url="/ui/rules", status_code=303)
