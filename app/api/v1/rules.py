from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.security import require_api_key
from app.db.models import Rule, User
from app.schemas.rule import RuleCreate, RuleOut, RuleUpdate

router = APIRouter(prefix="/rules", tags=["rules"])


async def _get_rule_or_404(db: AsyncSession, rule_id: str, user_id: str) -> Rule:
    rule = (
        await db.execute(select(Rule).where(Rule.id == rule_id, Rule.user_id == user_id))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(404, "Rule not found.")
    return rule


@router.post(
    "",
    response_model=RuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a parsing rule (markdown body)",
)
async def create_rule(
    payload: RuleCreate,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> RuleOut:
    slug = slugify(payload.name)
    existing = (
        await db.execute(
            select(Rule).where(
                Rule.user_id == user.id,
                (Rule.name == payload.name) | (Rule.slug == slug),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Rule with this name already exists.")
    rule = Rule(
        user_id=user.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        body_md=payload.body_md,
        model_route=payload.model_route,
        model_override=payload.model_override,
        output_schema=payload.output_schema,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return RuleOut.model_validate(rule)


@router.get("", response_model=list[RuleOut], summary="List rules")
async def list_rules(
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> list[RuleOut]:
    rows = (
        await db.execute(
            select(Rule).where(Rule.user_id == user.id).order_by(Rule.created_at.desc())
        )
    ).scalars().all()
    return [RuleOut.model_validate(r) for r in rows]


@router.get("/{rule_id}", response_model=RuleOut, summary="Get a rule")
async def get_rule(
    rule_id: str,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> RuleOut:
    rule = await _get_rule_or_404(db, rule_id, user.id)
    return RuleOut.model_validate(rule)


@router.patch("/{rule_id}", response_model=RuleOut, summary="Update a rule")
async def update_rule(
    rule_id: str,
    payload: RuleUpdate,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> RuleOut:
    r = await _get_rule_or_404(db, rule_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        new_slug = slugify(data["name"])
        conflict = (
            await db.execute(
                select(Rule).where(
                    Rule.user_id == user.id,
                    Rule.id != rule_id,
                    (Rule.name == data["name"]) | (Rule.slug == new_slug),
                )
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(409, "Rule with this name already exists.")
        r.name = data["name"]
        r.slug = new_slug
    for k in ("description", "body_md", "model_route", "model_override", "output_schema"):
        if k in data:
            setattr(r, k, data[k])
    await db.commit()
    await db.refresh(r)
    return RuleOut.model_validate(r)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a rule")
async def delete_rule(
    rule_id: str,
    user: User = Depends(require_api_key),
    db: AsyncSession = Depends(db_session),
) -> None:
    r = await _get_rule_or_404(db, rule_id, user.id)
    await db.delete(r)
    await db.commit()
