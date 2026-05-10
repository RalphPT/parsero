"""
Endpoints de billing. Todos requieren JWT de sesión.

  - POST /billing/checkout  -> URL hosted de Lemon Squeezy para suscribirse
  - POST /billing/portal    -> URL del portal del cliente (cancelar, cambiar tarjeta)
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user_jwt
from app.core.config import get_settings
from app.db.models.tenant import Tenant
from app.schemas.billing import CheckoutRequest, CheckoutResponse, PortalResponse
from app.services.lemonsqueezy_service import (
    LemonSqueezyError,
    get_lemonsqueezy_service,
)


router = APIRouter()


@router.post("/billing/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    tenant: Tenant = Depends(get_current_user_jwt),
):
    """Crea un checkout en Lemon Squeezy y devuelve la URL hosted para redirigir."""
    settings = get_settings()
    variant_map = {
        "starter": settings.lemonsqueezy_variant_starter,
        "pro": settings.lemonsqueezy_variant_pro,
    }
    variant_id = variant_map.get(body.plan)
    if not variant_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Variant ID para plan '{body.plan}' no configurado",
        )

    try:
        url = await get_lemonsqueezy_service().create_checkout_url(
            variant_id=variant_id,
            tenant_id=tenant.id,
            tenant_email=tenant.email,
        )
    except LemonSqueezyError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    return CheckoutResponse(checkout_url=url)


@router.post("/billing/portal", response_model=PortalResponse)
async def get_portal(tenant: Tenant = Depends(get_current_user_jwt)):
    """Devuelve URL del Customer Portal - el cliente cancela o cambia tarjeta ahí."""
    if not tenant.lemon_subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tienes suscripción activa para acceder al portal",
        )
    try:
        url = await get_lemonsqueezy_service().get_customer_portal_url(
            tenant.lemon_subscription_id
        )
    except LemonSqueezyError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    return PortalResponse(portal_url=url)
