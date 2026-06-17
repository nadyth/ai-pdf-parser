from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().database_url
    # asyncpg doesn't accept sslmode=... style kwargs via URL directly in some envs,
    # but standard urls work. Keep simple.
    return create_async_engine(url, future=True, pool_pre_ping=True)


engine = _make_engine()
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
