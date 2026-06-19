from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth, documents, health, rules
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import configure_logging, log
from app.core.settings import get_settings
from app.db.base import engine
from app.services.storage import get_storage
from app.tasks.queue import close_queue
from app.ui import routes as ui_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level)
    get_storage().ensure_bucket()
    log.info("startup_complete", env=s.app_env, db=_redact(s.database_url))
    yield
    await close_queue()
    await engine.dispose()


def _redact(url: str) -> str:
    if "@" in url:
        head, tail = url.split("@", 1)
        if "://" in head:
            scheme, creds = head.split("://", 1)
            return f"{scheme}://***@{tail}"
    return url


def _custom_openapi(app: FastAPI):
    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "ApiKeyAuth"
        ] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key returned by POST /api/v1/auth/signup or /api/v1/auth/login.",
        }
        schema["security"] = [{"ApiKeyAuth": []}]
        app.openapi_schema = schema
        return schema

    return openapi


def create_app() -> FastAPI:
    app = FastAPI(
        title="PDF Parser",
        version="0.1.0",
        description=(
            "Async AI-powered PDF parser. Default pipeline: 300dpi render → vision LLM "
            "+ pdfplumber → consolidation. Optional Markdown rules drive structured "
            "extraction. Pass a `callback_url` on upload to be notified when "
            "processing completes.\n\n"
            "All endpoints require an `X-API-Key` header."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "auth", "description": "User registration, login, and API key management."},
            {"name": "documents", "description": "Upload, list, retrieve PDFs and parsed content."},
            {"name": "rules", "description": "User-defined Markdown rules for structured extraction."},
            {"name": "health", "description": "Liveness."},
            {"name": "ui", "description": "Server-rendered UI."},
        ],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(rules.router, prefix="/api/v1")

    app.include_router(ui_routes.router)
    app.mount(
        "/static",
        StaticFiles(directory="app/ui/static", check_dir=False),
        name="static",
    )

    app.openapi = _custom_openapi(app)  # type: ignore[assignment]

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError):
        return JSONResponse({"error": exc.message, "details": exc.details}, status_code=404)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse({"error": exc.message, "details": exc.details}, status_code=400)

    return app


app = create_app()
