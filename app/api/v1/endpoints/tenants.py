"""
Endpoints del tenant autenticado (auth via Bearer <api_key> + rate limit).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_rate_limit, get_current_tenant
from app.db.models.tenant import Tenant
from app.db.repositories.api_key import ApiKeyRepository
from app.db.session import get_db
from app.schemas.api_key import ApiKeyResponse
from app.schemas.tenant import TenantResponse

# El rate limit aplica a todas las rutas de este router
router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("/me", response_model=TenantResponse)
async def get_me(tenant: Tenant = Depends(get_current_tenant)):
    return tenant


@router.get("/me/keys", response_model=list[ApiKeyResponse])
async def list_my_keys(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await ApiKeyRepository(db).list_for_tenant(tenant.id)
