from __future__ import annotations

from typing import Any

from app.core.settings import get_settings
from app.services.webhooks import attempt_callback, next_backoff_seconds


async def deliver_callback(
    ctx,
    document_id: str,
    event: str,
    payload: dict[str, Any],
    attempt: int = 1,
) -> dict:
    """arq task: attempt one delivery; on failure, re-enqueue with backoff."""
    ok = await attempt_callback(document_id, event, payload, attempt)
    if ok:
        return {"ok": True, "attempt": attempt}

    s = get_settings()
    if attempt >= s.webhook_max_retries:
        return {"ok": False, "attempt": attempt, "exhausted": True}

    delay = next_backoff_seconds(attempt)
    redis = ctx["redis"]
    await redis.enqueue_job(
        "deliver_callback",
        document_id,
        event,
        payload,
        attempt + 1,
        _defer_by=delay,
    )
    return {"ok": False, "attempt": attempt, "next_in_seconds": delay}
