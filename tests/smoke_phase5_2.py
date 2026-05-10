r"""
Smoke test end-to-end de Fase 5.2 (billing con Lemon Squeezy).

Se corre como script:
    .\.venv\Scripts\python.exe -m tests.smoke_phase5_2

NO usa Lemon Squeezy real para no contaminar la cuenta. En su lugar:
  - El servicio LemonSqueezyService se mockea para devolver URLs falsas
  - Los webhooks se firman localmente con HMAC y se postean al endpoint real
  - El flujo de actualización del tenant en BD se valida punta a punta

Cubre:
  1.  POST /billing/checkout sin JWT -> 401
  2.  POST /billing/checkout con JWT + plan starter -> 200 con checkout_url
  3.  POST /billing/checkout con plan inválido -> 422 (Pydantic)
  4.  POST /billing/portal sin suscripción -> 400
  5.  POST /webhooks/lemonsqueezy sin firma -> 401
  6.  POST /webhooks/lemonsqueezy con firma mala -> 401
  7.  POST /webhooks subscription_created firmado correcto -> 200
       y tenant.plan == 'starter', lemon_subscription_id, etc.
  8.  POST /billing/portal después del subscription_created -> 200
  9.  POST /webhooks subscription_updated a pro -> tenant.plan == 'pro'
  10. POST /webhooks subscription_payment_failed -> status='past_due'
  11. POST /webhooks subscription_cancelled -> tenant.plan == 'free'
  12. POST /webhooks evento desconocido -> 200 ignored
  13. POST /webhooks tenant inexistente -> 200 ignored
  14. Webhook idempotente: re-postear el mismo subscription_created no rompe
  15. Cleanup
"""
import asyncio
import hashlib
import hmac
import json
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models.tenant import Tenant
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services import email_service as email_module
from app.services import lemonsqueezy_service as ls_module
from app.services.redis_client import redis_client


settings = get_settings()
PASS = "[ OK ]"
FAIL = "[FAIL]"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"  {PASS if ok else FAIL} {label}")


async def cleanup(*emails: str) -> None:
    async with AsyncSessionLocal() as db:
        for em in emails:
            await db.execute(delete(Tenant).where(Tenant.email == em))
        await db.commit()
    async for k in redis_client.scan_iter("ratelimit:*"):
        await redis_client.delete(k)
    async for k in redis_client.scan_iter("apikey:lastused:*"):
        await redis_client.delete(k)


#  Mocks 
class _FakeEmailService:
    is_live = False
    async def send_verification_email(self, **kw): pass
    async def send_password_reset_email(self, **kw): pass
    async def send_welcome_email(self, **kw): pass


class _FakeLemonSqueezy:
    """Mock del LS client. No hace HTTP real."""
    async def create_checkout_url(self, *, variant_id, tenant_id, tenant_email, success_redirect_url=None):
        return f"https://parsero.lemonsqueezy.com/checkout/buy/fake-{variant_id}-{tenant_id}"

    async def get_subscription(self, subscription_id):
        return {
            "id": subscription_id,
            "attributes": {
                "urls": {"customer_portal": f"https://parsero.lemonsqueezy.com/portal/{subscription_id}"}
            },
        }

    async def get_customer_portal_url(self, subscription_id):
        return f"https://parsero.lemonsqueezy.com/portal/{subscription_id}"


