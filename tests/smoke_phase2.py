r"""
Smoke test end-to-end de Fase 2 (auth + rate limit).

No es pytest -- se corre como script:
    .\.venv\Scripts\python.exe -m tests.smoke_phase2

Ejercita el flujo completo contra la BD/Redis reales:
  1. POST /admin/tenants sin token         -> 401
  2. POST /admin/tenants con token         -> 201
  3. POST /admin/tenants/{id}/keys         -> 201 (devuelve raw key)
  4. GET  /me sin Bearer                   -> 401
  5. GET  /me con Bearer valido            -> 200
  6. GET  /me con Bearer invalido          -> 401
  7. GET  /me/keys                         -> 200 (lista la key creada)
  8. 11 requests seguidas en plan free     -> la 11ma -> 429
  9. Cleanup: borra el tenant de prueba (cascade limpia api_keys)
"""
import asyncio
import sys
import uuid

# Forzar UTF-8 en stdout para que las flechas/ticks se impriman bien en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, text

from app.core.config import get_settings
from app.db.models.tenant import Tenant
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services.redis_client import redis_client

settings = get_settings()
ADMIN_TOKEN = settings.secret_key

# --- helpers --------------------------------------
PASS = "[ OK ]"
FAIL = "[FAIL]"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    icon = PASS if ok else FAIL
    print(f"  {icon} {label}")


