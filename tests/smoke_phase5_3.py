r"""
Smoke test end-to-end de Fase 5.3 (landing + dashboard HTML).

Se corre como script:
    .\.venv\Scripts\python.exe -m tests.smoke_phase5_3

Cubre el flujo completo del browser:
   1.  GET / -> 200 HTML
   2.  GET /pricing -> 200 HTML con precios
   3.  GET /signup -> 200 con form
   4.  POST /signup datos válidos -> 303 /login?signed_up=1, email mockeado
   5.  POST /signup email duplicado -> 409
   6.  GET /login -> 200
   7.  POST /login sin verificar -> 403
   8.  GET /verify-email con token válido -> 200 success + key creada
   9.  GET /verify-email con token chocho -> 400
  10.  POST /login con creds correctas -> 303 + cookie seteada
  11.  GET /dashboard sin cookie -> 303 /login
  12.  GET /dashboard con cookie -> 200 con email del tenant
  13.  POST /dashboard/keys/new -> 303 /dashboard?new_key=psr_...
  14.  POST /dashboard/keys/{id}/revoke -> 303
  15.  POST /dashboard/keys/{id}/reactivate -> 303
  16.  GET /signup con cookie -> 303 /dashboard
  17.  POST /logout -> 303 / + cookie eliminada
  18.  GET /dashboard sin cookie (después de logout) -> 303 /login
  19.  POST /forgot-password -> 200 con flash genérico, token capturado
  20.  POST /reset-password con token -> 303 /login?password_reset=1
  21.  Login con nueva password -> OK
  22.  GET /api/v1/account/usage con cookie -> 200 con summary
  23.  Cleanup
"""
import asyncio
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.api.dependencies import SESSION_COOKIE_NAME
from app.db.models.tenant import Tenant
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services import email_service as email_module
from app.services.redis_client import redis_client


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


#  Email capturer 
class _Capture:
    is_live = False
    def __init__(self):
        self.verifications: list[tuple[str, str]] = []
        self.resets: list[tuple[str, str]] = []
    async def send_verification_email(self, *, to, token):
        self.verifications.append((to, token))
    async def send_password_reset_email(self, *, to, token):
        self.resets.append((to, token))
    async def send_welcome_email(self, *, to, api_key):
        pass


