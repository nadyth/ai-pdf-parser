from __future__ import annotations

import asyncio
import base64
import random
from pathlib import Path
from typing import Any

import litellm

from app.core.logging import log
from app.core.router import ResolvedRoute, get_router
from app.core.settings import get_settings


def _completion_kwargs(route: ResolvedRoute) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": _format_model(route),
        "api_key": route.api_key or None,
    }
    if route.base_url:
        kwargs["api_base"] = route.base_url
    for k in ("temperature", "max_tokens", "top_p"):
        if k in route.params:
            kwargs[k] = route.params[k]
    return kwargs


def _format_model(route: ResolvedRoute) -> str:
    model = route.model
    if route.provider == "openai" or "/" in model:
        return model
    return f"{route.provider}/{model}"


def _is_retryable(exc: BaseException) -> bool:
    # litellm wraps everything in its own exceptions; treat anything that
    # smells like rate-limit / transient as retryable.
    name = type(exc).__name__.lower()
    if any(k in name for k in ("ratelimit", "timeout", "apierror", "serviceunavailable")):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "503", "502", "504", "timeout", "rate limit"))


async def _acompletion_with_retry(**kwargs):
    s = get_settings()
    last_exc: BaseException | None = None
    for attempt in range(1, s.llm_max_attempts + 1):
        try:
            return await litellm.acompletion(**kwargs)
        except Exception as e:
            last_exc = e
            if not _is_retryable(e) or attempt >= s.llm_max_attempts:
                raise
            delay = s.llm_backoff_base_seconds * (2 ** (attempt - 1))
            delay = min(delay, 60.0) + random.uniform(0, 0.5)
            log.warning(
                "llm_retry",
                attempt=attempt,
                max=s.llm_max_attempts,
                delay=round(delay, 2),
                error=str(e)[:200],
            )
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


async def chat(
    task: str,
    messages: list[dict[str, Any]],
    *,
    override_model: str | None = None,
    route_name: str | None = None,
) -> str:
    route = get_router().resolve(task, override_model=override_model, route_name=route_name)
    kwargs = _completion_kwargs(route)
    resp = await _acompletion_with_retry(messages=messages, **kwargs)
    return resp["choices"][0]["message"]["content"] or ""


async def vision(
    task: str,
    prompt: str,
    image_path: Path,
    *,
    override_model: str | None = None,
    route_name: str | None = None,
) -> str:
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ],
        }
    ]
    return await chat(task, messages, override_model=override_model, route_name=route_name)
