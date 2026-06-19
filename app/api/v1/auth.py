from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.password import hash_password, verify_password
from app.core.security import require_api_key
from app.db.models import User
from app.schemas.user import TokenOut, UserLogin, UserOut, UserSignup

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignup, db: AsyncSession = Depends(db_session)) -> TokenOut:
    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered.")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        api_key=secrets.token_urlsafe(32),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenOut(api_key=user.api_key, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(db_session)) -> TokenOut:
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")
    return TokenOut(api_key=user.api_key, user=UserOut.model_validate(user))


@router.post("/regenerate-key", response_model=TokenOut)
async def regenerate_key(
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> TokenOut:
    # Fetch the user in this session (require_api_key uses its own session)
    db_user = await db.get(User, user.id)
    if db_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    db_user.api_key = secrets.token_urlsafe(32)
    await db.commit()
    await db.refresh(db_user)
    return TokenOut(api_key=db_user.api_key, user=UserOut.model_validate(db_user))
