import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base
import enum

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant
    from app.db.models.api_key import ApiKey
    from app.db.models.extraction_result import ExtractionResult
    from app.db.models.usage_log import UsageLog


class JobStatus(str, enum.Enum):
    pending    = "pending"
    processing = "processing"
    completed  = "completed"
    failed     = "failed"
    cached     = "cached"      # resultado devuelto desde cache, sin llamar a Claude


class SchemaType(str, enum.Enum):
    invoice = "invoice"
    cv      = "cv"
    receipt = "receipt"


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_type: Mapped[SchemaType] = mapped_column(
        SAEnum(SchemaType, name="schema_type_enum"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status_enum"),
        nullable=False, default=JobStatus.pending
    )
    source_url:   Mapped[Optional[str]] = mapped_column(Text)
    source_hash:  Mapped[Optional[str]] = mapped_column(String(64))  # SHA-256 para cache
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens:Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms:  Mapped[Optional[int]] = mapped_column(Integer)
    error_message:Mapped[Optional[str]] = mapped_column(Text)
    created_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relaciones
    tenant:     Mapped["Tenant"]             = relationship(back_populates="extraction_jobs")
    api_key:    Mapped["ApiKey"]             = relationship(back_populates="extraction_jobs")
    result:     Mapped[Optional["ExtractionResult"]] = relationship(back_populates="job", uselist=False)
    usage_log:  Mapped[Optional["UsageLog"]]         = relationship(back_populates="job", uselist=False)

    __table_args__ = (
        Index("idx_jobs_source_hash_completed", "source_hash",
              postgresql_where="status = 'completed'"),
        Index("idx_jobs_tenant_created", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ExtractionJob {self.id} [{self.schema_type}] {self.status}>"
