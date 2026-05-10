from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    expires_at: Optional[datetime] = None


class ApiKeyUpdate(BaseModel):
    """Patch para activar/desactivar una API key."""
    is_active: bool


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key_prefix: str
    name: Optional[str]
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """
    Respuesta del POST /admin/tenants/{id}/keys. Incluye `key` en claro -
    solo se devuelve UNA VEZ al crear y nunca se persiste.
    """
    key: str
