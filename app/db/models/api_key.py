import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant
    from app.db.models.extraction_job import ExtractionJob


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # SHA-256 de la clave en claro - nunca guardamos la clave real
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Prefijo público de la key (ej: "psr_abc123...") para que el usuario reconozca cuál es cuál
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(80))

    is_active:    Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    tenant:          Mapped["Tenant"]             = relationship(back_populates="api_keys")
    extraction_jobs: Mapped[list["ExtractionJob"]] = relationship(back_populates="api_key")

    def __repr__(self) -> str:
        return f"<ApiKey {self.id} {self.key_prefix}... active={self.is_active}>"