async def main() -> int:
    capture = _Capture()
    email_module._email_service = capture

    test_email = f"u53-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    test_password = "Pass1234"
    new_password = "NewPass5678"
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as c:
        print(f"\n>>> Smoke test Fase 5.3 -- email: {test_email}\n")

        # 1. GET / -> 200 HTML
        r = await c.get("/")
        check(r.status_code == 200, f"GET / -> 200 (got {r.status_code})")
        check("Parsero" in r.text, "Landing contiene 'Parsero'")
        check("text/html" in r.headers.get("content-type", ""), "Landing es HTML")

        # 2. GET /pricing
        r = await c.get("/pricing")
        check(r.status_code == 200, f"GET /pricing -> 200 (got {r.status_code})")
        check("$19" in r.text and "$79" in r.text, "Pricing muestra los 3 planes")

        # 3. GET /signup
        r = await c.get("/signup")
        check(r.status_code == 200, f"GET /signup -> 200 (got {r.status_code})")
        check("name=\"email\"" in r.text, "Signup form tiene input email")

        # 4. POST /signup OK
        r = await c.post(
            "/signup",
            data={"name": "Rafael Test", "email": test_email, "password": test_password},
        )
        check(
            r.status_code == 303 and r.headers.get("location") == "/login?signed_up=1",
            f"POST /signup -> 303 /login?signed_up=1 (got {r.status_code} / {r.headers.get('location')})",
        )
        check(len(capture.verifications) == 1, "Email de verificación capturado")
        verify_token = capture.verifications[0][1]

        # 5. POST /signup email duplicado
        r = await c.post(
            "/signup",
            data={"name": "Otro", "email": test_email, "password": "x12345678"},
        )
        check(r.status_code == 409, f"POST /signup duplicado -> 409 (got {r.status_code})")

        # 6. GET /login
        r = await c.get("/login")
        check(r.status_code == 200, f"GET /login -> 200 (got {r.status_code})")

        # 7. POST /login sin verificar -> 403
        r = await c.post(
            "/login", data={"email": test_email, "password": test_password}
        )
        check(r.status_code == 403, f"POST /login sin verificar -> 403 (got {r.status_code})")

        # 8. GET /verify-email con token válido
        r = await c.get(f"/verify-email?token={verify_token}")
        check(r.status_code == 200, f"GET /verify-email -> 200 (got {r.status_code})")
        check("verificado" in r.text.lower(), "verify-email muestra mensaje de éxito")

        # 9. GET /verify-email token chocho
        r = await c.get("/verify-email?token=not-a-jwt")
        check(r.status_code == 400, f"verify-email token inválido -> 400 (got {r.status_code})")

        # 10. POST /login con creds correctas -> 303 + cookie
        r = await c.post(
            "/login", data={"email": test_email, "password": test_password}
        )
        check(
            r.status_code == 303 and r.headers.get("location") == "/dashboard",
            f"POST /login -> 303 /dashboard (got {r.status_code} / {r.headers.get('location')})",
        )
        cookie = r.cookies.get(SESSION_COOKIE_NAME)
        check(cookie is not None, "Cookie parsero_session seteada")

        # Para los siguientes requests, mantenemos la cookie en el client
        c.cookies.set(SESSION_COOKIE_NAME, cookie)

        # 11. GET /dashboard sin cookie (cliente nuevo)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as c2:
            r = await c2.get("/dashboard")
            check(
                r.status_code == 303 and r.headers.get("location") == "/login",
                f"GET /dashboard sin cookie -> 303 /login (got {r.status_code})",
            )

        # 12. GET /dashboard con cookie
        r = await c.get("/dashboard")
        check(r.status_code == 200, f"GET /dashboard con cookie -> 200 (got {r.status_code})")
        check(test_email in r.text, "Dashboard muestra email del tenant")
        check("Plan Free" in r.text or "Free" in r.text, "Dashboard muestra plan actual")

        # 13. POST /dashboard/keys/new
        r = await c.post("/dashboard/keys/new", data={"name": "test-key"})
        check(
            r.status_code == 303 and "new_key=psr_" in (r.headers.get("location") or ""),
            f"crear key -> 303 con new_key (got {r.status_code} / {r.headers.get('location')})",
        )

        # Listar keys del tenant para tener el ID
        r = await c.get("/api/v1/account/keys")
        check(r.status_code == 200, f"GET /api/v1/account/keys -> 200 (got {r.status_code})")
        keys = r.json()
        # Filter only the one we just created (skip the default key from verify-email)
        new_keys = [k for k in keys if k["name"] == "test-key"]
        check(len(new_keys) == 1, f"hay 1 key con name='test-key' (got {len(new_keys)})")
        new_key_id = new_keys[0]["id"]

        # 14. revoke
        r = await c.post(f"/dashboard/keys/{new_key_id}/revoke")
        check(r.status_code == 303, f"revoke -> 303 (got {r.status_code})")

        # Verificar que quedó revocada
        r = await c.get("/api/v1/account/keys")
        revoked = next((k for k in r.json() if k["id"] == new_key_id), None)
        check(revoked and not revoked["is_active"], "key marcada como revocada")

        # 15. reactivate
        r = await c.post(f"/dashboard/keys/{new_key_id}/reactivate")
        check(r.status_code == 303, f"reactivate -> 303 (got {r.status_code})")
        r = await c.get("/api/v1/account/keys")
        reactivated = next((k for k in r.json() if k["id"] == new_key_id), None)
        check(reactivated and reactivated["is_active"], "key reactivada")

        # 16. GET /signup con cookie -> redirect /dashboard
        r = await c.get("/signup")
        check(
            r.status_code == 303 and r.headers.get("location") == "/dashboard",
            f"GET /signup con cookie -> 303 /dashboard (got {r.status_code})",
        )

        # 17. POST /logout
        r = await c.post("/logout")
        check(
            r.status_code == 303 and r.headers.get("location") == "/",
            f"POST /logout -> 303 / (got {r.status_code})",
        )

        # 18. Después del logout no hay cookie válida
        # (httpx debería haber recibido la cookie con max_age 0)
        c.cookies.delete(SESSION_COOKIE_NAME)
        r = await c.get("/dashboard")
        check(
            r.status_code == 303 and r.headers.get("location") == "/login",
            f"dashboard post-logout -> 303 /login (got {r.status_code})",
        )

        # 19. POST /forgot-password
        r = await c.post("/forgot-password", data={"email": test_email})
        check(r.status_code == 200, f"POST /forgot-password -> 200 (got {r.status_code})")
        check(
            "Si la cuenta existe" in r.text,
            "forgot-password devuelve mensaje genérico",
        )
        check(len(capture.resets) == 1, "Email de reset capturado")
        reset_token = capture.resets[0][1]

        # 20. POST /reset-password
        r = await c.post(
            "/reset-password",
            data={"token": reset_token, "new_password": new_password},
        )
        check(
            r.status_code == 303 and "password_reset=1" in (r.headers.get("location") or ""),
            f"reset-password -> 303 (got {r.status_code} / {r.headers.get('location')})",
        )

        # 21. Login con nueva password
        r = await c.post(
            "/login", data={"email": test_email, "password": new_password}
        )
        check(
            r.status_code == 303 and r.headers.get("location") == "/dashboard",
            f"login con nueva password -> 303 /dashboard (got {r.status_code})",
        )
        c.cookies.set(SESSION_COOKIE_NAME, r.cookies.get(SESSION_COOKIE_NAME))

        # 22. /api/v1/account/usage
        r = await c.get("/api/v1/account/usage")
        check(r.status_code == 200, f"account/usage -> 200 (got {r.status_code})")
        body = r.json()
        check(
            "billing_period" in body and "extractions_count" in body,
            "usage tiene los campos esperados",
        )

        # 23. Cleanup
        await cleanup(test_email)
        print(f"\n  cleanup: tenant {test_email} borrado")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'-' * 50}")
    if passed == total:
        print(f"  {PASS} {passed}/{total} checks pasaron -- Fase 5.3 OK\n")
        return 0
    print(f"  {FAIL} {passed}/{total} checks pasaron")
    for ok, label in results:
        if not ok:
            print(f"      {FAIL} {label}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
