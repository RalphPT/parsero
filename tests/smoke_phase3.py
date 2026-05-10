r"""
Smoke test end-to-end de Fase 3 (core extraction con Gemini).

Se corre como script:
    .\.venv\Scripts\python.exe -m tests.smoke_phase3

Ejercita el flujo completo contra BD/Redis/Gemini reales:
  1.  POST /extract con doc de texto             -> 202 + status=completed
  2.  GET  /extract/{id}                          -> 200 con data + tokens
  3.  POST /extract mismo doc + schema            -> 202 + status=cached
  4.  POST /extract schema_type inválido          -> 400
  5.  POST /extract URL inválida                  -> 400
  6.  GET  /extract/{id} de otro tenant           -> 404
  7.  POST /extract con LLM mockeado a 502        -> 502 + job=failed
  8.  POST /extract con LLM mockeado a 422        -> 422 + job=failed
  9.  Cleanup
"""
import asyncio
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.exceptions import LLMUpstreamError
from app.core.llm_provider import LLMProvider
from app.db.models.tenant import Tenant
from app.db.models.extraction_job import ExtractionJob, JobStatus
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services.redis_client import redis_client

settings = get_settings()
ADMIN_TOKEN = settings.secret_key

PASS = "[ OK ]"
FAIL = "[FAIL]"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    icon = PASS if ok else FAIL
    print(f"  {icon} {label}")


