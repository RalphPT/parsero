"""Repository for usage logs (token tracking for billing)."""
from uuid import UUID
from decimal import Decimal
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.usage_log import UsageLog


class UsageLogRepository:
    """Track token usage and costs for billing."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_extraction(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        billing_period: str,  # YYYY-MM
    ) -> UsageLog:
        """Log usage from an extraction job."""
        usage = UsageLog(
            tenant_id=tenant_id,
            job_id=job_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            billing_period=billing_period,
        )
        self.db.add(usage)
        await self.db.flush()
        return usage
