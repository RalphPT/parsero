import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant
    from app.db.models.extraction_job import ExtractionJob


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_jobs.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    input_tokens:  Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 6 decimales: el costo unitario de Claude se mide en fracciones de centavo
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    # Periodo de facturación en formato 'YYYY-MM' - agrupa el cobro mensual
    billing_period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    tenant: Mapped["Tenant"]        = relationship(back_populates="usage_logs")
    job:    Mapped["ExtractionJob"] = relationship(back_populates="usage_log")

    __table_args__ = (
        Index("idx_usage_tenant_period", "tenant_id", "billing_period"),
    )

    def __repr__(self) -> str:
        return f"<UsageLog {self.id} tenant={self.tenant_id} {self.billing_period} ${self.cost_usd}>"