async def cleanup(test_email: str) -> None:
    """Borra el tenant de prueba y sus claves rate-limit en Redis."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Tenant).where(Tenant.email == test_email))
        await db.commit()
    # Borra contadores de rate limit residuales (cualquier tenant_id que ya no exista)
    async for k in redis_client.scan_iter("ratelimit:*"):
        await redis_client.delete(k)
    async for k in redis_client.scan_iter("apikey:lastused:*"):
        await redis_client.delete(k)


# ─── tests ──────────────────────────────────────────
async def main() -> int:
    test_email = f"smoke-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        print(f"\n>>> Smoke test Fase 2 -- tenant: {test_email}\n")

        # 1. Admin sin token → 401
        r = await c.post("/admin/tenants", json={"name": "X", "email": test_email})
        check(r.status_code == 401, f"POST /admin/tenants sin token → 401 (got {r.status_code})")

        # 2. Admin con token → 201
        r = await c.post(
            "/admin/tenants",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "Smoke Test SA", "email": test_email, "plan": "free"},
        )
        check(r.status_code == 201, f"POST /admin/tenants con token → 201 (got {r.status_code})")
        if r.status_code != 201:
            print(f"    Body: {r.text}")
            await cleanup(test_email)
            return 1
        tenant_id = r.json()["id"]
        check(r.json()["plan"] == "free", "tenant.plan == 'free'")
        check(r.json()["is_active"] is True, "tenant.is_active == True")

        # 2b. Email duplicado → 409
        r = await c.post(
            "/admin/tenants",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "Dup", "email": test_email},
        )
        check(r.status_code == 409, f"POST /admin/tenants email duplicado → 409 (got {r.status_code})")

        # 3. Crear API key
        r = await c.post(
            f"/admin/tenants/{tenant_id}/keys",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "smoke-key"},
        )
        check(r.status_code == 201, f"POST /admin/tenants/.../keys → 201 (got {r.status_code})")
        if r.status_code != 201:
            print(f"    Body: {r.text}")
            await cleanup(test_email)
            return 1
        body = r.json()
        raw_key = body["key"]
        api_key_id = body["id"]
        check(raw_key.startswith("psr_"), f"raw key empieza con psr_ (got {raw_key[:6]}...)")
        check(body["key_prefix"] == raw_key[:12], "key_prefix coincide con primeros 12 chars")
        check(body["last_used_at"] is None, "last_used_at empieza en None")

        # 4. /me sin Bearer → 401
        r = await c.get("/me")
        check(r.status_code == 401, f"GET /me sin Bearer → 401 (got {r.status_code})")

        # 5. /me con Bearer válido → 200
        r = await c.get("/me", headers={"Authorization": f"Bearer {raw_key}"})
        check(r.status_code == 200, f"GET /me con Bearer válido → 200 (got {r.status_code})")
        if r.status_code == 200:
            check(r.json()["email"] == test_email, "GET /me devuelve el tenant correcto")

        # 6. Bearer inválido → 401
        r = await c.get("/me", headers={"Authorization": "Bearer psr_fake_key_xyz"})
        check(r.status_code == 401, f"GET /me Bearer inválido → 401 (got {r.status_code})")

        # 7. /me/keys lista la key
        r = await c.get("/me/keys", headers={"Authorization": f"Bearer {raw_key}"})
        check(r.status_code == 200, f"GET /me/keys → 200 (got {r.status_code})")
        if r.status_code == 200:
            keys = r.json()
            check(len(keys) == 1, f"GET /me/keys devuelve 1 elemento (got {len(keys)})")
            check(keys[0]["name"] == "smoke-key", "key.name == 'smoke-key'")

        # 8. Rate limit en plan free (10/min)
        # Limpiar contador previo del bucket actual
        async for k in redis_client.scan_iter(f"ratelimit:{tenant_id}:*"):
            await redis_client.delete(k)

        statuses = []
        for _ in range(11):
            rr = await c.get("/me", headers={"Authorization": f"Bearer {raw_key}"})
            statuses.append(rr.status_code)
        ok_count = sum(1 for s in statuses if s == 200)
        too_many = sum(1 for s in statuses if s == 429)
        check(ok_count == 10, f"primeras 10 reqs → 200 (got {ok_count})")
        check(too_many == 1, f"req #11 → 429 (got {too_many} de 11)")

        # 9. Revocar la key (admin desactiva)
        r = await c.patch(
            f"/admin/tenants/{tenant_id}/keys/{api_key_id}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"is_active": False},
        )
        check(
            r.status_code == 200 and r.json()["is_active"] is False,
            f"PATCH key is_active=false → 200 + is_active=False (got {r.status_code} / {r.json()})",
        )

        # 10. La key revocada ya no autentica (401, no 429 — debe cortar antes del rate limit)
        r = await c.get("/me", headers={"Authorization": f"Bearer {raw_key}"})
        check(
            r.status_code == 401 and "desactivada" in r.json().get("detail", "").lower(),
            f"GET /me con key revocada → 401 'desactivada' (got {r.status_code} / {r.json()})",
        )

        # 11. Reactivar la key
        r = await c.patch(
            f"/admin/tenants/{tenant_id}/keys/{api_key_id}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"is_active": True},
        )
        check(
            r.status_code == 200 and r.json()["is_active"] is True,
            f"PATCH key is_active=true → 200 + is_active=True (got {r.status_code})",
        )

        # 12. Limpiar contadores y verificar que la key reactivada vuelve a funcionar
        async for k in redis_client.scan_iter(f"ratelimit:{tenant_id}:*"):
            await redis_client.delete(k)
        r = await c.get("/me", headers={"Authorization": f"Bearer {raw_key}"})
        check(r.status_code == 200, f"GET /me con key reactivada → 200 (got {r.status_code})")

        # 13. Patch sobre key inexistente → 404
        import uuid as _uuid
        r = await c.patch(
            f"/admin/tenants/{tenant_id}/keys/{_uuid.uuid4()}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"is_active": False},
        )
        check(r.status_code == 404, f"PATCH key inexistente → 404 (got {r.status_code})")

        # 14. GET admin tenants — el de prueba aparece en la lista
        r = await c.get("/admin/tenants", headers={"X-Admin-Token": ADMIN_TOKEN})
        check(r.status_code == 200, f"GET /admin/tenants → 200 (got {r.status_code})")
        ids = [t["id"] for t in r.json()]
        check(tenant_id in ids, "tenant de prueba aparece en GET /admin/tenants")

        # 15. GET admin tenant por id
        r = await c.get(f"/admin/tenants/{tenant_id}", headers={"X-Admin-Token": ADMIN_TOKEN})
        check(
            r.status_code == 200 and r.json()["email"] == test_email,
            f"GET /admin/tenants/{{id}} → 200 con email correcto",
        )

        # 16. GET admin tenant inexistente → 404
        r = await c.get(f"/admin/tenants/{_uuid.uuid4()}", headers={"X-Admin-Token": ADMIN_TOKEN})
        check(r.status_code == 404, f"GET /admin/tenants/{{id}} inexistente → 404 (got {r.status_code})")

        # 17. GET admin keys del tenant — incluye la key creada
        r = await c.get(
            f"/admin/tenants/{tenant_id}/keys",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        check(r.status_code == 200, f"GET /admin/tenants/{{id}}/keys → 200 (got {r.status_code})")
        if r.status_code == 200:
            key_ids = [k["id"] for k in r.json()]
            check(api_key_id in key_ids, "key creada aparece en GET /admin/tenants/{id}/keys")

        # 18. Cleanup
        await cleanup(test_email)
        print(f"\n  cleanup: tenant {test_email} borrado")

    # --- reporte --------------------------------------
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'-' * 50}")
    if passed == total:
        print(f"  {PASS} {passed}/{total} checks pasaron -- Fase 2 OK\n")
        return 0
    print(f"  {FAIL} {passed}/{total} checks pasaron")
    for ok, label in results:
        if not ok:
            print(f"      {FAIL} {label}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
