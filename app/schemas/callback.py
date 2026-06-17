from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CallbackDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    event: str
    attempt: int
    url: str
    status_code: int | None = None
    response_excerpt: str | None = None
    error: str | None = None
    duration_ms: float | None = None
    delivered_at: datetime | None = None
    created_at: datetime
