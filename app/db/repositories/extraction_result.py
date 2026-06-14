from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.extraction_result import ExtractionResult


class ExtractionResultRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        job_id: UUID,
        extracted_data: dict,
    ) -> ExtractionResult:
        result = ExtractionResult(
            job_id=job_id,
            data=extracted_data,
        )
        self.db.add(result)
        await self.db.flush()
        return result

    async def get_by_job_id(self, job_id: UUID) -> Optional[ExtractionResult]:
        stmt = select(ExtractionResult).where(ExtractionResult.job_id == job_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
