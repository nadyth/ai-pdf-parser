from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.password import hash_password, verify_password
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

router = APIRouter(tags=["ui"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_UPLOAD_CHUNK = 1024 * 1024


async def _require_ui_auth(
    api_key: str | None = Cookie(default=None),
    db: AsyncSession = Depends(db_session),
) -> User:
    if not api_key:
        raise HTTPException(303, headers={"Location": "/ui/login"})
    user = (
        await db.execute(select(User).where(User.api_key == api_key))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(303, headers={"Location": "/ui/login"})
    return user


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@router.get("/ui/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/ui/login", include_in_schema=False)
async def login_submit(
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        return RedirectResponse(url="/ui/login?error=1", status_code=303)
    resp = RedirectResponse(url="/ui/", status_code=303)
    resp.set_cookie("api_key", user.api_key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@router.get("/ui/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "signup.html", {})


@router.post("/ui/signup", include_in_schema=False)
async def signup_submit(
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    if password != password_confirm:
        return RedirectResponse(url="/ui/signup?error=mismatch", status_code=303)
    if len(password) < 8:
        return RedirectResponse(url="/ui/signup?error=tooshort", status_code=303)
    if len(password) > 72:
        return RedirectResponse(url="/ui/signup?error=toolong", status_code=303)
    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        return RedirectResponse(url="/ui/signup?error=duplicate", status_code=303)
    user = User(
        email=email,
        hashed_password=hash_password(password),
        api_key=secrets.token_urlsafe(32),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    resp = RedirectResponse(url="/ui/", status_code=303)
    resp.set_cookie("api_key", user.api_key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@router.post("/ui/logout", include_in_schema=False)
async def logout() -> RedirectResponse:
    resp = RedirectResponse(url="/ui/login", status_code=303)
    resp.delete_cookie("api_key")
    return resp


@router.post("/ui/regenerate-key", include_in_schema=False)
async def ui_regenerate_key(
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    db_user = await db.get(User, current_user.id)
    if db_user is None:
        raise HTTPException(404)
    db_user.api_key = secrets.token_urlsafe(32)
    await db.commit()
    resp = RedirectResponse(url="/ui/", status_code=303)
    resp.set_cookie("api_key", db_user.api_key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@router.get("/ui/", response_class=HTMLResponse, include_in_schema=False)
async def index(
    request: Request,
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    docs = (
        await db.execute(
            select(Document)
            .where(Document.user_id == current_user.id)
            .order_by(Document.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    rules = (
        await db.execute(
            select(Rule).where(Rule.user_id == current_user.id).order_by(Rule.name)
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request, "index.html", {"documents": docs, "rules": rules, "current_user": current_user}
    )


@router.post("/ui/upload", include_in_schema=False)
async def ui_upload(
    file: UploadFile = File(...),
    rule_id: str | None = Form(default=None),
    callback_url: str | None = Form(default=None),
    callback_secret: str | None = Form(default=None),
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    from app.services.pdf import render as render_svc
    from app.services.storage import get_storage
    from app.tasks.queue import get_queue

    s = get_settings()
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF only.")

    if rule_id:
        rule = (
            await db.execute(
                select(Rule).where(Rule.id == rule_id, Rule.user_id == current_user.id)
            )
        ).scalar_one_or_none()
        if rule is None:
            raise HTTPException(404, "Rule not found.")

    doc = Document(
        filename=file.filename,
        storage_path="",
        size_bytes=0,
        rule_id=rule_id or None,
        user_id=current_user.id,
        status=DocumentStatus.pending,
        callback_url=callback_url or None,
        callback_secret=callback_secret or None,
    )
    db.add(doc)
    await db.flush()

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
                    raise HTTPException(413, "PDF too large.")
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
        raise HTTPException(400, "Empty file.")

    try:
        n_pages = await render_svc.count_pages(tmp_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        await db.delete(doc)
        await db.commit()
        raise HTTPException(400, f"Not a valid PDF: {e}") from e

    if n_pages > s.max_pages:
        tmp_path.unlink(missing_ok=True)
        await db.delete(doc)
        await db.commit()
        raise HTTPException(413, f"{n_pages} pages > MAX_PAGES={s.max_pages}.")

    blob_path = f"documents/{doc.id}/original.pdf"
    storage = get_storage()
    await storage.upload(blob_path, tmp_path)
    tmp_path.unlink(missing_ok=True)

    doc.storage_path = blob_path
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
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id, Document.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
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
        {"doc": doc, "pages": pages, "sections": sections, "callbacks": callbacks, "current_user": current_user},
    )


@router.get("/ui/rules", response_class=HTMLResponse, include_in_schema=False)
async def rules_index(
    request: Request,
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    rules = (
        await db.execute(
            select(Rule)
            .where(Rule.user_id == current_user.id)
            .order_by(Rule.created_at.desc())
        )
    ).scalars().all()
    return templates.TemplateResponse(request, "rules.html", {"rules": rules, "current_user": current_user})


@router.post("/ui/rules", include_in_schema=False)
async def rules_create(
    name: str = Form(...),
    description: str = Form(""),
    body_md: str = Form(...),
    model_route: str = Form(""),
    model_override: str = Form(""),
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    from slugify import slugify

    rule = Rule(
        user_id=current_user.id,
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
    current_user: User = Depends(_require_ui_auth),
    db: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    r = (
        await db.execute(
            select(Rule).where(Rule.id == rule_id, Rule.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if r:
        await db.delete(r)
        await db.commit()
    return RedirectResponse(url="/ui/rules", status_code=303)
