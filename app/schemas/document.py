from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.models import CallbackStatus, DocumentStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    size_bytes: int
    page_count: int  # total pages, set after upload
    processed_page_count: int = 0  # pages with consolidated_text persisted so far
    status: DocumentStatus
    error: str | None = None
    rule_id: str | None = None
    callback_url: str | None = None
    callback_status: CallbackStatus | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    index: int
    plumber_text: str | None = None
    vision_text: str | None = None
    consolidated_text: str | None = None
    image_path: str | None = None


class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order: int
    kind: str
    title: str | None = None
    content: str | None = None
    data: dict[str, Any] | None = None
    page_start: int | None = None
    page_end: int | None = None


class DocumentContent(BaseModel):
    document_id: str
    consolidated_text: str | None = None
    rule_output: Any | None = None
    page_count: int


class DocumentDetail(DocumentOut):
    consolidated_text: str | None = None
    rule_output: Any | None = None
