"""Auth pública: signup, verify, login, forgot/reset password."""
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_jwt
from app.core.jwt_tokens import create_token, decode_token
from app.core.passwords import hash_password, verify_password
from app.db.models.tenant import Tenant, TenantPlan
from app.db.repositories.api_key import ApiKeyRepository
from app.db.repositories.tenant import TenantRepository
from app.db.session import get_db
from app.schemas.auth import (
    AccountResponse,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.services.email_service import get_email_service


router = APIRouter()

# Mensaje genérico para login fallido — no revelamos si el email existe.
_LOGIN_FAIL = "Email o contraseña incorrectos"


@router.post(
    "/auth/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> SignupResponse:
    """Crea un tenant en plan free. Inactivo hasta que verifique el email."""
    repo = TenantRepository(db)
    if await repo.get_by_email(body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una cuenta con email {body.email}",
        )

    tenant = await repo.create(
        name=body.name,
        email=body.email,
        plan=TenantPlan.free,
        password_hash=hash_password(body.password),
        is_active=False,  # se activa al verificar email
    )
    await db.commit()

    token = create_token(tenant_id=tenant.id, purpose="email_verify")
    await get_email_service().send_verification_email(to=body.email, token=token)

    return SignupResponse(tenant_id=tenant.id, email=body.email)


@router.get("/auth/verify-email", response_model=VerifyEmailResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Verifica el email, activa la cuenta, y crea la primera API key."""
    try:
        tenant_id = decode_token(token, expected_purpose="email_verify")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link expirado, pedí uno nuevo")
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link inválido")

    repo = TenantRepository(db)
    tenant = await repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")

    # Idempotente: si ya estaba verificada no creamos otra key
    if tenant.email_verified_at is not None:
        return VerifyEmailResponse(
            tenant_id=tenant.id, email=tenant.email, api_key=None
        )

    await repo.mark_email_verified(tenant)
    api_key, raw_key = await ApiKeyRepository(db).create(
        tenant_id=tenant.id, name="default"
    )
    await db.commit()

    # Email de bienvenida con la API key (best-effort, no rompe si falla)
    try:
        await get_email_service().send_welcome_email(to=tenant.email, api_key=raw_key)
    except Exception:
        pass

    return VerifyEmailResponse(
        tenant_id=tenant.id, email=tenant.email, api_key=raw_key
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login con email/password. Devuelve JWT de sesión (7 días)."""
    repo = TenantRepository(db)
    tenant = await repo.get_by_email(body.email)

    # No revelamos qué falló (email no existe vs password mal) → mismo 401
    if tenant is None or tenant.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _LOGIN_FAIL)
    if not verify_password(body.password, tenant.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _LOGIN_FAIL)
    if not tenant.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cuenta sin verificar — revisá tu email",
        )

    return LoginResponse(
        access_token=create_token(tenant_id=tenant.id, purpose="session"),
        tenant_id=tenant.id,
        email=tenant.email,
        plan=tenant.plan.value,
        email_verified=tenant.email_verified_at is not None,
    )


@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Manda email con reset link. Siempre devuelve 202 — no revela si el email existe."""
    tenant = await TenantRepository(db).get_by_email(body.email)
    if tenant is not None and tenant.password_hash is not None:
        token = create_token(tenant_id=tenant.id, purpose="password_reset")
        await get_email_service().send_password_reset_email(
            to=tenant.email, token=token
        )
    return {"message": "Si la cuenta existe, te enviamos un email con instrucciones"}


@router.post("/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Cambia la password usando el token del email."""
    try:
        tenant_id = decode_token(body.token, expected_purpose="password_reset")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link expirado")
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link inválido")

    repo = TenantRepository(db)
    tenant = await repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")

    await repo.update_password(tenant, hash_password(body.new_password))
    await db.commit()


@router.post("/auth/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Reenvía el email de verificación. Solo si la cuenta no está verificada."""
    tenant = await TenantRepository(db).get_by_email(body.email)
    if tenant is not None and tenant.email_verified_at is None:
        token = create_token(tenant_id=tenant.id, purpose="email_verify")
        await get_email_service().send_verification_email(
            to=tenant.email, token=token
        )
    return {"message": "Si la cuenta existe y no está verificada, te enviamos un email"}


@router.get("/account/me", response_model=AccountResponse)
async def get_account(tenant: Tenant = Depends(get_current_user_jwt)):
    """Datos del tenant logueado. Auth: Bearer <JWT de sesión>."""
    return tenant
