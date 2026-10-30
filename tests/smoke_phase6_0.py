r"""
Smoke test de Fase 6.0 (API lista para un frontend separado).

    .\.venv\Scripts\python.exe -m tests.smoke_phase6_0

Cubre /account/jobs, rate_limit en /account/me, logout, CORS_ORIGINS y
FRONTEND_URL en los links de email.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.core.config import Settings
from app.db.models.extraction_job import ExtractionJob, JobStatus, SchemaType
from app.db.models.extraction_result import ExtractionResult
from app.db.models.tenant import Tenant
from app.db.models.usage_log import UsageLog
from app.db.repositories.api_key import ApiKeyRepository
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


class _CapturingEmailService:
    def __init__(self):
        self.verification_tokens: list[tuple[str, str]] = []

    @property
    def is_live(self) -> bool:
        return False

    async def send_verification_email(self, *, to: str, token: str) -> None:
        self.verification_tokens.append((to, token))

    async def send_password_reset_email(self, *, to: str, token: str) -> None:
        pass

    async def send_welcome_email(self, *, to: str, api_key: str) -> None:
        pass


async def create_account(c: AsyncClient, capture: _CapturingEmailService, email: str):
    password = "SuperSecret123"
    r = await c.post(
        "/auth/signup", json={"name": "Smoke Test", "email": email, "password": password}
    )
    tenant_id = r.json()["tenant_id"]
    token = capture.verification_tokens[-1][1]
    await c.get(f"/auth/verify-email?token={token}")
    r = await c.post("/auth/login", json={"email": email, "password": password})
    return tenant_id, {"Authorization": f"Bearer {r.json()['access_token']}"}


async def seed_jobs(tenant_id: str, count: int) -> list[str]:
    job_ids: list[str] = []
    async with AsyncSessionLocal() as db:
        keys = await ApiKeyRepository(db).list_for_tenant(uuid.UUID(tenant_id))
        api_key_id = keys[0].id
        base = datetime.now(timezone.utc)
        for i in range(count):
            job = ExtractionJob(
                tenant_id=uuid.UUID(tenant_id),
                api_key_id=api_key_id,
                schema_type=SchemaType.invoice,
                status=JobStatus.completed if i == 0 else JobStatus.failed,
                source_url=f"https://example.com/doc-{i}.pdf",
                source_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                input_tokens=100 + i,
                output_tokens=50 + i,
                duration_ms=1000 + i,
                error_message=None if i == 0 else "boom",
                created_at=base + timedelta(seconds=i),
            )
            db.add(job)
            await db.flush()
            if i == 0:
                db.add(ExtractionResult(job_id=job.id, data={"total": 42}))
                db.add(
                    UsageLog(
                        tenant_id=uuid.UUID(tenant_id),
                        job_id=job.id,
                        input_tokens=100,
                        output_tokens=50,
                        cost_usd=0,
                        billing_period=base.strftime("%Y-%m"),
                    )
                )
            job_ids.append(str(job.id))
        await db.commit()
    return job_ids


async def main() -> int:
    capture = _CapturingEmailService()
    email_module._email_service = capture

    email_a = f"a-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    email_b = f"b-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        print(f"\n>>> Smoke test Fase 6.0 -- {email_a}\n")

        tenant_a, auth_a = await create_account(c, capture, email_a)
        tenant_b, auth_b = await create_account(c, capture, email_b)
        jobs_a = await seed_jobs(tenant_a, 3)
        jobs_b = await seed_jobs(tenant_b, 1)

        r = await c.get("/account/me", headers=auth_a)
        check(r.status_code == 200, f"GET /account/me -> 200 (got {r.status_code})")
        check(
            r.json().get("rate_limit_per_minute") == 10,
            f"/account/me trae rate_limit_per_minute=10 para free (got {r.json().get('rate_limit_per_minute')})",
        )
        check(r.json().get("plan") == "free", "/account/me sigue devolviendo plan='free'")

        r = await c.get("/account/jobs", headers=auth_a)
        body = r.json()
        check(r.status_code == 200, f"GET /account/jobs -> 200 (got {r.status_code})")
        check(body.get("total") == 3, f"total=3 (got {body.get('total')})")
        check(len(body.get("items", [])) == 3, "items trae los 3 jobs del tenant")
        created = [i["created_at"] for i in body["items"]]
        check(created == sorted(created, reverse=True), "Orden por created_at desc")
        check(
            body["items"][0]["status"] in ("completed", "failed")
            and body["items"][0]["schema_type"] == "invoice",
            "status y schema_type salen como string plano",
        )
        r = await c.get("/account/jobs?limit=2&offset=2", headers=auth_a)
        body = r.json()
        check(
            len(body["items"]) == 1 and body["total"] == 3 and body["offset"] == 2,
            "Paginación limit=2&offset=2 -> 1 item, total=3",
        )
        ids_b = [i["id"] for i in (await c.get("/account/jobs", headers=auth_b)).json()["items"]]
        check(ids_b == jobs_b, "Tenant B solo ve sus propios jobs")

        r = await c.get("/account/jobs")
        check(r.status_code == 401, f"GET /account/jobs sin JWT -> 401 (got {r.status_code})")
        r = await c.get("/account/jobs?limit=1000", headers=auth_a)
        check(r.status_code == 422, f"limit=1000 -> 422 (got {r.status_code})")

        completed_id = next(
            i["id"]
            for i in (await c.get("/account/jobs", headers=auth_a)).json()["items"]
            if i["status"] == "completed"
        )
        r = await c.get(f"/account/jobs/{completed_id}", headers=auth_a)
        check(r.status_code == 200, f"GET /account/jobs/{{id}} -> 200 (got {r.status_code})")
        check(r.json().get("data") == {"total": 42}, "Detalle incluye el JSON extraído")
        failed_id = next(j for j in jobs_a if j != completed_id)
        r = await c.get(f"/account/jobs/{failed_id}", headers=auth_a)
        check(
            r.status_code == 200
            and r.json().get("data") is None
            and r.json().get("error_message") == "boom",
            "Job fallido -> data=None + error_message",
        )

        r = await c.get(f"/account/jobs/{jobs_b[0]}", headers=auth_a)
        check(r.status_code == 404, f"Job de otro tenant -> 404 (got {r.status_code})")
        r = await c.get(f"/account/jobs/{uuid.uuid4()}", headers=auth_a)
        check(r.status_code == 404, f"Job inexistente -> 404 (got {r.status_code})")

        r = await c.get("/account/usage", headers=auth_a)
        check(
            r.status_code == 200
            and r.json().get("extractions_count") == 1
            and r.json().get("total_tokens") == 150,
            f"/account/usage -> 1 extracción, 150 tokens (got {r.json()})",
        )

        r = await c.post("/auth/logout")
        check(r.status_code == 204, f"POST /auth/logout -> 204 (got {r.status_code})")
        set_cookie = r.headers.get("set-cookie", "")
        check(
            "parsero_session" in set_cookie and "Max-Age=0" in set_cookie,
            "Logout borra la cookie parsero_session",
        )

        r = await c.options(
            "/account/me",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        check(
            r.status_code == 200 and "access-control-allow-origin" in r.headers,
            f"Preflight CORS desde localhost:5173 -> 200 (got {r.status_code})",
        )

        await cleanup(email_a, email_b)
        print(f"\n  cleanup: tenants de prueba borrados")

    base = {"database_url": "postgresql://x", "secret_key": "k"}
    s = Settings(_env_file=None, **base)
    check(s.cors_origins_list == [], "CORS_ORIGINS vacío -> lista vacía")
    check(
        s.frontend_base_url == s.public_base_url.rstrip("/"),
        "Sin FRONTEND_URL, frontend_base_url cae a PUBLIC_BASE_URL",
    )
    s = Settings(
        _env_file=None,
        cors_origins="https://app.parsero.dev/, http://localhost:5173 ,",
        frontend_url="https://app.parsero.dev/",
        **base,
    )
    check(
        s.cors_origins_list == ["https://app.parsero.dev", "http://localhost:5173"],
        f"CORS_ORIGINS se parsea y limpia (got {s.cors_origins_list})",
    )
    check(
        s.frontend_base_url == "https://app.parsero.dev",
        f"FRONTEND_URL sin barra final (got {s.frontend_base_url})",
    )

    sent: list[str] = []
    original_get_settings = email_module.get_settings
    original_send = email_module.EmailService._send
    email_module.get_settings = lambda: s

    async def fake_send(self, *, to, subject, html):
        sent.append(html)

    email_module.EmailService._send = fake_send
    try:
        svc = email_module.EmailService()
        await svc.send_verification_email(to="x@y.com", token="tok1")
        await svc.send_password_reset_email(to="x@y.com", token="tok2")
    finally:
        email_module.get_settings = original_get_settings
        email_module.EmailService._send = original_send
    check(
        "https://app.parsero.dev/verify-email?token=tok1" in sent[0],
        "Email de verificación apunta a FRONTEND_URL",
    )
    check(
        "https://app.parsero.dev/reset-password?token=tok2" in sent[1],
        "Email de reset apunta a FRONTEND_URL",
    )

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'-' * 50}")
    if passed == total:
        print(f"  {PASS} {passed}/{total} checks pasaron -- Fase 6.0 OK\n")
        return 0
    print(f"  {FAIL} {passed}/{total} checks pasaron")
    for ok, label in results:
        if not ok:
            print(f"      {FAIL} {label}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
