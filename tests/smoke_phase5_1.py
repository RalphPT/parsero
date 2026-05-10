r"""
Smoke test end-to-end de Fase 5.1 (auth pública).

Se corre como script:
    .\.venv\Scripts\python.exe -m tests.smoke_phase5_1

Cubre el flujo completo de auth pública:
   1.  POST /auth/signup -> 201, tenant inactivo, email mockeado
   2.  POST /auth/signup mismo email -> 409
   3.  POST /auth/login antes de verificar email -> 403
   4.  GET  /auth/verify-email con token válido -> 200 + API key creada
   5.  GET  /auth/verify-email idempotente -> 200 sin nueva key
   6.  GET  /auth/verify-email token inválido -> 400
   7.  POST /auth/login con password correcta -> 200 + JWT
   8.  POST /auth/login con password incorrecta -> 401
   9.  GET  /account/me con JWT válido -> 200
  10.  GET  /account/me sin JWT -> 401
  11.  GET  /account/me con JWT inválido -> 401
  12.  GET  /account/me con JWT de wrong purpose -> 401
  13.  POST /auth/forgot-password email inexistente -> 202 (no revela)
  14.  POST /auth/forgot-password email existente -> 202 + token capturado
  15.  POST /auth/reset-password con token -> 204
  16.  Login con nueva password -> 200
  17.  Login con password vieja -> 401
  18.  POST /auth/resend-verification cuenta no verificada -> 202
  19.  La API key entregada en verify-email funciona en /me
  20.  Cleanup
"""
import asyncio
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.jwt_tokens import create_token
from app.db.models.tenant import Tenant
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services import email_service as email_module
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


#  Email capturer 
class _CapturingEmailService:
    """Reemplaza al email service real durante el test. Guarda los tokens
    de los links de verificación / reset que normalmente irían por email."""

    def __init__(self):
        self.verification_tokens: list[tuple[str, str]] = []  # (email, token)
        self.reset_tokens: list[tuple[str, str]] = []
        self.welcome_keys: list[tuple[str, str]] = []

    @property
    def is_live(self) -> bool:
        return False

    async def send_verification_email(self, *, to: str, token: str) -> None:
        self.verification_tokens.append((to, token))

    async def send_password_reset_email(self, *, to: str, token: str) -> None:
        self.reset_tokens.append((to, token))

    async def send_welcome_email(self, *, to: str, api_key: str) -> None:
        self.welcome_keys.append((to, api_key))


