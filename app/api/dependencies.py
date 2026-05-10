"""Auth, rate limiting y demás dependencies compartidas."""
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

import jwt as pyjwt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.jwt_tokens import decode_token
from app.core.rate_limits import RATE_LIMITS_PER_MINUTE
from app.core.security import hash_api_key
from app.db.models.api_key import ApiKey
from app.db.models.tenant import Tenant
from app.db.repositories.tenant import TenantRepository
from app.db.session import get_db
from app.services.redis_client import get_redis

settings = get_settings()

LAST_USED_THROTTLE_SECONDS = 60  # Solo escribir last_used_at una vez por minuto

#
# Security schemes (registrados en OpenAPI -> botón "Authorize" en Swagger)
#
admin_token_scheme = APIKeyHeader(
    name="X-Admin-Token",
    scheme_name="AdminToken",
    description="Token administrativo (mismo valor que SECRET_KEY del .env).",
    auto_error=False,
)

bearer_scheme = HTTPBearer(
    scheme_name="ApiKeyBearer",
    description="API key del tenant en formato `psr_...`.",
    auto_error=False,
)

jwt_scheme = HTTPBearer(
    scheme_name="SessionJWT",
    description="JWT de sesión emitido por POST /auth/login.",
    auto_error=False,
)


#
# Admin (header X-Admin-Token)
#
async def verify_admin(
    x_admin_token: Optional[str] = Depends(admin_token_scheme),
) -> None:
    """Endpoints administrativos: el header X-Admin-Token debe coincidir con SECRET_KEY."""
    if not x_admin_token or not secrets.compare_digest(
        x_admin_token, settings.secret_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token inválido o ausente",
        )


#
# Auth de cliente (Bearer <api_key>)
#
async def get_current_api_key(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> ApiKey:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header 'Authorization: Bearer <api_key>' requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_key = creds.credentials
    key_hash = hash_api_key(raw_key)

    # Eager-load del tenant porque las dependencias siguientes lo necesitan
    stmt = (
        select(ApiKey)
        .options(selectinload(ApiKey.tenant))
        .where(ApiKey.key_hash == key_hash)
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key inválida")
    if not api_key.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key desactivada")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expirada")
    if not api_key.tenant.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tenant desactivado")

    # Throttled last_used_at: SET NX EX 60 - solo el primer hit de cada
    # ventana de 60s escribe a Postgres. Los demás se saltan el write.
    throttle_key = f"apikey:lastused:{api_key.id}"
    just_acquired = await redis.set(
        throttle_key, "1", ex=LAST_USED_THROTTLE_SECONDS, nx=True
    )
    if just_acquired:
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()

    return api_key


async def get_current_tenant(
    api_key: ApiKey = Depends(get_current_api_key),
) -> Tenant:
    return api_key.tenant


#
# Auth de cliente vía JWT de sesión
# Usado por endpoints /account/* del dashboard. No comparte path con
# get_current_api_key para que Swagger pueda diferenciarlos.
#
SESSION_COOKIE_NAME = "parsero_session"


async def get_current_user_jwt(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(jwt_scheme),
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """
    Resuelve el tenant a partir de:
      1. Header `Authorization: Bearer <jwt>` (clientes API), o
      2. Cookie `parsero_session=<jwt>` (browser, seteada en /auth/login)
    Header tiene prioridad sobre cookie cuando ambos están presentes.
    """
    token = creds.credentials if creds else parsero_session
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth requerida: Bearer header o cookie de sesión",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        tenant_id = decode_token(token, expected_purpose="session")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada")
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "JWT inválido")

    tenant = await TenantRepository(db).get(tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tenant inactivo o no existe")
    return tenant


#
# Rate limiter (fixed window por minuto)
#
async def enforce_rate_limit(
    tenant: Tenant = Depends(get_current_tenant),
    redis=Depends(get_redis),
) -> None:
    limit = RATE_LIMITS_PER_MINUTE[tenant.plan]
    if limit == 0:  # 0 = ilimitado (enterprise)
        return

    minute_bucket = int(time.time() // 60)
    bucket_key = f"ratelimit:{tenant.id}:{minute_bucket}"

    count = await redis.incr(bucket_key)
    if count == 1:
        # Primera request del bucket: setear TTL para que el contador se
        # autodestruya al cierre del minuto.
        await redis.expire(bucket_key, 60)

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit excedido ({limit} req/min para plan {tenant.plan.value})",
            headers={"Retry-After": "60"},
        )