async def cleanup(test_email: str) -> None:
    """Borra el tenant — ON DELETE CASCADE limpia jobs/results/usage_logs/api_keys."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Tenant).where(Tenant.email == test_email))
        await db.commit()
    async for k in redis_client.scan_iter("ratelimit:*"):
        await redis_client.delete(k)
    async for k in redis_client.scan_iter("apikey:lastused:*"):
        await redis_client.delete(k)


async def clear_rate_limit(tenant_id: str) -> None:
    """Limpia contadores de rate limit del tenant para no chocar con free=10/min."""
    async for k in redis_client.scan_iter(f"ratelimit:{tenant_id}:*"):
        await redis_client.delete(k)


# ─── LLM mocks para tests 422 / 502 ──────────────────────────
class _UpstreamFailLLM(LLMProvider):
    async def extract(self, *_, **__):
        raise LLMUpstreamError("simulated upstream timeout")

    def get_usage_tokens(self):
        return (0, 0)


class _BadSchemaLLM(LLMProvider):
    """Devuelve JSON estructuralmente incorrecto (tipos malos)."""

    async def extract(self, *_, **__):
        # `experience` debe ser lista de objetos pero le mandamos string
        return '{"personal": {"full_name": "X"}, "experience": "no soy lista"}'

    def get_usage_tokens(self):
        return (10, 5)


async def get_job_status(job_id: str) -> str | None:
    """Lee el status del job directamente de la BD (para validar persistencia)."""
    async with AsyncSessionLocal() as db:
        job = await db.get(ExtractionJob, uuid.UUID(job_id))
        return job.status.value if job else None


async def main() -> int:
    test_email = f"smoke3-{uuid.uuid4().hex[:8]}@parsero-smoke.com"
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        print(f"\n>>> Smoke test Fase 3 -- tenant: {test_email}\n")

        # --- Setup ──────────────────────────────────────────
        r = await c.post(
            "/admin/tenants",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "Smoke Fase 3", "email": test_email, "plan": "free"},
        )
        check(r.status_code == 201, f"Setup tenant -> 201 (got {r.status_code})")
        if r.status_code != 201:
            print(f"    Body: {r.text}")
            return 1
        tenant_id = r.json()["id"]

        r = await c.post(
            f"/admin/tenants/{tenant_id}/keys",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "smoke3-key"},
        )
        check(r.status_code == 201, f"Setup API key -> 201 (got {r.status_code})")
        if r.status_code != 201:
            print(f"    Body: {r.text}")
            await cleanup(test_email)
            return 1
        raw_key = r.json()["key"]
        auth = {"Authorization": f"Bearer {raw_key}"}

        # --- 1. POST /extract happy path ──────────────────
        test_url = "https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/README.md"
        r = await c.post(
            "/extract",
            headers=auth,
            json={"document_url": test_url, "schema_type": "cv"},
        )
        check(r.status_code == 202, f"POST /extract -> 202 (got {r.status_code})")
        if r.status_code != 202:
            print(f"    Body: {r.text}")
            await cleanup(test_email)
            return 1

        body = r.json()
        job_id = body["id"]
        check(
            body["status"] == "completed",
            f"POST /extract status=completed (got {body['status']})",
        )

        # --- 2. GET /extract/{id} ──────────────────────────
        r = await c.get(f"/extract/{job_id}", headers=auth)
        check(r.status_code == 200, f"GET /extract/{{id}} -> 200 (got {r.status_code})")
        result = r.json()
        check(result.get("status") == "completed", "GET status=completed")
        check(isinstance(result.get("data"), dict), "data es dict")
        check(
            result.get("input_tokens") and result["input_tokens"] > 0,
            f"input_tokens > 0 (got {result.get('input_tokens')})",
        )
        check(
            result.get("output_tokens") and result["output_tokens"] > 0,
            f"output_tokens > 0 (got {result.get('output_tokens')})",
        )

        # --- 3. Cache hit ───────────────────────────────────
        await clear_rate_limit(tenant_id)
        r = await c.post(
            "/extract",
            headers=auth,
            json={"document_url": test_url, "schema_type": "cv"},
        )
        check(r.status_code == 202, f"POST /extract (cache) -> 202 (got {r.status_code})")
        check(
            r.json().get("status") == "cached",
            f"Segunda extracción status=cached (got {r.json().get('status')})",
        )

        # --- 4. Schema inválido -> 400 ─────────────────────
        await clear_rate_limit(tenant_id)
        r = await c.post(
            "/extract",
            headers=auth,
            json={"document_url": test_url, "schema_type": "factura"},
        )
        check(
            r.status_code == 400,
            f"POST /extract schema inválido -> 400 (got {r.status_code})",
        )

        # --- 5. URL inválida -> 400 ────────────────────────
        await clear_rate_limit(tenant_id)
        r = await c.post(
            "/extract",
            headers=auth,
            json={
                "document_url": "https://no-existe-este-host-12345.invalid/x.pdf",
                "schema_type": "cv",
            },
        )
        check(
            r.status_code == 400,
            f"POST /extract URL inválida -> 400 (got {r.status_code})",
        )

        # --- 6. Cross-tenant -> 404 ─────────────────────────
        r = await c.post(
            "/admin/tenants",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={
                "name": "Smoke Fase 3 otro",
                "email": f"otro-{test_email}",
                "plan": "free",
            },
        )
        if r.status_code == 201:
            other_tenant_id = r.json()["id"]
            rk = await c.post(
                f"/admin/tenants/{other_tenant_id}/keys",
                headers={"X-Admin-Token": ADMIN_TOKEN},
                json={"name": "otra-key"},
            )
            other_key = rk.json()["key"]
            r = await c.get(
                f"/extract/{job_id}", headers={"Authorization": f"Bearer {other_key}"}
            )
            check(
                r.status_code == 404,
                f"GET /extract/{{id}} cross-tenant -> 404 (got {r.status_code})",
            )
            await cleanup(f"otro-{test_email}")

        # --- 7. LLM upstream falla -> 502 ──────────────────
        # Override del provider via dependency injection (FastAPI)
        from app.core.llm_provider import get_llm_provider as real_get_llm
        from app.api.v1.endpoints import extraction as ext_module

        await clear_rate_limit(tenant_id)
        # Patch directo en el módulo del endpoint (más simple que dependency_overrides
        # porque get_llm_provider no es una FastAPI dependency, es función plain)
        ext_module.get_llm_provider = lambda: _UpstreamFailLLM()
        try:
            # Usar URL distinta para no caer en cache
            r = await c.post(
                "/extract",
                headers=auth,
                json={
                    "document_url": "https://raw.githubusercontent.com/python/cpython/main/README.rst",
                    "schema_type": "cv",
                },
            )
            check(
                r.status_code == 502,
                f"POST /extract LLM caído -> 502 (got {r.status_code})",
            )
            # Verificar que el job quedó persistido como failed
            if r.status_code == 502:
                # El response no incluye job_id (porque levantamos HTTPException)
                # así que buscamos el último job del tenant
                async with AsyncSessionLocal() as db:
                    stmt = (
                        select(ExtractionJob)
                        .where(ExtractionJob.tenant_id == uuid.UUID(tenant_id))
                        .order_by(ExtractionJob.created_at.desc())
                        .limit(1)
                    )
                    last_job = (await db.execute(stmt)).scalar_one_or_none()
                check(
                    last_job is not None and last_job.status == JobStatus.failed,
                    f"Job quedó persistido como failed (status={last_job.status if last_job else None})",
                )
                check(
                    last_job is not None and last_job.error_message is not None,
                    "Job tiene error_message poblado",
                )
        finally:
            ext_module.get_llm_provider = real_get_llm

        # --- 8. LLM devuelve JSON inválido -> 422 ──────────
        await clear_rate_limit(tenant_id)
        ext_module.get_llm_provider = lambda: _BadSchemaLLM()
        try:
            r = await c.post(
                "/extract",
                headers=auth,
                json={
                    "document_url": "https://raw.githubusercontent.com/python/cpython/main/Doc/README.rst",
                    "schema_type": "cv",
                },
            )
            check(
                r.status_code == 422,
                f"POST /extract LLM mal schema -> 422 (got {r.status_code})",
            )
        finally:
            ext_module.get_llm_provider = real_get_llm

        # --- 9. Cleanup ─────────────────────────────────────
        await cleanup(test_email)
        print(f"\n  cleanup: tenant {test_email} borrado")

    # --- Reporte ────────────────────────────────────────
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'-' * 50}")
    if passed == total:
        print(f"  {PASS} {passed}/{total} checks pasaron -- Fase 3 OK\n")
        return 0
    print(f"  {FAIL} {passed}/{total} checks pasaron")
    for ok, label in results:
        if not ok:
            print(f"      {FAIL} {label}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
