import uuid
import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.api_key import ApiKey
    from app.db.models.extraction_job import ExtractionJob
    from app.db.models.usage_log import UsageLog


class TenantPlan(str, enum.Enum):
    free       = "free"
    starter    = "starter"
    pro        = "pro"
    enterprise = "enterprise"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name:  Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    plan:  Mapped[TenantPlan] = mapped_column(
        SAEnum(TenantPlan, name="tenant_plan_enum"),
        nullable=False, default=TenantPlan.free
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Auth pública
    # NULL para tenants creados por admin antes de Fase 5 (no pueden hacer login)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    # NULL hasta que el cliente clickee el link de verificación de email
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Billing con Lemon Squeezy
    # NULL para tenants en plan free o creados por admin sin suscripción
    lemon_customer_id:     Mapped[Optional[str]] = mapped_column(String(64), index=True)
    lemon_subscription_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # Status crudo de Lemon Squeezy: active, on_trial, paused, past_due, unpaid, cancelled, expired
    subscription_status:   Mapped[Optional[str]] = mapped_column(String(32))
    subscription_renews_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    api_keys:        Mapped[list["ApiKey"]]        = relationship(back_populates="tenant", cascade="all, delete-orphan")
    extraction_jobs: Mapped[list["ExtractionJob"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    usage_logs:      Mapped[list["UsageLog"]]      = relationship(back_populates="tenant", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Tenant {self.id} {self.email} [{self.plan}]>"