async def main() -> int:
    capture = _CapturingEmailService()
    # Override del singleton del email service
    email_module._email_service = capture

    test_email = f"u-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    test_password = "SuperSecret123"
    new_password = "OtroSecret456"
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        print(f"\n>>> Smoke test Fase 5.1 -- email: {test_email}\n")

        # --- 1. Signup 
        r = await c.post(
            "/auth/signup",
            json={"name": "Rafael Test", "email": test_email, "password": test_password},
        )
        check(r.status_code == 201, f"POST /auth/signup -> 201 (got {r.status_code})")
        if r.status_code != 201:
            print(f"    Body: {r.text}")
            await cleanup(test_email)
            return 1
        tenant_id = r.json()["tenant_id"]
        check(
            len(capture.verification_tokens) == 1,
            f"Email de verificación enviado (got {len(capture.verification_tokens)})",
        )
        check(
            capture.verification_tokens[0][0] == test_email,
            "Email de verificación va al destinatario correcto",
        )

        # --- 2. Signup duplicado 
        r = await c.post(
            "/auth/signup",
            json={"name": "Otro", "email": test_email, "password": "x12345678"},
        )
        check(
            r.status_code == 409,
            f"POST /auth/signup email duplicado -> 409 (got {r.status_code})",
        )

        # --- 3. Login antes de verificar -> 403 
        r = await c.post(
            "/auth/login",
            json={"email": test_email, "password": test_password},
        )
        check(
            r.status_code == 403,
            f"POST /auth/login sin verificar -> 403 (got {r.status_code})",
        )

        # --- 4. Verify-email con token válido 
        verify_token = capture.verification_tokens[0][1]
        r = await c.get(f"/auth/verify-email?token={verify_token}")
        check(
            r.status_code == 200,
            f"GET /auth/verify-email -> 200 (got {r.status_code})",
        )
        verify_body = r.json()
        check(
            verify_body.get("api_key", "").startswith("psr_"),
            f"verify-email devuelve raw API key (got {verify_body.get('api_key', '')[:8]}...)",
        )
        first_api_key = verify_body["api_key"]
        check(
            len(capture.welcome_keys) == 1,
            "Email de bienvenida enviado",
        )

        # --- 5. Verify-email idempotente 
        r = await c.get(f"/auth/verify-email?token={verify_token}")
        check(
            r.status_code == 200 and r.json().get("api_key") is None,
            f"verify-email idempotente -> sin nueva key (got status={r.status_code}, key={r.json().get('api_key')})",
        )

        # --- 6. Verify-email con token chocho 
        r = await c.get("/auth/verify-email?token=not-a-real-jwt")
        check(
            r.status_code == 400,
            f"verify-email token inválido -> 400 (got {r.status_code})",
        )

        # --- 7. Login con password correcta 
        r = await c.post(
            "/auth/login",
            json={"email": test_email, "password": test_password},
        )
        check(r.status_code == 200, f"POST /auth/login -> 200 (got {r.status_code})")
        login_body = r.json()
        check(
            "access_token" in login_body and login_body.get("token_type") == "bearer",
            "Login devuelve access_token",
        )
        session_jwt = login_body["access_token"]
        check(
            login_body.get("email_verified") is True,
            "Login devuelve email_verified=True",
        )

        # --- 8. Login con password mala 
        r = await c.post(
            "/auth/login",
            json={"email": test_email, "password": "passwordequivocado"},
        )
        check(
            r.status_code == 401,
            f"POST /auth/login password mal -> 401 (got {r.status_code})",
        )

        # --- 9. GET /account/me con JWT 
        r = await c.get(
            "/account/me",
            headers={"Authorization": f"Bearer {session_jwt}"},
        )
        check(
            r.status_code == 200,
            f"GET /account/me con JWT -> 200 (got {r.status_code})",
        )
        if r.status_code == 200:
            check(
                r.json().get("email") == test_email,
                "GET /account/me devuelve el tenant correcto",
            )
            check(
                r.json().get("email_verified_at") is not None,
                "GET /account/me incluye email_verified_at",
            )

        # --- 10. /account/me sin JWT 
        r = await c.get("/account/me")
        check(
            r.status_code == 401,
            f"GET /account/me sin JWT -> 401 (got {r.status_code})",
        )

        # --- 11. /account/me con JWT inválido 
        r = await c.get(
            "/account/me", headers={"Authorization": "Bearer not.a.jwt"}
        )
        check(
            r.status_code == 401,
            f"GET /account/me JWT inválido -> 401 (got {r.status_code})",
        )

        # --- 12. /account/me con JWT de wrong purpose 
        # Usamos el verification token (purpose=email_verify) como si fuera session
        r = await c.get(
            "/account/me",
            headers={"Authorization": f"Bearer {verify_token}"},
        )
        check(
            r.status_code == 401,
            f"GET /account/me con JWT wrong purpose -> 401 (got {r.status_code})",
        )

        # --- 13. forgot-password email inexistente -> 202 
        r = await c.post(
            "/auth/forgot-password",
            json={"email": "no-existe-en-bd@parsero-smoke.com"},
        )
        check(
            r.status_code == 202,
            f"forgot-password email inexistente -> 202 (got {r.status_code})",
        )
        check(
            len(capture.reset_tokens) == 0,
            "No se envió email de reset para cuenta inexistente",
        )

        # --- 14. forgot-password email existente 
        r = await c.post(
            "/auth/forgot-password", json={"email": test_email}
        )
        check(
            r.status_code == 202,
            f"forgot-password email existente -> 202 (got {r.status_code})",
        )
        check(
            len(capture.reset_tokens) == 1,
            "Email de reset enviado",
        )

        # --- 15. reset-password 
        reset_token = capture.reset_tokens[0][1]
        r = await c.post(
            "/auth/reset-password",
            json={"token": reset_token, "new_password": new_password},
        )
        check(
            r.status_code == 204,
            f"reset-password -> 204 (got {r.status_code})",
        )

        # --- 16. Login con nueva password -> 200 
        r = await c.post(
            "/auth/login",
            json={"email": test_email, "password": new_password},
        )
        check(
            r.status_code == 200,
            f"Login con nueva password -> 200 (got {r.status_code})",
        )

        # --- 17. Login con password vieja -> 401 
        r = await c.post(
            "/auth/login",
            json={"email": test_email, "password": test_password},
        )
        check(
            r.status_code == 401,
            f"Login con password vieja -> 401 (got {r.status_code})",
        )

        # --- 18. resend-verification para cuenta verificada -> 202 sin email
        capture.verification_tokens.clear()
        r = await c.post(
            "/auth/resend-verification", json={"email": test_email}
        )
        check(
            r.status_code == 202,
            f"resend-verification cuenta verificada -> 202 (got {r.status_code})",
        )
        check(
            len(capture.verification_tokens) == 0,
            "No se reenvía email si la cuenta YA está verificada",
        )

        # --- 19. La API key entregada en verify funciona 
        async for k in redis_client.scan_iter(f"ratelimit:{tenant_id}:*"):
            await redis_client.delete(k)
        r = await c.get("/me", headers={"Authorization": f"Bearer {first_api_key}"})
        check(
            r.status_code == 200 and r.json()["email"] == test_email,
            f"GET /me con la API key creada en verify -> 200 (got {r.status_code})",
        )

        # --- 20. Cleanup 
        await cleanup(test_email)
        print(f"\n  cleanup: tenant {test_email} borrado")

    # Reporte
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'-' * 50}")
    if passed == total:
        print(f"  {PASS} {passed}/{total} checks pasaron -- Fase 5.1 OK\n")
        return 0
    print(f"  {FAIL} {passed}/{total} checks pasaron")
    for ok, label in results:
        if not ok:
            print(f"      {FAIL} {label}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
