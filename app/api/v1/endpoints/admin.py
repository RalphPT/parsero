"""
Endpoints administrativos. Todos protegidos por X-Admin-Token == SECRET_KEY.

Para v1 los tenants se crean a mano por aquí. Cuando llegue Fase 5 (Stripe +
landing) se agregará un /auth/signup público — estos seguirán existiendo.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_admin
from app.db.repositories.api_key import ApiKeyRepository
from app.db.repositories.tenant import TenantRepository
from app.db.session import get_db
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
)
from app.schemas.tenant import TenantCreate, TenantResponse

router = APIRouter(dependencies=[Depends(verify_admin)])


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    """Lista todos los tenants (orden: más recientes primero)."""
    return await TenantRepository(db).list_all()


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    tenant = await TenantRepository(db).get(tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant no encontrado")
    return tenant


@router.get(
    "/tenants/{tenant_id}/keys",
    response_model=list[ApiKeyResponse],
)
async def list_tenant_keys(tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Lista las API keys de un tenant. Útil para conseguir el `id` (UUID) que
    necesitas en el PATCH para revocar una key."""
    if not await TenantRepository(db).get(tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant no encontrado")
    return await ApiKeyRepository(db).list_for_tenant(tenant_id)


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
):
    repo = TenantRepository(db)
    if await repo.get_by_email(body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un tenant con email {body.email}",
        )
    tenant = await repo.create(name=body.name, email=body.email, plan=body.plan)
    await db.commit()
    return tenant


@router.post(
    "/tenants/{tenant_id}/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key_for_tenant(
    tenant_id: UUID,
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
):
    if not await TenantRepository(db).get(tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant no encontrado")

    api_key, raw_key = await ApiKeyRepository(db).create(
        tenant_id=tenant_id, name=body.name, expires_at=body.expires_at
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


@router.patch(
    "/tenants/{tenant_id}/keys/{key_id}",
    response_model=ApiKeyResponse,
)
async def update_api_key(
    tenant_id: UUID,
    key_id: UUID,
    body: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Activa o desactiva una API key. Útil para revocar una key filtrada."""
    api_key = await ApiKeyRepository(db).set_active(
        tenant_id=tenant_id, key_id=key_id, is_active=body.is_active
    )
    if api_key is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "API key no encontrada para ese tenant"
        )
    await db.commit()
    return api_key
