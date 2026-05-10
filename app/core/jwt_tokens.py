"""Tokens firmados (session, email_verify, password_reset). El claim `purpose`
es lo que evita que el token de un flujo sirva en otro."""
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import jwt

from app.core.config import get_settings


TokenPurpose = Literal["session", "email_verify", "password_reset"]


def create_token(*, tenant_id: UUID, purpose: TokenPurpose) -> str:
    """Crea un JWT con TTL según el purpose."""
    settings = get_settings()
    ttl_map = {
        "session": settings.jwt_session_ttl_hours,
        "email_verify": settings.jwt_email_verify_ttl_hours,
        "password_reset": settings.jwt_password_reset_ttl_hours,
    }
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(tenant_id),
        "purpose": purpose,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_map[purpose])).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_purpose: TokenPurpose) -> UUID:
    """
    Decodifica el JWT, valida firma + expiración + purpose esperado.
    Devuelve el tenant_id como UUID.
    Lanza jwt.PyJWTError (o subclase) si el token es inválido/expirado/wrong purpose.
    """
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("purpose") != expected_purpose:
        raise jwt.InvalidTokenError(
            f"Token purpose mismatch: esperado {expected_purpose}, "
            f"recibido {payload.get('purpose')}"
        )
    return UUID(payload["sub"])
