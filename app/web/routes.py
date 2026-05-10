"""Páginas HTML y handlers de los forms de auth/dashboard."""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import jwt as pyjwt
from fastapi import APIRouter, Cookie, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SESSION_COOKIE_NAME
from app.core.config import get_settings
from app.core.jwt_tokens import create_token, decode_token
from app.core.passwords import hash_password, verify_password
from app.core.rate_limits import RATE_LIMITS_PER_MINUTE
from app.db.models.tenant import Tenant, TenantPlan
from app.db.repositories.api_key import ApiKeyRepository
from app.db.repositories.tenant import TenantRepository
from app.db.session import get_db
from app.services.email_service import get_email_service
from app.services.lemonsqueezy_service import (
    LemonSqueezyError,
    get_lemonsqueezy_service,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


# Cookie config - Secure=False en dev (no HTTPS), True en prod
def _cookie_kwargs() -> dict:
    settings = get_settings()
    is_prod = settings.is_production
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": is_prod,
        "max_age": settings.jwt_session_ttl_hours * 3600,
        "path": "/",
    }


async def _session_or_none(
    parsero_session: Optional[str],
    db: AsyncSession,
) -> Optional[Tenant]:
    """Resuelve tenant desde cookie. None si no hay sesión válida."""
    if not parsero_session:
        return None
    try:
        tenant_id = decode_token(parsero_session, expected_purpose="session")
    except pyjwt.PyJWTError:
        return None
    tenant = await TenantRepository(db).get(tenant_id)
    if tenant is None or not tenant.is_active:
        return None
    return tenant


def _redirect(url: str, status_code: int = 303) -> RedirectResponse:
    """303 See Other - patrón POST/Redirect/GET."""
    return RedirectResponse(url=url, status_code=status_code)


