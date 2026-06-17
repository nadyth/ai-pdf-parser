from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    body_md: str = Field(..., min_length=1)
    model_route: str | None = None
    model_override: str | None = None
    output_schema: dict[str, Any] | None = None


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    body_md: str | None = None
    model_route: str | None = None
    model_override: str | None = None
    output_schema: dict[str, Any] | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    body_md: str
    model_route: str | None = None
    model_override: str | None = None
    output_schema: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
