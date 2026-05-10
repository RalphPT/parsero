"""Schemas para los endpoints de auth pública."""
from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class SignupResponse(BaseModel):
    """Respuesta de signup. La cuenta arranca inactiva hasta verificar el email."""
    tenant_id: UUID
    email: EmailStr
    message: str = "Te enviamos un email de verificación"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: UUID
    email: EmailStr
    plan: str
    email_verified: bool


class VerifyEmailResponse(BaseModel):
    """Respuesta del verify-email. Devuelve la primera API key del tenant
    si fue creada como parte de la activación."""
    tenant_id: UUID
    email: EmailStr
    api_key: Optional[str] = None  # raw key — solo se muestra UNA vez


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class AccountResponse(BaseModel):
    """Datos del tenant logueado (devuelto por GET /account/me con JWT)."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    plan: str
    is_active: bool
    email_verified_at: Optional[datetime]
    created_at: datetime