#
# Páginas públicas
#
@router.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    return templates.TemplateResponse(
        request,
        "landing.html", {"tenant": tenant}
    )


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(
    request: Request,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    return templates.TemplateResponse(
        request,
        "pricing.html", {"tenant": tenant}
    )


@router.get("/docs", response_class=HTMLResponse)
async def docs_page(
    request: Request,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    return templates.TemplateResponse(
        request,
        "docs.html", {"tenant": tenant}
    )


#
# Signup
#
@router.get("/signup", response_class=HTMLResponse)
async def signup_form(
    request: Request,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant:
        return _redirect("/dashboard")
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"tenant": None, "flash_success": request.query_params.get("signed_up")},
    )


@router.post("/signup", response_class=HTMLResponse)
async def signup_submit(
    request: Request,
    name: str = Form(..., min_length=2, max_length=120),
    email: str = Form(...),
    password: str = Form(..., min_length=8, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    repo = TenantRepository(db)
    if await repo.get_by_email(email):
        return templates.TemplateResponse(
            request,
            "signup.html",
            {
                "tenant": None,
                "flash_error": f"Ya existe una cuenta con email {email}",
                "form_name": name,
                "form_email": email,
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    tenant = await repo.create(
        name=name, email=email, plan=TenantPlan.free,
        password_hash=hash_password(password), is_active=False,
    )
    await db.commit()

    token = create_token(tenant_id=tenant.id, purpose="email_verify")
    try:
        await get_email_service().send_verification_email(to=email, token=token)
    except Exception as e:
        # Resend en sandbox solo permite mandar al email registrado.
        # Logueamos pero no rompemos el signup.
        import logging
        logging.getLogger(__name__).error(
            "send_verification_email falló para %s: %s", email, e
        )

    return _redirect("/login?signed_up=1")


#
# Login / Logout
#
@router.get("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant:
        return _redirect("/dashboard")
    flash = None
    if request.query_params.get("signed_up"):
        flash = "Te enviamos un email para verificar tu cuenta."
    if request.query_params.get("verified"):
        flash = "Email verificado. Ya puedes iniciar sesión."
    if request.query_params.get("password_reset"):
        flash = "Contraseña actualizada. Inicia sesión con la nueva."
    return templates.TemplateResponse(
        request,
        "login.html", {"tenant": None, "flash_success": flash}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await TenantRepository(db).get_by_email(email)
    fail_msg = "Email o contraseña incorrectos"

    if tenant is None or tenant.password_hash is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"tenant": None, "flash_error": fail_msg, "form_email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not verify_password(password, tenant.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"tenant": None, "flash_error": fail_msg, "form_email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not tenant.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "tenant": None,
                "flash_error": "Cuenta sin verificar, revisa tu email.",
                "form_email": email,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    jwt_token = create_token(tenant_id=tenant.id, purpose="session")
    response = _redirect("/dashboard")
    response.set_cookie(SESSION_COOKIE_NAME, jwt_token, **_cookie_kwargs())
    return response


@router.post("/logout")
async def logout():
    response = _redirect("/")
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


#
# Forgot / reset password
#
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_form(request: Request):
    return templates.TemplateResponse(
        request,
        "forgot_password.html", {"tenant": None}
    )


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_submit(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await TenantRepository(db).get_by_email(email)
    if tenant is not None and tenant.password_hash is not None:
        token = create_token(tenant_id=tenant.id, purpose="password_reset")
        try:
            await get_email_service().send_password_reset_email(to=tenant.email, token=token)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                "send_password_reset_email falló para %s: %s", email, e
            )
    # Genérico - no revelamos si el email existe
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {
            "tenant": None,
            "flash_success": "Si la cuenta existe, te enviamos un email con instrucciones.",
        },
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_form(
    request: Request,
    token: str = Query(...),
):
    return templates.TemplateResponse(
        request,
        "reset_password.html",
        {"tenant": None, "token": token},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_submit(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(..., min_length=8, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    try:
        tenant_id = decode_token(token, expected_purpose="password_reset")
    except pyjwt.ExpiredSignatureError:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {"tenant": None, "token": token,
             "flash_error": "Link expirado. Pide uno nuevo desde 'Olvidaste tu contraseña'."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except pyjwt.PyJWTError:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {"tenant": None, "token": token,
             "flash_error": "Link inválido."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    repo = TenantRepository(db)
    tenant = await repo.get(tenant_id)
    if tenant is None:
        return _redirect("/login")
    await repo.update_password(tenant, hash_password(new_password))
    await db.commit()
    return _redirect("/login?password_reset=1")


#
# Verify email (callback del link del email)
#
@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(
    request: Request,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        tenant_id = decode_token(token, expected_purpose="email_verify")
    except pyjwt.ExpiredSignatureError:
        return templates.TemplateResponse(
            request,
            "verify_email.html",
            {"tenant": None, "success": False,
             "error_message": "El link expiró. Inicia sesión y solicita uno nuevo."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except pyjwt.PyJWTError:
        return templates.TemplateResponse(
            request,
            "verify_email.html",
            {"tenant": None, "success": False,
             "error_message": "Link inválido."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    repo = TenantRepository(db)
    tenant = await repo.get(tenant_id)
    if tenant is None:
        return templates.TemplateResponse(
            request,
            "verify_email.html",
            {"tenant": None, "success": False,
             "error_message": "Cuenta no encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Idempotente: si ya estaba verificado, no creamos nueva key
    if tenant.email_verified_at is None:
        await repo.mark_email_verified(tenant)
        api_key, raw_key = await ApiKeyRepository(db).create(
            tenant_id=tenant.id, name="default"
        )
        await db.commit()
        try:
            await get_email_service().send_welcome_email(to=tenant.email, api_key=raw_key)
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "verify_email.html", {"tenant": None, "success": True}
    )


#
# Dashboard (autenticado)
#
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant is None:
        return _redirect("/login")

    keys = await ApiKeyRepository(db).list_for_tenant(tenant.id)
    # Usage del mes actual
    from sqlalchemy import func, select
    from app.db.models.usage_log import UsageLog
    period = datetime.utcnow().strftime("%Y-%m")
    stmt = select(
        func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
        func.count(UsageLog.id).label("extractions_count"),
    ).where(UsageLog.tenant_id == tenant.id, UsageLog.billing_period == period)
    row = (await db.execute(stmt)).one()
    usage = {
        "billing_period": period,
        "extractions_count": int(row.extractions_count or 0),
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
    }

    rate_limit = RATE_LIMITS_PER_MINUTE.get(tenant.plan, 0)
    new_api_key = request.query_params.get("new_key")

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "tenant": tenant,
            "keys": keys,
            "usage": usage,
            "rate_limit": rate_limit if rate_limit > 0 else "ilimitado",
            "new_api_key": new_api_key,
        },
    )


@router.post("/dashboard/keys/new")
async def create_key(
    request: Request,
    name: Optional[str] = Form(default=None),
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant is None:
        return _redirect("/login")
    api_key, raw_key = await ApiKeyRepository(db).create(
        tenant_id=tenant.id, name=name or None
    )
    await db.commit()
    return _redirect(f"/dashboard?new_key={raw_key}")


@router.post("/dashboard/keys/{key_id}/revoke")
async def revoke_key(
    key_id: UUID,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant is None:
        return _redirect("/login")
    await ApiKeyRepository(db).set_active(
        tenant_id=tenant.id, key_id=key_id, is_active=False
    )
    await db.commit()
    return _redirect("/dashboard")


@router.post("/dashboard/keys/{key_id}/reactivate")
async def reactivate_key(
    key_id: UUID,
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant is None:
        return _redirect("/login")
    await ApiKeyRepository(db).set_active(
        tenant_id=tenant.id, key_id=key_id, is_active=True
    )
    await db.commit()
    return _redirect("/dashboard")


@router.post("/dashboard/upgrade")
async def upgrade(
    request: Request,
    plan: str = Form(...),
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant is None:
        return _redirect("/login")
    if plan not in ("starter", "pro"):
        return _redirect("/dashboard")

    settings = get_settings()
    variant_id = (
        settings.lemonsqueezy_variant_starter
        if plan == "starter"
        else settings.lemonsqueezy_variant_pro
    )
    if not variant_id:
        return _redirect("/dashboard")

    try:
        url = await get_lemonsqueezy_service().create_checkout_url(
            variant_id=variant_id,
            tenant_id=tenant.id,
            tenant_email=tenant.email,
        )
    except LemonSqueezyError:
        return _redirect("/dashboard")
    return _redirect(url)


@router.post("/dashboard/portal")
async def portal(
    parsero_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _session_or_none(parsero_session, db)
    if tenant is None:
        return _redirect("/login")
    if not tenant.lemon_subscription_id:
        return _redirect("/dashboard")
    try:
        url = await get_lemonsqueezy_service().get_customer_portal_url(
            tenant.lemon_subscription_id
        )
    except LemonSqueezyError:
        return _redirect("/dashboard")
    return _redirect(url)
