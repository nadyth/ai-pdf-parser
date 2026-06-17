from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from app.core.settings import get_settings


def _valid(key: str | None) -> bool:
    if not key:
        return False
    return key in set(get_settings().api_keys)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    # Allow header OR cookie (so UI can store the key once).
    key = x_api_key or request.cookies.get("api_key")
    if not _valid(key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key  # type: ignore[return-value]
