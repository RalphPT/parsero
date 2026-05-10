"""Endpoints del dashboard: keys + usage del mes. Auth con cookie o JWT."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_jwt
from app.db.models.tenant import Tenant
from app.db.models.usage_log import UsageLog
from app.db.repositories.api_key import ApiKeyRepository
from app.db.session import get_db
from app.schemas.account import UsageSummary
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
)


router = APIRouter()


@router.get("/account/keys", response_model=list[ApiKeyResponse])
async def list_my_keys(
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    return await ApiKeyRepository(db).list_for_tenant(tenant.id)


@router.post(
    "/account/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_key(
    body: ApiKeyCreate,
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    api_key, raw_key = await ApiKeyRepository(db).create(
        tenant_id=tenant.id, name=body.name, expires_at=body.expires_at
    )
    await db.commit()
    return ApiKeyCreatedResponse(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.patch("/account/keys/{key_id}", response_model=ApiKeyResponse)
async def update_my_key(
    key_id: UUID,
    body: ApiKeyUpdate,
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Activa/desactiva una key del propio tenant. 404 si la key no es suya."""
    api_key = await ApiKeyRepository(db).set_active(
        tenant_id=tenant.id, key_id=key_id, is_active=body.is_active
    )
    if api_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key no encontrada")
    await db.commit()
    return api_key


@router.get("/account/usage", response_model=UsageSummary)
async def my_usage(
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Suma de extracciones + tokens del mes actual (formato YYYY-MM)."""
    period = datetime.utcnow().strftime("%Y-%m")
    stmt = select(
        func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
        func.count(UsageLog.id).label("extractions_count"),
    ).where(
        UsageLog.tenant_id == tenant.id,
        UsageLog.billing_period == period,
    )
    row = (await db.execute(stmt)).one()
    return UsageSummary(
        billing_period=period,
        extractions_count=int(row.extractions_count or 0),
        input_tokens=int(row.input_tokens or 0),
        output_tokens=int(row.output_tokens or 0),
        total_tokens=int((row.input_tokens or 0) + (row.output_tokens or 0)),
    )