def sign_payload(payload: dict, secret: str) -> tuple[bytes, str]:
    """Serializa el payload tal como Lemon Squeezy lo manda y firma con HMAC-SHA256."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, sig


def make_subscription_payload(*, event: str, tenant_id: str, sub_id: str, variant_id: str,
                              customer_id: int, status: str = "active") -> dict:
    return {
        "meta": {
            "event_name": event,
            "custom_data": {"tenant_id": tenant_id},
        },
        "data": {
            "type": "subscriptions",
            "id": sub_id,
            "attributes": {
                "store_id": int(settings.lemonsqueezy_store_id or "0"),
                "customer_id": customer_id,
                "variant_id": int(variant_id),
                "status": status,
                "renews_at": "2026-12-01T00:00:00.000000Z",
                "urls": {"customer_portal": f"https://parsero.lemonsqueezy.com/portal/{sub_id}"},
            },
        },
    }


async def get_tenant(tenant_id: str) -> Tenant:
    async with AsyncSessionLocal() as db:
        return await db.get(Tenant, uuid.UUID(tenant_id))


async def main() -> int:
    if not settings.lemonsqueezy_webhook_secret:
        print("[FAIL] LEMONSQUEEZY_WEBHOOK_SECRET no configurado en .env")
        return 1
    if not settings.lemonsqueezy_variant_starter or not settings.lemonsqueezy_variant_pro:
        print("[FAIL] LEMONSQUEEZY_VARIANT_STARTER/PRO no configurados en .env")
        return 1

    # Mockear email + LS service
    email_module._email_service = _FakeEmailService()
    ls_module._service = _FakeLemonSqueezy()

    test_email = f"u52-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        print(f"\n>>> Smoke test Fase 5.2 -- email: {test_email}\n")

        # Setup: signup + verify (reusamos el flujo de Fase 5.1)
        r = await c.post(
            "/api/v1/auth/signup",
            json={"name": "Rafael 52", "email": test_email, "password": "Pass1234"},
        )
        if r.status_code != 201:
            print(f"    Setup signup falló: {r.text}")
            return 1
        tenant_id = r.json()["tenant_id"]

        # Activar la cuenta directamente vía BD (no necesitamos email real para este test)
        async with AsyncSessionLocal() as db:
            t = await db.get(Tenant, uuid.UUID(tenant_id))
            from datetime import datetime, timezone
            t.email_verified_at = datetime.now(timezone.utc)
            t.is_active = True
            await db.commit()

        # Login
        r = await c.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "Pass1234"},
        )
        if r.status_code != 200:
            print(f"    Setup login falló: {r.text}")
            await cleanup(test_email)
            return 1
        jwt = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {jwt}"}

        # --- 1. /billing/checkout sin JWT -> 401 
        r = await c.post("/api/v1/billing/checkout", json={"plan": "starter"})
        check(r.status_code == 401, f"checkout sin JWT -> 401 (got {r.status_code})")

        # --- 2. /billing/checkout con JWT + starter 
        r = await c.post(
            "/api/v1/billing/checkout",
            headers=auth,
            json={"plan": "starter"},
        )
        check(r.status_code == 200, f"checkout starter -> 200 (got {r.status_code})")
        if r.status_code == 200:
            check(
                r.json()["checkout_url"].startswith("https://parsero.lemonsqueezy.com/checkout"),
                "checkout devuelve URL válida",
            )

        # --- 3. /billing/checkout con plan inválido 
        r = await c.post(
            "/api/v1/billing/checkout", headers=auth, json={"plan": "ultra"}
        )
        check(
            r.status_code == 422,
            f"checkout plan inválido -> 422 (got {r.status_code})",
        )

        # --- 4. /billing/portal sin suscripción -> 400 
        r = await c.post("/api/v1/billing/portal", headers=auth)
        check(
            r.status_code == 400,
            f"portal sin sub -> 400 (got {r.status_code})",
        )

        # --- 5. webhook sin firma -> 401 
        r = await c.post(
            "/webhooks/lemonsqueezy",
            json={"meta": {"event_name": "test"}, "data": {}},
        )
        check(
            r.status_code == 401,
            f"webhook sin firma -> 401 (got {r.status_code})",
        )

        # --- 6. webhook con firma mala -> 401 
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=b'{"x": 1}',
            headers={"X-Signature": "bad-sig", "X-Event-Name": "subscription_created"},
        )
        check(
            r.status_code == 401,
            f"webhook firma mala -> 401 (got {r.status_code})",
        )

        # --- 7. subscription_created firmado correcto 
        sub_id = "sub_test_001"
        cust_id = 99001
        payload = make_subscription_payload(
            event="subscription_created",
            tenant_id=tenant_id,
            sub_id=sub_id,
            variant_id=settings.lemonsqueezy_variant_starter,
            customer_id=cust_id,
        )
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={
                "X-Signature": sig,
                "X-Event-Name": "subscription_created",
                "Content-Type": "application/json",
            },
        )
        check(
            r.status_code == 200,
            f"webhook subscription_created -> 200 (got {r.status_code})",
        )
        if r.status_code == 200:
            check(r.json()["status"] == "ok", "webhook devuelve status=ok")
            t = await get_tenant(tenant_id)
            check(t.plan.value == "starter", f"tenant.plan == 'starter' (got {t.plan.value})")
            check(
                t.lemon_subscription_id == sub_id,
                f"tenant.lemon_subscription_id persistido (got {t.lemon_subscription_id})",
            )
            check(
                t.lemon_customer_id == str(cust_id),
                f"tenant.lemon_customer_id persistido (got {t.lemon_customer_id})",
            )
            check(t.subscription_status == "active", "subscription_status == active")

        # --- 8. portal después de subscription_created 
        r = await c.post("/api/v1/billing/portal", headers=auth)
        check(r.status_code == 200, f"portal con sub -> 200 (got {r.status_code})")
        if r.status_code == 200:
            check(
                "portal" in r.json()["portal_url"],
                "portal_url devuelta correctamente",
            )

        # --- 9. subscription_updated a pro 
        payload = make_subscription_payload(
            event="subscription_updated",
            tenant_id=tenant_id,
            sub_id=sub_id,
            variant_id=settings.lemonsqueezy_variant_pro,
            customer_id=cust_id,
        )
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "X-Event-Name": "subscription_updated"},
        )
        check(r.status_code == 200, f"subscription_updated -> 200 (got {r.status_code})")
        t = await get_tenant(tenant_id)
        check(t.plan.value == "pro", f"tenant upgraded a pro (got {t.plan.value})")

        # --- 10. payment_failed -> past_due 
        payload = make_subscription_payload(
            event="subscription_payment_failed",
            tenant_id=tenant_id,
            sub_id=sub_id,
            variant_id=settings.lemonsqueezy_variant_pro,
            customer_id=cust_id,
            status="past_due",
        )
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "X-Event-Name": "subscription_payment_failed"},
        )
        check(r.status_code == 200, f"payment_failed -> 200 (got {r.status_code})")
        t = await get_tenant(tenant_id)
        check(
            t.subscription_status == "past_due",
            f"subscription_status == past_due (got {t.subscription_status})",
        )

        # --- 11. cancelled -> plan vuelve a free 
        payload = make_subscription_payload(
            event="subscription_cancelled",
            tenant_id=tenant_id,
            sub_id=sub_id,
            variant_id=settings.lemonsqueezy_variant_pro,
            customer_id=cust_id,
            status="cancelled",
        )
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "X-Event-Name": "subscription_cancelled"},
        )
        check(r.status_code == 200, f"subscription_cancelled -> 200 (got {r.status_code})")
        t = await get_tenant(tenant_id)
        check(t.plan.value == "free", f"tenant downgraded a free (got {t.plan.value})")
        check(
            t.subscription_renews_at is None,
            "subscription_renews_at se limpió al cancelar",
        )

        # --- 12. evento desconocido -> 200 ignored 
        payload = {
            "meta": {"event_name": "license_key_created", "custom_data": {"tenant_id": tenant_id}},
            "data": {"type": "license_keys", "id": "lk_x", "attributes": {}},
        }
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "X-Event-Name": "license_key_created"},
        )
        check(
            r.status_code == 200 and r.json().get("status") == "ignored",
            f"evento desconocido -> 200 ignored (got {r.status_code} / {r.json()})",
        )

        # --- 13. tenant inexistente -> 200 ignored 
        bogus = str(uuid.uuid4())
        payload = make_subscription_payload(
            event="subscription_created",
            tenant_id=bogus,
            sub_id="sub_x",
            variant_id=settings.lemonsqueezy_variant_starter,
            customer_id=99999,
        )
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        r = await c.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "X-Event-Name": "subscription_created"},
        )
        check(
            r.status_code == 200 and r.json().get("status") == "ignored",
            f"tenant fantasma -> 200 ignored (got {r.status_code} / {r.json()})",
        )

        # --- 14. Idempotencia: re-postear el mismo evento 
        # Re-aplicamos subscription_created -> tenant debe quedar en starter de nuevo
        payload = make_subscription_payload(
            event="subscription_created",
            tenant_id=tenant_id,
            sub_id=sub_id,
            variant_id=settings.lemonsqueezy_variant_starter,
            customer_id=cust_id,
        )
        body, sig = sign_payload(payload, settings.lemonsqueezy_webhook_secret)
        for _ in range(3):
            r = await c.post(
                "/webhooks/lemonsqueezy",
                content=body,
                headers={"X-Signature": sig, "X-Event-Name": "subscription_created"},
            )
            if r.status_code != 200:
                break
        check(
            r.status_code == 200,
            f"Webhook idempotente (3 retries) -> 200 (got {r.status_code})",
        )
        t = await get_tenant(tenant_id)
        check(t.plan.value == "starter", f"3x subscription_created -> plan starter (got {t.plan.value})")

        # --- 15. Cleanup 
        await cleanup(test_email)
        print(f"\n  cleanup: tenant {test_email} borrado")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'-' * 50}")
    if passed == total:
        print(f"  {PASS} {passed}/{total} checks pasaron -- Fase 5.2 OK\n")
        return 0
    print(f"  {FAIL} {passed}/{total} checks pasaron")
    for ok, label in results:
        if not ok:
            print(f"      {FAIL} {label}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
