from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.extraction_job import ExtractionJob, JobStatus, SchemaType


class ExtractionJobRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        tenant_id: UUID,
        api_key_id: UUID,
        schema_type: str,
        source_hash: str,
        source_url: str,
    ) -> ExtractionJob:
        job = ExtractionJob(
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            schema_type=SchemaType(schema_type),
            source_hash=source_hash,
            source_url=source_url,
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get(self, job_id: UUID) -> Optional[ExtractionJob]:
        return await self.db.get(ExtractionJob, job_id)

    async def get_by_hash_and_schema(
        self, tenant_id: UUID, source_hash: str, schema_type: str
    ) -> Optional[ExtractionJob]:
        # Lookup de cache: buscamos jobs ya completados con mismo (tenant, hash, schema).
        stmt = select(ExtractionJob).where(
            ExtractionJob.tenant_id == tenant_id,
            ExtractionJob.source_hash == source_hash,
            ExtractionJob.schema_type == SchemaType(schema_type),
            ExtractionJob.status == JobStatus.completed,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: UUID,
        status: str,
        *,
        error_message: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[ExtractionJob]:
        job = await self.get(job_id)
        if job is None:
            return None
        new_status = JobStatus(status)
        job.status = new_status
        if error_message:
            job.error_message = error_message
        if input_tokens is not None:
            job.input_tokens = input_tokens
        if output_tokens is not None:
            job.output_tokens = output_tokens
        if duration_ms is not None:
            job.duration_ms = duration_ms
        if new_status in (JobStatus.completed, JobStatus.failed, JobStatus.cached):
            job.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return job
