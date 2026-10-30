"""Schemas para los endpoints /account/* del dashboard."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageSummary(BaseModel):
    """Resumen de consumo del billing period actual (mes)."""
    billing_period: str  # YYYY-MM
    extractions_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    schema_type: str
    source_url: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    limit: int
    offset: int


class JobDetailResponse(JobSummary):
    data: Optional[dict] = None
