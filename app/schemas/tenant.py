from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, Field

from app.db.models.tenant import TenantPlan


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    plan: TenantPlan = TenantPlan.free


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    plan: TenantPlan
    is_active: bool
    created_at: datetime
