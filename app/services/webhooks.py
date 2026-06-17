from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logging import log
from app.core.settings import get_settings
from app.db.base import SessionLocal
from app.db.models import CallbackDelivery, CallbackStatus, Document


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def attempt_callback(document_id: str, event: str, payload: dict[str, Any], attempt: int) -> bool:
    """Single delivery attempt. Persists a CallbackDelivery row. Returns True on 2xx."""
    s = get_settings()
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None or not doc.callback_url:
            return True  # nothing to do

        body = json.dumps(
            {"event": event, "document_id": document_id, "data": payload}
        ).encode()
        headers = {"Content-Type": "application/json", "X-Event": event}
        if doc.callback_secret:
            headers["X-Signature-Sha256"] = _sign(doc.callback_secret, body)

        delivery = CallbackDelivery(
            document_id=document_id,
            event=event,
            attempt=attempt,
            url=doc.callback_url,
        )
        db.add(delivery)

        t0 = time.perf_counter()
        ok = False
        try:
            async with httpx.AsyncClient(timeout=s.webhook_timeout_seconds) as client:
                resp = await client.post(doc.callback_url, content=body, headers=headers)
            delivery.status_code = resp.status_code
            delivery.response_excerpt = resp.text[:512]
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.duration_ms = (time.perf_counter() - t0) * 1000.0
            ok = 200 <= resp.status_code < 300
            if not ok:
                delivery.error = f"HTTP {resp.status_code}"
        except Exception as e:
            delivery.error = str(e)[:512]
            delivery.duration_ms = (time.perf_counter() - t0) * 1000.0
            log.error("callback_attempt_failed", document_id=document_id, error=str(e))

        if ok:
            doc.callback_status = CallbackStatus.delivered
        elif attempt >= s.webhook_max_retries:
            doc.callback_status = CallbackStatus.failed
        else:
            doc.callback_status = CallbackStatus.pending

        await db.commit()
        return ok


def next_backoff_seconds(attempt: int) -> float:
    """Exponential backoff: base * 2^(attempt-1), capped at 5 minutes."""
    base = get_settings().webhook_backoff_base_seconds
    delay = base * (2 ** max(attempt - 1, 0))
    return min(delay, 300.0)
