# Webhook de Lemon Squeezy. La firma viene en X-Signature, HMAC-SHA256 del
# body con LEMONSQUEEZY_WEBHOOK_SECRET. Si no matchea -> 401 y a otra cosa.
import hashlib
import hmac
import json
import logging
import secrets as stdlib_secrets
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.tenant import Tenant, TenantPlan
from app.db.repositories.tenant import TenantRepository
from app.db.session import get_db


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


def _verify_signature(body: bytes, signature_header: Optional[str]) -> None:
    settings = get_settings()
    if not settings.lemonsqueezy_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LEMONSQUEEZY_WEBHOOK_SECRET no configurado",
        )
    if not signature_header:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta X-Signature")
    expected = hmac.new(
        settings.lemonsqueezy_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not stdlib_secrets.compare_digest(expected, signature_header):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Firma inválida")


def _variant_to_plan(variant_id: str) -> Optional[TenantPlan]:
    settings = get_settings()
    if str(variant_id) == settings.lemonsqueezy_variant_starter:
        return TenantPlan.starter
    if str(variant_id) == settings.lemonsqueezy_variant_pro:
        return TenantPlan.pro
    return None


def _parse_renews_at(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Lemon Squeezy usa ISO 8601 con sufijo Z; fromisoformat lo soporta desde 3.11
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _resolve_tenant(
    db: AsyncSession, payload: dict
) -> Optional[Tenant]:
    # Prefiere meta.custom_data.tenant_id (lo embebemos al crear el checkout).
    # Fallback: lemon_customer_id que ya hayamos guardado en un evento anterior.
    repo = TenantRepository(db)
    custom = payload.get("meta", {}).get("custom_data") or {}
    raw_id = custom.get("tenant_id")
    if raw_id:
        try:
            tenant = await repo.get(UUID(raw_id))
            if tenant:
                return tenant
        except (ValueError, TypeError):
            pass

    # Fallback: por customer_id (en eventos posteriores como cancellation)
    customer_id = (
        payload.get("data", {}).get("attributes", {}).get("customer_id")
    )
    if customer_id is not None:
        from sqlalchemy import select
        stmt = select(Tenant).where(
            Tenant.lemon_customer_id == str(customer_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    return None


@router.post("/lemonsqueezy", status_code=status.HTTP_200_OK)
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
    x_event_name: Optional[str] = Header(default=None, alias="X-Event-Name"),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    _verify_signature(body, x_signature)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body no es JSON")

    event = x_event_name or payload.get("meta", {}).get("event_name")
    if not event:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta event_name")

    tenant = await _resolve_tenant(db, payload)
    if tenant is None:
        # Devolvemos 200 a propósito - si LS no recibe 2xx reintenta y vuelve
        # eternamente. Mejor logueamos y seguimos.
        logger.warning(
            "Webhook %s sin tenant resoluble: %s",
            event,
            payload.get("meta", {}).get("custom_data"),
        )
        return {"status": "ignored", "reason": "tenant_not_found"}

    attrs = payload.get("data", {}).get("attributes", {}) or {}
    sub_id = payload.get("data", {}).get("id")

    if event in ("subscription_created", "subscription_updated", "subscription_resumed"):
        plan = _variant_to_plan(str(attrs.get("variant_id"))) or tenant.plan
        tenant.plan = plan
        tenant.lemon_subscription_id = str(sub_id) if sub_id else tenant.lemon_subscription_id
        cust = attrs.get("customer_id")
        if cust is not None:
            tenant.lemon_customer_id = str(cust)
        tenant.subscription_status = attrs.get("status") or tenant.subscription_status
        tenant.subscription_renews_at = _parse_renews_at(attrs.get("renews_at"))

    elif event in ("subscription_cancelled", "subscription_expired"):
        # Cliente canceló o expiró - vuelve a free
        tenant.plan = TenantPlan.free
        tenant.subscription_status = attrs.get("status") or "cancelled"
        tenant.subscription_renews_at = None

    elif event in ("subscription_paused", "subscription_unpaused"):
        tenant.subscription_status = attrs.get("status") or tenant.subscription_status

    elif event == "subscription_payment_failed":
        tenant.subscription_status = "past_due"
        # TODO: mandarle email avisando, sino se entera cuando ya está past_due

    elif event in ("subscription_payment_success", "subscription_payment_recovered"):
        tenant.subscription_status = attrs.get("status") or "active"

    elif event == "order_created":
        # Por ahora ignoramos orders - el flujo lo manejamos vía subscription_*
        return {"status": "ignored", "reason": "order_event"}

    else:
        logger.info("Webhook event no manejado: %s", event)
        return {"status": "ignored", "reason": f"unhandled_event:{event}"}

    await db.commit()
    return {"status": "ok", "tenant_id": str(tenant.id), "event": event}
