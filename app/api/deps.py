from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.db.base import SessionLocal


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


# Convenience composite
def auth_and_db():
    async def _dep(
        _: str = Depends(require_api_key),
        db: AsyncSession = Depends(db_session),
    ) -> AsyncSession:
        return db

    return _dep
