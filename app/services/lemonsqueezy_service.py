# Cliente para la API de Lemon Squeezy. Solo usamos checkouts y subscriptions
# por ahora; el resto del catálogo (orders, customers crudos) no lo tocamos.
from typing import Optional
from uuid import UUID

import httpx

from app.core.config import get_settings


LEMONSQUEEZY_API = "https://api.lemonsqueezy.com/v1"


class LemonSqueezyError(RuntimeError):
    pass


class LemonSqueezyService:
    def __init__(self):
        settings = get_settings()
        if not settings.lemonsqueezy_api_key:
            raise RuntimeError("LEMONSQUEEZY_API_KEY no configurado en .env")
        if not settings.lemonsqueezy_store_id:
            raise RuntimeError("LEMONSQUEEZY_STORE_ID no configurado en .env")
        self._api_key = settings.lemonsqueezy_api_key
        self._store_id = settings.lemonsqueezy_store_id

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }

    async def create_checkout_url(
        self,
        *,
        variant_id: str,
        tenant_id: UUID,
        tenant_email: str,
        success_redirect_url: Optional[str] = None,
    ) -> str:
        # Embebemos tenant_id en custom_data - es el único enlace que tenemos
        # entre la subscription que crea LS y el tenant nuestro cuando llega
        # el webhook.
        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": tenant_email,
                        "custom": {"tenant_id": str(tenant_id)},
                    },
                    "checkout_options": {"embed": False},
                    "product_options": {
                        "redirect_url": success_redirect_url
                        or f"{get_settings().public_base_url}/dashboard?upgraded=1"
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": self._store_id}},
                    "variant": {"data": {"type": "variants", "id": variant_id}},
                },
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{LEMONSQUEEZY_API}/checkouts",
                headers=self._headers,
                json=payload,
            )
        if resp.status_code >= 400:
            raise LemonSqueezyError(
                f"create_checkout_url -> {resp.status_code}: {resp.text}"
            )
        return resp.json()["data"]["attributes"]["url"]

    async def get_subscription(self, subscription_id: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{LEMONSQUEEZY_API}/subscriptions/{subscription_id}",
                headers=self._headers,
            )
        if resp.status_code >= 400:
            raise LemonSqueezyError(
                f"get_subscription -> {resp.status_code}: {resp.text}"
            )
        return resp.json()["data"]

    async def get_customer_portal_url(self, subscription_id: str) -> str:
        # Portal hosted donde el cliente puede cambiar tarjeta, cancelar, etc.
        sub = await self.get_subscription(subscription_id)
        urls = sub.get("attributes", {}).get("urls", {})
        portal_url = urls.get("customer_portal")
        if not portal_url:
            raise LemonSqueezyError(
                "Subscription sin customer_portal URL - ¿está cancelada/expirada?"
            )
        return portal_url


_service: Optional[LemonSqueezyService] = None


def get_lemonsqueezy_service() -> LemonSqueezyService:
    global _service
    if _service is None:
        _service = LemonSqueezyService()
    return _service
