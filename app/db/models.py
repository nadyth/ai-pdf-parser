from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class JsonType(TypeDecorator):
    """Use JSONB on Postgres, JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class CallbackStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"
    failed = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.pending,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("rules.id"), nullable=True)
    consolidated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_output: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JsonType), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-upload callback (one-shot). If set, on completion/failure the system POSTs
    # JSON to callback_url with optional HMAC-SHA256 signature using callback_secret.
    callback_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    callback_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    callback_status: Mapped[CallbackStatus | None] = mapped_column(
        Enum(CallbackStatus, name="callback_status"), nullable=True
    )

    rule = relationship("Rule", back_populates="documents")
    pages = relationship(
        "Page",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Page.index",
    )
    sections = relationship(
        "Section",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Section.order",
    )
    callbacks = relationship(
        "CallbackDelivery",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="CallbackDelivery.attempt",
    )


class Page(Base, TimestampMixin):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    plumber_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    vision_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consolidated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extras: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JsonType), nullable=True
    )

    document = relationship("Document", back_populates="pages")


class Section(Base, TimestampMixin):
    """Chapter / section unit produced by rule-driven extraction."""

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), default="section", nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JsonType), nullable=True
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document = relationship("Document", back_populates="sections")


class Rule(Base, TimestampMixin):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    model_route: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JsonType), nullable=True
    )

    documents = relationship("Document", back_populates="rule")


class CallbackDelivery(Base, TimestampMixin):
    """One row per delivery attempt for a Document's callback_url."""

    __tablename__ = "callback_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="callbacks")
