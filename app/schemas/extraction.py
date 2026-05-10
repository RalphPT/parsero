"""Schemas for extraction requests and responses."""
from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, HttpUrl


class ExtractionRequest(BaseModel):
    """Request to extract data from a document."""
    document_url: HttpUrl
    schema_type: str  # invoice, cv, receipt


class ExtractionJobResponse(BaseModel):
    """Response with extraction job ID."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str  # pending, processing, completed, failed, cached
    created_at: datetime


class ExtractionResultResponse(BaseModel):
    """Extraction result with job info."""
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    status: str
    data: Optional[dict] = None
    error_message: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    created_at: datetime
